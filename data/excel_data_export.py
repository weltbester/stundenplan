"""Schreibt einen vorhandenen Datensatz als importierbare Excel-Mappe.

Gegenstück zum Import: aus SchoolData (und optional einer Lösung) entsteht
eine ausgefüllte Vorlage. Damit lässt sich die Unterrichtsverteilung eines
bestehenden Plans in Excel ansehen, ändern und wieder importieren.
"""

from pathlib import Path
from typing import Optional

from data.excel_import import (
    _DAY_NAMES, ASSIGNMENT_SHEET, generate_template,
)
from models.coupling import Coupling
from models.fixed_assignment import FixedAssignment
from models.school_data import SchoolData
from models.teacher import Teacher
from solver.scheduler import ScheduleSolution

TEACHER_SHEET = "Lehrkräfte"
ROOM_SHEET = "Fachräume"
COUPLING_SHEET = "Kopplungen"
# Zeile 1 = Kopfzeile, Zeile 2 = Beispielzeile der Vorlage
FIRST_TEACHER_ROW = 3
FIRST_COUPLING_ROW = 2
FIRST_ROOM_ROW = 2
MAX_SUBJECT_COLUMNS = 3
YES, NO = "ja", "nein"


def export_workbook(
    data: SchoolData,
    path: Path,
    solution: Optional[ScheduleSolution] = None,
) -> None:
    """Erzeugt die Vorlage und füllt sie mit `data`.

    Mit `solution` wird zusätzlich deren Unterrichtsverteilung eingetragen
    (wer unterrichtet welches Fach in welcher Klasse, Kopplungslehrkräfte).
    Ohne `solution` erscheinen nur die in `data` bereits festen Vorgaben.
    """
    import openpyxl

    path = Path(path)
    generate_template(data.config, path)
    workbook = openpyxl.load_workbook(path)

    assignments = list(data.fixed_assignments)
    couplings = data.couplings
    if solution is not None:
        assignments = assignments_from_solution(solution)
        couplings = couplings_with_solution_teachers(couplings, solution)

    _fill_teachers(workbook[TEACHER_SHEET], data)
    _clear_room_example(workbook[ROOM_SHEET], data)
    _fill_couplings(workbook[COUPLING_SHEET], couplings)
    _fill_assignments(workbook[ASSIGNMENT_SHEET], assignments)
    workbook.save(path)


def assignments_from_solution(
    solution: ScheduleSolution,
) -> list[FixedAssignment]:
    """Die Lehrer-Klassen-Zuweisungen einer Lösung als feste Vorgaben."""
    return [
        FixedAssignment(
            class_id=assignment.class_id,
            subject=assignment.subject,
            teacher_id=assignment.teacher_id,
        )
        for assignment in solution.assignments
    ]


def couplings_with_solution_teachers(
    couplings: list[Coupling], solution: ScheduleSolution
) -> list[Coupling]:
    """Kopien der Kopplungen mit den Lehrkräften aus der Lösung.

    Die Lösung nennt pro Kopplungstermin Fach und Lehrkraft, aber nicht die
    Gruppe. Gruppen desselben Fachs sind für den Plan austauschbar, daher
    werden die Lehrkräfte eines Fachs der Reihe nach verteilt.
    """
    teachers_by_subject: dict[tuple[str, str], list[str]] = {}
    for entry in solution.entries:
        if not (entry.is_coupling and entry.coupling_id):
            continue
        teachers = teachers_by_subject.setdefault(
            (entry.coupling_id, entry.subject), []
        )
        if entry.teacher_id not in teachers:
            teachers.append(entry.teacher_id)

    result: list[Coupling] = []
    for coupling in couplings:
        groups = []
        for group in coupling.groups:
            pool = teachers_by_subject.get((coupling.id, group.subject), [])
            teacher_id = group.teacher_id or (pool.pop(0) if pool else None)
            groups.append(group.model_copy(update={"teacher_id": teacher_id}))
        result.append(coupling.model_copy(update={"groups": groups}))
    return result


def _teacher_row(teacher: Teacher, deputat_buffer: int) -> list:
    """Zeile im Blatt 'Lehrkräfte' (Reihenfolge wie die Kopfzeile)."""
    subjects = (teacher.subjects + [""] * MAX_SUBJECT_COLUMNS)
    blocked = ",".join(
        f"{_DAY_NAMES[day]}{slot}" for day, slot in teacher.unavailable_slots
    )
    free_days = ",".join(_DAY_NAMES[d] for d in teacher.preferred_free_days)
    return [
        teacher.name,
        teacher.id,
        *subjects[:MAX_SUBJECT_COLUMNS],
        # Der Import addiert den Puffer wieder auf das Deputat.
        teacher.deputat_max - deputat_buffer,
        YES if teacher.is_teilzeit else NO,
        blocked,
        free_days,
        teacher.max_hours_per_day,
        teacher.max_gaps_per_day,
    ]


def _fill_teachers(sheet, data: SchoolData) -> None:
    buffer = data.config.teachers.deputat_max_buffer
    for row, teacher in enumerate(data.teachers, FIRST_TEACHER_ROW):
        for column, value in enumerate(_teacher_row(teacher, buffer), 1):
            sheet.cell(row=row, column=column, value=value)


def _clear_room_example(sheet, data: SchoolData) -> None:
    """Entfernt die Beispielzeile, die der Import sonst als Raum einliest."""
    example_row = FIRST_ROOM_ROW + len(data.config.rooms.special_rooms)
    for cell in sheet[example_row]:
        cell.value = None


def _coupling_row(coupling: Coupling) -> list:
    """Zeile im Blatt 'Kopplungen' (Gruppen als Name:Fach:Std[:Kürzel])."""
    groups = []
    for group in coupling.groups:
        parts = [group.group_name, group.subject, str(group.hours_per_week)]
        if group.teacher_id:
            parts.append(group.teacher_id)
        groups.append(":".join(parts))
    return [
        coupling.id,
        coupling.coupling_type,
        ",".join(coupling.involved_class_ids),
        ",".join(groups),
        coupling.hours_per_week,
        YES if coupling.cross_class else NO,
    ]


def _fill_couplings(sheet, couplings: list[Coupling]) -> None:
    for cell in sheet[FIRST_COUPLING_ROW]:
        cell.value = None  # Beispielzeile der Vorlage entfernen
    for row, coupling in enumerate(couplings, FIRST_COUPLING_ROW):
        for column, value in enumerate(_coupling_row(coupling), 1):
            sheet.cell(row=row, column=column, value=value)


def _fill_assignments(sheet, assignments: list[FixedAssignment]) -> None:
    """Trägt die Kürzel in die Matrix Klasse × Fach ein."""
    column_by_subject = {
        cell.value: cell.column for cell in sheet[1] if cell.value
    }
    row_by_class = {
        cell.value: cell.row for cell in sheet["A"] if cell.value
    }
    for assignment in assignments:
        row = row_by_class.get(assignment.class_id)
        column = column_by_subject.get(assignment.subject)
        if row is None or column is None:
            continue  # Klasse/Fach steht nicht in der Vorlage
        sheet.cell(row=row, column=column, value=assignment.teacher_id)
