"""Führt einen einzelnen Benchmark-Lauf aus und misst ihn.

Der Solver wird nicht verändert: Messwerte stammen aus einer dünnen
Unterklasse (Ende des Modellaufbaus) und aus den Log-Meldungen des
Solvers (Warm-Start-Zeit, Verlauf des Zielfunktionswerts).
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
from solver.scheduler import ScheduleSolution, ScheduleSolver

SOLVER_LOGGER_NAME = "solver.scheduler"
SOLVED_STATUSES = ("OPTIMAL", "FEASIBLE")
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
    warmstart_seconds: Optional[float] = None
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

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        solution_match = _SOLUTION_RE.search(message)
        if solution_match:
            elapsed, objective = solution_match.groups()
            self.trace.append((float(elapsed), float(objective)))
            return
        warmstart_match = _WARMSTART_RE.search(message)
        if warmstart_match:
            self.warmstart_seconds = float(warmstart_match.group(1))


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
    time_limit: float,
    window_fraction: float = LATE_WINDOW_FRACTION,
) -> Optional[float]:
    """Anteil der Gesamtverbesserung, der erst im Schlussfenster entstand.

    0 % = Zielfunktion war vor dem Schlussfenster bereits ausgereift.
    Hohe Werte = der Solver verbesserte bis zuletzt, das Zeitlimit schnitt
    die Optimierung ab. None, wenn weniger als zwei Lösungen vorliegen.
    """
    if len(trace) < 2:
        return None
    first_objective = trace[0][1]
    final_objective = trace[-1][1]
    total_gain = first_objective - final_objective
    if total_gain <= 0:
        return 0.0
    cutoff = time_limit * (1.0 - window_fraction)
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
    """Löst `data` einmal mit Soft-Constraints und liefert die Messwerte."""
    data.config.solver.time_limit_seconds = time_limit
    solver = TimedSolver(data)

    with capture_solver_log() as capture:
        started_at = time.perf_counter()
        solution = solver.solve()

    build_seconds = (solver.build_finished_at or started_at) - started_at
    result = RunResult(
        dataset=dataset,
        seed=seed,
        num_classes=len(data.classes),
        num_teachers=len(data.teachers),
        status=solution.solver_status,
        num_variables=solver.total_variables,
        num_constraints=solver.total_constraints,
        build_seconds=round(build_seconds, 1),
        warmstart_seconds=capture.warmstart_seconds,
        total_seconds=round(solution.solve_time_seconds, 1),
        solutions_found=len(capture.trace),
    )
    if not result.is_solved:
        return result

    validation = SolutionValidator().validate(solution, data)
    quality = QualityAnalyzer().analyze(solution, data)
    severities = Counter(v.severity for v in validation.violations)
    return result.model_copy(update={
        "objective": solution.objective_value,
        "late_gain_percent": late_gain_percent(capture.trace, time_limit),
        "total_gaps": quality.total_gaps,
        "bunched_subject_days": count_bunched_subject_days(solution),
        "validator_errors": severities["error"],
        "validator_warnings": severities["warning"],
    })
