"""Prüft, dass alle verwendeten Fächer in der Fächerliste stehen."""

from models.coupling import Coupling
from models.school_class import SchoolClass
from models.subject import Subject
from models.teacher import Teacher

# So viele Fundstellen nennt eine Meldung höchstens.
MAX_PLACES_SHOWN = 4


def _used_subjects(
    classes: list[SchoolClass],
    teachers: list[Teacher],
    couplings: list[Coupling],
) -> dict[str, list[str]]:
    """Fach → Stellen, an denen es verwendet wird."""
    places: dict[str, list[str]] = {}
    for school_class in classes:
        for subject, hours in school_class.curriculum.items():
            if hours > 0:
                places.setdefault(subject, []).append(
                    f"Stundentafel {school_class.id}"
                )
    for teacher in teachers:
        for subject in teacher.subjects:
            places.setdefault(subject, []).append(f"Lehrkraft {teacher.id}")
    for coupling in couplings:
        for group in coupling.groups:
            places.setdefault(group.subject, []).append(
                f"Kopplung {coupling.id}"
            )
    return places


def check_subject_references(
    subjects: list[Subject],
    classes: list[SchoolClass],
    teachers: list[Teacher],
    couplings: list[Coupling],
) -> list[str]:
    """Fehlermeldungen für Fächer, die nicht in der Fächerliste stehen.

    Ohne Eintrag kennt der Solver weder Fachraum noch Doppelstunden-Regel
    des Fachs; ein Tippfehler bliebe sonst unbemerkt.
    """
    known = {subject.name for subject in subjects}
    errors: list[str] = []
    used = _used_subjects(classes, teachers, couplings)
    for subject, places in used.items():
        if subject in known:
            continue
        unique_places = list(dict.fromkeys(places))
        shown = ", ".join(unique_places[:MAX_PLACES_SHOWN])
        more = len(unique_places) - MAX_PLACES_SHOWN
        suffix = f" und {more} weitere" if more > 0 else ""
        errors.append(
            f"Fach '{subject}' steht nicht in der Fächerliste "
            f"(verwendet in: {shown}{suffix})."
        )
    return errors
