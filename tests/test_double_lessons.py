"""Tests für Regel C9: Fächer mit Doppelstunden-Pflicht.

Gerade Stundenzahl: nur Doppelstunden in den Blöcken. Ungerade: N // 2
Doppelstunden und eine Einzelstunde in einem beliebigen Slot, nicht an
einem Tag mit Doppelstunde dieses Fachs.
"""

import pytest

from config.defaults import default_rooms, default_time_grid
from config.schema import (
    CouplingConfig, GradeConfig, GradeDefinition, SchoolConfig, SchoolType,
    SolverConfig,
)
from data.fake_data import FakeDataGenerator
from models.school_data import SchoolData
from models.subject import default_subjects
from models.teacher import Teacher
from solver.scheduler import ScheduleEntry, ScheduleSolution, ScheduleSolver

SUBJECT = "Chemie"   # Doppelstunden-Pflicht laut Vorschlagsliste
TEACHER_ID = "CHE"
GRADE = 10
SOLVED = ("OPTIMAL", "FEASIBLE")
# Slot außerhalb aller Doppelblöcke im Standard-Raster
SINGLE_ONLY_SLOT = 7
OTHER_SUBJECT = "Deutsch"
OTHER_TEACHER_ID = "DEU"
OTHER_HOURS = 4
DAYS = 5


def _school_data(
    hours: int,
    num_classes: int,
    subject_day_limit: bool = True,
    with_other_subject: bool = False,
    block_single_only_slot: bool = False,
) -> SchoolData:
    config = SchoolConfig(
        school_name="C9-Test",
        school_type=SchoolType.GYMNASIUM,
        bundesland="NRW",
        time_grid=default_time_grid(),
        grades=GradeConfig(grades=[
            GradeDefinition(grade=GRADE, num_classes=num_classes),
        ]),
        rooms=default_rooms(),
        couplings=CouplingConfig(reli_ethik_enabled=False, wpf_enabled=False),
        solver=SolverConfig(
            time_limit_seconds=30, num_workers=4,
            subject_day_limit=subject_day_limit,
        ),
    )
    table = {SUBJECT: hours}
    teachers = [Teacher(
        id=TEACHER_ID, name="Test, Chemie", subjects=[SUBJECT],
        deputat_max=hours * num_classes, deputat_min=1,
        unavailable_slots=(
            [(day, SINGLE_ONLY_SLOT) for day in range(DAYS)]
            if block_single_only_slot else []
        ),
    )]
    if with_other_subject:
        table[OTHER_SUBJECT] = OTHER_HOURS
        teachers.append(Teacher(
            id=OTHER_TEACHER_ID, name="Test, Deutsch",
            subjects=[OTHER_SUBJECT],
            deputat_max=OTHER_HOURS * num_classes, deputat_min=1,
        ))
    generator = FakeDataGenerator(config, curriculum={GRADE: table})
    return SchoolData(
        subjects=default_subjects(), rooms=generator.generate_rooms(),
        classes=generator.generate_classes(), teachers=teachers,
        couplings=[], config=config,
    )


def _solve(data: SchoolData) -> ScheduleSolution:
    return ScheduleSolver(data).solve(use_soft=False)


def _block_pairs(data: SchoolData) -> set[tuple[int, int]]:
    grid = data.config.time_grid
    return {
        (block.slot_first, block.slot_second)
        for block in grid.double_blocks
        if block.slot_second <= grid.sek1_max_slot
    }


def _split(
    entries: list[ScheduleEntry], pairs: set[tuple[int, int]]
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """(Doppelstunden, Einzelstunden) einer Klasse als (Tag, erster Slot)."""
    by_day: dict[int, set[int]] = {}
    for entry in entries:
        by_day.setdefault(entry.day, set()).add(entry.slot_number)
    doubles: list[tuple[int, int]] = []
    singles: list[tuple[int, int]] = []
    for day, slots in by_day.items():
        rest = set(slots)
        for first, second in sorted(pairs):
            if {first, second} <= rest:
                doubles.append((day, first))
                rest -= {first, second}
        singles.extend((day, slot) for slot in sorted(rest))
    return doubles, singles


def _class_entries(solution: ScheduleSolution, class_id: str) -> list:
    return [e for e in solution.entries if e.class_id == class_id]


class TestOddHours:

    def test_single_lesson_is_not_limited_to_slot_7(self):
        """Bis Version 1.1 nur in Slot 7 möglich: hier ist er gesperrt."""
        data = _school_data(
            hours=1, num_classes=1, with_other_subject=True,
            block_single_only_slot=True,
        )
        solution = _solve(data)
        assert solution.solver_status in SOLVED
        chemistry = [e for e in solution.entries if e.subject == SUBJECT]
        assert len(chemistry) == 1
        assert chemistry[0].slot_number != SINGLE_ONLY_SLOT

    @pytest.mark.parametrize("hours", [3, 5])
    def test_doubles_plus_one_single_on_another_day(self, hours: int):
        data = _school_data(hours=hours, num_classes=1)
        solution = _solve(data)
        assert solution.solver_status in SOLVED
        doubles, singles = _split(
            _class_entries(solution, "10a"), _block_pairs(data)
        )
        assert len(doubles) == hours // 2
        assert len(singles) == 1
        double_days = {day for day, _ in doubles}
        assert singles[0][0] not in double_days

    def test_single_stays_off_double_days_without_c15(self):
        data = _school_data(hours=5, num_classes=1, subject_day_limit=False)
        solution = _solve(data)
        assert solution.solver_status in SOLVED
        doubles, singles = _split(
            _class_entries(solution, "10a"), _block_pairs(data)
        )
        assert len(doubles) == 2 and len(singles) == 1
        assert singles[0][0] not in {day for day, _ in doubles}


class TestEvenHours:

    @pytest.mark.parametrize("hours", [2, 4])
    def test_only_block_pairs(self, hours: int):
        data = _school_data(hours=hours, num_classes=1)
        solution = _solve(data)
        assert solution.solver_status in SOLVED
        doubles, singles = _split(
            _class_entries(solution, "10a"), _block_pairs(data)
        )
        assert singles == []
        assert len(doubles) == hours // 2
        assert SINGLE_ONLY_SLOT not in {
            entry.slot_number for entry in solution.entries
        }
