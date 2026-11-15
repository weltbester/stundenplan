"""Excel-Import und Template-Generator für echte Schuldaten.

Template-Generator: Leere Excel-Vorlage mit vorausgefüllten Blättern.
Import-Funktion:    Excel → SchoolData mit Validierung und FeasibilityReport.
"""

import difflib
from pathlib import Path
from typing import Optional

from config.schema import SchoolConfig
from config.defaults import STUNDENTAFEL_GYMNASIUM_SEK1, SUBJECT_METADATA
from models.teacher import Teacher
from models.school_class import SchoolClass
from models.subject import Subject
from models.room import Room
from models.coupling import Coupling, CouplingGroup
from models.fixed_assignment import (
    FixedAssignment, coupling_subjects_by_class,
)
from models.school_data import SchoolData, FeasibilityReport


class ExcelImportError(Exception):
    """Fehler beim Excel-Import."""


# ─── Blatt "Unterrichtsverteilung" ────────────────────────────────────────────

ASSIGNMENT_SHEET = "Unterrichtsverteilung"
CLASS_HEADER = "Klasse"
# Zellmarken der Vorlage: Fach wird nicht unterrichtet / läuft über Kopplung
NOT_TAUGHT_MARK = "–"
COUPLING_MARK = "Kopplung"
HINT_PREFIX = "Hinweis"
ASSIGNMENT_HINT = (
    f"{HINT_PREFIX}: In die Zelle das Kürzel der Lehrkraft eintragen. "
    f"Leer = der Solver entscheidet. '{NOT_TAUGHT_MARK}' = Fach wird in "
    f"dieser Klasse nicht unterrichtet. '{COUPLING_MARK}' = Lehrkraft im "
    f"Blatt 'Kopplungen' angeben (Name:Fach:Std:Kürzel)."
)
# Zellinhalte (kleingeschrieben), die wie eine leere Zelle behandelt werden
_BLANK_CELL_MARKS = frozenset({"", "–", "-", "—", COUPLING_MARK.lower()})
_DEFAULT_CLASS_LABELS = "abcdefghij"
_HEADER_COLOR = "2E6DA4"
_LOCKED_COLOR = "E0E0E0"
_BORDER_COLOR = "BBBBBB"
_CLASS_COLUMN_WIDTH = 10
_SUBJECT_COLUMN_WIDTH = 13


# ─── Tages-Mapping ────────────────────────────────────────────────────────────

_DAY_MAP = {"mo": 0, "di": 1, "mi": 2, "do": 3, "fr": 4,
            "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3, "freitag": 4}

_DAY_NAMES = ["Mo", "Di", "Mi", "Do", "Fr"]


def _parse_blocked_slots(raw: str) -> list[tuple[int, int]]:
    """Parst Sperrzeiten-String 'Mo1,Di3,Fr5' → [(0,1),(1,3),(4,5)]."""
    if not raw.strip():
        return []
    result = []
    for token in raw.replace(";", ",").split(","):
        token = token.strip().lower()
        if not token:
            continue
        # Trenne Tages-Buchstaben von Slot-Zahl
        for prefix in sorted(_DAY_MAP, key=len, reverse=True):
            if token.startswith(prefix):
                slot_str = token[len(prefix):]
                try:
                    slot = int(slot_str)
                    result.append((_DAY_MAP[prefix], slot))
                except ValueError:
                    pass  # Ignoriere ungültige Tokens
                break
    return result


def _parse_free_days(raw: str) -> list[int]:
    """Parst Wunschtage-String 'Mo,Fr' → [0,4]."""
    if not raw.strip():
        return []
    result = []
    for token in raw.replace(";", ",").split(","):
        token = token.strip().lower()
        if token in _DAY_MAP:
            day = _DAY_MAP[token]
            if day not in result:
                result.append(day)
    return result


def _fuzzy_subject(name: str, known: list[str]) -> Optional[str]:
    """Fuzzy-Matching: Findet das ähnlichste bekannte Fach."""
    matches = difflib.get_close_matches(name, known, n=1, cutoff=0.6)
    return matches[0] if matches else None


def _cell_text(row: tuple, column: int) -> str:
    """Zellinhalt als getrimmter Text; leere/fehlende Zelle → ''."""
    if column >= len(row) or row[column] is None:
        return ""
    return str(row[column]).strip()


def _cell_ref(column: int, row_number: int) -> str:
    """Excel-Zellbezug (z.B. 'C5') für 0-basierte Spalte, 1-basierte Zeile."""
    from openpyxl.utils import get_column_letter

    return f"{get_column_letter(column + 1)}{row_number}"


# ─── TEMPLATE-GENERATOR ───────────────────────────────────────────────────────

def generate_template(config: SchoolConfig, path: Path) -> None:
    """Erzeugt eine leere Excel-Vorlage mit vorausgefüllten Blättern.

    Blätter:
      - Zeitraster:    Slot-Nr, Start, Ende, SII-only (aus Config)
      - Jahrgänge:     Jahrgang, Klassen, Soll-Stunden (aus Config)
      - Stundentafel:  Jahrgang × Fächer Matrix (aus STUNDENTAFEL)
      - Lehrkräfte:    Eingabe-Vorlage mit Beispielzeile
      - Fachräume:     Raumtyp, Name, Anzahl
      - Kopplungen:    Jahrgang, Typ, Klassen, Gruppen, Stunden
      - Unterrichtsverteilung: Matrix Klasse × Fach (Kürzel je Zelle)
    """
    try:
        import openpyxl
        from openpyxl.styles import (
            Font, PatternFill, Alignment, Border, Side
        )
        from openpyxl.utils import get_column_letter
        from openpyxl.worksheet.datavalidation import DataValidation
    except ImportError:
        raise ImportError("openpyxl nicht installiert. Bitte: pip install openpyxl")

    wb = openpyxl.Workbook()

    # ── Hilfs-Styles ─────────────────────────────────────────────────────────
    hdr_font = Font(bold=True, color="FFFFFF", size=11)
    hdr_fill = PatternFill("solid", fgColor="2E6DA4")
    alt_fill = PatternFill("solid", fgColor="D6E4F0")
    ex_font = Font(italic=True, color="888888")
    ex_fill = PatternFill("solid", fgColor="F5F5F5")
    center = Alignment(horizontal="center", vertical="center")
    thin = Side(style="thin", color="BBBBBB")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    def style_header(cell, width: int = 14):
        cell.font = hdr_font
        cell.fill = hdr_fill
        cell.alignment = center
        cell.border = border

    def style_data(cell, alt: bool = False):
        cell.fill = alt_fill if alt else PatternFill()
        cell.alignment = Alignment(vertical="center")
        cell.border = border

    def style_example(cell):
        cell.font = ex_font
        cell.fill = ex_fill
        cell.border = border

    def set_col_width(ws, col: int, width: float):
        ws.column_dimensions[get_column_letter(col)].width = width

    def write_row(ws, row: int, values: list, style_fn=style_data, alt: bool = False):
        for col, val in enumerate(values, 1):
            cell = ws.cell(row=row, column=col, value=val)
            style_fn(cell) if style_fn != style_data else style_fn(cell, alt=alt)

    # ── Blatt 1: Zeitraster ───────────────────────────────────────────────────
    ws_zt = wb.active
    ws_zt.title = "Zeitraster"
    headers = ["Slot-Nr", "Beginn", "Ende", "SII-only"]
    for col, h in enumerate(headers, 1):
        cell = ws_zt.cell(row=1, column=col, value=h)
        style_header(cell)
    set_col_width(ws_zt, 1, 10)
    set_col_width(ws_zt, 2, 10)
    set_col_width(ws_zt, 3, 10)
    set_col_width(ws_zt, 4, 12)

    for r, slot in enumerate(config.time_grid.lesson_slots, 2):
        row_vals = [slot.slot_number, slot.start_time, slot.end_time,
                    "ja" if slot.is_sek2_only else "nein"]
        alt = (r % 2 == 0)
        for col, val in enumerate(row_vals, 1):
            cell = ws_zt.cell(row=r, column=col, value=val)
            style_data(cell, alt=alt)

    # ── Blatt 2: Jahrgänge ────────────────────────────────────────────────────
    ws_jg = wb.create_sheet("Jahrgänge")
    headers = ["Jahrgang", "Anzahl Klassen", "Soll-Stunden/Woche", "Klassen-Buchstaben"]
    for col, h in enumerate(headers, 1):
        style_header(ws_jg.cell(row=1, column=col, value=h))
    for w, width in zip(range(1, 5), [12, 16, 18, 24]):
        set_col_width(ws_jg, w, width)

    for r, gd in enumerate(config.grades.grades, 2):
        labels = gd.class_labels or list("abcdefghij"[:gd.num_classes])
        row_vals = [gd.grade, gd.num_classes, gd.weekly_hours_target, ", ".join(labels)]
        alt = (r % 2 == 0)
        for col, val in enumerate(row_vals, 1):
            style_data(ws_jg.cell(row=r, column=col, value=val), alt=alt)

    # ── Blatt 3: Stundentafel ─────────────────────────────────────────────────
    ws_st = wb.create_sheet("Stundentafel")
    all_subjects = list(SUBJECT_METADATA.keys())
    grade_nums = sorted(STUNDENTAFEL_GYMNASIUM_SEK1.keys())

    # Kopfzeile: Jahrgang-Spalten
    style_header(ws_st.cell(row=1, column=1, value="Fach"))
    for col, grade in enumerate(grade_nums, 2):
        style_header(ws_st.cell(row=1, column=col, value=f"Jg. {grade}"))

    set_col_width(ws_st, 1, 16)
    for col in range(2, len(grade_nums) + 2):
        set_col_width(ws_st, col, 10)

    for r, subj in enumerate(all_subjects, 2):
        alt = (r % 2 == 0)
        style_data(ws_st.cell(row=r, column=1, value=subj), alt=alt)
        for col, grade in enumerate(grade_nums, 2):
            hours = STUNDENTAFEL_GYMNASIUM_SEK1.get(grade, {}).get(subj, 0)
            cell = ws_st.cell(row=r, column=col, value=hours if hours else "")
            style_data(cell, alt=alt)

    # ── Blatt 4: Lehrkräfte ───────────────────────────────────────────────────
    ws_lk = wb.create_sheet("Lehrkräfte")
    lk_headers = [
        "Name (Nachname, Vorname)", "Kürzel", "Fach 1", "Fach 2", "Fach 3",
        "Deputat", "Teilzeit", "Sperrzeiten (z.B. Mo1,Di3,Fr5)",
        "Wunschtage (z.B. Mo,Fr)", "Max Std/Tag", "Max Springstd/Tag",
    ]
    for col, h in enumerate(lk_headers, 1):
        style_header(ws_lk.cell(row=1, column=col, value=h))

    widths_lk = [28, 10, 16, 16, 16, 10, 10, 26, 22, 12, 16]
    for col, w in enumerate(widths_lk, 1):
        set_col_width(ws_lk, col, w)

    # Beispielzeile (kursiv)
    example_row = [
        "Müller, Hans", "MÜL", "Mathematik", "Physik", "",
        26, "nein", "Mi5", "Fr", 6, 2,
    ]
    for col, val in enumerate(example_row, 1):
        style_example(ws_lk.cell(row=2, column=col, value=val))
    ws_lk.cell(row=2, column=1).comment = None

    # Dropdown-Validierung für Fächer (Spalten 3-5)
    subject_list = ",".join(all_subjects)
    # openpyxl DataValidation: Dropdown via formula (list muss kurz sein)
    # Wegen Längenbeschränkung: nur Formel-basiert mit benanntem Bereich oder direkt
    # Für Excel-Kompatibilität: Dropdown über explizite Liste (max 255 Zeichen)
    # Kürzel der Fächer passen; Vollnamen ggf. zu lang → separate Hilfsliste
    dv_subject = DataValidation(
        type="list",
        formula1='"' + ",".join(all_subjects[:20]) + '"',  # Ersten 20 Fächer
        allow_blank=True,
        showDropDown=False,
    )
    dv_subject.sqref = "C3:E200"
    ws_lk.add_data_validation(dv_subject)

    dv_teilzeit = DataValidation(
        type="list",
        formula1='"ja,nein"',
        allow_blank=False,
        showDropDown=False,
    )
    dv_teilzeit.sqref = "G3:G200"
    ws_lk.add_data_validation(dv_teilzeit)

    # ── Blatt 5: Fachräume ────────────────────────────────────────────────────
    ws_fr = wb.create_sheet("Fachräume")
    fr_headers = ["Raumtyp (intern)", "Anzeigename", "Anzahl"]
    for col, h in enumerate(fr_headers, 1):
        style_header(ws_fr.cell(row=1, column=col, value=h))
    set_col_width(ws_fr, 1, 18)
    set_col_width(ws_fr, 2, 22)
    set_col_width(ws_fr, 3, 10)

    for r, room_def in enumerate(config.rooms.special_rooms, 2):
        alt = (r % 2 == 0)
        row_vals = [room_def.room_type, room_def.display_name, room_def.count]
        for col, val in enumerate(row_vals, 1):
            style_data(ws_fr.cell(row=r, column=col, value=val), alt=alt)

    # Beispielzeile
    example_fr = ["sport", "Sporthalle", 2]
    for col, val in enumerate(example_fr, 1):
        style_example(ws_fr.cell(row=len(config.rooms.special_rooms) + 2, column=col, value=val))

    # ── Blatt 6: Kopplungen ───────────────────────────────────────────────────
    ws_kp = wb.create_sheet("Kopplungen")
    kp_headers = [
        "ID", "Typ (reli_ethik/wpf)", "Beteiligte Klassen (kommagetrennt)",
        "Gruppen (Name:Fach:Std[:Kürzel], kommagetrennt)",
        "Stunden/Woche", "Klassenübergreifend",
    ]
    for col, h in enumerate(kp_headers, 1):
        style_header(ws_kp.cell(row=1, column=col, value=h))
    widths_kp = [14, 20, 34, 42, 14, 18]
    for col, w in enumerate(widths_kp, 1):
        set_col_width(ws_kp, col, w)

    # Beispiel-Kopplung
    ex_kp = [
        "reli_5", "reli_ethik", "5a,5b,5c,5d,5e,5f",
        "evangelisch:Religion:2,katholisch:Religion:2,ethik:Ethik:2",
        2, "ja",
    ]
    for col, val in enumerate(ex_kp, 1):
        style_example(ws_kp.cell(row=2, column=col, value=val))

    # ── Blatt 7: Unterrichtsverteilung ────────────────────────────────────────
    _write_assignment_sheet(wb, config)

    # ── Speichern ─────────────────────────────────────────────────────────────
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))


def _template_classes(config: SchoolConfig) -> list[tuple[str, int]]:
    """(Klassen-ID, Jahrgang) für alle Klassen der Konfiguration."""
    classes: list[tuple[str, int]] = []
    for grade_def in config.grades.grades:
        labels = grade_def.class_labels or list(
            _DEFAULT_CLASS_LABELS[:grade_def.num_classes]
        )
        classes.extend((f"{grade_def.grade}{label}", grade_def.grade)
                       for label in labels)
    return classes


def _config_coupled_subjects(config: SchoolConfig, grade: int) -> set[str]:
    """Fächer, die laut Konfiguration im Jahrgang über Kopplungen laufen."""
    coupling_config = config.couplings
    coupled: set[str] = set()
    if coupling_config.reli_ethik_enabled:
        coupled.update({"Religion", "Ethik"})
    if coupling_config.wpf_enabled and grade >= coupling_config.wpf_start_grade:
        coupled.add("WPF")
    return coupled


def _assignment_cell_mark(
    config: SchoolConfig, grade: int, subject: str
) -> Optional[str]:
    """Vorbelegung einer Matrix-Zelle; None = Zelle ist auszufüllen."""
    hours = STUNDENTAFEL_GYMNASIUM_SEK1.get(grade, {}).get(subject, 0)
    if hours <= 0:
        return NOT_TAUGHT_MARK
    if subject in _config_coupled_subjects(config, grade):
        return COUPLING_MARK
    return None


def _write_assignment_sheet(workbook, config: SchoolConfig) -> None:
    """Matrix Klasse × Fach für die vorgegebene Unterrichtsverteilung."""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    side = Side(style="thin", color=_BORDER_COLOR)
    border = Border(left=side, right=side, top=side, bottom=side)
    center = Alignment(horizontal="center", vertical="center")
    header_font = Font(bold=True, color="FFFFFF", size=11)
    header_fill = PatternFill("solid", fgColor=_HEADER_COLOR)
    locked_fill = PatternFill("solid", fgColor=_LOCKED_COLOR)

    classes = _template_classes(config)
    grades = {grade for _, grade in classes}
    subjects = [
        name for name in SUBJECT_METADATA
        if any(STUNDENTAFEL_GYMNASIUM_SEK1.get(g, {}).get(name, 0) > 0
               for g in grades)
    ]

    sheet = workbook.create_sheet(ASSIGNMENT_SHEET)
    for column, title in enumerate([CLASS_HEADER] + subjects, 1):
        cell = sheet.cell(row=1, column=column, value=title)
        cell.font, cell.fill = header_font, header_fill
        cell.alignment, cell.border = center, border
        width = _CLASS_COLUMN_WIDTH if column == 1 else _SUBJECT_COLUMN_WIDTH
        sheet.column_dimensions[get_column_letter(column)].width = width

    for row, (class_id, grade) in enumerate(classes, 2):
        class_cell = sheet.cell(row=row, column=1, value=class_id)
        class_cell.font, class_cell.border = Font(bold=True), border
        for column, subject in enumerate(subjects, 2):
            mark = _assignment_cell_mark(config, grade, subject)
            cell = sheet.cell(row=row, column=column, value=mark)
            cell.alignment, cell.border = center, border
            if mark is not None:
                cell.fill = locked_fill

    hint_row = len(classes) + 3
    sheet.cell(row=hint_row, column=1, value=ASSIGNMENT_HINT).font = Font(
        italic=True
    )
    sheet.freeze_panes = "B2"


# ─── IMPORT ───────────────────────────────────────────────────────────────────

class ExcelImporter:
    """Importiert Schuldaten aus einer Excel-Vorlage."""

    def __init__(self, path: Path, config: SchoolConfig) -> None:
        self.path = Path(path)
        self.config = config
        self._wb = None
        self._known_subjects = list(SUBJECT_METADATA.keys())
        self._errors: list[str] = []
        self._warnings: list[str] = []

    def _open(self):
        try:
            import openpyxl
            self._wb = openpyxl.load_workbook(
                str(self.path), read_only=True, data_only=True
            )
        except FileNotFoundError:
            raise ExcelImportError(f"Datei nicht gefunden: {self.path}")
        except Exception as e:
            raise ExcelImportError(f"Fehler beim Öffnen der Excel-Datei: {e}")

    def _get_sheet(self, name: str):
        if self._wb is None:
            self._open()
        for sn in self._wb.sheetnames:
            if sn.strip().lower() == name.strip().lower():
                return self._wb[sn]
        return None

    def _sheet_rows(self, sheet) -> list[dict]:
        """Tabellenblatt → Liste von Dicts (erste Zeile = Header)."""
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [
            str(h).strip().lower() if h is not None else f"col_{i}"
            for i, h in enumerate(rows[0])
        ]
        result = []
        for row in rows[1:]:
            if all(v is None for v in row):
                continue
            result.append({
                headers[i]: (str(v).strip() if v is not None else "")
                for i, v in enumerate(row)
                if i < len(headers)
            })
        return result

    def _parse_subject(self, raw: str, row_id: str) -> Optional[str]:
        """Normalisiert und validiert einen Fachnamen. Fuzzy-matching bei Tippfehlern."""
        name = raw.strip()
        if not name:
            return None
        if name in self._known_subjects:
            return name
        match = _fuzzy_subject(name, self._known_subjects)
        if match:
            self._warnings.append(
                f"{row_id}: Fach '{name}' unbekannt → meinten Sie '{match}'? "
                f"Wird als '{match}' importiert."
            )
            return match
        self._errors.append(
            f"{row_id}: Unbekanntes Fach '{name}'. "
            f"Ähnliche Fächer: {', '.join(difflib.get_close_matches(name, self._known_subjects, n=3, cutoff=0.4)) or 'keine'}"
        )
        return None

    # ── Zeitraster ──────────────────────────────────────────────────────────

    def import_time_grid(self):
        """Importiert das Zeitraster aus Blatt 'Zeitraster' und überschreibt Config."""
        from config.schema import LessonSlot, TimeGridConfig

        sheet = self._get_sheet("Zeitraster")
        if sheet is None:
            return  # Optional, kein Fehler

        rows = self._sheet_rows(sheet)
        new_slots = []
        for i, row in enumerate(rows, 2):
            slot_raw = row.get("slot-nr", row.get("slot_nr", ""))
            start = row.get("beginn", row.get("start", ""))
            end = row.get("ende", row.get("end", ""))
            sii_raw = row.get("sii-only", row.get("sii_only", "nein")).lower()

            try:
                slot_num = int(float(slot_raw)) if slot_raw else None
                if slot_num is None:
                    continue
                new_slots.append(LessonSlot(
                    slot_number=slot_num,
                    start_time=start or "00:00",
                    end_time=end or "00:00",
                    is_sek2_only=sii_raw in ("ja", "yes", "true", "1", "x"),
                ))
            except Exception as e:
                self._warnings.append(f"Zeitraster Zeile {i}: Übersprungen ({e})")

        if new_slots:
            # Überschreibt lesson_slots, behält pauses/double_blocks
            self.config = self.config.model_copy(update={
                "time_grid": self.config.time_grid.model_copy(
                    update={"lesson_slots": new_slots}
                )
            })

    # ── Lehrkräfte ─────────────────────────────────────────────────────────

    def import_teachers(self) -> list[Teacher]:
        sheet = self._get_sheet("Lehrkräfte")
        if sheet is None:
            raise ExcelImportError(
                "Tabellenblatt 'Lehrkräfte' nicht gefunden."
            )
        rows = self._sheet_rows(sheet)
        teachers = []
        used_ids: set[str] = set()
        tc = self.config.teachers

        for i, row in enumerate(rows, 2):
            # Beispielzeilen (kursiv-Marker) überspringen anhand von Kürzel = MÜL
            abbr = row.get("kürzel", row.get("kurzel", "")).strip().upper()
            name = row.get("name (nachname, vorname)", row.get("name", "")).strip()

            if not abbr or abbr == "MÜL":
                continue  # Beispielzeile
            if abbr in used_ids:
                self._errors.append(f"Zeile {i}: Doppeltes Kürzel '{abbr}'")
                continue
            used_ids.add(abbr)

            # Fächer
            subjects = []
            for fach_key in ["fach 1", "fach1", "fach 2", "fach2", "fach 3", "fach3"]:
                raw = row.get(fach_key, "").strip()
                if raw:
                    s = self._parse_subject(raw, f"Zeile {i}, Kürzel {abbr}")
                    if s:
                        subjects.append(s)

            # Deputat
            dep_raw = row.get("deputat", "").strip()
            try:
                deputat = int(float(dep_raw)) if dep_raw else tc.vollzeit_deputat
            except ValueError:
                self._warnings.append(f"Zeile {i}: Ungültiges Deputat '{dep_raw}' → {tc.vollzeit_deputat}h")
                deputat = tc.vollzeit_deputat

            # Teilzeit
            tz_raw = row.get("teilzeit", "nein").strip().lower()
            is_teilzeit = tz_raw in ("ja", "yes", "true", "1", "x")

            # Sperrzeiten
            blocked_raw = row.get("sperrzeiten (z.b. mo1,di3,fr5)",
                                  row.get("sperrzeiten", ""))
            unavailable = _parse_blocked_slots(blocked_raw)

            # Wunschtage
            wishes_raw = row.get("wunschtage (z.b. mo,fr)",
                                 row.get("wunschtage", ""))
            free_days = _parse_free_days(wishes_raw)

            # Max Std/Tag
            max_h_raw = row.get("max std/tag", row.get("max_std_tag", "")).strip()
            try:
                max_h = int(float(max_h_raw)) if max_h_raw else tc.max_hours_per_day
            except ValueError:
                max_h = tc.max_hours_per_day

            # Max Springstd/Tag
            max_g_raw = row.get("max springstd/tag", row.get("max_springstd", "")).strip()
            try:
                max_g = int(float(max_g_raw)) if max_g_raw else tc.max_gaps_per_day
            except ValueError:
                max_g = tc.max_gaps_per_day

            deputat_max = deputat + tc.deputat_max_buffer
            deputat_min = max(1, round(deputat_max * tc.deputat_min_fraction))
            teachers.append(Teacher(
                id=abbr,
                name=name,
                subjects=subjects,
                deputat_max=deputat_max,
                deputat_min=deputat_min,
                is_teilzeit=is_teilzeit,
                unavailable_slots=unavailable,
                preferred_free_days=free_days,
                max_hours_per_day=max_h,
                max_gaps_per_day=max_g,
            ))

        if not teachers:
            raise ExcelImportError(
                "Keine Lehrkräfte gefunden. Bitte Tabellenblatt 'Lehrkräfte' prüfen."
            )
        return teachers

    # ── Fachräume ──────────────────────────────────────────────────────────

    def import_rooms(self) -> list[Room]:
        sheet = self._get_sheet("Fachräume")
        if sheet is None:
            return []  # Optional

        rows = self._sheet_rows(sheet)
        rooms = []
        for i, row in enumerate(rows, 2):
            rtype = row.get("raumtyp (intern)", row.get("raumtyp", "")).strip().lower()
            name = row.get("anzeigename", row.get("name", "")).strip()
            count_raw = row.get("anzahl", "1").strip()

            if not rtype or rtype in ("raumtyp", "beispiel"):
                continue  # Header/Beispiel überspringen

            try:
                count = int(float(count_raw)) if count_raw else 1
            except ValueError:
                count = 1

            prefix = rtype[:2].upper()
            for idx in range(1, count + 1):
                rooms.append(Room(
                    id=f"{prefix}{idx}",
                    room_type=rtype,
                    name=f"{name} {idx}" if count > 1 else name,
                ))

        return rooms

    # ── Klassen aus Jahrgänge-Blatt ────────────────────────────────────────

    def import_classes(self) -> list[SchoolClass]:
        sheet = self._get_sheet("Jahrgänge")
        if sheet is None:
            # Fallback: Klassen aus Config ableiten
            return []

        rows = self._sheet_rows(sheet)
        classes = []
        sek1_max = self.config.time_grid.sek1_max_slot

        for i, row in enumerate(rows, 2):
            grade_raw = row.get("jahrgang", "").strip()
            num_raw = row.get("anzahl klassen", row.get("klassen", "")).strip()

            if not grade_raw:
                continue
            try:
                grade = int(float(grade_raw))
            except ValueError:
                self._warnings.append(f"Jahrgänge Zeile {i}: Ungültiger Jahrgang '{grade_raw}'")
                continue

            try:
                num_classes = int(float(num_raw)) if num_raw else 1
            except ValueError:
                num_classes = 1

            curriculum = {
                f: h
                for f, h in STUNDENTAFEL_GYMNASIUM_SEK1.get(grade, {}).items()
                if h > 0
            }

            labels = list("abcdefghij"[:num_classes])
            for label in labels:
                classes.append(SchoolClass(
                    id=f"{grade}{label}",
                    grade=grade,
                    label=label,
                    curriculum=curriculum.copy(),
                    max_slot=sek1_max,
                ))

        return classes

    # ── Kopplungen ─────────────────────────────────────────────────────────

    def import_couplings(self) -> list[Coupling]:
        sheet = self._get_sheet("Kopplungen")
        if sheet is None:
            return []

        rows = self._sheet_rows(sheet)
        couplings = []

        for i, row in enumerate(rows, 2):
            cid = row.get("id", "").strip()
            ctype = row.get("typ (reli_ethik/wpf)", row.get("typ", "")).strip().lower()
            classes_raw = row.get("beteiligte klassen (kommagetrennt)",
                                  row.get("klassen", "")).strip()
            groups_raw = row.get(
                "gruppen (name:fach:std[:kürzel], kommagetrennt)",
                row.get("gruppen (name:fach:std, kommagetrennt)",
                        row.get("gruppen", "")),
            ).strip()
            hours_raw = row.get("stunden/woche", row.get("stunden", "2")).strip()
            cross_raw = row.get("klassenübergreifend", "ja").strip().lower()

            if not cid or cid.startswith("id"):
                continue  # Header/Beispiel

            class_ids = [c.strip() for c in classes_raw.split(",") if c.strip()]

            # Gruppen parsen: "Name:Fach:Std[:Kürzel],..."
            groups = []
            for gpart in groups_raw.split(","):
                parts = gpart.strip().split(":")
                if len(parts) >= 2:
                    gname = parts[0].strip()
                    gsubj = parts[1].strip() if len(parts) > 1 else ""
                    ghours_raw = parts[2].strip() if len(parts) > 2 else ""
                    try:
                        ghours = int(ghours_raw) if ghours_raw else 2
                    except ValueError:
                        ghours = 2
                    teacher_id = parts[3] if len(parts) > 3 else None
                    groups.append(CouplingGroup(
                        group_name=gname,
                        subject=gsubj,
                        hours_per_week=ghours,
                        teacher_id=teacher_id,
                    ))

            try:
                hours = int(float(hours_raw)) if hours_raw else 2
            except ValueError:
                hours = 2

            cross = cross_raw not in ("nein", "no", "false", "0")

            if not groups:
                self._warnings.append(f"Kopplung Zeile {i}: Keine Gruppen definiert für '{cid}'")

            couplings.append(Coupling(
                id=cid,
                coupling_type=ctype or "wpf",
                involved_class_ids=class_ids,
                groups=groups,
                hours_per_week=hours,
                cross_class=cross,
            ))

        return couplings

    # ── Unterrichtsverteilung ──────────────────────────────────────────────

    def import_assignments(
        self,
        classes: list[SchoolClass],
        teachers: list[Teacher],
        couplings: list[Coupling],
    ) -> list[FixedAssignment]:
        """Liest die Matrix Klasse × Fach (Zelle = Kürzel der Lehrkraft).

        Das Blatt ist optional; leere Zellen entscheidet der Solver.
        Fehler nennen die Zelle (z.B. "C5"), damit sie auffindbar ist.
        """
        sheet = self._get_sheet(ASSIGNMENT_SHEET)
        if sheet is None:
            return []
        rows = list(sheet.iter_rows(values_only=True))
        if not rows:
            return []

        subject_columns = self._assignment_columns(rows[0])
        class_by_key = {cls.id.lower(): cls for cls in classes}
        teacher_ids = {teacher.id for teacher in teachers}
        covered = coupling_subjects_by_class(couplings)

        assignments: list[FixedAssignment] = []
        seen_classes: set[str] = set()
        for row_number, row in enumerate(rows[1:], 2):
            school_class = self._assignment_row_class(
                row, row_number, class_by_key, seen_classes
            )
            if school_class is None:
                continue
            for column, subject in subject_columns.items():
                assignment = self._assignment_from_cell(
                    _cell_text(row, column), _cell_ref(column, row_number),
                    school_class, subject, teacher_ids,
                    covered.get(school_class.id, set()),
                )
                if assignment is not None:
                    assignments.append(assignment)
        return assignments

    def _assignment_columns(self, header: tuple) -> dict[int, str]:
        """Spaltenindex (0-basiert) → Fachname laut Kopfzeile."""
        columns: dict[int, str] = {}
        for column in range(1, len(header)):
            raw = _cell_text(header, column)
            if not raw:
                continue
            location = f"{ASSIGNMENT_SHEET} {_cell_ref(column, 1)}"
            subject = self._parse_subject(raw, location)
            if subject:
                columns[column] = subject
        return columns

    def _assignment_row_class(
        self,
        row: tuple,
        row_number: int,
        class_by_key: dict[str, SchoolClass],
        seen_classes: set[str],
    ) -> Optional[SchoolClass]:
        """Klasse der Zeile; None bei Leer-/Hinweiszeile oder Fehler."""
        raw = _cell_text(row, 0)
        if not raw or raw.startswith(HINT_PREFIX):
            return None
        location = f"{ASSIGNMENT_SHEET} {_cell_ref(0, row_number)}"
        school_class = class_by_key.get(raw.lower())
        if school_class is None:
            self._errors.append(f"{location}: Unbekannte Klasse '{raw}'.")
            return None
        if school_class.id in seen_classes:
            self._errors.append(
                f"{location}: Klasse '{school_class.id}' steht mehrfach "
                f"im Blatt."
            )
            return None
        seen_classes.add(school_class.id)
        return school_class

    def _assignment_from_cell(
        self,
        raw: str,
        cell_ref: str,
        school_class: SchoolClass,
        subject: str,
        teacher_ids: set[str],
        coupled_subjects: set[str],
    ) -> Optional[FixedAssignment]:
        """Wertet eine Zelle aus; None = keine Vorgabe oder Fehler."""
        if raw.lower() in _BLANK_CELL_MARKS:
            return None
        location = (
            f"{ASSIGNMENT_SHEET} {cell_ref} "
            f"(Klasse {school_class.id}, Fach {subject})"
        )
        teacher_id = raw.upper()
        if school_class.curriculum.get(subject, 0) <= 0:
            self._errors.append(
                f"{location}: Das Fach steht nicht in der Stundentafel "
                f"dieser Klasse, '{raw}' kann hier nicht eingetragen werden."
            )
            return None
        if subject in coupled_subjects:
            self._warnings.append(
                f"{location}: Das Fach läuft über eine Kopplung, der "
                f"Eintrag '{raw}' wird ignoriert. Lehrkraft im Blatt "
                f"'Kopplungen' angeben."
            )
            return None
        if teacher_id not in teacher_ids:
            self._errors.append(
                f"{location}: Unbekanntes Kürzel '{raw}'."
            )
            return None
        return FixedAssignment(
            class_id=school_class.id, subject=subject, teacher_id=teacher_id
        )

    # ── Vollständiger Import ───────────────────────────────────────────────

    def import_all(self) -> tuple[SchoolData, FeasibilityReport]:
        """Importiert alle Daten → SchoolData + FeasibilityReport."""
        self._open()
        self._errors = []
        self._warnings = []

        # Zeitraster optional überschreiben
        self.import_time_grid()

        # Fächer aus SUBJECT_METADATA
        subjects = [
            Subject(
                name=name,
                short_name=meta["short"],
                category=meta["category"],
                is_hauptfach=meta["is_hauptfach"],
                requires_special_room=meta["room"],
                double_lesson_required=meta["double_required"],
                double_lesson_preferred=meta["double_preferred"],
            )
            for name, meta in SUBJECT_METADATA.items()
        ]

        # Räume
        try:
            rooms = self.import_rooms()
        except ExcelImportError as e:
            self._errors.append(f"Fachräume: {e}")
            rooms = []

        # Klassen
        try:
            classes = self.import_classes()
        except ExcelImportError as e:
            self._errors.append(f"Klassen: {e}")
            classes = []

        # Lehrkräfte
        try:
            teachers = self.import_teachers()
        except ExcelImportError as e:
            self._errors.append(f"Lehrkräfte: {e}")
            teachers = []

        # Kopplungen
        try:
            couplings = self.import_couplings()
        except ExcelImportError as e:
            self._warnings.append(f"Kopplungen: {e}")
            couplings = []

        # Unterrichtsverteilung (optional)
        fixed_assignments = self.import_assignments(
            classes, teachers, couplings
        )

        if self._errors:
            # Kritische Fehler: Report zurückgeben, kein SchoolData
            report = FeasibilityReport(
                is_feasible=False,
                errors=self._errors,
                warnings=self._warnings,
            )
            raise ExcelImportError(
                f"Import mit {len(self._errors)} Fehlern:\n"
                + "\n".join(f"  • {e}" for e in self._errors)
            )

        school_data = SchoolData(
            subjects=subjects,
            rooms=rooms,
            classes=classes,
            teachers=teachers,
            couplings=couplings,
            config=self.config,
            fixed_assignments=fixed_assignments,
        )

        # Machbarkeits-Check nach Import
        feasibility = school_data.validate_feasibility()
        feasibility = FeasibilityReport(
            is_feasible=feasibility.is_feasible,
            errors=feasibility.errors,
            warnings=feasibility.warnings + self._warnings,
        )

        return school_data, feasibility


def import_from_excel(
    path: Path, config: SchoolConfig
) -> tuple[SchoolData, FeasibilityReport]:
    """Importiert Schuldaten aus einer Excel-Vorlage.

    Args:
        path:   Pfad zur Excel-Datei (.xlsx)
        config: Basis-Konfiguration (kann durch Zeitraster-Blatt überschrieben werden)

    Returns:
        (SchoolData, FeasibilityReport)

    Raises:
        ExcelImportError: Bei kritischen Import-Fehlern.
    """
    importer = ExcelImporter(path, config)
    return importer.import_all()
