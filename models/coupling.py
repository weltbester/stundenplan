"""Datenmodell für Kopplungen (klassenübergreifender Unterricht, Pydantic v2)."""

from typing import Optional

from pydantic import BaseModel, field_validator

COUPLING_TYPE_WPF = "wpf"
COUPLING_TYPE_RELI_ETHIK = "reli_ethik"
# Schiene: parallele Gruppen, die zusammen EIN Fach der Stundentafel
# abdecken (z.B. Französisch und Latein für "2. Fremdsprache").
COUPLING_TYPE_BAND = "band"
# Unter diesem Fachnamen steht der Wahlpflichtbereich in der Stundentafel.
WPF_CURRICULUM_SUBJECT = "WPF"


class CouplingGroup(BaseModel):
    """Eine Gruppe innerhalb einer Kopplung (z.B. "evangelisch" bei Reli/Ethik).

    Die Lehrkraft bestimmt normalerweise der Solver; mit `teacher_id`
    kann sie fest vorgegeben werden.
    """

    group_name: str      # "evangelisch", "Informatik-WPF"
    subject: str         # Unterrichtetes Fach (z.B. "Religion", "Informatik")
    hours_per_week: int  # Wochenstunden dieser Gruppe
    # Vorgegebene Lehrkraft (Kürzel); None = Solver entscheidet
    teacher_id: Optional[str] = None

    @field_validator("teacher_id")
    @classmethod
    def normalize_teacher_id(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        return value.strip().upper()


class Coupling(BaseModel):
    """Kopplung: Mehrere Klassen teilen einen Zeitslot auf verschiedene Gruppen auf.

    Beispiel Religion/Ethik Jahrgang 5:
    - Klassen 5a..5f belegen alle denselben Slot.
    - Schüler werden auf evangelisch/katholisch/ethik aufgeteilt.
    - Jede Gruppe bekommt einen eigenen Lehrer (Solver-Entscheidung).

    WICHTIG: Alle beteiligten Klassen müssen im Kopplungs-Slot gleichzeitig frei sein!
    """

    id: str                           # "reli_5", "wpf_9", "fs2_7"
    coupling_type: str                # "reli_ethik" / "wpf" / "band"
    involved_class_ids: list[str]     # ALLE beteiligten Klassen (z.B. ["5a","5b","5c","5d","5e","5f"])
    groups: list[CouplingGroup]       # Alle Gruppen dieser Kopplung
    hours_per_week: int               # Gesamtstunden der Kopplung pro Woche
    cross_class: bool = True          # True = klassenübergreifend (Standard)
    # Fach der Stundentafel, das diese Kopplung abdeckt, wenn es anders
    # heißt als die Fächer der Gruppen (z.B. "2. Fremdsprache").
    curriculum_subject: Optional[str] = None

    @field_validator("curriculum_subject")
    @classmethod
    def normalize_curriculum_subject(
        cls, value: Optional[str]
    ) -> Optional[str]:
        if value is None or not value.strip():
            return None
        return value.strip()

    def curriculum_subjects(self) -> set[str]:
        """Stundentafel-Fächer, die diese Kopplung für ihre Klassen abdeckt.

        Mit `curriculum_subject`: genau dieses Fach. WPF: die Gruppen
        heißen nach dem gewählten Fach (z.B. Informatik), in der
        Stundentafel steht aber "WPF". Sonst: die Fächer der Gruppen.
        """
        if self.curriculum_subject:
            return {self.curriculum_subject}
        if self.coupling_type == COUPLING_TYPE_WPF:
            return {WPF_CURRICULUM_SUBJECT}
        return {group.subject for group in self.groups}
