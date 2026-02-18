"""Datenmodell für einen Zeitslot im Wochenraster."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TimeSlot:
    """Repräsentiert einen einzelnen Unterrichtszeitslot im Wochenraster.

    Kombination aus Wochentag und Stundenslot.
    Immutable (frozen=True) damit es als Dict-Key / Set-Element nutzbar ist.
    """

    # Wochentag (0=Montag, 1=Dienstag, ..., 4=Freitag)
    day: int
    # Stunden-Slot (1-basiert, z.B. 1 = 1. Stunde)
    slot: int

    @property
    def slot_id(self) -> str:
        """Eindeutiger String-Bezeichner (z.B. "0_1" für Mo 1. Stunde)."""
        return f"{self.day}_{self.slot}"

    @property
    def day_name(self) -> str:
        """Abgekürzter Tagesname."""
        names = ["Mo", "Di", "Mi", "Do", "Fr", "Sa"]
        return names[self.day] if self.day < len(names) else str(self.day)

    def __repr__(self) -> str:
        return f"TimeSlot({self.day_name}, Std.{self.slot})"

    def __str__(self) -> str:
        return f"{self.day_name} {self.slot}."
