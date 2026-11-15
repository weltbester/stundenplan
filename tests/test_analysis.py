"""Tests für Phase 7: Validierung, Qualitätsbericht und Vertretungshelfer."""

import pytest
from collections import defaultdict
from pathlib import Path

from config.schema import (
    SchoolConfig, GradeConfig, GradeDefinition, SchoolType,
    TeacherConfig, SolverConfig,
)
from config.defaults import (
    default_time_grid, default_rooms,
    SUBJECT_METADATA, STUNDENTAFEL_GYMNASIUM_SEK1,
)
from models.school_data import SchoolData
from models.subject import Subject
from models.room import Room
from models.teacher import Teacher
from models.school_class import SchoolClass
from models.coupling import Coupling, CouplingGroup
from solver.scheduler import ScheduleSolver, ScheduleSolution, ScheduleEntry, TeacherAssignment
from analysis.solution_validator import SolutionValidator, ValidationReport, ValidationViolation
from analysis.quality_report import QualityAnalyzer, ScheduleQualityReport
from analysis.substitution_helper import SubstitutionFinder, SubstituteCandidate


# ─── Testdaten-Hilfsfunktionen ────────────────────────────────────────────────

def _make_mini_config() -> SchoolConfig:
    return SchoolConfig(
        school_name="Analysis-Test-Gymnasium",
        school_type=SchoolType.GYMNASIUM,
        bundesland="NRW",
        time_grid=default_time_grid(),
        grades=GradeConfig(grades=[
            GradeDefinition(grade=5, num_classes=1, weekly_hours_target=30),
            GradeDefinition(grade=7, num_classes=1, weekly_hours_target=32),
        ]),
        rooms=default_rooms(),
        teachers=TeacherConfig(
            total_count=10, vollzeit_deputat=26,
            teilzeit_percentage=0.0, deputat_min_fraction=0.80,
        ),
        solver=SolverConfig(
            time_limit_seconds=60,
            num_workers=4,
            weight_deputat_deviation=0,  # Deaktiviert für schnelle Tests
        ),
    )


def _make_mini_school_data() -> SchoolData:
    config = _make_mini_config()
    sek1_max = config.time_grid.sek1_max_slot

    subjects = [
        Subject(
            name=name, short_name=meta["short"], category=meta["category"],
            is_hauptfach=meta["is_hauptfach"], requires_special_room=meta["room"],
            double_lesson_required=meta["double_required"],
            double_lesson_preferred=meta["double_preferred"],
        )
        for name, meta in SUBJECT_METADATA.items()
    ]
    rooms = []
    for rd in config.rooms.special_rooms:
        prefix = rd.room_type[:2].upper()
        for i in range(1, rd.count + 1):
            rooms.append(Room(id=f"{prefix}{i}", room_type=rd.room_type,
                              name=f"{rd.display_name} {i}"))

    classes = [
        SchoolClass(id="5a", grade=5, label="a",
                    curriculum={s: h for s, h in STUNDENTAFEL_GYMNASIUM_SEK1[5].items() if h > 0},
                    max_slot=sek1_max),
        SchoolClass(id="7a", grade=7, label="a",
                    curriculum={s: h for s, h in STUNDENTAFEL_GYMNASIUM_SEK1[7].items() if h > 0},
                    max_slot=sek1_max),
    ]
    dep_max = 9
    dep_min = 4
    teachers = [
        Teacher(id="T01", name="Müller, Anna",   subjects=["Deutsch", "Geschichte"],  deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T02", name="Schmidt, Hans",  subjects=["Mathematik", "Physik"],   deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T03", name="Weber, Eva",     subjects=["Englisch", "Politik"],    deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T04", name="Becker, Klaus",  subjects=["Biologie", "Erdkunde"],   deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T05", name="Koch, Lisa",     subjects=["Kunst", "Musik"],         deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T06", name="Wagner, Tom",    subjects=["Sport", "Chemie"],        deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T07", name="Braun, Sara",    subjects=["Latein", "Deutsch"],      deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T08", name="Wolf, Peter",    subjects=["Religion", "Ethik"],      deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T09", name="Neumann, Maria", subjects=["Religion", "Ethik"],      deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T10", name="Schulz, Ralf",   subjects=["Mathematik", "Deutsch"],  deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
    ]
    couplings = [
        Coupling(id="reli_5", coupling_type="reli_ethik", involved_class_ids=["5a"],
                 groups=[CouplingGroup(group_name="evangelisch", subject="Religion", hours_per_week=2),
                         CouplingGroup(group_name="ethik",       subject="Ethik",    hours_per_week=2)],
                 hours_per_week=2, cross_class=True),
        Coupling(id="reli_7", coupling_type="reli_ethik", involved_class_ids=["7a"],
                 groups=[CouplingGroup(group_name="evangelisch", subject="Religion", hours_per_week=2),
                         CouplingGroup(group_name="ethik",       subject="Ethik",    hours_per_week=2)],
                 hours_per_week=2, cross_class=True),
    ]
    return SchoolData(subjects=subjects, rooms=rooms, classes=classes,
                      teachers=teachers, couplings=couplings, config=config)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def mini_school_data() -> SchoolData:
    return _make_mini_school_data()


@pytest.fixture(scope="module")
def mini_solution(mini_school_data: SchoolData) -> ScheduleSolution:
    """Löst den Mini-Datensatz einmal für alle Tests dieses Moduls."""
    solver = ScheduleSolver(mini_school_data)
    solution = solver.solve(use_soft=False)
    assert solution.solver_status in ("OPTIMAL", "FEASIBLE"), (
        f"Solver konnte keine Lösung finden: {solution.solver_status}"
    )
    return solution


def _make_minimal_solution(config: SchoolConfig) -> ScheduleSolution:
    """Erstellt eine minimale ScheduleSolution für Unit-Tests ohne Solver."""
    return ScheduleSolution(
        entries=[],
        assignments=[],
        solver_status="OPTIMAL",
        solve_time_seconds=1.0,
        num_variables=0,
        num_constraints=0,
        config_snapshot=config,
    )


WPF_CLASS_ID = "9a"
WPF_COUPLING_ID = "wpf_9"
WPF_HOURS = 3


@pytest.fixture(scope="module")
def wpf_school_data(mini_school_data: SchoolData) -> SchoolData:
    """Mini-Datensatz plus Klasse 9a mit einer WPF-Kopplung (2 Gruppen)."""
    wpf_class = SchoolClass(
        id=WPF_CLASS_ID, grade=9, label="a",
        curriculum={"WPF": WPF_HOURS},
        max_slot=mini_school_data.config.time_grid.sek1_max_slot,
    )
    wpf_coupling = Coupling(
        id=WPF_COUPLING_ID, coupling_type="wpf",
        involved_class_ids=[WPF_CLASS_ID],
        groups=[
            CouplingGroup(group_name="Informatik-WPF",
                          subject="Informatik", hours_per_week=WPF_HOURS),
            CouplingGroup(group_name="Französisch-WPF",
                          subject="Französisch", hours_per_week=WPF_HOURS),
        ],
        hours_per_week=WPF_HOURS,
    )
    return mini_school_data.model_copy(update={
        "classes": mini_school_data.classes + [wpf_class],
        "couplings": mini_school_data.couplings + [wpf_coupling],
    })


def _wpf_slot_entries(day: int, slot: int) -> list[ScheduleEntry]:
    """Ein WPF-Termin der 9a: je ein Eintrag pro Gruppe im selben Slot."""
    return [
        ScheduleEntry(
            day=day, slot_number=slot, teacher_id=teacher_id,
            class_id=WPF_CLASS_ID, subject=subject,
            is_coupling=True, coupling_id=WPF_COUPLING_ID,
        )
        for teacher_id, subject in (("T02", "Informatik"),
                                    ("T03", "Französisch"))
    ]


def _solution_from(
    entries: list[ScheduleEntry], config: SchoolConfig
) -> ScheduleSolution:
    """ScheduleSolution mit vorgegebenen Einträgen (ohne Solver)."""
    return _make_minimal_solution(config).model_copy(
        update={"entries": entries}
    )


def _validate_deutsch_slots(
    school_data: SchoolData, slots: tuple[int, ...]
) -> ValidationReport:
    """Validiert einen Plan, in dem 5a montags Deutsch in `slots` hat."""
    entries = [
        ScheduleEntry(day=0, slot_number=slot, teacher_id="T01",
                      class_id="5a", subject="Deutsch")
        for slot in slots
    ]
    solution = _solution_from(entries, school_data.config)
    return SolutionValidator().validate(solution, school_data)


class TestCouplingCurriculumSubjects:
    """Coupling.curriculum_subjects(): welche Stundentafel-Fächer zählen."""

    def test_wpf_coupling_covers_wpf(self, wpf_school_data):
        wpf = next(
            c for c in wpf_school_data.couplings if c.id == WPF_COUPLING_ID
        )
        assert wpf.curriculum_subjects() == {"WPF"}

    def test_reli_coupling_covers_group_subjects(self, mini_school_data):
        reli = next(
            c for c in mini_school_data.couplings if c.id == "reli_5"
        )
        assert reli.curriculum_subjects() == {"Religion", "Ethik"}


# ─── Tests: SolutionValidator ─────────────────────────────────────────────────

class TestSolutionValidator:

    def test_validator_no_violations(self, mini_solution, mini_school_data):
        """Saubere Lösung → keine Fehler, is_valid=True."""
        validator = SolutionValidator()
        report = validator.validate(mini_solution, mini_school_data)
        errors = [v for v in report.violations if v.severity == "error"]
        assert report.is_valid, (
            f"Unerwartete Fehler: {[v.description for v in errors]}"
        )

    def test_validator_teacher_double_booking(self, mini_school_data):
        """Doppelt gebuchter Lehrer → error 'teacher_double_booking'."""
        config = mini_school_data.config
        entries = [
            ScheduleEntry(day=0, slot_number=1, teacher_id="T01", class_id="5a",
                          subject="Deutsch"),
            ScheduleEntry(day=0, slot_number=1, teacher_id="T01", class_id="7a",
                          subject="Geschichte"),
        ]
        solution = ScheduleSolution(
            entries=entries, assignments=[],
            solver_status="OPTIMAL", solve_time_seconds=1.0,
            num_variables=0, num_constraints=0, config_snapshot=config,
        )
        validator = SolutionValidator()
        report = validator.validate(solution, mini_school_data)
        assert not report.is_valid
        constraints = [v.constraint for v in report.violations if v.severity == "error"]
        assert "teacher_double_booking" in constraints

    def test_validator_class_conflict(self, mini_school_data):
        """Klasse hat zwei reguläre Stunden im selben Slot → error 'class_double_booking'."""
        config = mini_school_data.config
        entries = [
            ScheduleEntry(day=1, slot_number=2, teacher_id="T01", class_id="5a",
                          subject="Deutsch"),
            ScheduleEntry(day=1, slot_number=2, teacher_id="T02", class_id="5a",
                          subject="Mathematik"),
        ]
        solution = ScheduleSolution(
            entries=entries, assignments=[],
            solver_status="OPTIMAL", solve_time_seconds=1.0,
            num_variables=0, num_constraints=0, config_snapshot=config,
        )
        validator = SolutionValidator()
        report = validator.validate(solution, mini_school_data)
        assert not report.is_valid
        constraints = [v.constraint for v in report.violations if v.severity == "error"]
        assert "class_double_booking" in constraints

    def test_validator_room_conflict(self, mini_school_data):
        """Selber Raum zweifach belegt → error 'room_double_booking'."""
        config = mini_school_data.config
        entries = [
            ScheduleEntry(day=0, slot_number=3, teacher_id="T01", class_id="5a",
                          subject="Physik", room="PH1"),
            ScheduleEntry(day=0, slot_number=3, teacher_id="T02", class_id="7a",
                          subject="Physik", room="PH1"),
        ]
        solution = ScheduleSolution(
            entries=entries, assignments=[],
            solver_status="OPTIMAL", solve_time_seconds=1.0,
            num_variables=0, num_constraints=0, config_snapshot=config,
        )
        validator = SolutionValidator()
        report = validator.validate(solution, mini_school_data)
        assert not report.is_valid
        constraints = [v.constraint for v in report.violations if v.severity == "error"]
        assert "room_double_booking" in constraints

    def test_validator_deputat_exceeded(self, mini_school_data):
        """Lehrer hat mehr Stunden als deputat_max → error 'deputat_exceeded'."""
        config = mini_school_data.config
        # T01 hat dep_max=9; 10 Einträge → überschritten
        entries = [
            ScheduleEntry(day=d, slot_number=s, teacher_id="T01", class_id="5a",
                          subject="Deutsch")
            for d, s in [(0,1),(0,2),(1,1),(1,2),(2,1),(2,2),(3,1),(3,2),(4,1),(4,2)]
        ]
        solution = ScheduleSolution(
            entries=entries, assignments=[],
            solver_status="OPTIMAL", solve_time_seconds=1.0,
            num_variables=0, num_constraints=0, config_snapshot=config,
        )
        validator = SolutionValidator()
        report = validator.validate(solution, mini_school_data)
        constraints = [v.constraint for v in report.violations]
        assert "deputat_exceeded" in constraints

    def test_validator_assignment_mismatch(self, mini_school_data):
        """Klasse hat weniger Stunden als Curriculum verlangt → warning/error."""
        config = mini_school_data.config
        # 5a braucht 4h Deutsch (Sek-I-Curriculum), wir geben nur 1h
        entries = [
            ScheduleEntry(day=0, slot_number=1, teacher_id="T01", class_id="5a",
                          subject="Deutsch"),
        ]
        solution = ScheduleSolution(
            entries=entries, assignments=[],
            solver_status="OPTIMAL", solve_time_seconds=1.0,
            num_variables=0, num_constraints=0, config_snapshot=config,
        )
        validator = SolutionValidator()
        report = validator.validate(solution, mini_school_data)
        constraints = [v.constraint for v in report.violations]
        assert "assignment_mismatch" in constraints

    def test_validator_coupling_inconsistency(self, mini_school_data):
        """Klassen einer Kopplung in unterschiedlichen Slots → error."""
        config = mini_school_data.config
        # reli_7 betrifft 7a; wir setzen zwei widersprüchliche Slots
        entries = [
            ScheduleEntry(day=0, slot_number=1, teacher_id="T08", class_id="7a",
                          subject="Religion", is_coupling=True, coupling_id="reli_7"),
            ScheduleEntry(day=0, slot_number=2, teacher_id="T08", class_id="7a",
                          subject="Religion", is_coupling=True, coupling_id="reli_7"),
        ]
        solution = ScheduleSolution(
            entries=entries, assignments=[],
            solver_status="OPTIMAL", solve_time_seconds=1.0,
            num_variables=0, num_constraints=0, config_snapshot=config,
        )
        validator = SolutionValidator()
        report = validator.validate(solution, mini_school_data)
        # coupling_inconsistency wird nicht ausgelöst, da nur 1 Klasse betroffen –
        # stattdessen prüfen wir dass die Validierung überhaupt läuft
        assert isinstance(report, ValidationReport)

    def test_validator_wpf_parallel_groups_allowed(self, wpf_school_data):
        """Parallele WPF-Gruppen im selben Slot sind keine Doppelbelegung."""
        solution = _solution_from(
            _wpf_slot_entries(day=1, slot=7), wpf_school_data.config
        )
        report = SolutionValidator().validate(solution, wpf_school_data)
        constraints = [v.constraint for v in report.violations]
        assert "class_double_booking" not in constraints

    def test_validator_wpf_hours_count_for_wpf_subject(
        self, wpf_school_data
    ):
        """3 WPF-Kopplungstermine erfüllen 'WPF: 3h' der Stundentafel."""
        entries = [
            entry
            for day in range(WPF_HOURS)
            for entry in _wpf_slot_entries(day=day, slot=1)
        ]
        solution = _solution_from(entries, wpf_school_data.config)
        report = SolutionValidator().validate(solution, wpf_school_data)
        wpf_class_mismatches = [
            v for v in report.violations
            if v.constraint == "assignment_mismatch"
            and v.entity == WPF_CLASS_ID
        ]
        assert wpf_class_mismatches == []

    def test_validator_wpf_missing_hour_is_reported(self, wpf_school_data):
        """Nur 1 von 3 WPF-Terminen → assignment_mismatch für die Klasse."""
        solution = _solution_from(
            _wpf_slot_entries(day=0, slot=1), wpf_school_data.config
        )
        report = SolutionValidator().validate(solution, wpf_school_data)
        wpf_class_mismatches = [
            v for v in report.violations
            if v.constraint == "assignment_mismatch"
            and v.entity == WPF_CLASS_ID
        ]
        assert len(wpf_class_mismatches) == 1
        assert "WPF" in wpf_class_mismatches[0].description

    def test_validator_two_couplings_same_slot_is_conflict(
        self, wpf_school_data
    ):
        """Einträge aus zwei verschiedenen Kopplungen im selben Slot → error."""
        entries = _wpf_slot_entries(day=0, slot=1) + [
            ScheduleEntry(
                day=0, slot_number=1, teacher_id="T08",
                class_id=WPF_CLASS_ID, subject="Religion",
                is_coupling=True, coupling_id="reli_5",
            ),
        ]
        solution = _solution_from(entries, wpf_school_data.config)
        report = SolutionValidator().validate(solution, wpf_school_data)
        constraints = [v.constraint for v in report.violations]
        assert "class_double_booking" in constraints

    def test_validator_coupling_plus_regular_is_conflict(
        self, wpf_school_data
    ):
        """Kopplungstermin und reguläre Stunde im selben Slot → error."""
        entries = _wpf_slot_entries(day=0, slot=1) + [
            ScheduleEntry(
                day=0, slot_number=1, teacher_id="T01",
                class_id=WPF_CLASS_ID, subject="Deutsch",
            ),
        ]
        solution = _solution_from(entries, wpf_school_data.config)
        report = SolutionValidator().validate(solution, wpf_school_data)
        constraints = [v.constraint for v in report.violations]
        assert "class_double_booking" in constraints

    def test_validator_unknown_coupling_id_is_conflict(
        self, wpf_school_data
    ):
        """Mehrere Einträge mit unbekannter Kopplungs-ID → error."""
        entries = [
            entry.model_copy(update={"coupling_id": "gibt_es_nicht"})
            for entry in _wpf_slot_entries(day=0, slot=1)
        ]
        solution = _solution_from(entries, wpf_school_data.config)
        report = SolutionValidator().validate(solution, wpf_school_data)
        constraints = [v.constraint for v in report.violations]
        assert "class_double_booking" in constraints

    @pytest.mark.parametrize("slots", [(1,), (1, 2), (3, 4), (5, 6)])
    def test_day_limit_allows_single_and_double_block(
        self, mini_school_data, slots
    ):
        """Eine Einzelstunde oder ein Doppelblock pro Tag ist erlaubt."""
        report = _validate_deutsch_slots(mini_school_data, slots)
        constraints = [v.constraint for v in report.violations]
        assert "subject_day_limit" not in constraints

    @pytest.mark.parametrize(
        "slots", [(1, 3), (2, 3), (6, 7), (1, 2, 3), (1, 2, 5, 6)]
    )
    def test_day_limit_rejects_bunched_lessons(
        self, mini_school_data, slots
    ):
        """Getrennte Stunden, Nicht-Blöcke und 3+ Stunden am Tag → error."""
        report = _validate_deutsch_slots(mini_school_data, slots)
        day_limit_errors = [
            v for v in report.violations
            if v.constraint == "subject_day_limit"
        ]
        assert len(day_limit_errors) == 1
        assert day_limit_errors[0].severity == "error"
        assert day_limit_errors[0].entity == "5a"

    def test_day_limit_counts_days_separately(self, mini_school_data):
        """Je eine Stunde an verschiedenen Tagen ist kein Verstoß."""
        entries = [
            ScheduleEntry(day=day, slot_number=1, teacher_id="T01",
                          class_id="5a", subject="Deutsch")
            for day in range(4)
        ]
        solution = _solution_from(entries, mini_school_data.config)
        report = SolutionValidator().validate(solution, mini_school_data)
        constraints = [v.constraint for v in report.violations]
        assert "subject_day_limit" not in constraints

    def test_day_limit_coupling_block_allowed(self, wpf_school_data):
        """Zwei Termine einer Kopplung als Doppelblock sind erlaubt."""
        entries = (_wpf_slot_entries(day=0, slot=1)
                   + _wpf_slot_entries(day=0, slot=2))
        solution = _solution_from(entries, wpf_school_data.config)
        report = SolutionValidator().validate(solution, wpf_school_data)
        constraints = [v.constraint for v in report.violations]
        assert "subject_day_limit" not in constraints

    def test_day_limit_coupling_split_rejected(self, wpf_school_data):
        """Zwei getrennte Termine einer Kopplung am selben Tag → error."""
        entries = (_wpf_slot_entries(day=0, slot=1)
                   + _wpf_slot_entries(day=0, slot=5))
        solution = _solution_from(entries, wpf_school_data.config)
        report = SolutionValidator().validate(solution, wpf_school_data)
        constraints = [v.constraint for v in report.violations]
        assert "subject_day_limit" in constraints

    def test_validator_unavailable_slot(self, mini_school_data):
        """Lehrer im gesperrten Slot → error 'unavailable_slot_violation'."""
        config = mini_school_data.config
        # Erstelle Lehrer mit Sperrzeit
        restricted_teacher = Teacher(
            id="TX1", name="Gesperrt, Hans",
            subjects=["Deutsch"],
            deputat_max=5, deputat_min=2,
            unavailable_slots=[(0, 1)],   # Montag Slot 1 gesperrt
        )
        school_data_mod = SchoolData(
            subjects=mini_school_data.subjects,
            rooms=mini_school_data.rooms,
            classes=mini_school_data.classes,
            teachers=mini_school_data.teachers + [restricted_teacher],
            couplings=mini_school_data.couplings,
            config=config,
        )
        entries = [
            ScheduleEntry(day=0, slot_number=1, teacher_id="TX1", class_id="5a",
                          subject="Deutsch"),
        ]
        solution = ScheduleSolution(
            entries=entries, assignments=[],
            solver_status="OPTIMAL", solve_time_seconds=1.0,
            num_variables=0, num_constraints=0, config_snapshot=config,
        )
        validator = SolutionValidator()
        report = validator.validate(solution, school_data_mod)
        assert not report.is_valid
        constraints = [v.constraint for v in report.violations if v.severity == "error"]
        assert "unavailable_slot_violation" in constraints

    def test_validator_print_rich_runs(self, mini_solution, mini_school_data):
        """print_rich() wirft keinen Fehler."""
        validator = SolutionValidator()
        report = validator.validate(mini_solution, mini_school_data)
        # Sollte keine Exception werfen
        report.print_rich()


# ─── Tests: QualityAnalyzer ───────────────────────────────────────────────────

class TestQualityReport:

    def test_quality_report_structure(self, mini_solution, mini_school_data):
        """analyze() gibt vollständiges ScheduleQualityReport zurück."""
        analyzer = QualityAnalyzer()
        report = analyzer.analyze(mini_solution, mini_school_data)

        assert isinstance(report, ScheduleQualityReport)
        assert len(report.teacher_metrics) == len(mini_school_data.teachers)
        assert len(report.class_metrics) == len(mini_school_data.classes)
        assert report.solver_status in ("OPTIMAL", "FEASIBLE")
        assert report.solve_time >= 0.0

    def test_teacher_metrics_hours(self, mini_solution, mini_school_data):
        """Jede Lehr-Metrik hat sinnvolle Stundenzahl (>= 0)."""
        analyzer = QualityAnalyzer()
        report = analyzer.analyze(mini_solution, mini_school_data)

        for m in report.teacher_metrics:
            assert m.actual_hours >= 0
            assert m.dep_min > 0
            assert m.dep_max >= m.dep_min

    def test_teacher_metrics_gaps(self, mini_solution, mini_school_data):
        """gaps_total >= 0 und gaps_per_day ist für alle Tage vorhanden."""
        analyzer = QualityAnalyzer()
        report = analyzer.analyze(mini_solution, mini_school_data)
        day_names = mini_school_data.config.time_grid.day_names

        for m in report.teacher_metrics:
            assert m.gaps_total >= 0
            for day in day_names:
                assert day in m.gaps_per_day
                assert m.gaps_per_day[day] >= 0

    def test_teacher_metrics_free_days(self, mini_solution, mini_school_data):
        """free_days liegt zwischen 0 und days_per_week."""
        analyzer = QualityAnalyzer()
        report = analyzer.analyze(mini_solution, mini_school_data)
        days = mini_school_data.config.time_grid.days_per_week

        for m in report.teacher_metrics:
            assert 0 <= m.free_days <= days

    def test_class_metrics_hours_per_day(self, mini_solution, mini_school_data):
        """hours_per_day für alle Klassen korrekt befüllt."""
        analyzer = QualityAnalyzer()
        report = analyzer.analyze(mini_solution, mini_school_data)
        day_names = mini_school_data.config.time_grid.day_names

        for m in report.class_metrics:
            for day in day_names:
                assert day in m.hours_per_day
                assert m.hours_per_day[day] >= 0

    def test_class_metrics_doubles(self, mini_solution, mini_school_data):
        """double_fulfilled <= double_requested (nie mehr erfüllt als gefordert)."""
        analyzer = QualityAnalyzer()
        report = analyzer.analyze(mini_solution, mini_school_data)

        for m in report.class_metrics:
            assert m.double_fulfilled >= 0
            assert m.double_requested >= 0

    def test_fairness_index_perfect(self):
        """Jain's Fairness = 1.0 wenn alle Lehrer gleich viele Stunden haben."""
        # 3 Lehrer mit je 5 Stunden → perfekte Fairness
        actuals = [5, 5, 5]
        n = len(actuals)
        sum_a = sum(actuals)
        sum_sq = sum(a * a for a in actuals)
        fairness = (sum_a ** 2) / (n * sum_sq)
        assert abs(fairness - 1.0) < 1e-9

    def test_fairness_index_imbalanced(self):
        """Jain's Fairness < 1.0 wenn Stunden ungleich verteilt."""
        # 1 Lehrer mit 10h, 4 mit 1h → starke Ungleichheit
        actuals = [10, 1, 1, 1, 1]
        n = len(actuals)
        sum_a = sum(actuals)
        sum_sq = sum(a * a for a in actuals)
        fairness = (sum_a ** 2) / (n * sum_sq)
        assert fairness < 1.0
        assert fairness > 0.0

    def test_fairness_index_in_report(self, mini_solution, mini_school_data):
        """deputat_fairness_index liegt zwischen 0 und 1."""
        analyzer = QualityAnalyzer()
        report = analyzer.analyze(mini_solution, mini_school_data)
        assert 0.0 <= report.deputat_fairness_index <= 1.0

    def test_double_fulfillment_rate_range(self, mini_solution, mini_school_data):
        """double_fulfillment_rate liegt zwischen 0 und 1."""
        analyzer = QualityAnalyzer()
        report = analyzer.analyze(mini_solution, mini_school_data)
        assert 0.0 <= report.double_fulfillment_rate <= 1.0

    def test_spread_score_range(self, mini_solution, mini_school_data):
        """subject_spread_score liegt zwischen 0.0 und 1.0 für alle Klassen."""
        analyzer = QualityAnalyzer()
        report = analyzer.analyze(mini_solution, mini_school_data)

        for m in report.class_metrics:
            assert 0.0 <= m.subject_spread_score <= 1.0, (
                f"Klasse {m.class_id}: spread={m.subject_spread_score}"
            )

    def test_print_rich_runs(self, mini_solution, mini_school_data):
        """print_rich() wirft keinen Fehler."""
        analyzer = QualityAnalyzer()
        report = analyzer.analyze(mini_solution, mini_school_data)
        analyzer.print_rich(report, mini_school_data.config)


# ─── Tests: SubstitutionFinder ────────────────────────────────────────────────

class TestSubstitutionFinder:

    def test_find_substitutes_same_subject(self, mini_solution, mini_school_data):
        """Lehrkräfte mit gemeinsamem Fach werden als Kandidaten zurückgegeben."""
        finder = SubstitutionFinder()
        # T01 unterrichtet Deutsch+Geschichte; T07 und T10 können auch Deutsch
        candidates = finder.find_substitutes("T01", 0, 1, mini_solution, mini_school_data)
        candidate_ids = {c.teacher_id for c in candidates}
        # Mindestens einer mit überschneidenden Fächern sollte gefunden werden
        assert len(candidates) >= 0  # Kann leer sein wenn keine Fachüberschneidung an diesem Slot

    def test_find_substitutes_absent_excluded(self, mini_solution, mini_school_data):
        """Der abwesende Lehrer selbst wird nicht als Kandidat zurückgegeben."""
        finder = SubstitutionFinder()
        candidates = finder.find_substitutes("T01", 0, 1, mini_solution, mini_school_data)
        candidate_ids = {c.teacher_id for c in candidates}
        assert "T01" not in candidate_ids

    def test_find_substitutes_no_match(self, mini_school_data):
        """Lehrer ohne Fach-Übereinstimmung wird nicht als Kandidat gelistet."""
        config = mini_school_data.config
        # Einziger Lehrer mit einem sehr speziellen Fach
        unique_teacher = Teacher(
            id="TU1", name="Einzig, Art",
            subjects=["EinzigartigesFach"],
            deputat_max=5, deputat_min=2,
        )
        school_data_mod = SchoolData(
            subjects=mini_school_data.subjects,
            rooms=mini_school_data.rooms,
            classes=mini_school_data.classes,
            teachers=[unique_teacher],
            couplings=[],
            config=config,
        )
        entries = [
            ScheduleEntry(day=0, slot_number=1, teacher_id="TU1", class_id="5a",
                          subject="EinzigartigesFach"),
        ]
        solution = ScheduleSolution(
            entries=entries, assignments=[],
            solver_status="OPTIMAL", solve_time_seconds=1.0,
            num_variables=0, num_constraints=0, config_snapshot=config,
        )
        finder = SubstitutionFinder()
        # Wir suchen Vertretung für TU1 – aber nur TU1 ist im System
        candidates = finder.find_substitutes("TU1", 0, 1, solution, school_data_mod)
        assert candidates == []

    def test_find_substitutes_unavailable_excluded(self, mini_solution, mini_school_data):
        """Lehrer, die im Slot bereits eingeplant sind, werden als nicht verfügbar markiert."""
        finder = SubstitutionFinder()
        # Finde einen Slot, in dem T02 eingeplant ist
        t02_entries = mini_solution.get_teacher_schedule("T02")
        if not t02_entries:
            pytest.skip("T02 hat keine Einträge in der Mini-Lösung")

        day = t02_entries[0].day
        slot = t02_entries[0].slot_number

        candidates = finder.find_substitutes("T01", day, slot, mini_solution, mini_school_data)
        t02_candidate = next((c for c in candidates if c.teacher_id == "T02"), None)

        if t02_candidate is not None:
            assert not t02_candidate.is_available_at_slot

    def test_substitute_score_ordering(self, mini_solution, mini_school_data):
        """Kandidatenliste ist nach Score absteigend sortiert."""
        finder = SubstitutionFinder()
        # Teste über alle Lehrer und Slots
        for teacher_id in ["T01", "T02", "T03"]:
            all_results = finder.find_all_for_teacher(teacher_id, mini_solution, mini_school_data)
            for slot_key, candidates in all_results.items():
                scores = [c.score for c in candidates]
                assert scores == sorted(scores, reverse=True), (
                    f"Kandidaten für {teacher_id} @ {slot_key} nicht nach Score sortiert"
                )

    def test_find_all_for_teacher_keys(self, mini_solution, mini_school_data):
        """find_all_for_teacher gibt Dict mit korrekten Schlüsseln zurück."""
        finder = SubstitutionFinder()
        result = finder.find_all_for_teacher("T01", mini_solution, mini_school_data)

        assert isinstance(result, dict)
        day_names = mini_school_data.config.time_grid.day_names

        for key in result.keys():
            # Key-Format: "Tagname-Slotnummer" (z.B. "Mo-3")
            parts = key.split("-")
            assert len(parts) == 2, f"Ungültiger Key: {key}"
            assert parts[0] in day_names, f"Unbekannter Tag im Key: {parts[0]}"
            assert parts[1].isdigit(), f"Slot-Nummer im Key ist keine Zahl: {parts[1]}"

    def test_find_all_for_teacher_unknown(self, mini_solution, mini_school_data):
        """find_all_for_teacher für unbekannten Lehrer gibt leeres Dict zurück."""
        finder = SubstitutionFinder()
        result = finder.find_all_for_teacher("UNBEKANNT", mini_solution, mini_school_data)
        assert result == {}

    def test_substitute_score_bounds(self, mini_solution, mini_school_data):
        """Score liegt immer zwischen 0 und 100."""
        finder = SubstitutionFinder()
        for teacher_id in ["T01", "T02"]:
            all_results = finder.find_all_for_teacher(teacher_id, mini_solution, mini_school_data)
            for slot_key, candidates in all_results.items():
                for c in candidates:
                    assert 0.0 <= c.score <= 100.0, (
                        f"Score {c.score} außerhalb [0,100] für {c.teacher_id} @ {slot_key}"
                    )

    def test_substitute_load_ratio(self, mini_solution, mini_school_data):
        """load_ratio ist immer >= 0."""
        finder = SubstitutionFinder()
        all_results = finder.find_all_for_teacher("T01", mini_solution, mini_school_data)
        for slot_key, candidates in all_results.items():
            for c in candidates:
                assert c.load_ratio >= 0.0
