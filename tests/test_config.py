"""Tests für das Konfigurationssystem und Phase-1-Datenmodelle."""

import tempfile
from pathlib import Path

import pytest

from config.schema import (
    DoubleBlock,
    GradeConfig,
    GradeDefinition,
    LessonSlot,
    PauseSlot,
    SchoolConfig,
    SchoolType,
    TimeGridConfig,
)
from config.defaults import (
    default_grades,
    default_rooms,
    default_school_config,
    default_time_grid,
    STUNDENTAFEL_GYMNASIUM_SEK1,
    SUBJECT_METADATA,
)
from config.manager import ConfigManager


# ─── DEFAULT-KONFIGURATION ────────────────────────────────────────────────────

class TestDefaultConfig:
    def test_default_time_grid_valid(self):
        """Default-Zeitraster lässt sich ohne Fehler erstellen."""
        tg = default_time_grid()
        assert tg.days_per_week == 5
        assert len(tg.lesson_slots) == 10
        assert len(tg.pauses) == 3
        assert len(tg.double_blocks) == 3

    def test_default_grades_valid(self):
        """Default-Jahrgangskonfiguration ist korrekt."""
        gc = default_grades()
        assert len(gc.grades) == 6
        assert gc.total_classes == 36
        assert gc.grade_numbers == [5, 6, 7, 8, 9, 10]

    def test_default_rooms_valid(self):
        """Default-Fachräume sind korrekt."""
        rc = default_rooms()
        assert len(rc.special_rooms) == 7
        physik = next(r for r in rc.special_rooms if r.room_type == "physik")
        assert physik.count == 3
        bio = next(r for r in rc.special_rooms if r.room_type == "biologie")
        assert bio.count == 3  # 36 Klassen brauchen mind. 3 Bio-Räume

    def test_default_school_config_valid(self):
        """Vollständige Default-Config ist valide."""
        config = default_school_config()
        assert config.school_name == "Muster-Gymnasium"
        assert config.school_type == SchoolType.GYMNASIUM
        assert config.bundesland == "NRW"
        assert config.grades.total_classes == 36
        assert config.teachers.total_count == 105

    def test_room_get_capacity_special(self):
        """get_capacity gibt korrekte Kapazität für Fachräume zurück."""
        rc = default_rooms()
        assert rc.get_capacity("physik") == 3
        assert rc.get_capacity("chemie") == 2

    def test_room_get_capacity_unknown(self):
        """get_capacity gibt 999 für unbekannte Raumtypen zurück."""
        rc = default_rooms()
        assert rc.get_capacity("unbekannt") == 999

    def test_stundentafel_covers_all_grades(self):
        """Stundentafel enthält alle Jahrgänge 5-10."""
        gc = default_grades()
        for g in gc.grade_numbers:
            assert g in STUNDENTAFEL_GYMNASIUM_SEK1, f"Jahrgang {g} fehlt in Stundentafel"

    def test_subject_metadata_not_empty(self):
        """SUBJECT_METADATA enthält alle relevanten Fächer."""
        required = ["Deutsch", "Mathematik", "Englisch", "Physik",
                    "Chemie", "Biologie", "Sport"]
        for subj in required:
            assert subj in SUBJECT_METADATA, f"Fach '{subj}' fehlt in SUBJECT_METADATA"


# ─── PYDANTIC-VALIDIERUNG ─────────────────────────────────────────────────────

class TestPydanticValidation:
    def test_valid_double_block(self):
        """Gültige Doppelstunden-Blöcke werden akzeptiert."""
        tg = TimeGridConfig(
            lesson_slots=[
                LessonSlot(slot_number=1, start_time="08:00", end_time="08:45"),
                LessonSlot(slot_number=2, start_time="08:45", end_time="09:30"),
            ],
            pauses=[],
            double_blocks=[DoubleBlock(slot_first=1, slot_second=2)],
        )
        assert len(tg.double_blocks) == 1

    def test_double_block_over_pause_raises(self):
        """Doppelstunden-Block über Pause hinweg → Validierungsfehler."""
        with pytest.raises(Exception):
            TimeGridConfig(
                lesson_slots=[
                    LessonSlot(slot_number=1, start_time="08:00", end_time="08:45"),
                    LessonSlot(slot_number=2, start_time="09:00", end_time="09:45"),
                ],
                pauses=[PauseSlot(after_slot=1, duration_minutes=15)],
                double_blocks=[DoubleBlock(slot_first=1, slot_second=2)],
            )

    def test_double_block_nonsequential_raises(self):
        """Nicht aufeinanderfolgende Blöcke → Validierungsfehler."""
        with pytest.raises(Exception):
            TimeGridConfig(
                lesson_slots=[
                    LessonSlot(slot_number=1, start_time="08:00", end_time="08:45"),
                    LessonSlot(slot_number=2, start_time="08:45", end_time="09:30"),
                    LessonSlot(slot_number=3, start_time="09:30", end_time="10:15"),
                ],
                pauses=[],
                double_blocks=[DoubleBlock(slot_first=1, slot_second=3)],
            )

    def test_double_block_missing_slot_raises(self):
        """Block referenziert nicht-existenten Slot → Validierungsfehler."""
        with pytest.raises(Exception):
            TimeGridConfig(
                lesson_slots=[
                    LessonSlot(slot_number=1, start_time="08:00", end_time="08:45"),
                ],
                pauses=[],
                double_blocks=[DoubleBlock(slot_first=1, slot_second=2)],
            )

    def test_teacher_config_defaults_valid(self):
        """TeacherConfig mit Defaults ist valide."""
        from config.schema import TeacherConfig
        tc = TeacherConfig()
        assert tc.total_count == 105
        assert tc.vollzeit_deputat == 26

    def test_grade_total_classes(self):
        """GradeConfig.total_classes berechnet korrekt."""
        gc = GradeConfig(grades=[
            GradeDefinition(grade=5, num_classes=6, weekly_hours_target=30),
            GradeDefinition(grade=6, num_classes=5, weekly_hours_target=31),
        ])
        assert gc.total_classes == 11

    def test_invalid_days_per_week(self):
        """Ungültige Tagesanzahl (< 5 oder > 6) → Validierungsfehler."""
        with pytest.raises(Exception):
            TimeGridConfig(
                days_per_week=4,
                lesson_slots=[LessonSlot(slot_number=1,
                                         start_time="08:00", end_time="08:45")],
                pauses=[],
                double_blocks=[],
            )


# ─── YAML SPEICHERN / LADEN ───────────────────────────────────────────────────

class TestConfigManager:
    def test_save_and_load_roundtrip(self, tmp_path: Path):
        """Config speichern, laden und validieren — vollständiger Roundtrip."""
        config = default_school_config()
        mgr = ConfigManager()
        mgr.CONFIG_DIR = tmp_path
        mgr.DEFAULT_CONFIG = tmp_path / "school_config.yaml"

        mgr.save(config)
        assert mgr.DEFAULT_CONFIG.exists()

        loaded = mgr.load(mgr.DEFAULT_CONFIG)
        assert loaded.school_name == config.school_name
        assert loaded.grades.total_classes == config.grades.total_classes
        assert loaded.teachers.total_count == config.teachers.total_count

    def test_first_run_check_no_file(self, tmp_path: Path):
        """first_run_check gibt True zurück wenn keine Config existiert."""
        mgr = ConfigManager()
        mgr.DEFAULT_CONFIG = tmp_path / "nonexistent.yaml"
        assert mgr.first_run_check() is True

    def test_first_run_check_with_file(self, tmp_path: Path):
        """first_run_check gibt False zurück wenn Config existiert."""
        config = default_school_config()
        mgr = ConfigManager()
        mgr.CONFIG_DIR = tmp_path
        mgr.DEFAULT_CONFIG = tmp_path / "school_config.yaml"
        mgr.save(config)
        assert mgr.first_run_check() is False

    def test_load_nonexistent_raises(self, tmp_path: Path):
        """Laden einer nicht-existenten Datei → FileNotFoundError."""
        mgr = ConfigManager()
        with pytest.raises(FileNotFoundError):
            mgr.load(tmp_path / "not_there.yaml")

    def test_scenario_save_and_load(self, tmp_path: Path):
        """Szenario speichern und laden — Roundtrip."""
        config = default_school_config()
        config = config.model_copy(update={"school_name": "Test-Schule"})

        mgr = ConfigManager()
        mgr.CONFIG_DIR = tmp_path
        mgr.DEFAULT_CONFIG = tmp_path / "school_config.yaml"
        mgr.SCENARIOS_DIR = tmp_path / "scenarios"

        mgr.save_scenario(config, "test_szenario", "Nur zum Testen")
        loaded = mgr.load_scenario("test_szenario")
        assert loaded.school_name == "Test-Schule"

    def test_list_scenarios_empty(self, tmp_path: Path):
        """Leeres Szenario-Verzeichnis → leere Liste."""
        mgr = ConfigManager()
        mgr.SCENARIOS_DIR = tmp_path / "scenarios"
        assert mgr.list_scenarios() == []


# ─── MODELLE (Phase 1: Pydantic v2) ──────────────────────────────────────────

class TestModels:
    def test_subject_pydantic(self):
        """Subject ist ein Pydantic-Modell mit korrekten Feldern."""
        from models.subject import Subject
        s = Subject(name="Mathematik", short_name="Ma", category="hauptfach",
                    is_hauptfach=True)
        assert s.name == "Mathematik"
        assert s.short_name == "Ma"
        assert not s.needs_special_room

    def test_subject_with_room(self):
        """Subject mit Fachraum: needs_special_room=True."""
        from models.subject import Subject
        s = Subject(name="Physik", short_name="Ph", category="nw",
                    requires_special_room="physik", double_lesson_required=True)
        assert s.needs_special_room
        assert s.requires_special_room == "physik"

    def test_teacher_pydantic(self):
        """Teacher ist ein Pydantic-Modell; id wird normalisiert."""
        from models.teacher import Teacher
        t = Teacher(id="mül", name="Müller, Hans", subjects=["Mathematik", "Physik"],
                    deputat=26)
        assert t.id == "MÜL"  # normalisiert zu Großbuchstaben
        assert t.deputat == 26
        assert not t.is_teilzeit

    def test_teacher_unavailable_slots(self):
        """Teacher.unavailable_slots akzeptiert tuple[int,int]."""
        from models.teacher import Teacher
        t = Teacher(id="TST", name="Test, A", subjects=["Deutsch"], deputat=20,
                    unavailable_slots=[(0, 1), (0, 2), (4, 7)])
        assert len(t.unavailable_slots) == 3

    def test_school_class_pydantic(self):
        """SchoolClass hat id, curriculum und max_slot."""
        from models.school_class import SchoolClass
        sc = SchoolClass(
            id="7b", grade=7, label="b",
            curriculum={"Mathematik": 4, "Deutsch": 4, "Englisch": 3},
            max_slot=7,
        )
        assert sc.id == "7b"
        assert sc.total_weekly_hours == 11
        assert sc.max_slot == 7

    def test_room_pydantic(self):
        """Room hat id, room_type, name."""
        from models.room import Room
        r = Room(id="PH1", room_type="physik", name="Physik-Raum 1")
        assert r.room_type == "physik"

    def test_coupling_group(self):
        """CouplingGroup hat group_name, subject, hours_per_week."""
        from models.coupling import CouplingGroup
        cg = CouplingGroup(group_name="evangelisch", subject="Religion", hours_per_week=2)
        assert cg.group_name == "evangelisch"

    def test_coupling_pydantic(self):
        """Coupling hat id, coupling_type, involved_class_ids, groups."""
        from models.coupling import Coupling, CouplingGroup
        c = Coupling(
            id="reli_5",
            coupling_type="reli_ethik",
            involved_class_ids=["5a", "5b", "5c"],
            groups=[
                CouplingGroup(group_name="evangelisch", subject="Religion", hours_per_week=2),
                CouplingGroup(group_name="ethik", subject="Ethik", hours_per_week=2),
            ],
            hours_per_week=2,
        )
        assert c.id == "reli_5"
        assert len(c.groups) == 2
        assert c.cross_class is True  # Default


# ─── FAKE-DATEN ───────────────────────────────────────────────────────────────

class TestFakeData:
    def test_generate_returns_school_data(self):
        """FakeDataGenerator.generate() gibt SchoolData zurück."""
        from data.fake_data import FakeDataGenerator
        from models.school_data import SchoolData
        config = default_school_config()
        gen = FakeDataGenerator(config, seed=42)
        data = gen.generate()
        assert isinstance(data, SchoolData)

    def test_generate_all_compat(self):
        """generate_all() (compat) gibt dict zurück."""
        from data.fake_data import FakeDataGenerator
        config = default_school_config()
        gen = FakeDataGenerator(config, seed=42)
        data = gen.generate_all()
        assert isinstance(data, dict)
        assert len(data["subjects"]) > 0
        assert len(data["classes"]) == 36
        assert len(data["teachers"]) == 105

    def test_generate_classes_count(self):
        """Anzahl generierter Klassen stimmt mit Config überein."""
        from data.fake_data import FakeDataGenerator
        config = default_school_config()
        gen = FakeDataGenerator(config, seed=0)
        data = gen.generate()
        assert len(data.classes) == config.grades.total_classes

    def test_generate_teachers_count(self):
        """Anzahl generierter Lehrer stimmt mit Config überein."""
        from data.fake_data import FakeDataGenerator
        config = default_school_config()
        gen = FakeDataGenerator(config, seed=0)
        data = gen.generate()
        assert len(data.teachers) == config.teachers.total_count

    def test_teacher_ids_unique(self):
        """Lehrer-IDs (Kürzel) sind eindeutig."""
        from data.fake_data import FakeDataGenerator
        config = default_school_config()
        gen = FakeDataGenerator(config, seed=1)
        data = gen.generate()
        ids = [t.id for t in data.teachers]
        assert len(ids) == len(set(ids)), "Doppelte Lehrer-Kürzel gefunden!"

    def test_generate_rooms(self):
        """Fachräume werden korrekt generiert (Physik:3, Chemie:2, Bio:3, ...)."""
        from data.fake_data import FakeDataGenerator
        config = default_school_config()
        gen = FakeDataGenerator(config, seed=0)
        data = gen.generate()
        # Physik:3, Chemie:2, Bio:3, Inf:2, Kunst:3, Musik:3, Sport:4 = 20
        assert len(data.rooms) == 20

    def test_classes_have_curriculum(self):
        """Alle Klassen haben ein nicht-leeres Curriculum."""
        from data.fake_data import FakeDataGenerator
        config = default_school_config()
        gen = FakeDataGenerator(config, seed=42)
        data = gen.generate()
        for cls in data.classes:
            assert len(cls.curriculum) > 0, f"Klasse {cls.id} hat leeres Curriculum"
            assert cls.total_weekly_hours > 0

    def test_classes_have_max_slot(self):
        """Alle Klassen haben max_slot aus Config."""
        from data.fake_data import FakeDataGenerator
        config = default_school_config()
        gen = FakeDataGenerator(config, seed=42)
        data = gen.generate()
        expected_max = config.time_grid.sek1_max_slot
        for cls in data.classes:
            assert cls.max_slot == expected_max

    def test_chemie_engpass_bottleneck(self):
        """Chemie-Engpass: Nur 2 Chemie-Lehrkräfte vorhanden."""
        from data.fake_data import FakeDataGenerator
        config = default_school_config()
        gen = FakeDataGenerator(config, seed=42)
        data = gen.generate()
        chemie_teachers = [t for t in data.teachers if "Chemie" in t.subjects]
        assert len(chemie_teachers) == 2, (
            f"Erwartet 2 Chemie-Lehrkräfte, gefunden: {len(chemie_teachers)}"
        )

    def test_freitag_cluster_bottleneck(self):
        """Freitag-Cluster: Mindestens 4 Lehrkräfte wünschen Freitag frei."""
        from data.fake_data import FakeDataGenerator
        config = default_school_config()
        gen = FakeDataGenerator(config, seed=42)
        data = gen.generate()
        fr_cluster = [t for t in data.teachers if 4 in t.preferred_free_days]
        assert len(fr_cluster) >= 4

    def test_restricted_teacher_bottleneck(self):
        """Stark eingeschränkter Lehrer: Hat Sperrzeiten für Mo, Fr und Di-Nachmittag."""
        from data.fake_data import FakeDataGenerator
        config = default_school_config()
        gen = FakeDataGenerator(config, seed=42)
        data = gen.generate()
        # Suche Lehrer mit vielen gesperrten Slots (≥ 18 = Mo7 + Fr7 + Di-Nachmittag4)
        restricted = [t for t in data.teachers if len(t.unavailable_slots) >= 18]
        assert len(restricted) >= 1, "Kein eingeschränkter Lehrer gefunden!"

    def test_generate_subjects_from_metadata(self):
        """Alle Fächer aus SUBJECT_METADATA werden erzeugt."""
        from data.fake_data import FakeDataGenerator
        config = default_school_config()
        gen = FakeDataGenerator(config, seed=0)
        data = gen.generate()
        names = {s.name for s in data.subjects}
        assert "Deutsch" in names
        assert "Mathematik" in names
        assert "Physik" in names

    def test_couplings_generated(self):
        """Kopplungen (Reli/Ethik und WPF) werden erzeugt."""
        from data.fake_data import FakeDataGenerator
        config = default_school_config()
        gen = FakeDataGenerator(config, seed=42)
        data = gen.generate()
        assert len(data.couplings) > 0
        reli = [c for c in data.couplings if c.coupling_type == "reli_ethik"]
        wpf = [c for c in data.couplings if c.coupling_type == "wpf"]
        assert len(reli) == 6  # Jahrgänge 5-10
        assert len(wpf) == 2   # Jahrgänge 9-10


# ─── SCHOOL DATA + FEASIBILITY ────────────────────────────────────────────────

class TestSchoolData:
    def _make_data(self, seed: int = 42):
        from data.fake_data import FakeDataGenerator
        config = default_school_config()
        gen = FakeDataGenerator(config, seed=seed)
        return gen.generate()

    def test_summary_contains_key_info(self):
        """summary() enthält Schlüsselinfos."""
        data = self._make_data()
        s = data.summary()
        assert "Klassen" in s
        assert "Lehrkräfte" in s
        assert "Gesamtdeputat" in s

    def test_validate_feasibility_returns_report(self):
        """validate_feasibility() gibt FeasibilityReport zurück."""
        from models.school_data import FeasibilityReport
        data = self._make_data()
        report = data.validate_feasibility()
        assert isinstance(report, FeasibilityReport)
        assert isinstance(report.is_feasible, bool)
        assert isinstance(report.errors, list)
        assert isinstance(report.warnings, list)

    def test_chemie_engpass_triggers_warning(self):
        """Chemie-Engpass erzeugt Warnung im Feasibility-Report."""
        data = self._make_data()
        report = data.validate_feasibility()
        # Warnung wegen Chemie-Auslastung > 85%
        chemie_warnings = [w for w in report.warnings if "Chemie" in w or "chemie" in w.lower()]
        assert len(chemie_warnings) >= 1, (
            f"Keine Chemie-Warnung im Report. Warnungen: {report.warnings}"
        )

    def test_freitag_cluster_triggers_warning(self):
        """Freitag-Cluster erzeugt Warnung im Feasibility-Report."""
        data = self._make_data()
        report = data.validate_feasibility()
        fr_warnings = [w for w in report.warnings
                       if "Freitag" in w or "freitag" in w.lower()]
        assert len(fr_warnings) >= 1

    def test_feasibility_broken_data(self):
        """Kaputte Daten (kein Lehrer für Mathematik) → error im Report."""
        from models.school_data import SchoolData
        from models.teacher import Teacher
        from models.school_class import SchoolClass
        from models.subject import Subject

        config = default_school_config()
        data = SchoolData(
            subjects=[Subject(name="Mathematik", short_name="Ma", category="hauptfach")],
            rooms=[],
            classes=[SchoolClass(
                id="5a", grade=5, label="a",
                curriculum={"Mathematik": 4}, max_slot=7,
            )],
            teachers=[],  # Kein Lehrer!
            couplings=[],
            config=config,
        )
        report = data.validate_feasibility()
        assert not report.is_feasible
        assert any("Mathematik" in e for e in report.errors)

    def test_save_and_load_json(self, tmp_path: Path):
        """SchoolData → JSON → SchoolData Roundtrip."""
        data = self._make_data()
        json_path = tmp_path / "school_data.json"
        data.save_json(json_path)
        assert json_path.exists()

        loaded = type(data).load_json(json_path)
        assert len(loaded.classes) == len(data.classes)
        assert len(loaded.teachers) == len(data.teachers)
        assert loaded.config.school_name == data.config.school_name

    def test_load_json_nonexistent_raises(self, tmp_path: Path):
        """load_json mit nicht-existenter Datei → FileNotFoundError."""
        from models.school_data import SchoolData
        with pytest.raises(FileNotFoundError):
            SchoolData.load_json(tmp_path / "does_not_exist.json")


# ─── EXCEL TEMPLATE ───────────────────────────────────────────────────────────

class TestExcelTemplate:
    def test_template_creates_file(self, tmp_path: Path):
        """generate_template() erzeugt eine Excel-Datei."""
        from data.excel_import import generate_template
        config = default_school_config()
        out = tmp_path / "vorlage.xlsx"
        generate_template(config, out)
        assert out.exists()
        assert out.stat().st_size > 0

    def test_template_has_correct_sheets(self, tmp_path: Path):
        """Excel-Vorlage enthält alle 6 Pflicht-Blätter."""
        import openpyxl
        from data.excel_import import generate_template
        config = default_school_config()
        out = tmp_path / "vorlage.xlsx"
        generate_template(config, out)

        wb = openpyxl.load_workbook(str(out))
        sheet_names_lower = [s.lower() for s in wb.sheetnames]
        for expected in ["zeitraster", "jahrgänge", "stundentafel",
                         "lehrkräfte", "fachräume", "kopplungen"]:
            assert expected in sheet_names_lower, \
                f"Blatt '{expected}' fehlt. Vorhanden: {wb.sheetnames}"

    def test_zeitraster_sheet_prefilled(self, tmp_path: Path):
        """Zeitraster-Blatt enthält vorausgefüllte Daten aus Config."""
        import openpyxl
        from data.excel_import import generate_template
        config = default_school_config()
        out = tmp_path / "vorlage.xlsx"
        generate_template(config, out)

        wb = openpyxl.load_workbook(str(out))
        ws = wb["Zeitraster"]
        rows = list(ws.iter_rows(values_only=True))
        # Header + mind. eine Datenzeile
        assert len(rows) >= 2
        # Erste Spalte der zweiten Zeile = Slot-Nummer 1
        assert rows[1][0] == 1


# ─── MAIN.PY CLI ──────────────────────────────────────────────────────────────

class TestCli:
    def test_help(self):
        """main.py --help gibt Usage aus."""
        from click.testing import CliRunner
        from main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Usage" in result.output

    def test_config_show_no_file(self):
        """config show ohne Konfiguration → Fehlermeldung."""
        from click.testing import CliRunner
        from main import cli
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["config", "show"])
            assert result.exit_code != 0 or "Keine Konfiguration" in result.output

    def test_generate_command_exists(self):
        """generate Befehl ist registriert und hat --export-json."""
        from click.testing import CliRunner
        from main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["generate", "--help"])
        assert result.exit_code == 0
        assert "export-json" in result.output

    def test_template_command_exists(self):
        """template Befehl ist registriert."""
        from click.testing import CliRunner
        from main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["template", "--help"])
        assert result.exit_code == 0

    def test_import_command_exists(self):
        """import Befehl ist registriert."""
        from click.testing import CliRunner
        from main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["import", "--help"])
        assert result.exit_code == 0

    def test_validate_command_exists(self):
        """validate Befehl ist registriert."""
        from click.testing import CliRunner
        from main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["validate", "--help"])
        assert result.exit_code == 0

    def test_solve_command_exists(self):
        """solve Befehl ist registriert."""
        from click.testing import CliRunner
        from main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["solve", "--help"])
        assert result.exit_code == 0

    def test_scenario_list_command_exists(self):
        """scenario list Befehl ist registriert."""
        from click.testing import CliRunner
        from main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["scenario", "list"])
        assert result.exit_code == 0
