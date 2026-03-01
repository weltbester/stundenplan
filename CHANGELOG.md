# Changelog

All notable changes to this project will be documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

---

## [2.1] — 2026-03-01

### Added
- **Oberstufe (Sek II) — Slots 8–10 aktiv** — Per-class `max_slot` filtering
  replaces the global `sek1_max_slot` ceiling; Sek-II courses may use slots 8–10.
- **`SchoolClass.is_course` / `course_type`** — New fields model Oberstufe LK/GK
  courses as `SchoolClass` objects (`is_course=True`, `course_type="LK"/"GK"`).
- **`CourseTrack` model** (`models/course_track.py`) — Kursschienen enforce that
  courses in the same lane are scheduled at identical (day, slot) pairs; enables
  student-conflict avoidance without tracking individual students.
- **`SchoolData.course_tracks`** — New field stores CourseTrack list; Solver
  constraint C15 enforces synchronisation.
- **`Teacher.can_teach_sek2`** — Boolean flag (default `True`) prevents Sek-I-only
  contract staff from being assigned to Oberstufe courses.
- **`TimeGridConfig.sek2_max_slot`** — New config field (default 10).
- **`DoubleBlock(9, 10)`** — Default time grid now includes the Sek-II double block.
- **`STUNDENTAFEL_OBERSTUFE_GYMNASIUM`** — NRW representative hour table for
  EF/Q1/Q2 (LK 5h, GK 3h).
- **`default_oberstufe_grades()`** — Helper returning grade definitions for Jg. 11–13.
- **`generate --oberstufe`** — CLI flag adds EF/Q1/Q2 courses + CourseTrack objects
  to the generated dataset.
- **Feasibility check for Sek-II capacity** — `validate_feasibility()` reports
  missing Sek-II-capable teachers per subject.
- **Solver: C15 CourseTrack constraint** — Parallel courses in the same lane share
  identical (day, slot) combinations.
- **`Teacher.available_slots_count(max_slot)`** — Replaces hardcoded Sek-I count in
  feasibility checks; defaults to 7 for backward compatibility.
- **Excel import — Oberstufe support** (`data/excel_import.py`):
  - `Lehrkräfte` sheet: new optional `Sek-II berechtigt` column (ja/nein, default ja)
    → `Teacher.can_teach_sek2`; dropdown validation in template.
  - `Jahrgänge` sheet: new optional `Kurstyp (LK/GK)` column; grade ≥ 11 rows are
    automatically imported as `is_course=True` with `max_slot=sek2_max_slot`.
  - New `import_course_tracks()` method reads optional `Kursschienen` sheet
    (columns: `ID`, `Name`, `Kurse (kommagetrennt)`, `Stunden/Woche`) →
    `list[CourseTrack]`; result passed to `SchoolData.course_tracks`.
  - `generate_template()` adds the `Kursschienen` sheet (sheet 8) with hint and
    example row.
- **Sek-II solver tests** (`tests/test_solver.py`) — `TestOberstufeSekII` class with
  5 tests: mixed-school feasibility, Sek-I slot boundary, `can_teach_sek2=False`
  exclusion, C15 synchronisation, and feasibility capacity error reporting.

### Changed
- Wizard intro no longer shows "Oberstufe folgt in v2" placeholder.
- `_c10_compact_class_schedule` skips Oberstufe courses (Freistunden allowed).
- Teacher/class/room conflict constraints cover all slots including 8–10.
- Gap penalty tracking uses all slots; Sek-I teachers are unaffected (no vars there).
- Pin warning now reports `slot > cls.max_slot` instead of generic message.
- Excel export: room-utilisation denominator in `_sheet_uebersicht()` uses
  `sek2_max_slot` when Oberstufe courses are present (was always `sek1_max_slot`).

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
