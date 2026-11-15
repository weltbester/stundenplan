"""Vorgegebene Unterrichtsverteilung und ihre Plausibilitätsprüfung.

Eine FixedAssignment legt fest, welche Lehrkraft ein Fach in einer Klasse
unterrichtet. Nicht festgelegte Klasse-Fach-Paare entscheidet der Solver.
"""

from collections import Counter

from pydantic import BaseModel, field_validator

from models.coupling import Coupling
from models.school_class import SchoolClass
from models.teacher import Teacher

# (Fehler, Warnungen)
CheckResult = tuple[list[str], list[str]]


class FixedAssignment(BaseModel):
    """Lehrkraft `teacher_id` unterrichtet `subject` in Klasse `class_id`."""

    class_id: str
    subject: str
    teacher_id: str

    @field_validator("teacher_id")
    @classmethod
    def normalize_teacher_id(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("class_id", "subject")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


def coupling_subjects_by_class(
    couplings: list[Coupling],
) -> dict[str, set[str]]:
    """Klasse → Stundentafel-Fächer, die eine Kopplung abdeckt."""
    covered: dict[str, set[str]] = {}
    for coupling in couplings:
        for class_id in coupling.involved_class_ids:
            covered.setdefault(class_id, set()).update(
                coupling.curriculum_subjects()
            )
    return covered


def check_fixed_assignments(
    assignments: list[FixedAssignment],
    classes: list[SchoolClass],
    teachers: list[Teacher],
    couplings: list[Coupling],
    days_per_week: int,
    slots_per_day: int,
) -> CheckResult:
    """Prüft die vorgegebene Unterrichtsverteilung vor dem Solver-Lauf.

    Fehler: unbekannte Klasse/Lehrkraft, Fach nicht in der Stundentafel der
    Klasse, Fach läuft über eine Kopplung, doppelte Vorgabe, Deputat-Max
    oder unterrichtbare Stunden (Sperrzeiten, Tagesmaximum) überschritten,
    Deputat-Min nicht mehr erreichbar.
    Warnung: fachfremder Einsatz.
    """
    errors: list[str] = []
    warnings: list[str] = []
    class_map = {cls.id: cls for cls in classes}
    teacher_map = {teacher.id: teacher for teacher in teachers}
    covered = coupling_subjects_by_class(couplings)

    valid: list[FixedAssignment] = []
    for assignment in assignments:
        problem = _reference_problem(
            assignment, class_map, teacher_map, covered
        )
        if problem:
            errors.append(problem)
        else:
            valid.append(assignment)

    errors.extend(_duplicate_problems(valid))
    errors.extend(_coupling_teacher_problems(couplings, teacher_map))
    warnings.extend(_out_of_field_warnings(valid, couplings, teacher_map))

    fixed_load = _fixed_load(valid, couplings, class_map)
    open_hours = _open_hours_by_subject(valid, couplings, classes, covered)
    for teacher in teachers:
        capacity = teacher.teachable_hours(days_per_week, slots_per_day)
        errors.extend(_load_problems(
            teacher, fixed_load[teacher.id], open_hours, capacity
        ))
    return errors, warnings


def _label(assignment: FixedAssignment) -> str:
    return (
        f"Unterrichtsverteilung {assignment.class_id}/"
        f"{assignment.subject} → {assignment.teacher_id}"
    )


def _reference_problem(
    assignment: FixedAssignment,
    class_map: dict[str, SchoolClass],
    teacher_map: dict[str, Teacher],
    covered: dict[str, set[str]],
) -> str:
    """Erster Verweis-Fehler der Vorgabe oder leerer String."""
    label = _label(assignment)
    school_class = class_map.get(assignment.class_id)
    if school_class is None:
        return f"{label}: Unbekannte Klasse '{assignment.class_id}'."
    if assignment.teacher_id not in teacher_map:
        return f"{label}: Unbekanntes Kürzel '{assignment.teacher_id}'."
    if school_class.curriculum.get(assignment.subject, 0) <= 0:
        return (
            f"{label}: Klasse {assignment.class_id} hat das Fach "
            f"'{assignment.subject}' nicht in der Stundentafel."
        )
    if assignment.subject in covered.get(assignment.class_id, set()):
        return (
            f"{label}: '{assignment.subject}' läuft in dieser Klasse über "
            f"eine Kopplung. Lehrkraft bei der Kopplungsgruppe angeben."
        )
    return ""


def _duplicate_problems(assignments: list[FixedAssignment]) -> list[str]:
    counts = Counter((a.class_id, a.subject) for a in assignments)
    return [
        f"Unterrichtsverteilung {class_id}/{subject}: "
        f"{count} Lehrkräfte vorgegeben, erlaubt ist genau eine."
        for (class_id, subject), count in counts.items()
        if count > 1
    ]


def _coupling_teacher_problems(
    couplings: list[Coupling], teacher_map: dict[str, Teacher]
) -> list[str]:
    return [
        f"Kopplung '{coupling.id}', Gruppe '{group.group_name}': "
        f"Unbekanntes Kürzel '{group.teacher_id}'."
        for coupling in couplings
        for group in coupling.groups
        if group.teacher_id and group.teacher_id not in teacher_map
    ]


def _out_of_field_warnings(
    assignments: list[FixedAssignment],
    couplings: list[Coupling],
    teacher_map: dict[str, Teacher],
) -> list[str]:
    """Warnungen für Lehrkräfte ohne Lehrbefähigung im vorgegebenen Fach."""
    warnings = [
        f"{_label(a)}: fachfremder Einsatz "
        f"({a.teacher_id} hat '{a.subject}' nicht als Fach)."
        for a in assignments
        if a.subject not in teacher_map[a.teacher_id].subjects
    ]
    for coupling in couplings:
        for group in coupling.groups:
            teacher = teacher_map.get(group.teacher_id or "")
            if teacher and group.subject not in teacher.subjects:
                warnings.append(
                    f"Kopplung '{coupling.id}', Gruppe "
                    f"'{group.group_name}': fachfremder Einsatz "
                    f"({teacher.id} hat '{group.subject}' nicht als Fach)."
                )
    return warnings


def _fixed_load(
    assignments: list[FixedAssignment],
    couplings: list[Coupling],
    class_map: dict[str, SchoolClass],
) -> Counter:
    """Lehrkraft → fest vorgegebene Wochenstunden (inkl. Kopplungen)."""
    load: Counter = Counter()
    for assignment in assignments:
        curriculum = class_map[assignment.class_id].curriculum
        load[assignment.teacher_id] += curriculum[assignment.subject]
    for coupling in couplings:
        for group in coupling.groups:
            if group.teacher_id:
                load[group.teacher_id] += group.hours_per_week
    return load


def _open_hours_by_subject(
    assignments: list[FixedAssignment],
    couplings: list[Coupling],
    classes: list[SchoolClass],
    covered: dict[str, set[str]],
) -> Counter:
    """Fach → Wochenstunden, deren Lehrkraft noch der Solver bestimmt."""
    fixed_pairs = {(a.class_id, a.subject) for a in assignments}
    open_hours: Counter = Counter()
    for school_class in classes:
        class_covered = covered.get(school_class.id, set())
        for subject, hours in school_class.curriculum.items():
            is_open = (
                subject not in class_covered
                and (school_class.id, subject) not in fixed_pairs
            )
            if is_open:
                open_hours[subject] += hours
    for coupling in couplings:
        for group in coupling.groups:
            if not group.teacher_id:
                open_hours[group.subject] += group.hours_per_week
    return open_hours


def _load_problems(
    teacher: Teacher,
    fixed_hours: int,
    open_hours: Counter,
    capacity: int,
) -> list[str]:
    """Deputat- und Verfügbarkeits-Fehler einer Lehrkraft.

    `capacity` = unterrichtbare Wochenstunden (Teacher.teachable_hours).
    """
    problems: list[str] = []
    if fixed_hours > teacher.deputat_max:
        problems.append(
            f"Lehrkraft {teacher.id}: {fixed_hours}h fest vorgegeben, "
            f"Deputat-Max ist {teacher.deputat_max}h."
        )
    if fixed_hours > capacity:
        problems.append(
            f"Lehrkraft {teacher.id}: {fixed_hours}h fest vorgegeben, "
            f"aber nur {capacity}h möglich (Stunden ohne Sperrzeit, "
            f"höchstens {teacher.max_hours_per_day}h pro Tag)."
        )
    reachable = fixed_hours + sum(
        open_hours[subject] for subject in set(teacher.subjects)
    )
    if reachable < teacher.deputat_min:
        problems.append(
            f"Lehrkraft {teacher.id}: Deputat-Min {teacher.deputat_min}h "
            f"nicht erreichbar ({fixed_hours}h fest vorgegeben, höchstens "
            f"{reachable}h mit den noch offenen Stunden ihrer Fächer)."
        )
    return problems
