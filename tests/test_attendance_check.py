"""Tests für die Prüfung "freie Lehrkräfte für die Pflichtstunden"."""

import pytest

import data.nrw_data as nrw_data
from benchmarks.assignment import assign_teachers
from benchmarks.datasets import build_dataset
from models.attendance_check import (
    attendance_by_slot, check_attendance, daily_slots_by_class,
    hall_violation,
)
from models.coupling import Coupling, CouplingGroup
from models.school_data import SchoolData
from tests.test_solver import make_mini_school_data

MONDAY_FIRST = (0, 1)
LAST_SLOT_MONDAY = (0, 7)
# Mini-Daten: 7a hat 34 Wochenstunden → täglich Stunde 1–6;
# 5a hat 28 → ein freier Tag wäre möglich.
FULL_CLASS = "7a"
SHORT_CLASS = "5a"
FULL_CLASS_DAILY = [1, 2, 3, 4, 5, 6]
SECOND_FULL_CLASS = "7b"
EXTRA_TEACHER = "T11"
ASSIGN_SEED = 42
# nrw-18 vor dem Wächter im Generator: montags in Stunde 1 zu wenige
# freie Lehrkräfte (17 für 18 Klassen).
SHORT_MORNING_SEEDS = (44, 46)


def _blocked_except(
    data: SchoolData, free_ids: set[str], slot: tuple[int, int]
) -> SchoolData:
    """Kopie, in der alle Lehrkräfte außer `free_ids` in `slot` fehlen."""
    teachers = [
        teacher if teacher.id in free_ids else teacher.model_copy(update={
            "unavailable_slots": [*teacher.unavailable_slots, slot],
        })
        for teacher in data.teachers
    ]
    return data.model_copy(update={"teachers": teachers})


def _with_second_full_class(data: SchoolData) -> SchoolData:
    """Mini-Daten mit einer zweiten Klasse wie 7a (ohne Kopplung)."""
    full = next(c for c in data.classes if c.id == FULL_CLASS)
    twin = full.model_copy(update={"id": SECOND_FULL_CLASS, "label": "b"})
    return data.model_copy(update={"classes": [*data.classes, twin]})


def _with_extra_german_teacher(data: SchoolData) -> SchoolData:
    """Kopie mit einer Deutsch-Lehrkraft ohne Unterrichtsverteilung."""
    template = data.teachers[0]
    extra = template.model_copy(update={
        "id": EXTRA_TEACHER, "name": "Neu, Nina", "subjects": ["Deutsch"],
        "unavailable_slots": [],
    })
    return data.model_copy(update={"teachers": [*data.teachers, extra]})


def _errors(data: SchoolData) -> list[str]:
    return check_attendance(
        data.classes, data.teachers, data.couplings,
        data.fixed_assignments, data.config.time_grid,
    )


class TestDailySlots:

    def test_only_long_weeks_need_every_day(self):
        data = make_mini_school_data()
        daily = daily_slots_by_class(
            data.classes, data.couplings, data.config.time_grid
        )
        assert daily == {SHORT_CLASS: [], FULL_CLASS: FULL_CLASS_DAILY}

    def test_attendance_counts_classes_per_slot(self):
        data = _with_second_full_class(make_mini_school_data())
        attendance = attendance_by_slot(
            data.classes, data.couplings, data.config.time_grid
        )
        # 7b: Tafel wie 7a, Religion ohne Kopplung → ebenfalls 34
        assert attendance == {1: 2, 2: 2, 3: 2, 4: 2, 5: 2, 6: 2, 7: 0}


class TestHallViolation:

    def test_all_classes_get_a_teacher(self):
        assert hall_violation({"a": {"T1", "T2"}, "b": {"T1"}}) is None

    def test_two_classes_share_one_teacher(self):
        candidates = {"a": {"T1"}, "b": {"T1"}, "c": {"T2", "T3"}}
        assert hall_violation(candidates) == (["a", "b"], ["T1"])

    def test_class_without_any_teacher(self):
        assert hall_violation({"a": set(), "b": {"T1"}}) == (["a"], [])

    def test_no_classes(self):
        assert hall_violation({}) is None


class TestCheckAttendance:

    def test_mini_school_passes(self):
        assert _errors(make_mini_school_data()) == []

    def test_no_teacher_free_for_a_full_class(self):
        data = _blocked_except(make_mini_school_data(), set(), MONDAY_FIRST)
        errors = _errors(data)
        assert len(errors) == 1
        assert errors[0].startswith("Mo 1. Stunde: 1 Klasse (7a) hat")
        assert "nur 0 der dafür möglichen Lehrkräfte sind frei" in errors[0]

    def test_lessons_not_needed_every_day_are_not_checked(self):
        # Stunde 7 hat keine Klasse an jedem Tag (7a: 1–6, 5a: keine).
        data = _blocked_except(
            make_mini_school_data(), set(), LAST_SLOT_MONDAY
        )
        assert _errors(data) == []

    def test_two_full_classes_and_one_free_teacher(self):
        data = _with_second_full_class(make_mini_school_data())
        blocked = _blocked_except(data, {"T01"}, MONDAY_FIRST)
        errors = _errors(blocked)
        assert len(errors) == 1
        assert "2 Klassen (7a, 7b) haben" in errors[0]
        assert "nur 1 der dafür möglichen Lehrkräfte ist frei (T01)" in (
            errors[0]
        )

    def test_coupling_teachers_count_for_their_classes(self):
        # Nur die Religion/Ethik-Lehrkräfte sind frei: 7a kann dann
        # in der Kopplung reli_7 Unterricht haben.
        data = _blocked_except(
            make_mini_school_data(), {"T08", "T09"}, MONDAY_FIRST
        )
        assert _errors(data) == []

    def test_coupling_with_fewer_groups_covers_its_classes(self):
        data = _with_second_full_class(make_mini_school_data())
        shared = Coupling(
            id="band_7", coupling_type="band",
            involved_class_ids=[FULL_CLASS, SECOND_FULL_CLASS],
            groups=[CouplingGroup(
                group_name="alle", subject="Musik", hours_per_week=1,
            )],
            hours_per_week=1,
        )
        data = data.model_copy(update={
            "couplings": [*data.couplings, shared],
        })
        # Nur T05 (Musik) frei: eine Gruppe für zwei Klassen. Die
        # Prüfung meldet nur Sicheres und lässt beide Klassen gelten.
        blocked = _blocked_except(data, {"T05"}, MONDAY_FIRST)
        assert _errors(blocked) == []

    def test_given_distribution_counts_only_assigned_teachers(self):
        open_data = _with_extra_german_teacher(make_mini_school_data())
        given = _with_extra_german_teacher(
            assign_teachers(make_mini_school_data(), ASSIGN_SEED)
        )
        assert _errors(
            _blocked_except(open_data, {EXTRA_TEACHER}, MONDAY_FIRST)
        ) == []
        errors = _errors(
            _blocked_except(given, {EXTRA_TEACHER}, MONDAY_FIRST)
        )
        assert len(errors) == 1
        assert "nur 0 der dafür möglichen Lehrkräfte" in errors[0]


class TestFeasibilityReport:

    def test_shortage_makes_data_infeasible(self):
        data = _blocked_except(make_mini_school_data(), set(), MONDAY_FIRST)
        report = data.validate_feasibility()
        assert not report.is_feasible
        assert any(e.startswith("Mo 1. Stunde:") for e in report.errors)

    @pytest.mark.parametrize("dataset", ["nrw-18-fixed", "nrw-18"])
    @pytest.mark.parametrize("seed", SHORT_MORNING_SEEDS)
    def test_former_benchmark_failures_are_reported(
        self, dataset: str, seed: int, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(
            nrw_data.AttendanceGuard, "allows", lambda self, unit: True
        )
        errors = build_dataset(dataset, seed).validate_feasibility().errors
        assert any(e.startswith("Mo 1. Stunde: 18 Klassen") for e in errors)

    @pytest.mark.parametrize("seed", SHORT_MORNING_SEEDS)
    def test_corrected_benchmark_data_passes(self, seed: int):
        data = build_dataset("nrw-18-fixed", seed)
        assert _errors(data) == []
