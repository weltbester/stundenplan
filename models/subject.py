"""Datenmodell für ein Unterrichtsfach (Pydantic v2)."""

from typing import Optional
from pydantic import BaseModel

from config.defaults import SUBJECT_METADATA

# Bekannte Kategorien (bestimmen die Farbe in Anzeige und Export).
SUBJECT_CATEGORIES: tuple[str, ...] = (
    "hauptfach", "sprache", "nw", "musisch", "sport", "gesellschaft",
    "wpf", "sonstig",
)
DEFAULT_CATEGORY = "sonstig"


class Subject(BaseModel):
    """Repräsentiert ein Unterrichtsfach."""

    name: str
    short_name: str
    category: str       # siehe SUBJECT_CATEGORIES
    requires_special_room: Optional[str] = None
    double_lesson_required: bool = False
    double_lesson_preferred: bool = False
    is_hauptfach: bool = False

    @property
    def needs_special_room(self) -> bool:
        """True wenn ein Fachraum benötigt wird."""
        return self.requires_special_room is not None


def subject_from_metadata(name: str, meta: dict) -> Subject:
    """Baut ein Fach aus einem Eintrag der Vorschlagstabelle."""
    return Subject(
        name=name,
        short_name=meta["short"],
        category=meta["category"],
        is_hauptfach=meta["is_hauptfach"],
        requires_special_room=meta["room"],
        double_lesson_required=meta["double_required"],
        double_lesson_preferred=meta["double_preferred"],
    )


def default_subjects() -> list[Subject]:
    """Vorschlag für die Fächerliste (neue Vorlage, Testdaten)."""
    return [
        subject_from_metadata(name, meta)
        for name, meta in SUBJECT_METADATA.items()
    ]
