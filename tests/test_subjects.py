"""Tests für die freie Fächerliste (Blatt "Fächer")."""

from pathlib import Path

import openpyxl
import pytest

from config.defaults import SUBJECT_METADATA
from data.excel_data_export import export_workbook
from data.excel_import import (
    CURRICULUM_SHEET, DOUBLE_PREFERRED, DOUBLE_REQUIRED, SUBJECT_SHEET,
    ExcelImportError, import_from_excel,
)
from models.school_data import SchoolData
from models.subject import Subject, default_subjects
from solver.constraint_relaxer import ConstraintRelaxer
from solver.scheduler import ScheduleSolver
from tests.test_fixed_assignments import (
    FIRST_TEACHER_ROW, TEACHER_SHEET, _matching, _write_mini_workbook,
)
from tests.test_solver import make_mini_config, make_mini_school_data

ROOM_SHEET = "Fachräume"
NEW_SUBJECT = "Astronomie"
NEW_SUBJECT_HOURS = 2
NEW_SUBJECT_GRADE = 5
NEW_SUBJECT_CLASS = "5a"
# Lehrkraft T08 (Religion, Ethik; hat noch Stunden frei) bekommt das
# neue Fach als Fach 3.
NEW_SUBJECT_TEACHER = "T08"
NEW_SUBJECT_TEACHER_ROW = FIRST_TEACHER_ROW + 7
FIRST_SUBJECT_COLUMN = 3
THIRD_SUBJECT_COLUMN = 5
NRW_SUBJECTS = (
    "Wirtschaft-Politik", "Praktische Philosophie", "Spanisch",
    "Niederländisch", "Ergänzungsstunde",
)


@pytest.fixture
def workbook_path(tmp_path: Path) -> Path:
    path = tmp_path / "import.xlsx"
    _write_mini_workbook(path)
    return path


def _append_row(path: Path, sheet_name: str, values: list) -> int:
    """Hängt eine Zeile an die Spalte A an und gibt ihre Nummer zurück."""
    workbook = openpyxl.load_workbook(path)
    sheet = workbook[sheet_name]
    row = max(c.row for c in sheet["A"] if c.value is not None) + 1
    for column, value in enumerate(values, 1):
        sheet.cell(row=row, column=column, value=value)
    workbook.save(path)
    return row


def _set_cell(
    path: Path, sheet_name: str, row: int, column: int, value: object
) -> None:
    workbook = openpyxl.load_workbook(path)
    workbook[sheet_name].cell(row=row, column=column, value=value)
    workbook.save(path)


def _subject_row_number(path: Path, subject: str) -> int:
    sheet = openpyxl.load_workbook(path)[SUBJECT_SHEET]
    return next(c.row for c in sheet["A"] if c.value == subject)


def _add_new_subject(
    path: Path, room_type: str = "", double: str = "nein"
) -> None:
    """Neues Fach: Fächerliste, Stundentafel Jg. 5 und eine Lehrkraft."""
    _append_row(path, SUBJECT_SHEET, [
        NEW_SUBJECT, "As", "nw", "nein", room_type, double,
    ])
    sheet = openpyxl.load_workbook(path)[CURRICULUM_SHEET]
    grade_column = next(
        c.column for c in sheet[1]
        if str(c.value).endswith(f" {NEW_SUBJECT_GRADE}")
    )
    hours = [None] * (grade_column - 2) + [NEW_SUBJECT_HOURS]
    _append_row(path, CURRICULUM_SHEET, [NEW_SUBJECT, *hours])
    _set_cell(path, TEACHER_SHEET, NEW_SUBJECT_TEACHER_ROW,
              THIRD_SUBJECT_COLUMN, NEW_SUBJECT)


def _import(path: Path) -> SchoolData:
    data, _ = import_from_excel(path, make_mini_config())
    return data


def _import_solvable(path: Path) -> SchoolData:
    """Import mit Deputatsgrenzen und Kopplungen des Mini-Datensatzes.

    Die Vorlage leitet beides aus der Konfiguration ab (Grenzen für ein
    volles Deputat, drei Religionsgruppen je Jahrgang); mit zwei Klassen
    und zehn Lehrkräften ist das nicht lösbar.
    """
    data = _import(path)
    mini = make_mini_school_data()
    bounds = {t.id: t for t in mini.teachers}
    solvable = data.model_copy(update={
        "couplings": mini.couplings,
        "teachers": [
            t.model_copy(update={
                "deputat_min": bounds[t.id].deputat_min,
                "deputat_max": bounds[t.id].deputat_max,
            })
            for t in data.teachers
        ],
    })
    report = solvable.validate_feasibility()
    assert report.is_feasible, report.errors
    return solvable


def _subject(data: SchoolData, name: str) -> Subject:
    return next(s for s in data.subjects if s.name == name)


class TestDefaultSubjects:

    def test_default_list_matches_the_suggestion_table(self):
        names = [subject.name for subject in default_subjects()]
        assert names == list(SUBJECT_METADATA)

    @pytest.mark.parametrize("name", NRW_SUBJECTS)
    def test_default_list_contains_nrw_subjects(self, name: str):
        assert name in [subject.name for subject in default_subjects()]


class TestTemplate:

    def test_template_lists_all_default_subjects(self, workbook_path: Path):
        sheet = openpyxl.load_workbook(workbook_path)[SUBJECT_SHEET]
        names = [c.value for c in sheet["A"][1:] if c.value]
        assert names == [subject.name for subject in default_subjects()]

    def test_template_round_trips_subject_properties(
        self, workbook_path: Path
    ):
        data = _import(workbook_path)
        assert data.subjects == default_subjects()

    def test_teacher_dropdown_points_to_subject_sheet(
        self, workbook_path: Path
    ):
        sheet = openpyxl.load_workbook(workbook_path)[TEACHER_SHEET]
        formulas = [
            v.formula1 for v in sheet.data_validations.dataValidation
        ]
        assert any(SUBJECT_SHEET in formula for formula in formulas)


class TestImportSubjects:

    def test_workbook_without_sheet_uses_default_list(
        self, workbook_path: Path
    ):
        workbook = openpyxl.load_workbook(workbook_path)
        del workbook[SUBJECT_SHEET]
        workbook.save(workbook_path)

        assert _import(workbook_path).subjects == default_subjects()

    def test_new_subject_is_imported(self, workbook_path: Path):
        _add_new_subject(
            workbook_path, room_type="physik", double=DOUBLE_REQUIRED
        )
        data = _import(workbook_path)

        subject = _subject(data, NEW_SUBJECT)
        assert subject.short_name == "As"
        assert subject.category == "nw"
        assert subject.requires_special_room == "physik"
        assert subject.double_lesson_required
        assert not subject.double_lesson_preferred
        new_class = next(
            c for c in data.classes if c.id == NEW_SUBJECT_CLASS
        )
        assert new_class.curriculum[NEW_SUBJECT] == NEW_SUBJECT_HOURS
        teacher = next(
            t for t in data.teachers if t.id == NEW_SUBJECT_TEACHER
        )
        assert NEW_SUBJECT in teacher.subjects

    def test_preferred_double_lesson(self, workbook_path: Path):
        _add_new_subject(workbook_path, double=DOUBLE_PREFERRED)
        subject = _subject(_import(workbook_path), NEW_SUBJECT)

        assert subject.double_lesson_preferred
        assert not subject.double_lesson_required

    def test_duplicate_subject_is_error(self, workbook_path: Path):
        _append_row(workbook_path, SUBJECT_SHEET, ["deutsch", "D2"])

        with pytest.raises(ExcelImportError, match="mehrfach"):
            import_from_excel(workbook_path, make_mini_config())

    def test_invalid_double_lesson_value_is_error(
        self, workbook_path: Path
    ):
        _add_new_subject(workbook_path, double="immer")

        with pytest.raises(ExcelImportError, match="Doppelstunde 'immer'"):
            import_from_excel(workbook_path, make_mini_config())

    def test_unknown_category_is_warning(self, workbook_path: Path):
        row = _subject_row_number(workbook_path, "Deutsch")
        _set_cell(workbook_path, SUBJECT_SHEET, row, 3, "kernfach")
        data, report = import_from_excel(workbook_path, make_mini_config())

        assert _subject(data, "Deutsch").category == "sonstig"
        assert len(_matching(report.warnings, "Kategorie 'kernfach'")) == 1

    def test_empty_subject_sheet_is_error(self, workbook_path: Path):
        workbook = openpyxl.load_workbook(workbook_path)
        sheet = workbook[SUBJECT_SHEET]
        sheet.delete_rows(2, sheet.max_row)
        workbook.save(workbook_path)

        with pytest.raises(ExcelImportError, match="keine Fächer"):
            import_from_excel(workbook_path, make_mini_config())


class TestSubjectNames:
    """Fachnamen in den anderen Blättern müssen in der Liste stehen."""

    def test_similar_name_is_error_with_suggestion(
        self, workbook_path: Path
    ):
        _set_cell(workbook_path, TEACHER_SHEET, FIRST_TEACHER_ROW,
                  FIRST_SUBJECT_COLUMN, "Mathematk")

        with pytest.raises(ExcelImportError) as error:
            import_from_excel(workbook_path, make_mini_config())
        message = str(error.value)
        assert "Unbekanntes Fach 'Mathematk'" in message
        assert "Meinten Sie 'Mathematik'?" in message

    def test_letter_case_is_ignored(self, workbook_path: Path):
        _set_cell(workbook_path, TEACHER_SHEET, FIRST_TEACHER_ROW,
                  FIRST_SUBJECT_COLUMN, "deutsch")
        data = _import(workbook_path)

        assert data.teachers[0].subjects[0] == "Deutsch"

    def test_subject_removed_from_list_is_error_in_curriculum(
        self, workbook_path: Path
    ):
        workbook = openpyxl.load_workbook(workbook_path)
        sheet = workbook[SUBJECT_SHEET]
        sheet.delete_rows(_subject_row_number(workbook_path, "Erdkunde"))
        workbook.save(workbook_path)

        with pytest.raises(
            ExcelImportError, match="Unbekanntes Fach 'Erdkunde'"
        ):
            import_from_excel(workbook_path, make_mini_config())


class TestRoomSheetReachesSolver:

    def test_room_count_from_sheet_is_the_solver_capacity(
        self, workbook_path: Path
    ):
        config = make_mini_config()
        sheet = openpyxl.load_workbook(workbook_path)[ROOM_SHEET]
        row = next(c.row for c in sheet["A"] if c.value == "physik")
        _set_cell(workbook_path, ROOM_SHEET, row, 3, 1)
        _append_row(workbook_path, ROOM_SHEET, ["werken", "Werkraum", 2])
        data, _ = import_from_excel(workbook_path, config)

        assert data.config.rooms.get_capacity("physik") == 1
        assert data.config.rooms.get_capacity("werken") == 2
        assert len([r for r in data.rooms if r.room_type == "werken"]) == 2


class TestFeasibilityCheck:

    def test_subject_missing_from_list_is_error(self):
        data = make_mini_school_data()
        without_art = data.model_copy(update={
            "subjects": [s for s in data.subjects if s.name != "Kunst"]
        })
        report = without_art.validate_feasibility()

        errors = _matching(report.errors, "Fach 'Kunst' steht nicht")
        assert len(errors) == 1
        assert "Stundentafel 5a" in errors[0]
        assert "Lehrkraft T05" in errors[0]

    def test_complete_list_gives_no_error(self):
        report = make_mini_school_data().validate_feasibility()
        assert _matching(report.errors, "Fächerliste") == []


class TestSolverUsesSubjectList:

    def test_new_subject_appears_in_plan(self, workbook_path: Path):
        _add_new_subject(workbook_path)
        data = _import_solvable(workbook_path)
        solution = ScheduleSolver(data).solve(use_soft=False)

        assert solution.solver_status in ("OPTIMAL", "FEASIBLE")
        lessons = [
            e for e in solution.entries
            if e.subject == NEW_SUBJECT and e.class_id == NEW_SUBJECT_CLASS
        ]
        assert len(lessons) == NEW_SUBJECT_HOURS
        assert {e.teacher_id for e in lessons} == {NEW_SUBJECT_TEACHER}

    def test_new_subject_gets_room_and_required_double_lesson(
        self, workbook_path: Path
    ):
        _add_new_subject(
            workbook_path, room_type="physik", double=DOUBLE_REQUIRED
        )
        data = _import_solvable(workbook_path)
        solution = ScheduleSolver(data).solve(use_soft=False)

        assert solution.solver_status in ("OPTIMAL", "FEASIBLE")
        lessons = sorted(
            (e for e in solution.entries if e.subject == NEW_SUBJECT),
            key=lambda e: e.slot_number,
        )
        physics_rooms = {r.id for r in data.rooms if r.room_type == "physik"}
        assert {e.room for e in lessons} <= physics_rooms
        assert len({e.day for e in lessons}) == 1
        first, second = lessons
        blocks = {
            (b.slot_first, b.slot_second)
            for b in data.config.time_grid.double_blocks
        }
        assert (first.slot_number, second.slot_number) in blocks

    def test_double_rule_comes_from_the_data_set(self):
        data = make_mini_school_data()
        relaxed = data.model_copy(update={"subjects": [
            s.model_copy(update={
                "double_lesson_required": False,
                "double_lesson_preferred": False,
                "requires_special_room": None,
            })
            for s in data.subjects
        ]})
        solver = ScheduleSolver(relaxed)

        assert solver._double_required == set()
        assert solver._double_preferred == set()
        assert solver._room_type_by_subject == {}


class TestRelaxer:

    def test_no_double_relaxation_changes_only_its_copy(self):
        data = make_mini_school_data()
        relaxed = ConstraintRelaxer(data)._relax_no_double_required()

        assert not any(s.double_lesson_required for s in relaxed.subjects)
        assert any(s.double_lesson_required for s in data.subjects)
        assert SUBJECT_METADATA["Physik"]["double_required"] is True


class TestExportKeepsSubjects:

    def test_export_writes_subjects_and_curriculum_of_the_data(
        self, workbook_path: Path, tmp_path: Path
    ):
        _add_new_subject(workbook_path, double=DOUBLE_PREFERRED)
        data = _import(workbook_path)
        exported = tmp_path / "export.xlsx"
        export_workbook(data, exported)
        imported, _ = import_from_excel(exported, data.config)

        assert imported.subjects == data.subjects
        assert {c.id: c.curriculum for c in imported.classes} == {
            c.id: c.curriculum for c in data.classes
        }
