"""Datenmodell für eine Lehrkraft (Pydantic v2)."""

from pydantic import BaseModel, field_validator, model_validator


class Teacher(BaseModel):
    """Repräsentiert eine einzelne Lehrkraft."""

    id: str                                       # Kürzel ("MÜL")
    name: str                                     # "Müller, Hans"
    subjects: list[str]                           # Unterrichtbare Fächer
    deputat_max: int                              # Absolute Obergrenze (nie überschreiten)
    deputat_min: int                              # Untergrenze (muss erreicht werden)
    is_teilzeit: bool = False
    unavailable_slots: list[tuple[int, int]] = [] # (day, slot_number)
    preferred_free_days: list[int] = []           # 0=Mo..4=Fr
    max_hours_per_day: int = 6
    max_gaps_per_day: int = 2
    max_gaps_per_week: int = 5   # pro-Lehrer-Limit; 0 = kein Limit

    @property
    def deputat(self) -> int:
        """Rückwärtskompatibilität: gibt deputat_max zurück."""
        return self.deputat_max

    @field_validator("id")
    @classmethod
    def normalize_id(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode='after')
    def _check_deputat_bounds(self):
        if self.deputat_min <= 0:
            raise ValueError("deputat_min muss > 0 sein.")
        if self.deputat_min > self.deputat_max:
            raise ValueError(
                f"deputat_min ({self.deputat_min}) > deputat_max ({self.deputat_max})"
            )
        return self

    @property
    def available_slot_count(self) -> int:
        """Anzahl verfügbarer Sek-I-Slots (5 Tage × sek1_max_slot − Sperren)."""
        # Dieser Wert ist konfigurationsabhängig; Standardwert für 5×7
        return 35 - len(self.unavailable_slots)
