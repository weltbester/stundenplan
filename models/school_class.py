"""Datenmodell für eine Schulklasse (Pydantic v2)."""

from typing import Optional

from pydantic import BaseModel


class SchoolClass(BaseModel):
    """Repräsentiert eine einzelne Klasse oder Oberstufen-Kurs (z.B. 7b, Q1-LK-Ma)."""

    id: str                      # "5a", "10f", "Q1-LK-Ma"
    grade: int
    label: str                   # "a".."f" oder Kurs-Bezeichner
    curriculum: dict[str, int]   # Fach → Wochenstunden (nur Fächer mit > 0 Std.)
    max_slot: int                # Letzte erlaubte Stunde (sek1_max_slot oder sek2_max_slot)
    home_room: Optional[str] = None  # Klassenraum-ID, z.B. "101" (optional)
    is_course: bool = False           # True für Oberstufe-LK/GK-Kurse
    course_type: Optional[str] = None # "LK", "GK" oder None für Klassen

    @property
    def total_weekly_hours(self) -> int:
        """Summe aller Wochenstunden laut Stundenplan."""
        return sum(self.curriculum.values())
