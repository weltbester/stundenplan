"""Tests für Schritt 4d: Testdaten-Profil "nrw-g9"."""

import math
import random

import pytest
from click.testing import CliRunner

from config.defaults import SECOND_LANGUAGE_SUBJECT, default_school_config
from config.nrw_g9 import STUNDENTAFEL_NRW_G9
from config.schema import GradeConfig, GradeDefinition, SchoolConfig
from data.coupling_builder import (
    parallel_coupling, parallel_groups, reli_group_subject,
)
from data.fake_data import FakeDataGenerator
from data.generators import (
    PROFILE_LOOSE, PROFILE_NRW_G9, PROFILES, generate_school_data,
)
from data.nrw_data import (
    MAX_SUBJECTS, MIN_SHARE_HOURS, RESERVE_HOURS, SPARE_TEACHERS,
    SUPPORT_SUBJECT, NrwDataGenerator, NrwProfile, StaffPlanner,
    make_abbreviation, nrw_couplings, parallel_group_counts, round_half,
    teaching_demand,
)
from models.coupling import (
    COUPLING_TYPE_BAND, COUPLING_TYPE_RELI_ETHIK, COUPLING_TYPE_WPF,
)
from models.deputat_check import target_margin
from models.school_data import SchoolData
from models.teacher import HALF_LESSONS_PER_LESSON
from solver.distribution import distribute_teachers

FIRST_GRADE, LAST_GRADE = 5, 10
SEEDS = (1, 2, 3, 4, 5)
PARALLEL_CLASSES = 3
MARGIN_RANGE = (0.03, 0.05)
PART_TIME_RANGE = (0.10, 0.50)
FULL_TIME_HOURS = 25.5
DISTRIBUTION_SECONDS = 20


def _config(parallel_classes: int) -> SchoolConfig:
    return default_school_config().model_copy(update={
        "grades": GradeConfig(grades=[
            GradeDefinition(grade=grade, num_classes=parallel_classes)
            for grade in range(FIRST_GRADE, LAST_GRADE + 1)
        ]),
    })


def _generate(
    seed: int, parallel_classes: int = PARALLEL_CLASSES
) -> SchoolData:
    return NrwDataGenerator(_config(parallel_classes), seed=seed).generate()


@pytest.fixture(scope="module", params=SEEDS)
def data(request: pytest.FixtureRequest) -> SchoolData:
    return _generate(request.param)


# ─── Kopplungen ───────────────────────────────────────────────────────────────

class TestCouplingBuilder:

    @pytest.mark.parametrize("name,subject", [
        ("evangelisch", "Religion"), ("katholisch", "Religion"),
        ("ethik", "Ethik"), ("Ethik", "Ethik"),
        ("Praktische Philosophie", "Praktische Philosophie"),
        ("praktische philosophie ", "Praktische Philosophie"),
    ])
    def test_reli_group_subject(self, name: str, subject: str):
        assert reli_group_subject(name) == subject

    def test_groups_cycle_through_the_kinds(self):
        kinds = [("ev", "Religion"), ("PP", "Praktische Philosophie")]
        groups = parallel_groups(kinds, group_count=5, hours=2)
        assert [g.group_name for g in groups] == [
            "ev 1", "PP 1", "ev 2", "PP 2", "ev 3",
        ]
        assert {g.hours_per_week for g in groups} == {2}

    def test_at_least_one_group_per_kind(self):
        kinds = [("a", "Deutsch"), ("b", "Englisch"), ("c", "Latein")]
        assert len(parallel_groups(kinds, group_count=1, hours=3)) == 3

    def test_parallel_coupling_has_one_group_per_class(self):
        coupling = parallel_coupling(
            "wpf_9", COUPLING_TYPE_WPF, ["9a", "9b", "9c", "9d"],
            [("If", "Informatik"), ("Bi", "Biologie")], hours=3,
        )
        assert len(coupling.groups) == 4
        assert coupling.hours_per_week == 3
        assert coupling.curriculum_subject is None


class TestNrwCouplings:

    @pytest.fixture(scope="class")
    def couplings(self) -> dict:
        data = _generate(seed=1)
        return {c.id: c for c in data.couplings}

    def test_every_grade_has_a_religion_coupling(self, couplings: dict):
        for grade in range(FIRST_GRADE, LAST_GRADE + 1):
            coupling = couplings[f"reli_{grade}"]
            assert coupling.coupling_type == COUPLING_TYPE_RELI_ETHIK
            assert len(coupling.groups) == PARALLEL_CLASSES
            assert coupling.hours_per_week == (
                STUNDENTAFEL_NRW_G9[grade]["Religion"]
            )

    def test_religion_uses_praktische_philosophie(self, couplings: dict):
        subjects = {g.subject for g in couplings["reli_5"].groups}
        assert subjects == {"Religion", "Praktische Philosophie"}

    def test_electives_only_in_grades_9_and_10(self, couplings: dict):
        elective_ids = sorted(
            c.id for c in couplings.values()
            if c.coupling_type == COUPLING_TYPE_WPF
        )
        assert elective_ids == ["wpf_10", "wpf_9"]
        subjects = [g.subject for g in couplings["wpf_9"].groups]
        assert subjects == list(NrwProfile().wpf_subjects)

    def test_language_band_from_grade_7(self, couplings: dict):
        band_ids = sorted(
            c.id for c in couplings.values()
            if c.coupling_type == COUPLING_TYPE_BAND
        )
        assert band_ids == ["fs2_10", "fs2_7", "fs2_8", "fs2_9"]
        band = couplings["fs2_10"]
        assert band.curriculum_subject == SECOND_LANGUAGE_SUBJECT
        assert band.hours_per_week == (
            STUNDENTAFEL_NRW_G9[10][SECOND_LANGUAGE_SUBJECT]
        )

    def test_group_names_are_unique_within_a_coupling(self, couplings: dict):
        for coupling in couplings.values():
            names = [g.group_name for g in coupling.groups]
            assert len(set(names)) == len(names)

    def test_disabled_couplings_are_left_out(self):
        config = _config(PARALLEL_CLASSES)
        config = config.model_copy(update={
            "couplings": config.couplings.model_copy(update={
                "reli_ethik_enabled": False, "wpf_enabled": False,
                "second_language_subjects": [],
            }),
        })
        classes = FakeDataGenerator(
            config, curriculum=STUNDENTAFEL_NRW_G9
        ).generate_classes()
        assert nrw_couplings(classes, config) == []


# ─── Bedarf und Stellenplan ───────────────────────────────────────────────────

class TestDemand:

    def test_demand_counts_groups_not_classes(self):
        data = _generate(seed=1)
        demand = teaching_demand(data.classes, data.couplings)
        bands = [c for c in data.couplings
                 if c.coupling_type == COUPLING_TYPE_BAND]
        french = sum(
            g.hours_per_week for c in bands for g in c.groups
            if g.subject == "Französisch"
        )
        assert demand["Französisch"] == french
        assert SECOND_LANGUAGE_SUBJECT not in demand
        assert "WPF" not in demand

    def test_demand_of_a_regular_subject(self):
        data = _generate(seed=1)
        demand = teaching_demand(data.classes, data.couplings)
        per_class = sum(
            table.get("Deutsch", 0) for table in STUNDENTAFEL_NRW_G9.values()
        )
        assert demand["Deutsch"] == per_class * PARALLEL_CLASSES

    def test_parallel_group_counts(self):
        data = _generate(seed=1, parallel_classes=6)
        counts = parallel_group_counts(data.couplings)
        assert counts["Französisch"] == 3
        assert counts["Latein"] == 3
        assert counts["Religion"] == 4
        assert counts["Praktische Philosophie"] == 2


class TestStaffPlanner:

    DEMAND = {"Deutsch": 60.0, "Geschichte": 30.0, "Latein": 24.0,
              SUPPORT_SUBJECT: 6.0}
    PARALLEL = {"Latein": 2}

    def _posts(self, seed: int) -> list:
        planner = StaffPlanner(
            dict(self.DEMAND), self.PARALLEL, NrwProfile(), (12, 20),
            random.Random(seed),
        )
        return planner.plan()

    def _planned(self, seed: int) -> dict[str, float]:
        planned: dict[str, float] = {}
        for post in self._posts(seed):
            for subject, hours in post.shares.items():
                planned[subject] = planned.get(subject, 0) + hours
        return planned

    @pytest.mark.parametrize("seed", SEEDS)
    def test_every_subject_is_staffed_up_to_a_small_rest(self, seed: int):
        planned = self._planned(seed)
        margin = 1 + NrwProfile().capacity_margin
        support = self.DEMAND[SUPPORT_SUBJECT]
        assert planned["Deutsch"] >= (
            (self.DEMAND["Deutsch"] + support) * margin - MIN_SHARE_HOURS
        )
        for subject in ("Geschichte", "Latein"):
            assert planned[subject] >= (
                self.DEMAND[subject] * margin - MIN_SHARE_HOURS
            )

    @pytest.mark.parametrize("seed", SEEDS)
    def test_support_lessons_are_not_a_subject_of_their_own(self, seed: int):
        assert SUPPORT_SUBJECT not in self._planned(seed)

    @pytest.mark.parametrize("seed", SEEDS)
    def test_parallel_subject_gets_spare_teachers(self, seed: int):
        latin_posts = [p for p in self._posts(seed) if "Latein" in p.shares]
        assert len(latin_posts) >= self.PARALLEL["Latein"] + SPARE_TEACHERS

    @pytest.mark.parametrize("seed", SEEDS)
    def test_posts_stay_within_their_contract(self, seed: int):
        for post in self._posts(seed):
            assert 0 < post.sek1_hours <= post.total_hours
            assert len(post.shares) <= MAX_SUBJECTS

    def test_same_seed_gives_same_posts(self):
        assert self._posts(7) == self._posts(7)


# ─── Datensatz ────────────────────────────────────────────────────────────────

class TestGeneratedData:

    def test_feasibility_check_passes(self, data: SchoolData):
        report = data.validate_feasibility()
        assert report.is_feasible, report.errors

    def test_no_weekly_frame_warning(self, data: SchoolData):
        warnings = data.validate_feasibility().warnings
        assert [w for w in warnings if "NRW-Rahmen" in w] == []

    def test_capacity_margin_is_a_few_percent(self, data: SchoolData):
        margin = target_margin(
            data.teachers, data.classes, data.couplings,
            data.config.teachers.deputat_max_buffer,
        )
        low, high = MARGIN_RANGE
        assert low <= margin <= high

    def test_every_needed_subject_has_teachers(self, data: SchoolData):
        taught = {s for teacher in data.teachers for s in teacher.subjects}
        demand = teaching_demand(data.classes, data.couplings)
        assert set(demand) <= taught

    def test_enough_teachers_for_parallel_groups(self, data: SchoolData):
        for subject, count in parallel_group_counts(data.couplings).items():
            teachers = [t for t in data.teachers if subject in t.subjects]
            assert len(teachers) >= count, subject

    def test_targets_are_half_lessons_up_to_full_time(self, data: SchoolData):
        for teacher in data.teachers:
            doubled = teacher.deputat_soll * HALF_LESSONS_PER_LESSON
            assert doubled == int(doubled)
            assert 0 < teacher.deputat_soll <= FULL_TIME_HOURS

    def test_bounds_are_close_to_the_target(self, data: SchoolData):
        profile = NrwProfile()
        for teacher in data.teachers:
            target = teacher.deputat_soll
            assert teacher.deputat_max == (
                math.ceil(target) + profile.deputat_max_buffer
            )
            assert teacher.deputat_min == max(
                1, math.floor(target) - profile.deputat_min_buffer
            )

    def test_teacher_ids_are_unique_and_subjects_limited(
        self, data: SchoolData
    ):
        ids = [teacher.id for teacher in data.teachers]
        assert len(set(ids)) == len(ids)
        assert all(
            1 <= len(teacher.subjects) <= MAX_SUBJECTS
            for teacher in data.teachers
        )

    def test_about_a_third_works_part_time(self, data: SchoolData):
        share = sum(t.is_teilzeit for t in data.teachers) / len(data.teachers)
        low, high = PART_TIME_RANGE
        assert low <= share <= high

    def test_blocked_times_leave_a_reserve(self, data: SchoolData):
        grid = data.config.time_grid
        for teacher in data.teachers:
            if not teacher.unavailable_slots:
                continue
            teachable = teacher.teachable_hours(
                grid.days_per_week, grid.sek1_max_slot
            )
            assert teachable >= teacher.deputat_max + RESERVE_HOURS

    def test_blocked_times_stand_in_for_sek2(self, data: SchoolData):
        with_blocks = [t for t in data.teachers if t.unavailable_slots]
        assert len(with_blocks) >= len(data.teachers) / 2
        full_sek1 = [
            t for t in data.teachers
            if t.deputat_soll == FULL_TIME_HOURS
        ]
        assert all(not t.unavailable_slots for t in full_sek1)

    def test_config_follows_the_profile(self, data: SchoolData):
        profile = NrwProfile()
        settings = data.config.teachers
        assert settings.deputat_max_buffer == profile.deputat_max_buffer
        assert settings.deputat_min_buffer == profile.deputat_min_buffer
        assert settings.total_count == len(data.teachers)
        assert data.config.couplings.reli_groups == list(profile.reli_groups)
        assert data.config.bundesland == "NRW"

    def test_distribution_stage_finds_a_distribution(self, data: SchoolData):
        result = distribute_teachers(
            data, DISTRIBUTION_SECONDS, balance_targets=False, seed=1
        )
        assert result.status in ("OPTIMAL", "FEASIBLE")
        for teacher in data.teachers:
            hours = result.hours_by_teacher[teacher.id]
            assert teacher.deputat_min <= hours <= teacher.deputat_max


class TestDeterminism:

    def test_same_seed_gives_identical_data(self):
        first = _generate(seed=11).model_dump_json()
        assert first == _generate(seed=11).model_dump_json()

    def test_other_seed_gives_other_teachers(self):
        first = [t.name for t in _generate(seed=11).teachers]
        assert first != [t.name for t in _generate(seed=12).teachers]

    def test_classes_follow_the_nrw_table(self):
        data = _generate(seed=11)
        class_8b = next(c for c in data.classes if c.id == "8b")
        assert class_8b.curriculum == STUNDENTAFEL_NRW_G9[8]

    def test_two_classes_per_grade_are_supported(self):
        data = _generate(seed=11, parallel_classes=2)
        assert data.validate_feasibility().is_feasible
        assert len(data.classes) == 2 * (LAST_GRADE - FIRST_GRADE + 1)


class TestHelpers:

    @pytest.mark.parametrize("hours,expected", [
        (12.74, 12.5), (12.75, 13.0), (15.3, 15.5), (19.0, 19.0),
    ])
    def test_round_half(self, hours: float, expected: float):
        assert round_half(hours) == expected

    def test_abbreviations_are_unique_without_randomness(self):
        used: set[str] = set()
        first = [make_abbreviation("Müller", used) for _ in range(20)]
        assert len(set(first)) == len(first)
        assert first[0] == "MUE"
        again = [make_abbreviation("Müller", set()) for _ in range(1)]
        assert again == ["MUE"]


# ─── Profile und CLI ──────────────────────────────────────────────────────────

class TestProfiles:

    def test_profile_names(self):
        assert PROFILES == (PROFILE_LOOSE, PROFILE_NRW_G9)

    def test_loose_profile_is_the_previous_generator(self):
        config = default_school_config()
        expected = FakeDataGenerator(config, seed=42).generate()
        actual = generate_school_data(config, seed=42, profile=PROFILE_LOOSE)
        assert actual.model_dump_json() == expected.model_dump_json()
        assert generate_school_data(
            config, seed=42
        ).model_dump_json() == expected.model_dump_json()

    def test_nrw_profile_uses_the_nrw_generator(self):
        config = _config(PARALLEL_CLASSES)
        data = generate_school_data(config, seed=3, profile=PROFILE_NRW_G9)
        assert data.model_dump_json() == _generate(seed=3).model_dump_json()

    def test_unknown_profile_is_rejected(self):
        with pytest.raises(ValueError, match="Unbekanntes Profil"):
            generate_school_data(default_school_config(), 1, "bayern")

    def test_summary_shows_the_capacity_reserve(self):
        summary = _generate(seed=1).summary()
        assert "Unterrichtsbedarf (Lehrerstunden):" in summary
        assert "Kapazitätsreserve" in summary

    def test_cli_validate_generates_the_nrw_profile(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        import main

        monkeypatch.setattr(
            main, "_load_config_or_abort",
            lambda: (None, _config(PARALLEL_CLASSES)),
        )
        result = CliRunner().invoke(main.cmd_validate, [
            "--generate", "--profile", PROFILE_NRW_G9, "--seed", "2",
        ])
        assert result.exit_code == 0, result.output
        assert "Kapazitätsreserve" in result.output
        assert "LÖSBAR" in result.output
        assert "NICHT LÖSBAR" not in result.output


class TestOwnCurriculum:
    """Eigene Stundentafel: Klassen, Soll-Stunden und Bedarf folgen ihr."""

    EXTRA_GERMAN = 2

    def _curriculum(self) -> dict[int, dict[str, int]]:
        return {
            grade: {
                **table,
                "Deutsch": table.get("Deutsch", 0) + self.EXTRA_GERMAN,
            }
            for grade, table in STUNDENTAFEL_NRW_G9.items()
        }

    def test_classes_and_weekly_target_follow_the_table(self):
        curriculum = self._curriculum()
        generator = NrwDataGenerator(
            _config(1), seed=1, curriculum=curriculum
        )
        data = generator.generate()
        for school_class in data.classes:
            assert school_class.curriculum == curriculum[school_class.grade]
        for grade in generator.config.grades.grades:
            assert grade.weekly_hours_target == sum(
                curriculum[grade.grade].values()
            )

    def test_default_is_the_nrw_g9_table(self):
        data = _generate(seed=1, parallel_classes=1)
        for school_class in data.classes:
            assert school_class.curriculum == (
                STUNDENTAFEL_NRW_G9[school_class.grade]
            )
