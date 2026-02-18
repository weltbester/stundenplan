"""Datenmodell für Kopplungen (klassenübergreifender Unterricht, Pydantic v2)."""

from pydantic import BaseModel


class CouplingGroup(BaseModel):
    """Eine Gruppe innerhalb einer Kopplung (z.B. "evangelisch" bei Reli/Ethik).

    Die Lehrerzuweisung ist eine Solver-Entscheidung und wird hier NICHT gespeichert.
    """

    group_name: str      # "evangelisch", "Informatik-WPF"
    subject: str         # Unterrichtetes Fach (z.B. "Religion", "Informatik")
    hours_per_week: int  # Wochenstunden dieser Gruppe


class Coupling(BaseModel):
    """Kopplung: Mehrere Klassen teilen einen Zeitslot auf verschiedene Gruppen auf.

    Beispiel Religion/Ethik Jahrgang 5:
    - Klassen 5a..5f belegen alle denselben Slot.
    - Schüler werden auf evangelisch/katholisch/ethik aufgeteilt.
    - Jede Gruppe bekommt einen eigenen Lehrer (Solver-Entscheidung).

    WICHTIG: Alle beteiligten Klassen müssen im Kopplungs-Slot gleichzeitig frei sein!
    """

    id: str                           # "reli_5", "wpf_9"
    coupling_type: str                # "reli_ethik" / "wpf"
    involved_class_ids: list[str]     # ALLE beteiligten Klassen (z.B. ["5a","5b","5c","5d","5e","5f"])
    groups: list[CouplingGroup]       # Alle Gruppen dieser Kopplung
    hours_per_week: int               # Gesamtstunden der Kopplung pro Woche
    cross_class: bool = True          # True = klassenübergreifend (Standard)
