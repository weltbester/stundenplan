# Stundenplan-Generator

Automatischer Stundenplan-Generator für ein deutsches Gymnasium (Sekundarstufe I).
Löst die Stundenzuweisung als Constraint-Satisfaction-Problem mit Google OR-Tools CP-SAT.

## Features

- **Vollständig konfigurierbar**: Zeitraster, Jahrgänge, Klassenanzahl, Fachräume,
  Kopplungen und Solver-Gewichte — alles über YAML oder einen interaktiven Wizard.
- **Solver-basierte Lehrerzuweisung**: Welcher Lehrer welche Klasse unterrichtet,
  wird gemeinsam mit der Stundenzuweisung optimiert.
- **Doppelstunden**: Pflicht- und optionale Doppelstunden, nur in konfigurierten
  Blöcken (nie über Pausen hinweg).
- **Klassenübergreifende Kopplungen**: Religion/Ethik, Wahlpflichtfächer (WPF)
  und die Sprachen-Schiene der zweiten Fremdsprache werden über
  Parallelklassen hinweg modelliert.
- **Stundentafel NRW G9**: Die Vorlage bringt eine Beispielverteilung
  nach APO-S I mit; jede Schule trägt ihre eigene ein.
- **Fachraum-Zuweisung**: Konkrete Räume (z.B. CH-1, CH-2) werden gleichmäßig belegt.
- **Export**: Excel-Arbeitsmappen und PDF-Dateien mit Uhrzeiten, Pausenzeilen und
  Farbcodierung.
- **Terminal-Viewer**: Schnelle Ansicht einzelner Stundenpläne direkt im Terminal.
- **Validierung**: Unabhängige Nachprüfung der Lösung auf Konflikte und Fehler.
- **Qualitätsbericht**: Springstunden, Deputat-Einhaltung und Wunsch-freie Tage.
- **Vertretungshelfer**: Sofortvorschläge bei Lehrerausfall.

### Einschränkungen v1

- Nur Sekundarstufe I (Jg. 5–10). Oberstufe folgt in v2.
- Keine Kursschienen oder Lerngruppen über mehrere Jahrgänge.
- Raum-Zuweisung als Post-Processing (Greedy), kein Solver-integriertes Raummodell.

---

## Installation

```bash
# Abhängigkeiten installieren
pip install -r requirements.txt

# Ersteinrichtung (interaktiver Wizard)
python main.py setup
```

### requirements.txt (Auszug)

```
ortools>=9.9        # CP-SAT Solver
pydantic>=2.0       # Konfigurationsmodelle
ruamel.yaml>=0.18   # YAML mit Kommentaren
rich>=13.0          # Ausgabeformatierung
click>=8.0          # CLI-Framework
openpyxl>=3.1       # Excel-Export
fpdf2>=2.7          # PDF-Export
pytest>=7.0         # Tests
```

---

## Schnellstart

```bash
# 1. Einrichtung
python main.py setup

# 2. Testdaten + Stundenplan in einem Schritt
python main.py run

# 3. Ergebnis ansehen
python main.py show 5a       # Klasse 5a im Terminal
python main.py show MÜL      # Lehrer MÜL im Terminal
python main.py quality       # Qualitätsbericht
```

Die exportierten Dateien liegen in `output/export/`.

---

## CLI-Referenz

### Einrichtung

```bash
python main.py setup                   # Interaktiver Setup-Wizard
python main.py config show             # Aktuelle Konfiguration anzeigen
python main.py config edit             # Konfiguration interaktiv bearbeiten
```

### Datenverwaltung

```bash
python main.py generate                # Realistische Testdaten erzeugen
python main.py generate --export-json  # Testdaten + JSON speichern
python main.py generate --seed 123     # Reproduzierbare Daten (Seed)
python main.py generate --profile nrw-g9   # NRW-Gymnasium, knapp besetzt

python main.py template                # Excel-Import-Vorlage erzeugen
python main.py template --from-data output/school_data.json \
    --from-solution output/solution.json   # Vorlage aus Datensatz + Plan
python main.py import lehrkraefte.xlsx # Echte Schuldaten aus Excel importieren
python main.py validate                # Machbarkeits-Check (ohne Lösung)
python main.py validate --solution     # Lösung zusätzlich validieren
python main.py validate --generate --profile nrw-g9 --seed 43
                                       # Testdaten erzeugen und nur prüfen
```

#### Testdaten-Profile

`generate` und `validate --generate` kennen zwei Profile. Klassenzahl,
Zeitraster und Fachräume kommen in beiden aus der Konfiguration.

| | `loose` (Standard) | `nrw-g9` |
|---|---|---|
| Stundentafel | ältere Beispiel-Tafel (entspricht keinem Land) | NRW G9 (`config/nrw_g9.py`) |
| Lehrkräfte | feste Zahl aus der Konfiguration, zufällige Fächer | aus dem Bedarf je Fach abgeleitet; jedes Fach ist besetzt |
| Reserve (Soll über Bedarf) | rund 18 % | rund 4 % |
| Soll und Grenzen | 26 Stunden, Grenzen 16–32 | 25,5 Stunden, Grenzen Soll −2 bis +1 |
| Sek II | nicht berücksichtigt | ein Teil des Deputats liegt in der Sek II: geringeres Sek-I-Soll und Sperrzeiten in acht gemeinsamen Oberstufen-Schienen (Doppelstunden, für alle Lehrkräfte dieselben) |
| Teilzeit | rund 30 %, einzelne Wunschtage | rund 30 %, mit freiem Tag oder einer gesperrten Randstunde (1. oder 7. Stunde) |
| Kopplungen | drei Reli-Gruppen und zwei WPF-Gruppen je Jahrgang | eine Gruppe je Klasse: Religion/Praktische Philosophie, WPF, Sprachen-Schiene |

Das Profil `nrw-g9` ist für realistische Belastungstests gedacht. Die
Zusammenfassung zeigt den Unterrichtsbedarf in Lehrerstunden und die
Kapazitätsreserve. Die Stellschrauben (Sek-II-Anteile, Reserve,
Teilzeit) stehen in `NrwProfile` in `data/nrw_data.py`.

### Solver

```bash
python main.py solve                   # Stundenplan berechnen (optimiert)
python main.py solve --small           # Schnelltest mit 2 Klassen
python main.py solve --no-soft         # Nur harte Constraints (schneller)
python main.py solve --time-limit 120  # Zeitlimit in Sekunden
python main.py solve --diagnose        # Bei INFEASIBLE: Ursachen ermitteln
python main.py solve --weights gaps=200,double_lessons=80  # Gewichte anpassen
python main.py solve --verbose         # Solver-Fortschritt anzeigen
python main.py solve --single-stage    # Verteilung und Plan in einem Schritt
```

`solve` rechnet in zwei Stufen:

1. **Unterrichtsverteilung** (nur wenn sie Lücken hat): Ein kleines
   Modell ohne Zeitdimension entscheidet, wer welches Fach in welcher
   Klasse und welche Kopplungsgruppe übernimmt, möglichst nah am
   Soll-Deputat jeder Lehrkraft. Vorgaben aus dem Blatt
   *Unterrichtsverteilung*, Lehrkräfte von Kopplungsgruppen und
   gepinnte Stunden bleiben erhalten.
2. **Stundenplan**: Der Plan wird mit dieser Verteilung gerechnet.

Ist die Verteilung vollständig vorgegeben, entfällt Stufe 1. Stufe 1
bekommt höchstens ein Fünftel des Zeitlimits (maximal 60 s). Sie kennt
keine Zeiten: findet Stufe 2 für die berechnete Verteilung keinen Plan,
rechnet `--single-stage` beides in einem Schritt (deutlich langsamer).

Das Zeitlimit gilt für den ganzen Lauf: Modellaufbau, Warm-Start
(erste gültige Lösung) und Optimierung teilen sich die Zeit. Der
Warm-Start bekommt höchstens ein Drittel der Zeit nach dem Aufbau
(maximal 90 s), die Optimierung den Rest.

### Export

```bash
python main.py export                  # Excel + PDF exportieren
python main.py export --format excel   # Nur Excel
python main.py export --format pdf     # Nur PDF
python main.py export --output-dir mein_ordner/
```

### Terminal-Viewer

```bash
python main.py show 5a                 # Stundenplan Klasse 5a
python main.py show 10c                # Stundenplan Klasse 10c
python main.py show MÜL                # Stundenplan Lehrer MÜL
python main.py show SCH                # Stundenplan Lehrer SCH
```

Springstunden werden rot hinterlegt. Fächer sind farbcodiert nach Kategorie.

### Qualität und Analyse

```bash
python main.py quality                 # Qualitätsbericht im Terminal
python main.py quality --format excel  # Qualitätsbericht als Excel
```

### Vertretungshelfer

```bash
python main.py substitute --teacher MÜL           # Alle Stunden des Tages
python main.py substitute --teacher MÜL --day montag
python main.py substitute --teacher MÜL --day montag --slot 3
python main.py substitute --teacher MÜL --top 10  # Top-10-Kandidaten
```

### Pins (fixierte Stunden)

```bash
python main.py pin add MÜL 5a Ma 1 3   # MÜL unterrichtet 5a Mathe Mo Std.3
python main.py pin remove MÜL 1 3      # Pin entfernen
python main.py pin list                 # Alle Pins anzeigen
```

### Szenarien

```bash
python main.py scenario save mein-plan -d "Optimierter Plan"
python main.py scenario list
python main.py scenario load mein-plan
```

### Vollständiger Durchlauf

```bash
python main.py run                     # generate → solve → export
python main.py run --seed 42 --no-soft --format excel
```

---

## Konfiguration (YAML)

Die Konfigurationsdatei liegt unter `config/school_config.yaml`.

### Zeitraster

```yaml
time_grid:
  days_per_week: 5
  day_names: ["Mo", "Di", "Mi", "Do", "Fr"]

  lesson_slots:
    - {slot_number: 1, start_time: "07:35", end_time: "08:20"}
    - {slot_number: 2, start_time: "08:25", end_time: "09:10"}
    # ...
    - {slot_number: 7, start_time: "13:15", end_time: "14:00"}

  pauses:
    - {after_slot: 2, duration_minutes: 20, label: "Pause"}
    - {after_slot: 4, duration_minutes: 15, label: "Pause"}
    - {after_slot: 6, duration_minutes: 20, label: "Mittagspause"}

  # NUR diese Paare sind als Doppelstunde erlaubt:
  double_blocks:
    - {slot_first: 1, slot_second: 2}
    - {slot_first: 3, slot_second: 4}
    - {slot_first: 5, slot_second: 6}

  sek1_max_slot: 7     # Letzte Stunde für Sek-I-Klassen
  min_hours_per_day: 5
```

### Jahrgänge

```yaml
grades:
  grades:
    - {grade: 5,  num_classes: 6, weekly_hours_target: 30}
    - {grade: 6,  num_classes: 6, weekly_hours_target: 30}
    # ...
    - {grade: 10, num_classes: 6, weekly_hours_target: 32}
```

### Lehrkräfte

```yaml
teachers:
  total_count: 105
  vollzeit_deputat: 26       # Vollzeit-Wochenstunden
  teilzeit_percentage: 0.30  # 30% Teilzeitlehrkräfte
  deputat_min_fraction: 0.50 # Untergrenze = 50% der Obergrenze
  deputat_max_buffer: 6      # Obergrenze = Soll (aufgerundet) + 6h
  deputat_min_buffer: 2      # optional: Untergrenze = Soll (abgerundet) - 2h
```

Jede Lehrkraft hat ein **Soll-Deputat** (Spalte *Deputat* im Blatt
*Lehrkräfte*), auch mit halben Stunden wie `25,5`. Der Solver plant nur
ganze Stunden; aus dem Soll entstehen deshalb ganzzahlige harte Grenzen:

- Obergrenze = Soll aufgerundet + `deputat_max_buffer`
- Untergrenze = Soll abgerundet − `deputat_min_buffer`; ohne diese
  Angabe `deputat_min_fraction` der Obergrenze, aber nie über dem Soll

Beispiel mit beiden Puffern auf 2: Soll 25,5 → 23 bis 28 Stunden. Die
Voreinstellung (Puffer 6, Anteil 0.50) ergibt für 26 Stunden den sehr
weiten Bereich 16 bis 32.

Zusammenfassung nach `solve`, `show <Kürzel>`, Qualitätsbericht und
Exporte zeigen Soll, Ist und die Abweichung. Der Machbarkeits-Check
warnt, wenn die Summe der Soll-Deputate mehr als 5 % vom
Unterrichtsbedarf abweicht: dann kann nicht jede Lehrkraft ihr Soll
erreichen, egal wie der Plan aussieht.

### Solver-Gewichte

```yaml
solver:
  time_limit_seconds: 300
  weight_gaps: 200          # Springstunden minimieren
  weight_workload_balance: 50
  weight_double_lessons: 40
  weight_compact: 30
  weight_day_wishes: 20
  weight_deputat_deviation: 50  # Nähe zum Soll-Deputat (immer aktiv)
  subject_day_limit: true   # Regel C15 (siehe Constraint-Übersicht)
```

`subject_day_limit: false` schaltet die Regel C15 ab. Solver und
`validate --solution` lesen die Einstellung aus dem Datensatz
(`output/school_data.json`), in den die Konfiguration bei `generate`
und `import` übernommen wird.

---

## Excel-Import

Vorlage erzeugen und ausfüllen:

```bash
python main.py template           # erzeugt output/import_vorlage.xlsx
python main.py import meine_daten.xlsx
```

Die Vorlage enthält folgende Tabellenblätter:

| Sheet | Inhalt |
|-------|--------|
| Zeitraster | Slot-Nummern, Uhrzeiten, Sek-II-only-Flag |
| Jahrgänge | Jahrgang, Klassenanzahl, Soll-Stunden |
| Fächer | Fächerliste der Schule: Kürzel, Kategorie, Hauptfach, Fachraum-Typ, Doppelstunde |
| Stundentafel | Jahrgang × Fach = Wochenstunden (wird importiert; leere Zelle = Fach entfällt); vorausgefüllt mit einer Beispielverteilung für NRW G9 |
| Lehrkräfte | Name, Kürzel, Fächer, Deputat (Soll, auch `25,5`), Sperrzeiten |
| Fachräume | Raumtyp, Name, Anzahl (gilt beim Import auch für den Solver) |
| Kopplungen | Typ (`reli_ethik`, `wpf`, `band`), Klassen, Gruppen, Stunden, Fach der Stundentafel (aus Konfiguration und Stundentafel vorausgefüllt) |
| Unterrichtsverteilung | Klasse × Fach: Kürzel der Lehrkraft |

Sperrzeiten-Format in der Lehrkräfte-Liste: `Mo1,Di3,Fr5`
(Tag + Slot-Nummer, kommagetrennt)

Hinweise zum Import:
- Die Beispielzeile im Blatt *Lehrkräfte* beginnt mit `Beispiel:` und wird
  übersprungen. Eigene Zeilen dürfen nicht so beginnen.
- Fachnamen in *Stundentafel*, *Lehrkräfte* und *Unterrichtsverteilung*
  müssen im Blatt *Fächer* stehen (Groß-/Kleinschreibung egal). Ein
  unbekannter Name ist ein Fehler mit Zellbezug; ein ähnliches Fach wird
  nur vorgeschlagen, nie stillschweigend eingesetzt.
- Steht ein Raumtyp in mehreren Zeilen, werden die Räume zusammengezählt
  (mit Warnung).

### Eingebaute Stundentafel (NRW, Gymnasium G9)

Das Blatt *Stundentafel* ist mit einer Beispielverteilung für das
Gymnasium G9 in NRW vorausgefüllt (`config/nrw_g9.py`). Die Verordnung
(APO-S I, Anlage 3a) gibt nur Kontingente für Kl. 5–6 und Kl. 7–10
vor; die Verteilung auf die Jahrgänge beschließt jede Schule selbst.
Die Tafel ist also **eine** zulässige Verteilung, kein Vorschlag des
Landes. Bitte die Zahlen der eigenen Schule eintragen.

| Fach | 5 | 6 | 7 | 8 | 9 | 10 | Summe |
|------|---|---|---|---|---|---|---|
| Deutsch | 5 | 4 | 4 | 3 | 3 | 3 | 22 |
| Mathematik | 4 | 5 | 3 | 4 | 3 | 3 | 22 |
| Englisch | 5 | 4 | 4 | 3 | 3 | 3 | 22 |
| Physik | – | 2 | – | 2 | 2 | 2 | 8 |
| Chemie | – | – | 2 | 2 | 2 | 1 | 7 |
| Biologie | 2 | 2 | 2 | – | – | 2 | 8 |
| Informatik | – | 2 | – | – | – | – | 2 |
| Kunst | 2 | 2 | – | 2 | 2 | – | 8 |
| Musik | 2 | 1 | 2 | 2 | – | 2 | 9 |
| Sport | 4 | 3 | 3 | 3 | 3 | 2 | 18 |
| Geschichte | – | 2 | 2 | 2 | – | 2 | 8 |
| Erdkunde | 2 | – | 2 | – | 2 | 1 | 7 |
| Religion | 2 | 2 | 2 | 2 | 2 | 2 | 12 |
| 2. Fremdsprache | – | – | 4 | 4 | 4 | 3 | 15 |
| WPF | – | – | – | – | 3 | 3 | 6 |
| Wirtschaft-Politik | 2 | – | – | 2 | 2 | 2 | 8 |
| Ergänzungsstunde | – | 1 | 2 | 1 | 1 | 1 | 6 |
| **Summe** | **30** | **30** | **32** | **32** | **32** | **32** | **188** |

- 182 Kernstunden (59 in Kl. 5–6, 123 in Kl. 7–10) und alle
  6 Ergänzungsstunden, zusammen 188.
- *Religion* steht für Religionslehre/Praktische Philosophie und läuft
  wie *WPF* (Wahlpflicht, Kl. 9–10) über eine Kopplung.
- *2. Fremdsprache* (ab Kl. 7) läuft über eine **Sprachen-Schiene**:
  eine Kopplung vom Typ `band` je Jahrgang, in der alle Klassen
  gleichzeitig in Gruppen (Französisch, Latein) unterrichtet werden.
  Die Vorlage legt je Klasse eine Gruppe an, abwechselnd auf die
  Sprachen verteilt; die Sprachen stehen in der Konfiguration unter
  `couplings.second_language_subjects`. Anzahl und Fach der Gruppen
  lassen sich im Blatt *Kopplungen* ändern.
- Die Spalte *Fach der Stundentafel* im Blatt *Kopplungen* sagt, für
  welches Fach der Stundentafel die Gruppen zählen. Sie ist nur nötig,
  wenn dieses Fach anders heißt als die Fächer der Gruppen.
- Fehlt das Blatt *Stundentafel* in einer Mappe, gilt diese Tafel
  (früher: eine ältere Beispiel-Tafel, die keinem Land entsprach).

Der Machbarkeits-Check warnt, wenn ein Jahrgang den Wochenstundenrahmen
verlässt (NRW G9: 28–30 Stunden in Kl. 5–6, 30–33 in Kl. 7–10). Geprüft
wird nur bei `bundesland: NRW` und Schulform Gymnasium.

Die Testdaten im Profil `loose` (Standard von `main.py generate`)
nutzen die ältere Beispiel-Tafel (28, 31, 32, 32, 34, 34 Stunden), auf
die ihr Lehrkräfte-Pool abgestimmt ist. Der Check meldet dort deshalb
Jahrgänge außerhalb des Rahmens. Das Profil `nrw-g9` nutzt die
NRW-Tafel (siehe *Testdaten-Profile*).

### Eigene Fächer

Das Blatt **Fächer** ist die Fächerliste der Schule. Es ist mit den
üblichen Fächern vorausgefüllt (auch Wirtschaft-Politik, Praktische
Philosophie, Spanisch, Niederländisch, Ergänzungsstunde) und frei
erweiterbar.

| Spalte | Bedeutung |
|--------|-----------|
| Fach | Name, wie er in den anderen Blättern verwendet wird |
| Kürzel | Anzeige im Plan |
| Kategorie | `hauptfach`, `sprache`, `nw`, `musisch`, `sport`, `gesellschaft`, `wpf`, `sonstig` (bestimmt die Farbe) |
| Hauptfach | `ja` / `nein` |
| Fachraum-Typ | Raumtyp aus dem Blatt *Fachräume*; leer = Klassenraum |
| Doppelstunde | `nein`, `bevorzugt` oder `Pflicht` |

Ein neues Fach braucht eine Zeile im Blatt *Fächer*, eine Zeile mit
demselben Namen im Blatt *Stundentafel* und mindestens eine Lehrkraft
mit diesem Fach. Fehlt das Blatt *Fächer* (ältere Mappen), gilt die
vorgeschlagene Liste.

### Unterrichtsverteilung vorgeben

Im Blatt **Unterrichtsverteilung** steht pro Klasse eine Zeile und pro
Fach eine Spalte. In die Zelle kommt das Kürzel der Lehrkraft, die das
Fach in dieser Klasse unterrichtet.

| Klasse | Deutsch | Mathematik | Physik | Religion |
|--------|---------|------------|--------|----------|
| 5a     | MÜL     |            | –      | Kopplung |
| 7a     | BE      | BT         | SHR    | Kopplung |

- **Leere Zelle**: der Solver entscheidet.
- **`–`**: die Klasse hat das Fach nicht (nichts eintragen).
- **`Kopplung`**: das Fach läuft über eine Kopplung. Die Lehrkraft wird im
  Blatt *Kopplungen* als vierter Teil der Gruppe angegeben:
  `evangelisch:Religion:2:SHN,ethik:Ethik:2:WAR`.

Der Import meldet Fehler mit Zellbezug (z.B. `Unterrichtsverteilung B2
(Klasse 5a, Fach Deutsch): Unbekanntes Kürzel 'XYZ'`). Der
Machbarkeits-Check prüft zusätzlich: Deputat-Max und unterrichtbare
Stunden nicht überschritten (je Tag das Minimum aus Tagesmaximum und
Stunden ohne Sperrzeit), Deputat-Min noch erreichbar, genau eine
Lehrkraft pro Klasse und Fach. Fachfremder Einsatz ist erlaubt und
ergibt eine Warnung.

Eine ausgefüllte Vorlage aus vorhandenen Daten erzeugen (z.B. um die
Verteilung eines berechneten Plans anzusehen, zu ändern und wieder zu
importieren):

```bash
python main.py template -o output/verteilung.xlsx \
    --from-data output/school_data.json \
    --from-solution output/solution.json
python main.py import output/verteilung.xlsx --save-json
```

Der Solver hält sich an jede Vorgabe (auch fachfremde) und erzeugt für
vorgegebene Klasse-Fach-Paare nur noch Variablen für diese eine
Lehrkraft. Eine vollständige Verteilung verkleinert das Modell bei 36
Klassen von rund 174.000 auf rund 30.000 Variablen. Ablauf:

```bash
python main.py import output/verteilung.xlsx --save-json
python main.py solve
python main.py show 5a
```

---

## Architektur

```
stundenplan/
├── config/          Konfigurationssystem (Pydantic + YAML + Wizard)
├── models/          Datenmodelle (Subject, Teacher, SchoolClass, ...)
├── data/            Datengenerierung und Excel-Import
├── solver/          CP-SAT Solver, Pinning, Constraint-Relaxer
├── analysis/        Validierung, Qualitätsbericht, Vertretungshelfer
├── export/          Excel- und PDF-Export
├── benchmarks/      Entwickler-Benchmark (Solver-Messungen)
└── main.py          CLI (click)
```

### Solver: Constraint-Übersicht

| # | Constraint | Typ |
|---|------------|-----|
| C1 | Genau ein Lehrer pro Klasse+Fach | Hart |
| C2 | Stundentafel vollständig erfüllt | Hart |
| C3 | Slot nur wenn zugewiesen | Hart |
| C4 | Kein Lehrer-Doppelbuchung | Hart |
| C5 | Kein Klassen-Doppelbuchung | Hart |
| C6 | Lehrer-Verfügbarkeit (Sperrzeiten) | Hart |
| C7 | Deputat-Grenzen (min/max) | Hart |
| C8 | Fachraum-Kapazität | Hart |
| C9 | Kompakter Klassenplan (keine Lücken) | Hart |
| C10 | Max Stunden/Tag (Lehrer) | Hart |
| C11 | Kopplungen korrekt modelliert | Hart |
| C12 | Doppelstunden nur in konfigurierten Blöcken | Hart |
| C13 | Doppelstunden-Anzahl erfüllt | Hart |
| C14 | Springstunden-Limit (optional) | Hart/Weich |
| C15 | Pro Klasse, Fach und Tag max. 1 Stunde oder 1 Doppelblock | Hart (abschaltbar) |
| S1 | Springstunden minimieren | Weich |
| S2 | Gleichmäßige Tagesverteilung | Weich |
| S3 | Wunsch-freie Tage honorieren | Weich |
| S4 | Kompakte Lehrerpläne | Weich |
| S5 | Optionale Doppelstunden fördern | Weich |
| S6 | Nähe zum Soll-Deputat je Lehrkraft (quadratisch) | Weich |

**C15 im Detail:** Zwei Stunden desselben Fachs am selben Tag sind nur
als konfigurierter Doppelstunden-Block (z.B. 1–2, 3–4, 5–6) erlaubt, drei
oder mehr nie. Die Regel gilt auch für Kopplungen (Reli/Ethik, WPF,
Sprachen-Schiene). `main.py validate --solution` prüft sie unabhängig
vom Solver (Verstoß: `subject_day_limit`). Kein Bundesland schreibt die
Regel vor; mit `solver.subject_day_limit: false` entfällt sie in Solver
und Validator. Dann verteilt nichts mehr ein Fach über die Woche: auch
drei Stunden desselben Fachs an einem Tag sind möglich. Das frühere Gewicht
`weight_subject_spread` ist ohne Wirkung und nur noch aus
Kompatibilitätsgründen in der Konfiguration erlaubt.

---

## Troubleshooting

### INFEASIBLE (kein Stundenplan gefunden)

```bash
python main.py solve --diagnose
```

Der Diagnose-Modus lockert Constraints schrittweise und meldet, welche
Einschränkung das Problem verursacht (Fachräume, Deputat, Kopplungen, ...).

Häufige Ursachen:
- **Zu wenig Fachlehrer**: Gesamtdeputat aller qualifizierten Lehrer <
  Gesamtbedarf des Fachs.
- **Deputat-Grenzen zu eng**: `deputat_min_fraction` zu hoch (empfohlen: 0.50).
- **Fachraum-Engpass**: Mehr gleichzeitige Kurse als Räume verfügbar.
- **Kopplungs-Konflikte**: Zu viele Klassen gleichzeitig im Kopplungs-Slot gebunden.

### Solver findet keine gute Lösung (schlechte Qualität)

- Zeitlimit erhöhen: `--time-limit 600`
- Soft-Gewichte anpassen: `--weights gaps=300,double_lessons=100`
- Solver-Parallelismus: `num_workers: 0` in der Config (= automatisch alle Kerne)

### Springstunden zu hoch

- `weight_gaps` erhöhen (Standard: 200)
- `max_gaps_per_week` in der Config setzen (Achtung: kann INFEASIBLE verursachen
  wenn Religionslehrer viele Kopplungs-Slots haben)

---

## Logging

Alle Läufe werden protokolliert in `output/stundenplan.log`.

```bash
python main.py solve --verbose   # Ausführliches Logging auf der Konsole
```

---

## Tests

```bash
pytest                                    # Alle Tests
pytest tests/test_solver.py              # Nur Solver-Tests
pytest tests/test_export.py              # Nur Export-Tests
pytest tests/test_analysis.py            # Nur Analyse-Tests
pytest -k "not full_36"                  # Ohne langsamen 36-Klassen-Test
pytest -m slow                           # Nur der 36-Klassen-Test
```

### Benchmark (für Entwickler)

Misst den Solver über mehrere Seeds und schreibt eine Tabelle nach
`output/benchmarks/`. Dient als Vorher/Nachher-Vergleich bei jeder
Solver-Änderung.

```bash
python3.14 -m benchmarks.run_benchmark --dataset loose-36 --seeds 3
python3.14 -m benchmarks.run_benchmark --dataset loose-36-fixed --seeds 3
python3.14 -m benchmarks.run_benchmark --seeds 1 --time-limit 60 \
    --label schnelltest
```

Datensätze: `loose-36` (Solver verteilt die Lehrkräfte selbst) und
`loose-36-fixed` (dieselben Daten mit vollständig vorgegebener
Unterrichtsverteilung). Seeds, deren generierte Daten den
Machbarkeits-Check nicht bestehen, werden übersprungen und unter der
Tabelle genannt.

| Spalte | Bedeutung |
|--------|-----------|
| Aufbau s | Zeit für den Modellaufbau |
| Erste Lösung s | Suchzeit bis zum ersten gültigen Plan |
| Gesamt s | Ganzer Lauf (Aufbau, Warm-Start, Optimierung); bleibt im Zeitlimit |
| Spätgewinn % | Anteil der Verbesserung in den letzten 20 % der Optimierungszeit (nahe 0 = ausgereift) |
| Fach-Häufungen | Klasse hat dasselbe Fach 3× oder öfter an einem Tag |
| Validator-Fehler | Verstöße laut unabhängiger Nachprüfung |

---

## v2 Roadmap

### v2.0 — Infrastruktur
- Per-Teacher Constraint Overrides (individuelle Limits)
- Data Versioning / Audit Trail
- Two-Pass Solver (schneller bei 36+ Klassen)
- Interaktiver Terminal-Viewer

### v2.1 — Oberstufe (Jg. 11–13)
- Slots 8–10 aktivieren (`is_sek2_only: true` → genutzt)
- Kurswahlsystem (LK/GK statt Klassen)
- Schüler-Konflikt-Prüfung und Kursschienen
- Integration mit Sek-I-Solver (gemeinsame Lehrer)

### v2.2 — Erweiterte Features
- Web-Interface
- Mehrere Schulformen (Realschule, Gesamtschule)
- Vollständige Solver-integrierte Raumzuweisung
- AG/Wahlunterricht (Nachmittag)
- Jahresplanung und Änderungsmanagement

---

## Lizenz

Dieses Projekt steht unter der MIT-Lizenz.
