"""Gemeinsamer Renderer für Terminal-Stundenplan-Anzeige.

Wird von cmd_show (Rich) und cmd_browse (Textual) verwendet.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solver.scheduler import ScheduleSolution, ScheduleEntry
    from models.school_data import SchoolData
    from config.schema import SchoolConfig


def render_class_rows(
    class_id: str,
    solution: "ScheduleSolution",
    school_data: "SchoolData",
    config: "SchoolConfig",
) -> list[list[str]]:
    """Gibt Tabellenzeilen für den Klassen-Stundenplan zurück.

    Jede Zeile: [slot_label, time_label, Mo, Di, Mi, Do, Fr]
    Pausen werden als separate Zeilen mit '—' in allen Fächern eingefügt.
    """
    from export.helpers import build_time_grid_rows, get_coupling_label
    from config.schema import LessonSlot, PauseSlot

    cls = next((c for c in school_data.classes if c.id == class_id), None)
    if cls is None:
        return []

    entries = solution.get_class_schedule(class_id)
    slot_map: dict = {
        (e.day, e.slot_number): e for e in entries
    }

    day_names = config.time_grid.day_names
    time_rows = build_time_grid_rows(config, max_slot=cls.max_slot)
    rows: list[list[str]] = []

    for row in time_rows:
        if isinstance(row, PauseSlot):
            rows.append(["—", row.label] + ["─" * 8] * len(day_names))
            continue
        slot = row
        cells = [str(slot.slot_number), f"{slot.start_time}–{slot.end_time}"]
        for day_idx in range(len(day_names)):
            entry = slot_map.get((day_idx, slot.slot_number))
            if entry is None:
                cells.append("—")
            else:
                label = get_coupling_label(entry, school_data)
                subj = entry.subject
                if label:
                    subj = f"{subj} ({label[:3].lower()}.)"
                cells.append(f"{subj}\n{entry.teacher_id}")
        rows.append(cells)

    return rows


def render_teacher_rows(
    teacher_id: str,
    solution: "ScheduleSolution",
    school_data: "SchoolData",
    config: "SchoolConfig",
) -> list[list[str]]:
    """Gibt Tabellenzeilen für den Lehrer-Stundenplan zurück.

    Springstunden werden als 'Springstunde' markiert.
    """
    from export.helpers import build_time_grid_rows
    from config.schema import LessonSlot, PauseSlot
    from collections import defaultdict

    entries = solution.get_teacher_schedule(teacher_id)
    slot_map: dict = {}
    for e in entries:
        key = (e.day, e.slot_number)
        if key not in slot_map:
            slot_map[key] = e

    # Berechne Springstunden
    by_day: dict = defaultdict(list)
    for e in entries:
        by_day[e.day].append(e.slot_number)
    gap_slots: set = set()
    for day_idx, slots in by_day.items():
        unique = sorted(set(slots))
        if len(unique) > 1:
            first, last = unique[0], unique[-1]
            for h in range(first + 1, last):
                if h not in unique:
                    gap_slots.add((day_idx, h))

    day_names = config.time_grid.day_names
    used_slots = [e.slot_number for e in entries]
    max_slot = (
        max(used_slots) if used_slots else config.time_grid.sek1_max_slot
    )
    time_rows = build_time_grid_rows(config, max_slot=max_slot)
    rows: list[list[str]] = []

    for row in time_rows:
        if isinstance(row, PauseSlot):
            rows.append(["—", row.label] + ["─" * 8] * len(day_names))
            continue
        slot = row
        cells = [str(slot.slot_number), f"{slot.start_time}–{slot.end_time}"]
        for day_idx in range(len(day_names)):
            key = (day_idx, slot.slot_number)
            entry = slot_map.get(key)
            if entry is None:
                if key in gap_slots:
                    cells.append("↕ Springstunde")
                else:
                    cells.append("—")
            else:
                cells.append(f"{entry.subject}\n{entry.class_id}")
        rows.append(cells)

    return rows
