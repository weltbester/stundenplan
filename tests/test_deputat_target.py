"""Tests für das Soll-Deputat (halbe Stunden) und den Soll-Term."""

from collections import Counter
from pathlib import Path

import openpyxl
import pytest
from pydantic import ValidationError

from config.schema import TeacherConfig
from data.excel_data_export import export_workbook
from data.excel_import import ExcelImportError, import_from_excel
from data.fake_data import FakeDataGenerator
from models.deputat_check import (
    check_target_balance, teacher_lessons_needed, total_target_hours,
)
from models.school_data import SchoolData
from models.teacher import Teacher, format_hours, format_hours_delta
from solver.scheduler import ScheduleSolution, ScheduleSolver
from tests.test_fixed_assignments import (
    FIRST_TEACHER_ROW, TEACHER_SHEET, _matching, _write_mini_workbook,
)
from tests.test_solver import make_mini_config, make_mini_school_data

DEPUTAT_COLUMN = 6
HALF_LESSON_TARGET = 25.5
MAX_BUFFER = 6
TARGET_WEIGHT = 50
FLEXIBLE_TEACHER = "T10"
LOW_TARGET = 4.0
HIGH_TARGET = 9.0


def _teacher(**overrides: object) -> Teacher:
    values: dict[str, object] = {
        "id": "TST", "name": "Test, A", "subjects": ["Deutsch"],
        "deputat_min": 16, "deputat_max": 32,
    }
    values.update(overrides)
    return Teacher(**values)


@pytest.fixture
def workbook_path(tmp_path: Path) -> Path:
    path = tmp_path / "import.xlsx"
    _write_mini_workbook(path)
    return path


def _set_deputat(path: Path, value: object) -> None:
    workbook = openpyxl.load_workbook(path)
    cell = workbook[TEACHER_SHEET].cell(
        row=FIRST_TEACHER_ROW, column=DEPUTAT_COLUMN
    )
    cell.value = value  # auch None: Zelle leeren
    workbook.save(path)


def _first_teacher(path: Path) -> Teacher:
    data, _ = import_from_excel(path, make_mini_config())
    return data.teachers[0]


def _loads(solution: ScheduleSolution) -> Counter:
    """Wochenstunden je Lehrkraft (Kopplungstermine einmal gezählt)."""
    lessons = {
        (e.teacher_id, e.day, e.slot_number) for e in solution.entries
    }
    return Counter(teacher_id for teacher_id, _, _ in lessons)


class TestFormatHours:

    @pytest.mark.parametrize("hours, text", [
        (26, "26"), (26.0, "26"), (25.5, "25,5"), (0.5, "0,5"),
    ])
    def test_format_hours(self, hours: float, text: str):
        assert format_hours(hours) == text

    @pytest.mark.parametrize("hours, text", [
        (1, "+1"), (-0.5, "-0,5"), (0, "±0"), (-10, "-10"),
    ])
    def test_format_hours_delta(self, hours: float, text: str):
        assert format_hours_delta(hours) == text


class TestTeacherTarget:

    def test_half_lesson_target_is_accepted(self):
        teacher = _teacher(deputat_soll=HALF_LESSON_TARGET)

        assert teacher.target_hours(MAX_BUFFER) == HALF_LESSON_TARGET
        assert teacher.target_half_lessons(MAX_BUFFER) == 51

    def test_quarter_lesson_target_is_rejected(self):
        with pytest.raises(ValidationError, match="halbe"):
            _teacher(deputat_soll=25.3)

    def test_target_outside_bounds_is_rejected(self):
        with pytest.raises(ValidationError, match="außerhalb"):
            _teacher(deputat_soll=33)

    def test_old_data_derives_target_from_upper_bound(self):
        assert _teacher().target_hours(MAX_BUFFER) == 26.0

    def test_derived_target_stays_within_bounds(self):
        teacher = _teacher(deputat_min=4, deputat_max=9)
        assert teacher.target_hours(MAX_BUFFER) == 4.0

    def test_old_json_without_target_still_loads(self):
        old = _teacher().model_dump()
        del old["deputat_soll"]

        assert Teacher.model_validate(old).deputat_soll is None


class TestBoundsFromTarget:

    def test_whole_target_keeps_the_previous_bounds(self):
        assert TeacherConfig().deputat_bounds(26) == (16, 32)

    def test_half_target_rounds_outwards(self):
        config = TeacherConfig(deputat_max_buffer=2, deputat_min_buffer=2)
        assert config.deputat_bounds(HALF_LESSON_TARGET) == (23, 28)

    def test_lower_bound_never_exceeds_the_target(self):
        config = TeacherConfig(deputat_min_fraction=0.8)
        assert config.deputat_bounds(9) == (9, 15)

    def test_lower_bound_is_at_least_one(self):
        config = TeacherConfig(deputat_min_buffer=5)
        assert config.deputat_bounds(2)[0] == 1


class TestImportAndExport:

    @pytest.mark.parametrize("cell", ["25,5", "25.5", 25.5])
    def test_half_lesson_deputat_is_imported(
        self, workbook_path: Path, cell: object
    ):
        _set_deputat(workbook_path, cell)
        teacher = _first_teacher(workbook_path)

        assert teacher.deputat_soll == HALF_LESSON_TARGET
        assert teacher.deputat_min <= 25
        assert teacher.deputat_max >= 26

    def test_empty_deputat_uses_full_time_default(
        self, workbook_path: Path
    ):
        _set_deputat(workbook_path, None)
        expected = make_mini_config().teachers.vollzeit_deputat

        assert _first_teacher(workbook_path).deputat_soll == expected

    @pytest.mark.parametrize("cell", ["25,3", "viel", -2])
    def test_invalid_deputat_is_error(
        self, workbook_path: Path, cell: object
    ):
        _set_deputat(workbook_path, cell)

        with pytest.raises(ExcelImportError, match="Deputat"):
            import_from_excel(workbook_path, make_mini_config())

    def test_export_keeps_half_lesson_target(
        self, workbook_path: Path, tmp_path: Path
    ):
        _set_deputat(workbook_path, "25,5")
        data, _ = import_from_excel(workbook_path, make_mini_config())
        exported = tmp_path / "export.xlsx"
        export_workbook(data, exported)
        imported, _ = import_from_excel(exported, data.config)

        assert [t.deputat_soll for t in imported.teachers] == [
            t.deputat_soll for t in data.teachers
        ]
        assert imported.teachers[0].deputat_soll == HALF_LESSON_TARGET


class TestGeneratedData:

    def test_generated_teachers_have_a_target_within_bounds(self):
        data = FakeDataGenerator(make_mini_config(), seed=42).generate()

        for teacher in data.teachers:
            assert teacher.deputat_soll is not None
            assert (
                teacher.deputat_min
                <= teacher.deputat_soll
                <= teacher.deputat_max
            )


class TestTargetBalance:

    def test_coupled_lessons_count_once_per_group(self):
        data = make_mini_school_data()
        covered_hours = sum(
            hours
            for school_class in data.classes
            for subject, hours in school_class.curriculum.items()
            if subject in ("Religion", "Ethik", "WPF")
        )
        group_hours = sum(
            g.hours_per_week for c in data.couplings for g in c.groups
        )
        class_hours = sum(
            sum(c.curriculum.values()) for c in data.classes
        )

        assert teacher_lessons_needed(data.classes, data.couplings) == (
            class_hours - covered_hours + group_hours
        )

    def test_targets_far_above_demand_give_warning(self):
        data = make_mini_school_data()
        teachers = [
            t.model_copy(update={"deputat_soll": 9.0})
            for t in data.teachers
        ]
        warnings = check_target_balance(
            teachers, data.classes, data.couplings, MAX_BUFFER
        )

        assert len(warnings) == 1
        assert "über dem Unterrichtsbedarf" in warnings[0]

    def test_matching_targets_give_no_warning(self):
        data = make_mini_school_data()
        needed = teacher_lessons_needed(data.classes, data.couplings)
        share = round(needed / len(data.teachers) * 2) / 2
        teachers = [
            t.model_copy(update={
                "deputat_soll": share, "deputat_min": 1, "deputat_max": 40,
            })
            for t in data.teachers
        ]

        assert total_target_hours(teachers, MAX_BUFFER) == pytest.approx(
            needed, rel=0.05
        )
        assert check_target_balance(
            teachers, data.classes, data.couplings, MAX_BUFFER
        ) == []

    def test_feasibility_report_contains_the_warning(self):
        data = make_mini_school_data()
        teachers = [
            t.model_copy(update={"deputat_soll": 9.0})
            for t in data.teachers
        ]
        report = data.model_copy(
            update={"teachers": teachers}
        ).validate_feasibility()

        assert len(_matching(report.warnings, "Soll-Deputate")) == 1

    def test_summary_shows_total_target(self):
        assert "Soll-Deputate:" in make_mini_school_data().summary()


class TestSolverTargetTerm:
    """Der Solver zieht eine Lehrkraft zu ihrem Soll."""

    def _load_with_target(self, target: float) -> int:
        data = make_mini_school_data()
        data.config.solver.weight_deputat_deviation = TARGET_WEIGHT
        teachers = [
            t.model_copy(update={"deputat_soll": target})
            if t.id == FLEXIBLE_TEACHER else t
            for t in data.teachers
        ]
        solution = ScheduleSolver(
            data.model_copy(update={"teachers": teachers})
        ).solve(use_soft=False)
        assert solution.solver_status == "OPTIMAL"
        return _loads(solution)[FLEXIBLE_TEACHER]

    def test_higher_target_gives_more_lessons(self):
        low = self._load_with_target(LOW_TARGET)
        high = self._load_with_target(HIGH_TARGET)

        assert low == LOW_TARGET
        assert high > low

    def test_loads_stay_within_hard_bounds(self):
        data = make_mini_school_data()
        data.config.solver.weight_deputat_deviation = TARGET_WEIGHT
        solution = ScheduleSolver(data).solve(use_soft=False)
        loads = _loads(solution)

        for teacher in data.teachers:
            assert (
                teacher.deputat_min
                <= loads[teacher.id]
                <= teacher.deputat_max
            )
