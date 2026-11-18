# Changelog

Alle nennenswerten Änderungen an diesem Projekt werden hier festgehalten.
Format angelehnt an [Keep a Changelog](https://keepachangelog.com/de/).

## [Unreleased]

### Added
- Machbarkeits-Check: Fehler, wenn in einer Stunde, die jede Klasse an
  jedem Tag hat (der Tag beginnt ohne Lücke in der 1. Stunde), nicht
  jede dieser Klassen gleichzeitig eine eigene freie Lehrkraft
  bekommen kann. Die Meldung nennt Tag, Stunde, Klassen und die freien
  Lehrkräfte. Bisher suchte der Solver in diesem Fall bis zum
  Zeitlimit ohne Ergebnis (`models/attendance_check.py`).
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
- Testdaten-Profil `nrw-g9` (`main.py generate --profile nrw-g9`,
  `main.py validate --generate --profile nrw-g9 --seed N`): ein
  NRW-Gymnasium mit der G9-Stundentafel. Die Lehrkräfte werden aus dem
  Bedarf je Fach abgeleitet (jedes Fach ist besetzt, rund 4 % Reserve),
  Soll 25,5 Stunden mit engen Grenzen, rund 30 % Teilzeit mit freiem Tag
  oder einer gesperrten Randstunde, Sperrzeiten für den Unterricht in
  der Sek II (in acht gemeinsamen Oberstufen-Schienen statt zufällig je
  Lehrkraft), je Klasse eine Gruppe in Religion/Praktische Philosophie, WPF
  und Sprachen-Schiene (`data/nrw_data.py`). Das bisherige Profil heißt
  `loose` und bleibt Standard.
- Zusammenfassung des Datensatzes: Unterrichtsbedarf in Lehrerstunden
  und Kapazitätsreserve (Soll-Deputate über Bedarf).
- `validate --generate` nimmt `--profile` und `--seed`.
- Reli-Gruppen: heißt eine Gruppe in `couplings.reli_groups` wie ein
  Fach (z.B. "Praktische Philosophie"), unterrichtet sie dieses Fach;
  bisher ging das nur für "ethik".
- Eingebaute Stundentafel für NRW, Gymnasium G9 (`config/nrw_g9.py`):
  eine Beispielverteilung nach APO-S I, Anlage 3a, mit 182 Kernstunden
  und 6 Ergänzungsstunden (30, 30, 32, 32, 32, 32 Wochenstunden),
  zweiter Fremdsprache ab Kl. 7, Wahlpflicht in Kl. 9–10, Informatik in
  Kl. 6. Die Vorlage aus `main.py template` ist damit vorausgefüllt.
- Sprachen-Schiene: neuer Kopplungstyp `band` und Feld
  `Coupling.curriculum_subject` ("Fach der Stundentafel"). Die Gruppen
  einer Schiene (z.B. Französisch, Latein) decken zusammen ein anders
  benanntes Fach der Stundentafel ab (`2. Fremdsprache`). Neue Spalte
  "Fach der Stundentafel" im Blatt "Kopplungen"; Mappen ohne die Spalte
  laden weiter. Die Vorlage legt je Jahrgang mit zweiter Fremdsprache
  eine Schiene an (Einstellung `couplings.second_language_subjects`).
- Fach `2. Fremdsprache` in der vorgeschlagenen Fächerliste.
- Einstellung `solver.subject_day_limit` (Standard `true`): schaltet die
  Regel C15 in Solver und Validator ab.
- Machbarkeits-Check: Warnung, wenn ein Jahrgang den
  Wochenstundenrahmen für NRW G9 verlässt (28–30 in Kl. 5–6, 30–33 in
  Kl. 7–10; nur bei `bundesland: NRW` und Gymnasium).
- `solve` rechnet in zwei Stufen: Fehlt die Unterrichtsverteilung
  ganz oder teilweise, entscheidet zuerst ein kleines Modell ohne
  Zeitdimension, wer was unterrichtet (möglichst nah am Soll-Deputat;
  Vorgaben und gepinnte Stunden bleiben erhalten), danach entsteht der
  Stundenplan mit dieser Verteilung (`solver/distribution.py`).
  `--single-stage` rechnet wie bisher alles in einem Schritt.
- Soll-Deputat je Lehrkraft (`deputat_soll`), auch mit halben Stunden:
  die Spalte "Deputat" nimmt `25,5` an. Die ganzzahligen Grenzen für
  den Solver werden daraus abgeleitet (aufgerundet + Puffer nach oben;
  neu und optional `deputat_min_buffer` für "Soll minus n Stunden").
  Ältere Datensätze ohne Soll funktionieren weiter (Soll = Obergrenze
  minus Puffer).
- Zusammenfassung nach `solve`, `show <Kürzel>`, Qualitätsbericht und
  Excel-/PDF-Export zeigen Soll und Abweichung vom Soll.
- Datensatz-Übersicht zeigt die Summe der Soll-Deputate; der
  Machbarkeits-Check warnt, wenn sie mehr als 5 % vom Unterrichtsbedarf
  abweicht.
- Machbarkeits-Check meldet Fächer, die in Stundentafel, bei
  Lehrkräften oder in Kopplungen vorkommen, aber nicht in der
  Fächerliste stehen.
- Machbarkeits-Check prüft die Vorgaben (unbekannte Klasse/Kürzel,
  Fach nicht in der Stundentafel, Deputat-Max, Sperrzeiten,
  Deputat-Min erreichbar; fachfremder Einsatz als Warnung).
- `template --from-data … [--from-solution …]` schreibt eine
  ausgefüllte, wieder importierbare Vorlage aus einem Datensatz und
  optional der Unterrichtsverteilung eines Plans.
- Benchmark-Leiter (`python3.14 -m benchmarks.run_benchmark --all`):
  Datensätze `nrw-18`, `nrw-30`, `nrw-36` (Profil `nrw-g9` mit 3, 5,
  6 Klassen je Jahrgang) jeweils mit vorgegebener Verteilung
  (`-fixed`, zählt für die Abnahme) und mit Wahl der Lehrkräfte durch
  das Programm (nur Bericht), dazu der Frühwarn-Datensatz
  `long-day-36` (8 Sek-I-Stunden am Tag, 34/36 Wochenstunden). Abnahme
  je Stufe auf jedem Seed: gültiger Plan in unter 60 s, null
  Validator-Fehler, weniger als 5 % Spätgewinn; eine Stufe zählt nur,
  wenn die vorige bestanden hat. Die Abnahme-Zeile nennt die
  gelösten Seeds. Bericht als Markdown und CSV.
- Benchmark: Datensätze mit offener Unterrichtsverteilung rechnen wie
  `main.py solve` zuerst Stufe 1 (neue Spalte "Stufe 1 s"). Die Spalte
  "Erster Plan s" misst die Wanduhr vom Start bis zum ersten gültigen
  Plan und ersetzt "Erste Lösung s" (nur Warm-Start-Suchzeit).
- `NrwDataGenerator` nimmt eine eigene Stundentafel (`curriculum`);
  Lehrkräfte-Bedarf und Soll-Wochenstunden folgen ihr.

### Changed
- Benchmark-Leiter: jede Stufe hat ihr eigenes Zeitlimit. `nrw-36` und
  `long-day-36` rechnen 450 s statt 300 s, weil der Solver bei 36
  Klassen nach 300 s noch deutlich verbessert (Spätgewinn bis 6,1 %).
  `--time-limit` gilt mit `--all` für alle Stufen; der Bericht nennt
  das Zeitlimit je Datensatz.
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
- Benchmark: Die Verteilung für `loose-36-fixed` kommt aus derselben
  Stufe 1 (ohne Soll-Ziel, fester Seed); die Datensätze sind
  unverändert.
- Solver-Ziel "Deputat": bestraft jetzt den Abstand jeder Lehrkraft
  von ihrem Soll (quadratisch, in halben Stunden). Der bisherige Term
  (Summe aus Obergrenze minus Ist) war für jeden Plan gleich groß und
  hatte keine Wirkung. Zielwerte sind dadurch nicht mehr mit älteren
  Läufen vergleichbar.
- Excel-Import: Ein ungültiges Deputat ist ein Fehler (bisher Warnung
  und Vollzeit-Deputat); `25,5` wurde bisher stillschweigend zu 25.
- Die Untergrenze aus `deputat_min_fraction` liegt nie mehr über dem
  Soll (bei hohem Anteil und kleinem Deputat konnte sie das).
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
- **Verhaltensänderung (Solver, C9):** Fächer mit Doppelstunden-Pflicht
  und ungerader Stundenzahl (z.B. Chemie mit 1 Stunde) bekommen ihre
  Einzelstunde jetzt in einem beliebigen Slot (nicht an einem Tag mit
  Doppelstunde dieses Fachs). Bisher war nur ein Slot außerhalb der
  Doppelblöcke erlaubt, im Standard-Raster die 7. Stunde; eine Lehrkraft
  konnte so höchstens fünf solche Stunden pro Woche geben, und eine
  Sperre der 7. Stunde machte sie unmöglich. Fächer mit gerader
  Stundenzahl sind unverändert.
- **Verhaltensänderung:** Die eingebaute Stundentafel ist jetzt die
  NRW-G9-Beispielverteilung. Das betrifft `main.py template` und den
  Import von Mappen ohne Blatt "Stundentafel" (oder ohne Spalte für
  einen Jahrgang). Mappen mit eigenem Blatt und gespeicherte
  JSON-Datensätze sind nicht betroffen.
- Die bisherige Beispiel-Tafel heißt `STUNDENTAFEL_LEGACY` (vorher
  `STUNDENTAFEL_GYMNASIUM_SEK1`) und dient nur noch den Testdaten aus
  `main.py generate` und den "loose"-Benchmarks; beide sind unverändert.
- Standard-Soll-Stunden der Jahrgänge: 30, 30, 32, 32, 32, 32 (vorher
  30, 31, 32, 32, 34, 34). Bestehende Konfigurationsdateien behalten
  ihre Werte.
- Solver und Machbarkeits-Check bestimmen die über Kopplungen
  abgedeckten Fächer jetzt mit derselben Regel wie der Validator
  (`Coupling.curriculum_subjects()`). Für `reli_ethik` und `wpf` ändert
  sich nichts; bei anderen Typen zählen die Fächer der Gruppen.
- Blatt "Kopplungen": Spaltenkopf "Typ (reli_ethik/wpf/band)"; der
  Import erkennt auch den alten Kopf.
- Blatt "Unterrichtsverteilung" der Vorlage: die Marke "Kopplung"
  richtet sich nach den Kopplungen der Vorlage statt nach festen
  Fachnamen.
- Hilfe-Ausgabe: `main.py` nutzt die aktuellen rich-click-Einstellungen
  (`TEXT_MARKUP` statt `USE_RICH_MARKUP`/`USE_MARKDOWN`, Metavar-Spalte
  als Standard); die drei Abkündigungs-Warnungen entfallen, die Ausgabe
  ist unverändert. Mindestversion jetzt rich-click 1.9.
- README: die nie umgesetzten weichen Ziele S2 (gleichmäßige
  Tagesverteilung) und S4 (kompakte Lehrerpläne) sind aus der
  Constraint-Übersicht entfernt. Einstellungen ohne Wirkung
  (`time_grid.min_hours_per_day`, `teachers.max_gaps_per_day`,
  `teachers.max_gaps_per_week`, `solver.weight_workload_balance`,
  `solver.weight_compact`, `solver.weight_subject_spread`) sind in
  README und Konfigurations-Schema als solche gekennzeichnet; sie laden
  weiter, damit bestehende Dateien gültig bleiben.
- Einrichtungs-Assistent (`config/wizard.py`): fragt die Gewichte
  "Arbeitslast" und "Kompakte Pläne" sowie die Springstunden-Grenzen je
  Lehrkraft (pro Tag, pro Woche) nicht mehr ab; sie hatten keine
  Wirkung. Die Felder behalten ihre Standardwerte.
- Einrichtungs-Assistent, Schritt 7: Vorschlagswerte (Gewichte,
  Zeitlimit, CPU-Kerne) kommen aus `SolverConfig`.
- Die Regel für das Zeitlimit des Stundenplans nach Stufe 1 steht
  jetzt in `solver/distribution.py` (`timetable_time_limit`) und gilt
  für `main.py solve` und den Benchmark gleich.

### Fixed
- Testdaten-Profil `nrw-g9`: Sperrzeiten lassen in jeder Stunde, die
  jede Klasse täglich hat, mindestens Klassen × 1,15 Lehrkräfte frei.
  Bei 3 Klassen je Jahrgang waren montags in der 1. Stunde teils nur
  17 Lehrkräfte für 18 Klassen frei; der Solver fand keinen Plan und
  konnte das nicht als unlösbar erkennen (Benchmark nrw-18, Seeds 44
  und 46).
- Einrichtungs-Assistent: Gewicht Springstunden zeigte und schlug 100
  vor, "Standard-Gewichte übernehmen" setzte aber 200. Jetzt überall
  200 (Standard, auf `weight_deputat_deviation` abgestimmt).
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
- Stufe 1 (Unterrichtsverteilung) beachtet die Sperrzeiten: Jede Klasse
  hat in den Stunden, die sie an jedem Tag braucht (ab der ersten), eine
  freie Lehrkraft oder eine mögliche Kopplung, und die Lehrkräfte einer
  Kopplung haben genug gemeinsame freie Stunden (mit C15 je Tag eine
  Stunde oder ein Doppelblock). Bisher konnte Stufe 1 z.B. alle
  Lehrkräfte einer Klasse aus derselben Oberstufen-Schiene wählen; der
  Stundenplan war dann unlösbar (INFEASIBLE).

### Removed
- `.DS_Store` aus der Versionsverwaltung entfernt (Datei bleibt lokal).
