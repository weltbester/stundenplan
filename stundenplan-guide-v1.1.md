# Stundenplan-Generator — Claude Code Prompts (v1.1)

## Anleitung

Arbeite die Phasen **der Reihe nach** ab. Kopiere jeweils den gesamten
Prompt-Block in Claude Code. Teste nach jeder Phase, bevor du zur nächsten
weitergehst.

**Geschätzte Gesamtdauer:** 4–6 Stunden iterative Arbeit.

### Wichtige Design-Entscheidungen für v1

- **Nur Sekundarstufe I** (Default: Jg. 5-10, 6×6=36 Klassen, konfigurierbar).
  Oberstufe folgt in v2.
- **Zeitraster vollständig konfigurierbar**: Anzahl Slots, Uhrzeiten, Pausen,
  Doppelstunden-Blöcke — alles in der YAML-Config und im Wizard einstellbar.
  Default: 7 Stunden/Tag mit Pausen nach 2., 4. und 6. Stunde.
  Doppelstunden-Blöcke: 1-2, 3-4, 5-6. Stunde 7 steht allein.
- **Klassenverteilung pro Jahrgang konfigurierbar** (nicht alle Jahrgänge
  müssen gleich viele Klassen haben).
- **Lehrer-Klassen-Zuweisungen sind TEIL des Solvers**.
- **Kopplungen** korrekt klassenübergreifend modelliert.
- **Doppelstunden mit ungerader Stundenzahl** explizit behandelt.
- **Fake-Daten mit absichtlichen Engpässen** für realistische Tests.

---

## Phase 0 — Projekt-Setup + Konfigurationssystem

```
# Stundenplan-Generator für ein deutsches Gymnasium
# Phase 0: Projektstruktur, Konfigurationssystem und Setup-Wizard

## Projektbeschreibung
Erstelle ein Python-Projekt für einen Stundenplan-Generator eines deutschen
Gymnasiums, Sekundarstufe I. Schulstruktur, Zeitraster und alle Parameter
sind VOLLSTÄNDIG konfigurierbar über YAML und einen Setup-Wizard.

- Default: 36 Klassen (6 Jahrgänge × 6 Klassen), 105 Lehrkräfte
- Default: 7 Stunden/Tag, 5 Tage/Woche
- Google OR-Tools CP-SAT als Constraint Solver

WICHTIG: Oberstufe (Jg. 11-13) ist in v1 NICHT enthalten.

Code-Sprache: Englisch (Variablen, Klassen, Funktionen).
Kommentare, Logging, Benutzer-Interaktion: Deutsch.

## Projektstruktur

stundenplan/
├── config/
│   ├── __init__.py
│   ├── schema.py            # Pydantic-Modelle für die gesamte Konfiguration
│   ├── wizard.py            # Interaktiver Setup-Wizard (Ersteinrichtung)
│   ├── manager.py           # Config laden/speichern/validieren/editieren
│   └── defaults.py          # Standardwerte für Gymnasium Sek I
├── models/
│   ├── __init__.py
│   ├── teacher.py
│   ├── school_class.py
│   ├── subject.py
│   ├── room.py
│   ├── timeslot.py
│   └── coupling.py
├── data/
│   ├── __init__.py
│   ├── fake_data.py         # Testdaten-Generator (nutzt Config)
│   └── excel_import.py      # Excel-Import für echte Schuldaten
├── solver/
│   └── __init__.py
├── export/
│   └── __init__.py
├── scenarios/
│   └── .gitkeep
├── output/
│   └── .gitkeep
├── main.py
├── requirements.txt
└── README.md

## Konfigurationssystem (config/)

### config/schema.py — Pydantic-Modelle

Nutze Pydantic v2 BaseModel mit Field(). Jeder Parameter hat einen
deutschen Kommentar. ALLES ist konfigurierbar.

```python
from pydantic import BaseModel, Field, model_validator
from typing import Optional
from enum import Enum


class SchoolType(str, Enum):
    GYMNASIUM = "gymnasium"
    REALSCHULE = "realschule"
    GESAMTSCHULE = "gesamtschule"


# ─── ZEITRASTER (vollständig konfigurierbar) ───

class LessonSlot(BaseModel):
    """Eine einzelne Unterrichtsstunde im Tagesraster."""
    slot_number: int          # 1-basiert (1. Stunde, 2. Stunde, ...)
    start_time: str           # "07:35"
    end_time: str             # "08:20"
    is_sek2_only: bool = False  # Nur für Oberstufe (in v1 ignoriert)

class PauseSlot(BaseModel):
    """Eine Pause zwischen Unterrichtsstunden."""
    after_slot: int           # Nach welcher Stunde (z.B. 2 = nach 2. Stunde)
    duration_minutes: int     # Dauer in Minuten
    label: str = "Pause"      # Optional: "Große Pause", "Mittagspause"

class DoubleBlock(BaseModel):
    """Ein erlaubter Doppelstunden-Block.
    
    Doppelstunden dürfen NUR innerhalb dieser Blöcke stattfinden!
    Eine Doppelstunde über eine Pause hinweg ist VERBOTEN.
    """
    slot_first: int           # Erste Stunde (z.B. 1)
    slot_second: int          # Zweite Stunde (z.B. 2)

class TimeGridConfig(BaseModel):
    """Vollständig konfigurierbares Zeitraster.
    
    Das Zeitraster definiert:
    - Welche Unterrichtsstunden es pro Tag gibt (mit Uhrzeiten)
    - Wo Pausen liegen
    - Welche Stunden-Paare als Doppelstunde erlaubt sind
    - Wie viele Tage pro Woche unterrichtet wird
    """
    days_per_week: int = Field(5, ge=5, le=6,
        description="Unterrichtstage pro Woche")
    day_names: list[str] = Field(
        default=["Mo", "Di", "Mi", "Do", "Fr"],
        description="Namen der Wochentage")
    
    lesson_slots: list[LessonSlot] = Field(
        description="Alle Unterrichtsstunden des Tages mit Uhrzeiten")
    
    pauses: list[PauseSlot] = Field(
        description="Pausen zwischen den Stunden")
    
    double_blocks: list[DoubleBlock] = Field(
        description="Erlaubte Doppelstunden-Blöcke (NUR diese Paare!)")
    
    sek1_max_slot: int = Field(7,
        description="Letzte Stunde für Sek-I-Klassen")
    
    min_hours_per_day: int = Field(5, ge=3, le=8,
        description="Minimale Stunden pro Tag für Klassen")
    
    @model_validator(mode='after')
    def validate_double_blocks(self):
        """Prüfe dass Doppelstunden-Blöcke aufeinanderfolgen und
        NICHT über eine Pause gehen."""
        slot_numbers = {s.slot_number for s in self.lesson_slots}
        pause_afters = {p.after_slot for p in self.pauses}
        for db in self.double_blocks:
            assert db.slot_first in slot_numbers, \
                f"Block-Start {db.slot_first} existiert nicht"
            assert db.slot_second in slot_numbers, \
                f"Block-Ende {db.slot_second} existiert nicht"
            assert db.slot_second == db.slot_first + 1, \
                f"Block {db.slot_first}-{db.slot_second} nicht aufeinanderfolgend"
            assert db.slot_first not in pause_afters, \
                f"Block {db.slot_first}-{db.slot_second} geht über Pause!"
        return self


# ─── JAHRGÄNGE + KLASSEN (pro Jahrgang konfigurierbar) ───

class GradeDefinition(BaseModel):
    """Definition eines einzelnen Jahrgangs."""
    grade: int                          # z.B. 5
    num_classes: int = Field(ge=1, le=10)  # Parallelklassen
    class_labels: Optional[list[str]] = None  
    # Optional: ["a","b","c","d","e","f"]. Wenn None → auto-generiert.
    weekly_hours_target: int = Field(30, ge=25, le=38,
        description="Soll-Wochenstunden für diesen Jahrgang")

class GradeConfig(BaseModel):
    """Konfiguration aller Jahrgänge.
    
    Pro Jahrgang kann die Anzahl der Klassen unterschiedlich sein!
    Beispiel: Jg.5 hat 6 Klassen, Jg.10 hat nur 5 wegen Abgängen.
    """
    grades: list[GradeDefinition] = Field(
        description="Definition jedes Jahrgangs")
    
    @property
    def total_classes(self) -> int:
        return sum(g.num_classes for g in self.grades)
    
    @property
    def grade_numbers(self) -> list[int]:
        return [g.grade for g in self.grades]


# ─── LEHRKRÄFTE ───

class TeacherConfig(BaseModel):
    """Lehrkräfte-Konfiguration (globale Defaults)."""
    total_count: int = Field(105, ge=10,
        description="Gesamtzahl Lehrkräfte")
    vollzeit_deputat: int = Field(26, ge=20, le=30,
        description="Wochenstunden Vollzeit-Deputat")
    teilzeit_percentage: float = Field(0.30, ge=0.0, le=1.0,
        description="Anteil Teilzeit-Lehrkräfte")
    teilzeit_deputat_min: int = Field(12,
        description="Minimum Deputat Teilzeit")
    teilzeit_deputat_max: int = Field(20,
        description="Maximum Deputat Teilzeit")
    max_hours_per_day: int = Field(6, ge=4, le=8,
        description="Max Unterrichtsstunden pro Tag (globaler Default)")
    max_gaps_per_day: int = Field(1, ge=0, le=3,
        description="Max Springstunden pro Tag (globaler Default)")
    max_gaps_per_week: int = Field(3, ge=0, le=10,
        description="Max Springstunden pro Woche (globaler Default)")
    deputat_tolerance: int = Field(1, ge=0, le=3,
        description="Erlaubte Abweichung vom Soll-Deputat (±)")


# ─── FACHRÄUME ───

class SpecialRoomDef(BaseModel):
    """Definition eines Fachraumtyps."""
    room_type: str           # "physik", "chemie", etc.
    display_name: str        # "Physik-Raum"
    count: int = Field(ge=0) # Anzahl verfügbarer Räume

class RoomConfig(BaseModel):
    """Fachraum-Konfiguration. Beliebig erweiterbar."""
    special_rooms: list[SpecialRoomDef] = Field(
        description="Liste aller Fachraumtypen mit Anzahl")
    # Normale Klassenräume werden als unbegrenzt modelliert
    
    def get_capacity(self, room_type: str) -> int:
        for r in self.special_rooms:
            if r.room_type == room_type:
                return r.count
        return 999  # Kein Fachraum = unbegrenzt


# ─── KOPPLUNGEN ───

class CouplingConfig(BaseModel):
    """Kopplungs-Konfiguration.
    
    WICHTIG: Kopplungen können KLASSENÜBERGREIFEND sein!
    Bei Reli/Ethik werden Schüler aus Parallelklassen gemischt.
    ALLE beteiligten Klassen müssen im Kopplungs-Slot frei sein.
    """
    reli_ethik_enabled: bool = Field(True,
        description="Religion/Ethik-Kopplung aktiv")
    reli_groups: list[str] = Field(
        default=["evangelisch", "katholisch", "ethik"],
        description="Gruppen für Reli/Ethik")
    reli_ethik_cross_class: bool = Field(True,
        description="Klassenübergreifend (Parallelklassen gemischt)")
    reli_ethik_hours: int = Field(2,
        description="Wochenstunden Reli/Ethik")
    wpf_enabled: bool = Field(True,
        description="Wahlpflichtfächer aktiv")
    wpf_start_grade: int = Field(9,
        description="Ab welchem Jahrgang WPF")
    wpf_subjects: list[str] = Field(
        default=["Informatik", "Spanisch", "Darst. Spiel",
                 "Ernährungslehre"],
        description="Angebotene WPF-Fächer")
    wpf_hours: int = Field(3,
        description="Wochenstunden WPF")
    wpf_cross_class: bool = Field(True,
        description="WPF klassenübergreifend")


# ─── SOLVER ───

class SolverConfig(BaseModel):
    """Solver-Konfiguration und Optimierungsgewichte."""
    time_limit_seconds: int = Field(300, ge=30, le=3600,
        description="Zeitlimit Solver (Sekunden)")
    num_workers: int = Field(0, ge=0,
        description="CPU-Kerne (0=automatisch)")
    weight_gaps: int = Field(100, ge=0,
        description="Gewicht: Springstunden minimieren")
    weight_workload_balance: int = Field(50, ge=0,
        description="Gewicht: Gleichmäßige Tagesverteilung")
    weight_day_wishes: int = Field(20, ge=0,
        description="Gewicht: Wunsch-freie Tage")
    weight_compact: int = Field(30, ge=0,
        description="Gewicht: Kompakte Lehrer-Pläne")
    weight_double_lessons: int = Field(40, ge=0,
        description="Gewicht: Optionale Doppelstunden")
    weight_subject_spread: int = Field(60, ge=0,
        description="Gewicht: Hauptfächer über Woche verteilen")


# ─── GESAMT-CONFIG ───

class SchoolConfig(BaseModel):
    """Gesamtkonfiguration der Schule."""
    school_name: str = Field("Muster-Gymnasium",
        description="Name der Schule")
    school_type: SchoolType = Field(SchoolType.GYMNASIUM)
    bundesland: str = Field("NRW")
    time_grid: TimeGridConfig
    grades: GradeConfig
    teachers: TeacherConfig = Field(default_factory=TeacherConfig)
    rooms: RoomConfig
    couplings: CouplingConfig = Field(default_factory=CouplingConfig)
    solver: SolverConfig = Field(default_factory=SolverConfig)
```

### config/defaults.py — Vordefinierte Defaults

Da TimeGridConfig, GradeConfig und RoomConfig keine einfachen Defaults
haben (sie enthalten verschachtelte Listen), erstelle Factory-Funktionen:

```python
def default_time_grid() -> TimeGridConfig:
    """Standard-Zeitraster eines typischen Gymnasiums.
    
    Stundenraster:
    1. Stunde  07:35 - 08:20
    2. Stunde  08:25 - 09:10
       ── Pause (20 min) ──
    3. Stunde  09:30 - 10:15
    4. Stunde  10:20 - 11:05
       ── Pause (15 min) ──
    5. Stunde  11:20 - 12:05
    6. Stunde  12:10 - 12:55
       ── Mittagspause (20 min) ──
    7. Stunde  13:15 - 14:00
    
    Doppelstunden-Blöcke: 1-2, 3-4, 5-6
    Stunde 7 steht allein (nach Mittagspause, kein Partner).
    Doppelstunden über Pausen hinweg sind VERBOTEN.
    
    Stunden 8-10 (SII only) sind hier bereits definiert aber als
    is_sek2_only=True markiert → werden in v1 vom Solver ignoriert.
    """
    return TimeGridConfig(
        days_per_week=5,
        day_names=["Mo", "Di", "Mi", "Do", "Fr"],
        lesson_slots=[
            LessonSlot(slot_number=1, start_time="07:35", end_time="08:20"),
            LessonSlot(slot_number=2, start_time="08:25", end_time="09:10"),
            LessonSlot(slot_number=3, start_time="09:30", end_time="10:15"),
            LessonSlot(slot_number=4, start_time="10:20", end_time="11:05"),
            LessonSlot(slot_number=5, start_time="11:20", end_time="12:05"),
            LessonSlot(slot_number=6, start_time="12:10", end_time="12:55"),
            LessonSlot(slot_number=7, start_time="13:15", end_time="14:00"),
            LessonSlot(slot_number=8, start_time="14:00", end_time="14:45",
                       is_sek2_only=True),
            LessonSlot(slot_number=9, start_time="14:45", end_time="15:30",
                       is_sek2_only=True),
            LessonSlot(slot_number=10, start_time="15:30", end_time="16:15",
                       is_sek2_only=True),
        ],
        pauses=[
            PauseSlot(after_slot=2, duration_minutes=20, label="Pause"),
            PauseSlot(after_slot=4, duration_minutes=15, label="Pause"),
            PauseSlot(after_slot=6, duration_minutes=20,
                      label="Mittagspause"),
        ],
        double_blocks=[
            DoubleBlock(slot_first=1, slot_second=2),
            DoubleBlock(slot_first=3, slot_second=4),
            DoubleBlock(slot_first=5, slot_second=6),
            # Stunde 7 hat keinen Partner → keine Doppelstunde möglich
            # Stunden 8-10 (SII): 9-10 wäre ein Block für v2
        ],
        sek1_max_slot=7,
        min_hours_per_day=5,
    )


def default_grades() -> GradeConfig:
    """Standard: 6 Jahrgänge × 6 Klassen = 36 Klassen."""
    return GradeConfig(
        grades=[
            GradeDefinition(grade=5, num_classes=6,
                weekly_hours_target=30),
            GradeDefinition(grade=6, num_classes=6,
                weekly_hours_target=31),
            GradeDefinition(grade=7, num_classes=6,
                weekly_hours_target=32),
            GradeDefinition(grade=8, num_classes=6,
                weekly_hours_target=32),
            GradeDefinition(grade=9, num_classes=6,
                weekly_hours_target=34),
            GradeDefinition(grade=10, num_classes=6,
                weekly_hours_target=34),
        ]
    )


def default_rooms() -> RoomConfig:
    """Standard-Fachräume eines großen Gymnasiums."""
    return RoomConfig(
        special_rooms=[
            SpecialRoomDef(room_type="physik",
                display_name="Physik-Raum", count=3),
            SpecialRoomDef(room_type="chemie",
                display_name="Chemie-Raum", count=2),
            SpecialRoomDef(room_type="biologie",
                display_name="Bio-Raum", count=2),
            SpecialRoomDef(room_type="informatik",
                display_name="Informatik-Raum", count=2),
            SpecialRoomDef(room_type="kunst",
                display_name="Kunst-Raum", count=2),
            SpecialRoomDef(room_type="musik",
                display_name="Musik-Raum", count=2),
            SpecialRoomDef(room_type="sport",
                display_name="Sporthalle", count=3),
        ]
    )


def default_school_config() -> SchoolConfig:
    """Komplette Default-Konfiguration."""
    return SchoolConfig(
        school_name="Muster-Gymnasium",
        school_type=SchoolType.GYMNASIUM,
        bundesland="NRW",
        time_grid=default_time_grid(),
        grades=default_grades(),
        rooms=default_rooms(),
    )

# Stundentafel: Jahrgang → Fach → Wochenstunden
# Muss zum weekly_hours_target des Jahrgangs passen!
STUNDENTAFEL_GYMNASIUM_SEK1 = {
    5:  {"Deutsch": 4, "Mathematik": 4, "Englisch": 4,
         "Biologie": 2, "Erdkunde": 2, "Geschichte": 2,
         "Politik": 1, "Kunst": 2, "Musik": 2,
         "Religion": 2, "Sport": 3,
         "Physik": 0, "Chemie": 0, "Informatik": 0,
         "Latein": 0, "Französisch": 0, "WPF": 0},  # = 28 + Diff.

    # ... vollständig für Jg. 5-10 ausfüllen.
    # Ab 6: Latein ODER Französisch (2. Fremdsprache, 4h)
    # Ab 7: Physik (2h), Chemie (2h) kommen dazu
    # Ab 9: WPF (3h), Informatik möglich
    # Jeder Jahrgang muss zum weekly_hours_target passen!
}

# Fach-Metadaten
SUBJECT_METADATA = {
    "Deutsch":     {"short": "De", "category": "hauptfach",
                    "is_hauptfach": True, "room": None,
                    "double_required": False, "double_preferred": True},
    "Mathematik":  {"short": "Ma", "category": "hauptfach",
                    "is_hauptfach": True, "room": None,
                    "double_required": False, "double_preferred": True},
    "Englisch":    {"short": "En", "category": "sprache",
                    "is_hauptfach": True, "room": None,
                    "double_required": False, "double_preferred": True},
    "Physik":      {"short": "Ph", "category": "nw",
                    "is_hauptfach": False, "room": "physik",
                    "double_required": True, "double_preferred": False},
    "Chemie":      {"short": "Ch", "category": "nw",
                    "is_hauptfach": False, "room": "chemie",
                    "double_required": True, "double_preferred": False},
    "Biologie":    {"short": "Bi", "category": "nw",
                    "is_hauptfach": False, "room": "biologie",
                    "double_required": True, "double_preferred": False},
    "Informatik":  {"short": "If", "category": "nw",
                    "is_hauptfach": False, "room": "informatik",
                    "double_required": True, "double_preferred": False},
    "Kunst":       {"short": "Ku", "category": "musisch",
                    "is_hauptfach": False, "room": "kunst",
                    "double_required": True, "double_preferred": False},
    "Musik":       {"short": "Mu", "category": "musisch",
                    "is_hauptfach": False, "room": "musik",
                    "double_required": True, "double_preferred": False},
    "Sport":       {"short": "Sp", "category": "sport",
                    "is_hauptfach": False, "room": "sport",
                    "double_required": True, "double_preferred": False},
    "Geschichte":  {"short": "Ge", "category": "gesellschaft",
                    "is_hauptfach": False, "room": None,
                    "double_required": False, "double_preferred": False},
    "Erdkunde":    {"short": "Ek", "category": "gesellschaft",
                    "is_hauptfach": False, "room": None,
                    "double_required": False, "double_preferred": False},
    "Politik":     {"short": "Pk", "category": "gesellschaft",
                    "is_hauptfach": False, "room": None,
                    "double_required": False, "double_preferred": False},
    "Religion":    {"short": "Re", "category": "gesellschaft",
                    "is_hauptfach": False, "room": None,
                    "double_required": False, "double_preferred": False},
    "Ethik":       {"short": "Et", "category": "gesellschaft",
                    "is_hauptfach": False, "room": None,
                    "double_required": False, "double_preferred": False},
    "Latein":      {"short": "La", "category": "sprache",
                    "is_hauptfach": True, "room": None,
                    "double_required": False, "double_preferred": True},
    "Französisch": {"short": "Fr", "category": "sprache",
                    "is_hauptfach": True, "room": None,
                    "double_required": False, "double_preferred": True},
}
```

### config/wizard.py — Interaktiver Setup-Wizard

Nutze `rich` für schöne Konsolenausgabe (Tabellen, Farben, Prompts).

Der Wizard soll in Schritten durch alle Konfigurationsbereiche führen:

1. **Begrüßung**: "Willkommen beim Stundenplan-Generator! v1 unterstützt
   Sekundarstufe I. Oberstufe folgt in v2."
2. **Schule**: Name, Typ, Bundesland
3. **Zeitraster**:
   - "Möchten Sie das Standard-Zeitraster verwenden?" (Anzeigen als Tabelle)
   - Wenn ja → Defaults übernehmen
   - Wenn nein → Stunde für Stunde eingeben:
     - Anzahl Stunden pro Tag
     - Pro Stunde: Start/Ende-Uhrzeit
     - Pausen definieren (nach welchen Stunden, Dauer)
     - Doppelstunden-Blöcke definieren (welche Stundenpaare)
     - Validierung: Blöcke dürfen NICHT über Pausen gehen!
4. **Jahrgänge und Klassen**:
   - "Welche Jahrgänge? (z.B. 5-10)"
   - Pro Jahrgang: "Wie viele Parallelklassen in Jahrgang X?" [6]
   - Pro Jahrgang: Soll-Wochenstunden [30-34]
   - Zeige Summe: "Gesamt: 36 Klassen in 6 Jahrgängen"
5. **Lehrkräfte**: Anzahl, Deputat, Teilzeit-Anteil, Toleranz
6. **Fachräume**:
   - "Möchten Sie die Standard-Fachräume verwenden?" (Anzeigen)
   - Wenn nein: Raumtypen hinzufügen/entfernen/ändern
7. **Kopplungen**: Reli/Ethik, WPF (wie bisher)
8. **Solver-Gewichte**: Erklärung + Eingabe
9. **Zusammenfassung** als rich.Table → Bestätigung
10. **Speichern** als YAML

Bei jedem Schritt: Default in Klammern, Enter = übernehmen,
Validierung via Pydantic, deutsche Fehlermeldungen.

### config/manager.py — Config-Manager

```python
class ConfigManager:
    CONFIG_DIR = Path("config")
    DEFAULT_CONFIG = CONFIG_DIR / "school_config.yaml"
    SCENARIOS_DIR = Path("scenarios")

    def load(self, path: Optional[Path] = None) -> SchoolConfig:
        """Lade Config aus YAML. Validiert via Pydantic."""

    def save(self, config: SchoolConfig, path: Optional[Path] = None):
        """Speichere als YAML mit deutschen Kommentaren (ruamel.yaml)."""

    def edit_interactive(self, config: SchoolConfig) -> SchoolConfig:
        """Interaktives Menü:
          1. Zeitraster (Stunden, Pausen, Blöcke)
          2. Jahrgänge & Klassen
          3. Lehrkräfte
          4. Fachräume
          5. Kopplungen
          6. Solver-Gewichte
          0. Speichern & Zurück
        """

    def save_scenario(self, config: SchoolConfig, name: str,
                      description: str = ""): ...
    def list_scenarios(self) -> list[dict]: ...
    def load_scenario(self, name: str) -> SchoolConfig: ...
    def first_run_check(self) -> bool:
        return not self.DEFAULT_CONFIG.exists()
```

### YAML-Ausgabe mit Kommentaren (ruamel.yaml)

Beispiel der generierten YAML-Datei:

```yaml
# ============================================
# Stundenplan-Generator — Schulkonfiguration
# Version: 1.1 (Sekundarstufe I)
# Erstellt: 2025-02-17
# ============================================

school_name: "Gymnasium Remigianum Borken"
school_type: gymnasium
bundesland: "NRW"

# ─── Zeitraster ───
# Definiert Unterrichtsstunden, Pausen und erlaubte Doppelstunden-Blöcke.
# Doppelstunden über Pausen hinweg sind NICHT erlaubt.
time_grid:
  days_per_week: 5
  day_names: ["Mo", "Di", "Mi", "Do", "Fr"]
  
  lesson_slots:
    - {slot_number: 1,  start_time: "07:35", end_time: "08:20"}
    - {slot_number: 2,  start_time: "08:25", end_time: "09:10"}
    - {slot_number: 3,  start_time: "09:30", end_time: "10:15"}
    - {slot_number: 4,  start_time: "10:20", end_time: "11:05"}
    - {slot_number: 5,  start_time: "11:20", end_time: "12:05"}
    - {slot_number: 6,  start_time: "12:10", end_time: "12:55"}
    - {slot_number: 7,  start_time: "13:15", end_time: "14:00"}
    # SII-only (ignoriert in v1):
    - {slot_number: 8,  start_time: "14:00", end_time: "14:45", is_sek2_only: true}
    - {slot_number: 9,  start_time: "14:45", end_time: "15:30", is_sek2_only: true}
    - {slot_number: 10, start_time: "15:30", end_time: "16:15", is_sek2_only: true}
  
  pauses:
    - {after_slot: 2, duration_minutes: 20, label: "Pause"}
    - {after_slot: 4, duration_minutes: 15, label: "Pause"}
    - {after_slot: 6, duration_minutes: 20, label: "Mittagspause"}
  
  # NUR diese Paare sind als Doppelstunde erlaubt:
  double_blocks:
    - {slot_first: 1, slot_second: 2}   # Block 1-2
    - {slot_first: 3, slot_second: 4}   # Block 3-4
    - {slot_first: 5, slot_second: 6}   # Block 5-6
    # Stunde 7 hat keinen Partner
  
  sek1_max_slot: 7
  min_hours_per_day: 5

# ─── Jahrgänge & Klassen ───
# Pro Jahrgang konfigurierbar: Klassenanzahl und Soll-Wochenstunden.
grades:
  grades:
    - {grade: 5,  num_classes: 6, weekly_hours_target: 30}
    - {grade: 6,  num_classes: 6, weekly_hours_target: 31}
    - {grade: 7,  num_classes: 6, weekly_hours_target: 32}
    - {grade: 8,  num_classes: 6, weekly_hours_target: 32}
    - {grade: 9,  num_classes: 6, weekly_hours_target: 34}
    - {grade: 10, num_classes: 6, weekly_hours_target: 34}

# ─── Lehrkräfte ───
teachers:
  total_count: 105
  vollzeit_deputat: 26
  teilzeit_percentage: 0.30
  teilzeit_deputat_min: 12
  teilzeit_deputat_max: 20
  max_hours_per_day: 6       # Globaler Default
  max_gaps_per_day: 1
  max_gaps_per_week: 3
  deputat_tolerance: 1

# ─── Fachräume ───
rooms:
  special_rooms:
    - {room_type: "physik",     display_name: "Physik-Raum",     count: 3}
    - {room_type: "chemie",     display_name: "Chemie-Raum",     count: 2}
    - {room_type: "biologie",   display_name: "Bio-Raum",        count: 2}
    - {room_type: "informatik", display_name: "Informatik-Raum", count: 2}
    - {room_type: "kunst",      display_name: "Kunst-Raum",      count: 2}
    - {room_type: "musik",      display_name: "Musik-Raum",      count: 2}
    - {room_type: "sport",      display_name: "Sporthalle",      count: 3}

# ─── Kopplungen ───
couplings:
  reli_ethik_enabled: true
  reli_groups: ["evangelisch", "katholisch", "ethik"]
  reli_ethik_cross_class: true
  reli_ethik_hours: 2
  wpf_enabled: true
  wpf_start_grade: 9
  wpf_subjects: ["Informatik", "Spanisch", "Darst. Spiel", "Ernährungslehre"]
  wpf_hours: 3
  wpf_cross_class: true

# ─── Solver ───
# Gewichte: höher = stärker optimiert. 0 = deaktiviert.
solver:
  time_limit_seconds: 300
  num_workers: 0
  weight_gaps: 100
  weight_workload_balance: 50
  weight_day_wishes: 20
  weight_compact: 30
  weight_double_lessons: 40
  weight_subject_spread: 60
```

## CLI (main.py) — click
```
python main.py setup                   # Ersteinrichtung (Wizard)
python main.py config edit             # Konfiguration bearbeiten
python main.py config show             # Konfiguration anzeigen
python main.py generate                # Fake-Daten erzeugen
python main.py solve                   # Stundenplan berechnen
python main.py export                  # Excel + PDF exportieren
python main.py run                     # generate → solve → export
python main.py scenario save/load/list # Szenarien verwalten
```

Beim ERSTEN Aufruf: Prüfe config/school_config.yaml → wenn nicht
vorhanden, automatisch Wizard starten.

## requirements.txt
```
ortools>=9.9
pydantic>=2.0
ruamel.yaml>=0.18
rich>=13.0
click>=8.0
openpyxl>=3.1
fpdf2>=2.7
pytest>=7.0
```

## Tests
- Config mit Defaults erstellen → YAML speichern → laden → validieren
- Ungültige Werte: Pydantic Fehler korrekt
- Doppelstunden-Block über Pause → Validierungsfehler
- Wizard (mock input) → korrekte Config
- main.py --help funktioniert
```

**→ Test nach Phase 0:**
```bash
pip install -r requirements.txt
python main.py setup
python main.py config show
```

---

## Phase 1 — Datenmodell + Fake-Data-Generator

```
# Phase 1: Datenmodell, Fake-Data-Generator, Excel-Import

## Kontext
Phase 0 ist abgeschlossen. SchoolConfig mit konfigurierbarem Zeitraster
und Jahrgängen existiert. Nutze die Config für ALLES.

## models/ — Datenmodelle (Pydantic v2)

### models/subject.py
```python
class Subject(BaseModel):
    name: str
    short_name: str
    category: str       # hauptfach/sprache/nw/musisch/sport/gesellschaft
    requires_special_room: Optional[str] = None
    double_lesson_required: bool = False
    double_lesson_preferred: bool = False
    is_hauptfach: bool = False
```

### models/teacher.py
```python
class Teacher(BaseModel):
    id: str                     # Kürzel ("MÜL")
    name: str                   # "Müller, Hans"
    subjects: list[str]         # Unterrichtbare Fächer
    deputat: int                # Wochen-Soll
    is_teilzeit: bool
    unavailable_slots: list[tuple[int, int]] = []  # (day, slot_number)
    preferred_free_days: list[int] = []  # 0=Mo..4=Fr
    max_hours_per_day: int
    max_gaps_per_day: int
```

### models/school_class.py
```python
class SchoolClass(BaseModel):
    id: str              # "5a", "10f"
    grade: int
    label: str           # "a".."f"
    curriculum: dict[str, int]  # Fach → Wochenstunden
    max_slot: int        # Letzte erlaubte Stunde (aus Config)
```

### models/room.py
```python
class Room(BaseModel):
    id: str              # "PH1", "CH2"
    room_type: str
    name: str
```

### models/coupling.py
```python
class CouplingGroup(BaseModel):
    group_name: str      # "evangelisch", "Informatik-WPF"
    subject: str
    hours_per_week: int

class Coupling(BaseModel):
    id: str                        # "reli_5", "wpf_9"
    coupling_type: str             # "reli_ethik" / "wpf"
    involved_class_ids: list[str]  # ALLE beteiligten Klassen
    groups: list[CouplingGroup]
    hours_per_week: int
    cross_class: bool = True
```

## data/fake_data.py — Testdaten-Generator

### WICHTIG: Absichtliche Engpässe!

Die Daten müssen LÖSBAR sein, aber den Solver fordern:

1. **Chemie-Engpass**: 1 Lehrer zu wenig → Auslastung >95%
2. **Fachraum-Engpass**: 2 Chemie-Räume reichen gerade so
3. **Freitag-Cluster**: 4 Teilzeit-Lehrer wollen alle Fr frei
4. **Stark eingeschränkter Lehrer**: Mo+Fr gesperrt, Di nur Std. 1-3
5. **Knapper Pool**: Gesamtdeputate nur 5-8% über Gesamtbedarf

```python
class FakeDataGenerator:
    def __init__(self, config: SchoolConfig):
        self.config = config

    def generate(self) -> SchoolData:
        subjects = self._generate_subjects()
        rooms = self._generate_rooms()
        classes = self._generate_classes(subjects)
        teachers = self._generate_teachers(subjects)
        couplings = self._generate_couplings(classes)
        return SchoolData(...)
```

### Lehrer-Generierung (105 Stk)
- Realistische deutsche Vor- und Nachnamen
- Kürzel: 3 Buchstaben Nachname (Duplikate: variieren)
- Gewichtete Fächerkombinationen: Ma+Ph, De+Ge, En+Fr, Bio+Ch,
  En+Sp, Ek+Pk, Ku allein, Mu allein, etc.
- 30% Teilzeit: Deputat 12-20h, 1-2 Wunschtage
- Gesperrte Slots bei Teilzeit-Lehrern

### Klassen-Generierung
- Iteriere über config.grades.grades
- Pro GradeDefinition: Erstelle num_classes Klassen
- Curriculum aus STUNDENTAFEL_GYMNASIUM_SEK1[grade]
- max_slot = config.time_grid.sek1_max_slot
- Prüfe: Summe Curriculum ≈ weekly_hours_target (±2)

### Kopplungen
- Reli/Ethik: Pro Jahrgang EINE Kopplung über alle 6 Klassen
- WPF: Ab wpf_start_grade, über alle 6 Klassen des Jahrgangs
- involved_class_ids korrekt befüllt

### SchoolData + Feasibility-Check
```python
class SchoolData(BaseModel):
    subjects: list[Subject]
    rooms: list[Room]
    classes: list[SchoolClass]
    teachers: list[Teacher]
    couplings: list[Coupling]
    config: SchoolConfig

    def summary(self) -> str: ...
    def validate_feasibility(self) -> FeasibilityReport: ...
    def save_json(self, path: Path): ...
    @classmethod
    def load_json(cls, path: Path) -> "SchoolData": ...

class FeasibilityReport(BaseModel):
    is_feasible: bool
    errors: list[str]
    warnings: list[str]
```

Feasibility prüft:
1. Pro Fach: Gesamtbedarf ≤ Fachlehrer-Kapazität
2. Fachräume: Bedarf/Slots ≤ Raumanzahl
3. Jeder Lehrer: freie Slots ≥ Deputat
4. Kopplungen: genug qualifizierte Lehrer
5. Gesamtbilanz: Summe Deputate ≥ Summe Bedarf
Bei Fehler: Klare Meldung + Lösungsvorschlag.

### Zeitraster-Nutzung im Generator

Der Generator muss das konfigurierte Zeitraster beachten:
- Verfügbare Sek-I-Slots: Nur slots wo is_sek2_only=False
  UND slot_number ≤ sek1_max_slot
- Gesamte Sek-I-Slots pro Woche = sek1_slots × days_per_week
  (Default: 7 × 5 = 35)
- Bei Lehrer-Sperrzeiten: Nutze (day, slot_number) Paare

## data/excel_import.py

1. **Template-Generator**: Leeres Excel mit:
   - Sheet "Zeitraster": Slot-Nr, Start, Ende, SII-only (vorausgefüllt)
   - Sheet "Jahrgänge": Jahrgang, Klassen, Soll-Stunden
   - Sheet "Stundentafel": Jahrgang × Fächer Matrix (vorausgefüllt)
   - Sheet "Lehrkräfte": Name, Kürzel, Fach1-3, Deputat, Teilzeit,
     Sperren (Format "Mo1,Di3,Fr5"), Wunschtage, MaxStd/Tag, MaxSpringstd
   - Sheet "Fachräume": Raumtyp, Name, Anzahl
   - Sheet "Kopplungen": Jahrgang, Typ, Klassen, Gruppen, Stunden
   - Formatierung, Dropdowns, Beispielzeilen (kursiv)

2. **Import-Funktion**: Excel → SchoolData
   - Validierung jedes Eintrags, deutsche Fehlermeldungen
   - Fuzzy matching für Fächer ("Phyisk" → "Physik?")
   - Import des Zeitrasters → überschreibt Config.time_grid
   - FeasibilityReport nach Import

## CLI
```
python main.py generate                  # Fake-Daten
python main.py generate --export-json    # + JSON speichern
python main.py template                  # Import-Vorlage erzeugen
python main.py import <datei.xlsx>       # Excel importieren
python main.py validate                  # Feasibility-Check
```

## Tests
- Generierte Daten: 36 Klassen, 105 Lehrer, Stressfaktoren vorhanden
- Feasibility-Check mit kaputten Daten → korrekte Fehler
- Excel-Template Roundtrip (erzeugen → einlesen)
- Korrekte Slot-Nutzung (nur Sek-I-Slots)
- Verschiedene Konfigurationen (5×4, 6×6, gemischt) testen
```

**→ Test nach Phase 1:**
```bash
python main.py generate
python main.py validate
python main.py template
```

---

## Phase 2 — Kern-Solver (Harte Constraints)

```
# Phase 2: CP-SAT Solver mit harten Constraints

## Kontext
Phase 0+1 fertig. SchoolConfig mit konfigurierbarem Zeitraster und
SchoolData mit 36 Klassen + Engpässen existieren.

WICHTIG: 
- Der Solver nutzt NUR Sek-I-Slots (slot_number ≤ sek1_max_slot,
  is_sek2_only=False)
- Doppelstunden nur in konfigurierten double_blocks erlaubt
- Lehrer-Zuweisungen sind TEIL des Solvers

## solver/scheduler.py

### Slot-Index-Mapping
Erstelle zu Beginn ein Mapping von (day, slot_number) → interner Index.
NUR Sek-I-Slots aufnehmen:
```python
self.sek1_slots = [
    s for s in config.time_grid.lesson_slots
    if not s.is_sek2_only and s.slot_number <= config.time_grid.sek1_max_slot
]
# Default: 7 Slots pro Tag × 5 Tage = 35 Slot-Indizes
self.slot_index = {}
for day in range(config.time_grid.days_per_week):
    for slot in self.sek1_slots:
        self.slot_index[(day, slot.slot_number)] = len(self.slot_index)
```

### Doppelstunden-Block-Lookup
```python
self.valid_double_starts = set()
for db in config.time_grid.double_blocks:
    if db.slot_second <= config.time_grid.sek1_max_slot:
        self.valid_double_starts.add(db.slot_first)
# Default: {1, 3, 5} — Doppelstunde startet bei 1, 3 oder 5
```

### Entscheidungsvariablen

#### Ebene 1: Zuweisung (wer unterrichtet was)
```
assign[t, c, s] ∈ {0, 1}
```
Nur erstellen wenn Lehrer t Fach s kann UND Klasse c Fach s braucht
UND es kein Kopplungsfach ist.

#### Ebene 2: Zeitslots (wann)
```
slot[t, c, s, day, slot_nr] ∈ {0, 1}
```
Nur erstellen wenn assign[t,c,s] möglich UND (day, slot_nr) ein
gültiger Sek-I-Slot ist.

Verknüpfung: slot ≤ assign (Slot nur wenn zugewiesen)

#### Kopplungs-Variablen
```
coupling_slot[k, day, slot_nr] ∈ {0, 1}
coupling_assign[k, group_idx, teacher_id] ∈ {0, 1}
```

### Harte Constraints

1. **Genau ein Lehrer pro Klasse+Fach**:
   Für jede (c, s): Summe assign[t,c,s] über alle t = 1

2. **Stundentafel erfüllt**:
   Für jede (c, s): Summe slot[t,c,s,d,h] über alle t,d,h = curriculum[c][s]

3. **Slot ≤ Assign**: slot[t,c,s,d,h] ≤ assign[t,c,s]

4. **Kein Lehrer-Konflikt**:
   Für jeden Lehrer t, (d,h): Summe slot[t,*,*,d,h] + coupling ≤ 1

5. **Kein Klassen-Konflikt**:
   Für jede Klasse c, (d,h): Summe slot[*,c,*,d,h] + coupling ≤ 1

6. **Verfügbarkeit**: Gesperrte (d,h) → alle slots des Lehrers = 0

7. **Deputat (±Toleranz)**:
   deputat - tol ≤ Summe aller Stunden des Lehrers ≤ deputat + tol

8. **Fachraum-Kapazität**:
   Für jeden Raumtyp r, (d,h):
   Summe aller slots mit Fach das Raum r braucht ≤ rooms.get_capacity(r)

9. **Kompakter Klassenplan (keine Lücken)**:
   class_active[c,d,h] = OR(alle slots für c bei d,h)
   class_active[c,d,h] ≥ class_active[c,d,h+1]
   (Nur für aufeinanderfolgende Sek-I-Slots!)

10. **Max Stunden/Tag (Lehrer)**:
    Summe pro Lehrer pro Tag ≤ max_hours_per_day

11. **Kopplungen**:
    - Summe coupling_slot[k,d,h] = k.hours_per_week
    - ALLE involved_classes frei im Kopplungs-Slot
    - Genau 1 qualifizierter Lehrer pro Gruppe

### Solver-Setup
```python
solver = cp_model.CpSolver()
solver.parameters.max_time_in_seconds = config.solver.time_limit_seconds
solver.parameters.num_workers = config.solver.num_workers or os.cpu_count()
solver.parameters.log_search_progress = True
```

### Progress-Callback mit rich
Zeige: Laufzeit, Lösungsanzahl, Zielfunktionswert

### Ergebnis
```python
class ScheduleEntry(BaseModel):
    day: int              # 0-basiert
    slot_number: int      # 1-basiert (wie im Zeitraster!)
    teacher_id: str
    class_id: str
    subject: str
    room: Optional[str] = None
    is_coupling: bool = False
    coupling_id: Optional[str] = None

class TeacherAssignment(BaseModel):
    teacher_id: str
    class_id: str
    subject: str
    hours_per_week: int

class ScheduleSolution(BaseModel):
    entries: list[ScheduleEntry]
    assignments: list[TeacherAssignment]
    solver_status: str
    solve_time_seconds: float
    objective_value: Optional[float] = None
    num_variables: int
    num_constraints: int
    config_snapshot: SchoolConfig  # Config zum Zeitpunkt der Lösung

    def get_class_schedule(self, class_id: str) -> list[ScheduleEntry]: ...
    def get_teacher_schedule(self, teacher_id: str) -> list[ScheduleEntry]: ...
    def save_json(self, path: Path): ...
```

### Bei INFEASIBLE — Diagnostik
- Logge Variablen/Constraints
- Strukturierte Fehlermeldung mit Zahlen
- Hinweis: "python main.py solve --diagnose"

## solver/pinning.py
```python
class PinnedLesson(BaseModel):
    teacher_id: str
    class_id: str
    subject: str
    day: int
    slot_number: int    # 1-basiert!

class PinManager:
    """Fixierte Stunden als harte Constraints."""
    def add_pin(self, pin: PinnedLesson): ...
    def remove_pin(self, teacher_id: str, day: int, slot: int): ...
    def get_pins(self) -> list[PinnedLesson]: ...
    def apply_to_solver(self, solver: ScheduleSolver): ...
```

## CLI
```
python main.py solve [--time-limit N] [--small]
python main.py pin add MÜL 5a Ma Mo 1
python main.py pin remove MÜL Mo 1
python main.py pin list
```

## Tests
- Mini-Daten (2 Klassen, 8 Lehrer) → FEASIBLE
- Alle harten Constraints einzeln prüfen
- Lösungszeit mit 36 Klassen messen (Ziel: < 5 Min)
- Slot-Nummern korrekt (1-basiert wie Zeitraster)
```

**→ Test nach Phase 2:**
```bash
python main.py solve --small
python main.py solve
```

---

## Phase 3 — Doppelstunden + Soft Constraints

```
# Phase 3: Doppelstunden, weiche Constraints, Optimierung

## Kontext
Phase 0-2 fertig. Solver findet machbare Lösung für 36 Klassen.

## Doppelstunden — NUR in konfigurierten Blöcken!

KRITISCH: Doppelstunden dürfen NUR in den definierten double_blocks
stattfinden (Default: 1-2, 3-4, 5-6). Eine Doppelstunde 2-3 oder 6-7
wäre über eine Pause und ist VERBOTEN.

Stunde 7 (nach Mittagspause) hat im Default keinen Partner →
dort sind nur Einzelstunden möglich.

### Hilfsvariablen
```
double[t, c, s, day, block_start] ∈ {0, 1}
```
Wobei block_start ∈ valid_double_starts (Default: {1, 3, 5})

### Constraints (Pflicht-Doppelstunden)
Für Fächer mit double_required=True und N Wochenstunden:
- N_double = N // 2 (abgerundet)
- N_rest = N % 2 (0 oder 1 Einzelstunde)
- Summe double[t,c,s,d,b] über alle d,b = N_double

Sonderfälle:
- **N=1**: Keine Doppelstunde möglich! Warnung loggen, nur Einzelstd.
- **N=2**: Exakt 1 Doppelstunde, 0 Einzelstunden
- **N=3**: 1 Doppelstunde + 1 Einzelstunde (an ANDEREM Tag!)
- **N=4**: 2 Doppelstunden, 0 Einzelstunden
- **N=5**: 2 Doppelstunden + 1 Einzelstunde

Einzelstunde bei ungerader N:
- Muss an einem Tag liegen wo KEINE Doppelstunde des Fachs ist
- Kann in JEDEM Sek-I-Slot liegen (auch Stunde 7)

Verknüpfung double ↔ slot:
- double[t,c,s,d,b] = 1 → slot[t,c,s,d,b] = 1 UND slot[t,c,s,d,b+1] = 1
- double ≤ slot[...,b] und double ≤ slot[...,b+1]
- double ≥ slot[...,b] + slot[...,b+1] - 1

### Optionale Doppelstunden (weich)
Für double_preferred=True: Bonus in Zielfunktion.
Bonus NUR für Doppelstunden in gültigen Blöcken.

## Weiche Constraints (Zielfunktion)

Gewichte aus config.solver.weight_*.

### 1. Springstunden minimieren (weight_gaps)
Für Lehrer t, Tag d:
- teacher_active[t,d,h] für alle Sek-I-Slot-Nummern h
- ACHTUNG: "Springstunde" nur ZWISCHEN Stunden mit Unterricht,
  NICHT in der Mittagspause. Wenn ein Lehrer Std.6 und Std.7 hat,
  ist die Mittagspause dazwischen KEINE Springstunde
  (das ist eine reguläre Pause).
  ABER: Wenn ein Lehrer Std.5 und Std.7 hat (Std.6 frei), dann ist
  Std.6 eine Springstunde.
- Implementierung:
  Berechne Lücken NUR innerhalb der Unterrichtsstunden-Sequenz.
  gap_count = (last_active_slot - first_active_slot + 1) - teaching_count
  Bestrafe: gap_count * weight, extra wenn gap_count ≥ 2

### 2. Gleichmäßige Tagesverteilung (weight_workload_balance)
- Minimiere max(hours[t,d]) - min(hours[t,d]) pro Lehrer
- Klassen: Hauptfächer auf verschiedene Tage verteilen

### 3. Wunsch-freie Tage (weight_day_wishes)
- Bonus wenn preferred_free_days nicht benutzt

### 4. Kompakte Lehrer-Pläne (weight_compact)
- Freistunden am Rand bevorzugen

### 5. Optionale Doppelstunden (weight_double_lessons)
- Bonus für Doppelstunden bei preferred-Fächern

### 6. Hauptfach-Verteilung (weight_subject_spread)
- Max 1 Stunde pro Hauptfach pro Tag (außer Doppelstd.)

### Zielfunktion
```python
self.model.Minimize(sum(all_penalties))
```

## solver/constraint_relaxer.py

Bei INFEASIBLE: Systematische Diagnose.
1. Ohne Doppelstunden-Pflicht → lösbar?
2. Ohne Fachraum-Limits → lösbar?
3. Ohne Kopplungen → lösbar?
4. Mit mehr Deputat-Toleranz → lösbar?
5. Bericht: "Lösbar wenn X gelockert wird."

## CLI
```
python main.py solve [--no-soft] [--diagnose] [--weights gaps=200]
```

## Tests
- Doppelstunden: N=1,2,3,4,5 korrekt
- Doppelstunden NUR in gültigen Blöcken (nie über Pause)
- Keine Doppelstunde an Stunde 7 (kein Partner)
- Springstunden-Berechnung: Mittagspause ≠ Springstunde
- Qualitätsvergleich mit/ohne Optimierung
```

**→ Test nach Phase 3:**
```bash
python main.py solve --no-soft   # Baseline
python main.py solve             # Optimiert
```

---

## Phase 4 — Export (Excel + PDF)

```
# Phase 4: Excel- und PDF-Export

## Kontext
Phase 0-3 fertig. Optimierte Lösung existiert.

## WICHTIG: Export nutzt das konfigurierte Zeitraster!

Die Exports MÜSSEN das konfigurierte Zeitraster widerspiegeln:
- Uhrzeiten aus config.time_grid.lesson_slots
- Pausen als Trennzeilen/Linien in der Tabelle
- Doppelstunden-Blöcke visuell zusammengefasst
- Slot-Nummern (1-basiert) wie in der Config

## export/excel_export.py (openpyxl)

### Farbschema
```python
COLORS = {
    "hauptfach":    "B3D4FF",
    "sprache":      "FFF2B3",
    "nw":           "B3FFB3",
    "musisch":      "FFB3E6",
    "sport":        "FFD4B3",
    "gesellschaft": "D4B3FF",
    "sonstig":      "E0E0E0",
    "gap":          "FF9999",    # Springstunde
    "free":         "F0F0F0",    # Randfreistunde
    "coupling":     "FFFFB3",    # Kopplung
    "pause":        "FFFFFF",    # Pausenzeile
}
```

### Sheet "Übersicht"
- Schulname, Datum, Solver-Status, Lösungszeit
- Lehrkräfte-Tabelle: Kürzel, Name, Fächer, Soll/Ist, Springstd, Score
- Fachraum-Auslastung
- Qualitätsmetriken

### Sheet "Klasse [X]" (pro Klasse)
- Tabellenstruktur:
  ```
  Stunde  | Zeit          | Mo       | Di       | Mi       | Do       | Fr
  --------+---------------+----------+----------+----------+----------+------
  1       | 07:35 - 08:20 | Mathe    | Deutsch  | ...
  2       | 08:25 - 09:10 | MÜL     | SCH     |
  ~~~~~~~~ Pause ~~~~~~~~~~
  3       | 09:30 - 10:15 | ...
  4       | 10:20 - 11:05 |
  ~~~~~~~~ Pause ~~~~~~~~~~
  5       | 11:20 - 12:05 |
  6       | 12:10 - 12:55 |
  ~~~~~~ Mittagspause ~~~~~~
  7       | 13:15 - 14:00 |
  ```
- Uhrzeiten und Pausen aus der Config!
- Pausenzeilen: dünnere Zeile mit grauem Hintergrund + Label
- Doppelstunden: vertikal verbundene Zellen
- Farbcodierung nach Kategorie
- Kopplungen mit "(K)" markiert

### Sheet "Lehrer [Kürzel]" (pro Lehrer)
- Gleiche Tabellenstruktur mit Uhrzeiten + Pausen
- Springstunden: ROT
- Statistik-Box: Deputat, Springstunden, Wunschtage, Score

### Sheet "Raumbelegung"
- Pro Fachraumtyp: Belegungsplan
- Auslastungsquote

### Formatierung
- Spaltenbreite: Stunde=8, Zeit=15, Tage=20
- Zeilenhöhe: 60 (Inhaltszeilen), 20 (Pausenzeilen)
- Querformat, Druckbereich, "Auf eine Seite"

## export/pdf_export.py (fpdf2)

### klassen_stundenplaene.pdf
- 1 Seite pro Klasse, Querformat A4
- Header: Schulname | Klassenname | Schuljahr
- Tabelle MIT Uhrzeiten und Pausenzeilen
- Farbcodierung
- Footer: Datum | Seite X/Y

### lehrer_stundenplaene.pdf
- 1 Seite pro Lehrer, Querformat A4
- Header: Schulname | "MÜL — Müller, Hans" | Deputat
- Footer: Datum | Seite X/Y

## export/diff_export.py
- Vergleich alter/neuer Lösung
- Änderungen markiert (rot/grün)
- Qualitätsvergleich

## CLI
```
python main.py export [--format excel|pdf|both]
python main.py export --diff <old.json>
python main.py run    # generate → solve → export
```

## Tests
- Export öffnen → Uhrzeiten und Pausen korrekt
- Doppelstunden visuell verbunden
- Kopplungen markiert
- PDF lesbar
```

**→ Test nach Phase 4:**
```bash
python main.py run
# Excel + PDF manuell prüfen: Uhrzeiten, Pausen, Blöcke korrekt?
```

---

## Phase 5 — Validierung, Vertretungshelfer, Polish

```
# Phase 5: Validierung, Vertretung, Qualitätssicherung

## solver/validator.py — Unabhängige Nachprüfung

```python
class ScheduleValidator:
    def validate(self, solution: ScheduleSolution, data: SchoolData,
                 config: SchoolConfig) -> ValidationReport:
        errors, warnings = [], []
        self._check_teacher_conflicts(...)
        self._check_class_conflicts(...)
        self._check_curriculum(...)
        self._check_deputat(...)
        self._check_availability(...)
        self._check_rooms(...)
        self._check_couplings(...)     # Klassenübergreifend!
        self._check_compactness(...)
        self._check_double_lessons(...)  # Nur in gültigen Blöcken!
        self._check_gaps(...)            # Mittagspause ≠ Springstd!
        self._check_subject_spread(...)
        self._check_slot_validity(...)   # Nur Sek-I-Slots verwendet!
        return ValidationReport(errors=errors, warnings=warnings)
```

### Qualitätsbericht
```python
class TeacherQualityStats(BaseModel):
    teacher_id: str
    teacher_name: str
    deputat_soll: int
    deputat_ist: int
    gaps_per_day: dict[int, int]
    total_gaps: int
    free_days: list[int]
    wished_free_days: list[int]
    assignments: list[str]
    satisfaction_score: float  # 0.0 - 1.0

class QualityReport(BaseModel):
    teacher_stats: list[TeacherQualityStats]
    avg_gaps_per_teacher: float
    max_gaps_teacher: tuple[str, int]
    fulfilled_day_wishes: int
    total_day_wishes: int
    double_lesson_rate: float
    room_utilization: dict[str, float]
    overall_score: float
```

Satisfaction: 40% Springstunden, 30% Wunschtage, 20% Balance, 10% Doppelstd

## solver/substitution.py — Vertretungshelfer

```python
class SubstitutionFinder:
    def find_substitutes(self, absent_teacher_id: str,
                          day: int) -> list[SubstitutionOption]:
        """Pro Stunde des abwesenden Lehrers:
        1. Fachlehrer mit freiem Slot (beste Option)
        2. Fachfremder Lehrer mit freiem Slot
        3. Entfall/Zusammenlegung
        
        Berücksichtigt:
        - Stundenzahl des Vertreters an dem Tag
        - Ob Vertretung Springstunde erzeugt
        - Fachraum-Verfügbarkeit
        """

    def generate_vertretungsplan(self, absences, path): ...
```

## CLI (final)
```
python main.py setup
python main.py config show|edit
python main.py generate [--export-json]
python main.py template
python main.py import <datei.xlsx>
python main.py validate
python main.py solve [--time-limit N] [--small] [--no-soft] [--diagnose]
python main.py export [--format excel|pdf|both] [--diff <old.json>]
python main.py run
python main.py pin add|remove|list
python main.py scenario save|load|list <name>
python main.py substitute <Kürzel> <Tag>
python main.py quality
python main.py show <Klasse|Kürzel>
```

### Terminal-Viewer (show)
- Nutze rich.Table für Stundenplan im Terminal
- MIT Uhrzeiten und Pausenzeilen (aus Config!)
- Farbcodierung via rich.Style

## Logging
- logging + rich.logging.RichHandler
- INFO default, --verbose für DEBUG
- Logfile: output/stundenplan.log

## README.md (Deutsch)
- Projektbeschreibung
- Features (konfigurierbar: Zeitraster, Klassen, Räume, ...)
- Installation + Schnellstart
- CLI-Befehle (alle)
- Konfiguration erklärt (YAML-Struktur)
- Import-Format (Excel-Template)
- Architektur (Solver, Constraints)
- Troubleshooting
- Einschränkungen v1
- Roadmap v2

## Tests
- Validator: korrekt + fehlerhaft
- Substitution: bekanntes Setup
- Quality Score
- Doppelstunden N=1..5
- Kopplungen klassenübergreifend
- Slot-Validierung (nur Sek-I)
- End-to-End Smoke Test
```

**→ Finaler Test:**
```bash
python main.py run
python main.py quality
python main.py show 5a
python main.py show MÜL
python main.py substitute MÜL Mo
pytest
```

---

## v2 Roadmap

### v2.0 — Infrastruktur
- Mittagspause als Constraint (max 4 Std. am Stück ohne Pause)
- Per-Teacher Constraint Overrides
- Data Versioning / Audit Trail
- Two-Pass Solver (schneller bei 36+ Klassen)
- Erweiterter Terminal-Viewer (interaktiv)

### v2.1 — Oberstufe (Jg. 11-13)
- Slots 8-10 aktivieren (is_sek2_only=True → genutzt)
- Kurswahlsystem (LK/GK statt Klassen)
- Schüler-Konflikt-Prüfung
- Kursschienen
- Integration mit Sek-I-Solver (gemeinsame Lehrer)

### v2.2 — Erweiterte Features
- Web-Interface
- Mehrere Schulformen
- Vollständige Raum-Zuweisung
- AG/Wahlunterricht (Nachmittag)
- Jahresplanung

---

## Zusammenfassung

| Phase | Inhalt | Testkriterium |
|-------|--------|---------------|
| 0 | Config (Zeitraster, Klassen, Räume — alles konfigurierbar) | `setup` + `config show` |
| 1 | Fake Data (36 Klassen, Engpässe), Excel-Import | `generate` + `validate` |
| 2 | Solver (harte Constraints, solver-basierte Zuweisung) | `solve --small` → FEASIBLE |
| 3 | Doppelstunden (nur in Blöcken!), Optimierung | `solve` → bessere Qualität |
| 4 | Excel + PDF (mit Uhrzeiten + Pausen) | Dateien prüfen |
| 5 | Validierung, Vertretung, Quality, Terminal-Viewer | `pytest` grün |
