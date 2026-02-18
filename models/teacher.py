"""Datenmodell für eine Lehrkraft (Pydantic v2)."""

from pydantic import BaseModel, field_validator


class Teacher(BaseModel):
    """Repräsentiert eine einzelne Lehrkraft."""

    id: str                                       # Kürzel ("MÜL")
    name: str                                     # "Müller, Hans"
    subjects: list[str]                           # Unterrichtbare Fächer
    deputat: int                                  # Wochen-Soll
    is_teilzeit: bool = False
    unavailable_slots: list[tuple[int, int]] = [] # (day, slot_number)
    preferred_free_days: list[int] = []           # 0=Mo..4=Fr
    max_hours_per_day: int = 6
    max_gaps_per_day: int = 2

    @field_validator("id")
    @classmethod
    def normalize_id(cls, v: str) -> str:
        return v.upper()

    @property
    def available_slot_count(self) -> int:
        """Anzahl verfügbarer Sek-I-Slots (5 Tage × sek1_max_slot − Sperren)."""
        # Dieser Wert ist konfigurationsabhängig; Standardwert für 5×7
        return 35 - len(self.unavailable_slots)
