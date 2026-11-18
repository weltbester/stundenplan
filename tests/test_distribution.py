"""Tests für Stufe 1: die Unterrichtsverteilung ohne Zeitdimension."""

import pytest
from click.testing import CliRunner

from models.coupling import Coupling, CouplingGroup
from models.fixed_assignment import (
    FixedAssignment, coupling_subjects_by_class,
)
from models.school_data import SchoolData
from solver.distribution import (
    DISTRIBUTION_MAX_SECONDS, DISTRIBUTION_MIN_SECONDS, DistributionError,
    DistributionResult, describe_distribution, distribute_teachers,
    distribution_time_limit, double_block_pairs, forced_by_pins,
    is_distribution_complete, lessons_every_day, open_class_subjects,
    open_coupling_groups, sek1_slot_numbers, timetable_time_limit,
    weekly_class_lessons,
)
from solver.pinning import PinnedLesson
from solver.scheduler import ScheduleSolver
from tests.test_solver import make_mini_school_data

STAGE_SECONDS = 10
MAX_BUFFER = 6
FLEXIBLE_TEACHER = "T10"
LOW_TARGET = 4.0
HIGH_TARGET = 9.0
DAYS = 5
SLOTS_PER_DAY = 7
MONDAY = 0
TUESDAY = 1
# 7a hat 34 Stunden: an jedem Tag die Stunden 1..6
FULL_CLASS = "7a"
FULL_CLASS_LESSONS = 34
# 5a hat 28 Stunden: ein freier Tag wäre möglich
SHORT_CLASS = "5a"
SPARE_TEACHER = "T11"
SPARE_HOURS = 4
RELI_TEACHERS = ("T08", "T09")
# Zweiter gemeinsamer Doppelblock: reli_5 und reli_7 brauchen beide
# T08 und T09, also je einen eigenen Block.
SECOND_BLOCK = {(TUESDAY, 5), (TUESDAY, 6)}


def _distribute(data: SchoolData, **options: object) -> DistributionResult:
    return distribute_teachers(data, STAGE_SECONDS, **options)


def _with_target(data: SchoolData, teacher_id: str, target: float):
    teachers = [
        t.model_copy(update={"deputat_soll": target})
        if t.id == teacher_id else t
        for t in data.teachers
    ]
    return data.model_copy(update={"teachers": teachers})


def _with_blocks(
    data: SchoolData, blocks: dict[str, list[tuple[int, int]]]
) -> SchoolData:
    """Kopie mit den Sperrzeiten aus `blocks` (Lehrkraft → Slots)."""
    teachers = [
        t.model_copy(update={"unavailable_slots": blocks[t.id]})
        if t.id in blocks else t
        for t in data.teachers
    ]
    return data.model_copy(update={"teachers": teachers})


def _free_only(free: set[tuple[int, int]]) -> list[tuple[int, int]]:
    """Sperrzeiten einer Lehrkraft, die nur in `free` unterrichten kann."""
    return [
        (day, hour)
        for day in range(DAYS)
        for hour in range(1, SLOTS_PER_DAY + 1)
        if (day, hour) not in free
    ]


def _whole_day(day: int) -> set[tuple[int, int]]:
    return {(day, hour) for hour in range(1, SLOTS_PER_DAY + 1)}


def _reli_teachers_free(
    first: set[tuple[int, int]], second: set[tuple[int, int]],
    subject_day_limit: bool = True,
) -> SchoolData:
    """Mini-Daten, in denen nur T08/T09 Religion/Ethik unterrichten
    können: T08 nur in `first`, T09 nur in `second`."""
    data = make_mini_school_data()
    solver_config = data.config.solver.model_copy(
        update={"subject_day_limit": subject_day_limit}
    )
    config = data.config.model_copy(update={"solver": solver_config})
    data = data.model_copy(update={"config": config})
    first_id, second_id = RELI_TEACHERS
    return _with_blocks(data, {
        first_id: _free_only(first), second_id: _free_only(second),
    })


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


class TestTimeHelpers:

    def test_default_grid_has_seven_sek1_lessons(self):
        grid = make_mini_school_data().config.time_grid
        assert sek1_slot_numbers(grid) == list(range(1, SLOTS_PER_DAY + 1))

    def test_double_blocks_inside_sek1(self):
        grid = make_mini_school_data().config.time_grid
        assert double_block_pairs(grid) == [(1, 2), (3, 4), (5, 6)]

    def test_weekly_lessons_include_couplings(self):
        data = make_mini_school_data()
        assert weekly_class_lessons(data)[FULL_CLASS] == FULL_CLASS_LESSONS

    def test_lessons_every_day(self):
        assert lessons_every_day(34, DAYS, SLOTS_PER_DAY) == 6
        assert lessons_every_day(32, DAYS, SLOTS_PER_DAY) == 4
        assert lessons_every_day(28, DAYS, SLOTS_PER_DAY) == 0
        assert lessons_every_day(20, DAYS, SLOTS_PER_DAY) == 0


class TestClassDayStart:

    def test_no_free_teacher_in_first_lesson_is_error(self):
        data = make_mini_school_data()
        blocked = _with_blocks(
            data, {t.id: [(MONDAY, 1)] for t in data.teachers}
        )

        with pytest.raises(DistributionError, match="Sperrzeiten"):
            _distribute(blocked)

    def test_only_free_teacher_gets_a_subject_of_the_class(self):
        # Zusätzliche Englisch-Lehrkraft mit Soll 4: das Ziel allein gäbe
        # ihr Englisch in 5a (4 Stunden) statt in 7a (3 Stunden).
        data = make_mini_school_data()
        spare = data.teachers[0].model_copy(update={
            "id": SPARE_TEACHER, "name": "Lang, Ute",
            "subjects": ["Englisch"], "deputat_min": 0,
            "deputat_max": SPARE_HOURS, "deputat_soll": float(SPARE_HOURS),
        })
        data = data.model_copy(update={"teachers": data.teachers + [spare]})
        blocked = _with_blocks(data, {
            t.id: [(MONDAY, 1)]
            for t in data.teachers if t.id != SPARE_TEACHER
        })

        result = _distribute(blocked)

        assert _teacher_of(result.data, FULL_CLASS, "Englisch") == (
            SPARE_TEACHER
        )

    def test_class_with_possible_free_day_is_not_restricted(self):
        # 5a allein: 28 Stunden passen in vier Tage, Montag darf leer sein
        data = make_mini_school_data()
        only_5a = data.model_copy(update={
            "classes": [c for c in data.classes if c.id == SHORT_CLASS],
            "couplings": [
                c for c in data.couplings
                if c.involved_class_ids == [SHORT_CLASS]
            ],
        })
        teachers = [
            t.model_copy(update={
                "deputat_min": 0, "unavailable_slots": [(MONDAY, 1)],
            })
            for t in data.teachers
        ]
        blocked = only_5a.model_copy(update={"teachers": teachers})

        assert lessons_every_day(
            weekly_class_lessons(blocked)[SHORT_CLASS], DAYS, SLOTS_PER_DAY
        ) == 0
        assert is_distribution_complete(_distribute(blocked).data)


class TestCouplingCapacity:

    def test_teachers_without_shared_free_lesson_are_error(self):
        data = _reli_teachers_free(
            _whole_day(MONDAY), _whole_day(TUESDAY)
        )

        with pytest.raises(DistributionError, match="INFEASIBLE"):
            _distribute(data)

    def test_two_shared_lessons_in_a_double_block_are_enough(self):
        data = _reli_teachers_free(
            _whole_day(MONDAY) | SECOND_BLOCK, {(MONDAY, 1), (MONDAY, 2)}
            | _whole_day(TUESDAY),
        )
        assert is_distribution_complete(_distribute(data).data)

    def test_two_shared_lessons_outside_a_block_break_day_limit(self):
        data = _reli_teachers_free(
            _whole_day(MONDAY), {(MONDAY, 2), (MONDAY, 3)}
            | _whole_day(TUESDAY),
        )

        with pytest.raises(DistributionError, match="INFEASIBLE"):
            _distribute(data)

    def test_without_day_limit_any_two_shared_lessons_are_enough(self):
        data = _reli_teachers_free(
            _whole_day(MONDAY) | SECOND_BLOCK, {(MONDAY, 2), (MONDAY, 3)}
            | _whole_day(TUESDAY),
            subject_day_limit=False,
        )
        assert is_distribution_complete(_distribute(data).data)

    def test_chosen_teacher_shares_free_lessons(self):
        data = _reli_teachers_free(
            _whole_day(MONDAY), _whole_day(TUESDAY)
        )
        third = data.teachers[0].model_copy(update={
            "id": SPARE_TEACHER, "name": "Lang, Ute",
            "subjects": ["Religion", "Ethik"], "deputat_min": 0,
            "unavailable_slots": [],
        })
        # T08/T09 dürfen leer ausgehen, sonst erzwingt das Deputat sie
        teachers = [
            t.model_copy(update={"deputat_min": 0})
            if t.id in RELI_TEACHERS else t
            for t in data.teachers
        ]
        data = data.model_copy(update={"teachers": teachers + [third]})

        result = _distribute(data)

        for coupling in result.data.couplings:
            chosen = {group.teacher_id for group in coupling.groups}
            assert SPARE_TEACHER in chosen


def _with_spare_reli_teachers(
    data: SchoolData, spare_ids: tuple[str, ...]
) -> SchoolData:
    """Zusätzliche Reli/Ethik-Lehrkräfte ohne Sperrzeiten; alle
    Reli-Lehrkräfte dürfen leer ausgehen."""
    template = data.teachers[0]
    spares = [
        template.model_copy(update={
            "id": spare_id, "name": f"Reserve, {spare_id}",
            "subjects": ["Religion", "Ethik"], "deputat_min": 0,
            "unavailable_slots": [],
        })
        for spare_id in spare_ids
    ]
    teachers = [
        t.model_copy(update={"deputat_min": 0})
        if t.id in RELI_TEACHERS else t
        for t in data.teachers
    ]
    return data.model_copy(update={"teachers": teachers + spares})


def _with_art_coupling(
    data: SchoolData, teacher_id: str, free: set[tuple[int, int]]
) -> SchoolData:
    """5a hat zusätzlich eine Kunst-Kopplung (2 h) bei `teacher_id`,
    der nur in `free` kann und sonst nichts unterrichtet."""
    template = data.teachers[0]
    teacher = template.model_copy(update={
        "id": teacher_id, "name": f"Kunst, {teacher_id}",
        "subjects": ["Kunst"], "deputat_min": 0,
        "unavailable_slots": _free_only(free),
    })
    art = Coupling(
        id="kunst_5", coupling_type="wpf", involved_class_ids=["5a"],
        groups=[CouplingGroup(
            group_name="kunst", subject="Kunst", hours_per_week=2,
            teacher_id=teacher_id,
        )],
        hours_per_week=2, cross_class=False,
    )
    return data.model_copy(update={
        "teachers": data.teachers + [teacher],
        "couplings": data.couplings + [art],
    })


def _fixed_coupling(
    data: SchoolData, coupling_id: str, teacher_ids: tuple[str, str]
) -> SchoolData:
    """Kopplung `coupling_id` mit fest vorgegebenen Lehrkräften."""
    couplings = []
    for coupling in data.couplings:
        if coupling.id == coupling_id:
            groups = [
                group.model_copy(update={"teacher_id": teacher_id})
                for group, teacher_id in zip(coupling.groups, teacher_ids)
            ]
            coupling = coupling.model_copy(update={"groups": groups})
        couplings.append(coupling)
    return data.model_copy(update={"couplings": couplings})


class TestCouplingTimetable:
    """Alle Kopplungen zusammen brauchen einen Plan ohne Überschneidung."""

    # T08 und T09 haben nur Mo 1-2 gemeinsam frei. Jede Kopplung passt
    # dort allein hinein, beide zusammen nicht (beide brauchen T08/T09).
    ONLY_SHARED = (
        {(MONDAY, 1), (MONDAY, 2)} | _whole_day(TUESDAY),
        {(MONDAY, 1), (MONDAY, 2)} | _whole_day(2),
    )

    def test_teacher_in_two_couplings_at_once_is_error(self):
        data = _reli_teachers_free(*self.ONLY_SHARED)

        with pytest.raises(DistributionError, match="INFEASIBLE"):
            _distribute(data)

    def test_spare_teachers_take_the_second_coupling(self):
        spares = (SPARE_TEACHER, "T12")
        data = _with_spare_reli_teachers(
            _reli_teachers_free(*self.ONLY_SHARED), spares
        )

        result = _distribute(data)

        # T08 und T09 können nur gemeinsam Mo 1-2: höchstens eine
        # Kopplung hat beide
        with_both = [
            coupling.id for coupling in result.data.couplings
            if set(RELI_TEACHERS)
            <= {g.teacher_id for g in coupling.groups}
        ]
        assert len(with_both) <= 1

    def test_class_in_two_couplings_at_once_is_error(self):
        only = {(MONDAY, 1), (MONDAY, 2)}
        spares = (SPARE_TEACHER, "T12")
        data = _with_spare_reli_teachers(
            _reli_teachers_free(only, only), spares
        )
        data = _fixed_coupling(data, "reli_5", RELI_TEACHERS)
        data = _fixed_coupling(data, "reli_7", spares)
        data = _with_art_coupling(data, "T13", only)

        with pytest.raises(DistributionError, match="INFEASIBLE"):
            _distribute(data)

    def test_class_couplings_at_different_times_are_fine(self):
        only = {(MONDAY, 1), (MONDAY, 2)}
        spares = (SPARE_TEACHER, "T12")
        data = _with_spare_reli_teachers(
            _reli_teachers_free(only, only), spares
        )
        data = _fixed_coupling(data, "reli_5", RELI_TEACHERS)
        data = _fixed_coupling(data, "reli_7", spares)
        data = _with_art_coupling(data, "T13", {(MONDAY, 3), (MONDAY, 4)})

        assert is_distribution_complete(_distribute(data).data)


class TestTimetableTimeLimit:
    """Zeitlimit des Stundenplans nach Stufe 1."""

    def test_rest_of_the_limit_is_left(self):
        assert timetable_time_limit(300, 60.4) == 240

    def test_never_below_the_floor(self):
        from solver.distribution import MIN_TIMETABLE_SECONDS

        assert timetable_time_limit(30, 29.0) == MIN_TIMETABLE_SECONDS
