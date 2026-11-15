"""Benchmark-Lauf über mehrere Seeds.

Aufruf (aus dem Projektverzeichnis):
    python3.14 -m benchmarks.run_benchmark --dataset loose-36 --seeds 3
"""

import argparse
from pathlib import Path
from typing import Optional, Sequence

from benchmarks.datasets import build_dataset, dataset_names
from benchmarks.report import render_markdown, write_csv, write_markdown
from benchmarks.runner import RunResult, run_once

BASE_SEED = 42
DEFAULT_SEED_COUNT = 3
DEFAULT_TIME_LIMIT = 300
DEFAULT_LABEL = "baseline"
DEFAULT_OUTPUT_DIR = Path("output/benchmarks")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    """Liest die Kommandozeilen-Optionen."""
    parser = argparse.ArgumentParser(
        description="Misst den Stundenplan-Solver über mehrere Seeds."
    )
    parser.add_argument(
        "--dataset", default="loose-36", choices=dataset_names(),
        help="Datensatz (Standard: loose-36).",
    )
    parser.add_argument(
        "--seeds", type=int, default=DEFAULT_SEED_COUNT,
        help=f"Anzahl Seeds ab {BASE_SEED} (Standard: 3).",
    )
    parser.add_argument(
        "--time-limit", type=int, default=DEFAULT_TIME_LIMIT,
        help="Solver-Zeitlimit pro Lauf in Sekunden (Standard: 300).",
    )
    parser.add_argument(
        "--label", default=DEFAULT_LABEL,
        help="Dateiname der Ergebnisse ohne Endung (Standard: baseline).",
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help="Zielordner (Standard: output/benchmarks).",
    )
    return parser.parse_args(argv)


def run_benchmark(
    dataset: str, seed_count: int, time_limit: int
) -> list[RunResult]:
    """Führt `seed_count` Läufe aus und meldet den Fortschritt."""
    results: list[RunResult] = []
    for index in range(seed_count):
        seed = BASE_SEED + index
        print(
            f"Lauf {index + 1}/{seed_count}: {dataset}, Seed {seed}, "
            f"Zeitlimit {time_limit}s ...",
            flush=True,
        )
        data = build_dataset(dataset, seed)
        result = run_once(dataset, seed, data, time_limit)
        print(
            f"  → {result.status} nach {result.total_seconds}s",
            flush=True,
        )
        results.append(result)
    return results


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Einstiegspunkt: Läufe ausführen, Tabelle ausgeben und speichern."""
    args = parse_args(argv)
    results = run_benchmark(args.dataset, args.seeds, args.time_limit)

    title = f"{args.label} ({args.dataset})"
    markdown_path = args.output_dir / f"{args.label}.md"
    csv_path = args.output_dir / f"{args.label}.csv"
    write_markdown(results, title, markdown_path)
    write_csv(results, csv_path)

    print()
    print(render_markdown(results, title))
    print(f"Gespeichert: {markdown_path} und {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
