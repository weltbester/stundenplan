"""Gemeinsame Hilfsfunktionen für Excel- und PDF-Export."""

from collections import defaultdict
from datetime import date
from typing import Union

from config.schema import SchoolConfig, LessonSlot, PauseSlot
from models.school_data import SchoolData
from models.subject import Subject
from solver.scheduler import ScheduleEntry

# ─── Farbpalette (RRGGBB, ohne #) ─────────────────────────────────────────────

COLORS: dict[str, str] = {
    "hauptfach":    "B3D4FF",
    "sprache":      "FFF2B3",
    "nw":           "B3FFB3",
    "musisch":      "FFB3E6",
    "sport":        "FFD4B3",
    "gesellschaft": "D4B3FF",
    "wpf":          "E0E0E0",
    "sonstig":      "E0E0E0",
    "gap":          "FF9999",
    "free":         "F5F5F5",
    "coupling":     "FFFFB3",
    "pause":        "DDDDDD",
    "header":       "4472C4",
}


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Wandelt RRGGBB-String in (r, g, b)-Tupel um."""
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def today_str() -> str:
    """Gibt das heutige Datum als DD.MM.YYYY zurück."""
    return date.today().strftime("%d.%m.%Y")


# ─── Zeitraster-Hilfsfunktionen ───────────────────────────────────────────────

def build_time_grid_rows(
    config: SchoolConfig, max_slot: int | None = None
) -> list[Union[LessonSlot, PauseSlot]]:
    """Gibt geordnete Zeilen zurück: LessonSlot- und PauseSlot-Objekte.

    Enthält alle Slots bis einschließlich max_slot. Ist max_slot nicht angegeben,
    wird sek1_max_slot aus der Config verwendet (Sek. I-Standardverhalten).
    PauseSlot folgt jeweils nach dem angegebenen after_slot.
    """
    tg = config.time_grid
    effective_max = max_slot if max_slot is not None else tg.sek1_max_slot
    slots = [s for s in tg.lesson_slots if s.slot_number <= effective_max]
    pause_map = {p.after_slot: p for p in tg.pauses}
    rows: list[Union[LessonSlot, PauseSlot]] = []
    for slot in sorted(slots, key=lambda s: s.slot_number):
        rows.append(slot)
        if slot.slot_number in pause_map:
            rows.append(pause_map[slot.slot_number])
    return rows


# ─── Fach-Farbe ───────────────────────────────────────────────────────────────

def get_subject_color(subject_name: str, subjects: list[Subject]) -> str:
    """Gibt die Hex-Farbe für ein Fach zurück (anhand Subject.category)."""
    for s in subjects:
        if s.name == subject_name:
            return COLORS.get(s.category, COLORS["sonstig"])
    return COLORS["sonstig"]


# ─── Springstunden ────────────────────────────────────────────────────────────

def count_gaps(entries: list[ScheduleEntry]) -> int:
    """Zählt Springstunden (freie Slots zwischen erster und letzter Stunde pro Tag)."""
    by_day: dict[int, list[int]] = defaultdict(list)
    for e in entries:
        by_day[e.day].append(e.slot_number)
    total = 0
    for slots in by_day.values():
        unique = sorted(set(slots))
        if len(unique) > 1:
            total += unique[-1] - unique[0] + 1 - len(unique)
    return total


# ─── Doppelstunden-Erkennung ──────────────────────────────────────────────────

def detect_double_starts(
    entries: list[ScheduleEntry], double_blocks: list
) -> set[tuple[int, int]]:
    """Gibt (day, slot_first)-Mengen zurück für alle erkannten Doppelstunden.

    Ein Doppelstunden-Start wird erkannt, wenn:
    (class_id, teacher_id, subject, day, slot_first) UND
    (class_id, teacher_id, subject, day, slot_second) beide in entries vorhanden sind.
    """
    entry_keys: set[tuple] = set()
    for e in entries:
        entry_keys.add((e.class_id, e.teacher_id, e.subject, e.day, e.slot_number))

    result: set[tuple[int, int]] = set()
    for db in double_blocks:
        for (cls, t, s, day, slot) in entry_keys:
            if slot == db.slot_first:
                if (cls, t, s, day, db.slot_second) in entry_keys:
                    result.add((day, db.slot_first))
    return result


# ─── Kopplungs-Label ──────────────────────────────────────────────────────────

def get_coupling_label(entry: ScheduleEntry, school_data: SchoolData) -> str | None:
    """Für reli_ethik-Kopplungen: gibt group_name zurück (z.B. 'evangelisch').

    Für WPF-Kopplungen und normale Entries: None.
    """
    if not entry.is_coupling or not entry.coupling_id:
        return None
    for c in school_data.couplings:
        if c.id == entry.coupling_id and c.coupling_type == "reli_ethik":
            for g in c.groups:
                if g.subject == entry.subject:
                    return g.group_name
    return None


# ─── Lehrer-Stunden ───────────────────────────────────────────────────────────

def count_teacher_actual_hours(
    entries: list[ScheduleEntry], teacher_id: str
) -> int:
    """Zählt tatsächliche Stunden eines Lehrers (Kopplungen de-dupliziert).

    Kopplungs-Entries werden per (coupling_id, day, slot_number) de-dupliziert
    (da ein Kopplungs-Slot mehrere class-Entries erzeugt, aber nur einmal zählt).
    """
    regular = sum(
        1 for e in entries
        if e.teacher_id == teacher_id and not e.is_coupling
    )
    seen: set[tuple] = set()
    coupling = 0
    for e in entries:
        if e.teacher_id == teacher_id and e.is_coupling and e.coupling_id:
            key = (e.coupling_id, e.day, e.slot_number)
            if key not in seen:
                seen.add(key)
                coupling += 1
    return regular + coupling


# ─── Zelleninhalt-Formatierung ────────────────────────────────────────────────

def format_entry(
    entry: ScheduleEntry, school_data: SchoolData, mode: str = "class"
) -> str:
    """Formatiert einen einzelnen Entry als Zelleninhalt.

    mode='class':   "Fach\nLehrer-ID"  (+ "(lbl.)" für reli_ethik)
    mode='teacher': "Fach\nKlasse"
    mode='room':    "Klasse\nFach"
    """
    label = get_coupling_label(entry, school_data)
    subj = entry.subject
    if label:
        abbrev = label[:3].lower() + "."   # "evangelisch" → "eva."
        subj = f"{subj} ({abbrev})"

    if mode == "class":
        return f"{subj}\n{entry.teacher_id}"
    elif mode == "teacher":
        return f"{subj}\n{entry.class_id}"
    elif mode == "room":
        return f"{entry.class_id}\n{subj}"
    return subj


def format_entries(
    entries: list[ScheduleEntry], school_data: SchoolData, mode: str = "class"
) -> str:
    """Formatiert mehrere Entries für eine Zelle (getrennt durch ──).

    Bei Kopplungen (reli_ethik) entstehen mehrere Entries pro Slot
    (eine pro Gruppe). Diese werden gestapelt dargestellt.
    """
    if not entries:
        return ""
    if len(entries) == 1:
        return format_entry(entries[0], school_data, mode)
    return "\n──\n".join(format_entry(e, school_data, mode) for e in entries)
