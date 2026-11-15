"""Tests für den Entwickler-Benchmark (benchmarks/)."""

import csv
import logging
from pathlib import Path

import pytest

from benchmarks.datasets import build_dataset, dataset_names
from benchmarks.report import (
    MISSING, render_markdown, summarize, write_csv, write_markdown,
)
from benchmarks.runner import (
    SOLVER_LOGGER_NAME, RunResult, capture_solver_log,
    count_bunched_subject_days, late_gain_percent, run_once,
)
from solver.scheduler import ScheduleEntry, ScheduleSolution
from tests.test_solver import make_mini_config, make_mini_school_data

MINI_TIME_LIMIT = 10
TIME_LIMIT = 100.0


def _result(**overrides: object) -> RunResult:
    """Erzeugt ein gelöstes RunResult mit überschreibbaren Feldern."""
    values: dict[str, object] = {
        "dataset": "demo", "seed": 42, "num_classes": 2,
        "num_teachers": 10, "status": "FEASIBLE",
        "num_variables": 100, "num_constraints": 200,
        "build_seconds": 1.5, "warmstart_seconds": 2.0,
        "total_seconds": 30.0, "solutions_found": 4,
        "objective": 1234.0, "late_gain_percent": 5.0,
        "total_gaps": 3, "bunched_subject_days": 1,
        "validator_errors": 0, "validator_warnings": 0,
    }
    values.update(overrides)
    return RunResult(**values)


def _entry(
    class_id: str, subject: str, day: int, slot: int,
    is_coupling: bool = False,
) -> ScheduleEntry:
    return ScheduleEntry(
        day=day, slot_number=slot, teacher_id="T01",
        class_id=class_id, subject=subject, is_coupling=is_coupling,
    )


def _solution(entries: list[ScheduleEntry]) -> ScheduleSolution:
    return ScheduleSolution(
        entries=entries, assignments=[], solver_status="FEASIBLE",
        solve_time_seconds=1.0, num_variables=0, num_constraints=0,
        config_snapshot=make_mini_config(),
    )


class TestLateGain:
    """late_gain_percent: wie viel Verbesserung kam erst am Ende?"""

    def test_fewer_than_two_solutions_gives_none(self):
        assert late_gain_percent([], TIME_LIMIT) is None
        assert late_gain_percent([(1.0, 500.0)], TIME_LIMIT) is None

    def test_converged_before_window_gives_zero(self):
        trace = [(1.0, 1000.0), (50.0, 400.0)]
        assert late_gain_percent(trace, TIME_LIMIT) == 0.0

    def test_half_of_gain_in_window(self):
        trace = [(1.0, 1000.0), (70.0, 600.0), (95.0, 200.0)]
        assert late_gain_percent(trace, TIME_LIMIT) == 50.0

    def test_all_solutions_inside_window_gives_hundred(self):
        trace = [(90.0, 1000.0), (95.0, 900.0)]
        assert late_gain_percent(trace, TIME_LIMIT) == 100.0

    def test_no_improvement_gives_zero(self):
        trace = [(1.0, 500.0), (95.0, 500.0)]
        assert late_gain_percent(trace, TIME_LIMIT) == 0.0

    def test_negative_objectives(self):
        trace = [(1.0, 100.0), (50.0, -100.0), (99.0, -300.0)]
        assert late_gain_percent(trace, TIME_LIMIT) == 50.0


class TestBunchedSubjectDays:
    """count_bunched_subject_days: Häufungen eines Fachs an einem Tag."""

    def test_three_lessons_same_day_counts_once(self):
        entries = [_entry("5a", "Mathematik", 0, s) for s in (1, 2, 3)]
        assert count_bunched_subject_days(_solution(entries)) == 1

    def test_double_lesson_is_not_bunched(self):
        entries = [_entry("5a", "Mathematik", 0, s) for s in (1, 2)]
        assert count_bunched_subject_days(_solution(entries)) == 0

    def test_spread_over_days_is_not_bunched(self):
        entries = [_entry("5a", "Mathematik", d, 1) for d in range(4)]
        assert count_bunched_subject_days(_solution(entries)) == 0

    def test_coupling_entries_are_ignored(self):
        entries = [
            _entry("5a", "Religion", 0, 1, is_coupling=True)
            for _ in range(3)
        ]
        assert count_bunched_subject_days(_solution(entries)) == 0


class TestSolverLogCapture:
    """Mitschnitt der Solver-Meldungen."""

    def test_parses_solution_and_warmstart_lines(self):
        solver_logger = logging.getLogger(SOLVER_LOGGER_NAME)
        with capture_solver_log() as capture:
            solver_logger.info(
                "Warm-Start: feasible Lösung in 18.4s gefunden – setze Hints"
            )
            solver_logger.info("  Lösung #1 | Zeit: 2.5s | Obj: 900")
            solver_logger.info("  Lösung #2 | Zeit: 7.0s | Obj: -40")
            solver_logger.info("Solver beendet: FEASIBLE")
        assert capture.warmstart_seconds == 18.4
        assert capture.trace == [(2.5, 900.0), (7.0, -40.0)]

    def test_handler_is_removed_afterwards(self):
        solver_logger = logging.getLogger(SOLVER_LOGGER_NAME)
        handlers_before = list(solver_logger.handlers)
        level_before = solver_logger.level
        with capture_solver_log():
            pass
        assert solver_logger.handlers == handlers_before
        assert solver_logger.level == level_before


class TestDatasets:
    """Datensatz-Register."""

    def test_loose_36_is_registered(self):
        assert "loose-36" in dataset_names()

    def test_loose_36_has_36_classes_and_is_reproducible(self):
        first = build_dataset("loose-36", seed=42)
        second = build_dataset("loose-36", seed=42)
        assert len(first.classes) == 36
        assert [t.id for t in first.teachers] == [
            t.id for t in second.teachers
        ]

    def test_unknown_dataset_raises(self):
        with pytest.raises(KeyError, match="Unbekannter Datensatz"):
            build_dataset("gibt-es-nicht", seed=42)


class TestReport:
    """Markdown- und CSV-Ausgabe."""

    def test_markdown_contains_one_row_per_result(self):
        results = [_result(seed=42), _result(seed=43)]
        text = render_markdown(results, "demo")
        rows = [line for line in text.splitlines() if "| demo |" in line]
        assert len(rows) == 2
        assert "Gelöst: 2/2" in text

    def test_unsolved_run_shows_missing_marker(self):
        unsolved = _result(
            status="UNKNOWN", warmstart_seconds=None, objective=None,
            late_gain_percent=None, total_gaps=None,
            bunched_subject_days=None, validator_errors=None,
        )
        text = render_markdown([unsolved], "demo")
        assert MISSING in text
        assert "Gelöst: 0/1" in summarize([unsolved])

    def test_files_are_written(self, tmp_path: Path):
        results = [_result()]
        markdown_path = tmp_path / "sub" / "run.md"
        csv_path = tmp_path / "sub" / "run.csv"
        write_markdown(results, "demo", markdown_path)
        write_csv(results, csv_path)

        assert markdown_path.read_text(encoding="utf-8").startswith(
            "# Benchmark: demo"
        )
        with open(csv_path, encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 1
        assert rows[0]["status"] == "FEASIBLE"
        assert rows[0]["seed"] == "42"


class TestRunOnce:
    """Ein echter Solver-Lauf auf dem Mini-Datensatz."""

    def test_mini_run_produces_complete_metrics(self):
        data = make_mini_school_data()
        result = run_once("mini", 42, data, MINI_TIME_LIMIT)

        assert result.is_solved, f"Status: {result.status}"
        assert result.num_classes == 2
        assert result.num_variables > 0
        assert result.num_constraints > 0
        assert result.build_seconds >= 0
        assert result.warmstart_seconds is not None
        assert result.validator_errors == 0
        assert result.total_gaps is not None
        assert result.bunched_subject_days is not None
