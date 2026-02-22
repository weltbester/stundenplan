"""Datenmodell für eine Schulklasse (Pydantic v2)."""

from typing import Optional

from pydantic import BaseModel


class SchoolClass(BaseModel):
    """Repräsentiert eine einzelne Klasse (z.B. 7b)."""

    id: str                      # "5a", "10f"
    grade: int
    label: str                   # "a".."f"
    curriculum: dict[str, int]   # Fach → Wochenstunden (nur Fächer mit > 0 Std.)
    max_slot: int                # Letzte erlaubte Stunde (aus Config.time_grid.sek1_max_slot)
    home_room: Optional[str] = None  # Klassenraum-ID, z.B. "101" (optional)

    @property
    def total_weekly_hours(self) -> int:
        """Summe aller Wochenstunden laut Stundenplan."""
        return sum(self.curriculum.values())
