"""Datenmodell für einen Raum (Pydantic v2)."""

from pydantic import BaseModel


class Room(BaseModel):
    """Repräsentiert einen Fachraum."""

    id: str         # "PH1", "CH2"
    room_type: str  # "physik", "chemie", etc.
    name: str       # "Physik-Raum 1"
