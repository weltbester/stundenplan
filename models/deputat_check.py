"""Vergleicht die Soll-Deputate mit dem Unterrichtsbedarf."""

from typing import Optional

from models.coupling import Coupling
from models.fixed_assignment import coupling_subjects_by_class
from models.school_class import SchoolClass
from models.teacher import Teacher, format_hours

# Ab dieser Abweichung zwischen Soll-Summe und Bedarf gibt es eine Warnung.
BALANCE_TOLERANCE = 0.05
PERCENT = 100


def teacher_lessons_needed(
    classes: list[SchoolClass], couplings: list[Coupling]
) -> int:
    """Wochenstunden, die Lehrkräfte insgesamt unterrichten müssen.

    Gekoppelter Unterricht zählt je Gruppe einmal, nicht je Klasse.
    """
    covered = coupling_subjects_by_class(couplings)
    class_lessons = sum(
        hours
        for school_class in classes
        for subject, hours in school_class.curriculum.items()
        if subject not in covered.get(school_class.id, set())
    )
    group_lessons = sum(
        group.hours_per_week
        for coupling in couplings
        for group in coupling.groups
    )
    return class_lessons + group_lessons


def total_target_hours(teachers: list[Teacher], max_buffer: int) -> float:
    """Summe der Soll-Stunden aller Lehrkräfte."""
    return sum(teacher.target_hours(max_buffer) for teacher in teachers)


def target_margin(
    teachers: list[Teacher],
    classes: list[SchoolClass],
    couplings: list[Coupling],
    max_buffer: int,
) -> Optional[float]:
    """Anteil, um den die Soll-Summe über dem Bedarf liegt (0.04 = 4 %).

    None, wenn es keinen Bedarf gibt.
    """
    needed = teacher_lessons_needed(classes, couplings)
    if needed == 0:
        return None
    return total_target_hours(teachers, max_buffer) / needed - 1


def check_target_balance(
    teachers: list[Teacher],
    classes: list[SchoolClass],
    couplings: list[Coupling],
    max_buffer: int,
) -> list[str]:
    """Warnungen, wenn Soll-Deputate und Bedarf deutlich auseinanderliegen.

    Dann kann nicht jede Lehrkraft ihr Soll erreichen, egal wie der Plan
    aussieht.
    """
    needed = teacher_lessons_needed(classes, couplings)
    if needed == 0 or not teachers:
        return []
    target = total_target_hours(teachers, max_buffer)
    difference = target - needed
    if abs(difference) <= needed * BALANCE_TOLERANCE:
        return []
    per_teacher = format_hours(round(abs(difference) / len(teachers), 1))
    share = abs(difference) / needed * PERCENT
    direction = "über" if difference > 0 else "unter"
    consequence = (
        f"im Schnitt bleibt jede Lehrkraft {per_teacher}h unter ihrem Soll"
        if difference > 0 else
        f"im Schnitt liegt jede Lehrkraft {per_teacher}h über ihrem Soll"
    )
    return [
        f"Soll-Deputate ({format_hours(target)}h) liegen {share:.0f}% "
        f"{direction} dem Unterrichtsbedarf ({needed}h): {consequence}."
    ]
