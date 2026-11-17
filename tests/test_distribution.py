"""Tests für Stufe 1: die Unterrichtsverteilung ohne Zeitdimension."""

import pytest
from click.testing import CliRunner

from models.fixed_assignment import (
    FixedAssignment, coupling_subjects_by_class,
)
from models.school_data import SchoolData
from solver.distribution import (
    DISTRIBUTION_MAX_SECONDS, DISTRIBUTION_MIN_SECONDS, DistributionError,
    DistributionResult, describe_distribution, distribute_teachers,
    distribution_time_limit, forced_by_pins, is_distribution_complete,
    open_class_subjects, open_coupling_groups,
)
from solver.pinning import PinnedLesson
from solver.scheduler import ScheduleSolver
from tests.test_solver import make_mini_school_data

STAGE_SECONDS = 10
MAX_BUFFER = 6
FLEXIBLE_TEACHER = "T10"
LOW_TARGET = 4.0
HIGH_TARGET = 9.0


def _distribute(data: SchoolData, **options: object) -> DistributionResult:
    return distribute_teachers(data, STAGE_SECONDS, **options)


def _with_target(data: SchoolData, teacher_id: str, target: float):
    teachers = [
        t.model_copy(update={"deputat_soll": target})
        if t.id == teacher_id else t
        for t in data.teachers
    ]
    return data.model_copy(update={"teachers": teachers})


def _teacher_of(data: SchoolData, class_id: str, subject: str) -> str:
    return next(
        a.teacher_id for a in data.fixed_assignments
        if (a.class_id, a.subject) == (class_id, subject)
    )


class TestOpenDecisions:

    def test_data_without_distribution_is_incomplete(self):
        data = make_mini_school_data()
        covered = coupling_subjects_by_class(data.couplings)
        expected = sum(
            1
            for c in data.classes
            for subject, hours in c.curriculum.items()
            if hours > 0 and subject not in covered.get(c.id, set())
        )

        assert len(open_class_subjects(data)) == expected
        assert len(open_coupling_groups(data)) == sum(
            len(c.groups) for c in data.couplings
        )
        assert not is_distribution_complete(data)

    def test_fixed_pair_is_no_longer_open(self):
        data = make_mini_school_data()
        fixed = [FixedAssignment(
            class_id="5a", subject="Deutsch", teacher_id="T01"
        )]
        partly = data.model_copy(update={"fixed_assignments": fixed})

        assert ("5a", "Deutsch") in open_class_subjects(data)
        assert ("5a", "Deutsch") not in open_class_subjects(partly)

    def test_result_of_stage_one_is_complete(self):
        result = _distribute(make_mini_school_data())
        assert is_distribution_complete(result.data)


class TestDistributeTeachers:

    def test_every_pair_and_group_gets_one_teacher(self):
        data = make_mini_school_data()
        result = _distribute(data)

        pairs = [
            (a.class_id, a.subject) for a in result.data.fixed_assignments
        ]
        assert sorted(pairs) == sorted(open_class_subjects(data))
        assert all(
            group.teacher_id
            for coupling in result.data.couplings
            for group in coupling.groups
        )
        assert result.decided_assignments == len(pairs)
        assert result.status in ("OPTIMAL", "FEASIBLE")

    def test_original_data_is_not_modified(self):
        data = make_mini_school_data()
        _distribute(data)

        assert data.fixed_assignments == []

    def test_hours_stay_within_bounds(self):
        data = make_mini_school_data()
        result = _distribute(data)

        for teacher in data.teachers:
            hours = result.hours_by_teacher[teacher.id]
            assert teacher.deputat_min <= hours <= teacher.deputat_max

    def test_result_passes_the_feasibility_check(self):
        report = _distribute(
            make_mini_school_data()
        ).data.validate_feasibility()
        assert report.is_feasible, report.errors

    def test_given_assignment_is_kept_even_without_qualification(self):
        data = make_mini_school_data()
        # T02 (Mathematik, Physik) unterrichtet fachfremd Deutsch in 5a.
        fixed = [FixedAssignment(
            class_id="5a", subject="Deutsch", teacher_id="T02"
        )]
        result = _distribute(
            data.model_copy(update={"fixed_assignments": fixed})
        )

        assert _teacher_of(result.data, "5a", "Deutsch") == "T02"
        assert result.decided_assignments == (
            len(open_class_subjects(data)) - 1
        )

    def test_given_coupling_teacher_is_kept(self):
        data = make_mini_school_data()
        coupling = data.couplings[0]
        groups = [
            coupling.groups[0].model_copy(update={"teacher_id": "T09"}),
            *coupling.groups[1:],
        ]
        couplings = [
            coupling.model_copy(update={"groups": groups}),
            *data.couplings[1:],
        ]
        result = _distribute(
            data.model_copy(update={"couplings": couplings})
        )

        assert result.data.couplings[0].groups[0].teacher_id == "T09"

    def test_unknown_given_teacher_is_error(self):
        data = make_mini_school_data()
        fixed = [FixedAssignment(
            class_id="5a", subject="Deutsch", teacher_id="XXX"
        )]

        with pytest.raises(DistributionError, match="XXX"):
            _distribute(
                data.model_copy(update={"fixed_assignments": fixed})
            )

    def test_impossible_bounds_are_error(self):
        data = make_mini_school_data()
        teachers = [
            t.model_copy(update={"deputat_min": 30, "deputat_max": 30})
            for t in data.teachers
        ]

        with pytest.raises(DistributionError, match="INFEASIBLE"):
            _distribute(data.model_copy(update={"teachers": teachers}))


class TestTargetGoal:

    def test_higher_target_gives_more_lessons(self):
        data = make_mini_school_data()
        low = _distribute(_with_target(data, FLEXIBLE_TEACHER, LOW_TARGET))
        high = _distribute(
            _with_target(data, FLEXIBLE_TEACHER, HIGH_TARGET)
        )

        assert low.hours_by_teacher[FLEXIBLE_TEACHER] == LOW_TARGET
        assert (
            high.hours_by_teacher[FLEXIBLE_TEACHER]
            > low.hours_by_teacher[FLEXIBLE_TEACHER]
        )

    def test_without_goal_any_valid_distribution_is_returned(self):
        result = _distribute(
            make_mini_school_data(), balance_targets=False, seed=7,
            num_workers=1,
        )
        again = _distribute(
            make_mini_school_data(), balance_targets=False, seed=7,
            num_workers=1,
        )

        assert is_distribution_complete(result.data)
        assert (
            result.data.fixed_assignments == again.data.fixed_assignments
        )

    def test_summary_names_decisions_and_deviation(self):
        text = describe_distribution(_distribute(make_mini_school_data()))

        assert "Klasse-Fach-Zuweisungen" in text
        assert "Abweichung vom Soll" in text
        assert "Untergrenze" in text


class TestPins:

    def test_pinned_lesson_fixes_the_teacher_of_the_pair(self):
        data = make_mini_school_data()
        pin = PinnedLesson(
            teacher_id="T10", class_id="5a", subject="Deutsch",
            day=0, slot_number=1,
        )
        forced = forced_by_pins([pin], data)
        result = _distribute(data, forced=forced)

        assert forced == {("5a", "Deutsch"): "T10"}
        assert _teacher_of(result.data, "5a", "Deutsch") == "T10"

    def test_pinned_coupling_lesson_is_ignored(self):
        data = make_mini_school_data()
        pin = PinnedLesson(
            teacher_id="T08", class_id="5a", subject="Religion",
            day=0, slot_number=1,
        )

        assert forced_by_pins([pin], data) == {}


class TestTimeLimit:

    def test_stage_gets_a_share_of_the_limit(self):
        assert distribution_time_limit(100) == 20

    def test_share_is_capped(self):
        assert distribution_time_limit(3600) == DISTRIBUTION_MAX_SECONDS

    def test_share_has_a_floor(self):
        assert distribution_time_limit(10) == DISTRIBUTION_MIN_SECONDS


class TestTwoStages:

    def test_timetable_follows_the_distribution(self):
        data = make_mini_school_data()
        result = _distribute(data)
        solution = ScheduleSolver(result.data).solve(use_soft=False)

        assert solution.solver_status in ("OPTIMAL", "FEASIBLE")
        expected = {
            (a.teacher_id, a.class_id, a.subject)
            for a in result.data.fixed_assignments
        }
        actual = {
            (a.teacher_id, a.class_id, a.subject)
            for a in solution.assignments
        }
        assert actual == expected

    def test_cli_runs_stage_one_by_default(self, tmp_path):
        from main import cmd_solve

        output = tmp_path / "solution.json"
        result = CliRunner().invoke(cmd_solve, [
            "--small", "--no-soft", "--time-limit", "30",
            "-o", str(output), "--pins-path", str(tmp_path / "none.json"),
        ])

        assert result.exit_code == 0, result.output
        assert "Stufe 1: Unterrichtsverteilung" in result.output
        assert output.exists()

    def test_cli_single_stage_skips_stage_one(self, tmp_path):
        from main import cmd_solve

        output = tmp_path / "solution.json"
        result = CliRunner().invoke(cmd_solve, [
            "--small", "--no-soft", "--time-limit", "30", "--single-stage",
            "-o", str(output), "--pins-path", str(tmp_path / "none.json"),
        ])

        assert result.exit_code == 0, result.output
        assert "Stufe 1" not in result.output
        assert output.exists()
