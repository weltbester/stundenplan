"""Zeitbudget eines Solver-Laufs.

Das konfigurierte Zeitlimit gilt für den ganzen Lauf: Modellaufbau,
Warm-Start und Suche teilen sich dieselbe Uhr.
"""

import time
from typing import Callable, Optional

# Der Warm-Start bekommt höchstens diesen Anteil der verbleibenden Zeit …
WARMSTART_SHARE = 1 / 3
# … und nie mehr als so viele Sekunden.
MAX_WARMSTART_SECONDS = 90.0
# Untergrenze je Phase, damit der Solver auch dann noch arbeiten kann,
# wenn der Modellaufbau das Zeitlimit schon (fast) aufgebraucht hat.
MIN_PHASE_SECONDS = 5.0

# Zeitlimit "nach Schulgröße" (Feld time_limit_seconds leer): Sekunden
# je Klasse, nie weniger als die Untergrenze. Gemessen (Benchmark-Leiter
# 2026-11-18): 18 und 30 Klassen bestehen mit 300 s, 36 Klassen brauchen
# 450 s.
SECONDS_PER_CLASS = 12.5
MIN_AUTO_LIMIT_SECONDS = 300
# Obergrenze, gleich dem Maximum von SolverConfig.time_limit_seconds.
MAX_LIMIT_SECONDS = 3600

Clock = Callable[[], float]


def recommended_time_limit(num_classes: int) -> int:
    """Zeitlimit in Sekunden für eine Schule mit `num_classes` Klassen."""
    seconds = round(num_classes * SECONDS_PER_CLASS)
    return min(MAX_LIMIT_SECONDS, max(MIN_AUTO_LIMIT_SECONDS, seconds))


def effective_time_limit(configured: Optional[int], num_classes: int) -> int:
    """Das konfigurierte Zeitlimit, ohne Angabe das nach Schulgröße."""
    if configured is None:
        return recommended_time_limit(num_classes)
    return configured


def describe_time_limit(configured: Optional[int]) -> str:
    """Zeitlimit für die Anzeige: "300s" oder "nach Schulgröße"."""
    if configured is None:
        return "nach Schulgröße"
    return f"{configured}s"


def short_time_limit_hint(
    configured: Optional[int], num_classes: int
) -> Optional[str]:
    """Hinweistext, wenn ein festes Zeitlimit unter dem nach Schulgröße
    liegt; sonst None."""
    recommended = recommended_time_limit(num_classes)
    if configured is None or configured >= recommended:
        return None
    return (
        f"Das Zeitlimit {configured}s liegt unter dem Wert für "
        f"{num_classes} Klassen ({recommended}s); der Plan wird "
        f"meist schlechter. Abhilfe: --time-limit {recommended} oder "
        f"time_limit_seconds leer lassen (Zeitlimit nach Schulgröße)."
    )


class TimeBudget:
    """Verteilt ein Zeitlimit auf die Phasen eines Solver-Laufs."""

    def __init__(
        self, limit_seconds: float, clock: Clock = time.monotonic
    ) -> None:
        self._limit = float(limit_seconds)
        self._clock = clock
        self._started_at = clock()

    @property
    def limit_seconds(self) -> float:
        """Das Zeitlimit für den ganzen Lauf."""
        return self._limit

    def elapsed(self) -> float:
        """Sekunden seit Beginn des Laufs."""
        return self._clock() - self._started_at

    def is_exhausted(self) -> bool:
        """True, wenn das Zeitlimit bereits aufgebraucht ist."""
        return self.elapsed() >= self._limit

    def remaining(self) -> float:
        """Verbleibende Sekunden, mindestens `MIN_PHASE_SECONDS`."""
        return max(MIN_PHASE_SECONDS, self._limit - self.elapsed())

    def warmstart_limit(self) -> float:
        """Zeitlimit für den Warm-Start (Suche ohne Zielfunktion)."""
        share = self.remaining() * WARMSTART_SHARE
        return max(MIN_PHASE_SECONDS, min(MAX_WARMSTART_SECONDS, share))
