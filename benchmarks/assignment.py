"""Erzeugt eine vollständige Unterrichtsverteilung für Benchmark-Daten.

Echte Schulen legen die Verteilung vor der Stundenplanung fest. Für
generierte Testdaten übernimmt das die Stufe 1 des Programms
(`solver/distribution.py`), hier ohne Soll-Ziel und mit festem Seed,
damit jeder Lauf dieselbe Verteilung liefert.
"""

from models.school_data import SchoolData
from solver.distribution import DistributionError, distribute_teachers

ASSIGNMENT_TIME_LIMIT_SECONDS = 60
# Ein Worker + fester Seed → dieselbe Verteilung bei jedem Lauf.
ASSIGNMENT_WORKERS = 1

# Für den Datensatz wurde keine Unterrichtsverteilung gefunden.
AssignmentError = DistributionError


def assign_teachers(data: SchoolData, seed: int) -> SchoolData:
    """Kopie von `data` mit vollständig vorgegebener Unterrichtsverteilung."""
    return distribute_teachers(
        data,
        ASSIGNMENT_TIME_LIMIT_SECONDS,
        balance_targets=False,
        seed=seed,
        num_workers=ASSIGNMENT_WORKERS,
    ).data
