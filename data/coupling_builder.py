"""Baut Kopplungen mit parallelen Gruppen (Reli, WPF, Sprachen-Schiene)."""

from typing import Optional

from config.defaults import SUBJECT_METADATA
from models.coupling import Coupling, CouplingGroup

RELIGION_SUBJECT = "Religion"
# (Bezeichnung der Gruppe, unterrichtetes Fach)
GroupKind = tuple[str, str]


def reli_group_subject(group_name: str) -> str:
    """Fach einer Reli-Gruppe.

    Heißt die Gruppe wie ein Fach der Vorschlagsliste ("ethik",
    "Praktische Philosophie"), dann dieses Fach; sonst Religion
    ("evangelisch", "katholisch").
    """
    by_key = {name.lower(): name for name in SUBJECT_METADATA}
    return by_key.get(group_name.strip().lower(), RELIGION_SUBJECT)


def parallel_groups(
    kinds: list[GroupKind], group_count: int, hours: int
) -> list[CouplingGroup]:
    """`group_count` Gruppen (mindestens eine je Art), reihum verteilt.

    Die Gruppen heißen "<Bezeichnung> <laufende Nummer>".
    """
    count = max(group_count, len(kinds))
    groups: list[CouplingGroup] = []
    for index in range(count):
        label, subject = kinds[index % len(kinds)]
        groups.append(CouplingGroup(
            group_name=f"{label} {index // len(kinds) + 1}",
            subject=subject,
            hours_per_week=hours,
        ))
    return groups


def parallel_coupling(
    coupling_id: str,
    coupling_type: str,
    class_ids: list[str],
    kinds: list[GroupKind],
    hours: int,
    curriculum_subject: Optional[str] = None,
) -> Coupling:
    """Kopplung über `class_ids` mit einer Gruppe je Klasse."""
    return Coupling(
        id=coupling_id,
        coupling_type=coupling_type,
        involved_class_ids=class_ids,
        groups=parallel_groups(kinds, len(class_ids), hours),
        hours_per_week=hours,
        cross_class=True,
        curriculum_subject=curriculum_subject,
    )
