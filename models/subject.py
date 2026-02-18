"""Datenmodell für ein Unterrichtsfach (Pydantic v2)."""

from typing import Optional
from pydantic import BaseModel


class Subject(BaseModel):
    """Repräsentiert ein Unterrichtsfach."""

    name: str
    short_name: str
    category: str       # hauptfach/sprache/nw/musisch/sport/gesellschaft/wpf
    requires_special_room: Optional[str] = None
    double_lesson_required: bool = False
    double_lesson_preferred: bool = False
    is_hauptfach: bool = False

    @property
    def needs_special_room(self) -> bool:
        """True wenn ein Fachraum benötigt wird."""
        return self.requires_special_room is not None
