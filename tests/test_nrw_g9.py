"""Tests für Schritt 4c: NRW-G9-Stundentafel, Sprachen-Schiene,
abschaltbare Regel C15 und Wochenstundenrahmen."""

from pathlib import Path

import openpyxl
import pytest

from analysis.solution_validator import SolutionValidator
from config.defaults import (
    SECOND_LANGUAGE_SUBJECT, STUNDENTAFEL_LEGACY, SUBJECT_METADATA,
    default_grades, default_rooms, default_school_config, default_time_grid,
)
from config.nrw_g9 import NRW_G9_WEEKLY_FRAME, STUNDENTAFEL_NRW_G9
from config.schema import (
    CouplingConfig, GradeConfig, GradeDefinition, SchoolConfig, SchoolType,
    SolverConfig,
)
from data.excel_import import (
    ASSIGNMENT_SHEET, COUPLING_HEADERS, COUPLING_MARK, CURRICULUM_SHEET,
    NOT_TAUGHT_MARK, ExcelImporter, ExcelImportError, builtin_curriculum,
    generate_template, import_from_excel,
)
from data.fake_data import FakeDataGenerator
from models.coupling import COUPLING_TYPE_BAND, Coupling, CouplingGroup
from models.school_class import SchoolClass
from models.school_data import SchoolData
from models.subject import default_subjects
from models.teacher import Teacher
from models.weekly_frame_check import check_weekly_frame
from solver.distribution import distribute_teachers
from solver.scheduler import ScheduleEntry, ScheduleSolution, ScheduleSolver

# ─── Kontingente der APO-S I NRW, Anlage 3a (G9, Fassung mit Informatik) ───
# Lernbereich → (Fächer, Stunden Kl. 5–6, Stunden Kl. 7–10)
QUOTAS: dict[str, tuple[tuple[str, ...], int, int]] = {
    "Deutsch": (("Deutsch",), 9, 13),
    "Gesellschaftslehre": (
        ("Geschichte", "Erdkunde", "Wirtschaft-Politik"), 6, 17,
    ),
    "Mathematik": (("Mathematik",), 9, 13),
    "Naturwissenschaften": (("Biologie", "Chemie", "Physik"), 6, 17),
    "Informatik": (("Informatik",), 2, 0),
    "Englisch": (("Englisch",), 9, 13),
    "Zweite Fremdsprache": ((SECOND_LANGUAGE_SUBJECT,), 0, 15),
    "Kunst/Musik": (("Kunst", "Musik"), 7, 10),
    "Religionslehre": (("Religion",), 4, 8),
    "Sport": (("Sport",), 7, 11),
    "Wahlpflicht": (("WPF",), 0, 6),
}
# Fach → Mindeststunden über die ganze Sekundarstufe I (Fußnoten 1, 2, 5)
MINIMUM_HOURS: dict[str, int] = {
    "Geschichte": 8, "Wirtschaft-Politik": 8, "Erdkunde": 7,
    "Biologie": 7, "Chemie": 7, "Physik": 7, "Kunst": 7, "Musik": 7,
}
# Diese Fächer müssen in Klasse 10 unterrichtet werden (Fußnoten 1, 2).
TAUGHT_IN_GRADE_10 = (
    "Geschichte", "Erdkunde", "Wirtschaft-Politik",
    "Biologie", "Chemie", "Physik",
)
EXTRA_SUBJECT = "Ergänzungsstunde"
CORE_HOURS_TOTAL = 182
MAX_EXTRA_HOURS = 6
LOWER_GRADES = (5, 6)
UPPER_GRADES = (7, 8, 9, 10)
CHEMISTRY_START_GRADE = 7
ELECTIVE_GRADES = (9, 10)

TEACHER_SHEET = "Lehrkräfte"
COUPLING_SHEET = "Kopplungen"
FIRST_TEACHER_ROW = 3
OLD_TYPE_HEADER = "Typ (reli_ethik/wpf)"
CURRICULUM_SUBJECT_COLUMN = len(COUPLING_HEADERS)
BAND_ID = "fs2_7"
BAND_HOURS = 4
MONDAY = 0
SOLVED = ("OPTIMAL", "FEASIBLE")


def _hours(subjects: tuple[str, ...], grades: tuple[int, ...]) -> int:
    """Summe der Stunden der Fächer in den Jahrgängen der NRW-Tafel."""
    return sum(
        STUNDENTAFEL_NRW_G9[grade].get(subject, 0)
        for grade in grades
        for subject in subjects
    )


# ─── Stundentafel ─────────────────────────────────────────────────────────────

class TestNrwTable:

    @pytest.mark.parametrize("area", list(QUOTAS))
    def test_quota_of_each_area_is_met(self, area: str):
        subjects, lower, upper = QUOTAS[area]
        assert _hours(subjects, LOWER_GRADES) == lower
        assert _hours(subjects, UPPER_GRADES) == upper

    def test_core_and_extra_hours(self):
        total = sum(sum(t.values()) for t in STUNDENTAFEL_NRW_G9.values())
        extra = _hours((EXTRA_SUBJECT,), LOWER_GRADES + UPPER_GRADES)
        assert total - extra == CORE_HOURS_TOTAL
        assert 0 <= extra <= MAX_EXTRA_HOURS

    def test_no_subject_outside_the_quotas(self):
        counted = {s for subjects, _, _ in QUOTAS.values() for s in subjects}
        used = {s for table in STUNDENTAFEL_NRW_G9.values() for s in table}
        assert used - counted == {EXTRA_SUBJECT}

    @pytest.mark.parametrize("subject", list(MINIMUM_HOURS))
    def test_minimum_hours_per_subject(self, subject: str):
        total = _hours((subject,), LOWER_GRADES + UPPER_GRADES)
        assert total >= MINIMUM_HOURS[subject]

    @pytest.mark.parametrize("subject", TAUGHT_IN_GRADE_10)
    def test_subject_is_taught_in_grade_10(self, subject: str):
        assert STUNDENTAFEL_NRW_G9[10].get(subject, 0) > 0

    def test_chemistry_and_electives_start_as_prescribed(self):
        for grade, table in STUNDENTAFEL_NRW_G9.items():
            if grade < CHEMISTRY_START_GRADE:
                assert "Chemie" not in table
            assert ("WPF" in table) == (grade in ELECTIVE_GRADES)

    @pytest.mark.parametrize("grade", list(STUNDENTAFEL_NRW_G9))
    def test_each_grade_is_inside_the_weekly_frame(self, grade: int):
        minimum, maximum = NRW_G9_WEEKLY_FRAME[grade]
        hours = sum(STUNDENTAFEL_NRW_G9[grade].values())
        assert minimum <= hours <= maximum

    def test_every_subject_is_in_the_default_subject_list(self):
        used = {s for table in STUNDENTAFEL_NRW_G9.values() for s in table}
        assert used <= set(SUBJECT_METADATA)

    def test_default_grade_targets_match_the_table(self):
        targets = {
            g.grade: g.weekly_hours_target for g in default_grades().grades
        }
        assert targets == {
            grade: sum(table.values())
            for grade, table in STUNDENTAFEL_NRW_G9.items()
        }

    def test_builtin_curriculum_is_the_nrw_table(self):
        assert builtin_curriculum() == STUNDENTAFEL_NRW_G9


# ─── Sprachen-Schiene: Erzeugung ──────────────────────────────────────────────

def _bands(couplings: list[Coupling]) -> list[Coupling]:
    return [c for c in couplings if c.coupling_type == COUPLING_TYPE_BAND]


class TestLanguageBandGeneration:

    def test_one_band_per_grade_with_second_language(self):
        config = default_school_config()
        bands = _bands(FakeDataGenerator(
            config, curriculum=STUNDENTAFEL_NRW_G9
        ).generate_couplings())
        assert [band.id for band in bands] == [
            "fs2_7", "fs2_8", "fs2_9", "fs2_10",
        ]
        for band in bands:
            grade = int(band.id.split("_")[1])
            hours = STUNDENTAFEL_NRW_G9[grade][SECOND_LANGUAGE_SUBJECT]
            assert band.hours_per_week == hours
            assert {g.hours_per_week for g in band.groups} == {hours}
            assert band.curriculum_subjects() == {SECOND_LANGUAGE_SUBJECT}
            assert len(band.involved_class_ids) == 6

    def test_one_group_per_class_alternating_languages(self):
        band = _bands(FakeDataGenerator(
            default_school_config(), curriculum=STUNDENTAFEL_NRW_G9
        ).generate_couplings())[0]
        assert [group.subject for group in band.groups] == [
            "Französisch", "Latein"
        ] * 3
        names = [group.group_name for group in band.groups]
        assert len(set(names)) == len(names)

    def test_single_class_still_gets_one_group_per_language(self):
        config = default_school_config().model_copy(update={
            "grades": GradeConfig(grades=[
                GradeDefinition(grade=7, num_classes=1),
            ]),
        })
        band = _bands(FakeDataGenerator(
            config, curriculum=STUNDENTAFEL_NRW_G9
        ).generate_couplings())[0]
        assert [group.subject for group in band.groups] == [
            "Französisch", "Latein",
        ]

    def test_legacy_table_has_no_band(self):
        generator = FakeDataGenerator(default_school_config())
        assert _bands(generator.generate_couplings()) == []
        legacy = FakeDataGenerator(
            default_school_config(), curriculum=STUNDENTAFEL_LEGACY
        )
        assert [c.id for c in legacy.generate_couplings()] == [
            c.id for c in generator.generate_couplings()
        ]

    def test_empty_language_list_disables_the_band(self):
        config = default_school_config().model_copy(update={
            "couplings": CouplingConfig(second_language_subjects=[]),
        })
        generator = FakeDataGenerator(config, curriculum=STUNDENTAFEL_NRW_G9)
        assert _bands(generator.generate_couplings()) == []


# ─── Sprachen-Schiene: Solver, Verteilung, Validator ──────────────────────────

BAND_TABLE = {
    7: {"Deutsch": 4, "Geschichte": 2, SECOND_LANGUAGE_SUBJECT: BAND_HOURS},
}


def _small_config(
    grade: int, num_classes: int, subject_day_limit: bool = True
) -> SchoolConfig:
    return SchoolConfig(
        school_name="Schienen-Test",
        school_type=SchoolType.GYMNASIUM,
        bundesland="NRW",
        time_grid=default_time_grid(),
        grades=GradeConfig(grades=[
            GradeDefinition(grade=grade, num_classes=num_classes),
        ]),
        rooms=default_rooms(),
        couplings=CouplingConfig(reli_ethik_enabled=False, wpf_enabled=False),
        solver=SolverConfig(
            time_limit_seconds=30, num_workers=4,
            subject_day_limit=subject_day_limit,
        ),
    )


def _teacher(teacher_id: str, subjects: list[str]) -> Teacher:
    return Teacher(
        id=teacher_id, name=f"Test, {teacher_id}", subjects=subjects,
        deputat_max=12, deputat_min=1,
    )


def _band_school_data() -> SchoolData:
    """7a und 7b mit Deutsch, Geschichte und der Sprachen-Schiene."""
    config = _small_config(grade=7, num_classes=2)
    generator = FakeDataGenerator(config, curriculum=BAND_TABLE)
    full = generator.generate()
    return SchoolData(
        subjects=default_subjects(),
        rooms=full.rooms,
        classes=full.classes,
        teachers=[
            _teacher("DE1", ["Deutsch", "Geschichte"]),
            _teacher("DE2", ["Deutsch", "Geschichte"]),
            _teacher("FRA", ["Französisch"]),
            _teacher("LAT", ["Latein"]),
        ],
        couplings=generator.generate_couplings(),
        config=config,
    )


@pytest.fixture(scope="module")
def band_data() -> SchoolData:
    return _band_school_data()


@pytest.fixture(scope="module")
def band_solution(band_data: SchoolData) -> ScheduleSolution:
    return ScheduleSolver(band_data).solve(use_soft=False)


class TestLanguageBandInSolver:

    def test_feasibility_check_accepts_the_band(self, band_data: SchoolData):
        report = band_data.validate_feasibility()
        assert report.is_feasible, report.errors

    def test_solver_finds_a_plan(self, band_solution: ScheduleSolution):
        assert band_solution.solver_status in SOLVED

    def test_band_runs_at_the_same_time_in_all_classes(
        self, band_solution: ScheduleSolution
    ):
        times_by_class: dict[str, set[tuple[int, int]]] = {}
        for entry in band_solution.entries:
            if entry.coupling_id == BAND_ID:
                times_by_class.setdefault(entry.class_id, set()).add(
                    (entry.day, entry.slot_number)
                )
        assert set(times_by_class) == {"7a", "7b"}
        assert times_by_class["7a"] == times_by_class["7b"]
        assert len(times_by_class["7a"]) == BAND_HOURS

    def test_language_teachers_teach_the_groups(
        self, band_solution: ScheduleSolution
    ):
        teacher_by_subject = {
            entry.subject: entry.teacher_id
            for entry in band_solution.entries
            if entry.coupling_id == BAND_ID
        }
        assert teacher_by_subject == {"Französisch": "FRA", "Latein": "LAT"}

    def test_no_regular_lesson_for_the_band_subject(
        self, band_solution: ScheduleSolution
    ):
        subjects = {entry.subject for entry in band_solution.entries}
        assert SECOND_LANGUAGE_SUBJECT not in subjects

    def test_validator_counts_band_hours_for_the_curriculum(
        self, band_data: SchoolData, band_solution: ScheduleSolution
    ):
        report = SolutionValidator().validate(band_solution, band_data)
        assert [v for v in report.violations if v.severity == "error"] == []
        assert [
            v for v in report.violations
            if v.constraint == "assignment_mismatch"
        ] == []

    def test_distribution_stage_staffs_the_band(self, band_data: SchoolData):
        result = distribute_teachers(band_data, time_limit_seconds=10)
        band = next(c for c in result.data.couplings if c.id == BAND_ID)
        assert {g.subject: g.teacher_id for g in band.groups} == {
            "Französisch": "FRA", "Latein": "LAT",
        }
        assert result.hours_by_teacher["FRA"] == BAND_HOURS


# ─── C15 als Einstellung ──────────────────────────────────────────────────────

# Mit C15 sind pro Tag höchstens zwei Stunden eines Fachs möglich (ein
# Doppelblock), in fünf Tagen also zehn. Elf passen nur ohne C15.
BUNCHED_SUBJECT = "Geschichte"
BUNCHED_TABLE = {5: {BUNCHED_SUBJECT: 11}}


def _bunched_school_data(subject_day_limit: bool) -> SchoolData:
    config = _small_config(
        grade=5, num_classes=1, subject_day_limit=subject_day_limit
    )
    full = FakeDataGenerator(config, curriculum=BUNCHED_TABLE).generate()
    return SchoolData(
        subjects=default_subjects(), rooms=full.rooms, classes=full.classes,
        teachers=[_teacher("GE1", [BUNCHED_SUBJECT])], couplings=[],
        config=config,
    )


def _bunched_solution(data: SchoolData) -> ScheduleSolution:
    """Plan ohne Solver: zwei Einzelstunden des Fachs am Montag."""
    entries = [
        ScheduleEntry(day=MONDAY, slot_number=slot, teacher_id="GE1",
                      class_id="5a", subject=BUNCHED_SUBJECT)
        for slot in (1, 3)
    ]
    return ScheduleSolution(
        entries=entries, assignments=[], solver_status="FEASIBLE",
        solve_time_seconds=0.0, num_variables=0, num_constraints=0,
        config_snapshot=data.config,
    )


def _day_limit_violations(data: SchoolData) -> list:
    report = SolutionValidator().validate(_bunched_solution(data), data)
    return [
        v for v in report.violations if v.constraint == "subject_day_limit"
    ]


class TestSubjectDayLimitSetting:

    def test_limit_is_on_by_default(self):
        assert SolverConfig().subject_day_limit is True
        assert default_school_config().solver.subject_day_limit is True

    def test_config_without_the_field_still_loads(self):
        raw = default_school_config().model_dump()
        del raw["solver"]["subject_day_limit"]
        del raw["couplings"]["second_language_subjects"]
        config = SchoolConfig.model_validate(raw)
        assert config.solver.subject_day_limit is True
        assert config.couplings.second_language_subjects == [
            "Französisch", "Latein",
        ]

    def test_validator_reports_violation_when_on(self):
        data = _bunched_school_data(subject_day_limit=True)
        assert len(_day_limit_violations(data)) == 1

    def test_validator_is_silent_when_off(self):
        data = _bunched_school_data(subject_day_limit=False)
        assert _day_limit_violations(data) == []

    def test_solver_enforces_the_limit_when_on(self):
        data = _bunched_school_data(subject_day_limit=True)
        solution = ScheduleSolver(data).solve(use_soft=False)
        assert solution.solver_status not in SOLVED

    def test_solver_ignores_the_limit_when_off(self):
        data = _bunched_school_data(subject_day_limit=False)
        solution = ScheduleSolver(data).solve(use_soft=False)
        assert solution.solver_status in SOLVED
        assert len(solution.entries) == BUNCHED_TABLE[5][BUNCHED_SUBJECT]


# ─── Wochenstundenrahmen ──────────────────────────────────────────────────────

def _class(class_id: str, grade: int, hours: int) -> SchoolClass:
    return SchoolClass(
        id=class_id, grade=grade, label=class_id[-1],
        curriculum={"Deutsch": hours}, max_slot=7,
    )


class TestWeeklyFrame:

    def test_nrw_table_gives_no_warning(self):
        config = default_school_config()
        classes = FakeDataGenerator(
            config, curriculum=STUNDENTAFEL_NRW_G9
        ).generate().classes
        assert check_weekly_frame(classes, config) == []

    def test_too_many_hours_are_reported_once_per_grade(self):
        classes = [_class("9a", 9, 34), _class("9b", 9, 34)]
        warnings = check_weekly_frame(classes, default_school_config())
        assert len(warnings) == 1
        assert "Jahrgang 9 (9a–9b)" in warnings[0]
        assert "34" in warnings[0] and "über" in warnings[0]
        assert "30–33" in warnings[0]

    def test_too_few_hours_are_reported(self):
        warnings = check_weekly_frame(
            [_class("5a", 5, 27)], default_school_config()
        )
        assert len(warnings) == 1
        assert "unter" in warnings[0] and "28–30" in warnings[0]

    @pytest.mark.parametrize("grade,hours", [(5, 28), (6, 30), (7, 30),
                                             (10, 33)])
    def test_frame_limits_are_allowed(self, grade: int, hours: int):
        classes = [_class(f"{grade}a", grade, hours)]
        assert check_weekly_frame(classes, default_school_config()) == []

    def test_other_state_is_not_checked(self):
        config = default_school_config().model_copy(
            update={"bundesland": "Bayern"}
        )
        assert check_weekly_frame([_class("9a", 9, 36)], config) == []

    def test_other_school_type_is_not_checked(self):
        config = default_school_config().model_copy(
            update={"school_type": SchoolType.REALSCHULE}
        )
        assert check_weekly_frame([_class("9a", 9, 36)], config) == []

    def test_grade_without_frame_is_not_checked(self):
        classes = [_class("11a", 11, 36)]
        assert check_weekly_frame(classes, default_school_config()) == []

    def test_feasibility_report_contains_the_warning(self):
        data = _bunched_school_data(subject_day_limit=True)
        report = data.validate_feasibility()
        assert any("NRW-Rahmen" in warning for warning in report.warnings)


# ─── Excel: Vorlage und Import ────────────────────────────────────────────────

def _cell_value(path: Path, sheet_name: str, row_key: str, column_key: str):
    """Zelle über den Wert in Spalte A und den Kopf in Zeile 1."""
    sheet = openpyxl.load_workbook(path)[sheet_name]
    row = next(c.row for c in sheet["A"] if c.value == row_key)
    column = next(c.column for c in sheet[1] if c.value == column_key)
    return sheet.cell(row=row, column=column).value


def _add_teacher(path: Path) -> None:
    """Der Import verlangt mindestens eine Lehrkraft."""
    workbook = openpyxl.load_workbook(path)
    row = ["Test, Tina", "TES", "Deutsch", "", "", 26, "nein"]
    for column, value in enumerate(row, 1):
        workbook[TEACHER_SHEET].cell(
            row=FIRST_TEACHER_ROW, column=column, value=value
        )
    workbook.save(path)


@pytest.fixture
def template_path(tmp_path: Path) -> Path:
    path = tmp_path / "vorlage.xlsx"
    generate_template(default_school_config(), path)
    _add_teacher(path)
    return path


class TestExcelTemplate:

    def test_curriculum_sheet_shows_the_nrw_table(self, template_path: Path):
        assert _cell_value(
            template_path, CURRICULUM_SHEET, SECOND_LANGUAGE_SUBJECT, "Jg. 7"
        ) == BAND_HOURS
        assert _cell_value(
            template_path, CURRICULUM_SHEET, "Wirtschaft-Politik", "Jg. 5"
        ) == 2
        assert _cell_value(
            template_path, CURRICULUM_SHEET, "Latein", "Jg. 7"
        ) is None

    def test_curriculum_sheet_round_trips(self, template_path: Path):
        importer = ExcelImporter(template_path, default_school_config())
        importer._set_known_subjects(importer.import_subjects())
        assert importer.import_curriculum() == STUNDENTAFEL_NRW_G9

    def test_coupling_sheet_lists_the_band(self, template_path: Path):
        sheet = openpyxl.load_workbook(template_path)[COUPLING_SHEET]
        assert [c.value for c in sheet[1]][:len(COUPLING_HEADERS)] == list(
            COUPLING_HEADERS
        )
        row = next(c.row for c in sheet["A"] if c.value == BAND_ID)
        assert sheet.cell(row=row, column=2).value == COUPLING_TYPE_BAND
        assert sheet.cell(
            row=row, column=CURRICULUM_SUBJECT_COLUMN
        ).value == SECOND_LANGUAGE_SUBJECT

    def test_assignment_sheet_marks_the_band_as_coupling(
        self, template_path: Path
    ):
        assert _cell_value(
            template_path, ASSIGNMENT_SHEET, "7a", SECOND_LANGUAGE_SUBJECT
        ) == COUPLING_MARK
        assert _cell_value(
            template_path, ASSIGNMENT_SHEET, "5a", SECOND_LANGUAGE_SUBJECT
        ) == NOT_TAUGHT_MARK
        assert _cell_value(
            template_path, ASSIGNMENT_SHEET, "9a", "WPF"
        ) == COUPLING_MARK


class TestExcelImport:

    def test_import_reads_the_band(self, template_path: Path):
        data, _ = import_from_excel(template_path, default_school_config())
        band = next(c for c in data.couplings if c.id == BAND_ID)
        assert band.coupling_type == COUPLING_TYPE_BAND
        assert band.curriculum_subject == SECOND_LANGUAGE_SUBJECT
        assert band.hours_per_week == BAND_HOURS
        assert len(band.groups) == 6
        assert band.groups[0] == CouplingGroup(
            group_name="Französisch 1", subject="Französisch",
            hours_per_week=BAND_HOURS,
        )
        class_7a = next(c for c in data.classes if c.id == "7a")
        assert class_7a.curriculum == STUNDENTAFEL_NRW_G9[7]

    def test_other_couplings_have_no_curriculum_subject(
        self, template_path: Path
    ):
        data, _ = import_from_excel(template_path, default_school_config())
        others = [c for c in data.couplings if c.id != BAND_ID
                  and c.coupling_type != COUPLING_TYPE_BAND]
        assert others
        assert {c.curriculum_subject for c in others} == {None}

    def test_older_workbook_without_the_new_column_still_loads(
        self, template_path: Path
    ):
        workbook = openpyxl.load_workbook(template_path)
        sheet = workbook[COUPLING_SHEET]
        sheet.delete_cols(CURRICULUM_SUBJECT_COLUMN, 3)
        sheet.cell(row=1, column=2, value=OLD_TYPE_HEADER)
        workbook.save(template_path)

        data, _ = import_from_excel(template_path, default_school_config())
        types = {c.id: c.coupling_type for c in data.couplings}
        assert types["reli_5"] == "reli_ethik"
        assert types["wpf_9"] == "wpf"
        assert {c.curriculum_subject for c in data.couplings} == {None}

    def test_unknown_curriculum_subject_names_the_row(
        self, template_path: Path
    ):
        workbook = openpyxl.load_workbook(template_path)
        sheet = workbook[COUPLING_SHEET]
        row = next(c.row for c in sheet["A"] if c.value == BAND_ID)
        sheet.cell(row=row, column=CURRICULUM_SUBJECT_COLUMN, value="Xyz")
        workbook.save(template_path)

        with pytest.raises(ExcelImportError) as error:
            import_from_excel(template_path, default_school_config())
        assert f"Kopplungen Zeile {row}" in str(error.value)
        assert "Unbekanntes Fach 'Xyz'" in str(error.value)
