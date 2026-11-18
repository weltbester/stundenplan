"""Tests für das Zeitbudget des Solvers."""

import time

from main import _resolve_time_limit
from solver import time_budget
from solver.scheduler import ScheduleSolver
from solver.time_budget import (
    MAX_LIMIT_SECONDS,
    MAX_WARMSTART_SECONDS,
    MIN_AUTO_LIMIT_SECONDS,
    MIN_PHASE_SECONDS,
    TimeBudget,
    describe_time_limit,
    effective_time_limit,
    recommended_time_limit,
    short_time_limit_hint,
)
from tests.test_solver import make_mini_school_data

LIMIT = 300.0
BUILD_SECONDS = 60.0
SLOW_BUILD_SECONDS = 2.0
SHORT_LIMIT = 12


class FakeClock:
    """Uhr, die der Test von Hand vorstellt."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestTimeBudget:
    """TimeBudget: ein Limit für Aufbau, Warm-Start und Suche."""

    def test_remaining_shrinks_with_elapsed_time(self):
        clock = FakeClock()
        budget = TimeBudget(LIMIT, clock)
        clock.advance(BUILD_SECONDS)

        assert budget.elapsed() == BUILD_SECONDS
        assert budget.remaining() == LIMIT - BUILD_SECONDS
        assert not budget.is_exhausted()

    def test_warmstart_gets_a_third_of_the_rest(self):
        clock = FakeClock()
        budget = TimeBudget(LIMIT, clock)
        clock.advance(BUILD_SECONDS)

        assert budget.warmstart_limit() == (LIMIT - BUILD_SECONDS) / 3

    def test_warmstart_is_capped(self):
        budget = TimeBudget(10 * LIMIT, FakeClock())

        assert budget.warmstart_limit() == MAX_WARMSTART_SECONDS

    def test_phases_sum_to_the_limit(self):
        clock = FakeClock()
        budget = TimeBudget(LIMIT, clock)
        clock.advance(BUILD_SECONDS)
        warmstart = budget.warmstart_limit()
        clock.advance(warmstart)

        assert BUILD_SECONDS + warmstart + budget.remaining() == LIMIT

    def test_floor_when_build_used_up_the_limit(self):
        clock = FakeClock()
        budget = TimeBudget(LIMIT, clock)
        clock.advance(LIMIT + BUILD_SECONDS)

        assert budget.is_exhausted()
        assert budget.remaining() == MIN_PHASE_SECONDS
        assert budget.warmstart_limit() == MIN_PHASE_SECONDS


class SlowBuildSolver(ScheduleSolver):
    """Solver, dessen Modellaufbau künstlich länger dauert."""

    def _add_constraints(self) -> None:
        super()._add_constraints()
        time.sleep(SLOW_BUILD_SECONDS)


class TestSolverUsesBudget:
    """solve() zieht Aufbau und Warm-Start vom Zeitlimit ab."""

    def test_search_limit_excludes_build_time(self):
        data = make_mini_school_data()
        data.config.solver.time_limit_seconds = SHORT_LIMIT
        solver = SlowBuildSolver(data)

        solution = solver.solve()

        assert solution.solver_status in ("OPTIMAL", "FEASIBLE")
        assert solver.search_limit_seconds is not None
        assert (
            solver.search_limit_seconds
            <= SHORT_LIMIT - SLOW_BUILD_SECONDS
        )

    def test_reported_time_covers_the_whole_run(self):
        data = make_mini_school_data()
        data.config.solver.time_limit_seconds = SHORT_LIMIT
        solver = SlowBuildSolver(data)

        solution = solver.solve()

        assert solution.solve_time_seconds >= SLOW_BUILD_SECONDS


class TestRecommendedTimeLimit:
    """Zeitlimit nach Schulgröße: 12,5 s je Klasse, mindestens 300 s."""

    def test_small_school_gets_the_floor(self):
        assert recommended_time_limit(18) == MIN_AUTO_LIMIT_SECONDS
        assert recommended_time_limit(0) == MIN_AUTO_LIMIT_SECONDS

    def test_grows_with_the_number_of_classes(self):
        assert recommended_time_limit(30) == 375
        assert recommended_time_limit(36) == 450

    def test_is_capped(self):
        assert recommended_time_limit(1000) == MAX_LIMIT_SECONDS

    def test_empty_config_uses_school_size(self):
        assert effective_time_limit(None, 36) == 450

    def test_explicit_limit_wins(self):
        assert effective_time_limit(SHORT_LIMIT, 36) == SHORT_LIMIT
        assert effective_time_limit(600, 18) == 600


class TestShortTimeLimitHint:
    """Hinweis nur bei einem festen Limit unter dem nach Schulgröße."""

    def test_hint_names_the_recommended_limit(self):
        hint = short_time_limit_hint(300, 36)

        assert hint is not None
        assert "450s" in hint
        assert "--time-limit 450" in hint

    def test_no_hint_when_limit_is_enough(self):
        assert short_time_limit_hint(450, 36) is None
        assert short_time_limit_hint(300, 18) is None

    def test_no_hint_without_a_fixed_limit(self):
        assert short_time_limit_hint(None, 36) is None

    def test_description(self):
        assert describe_time_limit(None) == "nach Schulgröße"
        assert describe_time_limit(SHORT_LIMIT) == f"{SHORT_LIMIT}s"


class TestSolverWithoutFixedLimit:
    """Ohne festes Zeitlimit nimmt solve() das nach Schulgröße."""

    def test_empty_limit_uses_school_size(self, monkeypatch):
        monkeypatch.setattr(time_budget, "SECONDS_PER_CLASS", 0.0)
        monkeypatch.setattr(
            time_budget, "MIN_AUTO_LIMIT_SECONDS", SHORT_LIMIT
        )
        data = make_mini_school_data()
        data.config.solver.time_limit_seconds = None
        solver = ScheduleSolver(data)

        solution = solver.solve()

        assert solution.solver_status in ("OPTIMAL", "FEASIBLE")
        assert solver.search_limit_seconds is not None
        assert solver.search_limit_seconds <= SHORT_LIMIT


class TestResolveTimeLimit:
    """main.py solve: leeres Limit wird gesetzt, zu kurzes gemeldet."""

    def test_empty_limit_is_set_from_school_size(self, capsys):
        data = make_mini_school_data()
        data.config.solver.time_limit_seconds = None

        _resolve_time_limit(data)

        expected = recommended_time_limit(len(data.classes))
        assert data.config.solver.time_limit_seconds == expected
        assert "nach Schulgröße" in capsys.readouterr().out

    def test_short_fixed_limit_stays_and_gives_a_hint(self, capsys):
        data = make_mini_school_data()
        data.config.solver.time_limit_seconds = SHORT_LIMIT

        _resolve_time_limit(data)

        assert data.config.solver.time_limit_seconds == SHORT_LIMIT
        assert "Hinweis" in capsys.readouterr().out

    def test_enough_fixed_limit_gives_no_hint(self, capsys):
        data = make_mini_school_data()
        data.config.solver.time_limit_seconds = MAX_LIMIT_SECONDS

        _resolve_time_limit(data)

        assert "Hinweis" not in capsys.readouterr().out
