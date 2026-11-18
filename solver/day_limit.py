"""Gemeinsame Hilfe für Regel C15 (ein Fach pro Tag: eine Stunde oder
ein Doppelblock), genutzt vom Stundenplan-Solver und von Stufe 1."""

from itertools import product

from config.schema import TimeGridConfig
from models.attendance_check import sek1_slot_numbers


def day_conflict_cliques(time_grid: TimeGridConfig) -> list[tuple[int, ...]]:
    """Slot-Mengen, aus denen ein Fach pro Tag höchstens einen belegt.

    Die Slots eines Tages zerfallen in Gruppen: jeder Doppelblock ist
    eine Zweiergruppe, jeder übrige Slot eine Einergruppe. Erlaubt sind
    nur Stunden innerhalb EINER Gruppe. Zwei Slots aus verschiedenen
    Gruppen schließen sich also aus; die größten solchen Mengen
    entstehen, indem man aus jeder Gruppe genau einen Slot wählt.
    Default-Raster (Blöcke 1-2, 3-4, 5-6, Einzelslot 7): 8 Cliquen.
    """
    slot_numbers = set(sek1_slot_numbers(time_grid))

    groups: list[tuple[int, ...]] = []
    grouped: set[int] = set()
    for block in time_grid.double_blocks:
        pair = (block.slot_first, block.slot_second)
        if slot_numbers.issuperset(pair) and grouped.isdisjoint(pair):
            groups.append(pair)
            grouped.update(pair)
    groups.extend((hour,) for hour in sorted(slot_numbers - grouped))

    return list(product(*groups))
