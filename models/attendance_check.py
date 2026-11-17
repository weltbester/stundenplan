"""Genug freie Lehrkräfte in den Stunden, die jede Klasse täglich hat.

Ein Klassentag beginnt ohne Lücke in der ersten Stunde (C10). Eine
Klasse mit k Pflichtstunden je Tag hat daher an JEDEM Tag die Stunden
1 bis k. Bekommen in einer solchen Stunde nicht alle betroffenen
Klassen gleichzeitig eine eigene freie Lehrkraft, gibt es keinen Plan.
Der Solver kann das (Schubfachprinzip) nicht beweisen und sucht ohne
Ergebnis bis zum Zeitlimit; diese Prüfung meldet es sofort.

Die Prüfung ist großzügig und meldet nur, was sicher unlösbar ist:
Ohne vorgegebene Verteilung zählt jede Lehrkraft mit einem Fach der
Klasse. Eine Kopplung, die in der Stunde stattfinden könnte, bringt
ihre freien Gruppen-Lehrkräfte als Kandidaten ihrer Klassen ein; hat
sie weniger Gruppen als Klassen, gelten ihre Klassen als versorgt.
"""

from config.schema import TimeGridConfig
from models.coupling import Coupling
from models.fixed_assignment import (
    FixedAssignment, coupling_subjects_by_class,
)
from models.school_class import SchoolClass
from models.teacher import Teacher

Slot = tuple[int, int]  # (Tag, Stunde)
# So viele Kürzel nennt eine Meldung, danach "…"
MAX_LISTED = 8
# Klasse → Lehrkräfte, die ihr in einer Stunde Unterricht geben können
Candidates = dict[str, set[str]]


def sek1_slot_numbers(time_grid: TimeGridConfig) -> list[int]:
    """Stunden des Sek-I-Rasters, aufsteigend (wie im Stundenplan-Solver)."""
    return sorted(
        slot.slot_number
        for slot in time_grid.lesson_slots
        if not slot.is_sek2_only
        and slot.slot_number <= time_grid.sek1_max_slot
    )


def weekly_lessons(
    classes: list[SchoolClass], couplings: list[Coupling]
) -> dict[str, int]:
    """Klasse → Wochenstunden, die der Stundenplan für sie einplant.

    Fächer außerhalb von Kopplungen laut Stundentafel, dazu die
    Stunden jeder Kopplung, an der die Klasse beteiligt ist.
    """
    covered = coupling_subjects_by_class(couplings)
    lessons = {
        school_class.id: sum(
            hours
            for subject, hours in school_class.curriculum.items()
            if hours > 0
            and subject not in covered.get(school_class.id, set())
        )
        for school_class in classes
    }
    for coupling in couplings:
        for class_id in coupling.involved_class_ids:
            if class_id in lessons:
                lessons[class_id] += coupling.hours_per_week
    return lessons


def lessons_every_day(
    weekly_lessons: int, days: int, slots_per_day: int
) -> int:
    """Wie viele Stunden ab der ersten eine Klasse an JEDEM Tag hat.

    Ein Tag hat höchstens `slots_per_day` Stunden und beginnt ohne Lücke
    in der ersten (C10). Die übrigen Tage nehmen zusammen höchstens
    `(days - 1) * slots_per_day` Stunden auf; der Rest fällt auf den
    kürzesten Tag. 0 heißt: ein freier Tag wäre möglich.
    """
    return max(0, weekly_lessons - (days - 1) * slots_per_day)


def daily_slots_by_class(
    classes: list[SchoolClass],
    couplings: list[Coupling],
    time_grid: TimeGridConfig,
) -> dict[str, list[int]]:
    """Klasse → Stunden, in denen sie an jedem Tag Unterricht hat."""
    slots = sek1_slot_numbers(time_grid)
    return {
        class_id: slots[:lessons_every_day(
            weekly, time_grid.days_per_week, len(slots)
        )]
        for class_id, weekly in weekly_lessons(classes, couplings).items()
    }


def attendance_by_slot(
    classes: list[SchoolClass],
    couplings: list[Coupling],
    time_grid: TimeGridConfig,
) -> dict[int, int]:
    """Stunde → Zahl der Klassen, die an JEDEM Tag in ihr Unterricht haben."""
    daily = daily_slots_by_class(classes, couplings, time_grid)
    return {
        slot: sum(slot in class_slots for class_slots in daily.values())
        for slot in sek1_slot_numbers(time_grid)
    }


def _is_free(teacher: Teacher, slot: Slot) -> bool:
    return slot not in teacher.unavailable_slots


def _listing(ids: list[str]) -> str:
    """Kürzel für eine Meldung, höchstens `MAX_LISTED`."""
    if not ids:
        return "keine"
    shown = ", ".join(ids[:MAX_LISTED])
    return shown + (", …" if len(ids) > MAX_LISTED else "")


class _AttendanceCheck:
    """Prüft jede Stunde, die Klassen an jedem Tag haben."""

    def __init__(
        self,
        classes: list[SchoolClass],
        teachers: list[Teacher],
        couplings: list[Coupling],
        fixed_assignments: list[FixedAssignment],
        time_grid: TimeGridConfig,
    ) -> None:
        self._classes = classes
        self._teachers = {teacher.id: teacher for teacher in teachers}
        self._couplings = couplings
        self._time_grid = time_grid
        self._daily = daily_slots_by_class(classes, couplings, time_grid)
        self._possible = self._possible_teachers(fixed_assignments)

    def _possible_teachers(
        self, fixed_assignments: list[FixedAssignment]
    ) -> Candidates:
        """Klasse → Lehrkräfte, die ihr Unterricht außerhalb von
        Kopplungen geben können (vorgegeben oder mit passendem Fach)."""
        fixed = {
            (item.class_id, item.subject): item.teacher_id
            for item in fixed_assignments
        }
        covered = coupling_subjects_by_class(self._couplings)
        possible: Candidates = {}
        for school_class in self._classes:
            ids: set[str] = set()
            for subject, hours in school_class.curriculum.items():
                if hours <= 0 or subject in covered.get(
                    school_class.id, set()
                ):
                    continue
                given = fixed.get((school_class.id, subject))
                if given is not None:
                    ids.add(given)
                else:
                    ids.update(
                        teacher.id for teacher in self._teachers.values()
                        if subject in teacher.subjects
                    )
            possible[school_class.id] = ids
        return possible

    def _group_teachers(self, coupling: Coupling, slot: Slot) -> set[str]:
        """Freie Lehrkräfte für die Gruppen der Kopplung in `slot`;
        leer, wenn eine Gruppe keine freie Lehrkraft hat."""
        found: set[str] = set()
        for group in coupling.groups:
            if group.teacher_id is not None:
                ids = {group.teacher_id} & set(self._teachers)
            else:
                ids = {
                    teacher.id for teacher in self._teachers.values()
                    if group.subject in teacher.subjects
                }
            free = {
                teacher_id for teacher_id in ids
                if _is_free(self._teachers[teacher_id], slot)
            }
            if not free:
                return set()
            found |= free
        return found

    def _candidates(self, slot: Slot) -> Candidates:
        """Klasse → freie Lehrkräfte für die Klassen, die in `slot`
        Unterricht haben müssen. Klassen einer möglichen Kopplung mit
        weniger Gruppen als Klassen fehlen (gelten als versorgt)."""
        required = [
            class_id for class_id, class_slots in self._daily.items()
            if slot[1] in class_slots
        ]
        candidates: Candidates = {
            class_id: {
                teacher_id for teacher_id in self._possible[class_id]
                if teacher_id in self._teachers
                and _is_free(self._teachers[teacher_id], slot)
            }
            for class_id in required
        }
        for coupling in self._couplings:
            group_teachers = self._group_teachers(coupling, slot)
            if not group_teachers:
                continue
            involved = set(coupling.involved_class_ids) & set(candidates)
            for class_id in involved:
                if len(coupling.groups) < len(coupling.involved_class_ids):
                    candidates.pop(class_id)
                else:
                    candidates[class_id] |= group_teachers
        return candidates

    def errors(self) -> list[str]:
        """Eine Meldung je Stunde, in der Lehrkräfte fehlen."""
        messages: list[str] = []
        for day in range(self._time_grid.days_per_week):
            for slot_number in sek1_slot_numbers(self._time_grid):
                message = self._check_slot((day, slot_number))
                if message:
                    messages.append(message)
        return messages

    def _check_slot(self, slot: Slot) -> str:
        """Fehlermeldung für `slot`, leer wenn alle Klassen versorgt sind."""
        short = hall_violation(self._candidates(slot))
        if short is None:
            return ""
        short_classes, free_teachers = short
        return self._message(slot, short_classes, free_teachers)

    def _message(
        self, slot: Slot, class_ids: list[str], teacher_ids: list[str]
    ) -> str:
        day, slot_number = slot
        names = self._time_grid.day_names
        day_name = names[day] if day < len(names) else f"Tag {day + 1}"
        classes = (
            f"1 Klasse ({_listing(class_ids)}) hat" if len(class_ids) == 1
            else f"{len(class_ids)} Klassen ({_listing(class_ids)}) haben"
        )
        verb = "ist" if len(teacher_ids) == 1 else "sind"
        return (
            f"{day_name} {slot_number}. Stunde: {classes} an jedem Tag "
            f"in dieser Stunde Unterricht (der Tag beginnt ohne Lücke in "
            f"der 1. Stunde), aber nur {len(teacher_ids)} der dafür "
            f"möglichen Lehrkräfte {verb} frei "
            f"({_listing(teacher_ids)}). Sperrzeiten in dieser Stunde "
            f"lockern oder die Unterrichtsverteilung ändern."
        )


def _augment(
    class_id: str,
    candidates: Candidates,
    match: dict[str, str],
    seen: set[str],
) -> bool:
    """Sucht einen erweiternden Weg ab `class_id` (Kuhn)."""
    for teacher_id in sorted(candidates[class_id]):
        if teacher_id in seen:
            continue
        seen.add(teacher_id)
        owner = match.get(teacher_id)
        if owner is None or _augment(owner, candidates, match, seen):
            match[teacher_id] = class_id
            return True
    return False


def hall_violation(
    candidates: Candidates,
) -> tuple[list[str], list[str]] | None:
    """Klassen, die zusammen mehr sind als ihre freien Lehrkräfte.

    Bestimmt eine größte Zuordnung Klasse → eigene Lehrkraft. Bleibt
    eine Klasse ohne Lehrkraft, liefert die Suche entlang wechselnder
    Wege von allen unversorgten Klassen eine Menge Klassen, deren
    mögliche Lehrkräfte zusammen weniger sind (Satz von Hall).
    None, wenn alle Klassen versorgt werden können.
    """
    match: dict[str, str] = {}
    unmatched = [
        class_id for class_id in sorted(candidates)
        if not _augment(class_id, candidates, match, set())
    ]
    if not unmatched:
        return None
    classes: set[str] = set(unmatched)
    teachers: set[str] = set()
    queue = list(unmatched)
    while queue:
        for teacher_id in candidates[queue.pop()]:
            if teacher_id in teachers:
                continue
            teachers.add(teacher_id)
            owner = match[teacher_id]
            if owner not in classes:
                classes.add(owner)
                queue.append(owner)
    return sorted(classes), sorted(teachers)


def check_attendance(
    classes: list[SchoolClass],
    teachers: list[Teacher],
    couplings: list[Coupling],
    fixed_assignments: list[FixedAssignment],
    time_grid: TimeGridConfig,
) -> list[str]:
    """Fehler für Stunden, in denen nicht jede Klasse eine freie
    Lehrkraft bekommen kann, obwohl sie dort Unterricht haben muss."""
    return _AttendanceCheck(
        classes, teachers, couplings, fixed_assignments, time_grid
    ).errors()
