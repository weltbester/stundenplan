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
- Der Solver berücksichtigt die vorgegebene Unterrichtsverteilung
  (Klasse-Fach-Zuweisungen und Kopplungsgruppen, auch fachfremd) und
  erzeugt dafür nur Variablen der vorgegebenen Lehrkraft.
- Benchmark: Datensatz `loose-36-fixed` mit generierter vollständiger
  Unterrichtsverteilung (`benchmarks/assignment.py`); Seeds mit
  ungültigen Testdaten werden übersprungen und gemeldet.
- Referenz `docs/bundeslaender.md`: Vorgaben der 16 Länder für die
  Sek I am Gymnasium (G8/G9, Schüler- und Lehrerstunden), Abgleich
  mit dem Programm und nötige Erweiterungen je Länderfamilie.
- Freie Fächerliste: neues Excel-Blatt "Fächer" (Fach, Kürzel,
  Kategorie, Hauptfach, Fachraum-Typ, Doppelstunde), vorausgefüllt mit
  den bisherigen Fächern und Wirtschaft-Politik, Praktische
  Philosophie, Spanisch, Niederländisch, Ergänzungsstunde. Solver,
  Machbarkeits-Check und `template --from-data` richten sich nach der
  Fächerliste des Datensatzes; Mappen ohne das Blatt und ältere
  JSON-Dateien funktionieren weiter.
- Machbarkeits-Check meldet Fächer, die in Stundentafel, bei
  Lehrkräften oder in Kopplungen vorkommen, aber nicht in der
  Fächerliste stehen.
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
- Das Zeitlimit (`--time-limit`, `time_limit_seconds`) gilt für den
  ganzen Solver-Lauf. Bisher kamen Modellaufbau und Warm-Start oben
  drauf (300 s Limit ergaben beim 36-Klassen-Datensatz rund 440 s).
  Der Warm-Start bekommt höchstens ein Drittel der Zeit nach dem
  Aufbau (maximal 90 s), die Optimierung den Rest
  (`solver/time_budget.py`).
- Benchmark: "Spätgewinn %" bezieht sich auf die Optimierungszeit
  statt auf das ganze Zeitlimit.
- Excel-Import: Ein unbekannter Fachname ist immer ein Fehler. Bisher
  wurde ein ähnlich geschriebenes Fach mit einer Warnung eingesetzt
  (z.B. "Mathe" → "Mathematik"); jetzt wird es nur vorgeschlagen.
  Groß-/Kleinschreibung bleibt egal.
- `template --from-data` schreibt die Stundentafel des Datensatzes
  (bisher immer die eingebaute).
- Die Auswahlliste für Fächer im Blatt "Lehrkräfte" verweist auf das
  Blatt "Fächer" (bisher eine feste Liste der ersten 20 Fächer).
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
- Machbarkeits-Check: Die unterrichtbaren Stunden einer Lehrkraft
  werden je Tag als Minimum aus Tagesmaximum und Stunden ohne
  Sperrzeit gerechnet (bisher: Wochen-Slots minus Sperrzeiten). Zu
  hohe Vorgaben oder ein zu hohes Deputat-Min fallen damit vor dem
  Solver-Lauf auf statt als unerklärtes INFEASIBLE.
- Excel-Import: Die Raumanzahl aus dem Blatt "Fachräume" gilt jetzt
  auch für den Solver. Bisher rechnete er mit der Anzahl aus der
  Konfiguration; ein nur im Blatt angelegter Raumtyp galt als
  unbegrenzt.
- `solve --diagnose` verändert für die Probe "ohne
  Doppelstunden-Pflicht" keine globale Tabelle mehr, sondern eine Kopie
  der Fächerliste.
- `solve --diagnose` rechnet mit der vorgegebenen Unterrichtsverteilung
  (die Relaxierungen ließen sie bisher weg).
- Validator meldete bei jedem Plan mit WPF-Kopplungen Fehlalarme
  (36-Klassen-Plan: 48 Fehler). Parallele Gruppen derselben Kopplung
  gelten nicht mehr als Klassen-Doppelbelegung, und WPF-Termine zählen
  für das Stundentafel-Fach "WPF".

### Removed
- `.DS_Store` aus der Versionsverwaltung entfernt (Datei bleibt lokal).
