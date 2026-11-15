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

- Harte Regel C15: pro Klasse, Fach und Tag höchstens eine Stunde oder
  ein Doppelstunden-Block (auch für Kopplungen).
- Validator-Prüfung `subject_day_limit` für dieselbe Regel.
- Unterrichtsverteilung als Eingabe: neues Excel-Blatt
  "Unterrichtsverteilung" (Matrix Klasse × Fach, Zelle = Kürzel),
  optionales Kürzel je Kopplungsgruppe (`Name:Fach:Std:Kürzel`),
  Modell `FixedAssignment` und `SchoolData.fixed_assignments`.
  Der Solver nutzt die Vorgaben noch nicht.
- Machbarkeits-Check prüft die Vorgaben (unbekannte Klasse/Kürzel,
  Fach nicht in der Stundentafel, Deputat-Max, Sperrzeiten,
  Deputat-Min erreichbar; fachfremder Einsatz als Warnung).
- `template --from-data … [--from-solution …]` schreibt eine
  ausgefüllte, wieder importierbare Vorlage aus einem Datensatz und
  optional der Unterrichtsverteilung eines Plans.

### Changed
- Das Soft-Ziel "Hauptfach-Verteilung" ist entfernt: es belohnte das
  Bündeln eines Fachs auf wenige Tage und ist durch C15 ersetzt.
  `weight_subject_spread` und `--weights subject_spread=…` werden noch
  akzeptiert, haben aber keine Wirkung (veraltet). Der Wizard fragt das
  Gewicht nicht mehr ab.
- `solve --small` schreibt nach `output/solution_small.json` und
  überschreibt die vollständige Lösung nicht mehr.
- `.gitignore`: echte Personaldaten (`lehrer.txt`, `lehrer.xlsx`),
  die fremde venv `.macpro/` und `.DS_Store` werden ignoriert.

### Fixed
- Excel-Import: Das Blatt "Stundentafel" wird jetzt eingelesen; bisher
  galt immer die eingebaute Stundentafel, Änderungen im Blatt blieben
  wirkungslos.
- Excel-Vorlage: keine Beispielzeile mehr im Blatt "Fachräume" (sie
  wurde als zwei zusätzliche Sporthallen mit doppelten IDs importiert);
  Raum-IDs sind auch bei mehrfach genanntem Raumtyp eindeutig.
- Excel-Import: Lehrkräfte mit dem Kürzel `MÜL` werden nicht mehr
  übersprungen; die Beispielzeile wird am Präfix `Beispiel:` erkannt.
- Excel-Vorlage: Das Blatt "Kopplungen" enthält alle Kopplungen laut
  Konfiguration statt nur einer Beispielzeile für Jahrgang 5.
- Validator meldete bei jedem Plan mit WPF-Kopplungen Fehlalarme
  (36-Klassen-Plan: 48 Fehler). Parallele Gruppen derselben Kopplung
  gelten nicht mehr als Klassen-Doppelbelegung, und WPF-Termine zählen
  für das Stundentafel-Fach "WPF".

### Removed
- `.DS_Store` aus der Versionsverwaltung entfernt (Datei bleibt lokal).
