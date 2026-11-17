"""Auswahl des Testdaten-Profils."""

from typing import Optional

from config.schema import SchoolConfig
from data.fake_data import FakeDataGenerator
from data.nrw_data import NrwDataGenerator
from models.school_data import SchoolData

# Bisherige Testdaten: alte Beispiel-Stundentafel, großzügig besetzt.
PROFILE_LOOSE = "loose"
# NRW-Gymnasium G9: Lehrkräfte nach Bedarf, knapp besetzt, Sek-II-Anteil.
PROFILE_NRW_G9 = "nrw-g9"
PROFILES: tuple[str, ...] = (PROFILE_LOOSE, PROFILE_NRW_G9)
DEFAULT_PROFILE = PROFILE_LOOSE


def generate_school_data(
    config: SchoolConfig,
    seed: Optional[int] = None,
    profile: str = DEFAULT_PROFILE,
) -> SchoolData:
    """Erzeugt Testdaten im gewählten Profil.

    Raises:
        ValueError: bei unbekanntem Profil.
    """
    if profile == PROFILE_LOOSE:
        return FakeDataGenerator(config, seed=seed).generate()
    if profile == PROFILE_NRW_G9:
        return NrwDataGenerator(config, seed=seed).generate()
    raise ValueError(
        f"Unbekanntes Profil '{profile}'. Erlaubt: {', '.join(PROFILES)}."
    )
