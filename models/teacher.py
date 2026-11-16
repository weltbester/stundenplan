"""Datenmodell für eine Lehrkraft (Pydantic v2)."""

from typing import Optional

from pydantic import BaseModel, field_validator, model_validator

# Soll-Stunden sind in halben Unterrichtsstunden angebbar (z.B. 25,5).
HALF_LESSONS_PER_LESSON = 2


def format_hours(hours: float) -> str:
    """Stundenzahl mit deutschem Komma, ganze Zahlen ohne Nachkomma."""
    if float(hours).is_integer():
        return str(int(hours))
    return f"{hours:.1f}".replace(".", ",")


def format_hours_delta(hours: float) -> str:
    """Abweichung mit Vorzeichen, z.B. '+1', '-0,5', '±0'."""
    if hours == 0:
        return "±0"
    sign = "+" if hours > 0 else "-"
    return sign + format_hours(abs(hours))


class Teacher(BaseModel):
    """Repräsentiert eine einzelne Lehrkraft."""

    id: str                                       # Kürzel ("MÜL")
    name: str                                     # "Müller, Hans"
    subjects: list[str]                           # Unterrichtbare Fächer
    deputat_max: int                              # Absolute Obergrenze (nie überschreiten)
    deputat_min: int                              # Untergrenze (muss erreicht werden)
    # Soll-Stunden laut Vertrag/Verteilung, halbe Stunden erlaubt (25.5).
    # None bei älteren Datensätzen: siehe target_hours().
    deputat_soll: Optional[float] = None
    is_teilzeit: bool = False
    unavailable_slots: list[tuple[int, int]] = [] # (day, slot_number)
    preferred_free_days: list[int] = []           # 0=Mo..4=Fr
    max_hours_per_day: int = 6
    max_gaps_per_day: int = 2

    @property
    def deputat(self) -> int:
        """Rückwärtskompatibilität: gibt deputat_max zurück."""
        return self.deputat_max

    @field_validator("id")
    @classmethod
    def normalize_id(cls, v: str) -> str:
        return v.upper()

    @field_validator("deputat_soll")
    @classmethod
    def _check_half_lessons(cls, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        if value <= 0:
            raise ValueError("deputat_soll muss > 0 sein.")
        if not (value * HALF_LESSONS_PER_LESSON).is_integer():
            raise ValueError(
                f"deputat_soll ({value}) muss eine ganze oder halbe "
                f"Stundenzahl sein."
            )
        return float(value)

    @model_validator(mode='after')
    def _check_deputat_bounds(self):
        if self.deputat_min <= 0:
            raise ValueError("deputat_min muss > 0 sein.")
        if self.deputat_min > self.deputat_max:
            raise ValueError(
                f"deputat_min ({self.deputat_min}) > deputat_max ({self.deputat_max})"
            )
        soll = self.deputat_soll
        if soll is not None and not (
            self.deputat_min <= soll <= self.deputat_max
        ):
            raise ValueError(
                f"deputat_soll ({soll}) liegt außerhalb der Grenzen "
                f"{self.deputat_min}–{self.deputat_max}."
            )
        return self

    @property
    def available_slot_count(self) -> int:
        """Anzahl verfügbarer Sek-I-Slots (5 Tage × sek1_max_slot − Sperren)."""
        # Dieser Wert ist konfigurationsabhängig; Standardwert für 5×7
        return 35 - len(self.unavailable_slots)

    def target_hours(self, max_buffer: int) -> float:
        """Soll-Stunden dieser Lehrkraft.

        Ältere Datensätze kennen kein `deputat_soll`; dort wurde die
        Obergrenze als "Deputat + Puffer" gebildet, also gilt Obergrenze
        minus `max_buffer` (in die Grenzen geholt).
        """
        if self.deputat_soll is not None:
            return self.deputat_soll
        derived = self.deputat_max - max_buffer
        return float(min(self.deputat_max, max(self.deputat_min, derived)))

    def target_half_lessons(self, max_buffer: int) -> int:
        """Soll in halben Stunden (ganzzahlig, für den Solver)."""
        return round(self.target_hours(max_buffer) * HALF_LESSONS_PER_LESSON)

    def teachable_hours(self, days_per_week: int, slots_per_day: int) -> int:
        """Höchstens unterrichtbare Wochenstunden dieser Lehrkraft.

        Je Tag zählt das Minimum aus Tagesmaximum und Stunden ohne
        Sperrzeit. Das ist schärfer als "Wochen-Slots minus Sperrzeiten":
        freie Stunden über dem Tagesmaximum sind nicht nutzbar.
        """
        blocked = set(self.unavailable_slots)
        total = 0
        for day in range(days_per_week):
            free = sum(
                (day, slot) not in blocked
                for slot in range(1, slots_per_day + 1)
            )
            total += min(self.max_hours_per_day, free)
        return total
