"""Vergleich zweier SchoolData-Datensätze (Diff / Changelog).

Gibt strukturierte Unterschiede zurück, die als Rich-Tabelle oder JSON
ausgegeben werden können.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models.school_data import SchoolData


@dataclass
class CurriculumChange:
    """Eine veränderte Stundenzahl für ein Fach in einer Klasse."""

    class_id: str
    subject: str
    old_hours: int
    new_hours: int


@dataclass
class DataDiff:
    """Vollständiger Diff zwischen zwei SchoolData-Datensätzen."""

    teachers_added: list[str] = field(default_factory=list)
    teachers_removed: list[str] = field(default_factory=list)
    curriculum_changes: list[CurriculumChange] = field(default_factory=list)
    coupling_changes: list[str] = field(default_factory=list)
    config_changes: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        """Gibt True zurück wenn kein Unterschied gefunden wurde."""
        return (
            not self.teachers_added
            and not self.teachers_removed
            and not self.curriculum_changes
            and not self.coupling_changes
            and not self.config_changes
        )

    def to_dict(self) -> dict:
        """Serialisiert den Diff als Dictionary (für JSON-Ausgabe)."""
        return {
            "teachers_added": self.teachers_added,
            "teachers_removed": self.teachers_removed,
            "curriculum_changes": [
                {
                    "class_id": c.class_id,
                    "subject": c.subject,
                    "old_hours": c.old_hours,
                    "new_hours": c.new_hours,
                }
                for c in self.curriculum_changes
            ],
            "coupling_changes": self.coupling_changes,
            "config_changes": self.config_changes,
        }

    def to_json(self, indent: int = 2) -> str:
        """Gibt den Diff als JSON-String zurück."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)


def diff_school_data(a: "SchoolData", b: "SchoolData") -> DataDiff:
    """Vergleicht zwei SchoolData-Datensätze und gibt einen strukturierten Diff zurück.

    Vergleicht:
    - Lehrer (hinzugefügt / entfernt)
    - Curriculum (Stundenzahlen pro Klasse × Fach)
    - Kopplungen (hinzugefügt / entfernt)
    - Konfiguration (school_name, bundesland, school_type, time_limit_seconds)

    Args:
        a: Erster Datensatz (Basis / alt).
        b: Zweiter Datensatz (neu).

    Returns:
        DataDiff mit allen gefundenen Unterschieden.
    """
    diff = DataDiff()

    # ── Lehrer ───────────────────────────────────────────────────────────────
    ids_a = {t.id for t in a.teachers}
    ids_b = {t.id for t in b.teachers}
    diff.teachers_added = sorted(ids_b - ids_a)
    diff.teachers_removed = sorted(ids_a - ids_b)

    # ── Curriculum ───────────────────────────────────────────────────────────
    classes_a = {c.id: c for c in a.classes}
    classes_b = {c.id: c for c in b.classes}
    common_classes = set(classes_a) & set(classes_b)

    for class_id in sorted(common_classes):
        curr_a = classes_a[class_id].curriculum
        curr_b = classes_b[class_id].curriculum
        all_subjects = set(curr_a) | set(curr_b)
        for subj in sorted(all_subjects):
            h_a = curr_a.get(subj, 0)
            h_b = curr_b.get(subj, 0)
            if h_a != h_b:
                diff.curriculum_changes.append(
                    CurriculumChange(
                        class_id=class_id,
                        subject=subj,
                        old_hours=h_a,
                        new_hours=h_b,
                    )
                )

    # ── Kopplungen ───────────────────────────────────────────────────────────
    coup_a = {c.id for c in a.couplings}
    coup_b = {c.id for c in b.couplings}
    for cid in sorted(coup_b - coup_a):
        diff.coupling_changes.append(f"Kopplung hinzugefügt: {cid}")
    for cid in sorted(coup_a - coup_b):
        diff.coupling_changes.append(f"Kopplung entfernt: {cid}")

    # ── Konfiguration ────────────────────────────────────────────────────────
    cfg_fields = [
        ("school_name", a.config.school_name, b.config.school_name),
        ("bundesland", a.config.bundesland, b.config.bundesland),
        (
            "school_type",
            a.config.school_type.value if hasattr(a.config.school_type, "value")
            else str(a.config.school_type),
            b.config.school_type.value if hasattr(b.config.school_type, "value")
            else str(b.config.school_type),
        ),
        (
            "time_limit_seconds",
            str(a.config.solver.time_limit_seconds),
            str(b.config.solver.time_limit_seconds),
        ),
    ]
    for key, val_a, val_b in cfg_fields:
        if val_a != val_b:
            diff.config_changes.append(f"{key}: {val_a!r} → {val_b!r}")

    return diff
