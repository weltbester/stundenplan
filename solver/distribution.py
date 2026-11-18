"""Stufe 1 der Planung: die Unterrichtsverteilung.

Ein kleines CP-SAT-Modell ohne Zeitdimension entscheidet, welche
Lehrkraft welches Fach in welcher Klasse und welche Kopplungsgruppe
übernimmt. Bereits vorgegebene Zuweisungen bleiben erhalten; offen
gebliebene werden so verteilt, dass jede Lehrkraft möglichst nah an
ihrem Soll-Deputat liegt. Der Stundenplan (Stufe 2) wird danach mit
dieser Verteilung gerechnet.

Das Modell kennt keine Stundenzeiten, prüft aber zwei notwendige
Bedingungen aus den Sperrzeiten, ohne die Stufe 2 sicher scheitert:
- Tagesbeginn: Jede Klasse hat an jedem Tag die Stunden 1..k (C10, k
  aus ihren Wochenstunden). In jeder dieser Stunden ist mindestens eine
  ihrer Lehrkräfte frei, oder eine ihrer Kopplungen, deren gewählte
  Lehrkräfte alle frei sind.
- Kopplungen: Die gewählten Lehrkräfte einer Kopplung haben genug
  gemeinsame freie Stunden, mit C15 verteilt auf genug Tage (je Tag
  eine Stunde oder ein Doppelblock).
- Kopplungsplan: Die Stunden aller Kopplungen bekommen Zeiten, in denen
  ihre gewählten Lehrkräfte frei sind, mit C15, ohne dass eine
  Lehrkraft oder Klasse zwei Kopplungen zugleich hat. Reguläre Stunden
  bekommen hier keine Zeiten.
"""

import time
from itertools import product
from typing import Optional

from ortools.sat.python import cp_model
from pydantic import BaseModel

from config.schema import TimeGridConfig
from models.attendance_check import (
    lessons_every_day, sek1_slot_numbers, weekly_lessons,
)
from models.coupling import Coupling
from models.fixed_assignment import (
    FixedAssignment, coupling_subjects_by_class,
)
from models.school_data import SchoolData
from models.teacher import (
    HALF_LESSONS_PER_LESSON, Teacher, format_hours_delta,
)
from solver.day_limit import day_conflict_cliques
from solver.pinning import PinnedLesson

SOLVED_STATUSES = (cp_model.OPTIMAL, cp_model.FEASIBLE)
# Stufe 1 bekommt diesen Anteil des Zeitlimits, höchstens aber …
DISTRIBUTION_TIME_SHARE = 0.2
# … so viele Sekunden und mindestens so viele.
DISTRIBUTION_MAX_SECONDS = 60.0
DISTRIBUTION_MIN_SECONDS = 5.0
# Dem Stundenplan-Solver bleibt nach Stufe 1 mindestens so viel Zeit.
MIN_TIMETABLE_SECONDS = 10

ClassSubject = tuple[str, str]            # (Klasse, Fach)
ClassSubjectKey = tuple[str, str, str]    # (Lehrkraft, Klasse, Fach)
GroupKey = tuple[str, int, str]           # (Kopplung, Gruppenindex, Lehrkraft)
Slot = tuple[int, int]                    # (Tag, Stunde)
CouplingSlotKey = tuple[str, int, int]    # (Kopplung, Tag, Stunde)


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


def timetable_time_limit(total_seconds: float, used_seconds: float) -> int:
    """Zeitlimit des Stundenplan-Solvers nach Stufe 1 (ganze Sekunden).

    Stufe 1 hat `used_seconds` vom Gesamtlimit verbraucht; der Rest,
    mindestens `MIN_TIMETABLE_SECONDS`, bleibt für den Stundenplan.
    """
    return max(MIN_TIMETABLE_SECONDS, round(total_seconds - used_seconds))


def double_block_pairs(time_grid: TimeGridConfig) -> list[Slot]:
    """Doppelblöcke (erste, zweite Stunde), die ganz im Sek-I-Raster liegen."""
    slot_numbers = set(sek1_slot_numbers(time_grid))
    return [
        (block.slot_first, block.slot_second)
        for block in time_grid.double_blocks
        if {block.slot_first, block.slot_second} <= slot_numbers
    ]


def weekly_class_lessons(data: SchoolData) -> dict[str, int]:
    """Klasse → Wochenstunden, die der Stundenplan für sie einplant."""
    return weekly_lessons(data.classes, data.couplings)


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
        # 1, wenn alle gewählten Lehrkräfte der Kopplung frei sind
        self.coupling_free: dict[CouplingSlotKey, cp_model.IntVar] = {}
        # 1, wenn die Kopplung im Kopplungsplan in dieser Stunde liegt
        self.coupling_lessons: dict[CouplingSlotKey, cp_model.IntVar] = {}

        time_grid = data.config.time_grid
        self._slot_numbers = sek1_slot_numbers(time_grid)
        self._slots: list[Slot] = list(
            product(range(time_grid.days_per_week), self._slot_numbers)
        )
        self._blocked_at: dict[Slot, set[str]] = {
            slot: set() for slot in self._slots
        }
        for teacher in data.teachers:
            for slot in teacher.unavailable_slots:
                if tuple(slot) in self._blocked_at:
                    self._blocked_at[tuple(slot)].add(teacher.id)

        self._add_class_subject_vars()
        self._add_coupling_group_vars()
        self._add_deputat_bounds()
        self._add_coupling_free_vars()
        self._add_class_day_start()
        self._add_coupling_capacity()
        self._add_coupling_timetable()

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

    def _add_coupling_free_vars(self) -> None:
        """coupling_free[k, Tag, Stunde] → keine gewählte Lehrkraft ist
        in dieser Stunde gesperrt."""
        candidates: dict[str, list[tuple[str, cp_model.IntVar]]] = {}
        for (coupling_id, _, teacher_id), var in self.group_vars.items():
            candidates.setdefault(coupling_id, []).append((teacher_id, var))
        for coupling in self.data.couplings:
            for day, hour in self._slots:
                free = self.model.new_bool_var(
                    f"free_{coupling.id}_{day}_{hour}"
                )
                blocked = self._blocked_at[(day, hour)]
                for teacher_id, var in candidates.get(coupling.id, []):
                    if teacher_id in blocked:
                        self.model.add_implication(free, var.negated())
                self.coupling_free[(coupling.id, day, hour)] = free

    def _add_class_day_start(self) -> None:
        """In den Stunden 1..k jedes Tages kann die Klasse Unterricht haben.

        k aus `lessons_every_day`. Ist keine Lehrkraft der Klasse frei und
        keine ihrer Kopplungen möglich, scheitert Stufe 2 an C10.
        """
        time_grid = self.data.config.time_grid
        weekly = weekly_class_lessons(self.data)
        teacher_vars: dict[str, list[tuple[str, cp_model.IntVar]]] = {}
        for (teacher_id, class_id, _), var in self.class_vars.items():
            teacher_vars.setdefault(class_id, []).append((teacher_id, var))
        couplings_of: dict[str, list[str]] = {}
        for coupling in self.data.couplings:
            for class_id in coupling.involved_class_ids:
                couplings_of.setdefault(class_id, []).append(coupling.id)

        for school_class in self.data.classes:
            first = lessons_every_day(
                weekly[school_class.id],
                time_grid.days_per_week,
                len(self._slot_numbers),
            )
            starts = product(
                range(time_grid.days_per_week), self._slot_numbers[:first]
            )
            for day, hour in starts:
                blocked = self._blocked_at[(day, hour)]
                options = [
                    var
                    for teacher_id, var in teacher_vars.get(
                        school_class.id, []
                    )
                    if teacher_id not in blocked
                ] + [
                    self.coupling_free[(coupling_id, day, hour)]
                    for coupling_id in couplings_of.get(school_class.id, [])
                ]
                self.model.add_bool_or(options)

    def _add_coupling_capacity(self) -> None:
        """Genug gemeinsame freie Stunden für die Stunden jeder Kopplung.

        Ohne C15 zählt jede freie Stunde. Mit C15 liegt je Tag eine
        Stunde oder ein Doppelblock, also höchstens zwei Stunden.
        """
        time_grid = self.data.config.time_grid
        day_limit = self.data.config.solver.subject_day_limit
        pairs = double_block_pairs(time_grid)
        for coupling in self.data.couplings:
            if day_limit:
                capacity = sum(
                    self._coupling_day_capacity(coupling.id, day, pairs)
                    for day in range(time_grid.days_per_week)
                )
            else:
                capacity = sum(
                    self.coupling_free[(coupling.id, day, hour)]
                    for day, hour in self._slots
                )
            self.model.add(capacity >= coupling.hours_per_week)

    def _coupling_day_capacity(
        self, coupling_id: str, day: int, pairs: list[Slot]
    ) -> cp_model.LinearExprT:
        """Stunden der Kopplung an einem Tag mit C15: 0, 1 oder 2.

        Eine Stunde, wenn eine Stunde frei ist; eine zweite nur, wenn
        beide Stunden eines Doppelblocks frei sind.
        """
        single = self.model.new_bool_var(f"single_{coupling_id}_{day}")
        self.model.add_bool_or([
            self.coupling_free[(coupling_id, day, hour)]
            for hour in self._slot_numbers
        ]).only_enforce_if(single)
        if not pairs:
            return single

        double = self.model.new_bool_var(f"double_{coupling_id}_{day}")
        both_free = []
        for first, second in pairs:
            both = self.model.new_bool_var(
                f"both_{coupling_id}_{day}_{first}"
            )
            for hour in (first, second):
                self.model.add_implication(
                    both, self.coupling_free[(coupling_id, day, hour)]
                )
            both_free.append(both)
        self.model.add_bool_or(both_free).only_enforce_if(double)
        return single + double

    def _add_coupling_timetable(self) -> None:
        """Ein Plan nur für die Kopplungsstunden, mit den Regeln aus Stufe 2.

        Ohne ihn wählt Stufe 1 Lehrkräfte, deren Kopplungen einzeln in
        die freien Stunden passen, zusammen aber nicht (z.B. eine
        Lehrkraft in drei Kopplungen mit wenigen gemeinsamen Stunden).
        """
        self._add_coupling_lesson_vars()
        if self.data.config.solver.subject_day_limit:
            self._add_coupling_day_limit()
        self._add_coupling_class_overlap()
        self._add_coupling_teacher_overlap()

    def _add_coupling_lesson_vars(self) -> None:
        """Wochenstunden je Kopplung, nur wo ihre Lehrkräfte frei sind."""
        for coupling in self.data.couplings:
            lessons = []
            for day, hour in self._slots:
                key = (coupling.id, day, hour)
                lesson = self.model.new_bool_var(
                    f"lesson_{coupling.id}_{day}_{hour}"
                )
                self.model.add_implication(lesson, self.coupling_free[key])
                self.coupling_lessons[key] = lesson
                lessons.append(lesson)
            self.model.add(sum(lessons) == coupling.hours_per_week)

    def _add_coupling_day_limit(self) -> None:
        """C15: je Kopplung und Tag eine Stunde oder ein Doppelblock."""
        cliques = day_conflict_cliques(self.data.config.time_grid)
        days = range(self.data.config.time_grid.days_per_week)
        for coupling, day, clique in product(
            self.data.couplings, days, cliques
        ):
            self.model.add_at_most_one(
                self.coupling_lessons[(coupling.id, day, hour)]
                for hour in clique
            )

    def _add_coupling_class_overlap(self) -> None:
        """Keine Klasse in zwei Kopplungen zur selben Stunde."""
        couplings_of: dict[str, list[str]] = {}
        for coupling in self.data.couplings:
            for class_id in coupling.involved_class_ids:
                couplings_of.setdefault(class_id, []).append(coupling.id)
        for coupling_ids in couplings_of.values():
            if len(coupling_ids) < 2:
                continue
            for day, hour in self._slots:
                self.model.add_at_most_one(
                    self.coupling_lessons[(coupling_id, day, hour)]
                    for coupling_id in coupling_ids
                )

    def _add_coupling_teacher_overlap(self) -> None:
        """Keine Lehrkraft in zwei Kopplungen zur selben Stunde.

        Nur für Lehrkräfte, die für mehrere Kopplungen in Frage kommen;
        in gesperrten Stunden verbietet das schon `coupling_free`.
        """
        groups_of: dict[str, dict[str, list[cp_model.IntVar]]] = {}
        for (coupling_id, _, teacher_id), var in self.group_vars.items():
            groups_of.setdefault(teacher_id, {}).setdefault(
                coupling_id, []
            ).append(var)
        for teacher_id, by_coupling in groups_of.items():
            if len(by_coupling) < 2:
                continue
            for day, hour in self._slots:
                if teacher_id in self._blocked_at[(day, hour)]:
                    continue
                self.model.add_at_most_one(
                    self._teacher_busy(group_vars, (coupling_id, day, hour))
                    for coupling_id, group_vars in by_coupling.items()
                )

    def _teacher_busy(
        self, group_vars: list[cp_model.IntVar], key: CouplingSlotKey
    ) -> cp_model.IntVar:
        """1, wenn die Lehrkraft (eine ihrer Gruppen) in der Stunde
        `key` die Kopplung unterrichtet."""
        lesson = self.coupling_lessons[key]
        busy = self.model.new_bool_var(f"busy_{key[0]}_{key[1]}_{key[2]}")
        for group in group_vars:
            self.model.add_bool_or([group.negated(), lesson.negated(), busy])
        return busy

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
            f"(Status {solver.status_name(status)}). Mögliche Gründe: "
            f"Deputatgrenzen, fehlende Fachlehrkräfte, Sperrzeiten, "
            f"in denen eine Klasse oder Kopplung keine freie Lehrkraft "
            f"hat, oder Kopplungen, die zusammen nicht in die freien "
            f"Stunden ihrer Lehrkräfte und Klassen passen."
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
