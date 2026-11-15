"""Schreibt Benchmark-Ergebnisse als CSV und Markdown-Tabelle."""

import csv
from pathlib import Path
from statistics import median
from typing import Callable, Optional

from benchmarks.runner import RunResult

MISSING = "–"

Formatter = Callable[[RunResult], object]

# (Spaltenüberschrift, Wert aus RunResult)
COLUMNS: tuple[tuple[str, Formatter], ...] = (
    ("Datensatz", lambda r: r.dataset),
    ("Seed", lambda r: r.seed),
    ("Status", lambda r: r.status),
    ("Variablen", lambda r: r.num_variables),
    ("Constraints", lambda r: r.num_constraints),
    ("Aufbau s", lambda r: r.build_seconds),
    ("Erste Lösung s", lambda r: r.warmstart_seconds),
    ("Gesamt s", lambda r: r.total_seconds),
    ("Zielwert", lambda r: r.objective),
    ("Spätgewinn %", lambda r: r.late_gain_percent),
    ("Springstd.", lambda r: r.total_gaps),
    ("Fach-Häufungen", lambda r: r.bunched_subject_days),
    ("Validator-Fehler", lambda r: r.validator_errors),
)


def _cell(value: object) -> str:
    """Formatiert einen Tabellenwert; None wird als Strich dargestellt."""
    if value is None:
        return MISSING
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _median_or_none(values: list[Optional[float]]) -> Optional[float]:
    present = [v for v in values if v is not None]
    return round(median(present), 1) if present else None


def summarize(results: list[RunResult]) -> str:
    """Einzeilige Zusammenfassung über alle Läufe."""
    solved = [r for r in results if r.is_solved]
    first = _median_or_none([r.warmstart_seconds for r in solved])
    late = _median_or_none([r.late_gain_percent for r in solved])
    return (
        f"Gelöst: {len(solved)}/{len(results)} | "
        f"Median erste Lösung: {_cell(first)} s | "
        f"Median Spätgewinn: {_cell(late)} %"
    )


def render_markdown(results: list[RunResult], title: str) -> str:
    """Erzeugt eine Markdown-Tabelle mit einer Zeile pro Lauf."""
    headers = [header for header, _ in COLUMNS]
    lines = [
        f"# Benchmark: {title}",
        "",
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for result in results:
        cells = [_cell(getter(result)) for _, getter in COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", summarize(results), "", _legend(), ""]
    return "\n".join(lines)


def _legend() -> str:
    return (
        "- **Aufbau s**: Zeit für den Modellaufbau.\n"
        "- **Erste Lösung s**: Suchzeit bis zum ersten gültigen Plan "
        "(Strich = keiner im Warm-Start gefunden).\n"
        "- **Spätgewinn %**: Anteil der Verbesserung in den letzten 20 % "
        "des Zeitlimits. Nahe 0 = ausgereift, hoch = vom Zeitlimit "
        "abgeschnitten.\n"
        "- **Fach-Häufungen**: Fälle, in denen eine Klasse dasselbe Fach "
        "3× oder öfter an einem Tag hat."
    )


def write_csv(results: list[RunResult], path: Path) -> None:
    """Schreibt alle Messwerte (auch nicht tabellierte) als CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(RunResult.model_fields)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(result.model_dump())


def write_markdown(results: list[RunResult], title: str, path: Path) -> None:
    """Schreibt die Markdown-Tabelle nach `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_markdown(results, title), encoding="utf-8")
