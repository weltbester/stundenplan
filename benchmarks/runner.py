"""Führt einen einzelnen Benchmark-Lauf aus und misst ihn.

Messwerte stammen aus einer dünnen Unterklasse (Ende des
Modellaufbaus), aus den Log-Meldungen des Solvers (Warm-Start-Zeit,
Zeitpunkt der ersten Lösung, Verlauf des Zielfunktionswerts) und aus
`search_limit_seconds` (Zeit, die der Suche nach Aufbau und Warm-Start
blieb).

Ist die Unterrichtsverteilung unvollständig, läuft wie bei
`main.py solve` zuerst Stufe 1 (`solver/distribution.py`); ihre Zeit
geht vom Zeitlimit ab und zählt in alle Gesamtzeiten.
"""

import logging
import re
import time
from collections import Counter
from contextlib import contextmanager
from typing import Iterator, Optional

from pydantic import BaseModel

from analysis.quality_report import QualityAnalyzer
from analysis.solution_validator import SolutionValidator
from models.school_data import SchoolData
from solver.distribution import (
    DistributionError, distribute_teachers, distribution_time_limit,
    is_distribution_complete, timetable_time_limit,
)
from solver.scheduler import ScheduleSolution, ScheduleSolver

SOLVER_LOGGER_NAME = "solver.scheduler"
SOLVED_STATUSES = ("OPTIMAL", "FEASIBLE")
# Status eines Laufs, dessen Stufe 1 keine Verteilung fand.
DISTRIBUTION_FAILED = "DISTRIBUTION_FAILED"
# Anteil des Zeitlimits am Ende, in dem die Lösung "ausgereift" sein soll.
LATE_WINDOW_FRACTION = 0.2
# Ab so vielen Stunden desselben Fachs pro Klasse und Tag gilt es als Häufung.
BUNCH_THRESHOLD = 3
PERCENT = 100.0

_SOLUTION_RE = re.compile(
    r"Lösung #\d+ \| Zeit: ([\d.]+)s \| Obj: (-?\d+)"
)
_WARMSTART_RE = re.compile(r"Warm-Start: feasible Lösung in ([\d.]+)s")

# (Sekunden seit Start der Optimierung, Zielfunktionswert)
TracePoint = tuple[float, float]


class RunResult(BaseModel):
    """Messwerte eines einzelnen Solver-Laufs."""

    dataset: str
    seed: int
    num_classes: int
    num_teachers: int
    status: str
    num_variables: int
    num_constraints: int
    build_seconds: float
    # Stufe 1 (None = Verteilung war vorgegeben)
    distribution_seconds: Optional[float] = None
    warmstart_seconds: Optional[float] = None
    # Wanduhr vom Start (inkl. Stufe 1) bis zum ersten gültigen Plan
    first_plan_seconds: Optional[float] = None
    total_seconds: float
    solutions_found: int = 0
    objective: Optional[float] = None
    late_gain_percent: Optional[float] = None
    total_gaps: Optional[int] = None
    bunched_subject_days: Optional[int] = None
    validator_errors: Optional[int] = None
    validator_warnings: Optional[int] = None

    @property
    def is_solved(self) -> bool:
        """True, wenn der Solver einen Stundenplan geliefert hat."""
        return self.status in SOLVED_STATUSES


class TimedSolver(ScheduleSolver):
    """ScheduleSolver, der das Ende des Modellaufbaus festhält."""

    def __init__(self, school_data: SchoolData) -> None:
        super().__init__(school_data)
        self.build_finished_at: Optional[float] = None

    def _add_constraints(self) -> None:
        super()._add_constraints()
        self.build_finished_at = time.perf_counter()

    @property
    def total_variables(self) -> int:
        """Alle Modellvariablen inklusive Hilfsvariablen."""
        return len(self._model.proto.variables)

    @property
    def total_constraints(self) -> int:
        """Alle Constraints des Modells."""
        return len(self._model.proto.constraints)


class SolverLogCapture(logging.Handler):
    """Liest Warm-Start-Zeit und Zielfunktionsverlauf aus dem Solver-Log."""

    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.trace: list[TracePoint] = []
        self.warmstart_seconds: Optional[float] = None
        # perf_counter() bei der ersten Meldung über eine gültige Lösung
        self.first_solution_at: Optional[float] = None

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        solution_match = _SOLUTION_RE.search(message)
        if solution_match:
            self._note_first_solution()
            elapsed, objective = solution_match.groups()
            self.trace.append((float(elapsed), float(objective)))
            return
        warmstart_match = _WARMSTART_RE.search(message)
        if warmstart_match:
            self._note_first_solution()
            self.warmstart_seconds = float(warmstart_match.group(1))

    def _note_first_solution(self) -> None:
        if self.first_solution_at is None:
            self.first_solution_at = time.perf_counter()


@contextmanager
def capture_solver_log() -> Iterator[SolverLogCapture]:
    """Hängt für die Dauer des Blocks einen Mitschnitt an den Solver-Log."""
    solver_logger = logging.getLogger(SOLVER_LOGGER_NAME)
    previous_level = solver_logger.level
    capture = SolverLogCapture()
    solver_logger.addHandler(capture)
    solver_logger.setLevel(logging.INFO)
    try:
        yield capture
    finally:
        solver_logger.removeHandler(capture)
        solver_logger.setLevel(previous_level)


def late_gain_percent(
    trace: list[TracePoint],
    search_seconds: float,
    window_fraction: float = LATE_WINDOW_FRACTION,
) -> Optional[float]:
    """Anteil der Gesamtverbesserung, der erst im Schlussfenster entstand.

    0 % = Zielfunktion war vor dem Schlussfenster bereits ausgereift.
    Hohe Werte = der Solver verbesserte bis zuletzt, das Zeitlimit schnitt
    die Optimierung ab. None, wenn weniger als zwei Lösungen vorliegen.
    `search_seconds` ist die Zeit, die der Suche zur Verfügung stand
    (Zeitlimit abzüglich Modellaufbau und Warm-Start).
    """
    if len(trace) < 2:
        return None
    first_objective = trace[0][1]
    final_objective = trace[-1][1]
    total_gain = first_objective - final_objective
    if total_gain <= 0:
        return 0.0
    cutoff = search_seconds * (1.0 - window_fraction)
    before_window = [obj for elapsed, obj in trace if elapsed <= cutoff]
    if not before_window:
        return PERCENT
    late_gain = before_window[-1] - final_objective
    return round(PERCENT * late_gain / total_gain, 1)


def count_bunched_subject_days(
    solution: ScheduleSolution, threshold: int = BUNCH_THRESHOLD
) -> int:
    """Zählt (Klasse, Fach, Tag) mit mindestens `threshold` Stunden.

    Kopplungsstunden werden nicht gezählt (mehrere Gruppen parallel).
    """
    lessons_per_day = Counter(
        (entry.class_id, entry.subject, entry.day)
        for entry in solution.entries
        if not entry.is_coupling
    )
    return sum(1 for count in lessons_per_day.values() if count >= threshold)


def run_once(
    dataset: str, seed: int, data: SchoolData, time_limit: int
) -> RunResult:
    """Löst `data` einmal mit Soft-Constraints und liefert die Messwerte.

    Fehlt ein Teil der Unterrichtsverteilung, läuft vorher Stufe 1.
    """
    data.config.solver.time_limit_seconds = time_limit
    distribution_seconds: Optional[float] = None
    if not is_distribution_complete(data):
        started_at = time.perf_counter()
        try:
            data, distribution_seconds = _run_distribution(data, time_limit)
        except DistributionError:
            elapsed = round(time.perf_counter() - started_at, 1)
            return _distribution_failed(dataset, seed, data, elapsed)
    return _solve_timetable(dataset, seed, data, distribution_seconds)


def _run_distribution(
    data: SchoolData, time_limit: int
) -> tuple[SchoolData, float]:
    """Stufe 1 wie bei `main.py solve`; gibt Daten und Dauer zurück."""
    result = distribute_teachers(
        data,
        distribution_time_limit(time_limit),
        num_workers=data.config.solver.num_workers,
    )
    solved = result.data
    solved.config.solver.time_limit_seconds = timetable_time_limit(
        time_limit, result.seconds
    )
    return solved, round(result.seconds, 1)


def _distribution_failed(
    dataset: str, seed: int, data: SchoolData, seconds: float
) -> RunResult:
    """Messwerte eines Laufs, dessen Stufe 1 scheiterte."""
    return RunResult(
        dataset=dataset,
        seed=seed,
        num_classes=len(data.classes),
        num_teachers=len(data.teachers),
        status=DISTRIBUTION_FAILED,
        num_variables=0,
        num_constraints=0,
        build_seconds=0.0,
        distribution_seconds=seconds,
        total_seconds=seconds,
    )


def _solve_timetable(
    dataset: str,
    seed: int,
    data: SchoolData,
    distribution_seconds: Optional[float],
) -> RunResult:
    """Stundenplan-Solver mit dem Zeitlimit aus `data`; misst den Lauf."""
    time_limit = data.config.solver.time_limit_seconds
    solver = TimedSolver(data)
    offset = distribution_seconds or 0.0

    with capture_solver_log() as capture:
        started_at = time.perf_counter()
        solution = solver.solve()

    build_seconds = (solver.build_finished_at or started_at) - started_at
    first_plan: Optional[float] = None
    if capture.first_solution_at is not None:
        first_plan = round(offset + capture.first_solution_at - started_at, 1)
    result = RunResult(
        dataset=dataset,
        seed=seed,
        num_classes=len(data.classes),
        num_teachers=len(data.teachers),
        status=solution.solver_status,
        num_variables=solver.total_variables,
        num_constraints=solver.total_constraints,
        build_seconds=round(build_seconds, 1),
        distribution_seconds=distribution_seconds,
        warmstart_seconds=capture.warmstart_seconds,
        first_plan_seconds=first_plan,
        total_seconds=round(offset + solution.solve_time_seconds, 1),
        solutions_found=len(capture.trace),
    )
    if not result.is_solved:
        return result

    validation = SolutionValidator().validate(solution, data)
    quality = QualityAnalyzer().analyze(solution, data)
    severities = Counter(v.severity for v in validation.violations)
    return result.model_copy(update={
        "objective": solution.objective_value,
        "late_gain_percent": late_gain_percent(
            capture.trace, solver.search_limit_seconds or time_limit
        ),
        "total_gaps": quality.total_gaps,
        "bunched_subject_days": count_bunched_subject_days(solution),
        "validator_errors": severities["error"],
        "validator_warnings": severities["warning"],
    })
