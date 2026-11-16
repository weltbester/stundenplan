"""Tests für das Zeitbudget des Solvers."""

import time

from solver.scheduler import ScheduleSolver
from solver.time_budget import (
    MAX_WARMSTART_SECONDS,
    MIN_PHASE_SECONDS,
    TimeBudget,
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
