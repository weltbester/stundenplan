"""Benchmark-Leiter und Abnahme-Kriterien (Schritt 4e).

Die Leiter hat drei Stufen (18, 30, 36 Klassen im Profil nrw-g9). Je
Stufe zählt für die Abnahme nur der Datensatz mit vorgegebener
Unterrichtsverteilung; der Datensatz, in dem das Programm die
Lehrkräfte selbst wählt, wird nur berichtet. Eine Stufe zählt erst,
wenn die vorige bestanden hat.

Abnahme einer Stufe: auf jedem der verlangten Seeds
- ein gültiger Plan in unter `FIRST_PLAN_LIMIT_SECONDS`,
- null Validator-Fehler,
- weniger als `MAX_LATE_GAIN_PERCENT` der Verbesserung im letzten
  Fünftel der Suchzeit.
"""

from typing import Optional

from pydantic import BaseModel

from benchmarks.datasets import FIXED_SUFFIX, LONG_DAY_NAME
from benchmarks.runner import RunResult

FIRST_PLAN_LIMIT_SECONDS = 60.0
MAX_LATE_GAIN_PERCENT = 5.0

PASSED = "BESTANDEN"
FAILED = "NICHT BESTANDEN"


class LadderStage(BaseModel):
    """Eine Stufe der Leiter: Abnahme- und Berichts-Datensatz."""

    name: str

    @property
    def given_dataset(self) -> str:
        """Datensatz mit vorgegebener Verteilung (zählt für die Abnahme)."""
        return self.name + FIXED_SUFFIX

    @property
    def chosen_dataset(self) -> str:
        """Datensatz, in dem das Programm die Lehrkräfte wählt (Bericht)."""
        return self.name


LADDER: tuple[LadderStage, ...] = (
    LadderStage(name="nrw-18"),
    LadderStage(name="nrw-30"),
    LadderStage(name="nrw-36"),
)
# Nur berichtet, nicht Teil der Abnahme.
EARLY_WARNING_DATASETS: tuple[str, ...] = (LONG_DAY_NAME,)


class StageVerdict(BaseModel):
    """Abnahme-Ergebnis einer Stufe."""

    stage: str
    required_seeds: int
    runs: int
    solved: int = 0
    passed: bool
    reasons: list[str]
    max_first_plan_seconds: Optional[float] = None
    validator_errors: int = 0
    max_late_gain_percent: Optional[float] = None

    def summary_line(self) -> str:
        """Einzeilige Abnahme-Aussage mit den Zahlen."""
        verdict = PASSED if self.passed else FAILED
        line = (
            f"Abnahme {self.stage}: {verdict} | "
            f"{self._seeds_part()} | "
            f"erster Plan max: {_number(self.max_first_plan_seconds)} s "
            f"(Grenze < {FIRST_PLAN_LIMIT_SECONDS:g} s) | "
            f"Validator-Fehler: {self.validator_errors} | "
            f"Spätgewinn max: {_number(self.max_late_gain_percent)} % "
            f"(Grenze < {MAX_LATE_GAIN_PERCENT:g} %)"
        )
        return line

    def _seeds_part(self) -> str:
        """Gelöste Seeds; gerechnete nur, wenn welche fehlen."""
        part = f"gelöst: {self.solved}/{self.required_seeds} Seeds"
        if self.runs < self.required_seeds:
            part += f" (gerechnet: {self.runs})"
        return part


def _number(value: Optional[float]) -> str:
    return "–" if value is None else f"{value:g}"


def run_failures(result: RunResult) -> list[str]:
    """Gründe, warum `result` die Abnahme verfehlt (leer = bestanden)."""
    prefix = f"Seed {result.seed}"
    if not result.is_solved:
        return [f"{prefix}: kein Plan (Status {result.status})"]
    reasons: list[str] = []
    first_plan = result.first_plan_seconds
    if first_plan is None or first_plan >= FIRST_PLAN_LIMIT_SECONDS:
        reasons.append(
            f"{prefix}: erster Plan nach {_number(first_plan)} s "
            f"(Grenze < {FIRST_PLAN_LIMIT_SECONDS:g} s)"
        )
    if result.validator_errors:
        reasons.append(
            f"{prefix}: {result.validator_errors} Validator-Fehler"
        )
    late_gain = result.late_gain_percent
    if late_gain is not None and late_gain >= MAX_LATE_GAIN_PERCENT:
        reasons.append(
            f"{prefix}: Spätgewinn {late_gain:g} % "
            f"(Grenze < {MAX_LATE_GAIN_PERCENT:g} %)"
        )
    return reasons


def _max_or_none(values: list[Optional[float]]) -> Optional[float]:
    present = [value for value in values if value is not None]
    return max(present) if present else None


def evaluate_stage(
    stage: str, results: list[RunResult], required_seeds: int
) -> StageVerdict:
    """Prüft die Läufe einer Stufe gegen die Abnahme-Kriterien.

    Fehlende Seeds (z.B. weil Testdaten übersprungen wurden) zählen als
    nicht bestanden. Ein Lauf ohne zweite Lösung hat keinen Spätgewinn;
    er besteht dieses Kriterium (nichts mehr zu verbessern).
    """
    reasons: list[str] = []
    if len(results) < required_seeds:
        reasons.append(
            f"nur {len(results)} von {required_seeds} Seeds gerechnet"
        )
    for result in results:
        reasons.extend(run_failures(result))
    solved = [result for result in results if result.is_solved]
    return StageVerdict(
        stage=stage,
        required_seeds=required_seeds,
        runs=len(results),
        solved=len(solved),
        passed=not reasons,
        reasons=reasons,
        max_first_plan_seconds=_max_or_none(
            [result.first_plan_seconds for result in solved]
        ),
        validator_errors=sum(
            result.validator_errors or 0 for result in solved
        ),
        max_late_gain_percent=_max_or_none(
            [result.late_gain_percent for result in solved]
        ),
    )
