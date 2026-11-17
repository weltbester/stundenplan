"""Stufe 1 der Planung: die Unterrichtsverteilung.

Ein kleines CP-SAT-Modell ohne Zeitdimension entscheidet, welche
Lehrkraft welches Fach in welcher Klasse und welche Kopplungsgruppe
übernimmt. Bereits vorgegebene Zuweisungen bleiben erhalten; offen
gebliebene werden so verteilt, dass jede Lehrkraft möglichst nah an
ihrem Soll-Deputat liegt. Der Stundenplan (Stufe 2) wird danach mit
dieser Verteilung gerechnet.
"""

import time
from typing import Optional

from ortools.sat.python import cp_model
from pydantic import BaseModel

from models.coupling import Coupling
from models.fixed_assignment import (
    FixedAssignment, coupling_subjects_by_class,
)
from models.school_data import SchoolData
from models.teacher import (
    HALF_LESSONS_PER_LESSON, Teacher, format_hours_delta,
)
from solver.pinning import PinnedLesson

SOLVED_STATUSES = (cp_model.OPTIMAL, cp_model.FEASIBLE)
# Stufe 1 bekommt diesen Anteil des Zeitlimits, höchstens aber …
DISTRIBUTION_TIME_SHARE = 0.2
# … so viele Sekunden und mindestens so viele.
DISTRIBUTION_MAX_SECONDS = 60.0
DISTRIBUTION_MIN_SECONDS = 5.0

ClassSubject = tuple[str, str]            # (Klasse, Fach)
ClassSubjectKey = tuple[str, str, str]    # (Lehrkraft, Klasse, Fach)
GroupKey = tuple[str, int, str]           # (Kopplung, Gruppenindex, Lehrkraft)


class DistributionError(RuntimeError):
    """Für den Datensatz wurde keine Unterrichtsverteilung gefunden."""


class DistributionResult(BaseModel):
    """Ergebnis der Stufe 1."""

    data: SchoolData          # Kopie mit vollständiger Verteilung
    status: str               # OPTIMAL oder FEASIBLE
    seconds: float
    decided_assignments: int  # neu entschiedene Klasse-Fach-Zuweisungen
    decided_groups: int       # neu besetzte Kopplungsgruppen
    # Lehrkraft → Wochenstunden laut Verteilung
    hours_by_teacher: dict[str, int]


def open_class_subjects(data: SchoolData) -> list[ClassSubject]:
    """Klasse-Fach-Paare außerhalb von Kopplungen ohne feste Lehrkraft."""
    covered = coupling_subjects_by_class(data.couplings)
    fixed = {(a.class_id, a.subject) for a in data.fixed_assignments}
    return [
        (school_class.id, subject)
        for school_class in data.classes
        for subject, hours in school_class.curriculum.items()
        if hours > 0
        and subject not in covered.get(school_class.id, set())
        and (school_class.id, subject) not in fixed
    ]


def open_coupling_groups(data: SchoolData) -> list[tuple[str, int]]:
    """Kopplungsgruppen (Kopplung, Gruppenindex) ohne feste Lehrkraft."""
    return [
        (coupling.id, index)
        for coupling in data.couplings
        for index, group in enumerate(coupling.groups)
        if not group.teacher_id
    ]


def is_distribution_complete(data: SchoolData) -> bool:
    """True, wenn es für Stufe 1 nichts mehr zu entscheiden gibt."""
    return not open_class_subjects(data) and not open_coupling_groups(data)


def distribution_time_limit(total_seconds: float) -> float:
    """Zeitlimit der Stufe 1 als Teil des gesamten Zeitlimits."""
    share = total_seconds * DISTRIBUTION_TIME_SHARE
    return max(
        DISTRIBUTION_MIN_SECONDS, min(DISTRIBUTION_MAX_SECONDS, share)
    )


def forced_by_pins(
    pins: list[PinnedLesson], data: SchoolData
) -> dict[ClassSubject, str]:
    """Klasse-Fach-Paare, deren Lehrkraft durch gepinnte Stunden feststeht.

    Gepinnte Kopplungsstunden bleiben außen vor: dort entscheidet die
    Gruppe, nicht das Klasse-Fach-Paar.
    """
    covered = coupling_subjects_by_class(data.couplings)
    return {
        (pin.class_id, pin.subject): pin.teacher_id
        for pin in pins
        if pin.subject not in covered.get(pin.class_id, set())
    }


class _DistributionModel:
    """Baut das Zuweisungsmodell für einen Datensatz auf."""

    def __init__(
        self, data: SchoolData, forced: dict[ClassSubject, str]
    ) -> None:
        self.data = data
        self.model = cp_model.CpModel()
        self._teacher_by_id = {t.id: t for t in data.teachers}
        self._teachers_by_subject: dict[str, list[Teacher]] = {}
        for teacher in data.teachers:
            for subject in teacher.subjects:
                self._teachers_by_subject.setdefault(
                    subject, []
                ).append(teacher)
        self._given: dict[ClassSubject, str] = dict(forced)
        self._given.update({
            (a.class_id, a.subject): a.teacher_id
            for a in data.fixed_assignments
        })
        self.class_vars: dict[ClassSubjectKey, cp_model.IntVar] = {}
        self.group_vars: dict[GroupKey, cp_model.IntVar] = {}
        self.loads: dict[str, cp_model.LinearExprT] = {}

        self._add_class_subject_vars()
        self._add_coupling_group_vars()
        self._add_deputat_bounds()

    def _candidates(
        self, subject: str, given_teacher: Optional[str]
    ) -> list[Teacher]:
        """Die vorgegebene Lehrkraft (auch fachfremd), sonst alle mit Fach."""
        if not given_teacher:
            return self._teachers_by_subject.get(subject, [])
        teacher = self._teacher_by_id.get(given_teacher)
        if teacher is None:
            raise DistributionError(
                f"Unbekanntes Kürzel '{given_teacher}' in der "
                f"vorgegebenen Unterrichtsverteilung."
            )
        return [teacher]

    def _add_class_subject_vars(self) -> None:
        """Genau eine Lehrkraft je (Klasse, Fach) außerhalb von Kopplungen."""
        covered = coupling_subjects_by_class(self.data.couplings)
        for school_class in self.data.classes:
            class_covered = covered.get(school_class.id, set())
            for subject, hours in school_class.curriculum.items():
                if hours <= 0 or subject in class_covered:
                    continue
                given = self._given.get((school_class.id, subject))
                candidates = []
                for teacher in self._candidates(subject, given):
                    var = self.model.new_bool_var(
                        f"a_{teacher.id}_{school_class.id}_{subject}"
                    )
                    key = (teacher.id, school_class.id, subject)
                    self.class_vars[key] = var
                    candidates.append(var)
                if candidates:
                    self.model.add_exactly_one(candidates)

    def _add_coupling_group_vars(self) -> None:
        """Genau eine Lehrkraft je Gruppe; keine Lehrkraft in zwei Gruppen
        derselben Kopplung (die Gruppen laufen gleichzeitig)."""
        for coupling in self.data.couplings:
            by_teacher: dict[str, list[cp_model.IntVar]] = {}
            for index, group in enumerate(coupling.groups):
                candidates = []
                for teacher in self._candidates(
                    group.subject, group.teacher_id
                ):
                    var = self.model.new_bool_var(
                        f"g_{coupling.id}_{index}_{teacher.id}"
                    )
                    self.group_vars[(coupling.id, index, teacher.id)] = var
                    by_teacher.setdefault(teacher.id, []).append(var)
                    candidates.append(var)
                if candidates:
                    self.model.add_exactly_one(candidates)
            for teacher_vars in by_teacher.values():
                self.model.add_at_most_one(teacher_vars)

    def _add_deputat_bounds(self) -> None:
        """Deputat-Min ≤ Stunden ≤ min(Deputat-Max, unterrichtbare Stunden)."""
        time_grid = self.data.config.time_grid
        hours_of = {
            (school_class.id, subject): hours
            for school_class in self.data.classes
            for subject, hours in school_class.curriculum.items()
        }
        coupling_by_id = {c.id: c for c in self.data.couplings}

        terms: dict[str, list] = {t.id: [] for t in self.data.teachers}
        for (teacher_id, class_id, subject), var in self.class_vars.items():
            terms[teacher_id].append(var * hours_of[(class_id, subject)])
        for (coupling_id, index, teacher_id), var in self.group_vars.items():
            group = coupling_by_id[coupling_id].groups[index]
            terms[teacher_id].append(var * group.hours_per_week)

        for teacher in self.data.teachers:
            upper = min(
                teacher.deputat_max,
                teacher.teachable_hours(
                    time_grid.days_per_week, time_grid.sek1_max_slot
                ),
            )
            load = sum(terms[teacher.id])
            self.loads[teacher.id] = load
            self.model.add(load >= teacher.deputat_min)
            self.model.add(load <= upper)

    def add_target_objective(self) -> None:
        """Minimiert die quadrierten Abstände vom Soll (halbe Stunden)."""
        max_buffer = self.data.config.teachers.deputat_max_buffer
        penalties = []
        for teacher in self.data.teachers:
            target = teacher.target_half_lessons(max_buffer)
            limit = max(
                target, HALF_LESSONS_PER_LESSON * teacher.deputat_max
            )
            diff = self.model.new_int_var(
                -limit, limit, f"diff_{teacher.id}"
            )
            self.model.add(
                diff
                == HALF_LESSONS_PER_LESSON * self.loads[teacher.id] - target
            )
            squared = self.model.new_int_var(
                0, limit * limit, f"sq_{teacher.id}"
            )
            self.model.add_multiplication_equality(squared, [diff, diff])
            penalties.append(squared)
        self.model.minimize(sum(penalties))


def _couplings_with_teachers(
    couplings: list[Coupling], chosen: dict[tuple[str, int], str]
) -> list[Coupling]:
    """Kopien der Kopplungen mit den gewählten Lehrkräften je Gruppe."""
    result: list[Coupling] = []
    for coupling in couplings:
        groups = [
            group.model_copy(update={
                "teacher_id": chosen.get((coupling.id, index)),
            })
            for index, group in enumerate(coupling.groups)
        ]
        result.append(coupling.model_copy(update={"groups": groups}))
    return result


def distribute_teachers(
    data: SchoolData,
    time_limit_seconds: float,
    balance_targets: bool = True,
    seed: Optional[int] = None,
    num_workers: int = 0,
    forced: Optional[dict[ClassSubject, str]] = None,
) -> DistributionResult:
    """Ergänzt `data` zu einer vollständigen Unterrichtsverteilung.

    Vorgaben in `data` (feste Zuweisungen, Lehrkräfte von
    Kopplungsgruppen) und in `forced` (z.B. aus gepinnten Stunden)
    bleiben erhalten. Mit `balance_targets` wird der Abstand vom
    Soll-Deputat minimiert; ohne entsteht irgendeine gültige Verteilung.
    `num_workers=0` nutzt alle Kerne.

    Raises:
        DistributionError: wenn keine gültige Verteilung existiert oder
            im Zeitlimit keine gefunden wurde.
    """
    open_assignments = len(open_class_subjects(data))
    open_groups = len(open_coupling_groups(data))
    builder = _DistributionModel(data, forced or {})
    if balance_targets:
        builder.add_target_objective()

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    if num_workers > 0:
        solver.parameters.num_workers = num_workers
    if seed is not None:
        solver.parameters.random_seed = seed
    started_at = time.monotonic()
    status = solver.solve(builder.model)
    seconds = time.monotonic() - started_at
    if status not in SOLVED_STATUSES:
        raise DistributionError(
            f"Keine Unterrichtsverteilung gefunden "
            f"(Status {solver.status_name(status)})."
        )

    fixed = [
        FixedAssignment(class_id=c, subject=s, teacher_id=t)
        for (t, c, s), var in builder.class_vars.items()
        if solver.value(var)
    ]
    chosen_groups = {
        (coupling_id, index): teacher_id
        for (coupling_id, index, teacher_id), var
        in builder.group_vars.items()
        if solver.value(var)
    }
    distributed = data.model_copy(update={
        "fixed_assignments": fixed,
        "couplings": _couplings_with_teachers(data.couplings, chosen_groups),
    })
    return DistributionResult(
        data=distributed,
        status=solver.status_name(status),
        seconds=seconds,
        decided_assignments=open_assignments,
        decided_groups=open_groups,
        hours_by_teacher={
            teacher.id: solver.value(builder.loads[teacher.id])
            for teacher in data.teachers
        },
    )


def describe_distribution(result: DistributionResult) -> str:
    """Einzeilige Zusammenfassung der Stufe 1 für die Ausgabe."""
    data = result.data
    max_buffer = data.config.teachers.deputat_max_buffer
    deviations = [
        result.hours_by_teacher[teacher.id]
        - teacher.target_hours(max_buffer)
        for teacher in data.teachers
    ]
    at_lower_bound = sum(
        result.hours_by_teacher[teacher.id] <= teacher.deputat_min
        for teacher in data.teachers
    )
    return (
        f"{result.decided_assignments} Klasse-Fach-Zuweisungen und "
        f"{result.decided_groups} Kopplungsgruppen entschieden "
        f"({result.seconds:.1f}s, {result.status}). Abweichung vom Soll: "
        f"{format_hours_delta(min(deviations))} bis "
        f"{format_hours_delta(max(deviations))} Stunden, "
        f"{at_lower_bound} von {len(data.teachers)} Lehrkräften an der "
        f"Untergrenze."
    )
