"""Tests für den Excel-Import: Beispielzeilen, Räume, Stundentafel."""

from pathlib import Path

import openpyxl
import pytest

from config.defaults import STUNDENTAFEL_GYMNASIUM_SEK1, default_school_config
from data.excel_import import (
    CURRICULUM_SHEET, EXAMPLE_PREFIX, ExcelImportError, generate_template,
    import_from_excel,
)
from data.fake_data import FakeDataGenerator
from tests.test_fixed_assignments import _matching, _write_mini_workbook
from tests.test_solver import make_mini_config

TEACHER_SHEET = "Lehrkräfte"
ROOM_SHEET = "Fachräume"
COUPLING_SHEET = "Kopplungen"
EXAMPLE_ROW = 2
LEGACY_EXAMPLE = [
    "Müller, Hans", "MÜL", "Mathematik", "Physik", "",
    26, "nein", "Mi5", "Fr", 6, 2,
]


@pytest.fixture
def workbook_path(tmp_path: Path) -> Path:
    path = tmp_path / "import.xlsx"
    _write_mini_workbook(path)
    return path


def _edit(path: Path, sheet_name: str, cell: str, value: object) -> None:
    workbook = openpyxl.load_workbook(path)
    workbook[sheet_name][cell] = value
    workbook.save(path)


def _set_row(path: Path, sheet_name: str, row: int, values: list) -> None:
    workbook = openpyxl.load_workbook(path)
    for column, value in enumerate(values, 1):
        workbook[sheet_name].cell(row=row, column=column, value=value)
    workbook.save(path)


def _curriculum_cell(path: Path, subject: str, grade: int) -> str:
    """Zellbezug im Blatt Stundentafel für Fach und Jahrgang."""
    sheet = openpyxl.load_workbook(path)[CURRICULUM_SHEET]
    column = next(
        c.column for c in sheet[1] if str(c.value).endswith(f" {grade}")
    )
    row = next(c.row for c in sheet["A"] if c.value == subject)
    return sheet.cell(row=row, column=column).coordinate


def _curriculum(path: Path, class_id: str) -> dict[str, int]:
    data, _ = import_from_excel(path, make_mini_config())
    return next(c for c in data.classes if c.id == class_id).curriculum


class TestRooms:

    def test_template_rooms_import_without_phantoms(
        self, workbook_path: Path
    ):
        config = make_mini_config()
        expected = sum(room.count for room in config.rooms.special_rooms)
        data, report = import_from_excel(workbook_path, config)
        room_ids = [room.id for room in data.rooms]
        assert len(room_ids) == expected
        assert len(set(room_ids)) == expected
        assert _matching(report.warnings, "mehrfach") == []

    def test_repeated_room_type_gets_unique_ids_and_warning(
        self, workbook_path: Path
    ):
        config = make_mini_config()
        base = sum(room.count for room in config.rooms.special_rooms)
        next_row = len(config.rooms.special_rooms) + 2
        _set_row(workbook_path, ROOM_SHEET, next_row,
                 ["sport", "Schwimmhalle", 2])
        data, report = import_from_excel(workbook_path, config)
        room_ids = [room.id for room in data.rooms]
        assert len(room_ids) == base + 2
        assert len(set(room_ids)) == len(room_ids)
        assert len(_matching(report.warnings, "Raumtyp 'sport'")) == 1


class TestTeacherExampleRow:

    def test_template_example_is_marked_and_skipped(
        self, workbook_path: Path
    ):
        sheet = openpyxl.load_workbook(workbook_path)[TEACHER_SHEET]
        assert sheet.cell(row=EXAMPLE_ROW, column=1).value.startswith(
            EXAMPLE_PREFIX
        )
        data, _ = import_from_excel(workbook_path, make_mini_config())
        assert "MÜL" not in [teacher.id for teacher in data.teachers]

    def test_legacy_example_row_is_still_skipped(self, workbook_path: Path):
        _set_row(workbook_path, TEACHER_SHEET, EXAMPLE_ROW, LEGACY_EXAMPLE)
        data, _ = import_from_excel(workbook_path, make_mini_config())
        assert "MÜL" not in [teacher.id for teacher in data.teachers]

    def test_real_teacher_with_abbreviation_muel_is_imported(
        self, workbook_path: Path
    ):
        real = ["Mühlen, Petra", "MÜL", "Deutsch", "Sport", "", 20, "nein"]
        _set_row(workbook_path, TEACHER_SHEET, 20, real)
        data, _ = import_from_excel(workbook_path, make_mini_config())
        teacher = next(t for t in data.teachers if t.id == "MÜL")
        assert teacher.name == "Mühlen, Petra"
        assert teacher.subjects == ["Deutsch", "Sport"]


class TestCouplingSheet:

    def test_template_lists_all_config_couplings(self, tmp_path: Path):
        config = default_school_config()
        path = tmp_path / "vorlage.xlsx"
        generate_template(config, path)
        sheet = openpyxl.load_workbook(path)[COUPLING_SHEET]
        ids = [cell.value for cell in sheet["A"][1:] if cell.value]
        expected = [c.id for c in FakeDataGenerator(config).generate_couplings()]
        assert ids == expected
        assert "reli_10" in ids and "wpf_9" in ids

    def test_import_reads_config_couplings(self, workbook_path: Path):
        config = make_mini_config()
        data, _ = import_from_excel(workbook_path, config)
        expected = FakeDataGenerator(config).generate_couplings()
        assert [(c.id, c.involved_class_ids) for c in data.couplings] == [
            (c.id, c.involved_class_ids) for c in expected
        ]


class TestCurriculumSheet:

    def test_unchanged_sheet_equals_builtin_table(
        self, workbook_path: Path
    ):
        builtin = {
            s: h for s, h in STUNDENTAFEL_GYMNASIUM_SEK1[5].items() if h > 0
        }
        assert _curriculum(workbook_path, "5a") == builtin

    def test_changed_hours_are_used(self, workbook_path: Path):
        cell = _curriculum_cell(workbook_path, "Deutsch", 5)
        _edit(workbook_path, CURRICULUM_SHEET, cell, 5)
        assert _curriculum(workbook_path, "5a")["Deutsch"] == 5
        assert _curriculum(workbook_path, "7a")["Deutsch"] == 4

    def test_emptied_cell_removes_subject(self, workbook_path: Path):
        cell = _curriculum_cell(workbook_path, "Politik", 5)
        _edit(workbook_path, CURRICULUM_SHEET, cell, None)
        assert "Politik" not in _curriculum(workbook_path, "5a")

    def test_added_subject_appears(self, workbook_path: Path):
        cell = _curriculum_cell(workbook_path, "Informatik", 7)
        _edit(workbook_path, CURRICULUM_SHEET, cell, 1)
        assert _curriculum(workbook_path, "7a")["Informatik"] == 1

    def test_invalid_hours_name_the_cell(self, workbook_path: Path):
        cell = _curriculum_cell(workbook_path, "Deutsch", 5)
        _edit(workbook_path, CURRICULUM_SHEET, cell, "viel")
        with pytest.raises(ExcelImportError) as error:
            import_from_excel(workbook_path, make_mini_config())
        assert f"{CURRICULUM_SHEET} {cell}" in str(error.value)

    def test_unknown_subject_row_is_error(self, workbook_path: Path):
        _edit(workbook_path, CURRICULUM_SHEET, "A2", "Xylophonbau")
        with pytest.raises(ExcelImportError, match="Unbekanntes Fach"):
            import_from_excel(workbook_path, make_mini_config())

    def test_missing_sheet_falls_back_silently(self, workbook_path: Path):
        workbook = openpyxl.load_workbook(workbook_path)
        del workbook[CURRICULUM_SHEET]
        workbook.save(workbook_path)
        data, report = import_from_excel(workbook_path, make_mini_config())
        builtin = {
            s: h for s, h in STUNDENTAFEL_GYMNASIUM_SEK1[5].items() if h > 0
        }
        assert next(c for c in data.classes if c.id == "5a").curriculum == (
            builtin
        )
        assert _matching(report.warnings, CURRICULUM_SHEET) == []

    def test_missing_grade_column_warns_and_falls_back(
        self, workbook_path: Path
    ):
        workbook = openpyxl.load_workbook(workbook_path)
        sheet = workbook[CURRICULUM_SHEET]
        column = next(
            c.column for c in sheet[1] if str(c.value).endswith(" 7")
        )
        sheet.delete_cols(column)
        workbook.save(workbook_path)
        data, report = import_from_excel(workbook_path, make_mini_config())
        class_7a = next(c for c in data.classes if c.id == "7a")
        assert class_7a.curriculum["Deutsch"] == 4
        assert len(_matching(report.warnings, "Jahrgang 7 fehlt")) == 1
