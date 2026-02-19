"""PinManager – fixiert einzelne Unterrichtsstunden vor dem Solver-Lauf.

Eine gepinnte Stunde ist eine harte Constraint: Der Solver MUSS genau diesen
Lehrer an genau diesem Tag/Slot für genau diese Klasse einplanen.
"""

import json
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from solver.scheduler import ScheduleSolver


class PinnedLesson(BaseModel):
    """Eine fixierte Unterrichtsstunde."""

    teacher_id: str   # Lehrer-Kürzel (wird normalisiert zu UPPERCASE)
    class_id: str     # Klassen-ID (z.B. "5a")
    subject: str      # Fach
    day: int          # 0-basiert (0=Mo, 4=Fr)
    slot_number: int  # 1-basiert (wie Zeitraster)

    def model_post_init(self, __context) -> None:
        # teacher_id normalisieren
        object.__setattr__(self, "teacher_id", self.teacher_id.upper())


class PinManager:
    """Verwaltet gepinnte Stunden und wendet sie auf den Solver an."""

    def __init__(self) -> None:
        self._pins: list[PinnedLesson] = []

    def add_pin(self, pin: PinnedLesson) -> None:
        """Fügt einen Pin hinzu. Ersetzt bestehenden Pin am selben Tag/Slot/Klasse."""
        # Bestehenden Pin an gleicher Position entfernen
        self._pins = [
            p for p in self._pins
            if not (p.class_id == pin.class_id and p.day == pin.day
                    and p.slot_number == pin.slot_number)
        ]
        self._pins.append(pin)

    def remove_pin(self, teacher_id: str, day: int, slot: int) -> bool:
        """Entfernt einen Pin. Gibt True zurück wenn ein Pin entfernt wurde."""
        teacher_id = teacher_id.upper()
        before = len(self._pins)
        self._pins = [
            p for p in self._pins
            if not (p.teacher_id == teacher_id and p.day == day
                    and p.slot_number == slot)
        ]
        return len(self._pins) < before

    def get_pins(self) -> list[PinnedLesson]:
        """Gibt alle gepinnten Stunden zurück."""
        return list(self._pins)

    def apply_to_solver(self, solver: "ScheduleSolver") -> None:
        """Übergibt alle Pins an den Solver (wird intern von solve() genutzt)."""
        # Der Solver erhält die Pins direkt über solve(pins=...).
        # Diese Methode existiert als alternativer Einstiegspunkt.
        solver._pinned_lessons = list(self._pins)

    def save_json(self, path: Path) -> None:
        """Speichert alle Pins als JSON."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = [p.model_dump() for p in self._pins]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load_json(self, path: Path) -> None:
        """Lädt Pins aus einer JSON-Datei (überschreibt aktuelle Pins)."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Pin-Datei nicht gefunden: {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._pins = [PinnedLesson(**item) for item in data]

    def __len__(self) -> int:
        return len(self._pins)

    def __repr__(self) -> str:
        return f"PinManager({len(self._pins)} pins)"
