"""Vergleicht die Wochenstunden der Klassen mit dem Rahmen des Landes."""

from config.nrw_g9 import NRW_G9_WEEKLY_FRAME
from config.schema import SchoolConfig, SchoolType
from models.school_class import SchoolClass

# Jahrgang → (Minimum, Maximum) Wochenstunden
WeeklyFrame = dict[int, tuple[int, int]]

# Bundesland (wie in der Konfiguration, großgeschrieben) → Rahmen und
# Bezeichnung für die Meldung. Nur Gymnasium; andere Länder folgen mit
# ihren Daten (docs/bundeslaender.md).
_GYMNASIUM_FRAMES: dict[str, tuple[WeeklyFrame, str]] = {
    "NRW": (NRW_G9_WEEKLY_FRAME, "NRW-Rahmen für das Gymnasium G9"),
    "NW": (NRW_G9_WEEKLY_FRAME, "NRW-Rahmen für das Gymnasium G9"),
}


def weekly_frame_for(config: SchoolConfig) -> tuple[WeeklyFrame, str]:
    """Rahmen und Bezeichnung zur Konfiguration; leer, wenn unbekannt."""
    if config.school_type != SchoolType.GYMNASIUM:
        return {}, ""
    return _GYMNASIUM_FRAMES.get(config.bundesland.strip().upper(), ({}, ""))


def _class_range(class_ids: list[str]) -> str:
    """'9a' oder '9a–9f' für die betroffenen Klassen."""
    ordered = sorted(class_ids)
    if len(ordered) == 1:
        return ordered[0]
    return f"{ordered[0]}–{ordered[-1]}"


def check_weekly_frame(
    classes: list[SchoolClass], config: SchoolConfig
) -> list[str]:
    """Warnungen für Klassen außerhalb des Wochenstundenrahmens.

    Je Jahrgang und Stundenzahl eine Meldung. Jahrgänge ohne Vorgabe
    und Länder ohne hinterlegten Rahmen werden nicht geprüft.
    """
    frame, frame_name = weekly_frame_for(config)
    outside: dict[tuple[int, int], list[str]] = {}
    for school_class in classes:
        if school_class.grade not in frame:
            continue
        minimum, maximum = frame[school_class.grade]
        hours = school_class.total_weekly_hours
        if not minimum <= hours <= maximum:
            outside.setdefault(
                (school_class.grade, hours), []
            ).append(school_class.id)

    warnings: list[str] = []
    for (grade, hours), class_ids in sorted(outside.items()):
        minimum, maximum = frame[grade]
        direction = "über" if hours > maximum else "unter"
        warnings.append(
            f"Jahrgang {grade} ({_class_range(class_ids)}): {hours} "
            f"Wochenstunden liegen {direction} dem {frame_name} "
            f"({minimum}–{maximum})."
        )
    return warnings
