"""Untis XML Import (XSD 3.5 kompatibel).

Importiert Schuldaten aus einem Untis XML-Export und erzeugt SchoolData.
Verwendet nur stdlib xml.etree.ElementTree — keine zusätzlichen Abhängigkeiten.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from pydantic import BaseModel

from config.schema import SchoolConfig
from config.defaults import SUBJECT_METADATA
from models.teacher import Teacher
from models.school_class import SchoolClass
from models.subject import Subject
from models.room import Room
from models.coupling import Coupling
from models.school_data import SchoolData, FeasibilityReport


class ImportReport(BaseModel):
    """Bericht über den Untis-Import."""
    warnings: list[str] = []
    errors: list[str] = []
    teachers_imported: int = 0
    subjects_imported: int = 0
    classes_imported: int = 0
    rooms_imported: int = 0

    def print_rich(self) -> None:
        from rich.console import Console
        from rich.panel import Panel
        console = Console()
        lines = [f"[green]Lehrer: {self.teachers_imported}[/green]  "
                 f"[green]Fächer: {self.subjects_imported}[/green]  "
                 f"[green]Klassen: {self.classes_imported}[/green]  "
                 f"[green]Räume: {self.rooms_imported}[/green]"]
        if self.warnings:
            lines.append("\n[yellow]Warnungen:[/yellow]")
            for w in self.warnings:
                lines.append(f"  [yellow]• {w}[/yellow]")
        if self.errors:
            lines.append("\n[red]Fehler:[/red]")
            for e in self.errors:
                lines.append(f"  [red]• {e}[/red]")
        console.print(Panel("\n".join(lines), title="Untis XML Import", border_style="cyan"))


class UntisXmlImporter:
    """Importiert Schuldaten aus einem Untis XML-Export (XSD 3.5)."""

    def __init__(self, path: Path, config: SchoolConfig) -> None:
        self.path = Path(path)
        self.config = config
        self._report = ImportReport()
        self._root: Optional[ET.Element] = None

    def _parse_xml(self) -> None:
        """Parst die XML-Datei."""
        try:
            tree = ET.parse(str(self.path))
            self._root = tree.getroot()
        except ET.ParseError as e:
            raise ValueError(f"XML-Parse-Fehler: {e}")
        except FileNotFoundError:
            raise FileNotFoundError(f"Datei nicht gefunden: {self.path}")

    def _ensure_parsed(self) -> None:
        if self._root is None:
            self._parse_xml()

    def _find_section(self, tag: str) -> Optional[ET.Element]:
        """Sucht eine Sektion im XML (case-insensitive)."""
        self._ensure_parsed()
        for child in self._root:  # type: ignore[union-attr]
            if child.tag.lower() in (tag.lower(), tag.lower() + "s"):
                return child
        return None

    def _text(self, el: ET.Element, tag: str, default: str = "") -> str:
        """Gibt den Text eines Kind-Elements zurück."""
        child = el.find(tag)
        if child is None:
            child = el.find(tag.lower())
        if child is None:
            return el.get(tag, el.get(tag.lower(), default))
        return (child.text or default).strip()

    def import_subjects(self) -> list[Subject]:
        """Importiert Fächer aus <subjects>/<subject>."""
        self._ensure_parsed()
        known = set(SUBJECT_METADATA.keys())
        section = self._find_section("subjects")
        if section is None:
            self._report.warnings.append(
                "Keine <subjects>-Sektion gefunden — leere Fächerliste."
            )
            return []

        subjects = []
        for el in section:
            name = (
                self._text(el, "longname")
                or self._text(el, "name")
                or self._text(el, "shortname")
            )
            short = self._text(el, "shortname") or self._text(
                el, "name", name[:3] if name else "?"
            )
            if not name:
                continue
            if name not in known:
                import difflib
                matches = difflib.get_close_matches(name, list(known), n=1, cutoff=0.6)
                if matches:
                    self._report.warnings.append(
                        f"Fach '{name}' → gemappt auf '{matches[0]}'."
                    )
                    name = matches[0]
                    meta = SUBJECT_METADATA[name]
                else:
                    self._report.warnings.append(
                        f"Fach '{name}' (Kürzel: {short}) nicht in SUBJECT_METADATA — "
                        "wird als 'sonstig' importiert."
                    )
                    subjects.append(Subject(
                        name=name, short_name=short, category="sonstig",
                        is_hauptfach=False, requires_special_room=None,
                        double_lesson_required=False, double_lesson_preferred=False,
                    ))
                    continue

            meta = SUBJECT_METADATA[name]
            subjects.append(Subject(
                name=name,
                short_name=meta["short"],
                category=meta["category"],
                is_hauptfach=meta["is_hauptfach"],
                requires_special_room=meta.get("room"),
                double_lesson_required=meta.get("double_required", False),
                double_lesson_preferred=meta.get("double_preferred", False),
            ))

        self._report.subjects_imported = len(subjects)
        return subjects

    def import_teachers(self) -> list[Teacher]:
        """Importiert Lehrer aus <teachers>/<teacher>."""
        self._ensure_parsed()
        tc = self.config.teachers
        section = self._find_section("teachers")
        if section is None:
            self._report.warnings.append("Keine <teachers>-Sektion gefunden.")
            return []

        teachers = []
        used_ids: set = set()
        for el in section:
            id_ = (
                self._text(el, "id") or self._text(el, "shortname", "")
            ).upper()
            name_raw = (
                self._text(el, "surname")
                or self._text(el, "longname")
                or self._text(el, "name")
            )
            firstname = self._text(el, "firstname") or self._text(el, "forename")
            name = (
                f"{name_raw}, {firstname}".strip(", ") if firstname else name_raw
            )

            if not id_ or id_ in used_ids:
                continue
            used_ids.add(id_)

            subj_raw = self._text(el, "subjects")
            subjects = (
                [s.strip() for s in subj_raw.split(",") if s.strip()]
                if subj_raw else []
            )
            valid_subjects = [s for s in subjects if s in SUBJECT_METADATA]
            if subjects and not valid_subjects:
                self._report.warnings.append(
                    f"Lehrer {id_}: Keine bekannten Fächer in '{subj_raw}'."
                )

            dep = tc.vollzeit_deputat
            dep_max = dep + tc.deputat_max_buffer
            dep_min = max(1, round(dep_max * tc.deputat_min_fraction))

            teachers.append(Teacher(
                id=id_,
                name=name or id_,
                subjects=valid_subjects or ["Deutsch"],
                deputat_max=dep_max,
                deputat_min=dep_min,
                is_teilzeit=False,
            ))

        self._report.teachers_imported = len(teachers)
        return teachers

    def import_classes(
        self, stundentafel: dict
    ) -> list[SchoolClass]:
        """Importiert Klassen aus <classes>/<class>."""
        self._ensure_parsed()
        sek1_max = self.config.time_grid.sek1_max_slot
        section = self._find_section("classes")
        if section is None:
            self._report.warnings.append("Keine <classes>-Sektion gefunden.")
            return []

        classes = []
        for el in section:
            id_ = self._text(el, "id") or self._text(el, "shortname")
            name = (
                self._text(el, "name")
                or self._text(el, "longname")
                or id_
            )
            grade_raw = self._text(el, "grade") or self._text(el, "classlevel")
            if not id_:
                continue
            try:
                grade = int(float(grade_raw)) if grade_raw else 0
            except ValueError:
                grade = 0

            curriculum = stundentafel.get(grade, {})
            classes.append(SchoolClass(
                id=id_,
                grade=grade,
                label=name,
                curriculum=curriculum,
                max_slot=sek1_max,
            ))

        self._report.classes_imported = len(classes)
        return classes

    def import_rooms(self) -> list[Room]:
        """Importiert Räume aus <rooms>/<room>."""
        self._ensure_parsed()
        section = self._find_section("rooms")
        if section is None:
            self._report.warnings.append(
                "Keine <rooms>-Sektion gefunden — leere Raumliste."
            )
            return []

        rooms = []
        for el in section:
            id_ = self._text(el, "id") or self._text(el, "shortname")
            name = (
                self._text(el, "name")
                or self._text(el, "longname")
                or id_
            )
            if not id_:
                continue
            rooms.append(Room(id=id_, room_type="allgemein", name=name))

        self._report.rooms_imported = len(rooms)
        return rooms

    def import_all(
        self, stundentafel: Optional[dict] = None
    ) -> "tuple[SchoolData, ImportReport]":
        """Importiert alle Daten und gibt SchoolData + ImportReport zurück."""
        from config.defaults import STUNDENTAFEL_GYMNASIUM_SEK1
        if stundentafel is None:
            stundentafel = dict(STUNDENTAFEL_GYMNASIUM_SEK1)

        subjects = self.import_subjects()
        teachers = self.import_teachers()
        classes = self.import_classes(stundentafel)
        rooms = self.import_rooms()

        if not subjects:
            subjects = [
                Subject(
                    name=n, short_name=m["short"], category=m["category"],
                    is_hauptfach=m["is_hauptfach"],
                    requires_special_room=m.get("room"),
                    double_lesson_required=m.get("double_required", False),
                    double_lesson_preferred=m.get("double_preferred", False),
                )
                for n, m in SUBJECT_METADATA.items()
            ]

        school_data = SchoolData(
            subjects=subjects,
            rooms=rooms,
            classes=classes,
            teachers=teachers,
            couplings=[],
            config=self.config,
        )
        return school_data, self._report


def import_from_untis(
    path: Path,
    config: SchoolConfig,
    stundentafel: Optional[dict] = None,
) -> "tuple[SchoolData, ImportReport]":
    """Top-Level Funktion: Importiert Untis XML → SchoolData."""
    importer = UntisXmlImporter(path, config)
    return importer.import_all(stundentafel)
