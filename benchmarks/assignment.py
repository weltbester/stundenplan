"""Erzeugt eine vollständige Unterrichtsverteilung für Benchmark-Daten.

Echte Schulen legen die Verteilung vor der Stundenplanung fest. Für
generierte Testdaten übernimmt das hier ein kleines CP-SAT-Modell ohne
Zeitdimension: jede Klasse-Fach-Kombination und jede Kopplungsgruppe
bekommt genau eine Lehrkraft, die Deputate bleiben in ihren Grenzen.
"""

from ortools.sat.python import cp_model

from models.coupling import Coupling
from models.fixed_assignment import (
    FixedAssignment, coupling_subjects_by_class,
)
from models.school_data import SchoolData
from models.teacher import Teacher

ASSIGNMENT_TIME_LIMIT_SECONDS = 60
# Ein Worker + fester Seed → dieselbe Verteilung bei jedem Lauf.
ASSIGNMENT_WORKERS = 1

ClassSubjectKey = tuple[str, str, str]   # (Lehrkraft, Klasse, Fach)
GroupKey = tuple[str, int, str]          # (Kopplung, Gruppenindex, Lehrkraft)


class AssignmentError(RuntimeError):
    """Für den Datensatz wurde keine Unterrichtsverteilung gefunden."""


def assign_teachers(data: SchoolData, seed: int) -> SchoolData:
    """Kopie von `data` mit vollständig vorgegebener Unterrichtsverteilung."""
    model = cp_model.CpModel()
    teachers_by_subject = _teachers_by_subject(data.teachers)

    class_vars = _add_class_subject_vars(model, data, teachers_by_subject)
    group_vars = _add_coupling_group_vars(model, data, teachers_by_subject)
    _add_deputat_bounds(model, data, class_vars, group_vars)

    solver = cp_model.CpSolver()
    solver.parameters.random_seed = seed
    solver.parameters.num_workers = ASSIGNMENT_WORKERS
    solver.parameters.max_time_in_seconds = ASSIGNMENT_TIME_LIMIT_SECONDS
    status = solver.solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise AssignmentError(
            f"Keine Unterrichtsverteilung gefunden "
            f"(Status {solver.status_name(status)})."
        )

    fixed = [
        FixedAssignment(class_id=c, subject=s, teacher_id=t)
        for (t, c, s), var in class_vars.items()
        if solver.value(var)
    ]
    chosen_groups = {
        (coupling_id, group_index): teacher_id
        for (coupling_id, group_index, teacher_id), var in group_vars.items()
        if solver.value(var)
    }
    return data.model_copy(update={
        "fixed_assignments": fixed,
        "couplings": _couplings_with_teachers(data.couplings, chosen_groups),
    })


def _teachers_by_subject(teachers: list[Teacher]) -> dict[str, list[Teacher]]:
    by_subject: dict[str, list[Teacher]] = {}
    for teacher in teachers:
        for subject in teacher.subjects:
            by_subject.setdefault(subject, []).append(teacher)
    return by_subject


def _add_class_subject_vars(
    model: cp_model.CpModel,
    data: SchoolData,
    teachers_by_subject: dict[str, list[Teacher]],
) -> dict[ClassSubjectKey, cp_model.IntVar]:
    """Genau eine Lehrkraft je (Klasse, Fach) außerhalb von Kopplungen."""
    covered = coupling_subjects_by_class(data.couplings)
    variables: dict[ClassSubjectKey, cp_model.IntVar] = {}
    for school_class in data.classes:
        class_covered = covered.get(school_class.id, set())
        for subject, hours in school_class.curriculum.items():
            if hours <= 0 or subject in class_covered:
                continue
            candidates = [
                model.new_bool_var(f"a_{t.id}_{school_class.id}_{subject}")
                for t in teachers_by_subject.get(subject, [])
            ]
            for teacher, var in zip(
                teachers_by_subject.get(subject, []), candidates
            ):
                variables[(teacher.id, school_class.id, subject)] = var
            if candidates:
                model.add_exactly_one(candidates)
    return variables


def _add_coupling_group_vars(
    model: cp_model.CpModel,
    data: SchoolData,
    teachers_by_subject: dict[str, list[Teacher]],
) -> dict[GroupKey, cp_model.IntVar]:
    """Genau eine Lehrkraft je Gruppe; keine Lehrkraft in zwei Gruppen
    derselben Kopplung (die Gruppen laufen gleichzeitig)."""
    variables: dict[GroupKey, cp_model.IntVar] = {}
    for coupling in data.couplings:
        by_teacher: dict[str, list[cp_model.IntVar]] = {}
        for index, group in enumerate(coupling.groups):
            candidates = []
            for teacher in teachers_by_subject.get(group.subject, []):
                var = model.new_bool_var(
                    f"g_{coupling.id}_{index}_{teacher.id}"
                )
                variables[(coupling.id, index, teacher.id)] = var
                by_teacher.setdefault(teacher.id, []).append(var)
                candidates.append(var)
            if candidates:
                model.add_exactly_one(candidates)
        for teacher_vars in by_teacher.values():
            model.add_at_most_one(teacher_vars)
    return variables


def _add_deputat_bounds(
    model: cp_model.CpModel,
    data: SchoolData,
    class_vars: dict[ClassSubjectKey, cp_model.IntVar],
    group_vars: dict[GroupKey, cp_model.IntVar],
) -> None:
    """Deputat-Min ≤ Stunden ≤ min(Deputat-Max, unterrichtbare Stunden)."""
    time_grid = data.config.time_grid
    hours_of = {
        (school_class.id, subject): hours
        for school_class in data.classes
        for subject, hours in school_class.curriculum.items()
    }
    coupling_by_id = {coupling.id: coupling for coupling in data.couplings}

    load_terms: dict[str, list] = {t.id: [] for t in data.teachers}
    for (teacher_id, class_id, subject), var in class_vars.items():
        load_terms[teacher_id].append(var * hours_of[(class_id, subject)])
    for (coupling_id, index, teacher_id), var in group_vars.items():
        group = coupling_by_id[coupling_id].groups[index]
        load_terms[teacher_id].append(var * group.hours_per_week)

    for teacher in data.teachers:
        upper = min(
            teacher.deputat_max,
            teacher.teachable_hours(
                time_grid.days_per_week, time_grid.sek1_max_slot
            ),
        )
        load = sum(load_terms[teacher.id])
        model.add(load >= teacher.deputat_min)
        model.add(load <= upper)


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
