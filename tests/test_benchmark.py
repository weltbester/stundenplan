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


class TestValidSeedSelection:
    """Ungültige Testdaten werden übersprungen und gemeldet."""

    @staticmethod
    def _factory(seed: int):
        """Mini-Daten; Seed 43 enthält eine unbekannte Lehrkraft."""
        from models.fixed_assignment import FixedAssignment

        data = make_mini_school_data()
        if seed != 43:
            return data
        broken = FixedAssignment(
            class_id="5a", subject="Deutsch", teacher_id="XXX"
        )
        return data.model_copy(update={"fixed_assignments": [broken]})

    def test_invalid_seed_is_skipped_with_note(self):
        from benchmarks.run_benchmark import collect_valid_datasets

        datasets, notes = collect_valid_datasets(self._factory, 3)
        assert [seed for seed, _ in datasets] == [42, 44, 45]
        assert len(notes) == 1
        assert notes[0].startswith("Seed 43 übersprungen")

    def test_failed_distribution_is_skipped_with_note(self):
        from benchmarks.assignment import AssignmentError
        from benchmarks.run_benchmark import collect_valid_datasets

        def factory(seed: int):
            if seed == 42:
                raise AssignmentError("keine Verteilung")
            return make_mini_school_data()

        datasets, notes = collect_valid_datasets(factory, 2)
        assert [seed for seed, _ in datasets] == [43, 44]
        assert notes == [
            "Seed 42 übersprungen (Daten ungültig): keine Verteilung"
        ]

    def test_notes_appear_in_markdown(self):
        text = render_markdown([_result()], "demo", ["Seed 43 übersprungen"])
        assert "- Seed 43 übersprungen" in text


class TestAssignTeachers:
    """Generator für eine vollständige Unterrichtsverteilung."""

    def test_every_class_subject_gets_exactly_one_teacher(self):
        from benchmarks.assignment import assign_teachers
        from models.fixed_assignment import coupling_subjects_by_class

        data = make_mini_school_data()
        assigned = assign_teachers(data, seed=42)
        covered = coupling_subjects_by_class(data.couplings)
        expected = {
            (c.id, subject)
            for c in data.classes
            for subject, hours in c.curriculum.items()
            if hours > 0 and subject not in covered.get(c.id, set())
        }
        pairs = [(a.class_id, a.subject) for a in assigned.fixed_assignments]
        assert set(pairs) == expected
        assert len(pairs) == len(expected)
        assert all(
            group.teacher_id
            for coupling in assigned.couplings
            for group in coupling.groups
        )

    def test_result_passes_the_feasibility_check(self):
        from benchmarks.assignment import assign_teachers

        assigned = assign_teachers(make_mini_school_data(), seed=42)
        report = assigned.validate_feasibility()
        assert report.is_feasible, report.errors

    def test_same_seed_gives_same_distribution(self):
        from benchmarks.assignment import assign_teachers

        first = assign_teachers(make_mini_school_data(), seed=7)
        second = assign_teachers(make_mini_school_data(), seed=7)
        assert first.fixed_assignments == second.fixed_assignments

    def test_original_data_is_not_modified(self):
        from benchmarks.assignment import assign_teachers

        data = make_mini_school_data()
        assign_teachers(data, seed=42)
        assert data.fixed_assignments == []
        assert all(
            group.teacher_id is None
            for coupling in data.couplings
            for group in coupling.groups
        )

    def test_load_respects_blocked_days_and_daily_maximum(self):
        """Seed 46: HOF darf nur 15h (3 + 6 + 6), nicht 17 freie Slots."""
        data = build_dataset("loose-36-fixed", 46)
        grid = data.config.time_grid
        hours = {
            (c.id, subject): value
            for c in data.classes
            for subject, value in c.curriculum.items()
        }
        load: dict[str, int] = {}
        for item in data.fixed_assignments:
            load[item.teacher_id] = (
                load.get(item.teacher_id, 0)
                + hours[(item.class_id, item.subject)]
            )
        for coupling in data.couplings:
            for group in coupling.groups:
                load[group.teacher_id] = (
                    load.get(group.teacher_id, 0) + group.hours_per_week
                )
        for teacher in data.teachers:
            capacity = teacher.teachable_hours(
                grid.days_per_week, grid.sek1_max_slot
            )
            assert load.get(teacher.id, 0) <= capacity, teacher.id

    def test_fixed_dataset_is_registered(self):
        assert "loose-36-fixed" in dataset_names()

    def test_fixed_dataset_returns_invalid_raw_data_unchanged(self):
        # Seed 45 erzeugt Daten ohne Latein-Lehrkraft.
        data = build_dataset("loose-36-fixed", 45)
        assert not data.validate_feasibility().is_feasible
        assert data.fixed_assignments == []
