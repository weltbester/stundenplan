# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier festgehalten.
Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/).

## [Unreleased]

### Added
- `show` zeigt Raumpläne für Sonderräume und Klassenräume
  (z.B. `show PH1`, `show 101`).
- `CHANGELOG.md`.
- Entwickler-Benchmark `benchmarks/` (`python3.14 -m
  benchmarks.run_benchmark`): misst Modellaufbau, Zeit bis zur ersten
  Lösung, Zielwert-Verlauf, Springstunden, Fach-Häufungen und
  Validator-Fehler über mehrere Seeds; Ausgabe als Markdown und CSV in
  `output/benchmarks/`.

### Changed
- `solve --small` schreibt nach `output/solution_small.json` und
  überschreibt die vollständige Lösung nicht mehr.
- `.gitignore`: echte Personaldaten (`lehrer.txt`, `lehrer.xlsx`),
  die fremde venv `.macpro/` und `.DS_Store` werden ignoriert.

### Fixed
- Validator meldete bei jedem Plan mit WPF-Kopplungen Fehlalarme
  (36-Klassen-Plan: 48 Fehler). Parallele Gruppen derselben Kopplung
  gelten nicht mehr als Klassen-Doppelbelegung, und WPF-Termine zählen
  für das Stundentafel-Fach "WPF".

### Removed
- `.DS_Store` aus der Versionsverwaltung entfernt (Datei bleibt lokal).
