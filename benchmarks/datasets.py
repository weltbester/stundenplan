"""Benchmark-Datensätze: Name → Fabrik, die SchoolData erzeugt."""

from types import MappingProxyType
from typing import Callable, Mapping

from benchmarks.assignment import assign_teachers
from config.defaults import default_school_config
from data.fake_data import FakeDataGenerator
from models.school_data import SchoolData

DatasetFactory = Callable[[int], SchoolData]


def _loose_36(seed: int) -> SchoolData:
    """Default-Schule: 36 Klassen, 60 Lehrkräfte, großzügiges Deputat."""
    generator = FakeDataGenerator(default_school_config(), seed=seed)
    return generator.generate()


def _loose_36_fixed(seed: int) -> SchoolData:
    """Wie loose-36, aber mit vollständig vorgegebener Unterrichtsverteilung.

    Ungültige Rohdaten (z.B. ein Fach ohne Lehrkraft) kommen unverändert
    zurück: der Benchmark überspringt sie dann mit der eigentlichen Ursache.
    """
    raw = _loose_36(seed)
    if not raw.validate_feasibility().is_feasible:
        return raw
    return assign_teachers(raw, seed)


DATASETS: Mapping[str, DatasetFactory] = MappingProxyType({
    "loose-36": _loose_36,
    "loose-36-fixed": _loose_36_fixed,
})


def dataset_names() -> list[str]:
    """Alle verfügbaren Datensatz-Namen (sortiert)."""
    return sorted(DATASETS)


def build_dataset(name: str, seed: int) -> SchoolData:
    """Erzeugt den Datensatz `name` reproduzierbar mit `seed`."""
    if name not in DATASETS:
        known = ", ".join(dataset_names())
        raise KeyError(f"Unbekannter Datensatz '{name}'. Bekannt: {known}")
    return DATASETS[name](seed)
