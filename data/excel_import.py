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
from models.school_data import SchoolData, FeasibilityReport


class ExcelImportError(Exception):
    """Fehler beim Excel-Import."""


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
        "Gruppen (Name:Fach:Std, kommagetrennt)", "Stunden/Woche", "Klassenübergreifend",
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

    # ── Speichern ─────────────────────────────────────────────────────────────
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(path))


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

            teachers.append(Teacher(
                id=abbr,
                name=name,
                subjects=subjects,
                deputat=deputat,
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
            groups_raw = row.get("gruppen (name:fach:std, kommagetrennt)",
                                 row.get("gruppen", "")).strip()
            hours_raw = row.get("stunden/woche", row.get("stunden", "2")).strip()
            cross_raw = row.get("klassenübergreifend", "ja").strip().lower()

            if not cid or cid.startswith("id"):
                continue  # Header/Beispiel

            class_ids = [c.strip() for c in classes_raw.split(",") if c.strip()]

            # Gruppen parsen: "Name:Fach:Std,..."
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
                    groups.append(CouplingGroup(
                        group_name=gname,
                        subject=gsubj,
                        hours_per_week=ghours,
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
