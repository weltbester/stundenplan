"""Benchmark-Datensätze: Name → Fabrik, die SchoolData erzeugt."""

from types import MappingProxyType
from typing import Callable, Mapping

from config.defaults import default_school_config
from data.fake_data import FakeDataGenerator
from models.school_data import SchoolData

DatasetFactory = Callable[[int], SchoolData]


def _loose_36(seed: int) -> SchoolData:
    """Default-Schule: 36 Klassen, 60 Lehrkräfte, großzügiges Deputat."""
    generator = FakeDataGenerator(default_school_config(), seed=seed)
    return generator.generate()


DATASETS: Mapping[str, DatasetFactory] = MappingProxyType({
    "loose-36": _loose_36,
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
