# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [2.0] — 2026-03-01

### Added
- **Adaptive Two-Pass Solver** — `solve()` now auto-enables two-pass mode when
  ≥ 20 classes are detected; `--two-pass` / `--no-two-pass` CLI flags still work
  as explicit overrides.
- **Per-Teacher Excel Fields** — three new optional columns in the `Lehrkräfte`
  sheet: `Sperrslots (Tag:Slot,...)` (e.g. `Mo:3,Fr:6`), `Wunsch-frei (Tage)`
  (e.g. `Fr Mo`), and `Max Springstd/Woche` (integer). Old-format columns remain
  supported as fallback.
- **`Teacher.max_gaps_per_week`** — new per-teacher field (default 5) for
  individual weekly gap limits, independent of the global solver config.
- **`python main.py diff`** — new CLI command that compares two `SchoolData` JSON
  files and reports teachers added/removed, curriculum hour changes, coupling
  changes, and config differences. Supports `--format text` (Rich table, default)
  and `--format json`. Exit code 0 = identical, 1 = differences found.
- **Untis Lesson Import** — `UntisXmlImporter.import_lessons()` parses
  `<lessons>/<lesson>` from Untis XML exports into `PinnedLesson` objects.
  Pins are automatically saved to `output/pins.json` (configurable via
  `--pins-output`) after a successful `import` run.
- **`ImportReport.pinned_lessons`** and `lessons_imported` fields.

### Changed
- `solve()` signature: `use_two_pass` changed from `bool = False` to
  `Optional[bool] = None` (None = auto-detect).
- `--two-pass / --no-two-pass` CLI default changed from `False` to `None`.
- `cmd_import` gains `--pins-output` option for controlling the pin file path.

---

## [1.1] — 2025 (pre-v2)

### Added
- Importable Stundentafel: new `Fächer` sheet in Excel template,
  `import_subjects()` and `import_stundentafel()` methods; no more NRW
  hardcoding.
- Teacher subjects: `Fächer (kommagetrennt)` column replaces `Fach1/2/3`;
  old format still parsed for backward compatibility.
- CSV import: `CsvImporter` subclass + `import_from_csv()`; `cmd_import`
  auto-detects `.xlsx` vs `.csv` / directory.
- Solver timeout UX: `UNKNOWN` → yellow message + `--time-limit` hint;
  `FEASIBLE` → non-optimal warning.
- Room assignment: greedy fast-path + CP-SAT second pass;
  `RoomAssignmentError` replaces silent `-?` fallbacks.
- Extended `SchoolType` enum: `REALSCHULE`, `GESAMTSCHULE`, `HAUPTSCHULE`,
  `BERUFSSCHULE`, `GEMEINSCHAFTSSCHULE`.

---

## [1.0] — 2025 (initial release)

- CP-SAT scheduler with hard and soft constraints.
- Excel template generation and import.
- Untis XML metadata import (teachers, subjects, classes, rooms).
- Pin manager for fixing individual lessons.
- PDF and Excel export.
- Rich CLI with setup wizard.
- Solution quality report and substitution helper.
