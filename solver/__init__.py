"""Solver-Modul (CP-SAT via Google OR-Tools)."""

from .scheduler import ScheduleSolver, ScheduleSolution, ScheduleEntry, TeacherAssignment
from .pinning import PinManager, PinnedLesson

__all__ = [
    "ScheduleSolver",
    "ScheduleSolution",
    "ScheduleEntry",
    "TeacherAssignment",
    "PinManager",
    "PinnedLesson",
]
