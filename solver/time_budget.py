"""Zeitbudget eines Solver-Laufs.

Das konfigurierte Zeitlimit gilt für den ganzen Lauf: Modellaufbau,
Warm-Start und Suche teilen sich dieselbe Uhr.
"""

import time
from typing import Callable

# Der Warm-Start bekommt höchstens diesen Anteil der verbleibenden Zeit …
WARMSTART_SHARE = 1 / 3
# … und nie mehr als so viele Sekunden.
MAX_WARMSTART_SECONDS = 90.0
# Untergrenze je Phase, damit der Solver auch dann noch arbeiten kann,
# wenn der Modellaufbau das Zeitlimit schon (fast) aufgebraucht hat.
MIN_PHASE_SECONDS = 5.0

Clock = Callable[[], float]


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
