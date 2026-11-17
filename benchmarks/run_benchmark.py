"""Benchmark-Lauf über mehrere Seeds.

Aufruf (aus dem Projektverzeichnis):
    python3.14 -m benchmarks.run_benchmark --dataset loose-36 --seeds 3
    python3.14 -m benchmarks.run_benchmark --all --seeds 5
"""

import argparse
from pathlib import Path
from typing import Optional, Sequence

from benchmarks.assignment import AssignmentError
from benchmarks.datasets import (
    DatasetFactory, build_dataset, dataset_names,
)
from benchmarks.ladder import render_ladder, run_ladder
from benchmarks.report import render_markdown, write_csv, write_markdown
from benchmarks.runner import RunResult, run_once
from models.school_data import SchoolData

BASE_SEED = 42
DEFAULT_SEED_COUNT = 3
DEFAULT_TIME_LIMIT = 300
DEFAULT_LABEL = "baseline"
DEFAULT_DATASET = "loose-36"
LADDER_LABEL = "leiter"
DEFAULT_OUTPUT_DIR = Path("output/benchmarks")
# Höchstens so viele Seeds je gewünschtem Lauf werden durchprobiert.
MAX_ATTEMPTS_PER_RUN = 5

SeededData = tuple[int, SchoolData]


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Liest die Kommandozeilen-Optionen."""
    parser = argparse.ArgumentParser(
        description="Misst den Stundenplan-Solver über mehrere Seeds."
    )
    target = parser.add_mutually_exclusive_group()
    target.add_argument(
        "--dataset", default=DEFAULT_DATASET, choices=dataset_names(),
        help=f"Datensatz (Standard: {DEFAULT_DATASET}).",
    )
    target.add_argument(
        "--all", action="store_true",
        help="Benchmark-Leiter nrw-18 → nrw-30 → nrw-36 mit Abnahme, "
        "danach long-day-36.",
    )
    parser.add_argument(
        "--seeds", type=int, default=DEFAULT_SEED_COUNT,
        help=f"Anzahl gültiger Seeds ab {BASE_SEED} (Standard: 3).",
    )
    parser.add_argument(
        "--time-limit", type=int, default=DEFAULT_TIME_LIMIT,
        help="Solver-Zeitlimit pro Lauf in Sekunden (Standard: 300).",
    )
    parser.add_argument(
        "--label", default=None,
        help=f"Dateiname der Ergebnisse ohne Endung (Standard: "
        f"{DEFAULT_LABEL}, mit --all {LADDER_LABEL}).",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help="Zielordner (Standard: output/benchmarks).",
    )
    return parser.parse_args(argv)


def collect_valid_datasets(
    factory: DatasetFactory, count: int
) -> tuple[list[SeededData], list[str]]:
    """Die ersten `count` Datensätze ab BASE_SEED, die lösbar sein können.

    Der Testdaten-Generator erzeugt gelegentlich unbrauchbare Daten (z.B.
    ein Fach ohne Lehrkraft). Solche Seeds werden übersprungen und in den
    Hinweisen genannt, statt den Solver daran scheitern zu lassen.
    """
    valid: list[SeededData] = []
    notes: list[str] = []
    for seed in range(BASE_SEED, BASE_SEED + count * MAX_ATTEMPTS_PER_RUN):
        if len(valid) == count:
            break
        data, problem = _build_checked(factory, seed)
        if data is None:
            notes.append(
                f"Seed {seed} übersprungen (Daten ungültig): {problem}"
            )
        else:
            valid.append((seed, data))
    return valid, notes


def _build_checked(
    factory: DatasetFactory, seed: int
) -> tuple[Optional[SchoolData], str]:
    """Datensatz für `seed`, oder (None, Grund) wenn er unbrauchbar ist."""
    try:
        data = factory(seed)
    except AssignmentError as error:
        return None, str(error)
    report = data.validate_feasibility()
    if report.is_feasible:
        return data, ""
    return None, report.errors[0]


def run_benchmark(
    dataset: str, seed_count: int, time_limit: int
) -> tuple[list[RunResult], list[str]]:
    """Führt `seed_count` Läufe aus; gibt Ergebnisse und Hinweise zurück."""
    datasets, notes = collect_valid_datasets(
        lambda seed: build_dataset(dataset, seed), seed_count
    )
    for note in notes:
        print(note, flush=True)

    results: list[RunResult] = []
    for index, (seed, data) in enumerate(datasets, 1):
        print(
            f"Lauf {index}/{len(datasets)}: {dataset}, Seed {seed}, "
            f"Zeitlimit {time_limit}s ...",
            flush=True,
        )
        result = run_once(dataset, seed, data, time_limit)
        print(
            f"  → {result.status} nach {result.total_seconds}s",
            flush=True,
        )
        results.append(result)
    return results, notes


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Einstiegspunkt: Läufe ausführen, Tabelle ausgeben und speichern.

    Mit `--all` ist der Rückgabewert 1, wenn die Abnahme scheitert.
    """
    args = parse_args(argv)
    if args.all:
        return _main_ladder(args)
    label = args.label or DEFAULT_LABEL
    results, notes = run_benchmark(
        args.dataset, args.seeds, args.time_limit
    )

    title = f"{label} ({args.dataset})"
    markdown_path = args.output_dir / f"{label}.md"
    csv_path = args.output_dir / f"{label}.csv"
    write_markdown(results, title, markdown_path, notes)
    write_csv(results, csv_path)

    print()
    print(render_markdown(results, title, notes))
    print(f"Gespeichert: {markdown_path} und {csv_path}")
    return 0


def _main_ladder(args: argparse.Namespace) -> int:
    """Leiter rechnen, Bericht ausgeben und speichern."""
    label = args.label or LADDER_LABEL
    report = run_ladder(run_benchmark, args.seeds, args.time_limit)
    text = render_ladder(
        report, f"{label} ({args.seeds} Seeds, {args.time_limit} s)"
    )
    markdown_path = args.output_dir / f"{label}.md"
    csv_path = args.output_dir / f"{label}.csv"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(text, encoding="utf-8")
    write_csv(report.all_results(), csv_path)

    print()
    print(text)
    print(f"Gespeichert: {markdown_path} und {csv_path}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
