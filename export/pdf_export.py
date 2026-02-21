"""PDF-Export für den Stundenplan (fpdf2)."""

from pathlib import Path

from config.schema import LessonSlot, PauseSlot
from models.school_data import SchoolData
from models.teacher import Teacher
from solver.scheduler import ScheduleEntry, ScheduleSolution

from export.helpers import (
    COLORS, hex_to_rgb, build_time_grid_rows, get_subject_color,
    count_gaps, detect_double_starts, count_teacher_actual_hours,
    format_entries, today_str,
)


def _pdf_safe(text: str) -> str:
    """Ersetzt nicht-latin-1-fähige Zeichen für fpdf2-Built-in-Fonts."""
    return (
        text
        .replace("\u2014", " - ")   # em dash —
        .replace("\u2013", "-")      # en dash –
        .replace("\u2500", "-")      # BOX DRAWINGS LIGHT HORIZONTAL ─
        .replace("\u2502", "|")      # BOX DRAWINGS LIGHT VERTICAL │
    )


# ─── A4-Querformat-Dimensionen ────────────────────────────────────────────────
# Landscape A4: 297 × 210 mm
# Nutzbare Breite (Margin 10 links+rechts): 277 mm
# Spalten: Std.(8) + Zeit(24) + 5×Tag(49) = 8 + 24 + 245 = 277 mm ✓

_COLS = {
    "std":  8,
    "zeit": 24,
    "day":  49,    # pro Wochentag
}
_ROW_HEADER_H  = 7    # mm
_ROW_LESSON_H  = 16   # mm (2 Doppelstunden: 32 mm)
_ROW_PAUSE_H   = 4    # mm
_FONT_HEADER   = 8    # pt
_FONT_CONTENT  = 7    # pt (Zelleninhalt)
_FONT_TINY     = 6    # pt (Pausen, Label)
_LINE_H        = 3.5  # mm pro Zeile bei 7pt


class _SchedulePdf:
    """Interner Wrapper um fpdf.FPDF für Stundenplan-Seiten."""

    def __init__(self, school_name: str):
        from fpdf import FPDF

        class _Pdf(FPDF):
            def __init__(inner, sn):
                super().__init__(orientation="L", unit="mm", format="A4")
                inner._school_name = sn
                inner._entity_title = ""
                inner.alias_nb_pages()
                inner.set_auto_page_break(auto=True, margin=18)
                inner.set_margins(left=10, top=22, right=10)

            def header(inner):
                inner.set_font("Helvetica", "B", 11)
                inner.set_xy(10, 8)
                inner.cell(130, 7, _pdf_safe(inner._school_name), border=0, align="L")
                inner.cell(0,   7, _pdf_safe(inner._entity_title), border=0, align="R")
                inner.ln(0)
                inner.set_draw_color(150, 150, 150)
                inner.line(10, 18, inner.w - 10, 18)

            def footer(inner):
                inner.set_y(-14)
                inner.set_font("Helvetica", "I", 7)
                inner.cell(
                    0, 8,
                    f"{today_str()}  |  Seite {inner.page_no()}/{{nb}}",
                    border=0, align="C",
                )

        self._pdf = _Pdf(school_name)

    def set_entity(self, title: str) -> None:
        self._pdf._entity_title = title

    def add_page(self) -> None:
        self._pdf.add_page()

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._pdf.output(str(path))

    # ─── Zellen-Zeichnung ─────────────────────────────────────────────────────

    def draw_cell(
        self,
        x: float, y: float,
        w: float, h: float,
        text: str = "",
        bg_hex: str | None = None,
        bold: bool = False,
        font_size: int = _FONT_CONTENT,
        text_color: tuple[int, int, int] = (0, 0, 0),
        align: str = "C",
    ) -> None:
        """Zeichnet eine Zelle mit Hintergrund, Rand und zentriertem Text."""
        pdf = self._pdf

        # Hintergrund
        if bg_hex:
            r, g, b = hex_to_rgb(bg_hex)
            pdf.set_fill_color(r, g, b)
            pdf.rect(x, y, w, h, style="F")

        # Rand
        pdf.set_draw_color(180, 180, 180)
        pdf.rect(x, y, w, h, style="D")

        # Text
        if text:
            style = "B" if bold else ""
            pdf.set_font("Helvetica", style, font_size)
            pdf.set_text_color(*text_color)

            lines = [ln for ln in _pdf_safe(text).split("\n") if ln][:3]  # max 3 Zeilen
            total_text_h = len(lines) * _LINE_H
            y_text = y + max(1.0, (h - total_text_h) / 2)

            for line in lines:
                pdf.set_xy(x, y_text)
                pdf.cell(w, _LINE_H, line[:28], border=0, align=align)
                y_text += _LINE_H

            pdf.set_text_color(0, 0, 0)   # Reset

    # ─── Tabellen-Zeilen ──────────────────────────────────────────────────────

    def draw_header_row(self, x: float, y: float, day_names: list[str]) -> float:
        """Zeichnet die Kopfzeile und gibt die Y-Position danach zurück."""
        r, g, b = hex_to_rgb(COLORS["header"])
        cols = [("Std.", _COLS["std"]), ("Zeit", _COLS["zeit"])]
        cols += [(name, _COLS["day"]) for name in day_names]

        cx = x
        for label, w in cols:
            self.draw_cell(
                cx, y, w, _ROW_HEADER_H, label,
                bg_hex=COLORS["header"],
                bold=True,
                font_size=_FONT_HEADER,
                text_color=(255, 255, 255),
            )
            cx += w
        return y + _ROW_HEADER_H

    def draw_pause_row(self, x: float, y: float, label: str, total_w: float) -> float:
        """Zeichnet eine Pausen-Trennzeile und gibt die Y-Position danach zurück."""
        self.draw_cell(
            x, y, total_w, _ROW_PAUSE_H, _pdf_safe(label),
            bg_hex=COLORS["pause"],
            font_size=_FONT_TINY,
            text_color=(100, 100, 100),
        )
        return y + _ROW_PAUSE_H

    def draw_lesson_row(
        self,
        x: float, y: float,
        slot: LessonSlot,
        day_entries: list[list[ScheduleEntry]],   # eine Liste pro Tag
        day_colors: list[str],
        row_h: float = _ROW_LESSON_H,
    ) -> float:
        """Zeichnet eine Unterrichtsstunden-Zeile und gibt Y danach zurück."""
        # Std.-Spalte
        self.draw_cell(
            x, y, _COLS["std"], row_h,
            str(slot.slot_number),
            bold=True, font_size=_FONT_HEADER,
        )
        cx = x + _COLS["std"]

        # Zeit-Spalte
        self.draw_cell(
            cx, y, _COLS["zeit"], row_h,
            f"{slot.start_time}\n{slot.end_time}",
            font_size=_FONT_TINY,
        )
        cx += _COLS["zeit"]

        # Tag-Spalten
        for entries_here, color in zip(day_entries, day_colors):
            self.draw_cell(cx, y, _COLS["day"], row_h, entries_here, bg_hex=color)
            cx += _COLS["day"]

        return y + row_h


class PdfExporter:
    """Exportiert eine ScheduleSolution in PDF-Dateien."""

    def __init__(self, solution: ScheduleSolution, school_data: SchoolData):
        self.solution  = solution
        self.data      = school_data
        self.config    = school_data.config
        self.tg        = school_data.config.time_grid
        self.days      = list(range(self.tg.days_per_week))
        self.day_names = self.tg.day_names
        # Gesamt-Tabellenbreite
        self._total_w = (
            _COLS["std"] + _COLS["zeit"] + _COLS["day"] * len(self.days)
        )
        self._table_x = 10.0   # linker Rand

    # ─── Öffentliche API ──────────────────────────────────────────────────────

    def export_class_schedules(self, output_path: Path) -> None:
        """Erzeugt eine PDF mit je einer Seite pro Klasse."""
        pdf = _SchedulePdf(self.config.school_name)
        for cls in sorted(self.data.classes, key=lambda c: c.id):
            entries = self.solution.get_class_schedule(cls.id)
            # Gesamtstunden = eindeutige (day, slot)-Paare der Klasse
            total_h = len({(e.day, e.slot_number) for e in entries})
            pdf.set_entity(f"Klasse {cls.id} - Stundenplan | {total_h} Std./Woche")
            pdf.add_page()
            self._draw_schedule(pdf, entries, mode="class", max_slot=cls.max_slot)
        pdf.save(output_path)

    def export_teacher_schedules(self, output_path: Path) -> None:
        """Erzeugt eine PDF mit je einer Seite pro Lehrer."""
        pdf = _SchedulePdf(self.config.school_name)
        for teacher in sorted(self.data.teachers, key=lambda t: t.id):
            entries = self.solution.get_teacher_schedule(teacher.id)
            actual = count_teacher_actual_hours(self.solution.entries, teacher.id)
            entity = (
                f"{teacher.id} - {teacher.name} "
                f"| Min: {teacher.deputat_min}h-Max: {teacher.deputat_max}h | Ist: {actual}h"
            )
            pdf.set_entity(entity)
            max_slot = max(
                (e.slot_number for e in entries), default=self.tg.sek1_max_slot
            )
            pdf.add_page()
            self._draw_schedule(pdf, entries, mode="teacher", max_slot=max_slot)
            self._draw_teacher_footer(pdf, teacher, entries, actual)
        pdf.save(output_path)

    # ─── Tabellenzeichnung ────────────────────────────────────────────────────

    def _build_grid(
        self, entries: list[ScheduleEntry]
    ) -> dict[tuple[int, int], list[ScheduleEntry]]:
        from collections import defaultdict
        grid: dict[tuple[int, int], list[ScheduleEntry]] = defaultdict(list)
        for e in entries:
            grid[(e.day, e.slot_number)].append(e)
        return grid

    def _draw_schedule(
        self, pdf: _SchedulePdf, entries: list[ScheduleEntry], mode: str,
        max_slot: int | None = None,
    ) -> None:
        """Zeichnet die Stundenplan-Tabelle auf der aktuellen Seite.

        max_slot begrenzt die angezeigten Zeitraster-Zeilen auf die für diese
        Entität relevanten Slots (Sek. I: sek1_max_slot, Sek. II: höher).
        """
        time_rows = build_time_grid_rows(self.config, max_slot)
        grid = self._build_grid(entries)

        x = self._table_x
        y = 22.0   # unter dem Header-Linie

        y = pdf.draw_header_row(x, y, self.day_names[: len(self.days)])

        for row_obj in time_rows:
            if isinstance(row_obj, PauseSlot):
                label = f"-- {row_obj.label} ({row_obj.duration_minutes} Min.) --"
                y = pdf.draw_pause_row(x, y, label, self._total_w)
                continue

            # LessonSlot: Inhalte und Farben je Tag bestimmen
            slot_num = row_obj.slot_number
            day_contents: list[str] = []
            day_colors: list[str] = []

            for day in self.days:
                here = grid.get((day, slot_num), [])
                content = format_entries(here, self.data, mode)
                color = COLORS["free"]

                if here:
                    e = here[0]
                    color = (
                        COLORS["coupling"] if e.is_coupling
                        else get_subject_color(e.subject, self.data.subjects)
                    )
                elif mode == "teacher":
                    # Springstunden rot markieren
                    teacher_slots_today = [
                        sn for (d, sn), es in grid.items()
                        if d == day and es
                    ]
                    if teacher_slots_today:
                        mn, mx = min(teacher_slots_today), max(teacher_slots_today)
                        if mn < slot_num < mx:
                            color = COLORS["gap"]

                day_contents.append(content)
                day_colors.append(color)

            y = pdf.draw_lesson_row(
                x, y, row_obj, day_contents, day_colors, row_h=_ROW_LESSON_H
            )

    def _draw_teacher_footer(
        self,
        pdf: _SchedulePdf,
        teacher: Teacher,
        entries: list[ScheduleEntry],
        actual: int,
    ) -> None:
        """Zeichnet Statistik-Box unter dem Lehrerplan."""
        gaps = count_gaps(entries)
        text = (
            f"Deputat Min: {teacher.deputat_min}h | Max: {teacher.deputat_max}h  |  "
            f"Ist: {actual}h  |  Springstunden: {gaps}"
        )
        p = pdf._pdf
        p.set_auto_page_break(False)
        p.set_font("Helvetica", "I", 8)
        p.set_y(-22)
        p.cell(0, 6, text, border=0, align="C")
        p.set_auto_page_break(True, margin=18)
