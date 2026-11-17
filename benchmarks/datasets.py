"""Benchmark-Datensätze: Name → Fabrik, die SchoolData erzeugt.

Namen mit `-fixed` und `long-day-36` enthalten eine vollständig
vorgegebene Unterrichtsverteilung (wie an einer echten Schule). Ohne
`-fixed` wählt das Programm die Lehrkräfte selbst (Stufe 1).
"""

from types import MappingProxyType
from typing import Callable, Mapping

from benchmarks.assignment import assign_teachers
from config.defaults import default_school_config
from config.nrw_g9 import STUNDENTAFEL_NRW_G9
from config.schema import DoubleBlock, SchoolConfig
from data.fake_data import CurriculumTable, FakeDataGenerator
from data.nrw_data import SUPPORT_SUBJECT, NrwDataGenerator
from models.school_data import SchoolData

DatasetFactory = Callable[[int], SchoolData]

# Parallelklassen je Jahrgang (Jg. 5–10) der Stufen der Benchmark-Leiter.
NRW_PARALLEL_CLASSES: Mapping[str, int] = MappingProxyType({
    "nrw-18": 3,
    "nrw-30": 5,
    "nrw-36": 6,
})
FIXED_SUFFIX = "-fixed"

# Frühwarn-Datensatz "long-day-36": 8 Sek-I-Stunden am Tag und mehr
# Wochenstunden je Klasse, sonst wie nrw-36 (keine neuen Regeln).
LONG_DAY_NAME = "long-day-36"
LONG_DAY_PARALLEL_CLASSES = 6
LONG_DAY_LAST_SLOT = 8
# Zusätzliche Wochenstunden je Klasse gegenüber NRW G9 (30/32 → 34/36).
LONG_DAY_EXTRA_HOURS: Mapping[str, int] = MappingProxyType({
    "Deutsch": 1,
    "Mathematik": 1,
    "Englisch": 1,
    SUPPORT_SUBJECT: 1,
})


def _loose_36(seed: int) -> SchoolData:
    """Default-Schule: 36 Klassen, 60 Lehrkräfte, großzügiges Deputat."""
    generator = FakeDataGenerator(default_school_config(), seed=seed)
    return generator.generate()


def with_given_distribution(raw: SchoolData, seed: int) -> SchoolData:
    """`raw` mit vollständig vorgegebener Unterrichtsverteilung.

    Ungültige Rohdaten (z.B. ein Fach ohne Lehrkraft) kommen unverändert
    zurück: der Benchmark überspringt sie dann mit der eigentlichen Ursache.
    """
    if not raw.validate_feasibility().is_feasible:
        return raw
    return assign_teachers(raw, seed)


def _loose_36_fixed(seed: int) -> SchoolData:
    """Wie loose-36, aber mit vorgegebener Unterrichtsverteilung."""
    return with_given_distribution(_loose_36(seed), seed)


def nrw_school_config(parallel_classes: int) -> SchoolConfig:
    """Default-Schule mit `parallel_classes` Klassen in jedem Jahrgang."""
    config = default_school_config()
    grades = config.grades.model_copy(update={
        "grades": [
            grade.model_copy(update={"num_classes": parallel_classes})
            for grade in config.grades.grades
        ],
    })
    return config.model_copy(update={"grades": grades})


def long_day_config() -> SchoolConfig:
    """36 Klassen, Stunde 8 gehört zur Sek I, Doppelblock 7–8."""
    config = nrw_school_config(LONG_DAY_PARALLEL_CLASSES)
    grid = config.time_grid
    slots = [
        slot.model_copy(update={"is_sek2_only": False})
        if slot.slot_number <= LONG_DAY_LAST_SLOT else slot
        for slot in grid.lesson_slots
    ]
    blocks = list(grid.double_blocks) + [
        DoubleBlock(
            slot_first=LONG_DAY_LAST_SLOT - 1,
            slot_second=LONG_DAY_LAST_SLOT,
        ),
    ]
    time_grid = grid.model_copy(update={
        "lesson_slots": slots,
        "double_blocks": blocks,
        "sek1_max_slot": LONG_DAY_LAST_SLOT,
    })
    return config.model_copy(update={"time_grid": time_grid})


def long_day_curriculum() -> CurriculumTable:
    """NRW-G9-Tafel plus `LONG_DAY_EXTRA_HOURS` in jedem Jahrgang."""
    table: CurriculumTable = {}
    for grade, subjects in STUNDENTAFEL_NRW_G9.items():
        extended = dict(subjects)
        for subject, extra in LONG_DAY_EXTRA_HOURS.items():
            extended[subject] = extended.get(subject, 0) + extra
        table[grade] = extended
    return table


def _nrw_factory(parallel_classes: int, given: bool) -> DatasetFactory:
    """Fabrik für das Profil nrw-g9 mit `parallel_classes` je Jahrgang."""

    def factory(seed: int) -> SchoolData:
        config = nrw_school_config(parallel_classes)
        raw = NrwDataGenerator(config, seed=seed).generate()
        return with_given_distribution(raw, seed) if given else raw

    return factory


def _long_day_36(seed: int) -> SchoolData:
    """Langer Tag: 8 Stunden, 34–36 Wochenstunden, vorgegebene Verteilung."""
    raw = NrwDataGenerator(
        long_day_config(), seed=seed, curriculum=long_day_curriculum()
    ).generate()
    return with_given_distribution(raw, seed)


def _nrw_datasets() -> dict[str, DatasetFactory]:
    datasets: dict[str, DatasetFactory] = {}
    for name, parallel in NRW_PARALLEL_CLASSES.items():
        datasets[name] = _nrw_factory(parallel, given=False)
        datasets[name + FIXED_SUFFIX] = _nrw_factory(parallel, given=True)
    return datasets


DATASETS: Mapping[str, DatasetFactory] = MappingProxyType({
    "loose-36": _loose_36,
    "loose-36-fixed": _loose_36_fixed,
    **_nrw_datasets(),
    LONG_DAY_NAME: _long_day_36,
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
