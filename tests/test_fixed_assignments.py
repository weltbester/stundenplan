"""Tests für die vorgegebene Unterrichtsverteilung (Modell, Vorlage, Import)."""

from pathlib import Path
from typing import Optional

import openpyxl
import pytest

from data.excel_import import (
    ASSIGNMENT_SHEET, COUPLING_MARK, HINT_PREFIX, NOT_TAUGHT_MARK,
    ExcelImportError, generate_template, import_from_excel,
)
from models.coupling import CouplingGroup
from models.fixed_assignment import FixedAssignment
from models.school_data import FeasibilityReport, SchoolData
from tests.test_solver import make_mini_config, make_mini_school_data

SLOTS_PER_WEEK = 35
TEACHER_SHEET = "Lehrkräfte"
COUPLING_SHEET = "Kopplungen"
FIRST_TEACHER_ROW = 3
COUPLING_GROUPS_COLUMN = 4
EXAMPLE_COUPLING_ROW = 2


# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def _fixed(class_id: str, subject: str, teacher_id: str) -> FixedAssignment:
    return FixedAssignment(
        class_id=class_id, subject=subject, teacher_id=teacher_id
    )


def _check(
    assignments: list[FixedAssignment],
    data: Optional[SchoolData] = None,
) -> FeasibilityReport:
    """Machbarkeits-Check des Mini-Datensatzes mit den Vorgaben."""
    base = data or make_mini_school_data()
    with_fixed = base.model_copy(update={"fixed_assignments": assignments})
    return with_fixed.validate_feasibility()


def _matching(messages: list[str], fragment: str) -> list[str]:
    return [message for message in messages if fragment in message]


def _write_mini_workbook(path: Path) -> None:
    """Vorlage für 5a + 7a mit den zehn Mini-Lehrkräften."""
    generate_template(make_mini_config(), path)
    workbook = openpyxl.load_workbook(path)
    sheet = workbook[TEACHER_SHEET]
    teachers = make_mini_school_data().teachers
    for row, teacher in enumerate(teachers, FIRST_TEACHER_ROW):
        subjects = (teacher.subjects + ["", ""])[:3]
        values = [teacher.name, teacher.id, *subjects, teacher.deputat_max]
        for column, value in enumerate(values, 1):
            sheet.cell(row=row, column=column, value=value)
    workbook.save(path)


def _set_matrix_cell(
    path: Path, class_id: str, subject: str, value: str
) -> str:
    """Schreibt `value` in die Matrix und gibt den Zellbezug zurück."""
    workbook = openpyxl.load_workbook(path)
    sheet = workbook[ASSIGNMENT_SHEET]
    column = next(c.column for c in sheet[1] if c.value == subject)
    row = next(c.row for c in sheet["A"] if c.value == class_id)
    cell = sheet.cell(row=row, column=column, value=value)
    workbook.save(path)
    return cell.coordinate


@pytest.fixture
def workbook_path(tmp_path: Path) -> Path:
    path = tmp_path / "import.xlsx"
    _write_mini_workbook(path)
    return path


# ─── Modell ───────────────────────────────────────────────────────────────────

class TestModel:

    def test_teacher_id_is_normalized(self):
        assignment = _fixed(" 5a ", " Deutsch", " mül ")
        assert assignment.teacher_id == "MÜL"
        assert assignment.class_id == "5a"
        assert assignment.subject == "Deutsch"

    def test_coupling_group_teacher_is_optional_and_normalized(self):
        group = CouplingGroup(
            group_name="ethik", subject="Ethik", hours_per_week=2
        )
        assert group.teacher_id is None
        assert CouplingGroup(
            group_name="ethik", subject="Ethik", hours_per_week=2,
            teacher_id=" t08 ",
        ).teacher_id == "T08"
        assert CouplingGroup(
            group_name="ethik", subject="Ethik", hours_per_week=2,
            teacher_id="  ",
        ).teacher_id is None

    def test_old_json_without_field_still_loads(self):
        dumped = make_mini_school_data().model_dump()
        del dumped["fixed_assignments"]
        for coupling in dumped["couplings"]:
            for group in coupling["groups"]:
                del group["teacher_id"]
        restored = SchoolData.model_validate(dumped)
        assert restored.fixed_assignments == []

    def test_json_round_trip_keeps_assignments(self, tmp_path: Path):
        data = make_mini_school_data().model_copy(update={
            "fixed_assignments": [_fixed("5a", "Deutsch", "T01")],
        })
        path = tmp_path / "data.json"
        data.save_json(path)
        restored = SchoolData.load_json(path)
        assert restored.fixed_assignments == data.fixed_assignments

    def test_summary_mentions_assignments_only_when_present(self):
        data = make_mini_school_data()
        assert "Unterrichtsverteilung" not in data.summary()
        with_fixed = data.model_copy(update={
            "fixed_assignments": [_fixed("5a", "Deutsch", "T01")],
        })
        assert "Unterrichtsverteilung: 1" in with_fixed.summary()


# ─── Plausibilitätsprüfung ────────────────────────────────────────────────────

class TestTeachableHours:
    """Teacher.teachable_hours: Sperrzeiten und Tagesmaximum zusammen."""

    DAYS = 5
    SLOTS = 7

    def _teacher(self, blocked: list[tuple[int, int]], per_day: int = 6):
        template = make_mini_school_data().teachers[0]
        return template.model_copy(update={
            "unavailable_slots": blocked, "max_hours_per_day": per_day,
        })

    def test_without_blocks_daily_maximum_limits(self):
        teacher = self._teacher([])
        assert teacher.teachable_hours(self.DAYS, self.SLOTS) == 30

    def test_fully_blocked_day_counts_zero(self):
        blocked = [(0, slot) for slot in range(1, 8)]
        teacher = self._teacher(blocked)
        assert teacher.teachable_hours(self.DAYS, self.SLOTS) == 24

    def test_partly_blocked_day_counts_free_slots(self):
        """Mo 3 frei, Di–Do je 6 (Tagesmaximum), Fr gesperrt → 21."""
        blocked = [(0, slot) for slot in range(4, 8)]
        blocked += [(4, slot) for slot in range(1, 8)]
        teacher = self._teacher(blocked)
        assert teacher.teachable_hours(self.DAYS, self.SLOTS) == 21

    def test_blocks_outside_the_grid_are_ignored(self):
        teacher = self._teacher([(0, 9), (6, 1)], per_day=7)
        assert teacher.teachable_hours(self.DAYS, self.SLOTS) == 35


class TestFeasibilityCheck:

    def test_valid_assignment_adds_no_problem(self):
        baseline = _check([])
        report = _check([_fixed("5a", "Deutsch", "T01")])
        assert report.errors == baseline.errors
        assert report.warnings == baseline.warnings

    @pytest.mark.parametrize("assignment, fragment", [
        (_fixed("9z", "Deutsch", "T01"), "Unbekannte Klasse '9z'"),
        (_fixed("5a", "Deutsch", "XXX"), "Unbekanntes Kürzel 'XXX'"),
        (_fixed("5a", "Physik", "T02"), "nicht in der Stundentafel"),
        (_fixed("5a", "Religion", "T08"), "über eine Kopplung"),
    ])
    def test_reference_problems_are_errors(
        self, assignment: FixedAssignment, fragment: str
    ):
        report = _check([assignment])
        assert not report.is_feasible
        assert len(_matching(report.errors, fragment)) == 1

    def test_two_teachers_for_one_subject_is_error(self):
        report = _check([
            _fixed("5a", "Deutsch", "T01"), _fixed("5a", "Deutsch", "T07"),
        ])
        assert len(_matching(report.errors, "genau eine")) == 1

    def test_out_of_field_is_warning_not_error(self):
        baseline = _check([])
        report = _check([_fixed("5a", "Deutsch", "T02")])
        assert report.errors == baseline.errors
        assert len(_matching(report.warnings, "fachfremd")) == 1

    def test_more_than_deputat_max_is_error(self):
        """T01: 4h + 4h + 2h = 10h bei Deputat-Max 9h."""
        report = _check([
            _fixed("5a", "Deutsch", "T01"),
            _fixed("7a", "Deutsch", "T01"),
            _fixed("5a", "Geschichte", "T01"),
        ])
        problems = _matching(report.errors, "Deputat-Max")
        assert len(problems) == 1
        assert "T01" in problems[0] and "10h" in problems[0]

    def test_more_than_unblocked_slots_is_error(self):
        """T01 hat nur 2 Stunden ohne Sperrzeit, soll aber 4h geben."""
        data = make_mini_school_data()
        all_slots = [(day, slot) for day in range(5) for slot in range(1, 8)]
        blocked = all_slots[:SLOTS_PER_WEEK - 2]
        teachers = [
            t.model_copy(update={"unavailable_slots": blocked})
            if t.id == "T01" else t
            for t in data.teachers
        ]
        data = data.model_copy(update={"teachers": teachers})
        report = _check([_fixed("5a", "Deutsch", "T01")], data)
        assert len(_matching(report.errors, "ohne Sperrzeit")) == 1

    def test_more_than_daily_capacity_is_error(self):
        """T01: 7 freie Stunden an einem Tag, aber höchstens 3h pro Tag.

        4h Deutsch passen in die freien Stunden, nicht ins Tagesmaximum.
        """
        data = make_mini_school_data()
        blocked = [(day, slot) for day in range(1, 5) for slot in range(1, 8)]
        teachers = [
            t.model_copy(update={
                "unavailable_slots": blocked, "max_hours_per_day": 3,
            })
            if t.id == "T01" else t
            for t in data.teachers
        ]
        data = data.model_copy(update={"teachers": teachers})
        report = _check([_fixed("5a", "Deutsch", "T01")], data)
        problems = _matching(report.errors, "ohne Sperrzeit")
        assert len(problems) == 1
        assert "4h fest" in problems[0] and "nur 3h" in problems[0]

    def test_unreachable_deputat_min_is_error(self):
        """Alle Deutsch-/Geschichtsstunden vergeben → T01 bleibt bei 0h."""
        report = _check([
            _fixed("5a", "Deutsch", "T07"),
            _fixed("7a", "Deutsch", "T10"),
            _fixed("5a", "Geschichte", "T03"),
            _fixed("7a", "Geschichte", "T03"),
        ])
        problems = _matching(report.errors, "nicht erreichbar")
        assert len(problems) == 1
        assert "T01" in problems[0]

    def test_unknown_coupling_teacher_is_error(self):
        data = make_mini_school_data()
        data.couplings[0].groups[0].teacher_id = "XXX"
        report = _check([], data)
        assert len(_matching(report.errors, "Unbekanntes Kürzel 'XXX'")) == 1

    def test_coupling_hours_count_towards_deputat(self):
        """T08: 2 Kopplungsgruppen à 2h + 4h + 2h fest = 10h > 9h."""
        data = make_mini_school_data()
        for coupling in data.couplings:
            coupling.groups[0].teacher_id = "T08"
        report = _check([
            _fixed("5a", "Deutsch", "T08"),
            _fixed("5a", "Geschichte", "T08"),
        ], data)
        problems = _matching(report.errors, "Deputat-Max")
        assert len(problems) == 1
        assert "T08" in problems[0] and "10h" in problems[0]


# ─── Excel-Vorlage ────────────────────────────────────────────────────────────

class TestTemplate:

    @pytest.fixture
    def sheet(self, workbook_path: Path):
        return openpyxl.load_workbook(workbook_path)[ASSIGNMENT_SHEET]

    def _cell(self, sheet, class_id: str, subject: str):
        column = next(c.column for c in sheet[1] if c.value == subject)
        row = next(c.row for c in sheet["A"] if c.value == class_id)
        return sheet.cell(row=row, column=column)

    def test_header_and_class_rows(self, sheet):
        header = [cell.value for cell in sheet[1]]
        assert header[0] == "Klasse"
        assert {"Deutsch", "Mathematik", "Sport"} <= set(header)
        assert [sheet["A2"].value, sheet["A3"].value] == ["5a", "7a"]

    def test_taught_subject_cell_is_empty(self, sheet):
        assert self._cell(sheet, "5a", "Deutsch").value is None

    def test_not_taught_subject_is_marked(self, sheet):
        assert self._cell(sheet, "5a", "Physik").value == NOT_TAUGHT_MARK
        assert self._cell(sheet, "7a", "Physik").value is None

    def test_coupled_subject_is_marked(self, sheet):
        assert self._cell(sheet, "5a", "Religion").value == COUPLING_MARK

    def test_hint_row_is_present(self, sheet):
        first_column = [cell.value for cell in sheet["A"]]
        assert any(
            isinstance(value, str) and value.startswith(HINT_PREFIX)
            for value in first_column
        )


# ─── Excel-Import ─────────────────────────────────────────────────────────────

class TestImport:

    def test_untouched_template_gives_no_assignments(
        self, workbook_path: Path
    ):
        data, _ = import_from_excel(workbook_path, make_mini_config())
        assert data.fixed_assignments == []

    def test_filled_cells_are_imported(self, workbook_path: Path):
        _set_matrix_cell(workbook_path, "5a", "Deutsch", "t01")
        _set_matrix_cell(workbook_path, "7a", "Mathematik", "T02")
        data, _ = import_from_excel(workbook_path, make_mini_config())
        assert data.fixed_assignments == [
            _fixed("5a", "Deutsch", "T01"),
            _fixed("7a", "Mathematik", "T02"),
        ]

    def test_unknown_abbreviation_names_the_cell(self, workbook_path: Path):
        cell_ref = _set_matrix_cell(workbook_path, "5a", "Deutsch", "XYZ")
        with pytest.raises(ExcelImportError) as error:
            import_from_excel(workbook_path, make_mini_config())
        message = str(error.value)
        assert cell_ref in message
        assert "Unbekanntes Kürzel 'XYZ'" in message
        assert "Klasse 5a, Fach Deutsch" in message

    def test_entry_for_subject_not_taught_is_error(
        self, workbook_path: Path
    ):
        cell_ref = _set_matrix_cell(workbook_path, "5a", "Physik", "T02")
        with pytest.raises(ExcelImportError) as error:
            import_from_excel(workbook_path, make_mini_config())
        assert cell_ref in str(error.value)
        assert "Stundentafel" in str(error.value)

    def test_entry_for_coupled_subject_is_ignored_with_warning(
        self, workbook_path: Path
    ):
        cell_ref = _set_matrix_cell(workbook_path, "5a", "Religion", "T08")
        data, report = import_from_excel(workbook_path, make_mini_config())
        assert data.fixed_assignments == []
        assert len(_matching(report.warnings, cell_ref)) == 1

    def test_unknown_class_row_is_error(self, workbook_path: Path):
        workbook = openpyxl.load_workbook(workbook_path)
        workbook[ASSIGNMENT_SHEET]["A2"] = "5x"
        workbook.save(workbook_path)
        with pytest.raises(ExcelImportError, match="Unbekannte Klasse '5x'"):
            import_from_excel(workbook_path, make_mini_config())

    def test_duplicate_class_row_is_error(self, workbook_path: Path):
        workbook = openpyxl.load_workbook(workbook_path)
        workbook[ASSIGNMENT_SHEET]["A3"] = "5a"
        workbook.save(workbook_path)
        with pytest.raises(ExcelImportError, match="mehrfach"):
            import_from_excel(workbook_path, make_mini_config())

    def test_workbook_without_sheet_still_imports(
        self, workbook_path: Path
    ):
        workbook = openpyxl.load_workbook(workbook_path)
        del workbook[ASSIGNMENT_SHEET]
        workbook.save(workbook_path)
        data, _ = import_from_excel(workbook_path, make_mini_config())
        assert data.fixed_assignments == []

    def test_over_deputat_shows_up_in_feasibility_report(
        self, workbook_path: Path
    ):
        """T01 (Deputat 9 + Puffer 6 = 15h) bekommt 4+4+2+2+... > 15h."""
        for class_id in ("5a", "7a"):
            for subject in ("Deutsch", "Mathematik", "Englisch"):
                _set_matrix_cell(workbook_path, class_id, subject, "T01")
        _, report = import_from_excel(workbook_path, make_mini_config())
        assert not report.is_feasible
        assert len(_matching(report.errors, "Deputat-Max")) == 1

    def test_coupling_group_teacher_is_imported(self, workbook_path: Path):
        workbook = openpyxl.load_workbook(workbook_path)
        workbook[COUPLING_SHEET].cell(
            row=EXAMPLE_COUPLING_ROW, column=COUPLING_GROUPS_COLUMN,
            value="evangelisch:Religion:2:t08,ethik:Ethik:2",
        )
        workbook.save(workbook_path)
        data, _ = import_from_excel(workbook_path, make_mini_config())
        groups = data.couplings[0].groups
        assert [g.teacher_id for g in groups] == ["T08", None]


# ─── Export eines Datensatzes als ausgefüllte Vorlage ─────────────────────────

class TestExportWorkbook:

    @pytest.fixture(scope="class")
    def solved(self):
        from solver.scheduler import ScheduleSolver

        data = make_mini_school_data()
        solution = ScheduleSolver(data).solve(use_soft=False)
        assert solution.solver_status in ("OPTIMAL", "FEASIBLE")
        return data, solution

    def test_round_trip_keeps_teachers_and_assignments(
        self, solved, tmp_path: Path
    ):
        from data.excel_data_export import export_workbook

        data, solution = solved
        path = tmp_path / "export.xlsx"
        export_workbook(data, path, solution)
        imported, _ = import_from_excel(path, data.config)

        assert [(t.id, t.subjects) for t in imported.teachers] == [
            (t.id, t.subjects) for t in data.teachers
        ]
        expected = {
            (a.class_id, a.subject, a.teacher_id)
            for a in solution.assignments
        }
        actual = {
            (a.class_id, a.subject, a.teacher_id)
            for a in imported.fixed_assignments
        }
        assert actual == expected
        assert len(actual) > 0

    def test_round_trip_sets_coupling_teachers(self, solved, tmp_path: Path):
        from data.excel_data_export import export_workbook

        data, solution = solved
        path = tmp_path / "export.xlsx"
        export_workbook(data, path, solution)
        imported, _ = import_from_excel(path, data.config)

        assert [c.id for c in imported.couplings] == [
            c.id for c in data.couplings
        ]
        coupling_teachers = {
            (e.coupling_id, e.subject, e.teacher_id)
            for e in solution.entries if e.is_coupling
        }
        for coupling in imported.couplings:
            for group in coupling.groups:
                key = (coupling.id, group.subject, group.teacher_id)
                assert key in coupling_teachers

    def test_without_solution_writes_existing_fixed_assignments(
        self, tmp_path: Path
    ):
        from data.excel_data_export import export_workbook

        fixed = [_fixed("5a", "Deutsch", "T01")]
        data = make_mini_school_data().model_copy(
            update={"fixed_assignments": fixed}
        )
        path = tmp_path / "export.xlsx"
        export_workbook(data, path)
        imported, _ = import_from_excel(path, data.config)

        assert imported.fixed_assignments == fixed
        assert all(
            group.teacher_id is None
            for coupling in imported.couplings
            for group in coupling.groups
        )

    def test_export_does_not_duplicate_rooms(self, tmp_path: Path):
        from data.excel_data_export import export_workbook

        data = make_mini_school_data()
        path = tmp_path / "export.xlsx"
        export_workbook(data, path)
        imported, _ = import_from_excel(path, data.config)

        room_ids = [room.id for room in imported.rooms]
        assert len(room_ids) == len(set(room_ids))

    def test_cli_from_solution_requires_from_data(self, tmp_path: Path):
        from click.testing import CliRunner
        from main import cli

        solution_file = tmp_path / "solution.json"
        solution_file.write_text("{}", encoding="utf-8")
        result = CliRunner().invoke(cli, [
            "template", "-o", str(tmp_path / "out.xlsx"),
            "--from-solution", str(solution_file),
        ])
        assert result.exit_code == 1
        assert "--from-data" in result.output


# ─── Solver berücksichtigt die Vorgaben ───────────────────────────────────────

def _solve(data: SchoolData):
    from solver.scheduler import ScheduleSolver

    return ScheduleSolver(data).solve(use_soft=False)


def _teachers_of(solution, class_id: str, subject: str) -> set[str]:
    return {
        entry.teacher_id for entry in solution.entries
        if entry.class_id == class_id and entry.subject == subject
        and not entry.is_coupling
    }


def _assignment_set(solution) -> set[tuple[str, str, str]]:
    return {
        (a.class_id, a.subject, a.teacher_id) for a in solution.assignments
    }


class TestSolverUsesAssignments:

    @pytest.mark.parametrize("teacher_id", ["T01", "T07", "T10"])
    def test_fixed_teacher_teaches_the_subject(self, teacher_id: str):
        """Jede der drei Deutsch-Lehrkräfte lässt sich für 5a erzwingen."""
        data = make_mini_school_data().model_copy(update={
            "fixed_assignments": [_fixed("5a", "Deutsch", teacher_id)],
        })
        solution = _solve(data)
        assert solution.solver_status in ("OPTIMAL", "FEASIBLE")
        assert _teachers_of(solution, "5a", "Deutsch") == {teacher_id}
        assigned = {
            a.teacher_id for a in solution.assignments
            if a.class_id == "5a" and a.subject == "Deutsch"
        }
        assert assigned == {teacher_id}

    def test_out_of_field_teacher_is_respected(self):
        """T04 (Biologie/Erdkunde) übernimmt fachfremd Politik in 5a."""
        data = make_mini_school_data().model_copy(update={
            "fixed_assignments": [_fixed("5a", "Politik", "T04")],
        })
        solution = _solve(data)
        assert solution.solver_status in ("OPTIMAL", "FEASIBLE")
        assert _teachers_of(solution, "5a", "Politik") == {"T04"}

    def test_fixed_coupling_teacher_is_respected(self):
        data = make_mini_school_data()
        data.couplings[0].groups[0].teacher_id = "T09"
        solution = _solve(data)
        assert solution.solver_status in ("OPTIMAL", "FEASIBLE")
        coupling = data.couplings[0]
        group_subject = coupling.groups[0].subject
        teachers = {
            entry.teacher_id for entry in solution.entries
            if entry.coupling_id == coupling.id
            and entry.subject == group_subject
        }
        assert teachers == {"T09"}

    def test_full_distribution_is_reproduced_with_fewer_variables(self):
        """Plan lösen, Verteilung vorgeben, erneut lösen: gleiche Verteilung."""
        from data.excel_data_export import (
            assignments_from_solution, couplings_with_solution_teachers,
        )

        free_data = make_mini_school_data()
        free = _solve(free_data)
        assert free.solver_status in ("OPTIMAL", "FEASIBLE")

        fixed_data = free_data.model_copy(update={
            "fixed_assignments": assignments_from_solution(free),
            "couplings": couplings_with_solution_teachers(
                free_data.couplings, free
            ),
        })
        assert fixed_data.validate_feasibility().is_feasible
        fixed = _solve(fixed_data)

        assert fixed.solver_status in ("OPTIMAL", "FEASIBLE")
        assert _assignment_set(fixed) == _assignment_set(free)
        # Der Mini-Datensatz hat kaum Alternativen je Fach; bei 36 Klassen
        # ist die Ersparnis deutlich größer.
        assert fixed.num_variables < free.num_variables

    def test_impossible_distribution_is_infeasible(self):
        """T01 soll 10h geben, darf aber höchstens 9h: kein Plan."""
        data = make_mini_school_data().model_copy(update={
            "fixed_assignments": [
                _fixed("5a", "Deutsch", "T01"),
                _fixed("7a", "Deutsch", "T01"),
                _fixed("5a", "Geschichte", "T01"),
            ],
        })
        assert not data.validate_feasibility().is_feasible
        assert _solve(data).solver_status == "INFEASIBLE"

    def test_unknown_teacher_raises_clear_error(self):
        data = make_mini_school_data().model_copy(update={
            "fixed_assignments": [_fixed("5a", "Deutsch", "XXX")],
        })
        with pytest.raises(ValueError, match="unbekanntes Kürzel 'XXX'"):
            _solve(data)


class TestRelaxerKeepsAssignments:
    """Die INFEASIBLE-Diagnose rechnet mit der vorgegebenen Verteilung."""

    def test_relaxed_copies_keep_fixed_assignments(self):
        from solver.constraint_relaxer import ConstraintRelaxer

        fixed = [_fixed("5a", "Deutsch", "T01")]
        data = make_mini_school_data().model_copy(
            update={"fixed_assignments": fixed}
        )
        relaxer = ConstraintRelaxer(data)
        copies = [
            relaxer._relax_no_room_limits(),
            relaxer._relax_no_couplings(),
            relaxer._relax_no_gap_limit(),
            relaxer._relax_wider_deputat_bounds(),
            relaxer._relax_all_combined(),
        ]
        assert all(copy.fixed_assignments == fixed for copy in copies)
