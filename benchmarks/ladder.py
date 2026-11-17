"""Rechnet die Benchmark-Leiter und schreibt den Bericht (Schritt 4e).

Ablauf je Stufe: Abnahme-Datensatz (vorgegebene Verteilung), dann
Berichts-Datensatz (Programm wählt die Lehrkräfte), dann Abnahme. Fällt
eine Stufe durch, endet die Leiter; die übrigen Stufen und die
Frühwarn-Datensätze werden nicht gerechnet und im Bericht genannt.
"""

from typing import Callable

from pydantic import BaseModel

from benchmarks.acceptance import (
    EARLY_WARNING_DATASETS, LADDER, StageVerdict, evaluate_stage,
)
from benchmarks.report import legend, table_lines
from benchmarks.runner import RunResult

# (Datensatz, Seeds, Zeitlimit) → (Ergebnisse, Hinweise)
DatasetRunner = Callable[[str, int, int], tuple[list[RunResult], list[str]]]


class DatasetRun(BaseModel):
    """Alle Läufe eines Datensatzes."""

    dataset: str
    results: list[RunResult]
    notes: list[str] = []


class StageReport(BaseModel):
    """Eine Stufe der Leiter: beide Datensätze und die Abnahme."""

    given: DatasetRun
    chosen: DatasetRun
    verdict: StageVerdict


class LadderReport(BaseModel):
    """Ergebnis der ganzen Leiter."""

    stages: list[StageReport] = []
    early_warning: list[DatasetRun] = []
    # Datensätze, die wegen einer durchgefallenen Stufe fehlen
    skipped: list[str] = []

    @property
    def passed(self) -> bool:
        """True, wenn alle Stufen gerechnet wurden und bestanden haben."""
        return len(self.stages) == len(LADDER) and all(
            stage.verdict.passed for stage in self.stages
        )

    def all_results(self) -> list[RunResult]:
        """Alle Läufe in Rechenreihenfolge (für die CSV-Datei)."""
        runs: list[DatasetRun] = []
        for stage in self.stages:
            runs += [stage.given, stage.chosen]
        runs += self.early_warning
        return [result for run in runs for result in run.results]


def _run(
    runner: DatasetRunner, dataset: str, seeds: int, time_limit: int
) -> DatasetRun:
    results, notes = runner(dataset, seeds, time_limit)
    return DatasetRun(dataset=dataset, results=results, notes=notes)


def run_ladder(
    runner: DatasetRunner, seed_count: int, time_limit: int
) -> LadderReport:
    """Rechnet die Stufen der Reihe nach, bis eine durchfällt."""
    report = LadderReport()
    for index, stage in enumerate(LADDER):
        given = _run(runner, stage.given_dataset, seed_count, time_limit)
        chosen = _run(runner, stage.chosen_dataset, seed_count, time_limit)
        verdict = evaluate_stage(stage.name, given.results, seed_count)
        print(verdict.summary_line(), flush=True)
        report.stages.append(
            StageReport(given=given, chosen=chosen, verdict=verdict)
        )
        if not verdict.passed:
            report.skipped = _remaining_datasets(index + 1)
            return report
    report.early_warning = [
        _run(runner, dataset, seed_count, time_limit)
        for dataset in EARLY_WARNING_DATASETS
    ]
    return report


def _remaining_datasets(first_stage: int) -> list[str]:
    names: list[str] = []
    for stage in LADDER[first_stage:]:
        names += [stage.given_dataset, stage.chosen_dataset]
    return names + list(EARLY_WARNING_DATASETS)


def render_ladder(report: LadderReport, title: str) -> str:
    """Bericht: eine Tabelle je Datensatz, Abnahme je Stufe, Ergebnis."""
    lines = [f"# Benchmark-Leiter: {title}", ""]
    for stage in report.stages:
        lines += [f"## Stufe {stage.verdict.stage}", ""]
        lines += _dataset_lines(
            stage.given, "vorgegebene Verteilung, zählt für die Abnahme"
        )
        lines += _dataset_lines(
            stage.chosen, "Programm wählt die Lehrkräfte, nur Bericht"
        )
        lines += _verdict_lines(stage.verdict)
    if report.early_warning:
        lines += ["## Frühwarnung", ""]
    for run in report.early_warning:
        lines += _dataset_lines(run, "nur Bericht")
    lines += ["## Ergebnis", ""]
    lines += [
        f"- {stage.verdict.summary_line()}" for stage in report.stages
    ]
    if report.skipped:
        lines.append(
            "- Nicht gerechnet (vorige Stufe nicht bestanden): "
            + ", ".join(report.skipped)
        )
    lines += ["", legend(), ""]
    return "\n".join(lines)


def _dataset_lines(run: DatasetRun, role: str) -> list[str]:
    return [f"### {run.dataset} ({role})", ""] + table_lines(
        run.results, run.notes
    )


def _verdict_lines(verdict: StageVerdict) -> list[str]:
    lines = [f"**{verdict.summary_line()}**", ""]
    if verdict.reasons:
        lines += [f"- {reason}" for reason in verdict.reasons] + [""]
    return lines
