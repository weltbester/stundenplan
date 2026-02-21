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
    # Laufende Nummer der Stunde, 1-basiert (1. Stunde, 2. Stunde, ...)
    slot_number: int
    # Beginn der Stunde im Format "HH:MM"
    start_time: str
    # Ende der Stunde im Format "HH:MM"
    end_time: str
    # Nur für Oberstufe relevant (in v1 ignoriert)
    is_sek2_only: bool = False


class PauseSlot(BaseModel):
    """Eine Pause zwischen Unterrichtsstunden."""
    # Nach welcher Stunde die Pause folgt (z.B. 2 = nach 2. Stunde)
    after_slot: int
    # Dauer der Pause in Minuten
    duration_minutes: int
    # Optionale Bezeichnung, z.B. "Große Pause" oder "Mittagspause"
    label: str = "Pause"


class DoubleBlock(BaseModel):
    """Ein erlaubter Doppelstunden-Block.

    Doppelstunden dürfen NUR innerhalb dieser Blöcke stattfinden!
    Eine Doppelstunde über eine Pause hinweg ist VERBOTEN.
    """
    # Nummer der ersten Stunde des Blocks (z.B. 1)
    slot_first: int
    # Nummer der zweiten Stunde des Blocks (z.B. 2)
    slot_second: int


class TimeGridConfig(BaseModel):
    """Vollständig konfigurierbares Zeitraster.

    Das Zeitraster definiert:
    - Welche Unterrichtsstunden es pro Tag gibt (mit Uhrzeiten)
    - Wo Pausen liegen
    - Welche Stunden-Paare als Doppelstunde erlaubt sind
    - Wie viele Tage pro Woche unterrichtet wird
    """
    # Anzahl Unterrichtstage pro Woche (5 oder 6)
    days_per_week: int = Field(5, ge=5, le=6,
        description="Unterrichtstage pro Woche")
    # Namen der Wochentage
    day_names: list[str] = Field(
        default=["Mo", "Di", "Mi", "Do", "Fr"],
        description="Namen der Wochentage")
    # Alle Unterrichtsstunden des Tages mit Uhrzeiten
    lesson_slots: list[LessonSlot] = Field(
        description="Alle Unterrichtsstunden des Tages mit Uhrzeiten")
    # Pausen zwischen den Stunden
    pauses: list[PauseSlot] = Field(
        description="Pausen zwischen den Stunden")
    # Erlaubte Doppelstunden-Blöcke (NUR diese Paare sind zulässig!)
    double_blocks: list[DoubleBlock] = Field(
        description="Erlaubte Doppelstunden-Blöcke (NUR diese Paare!)")
    # Letzte Stunde für Sek-I-Klassen
    sek1_max_slot: int = Field(7,
        description="Letzte Stunde für Sek-I-Klassen")
    # Minimale Stunden pro Tag für Klassen
    min_hours_per_day: int = Field(5, ge=3, le=8,
        description="Minimale Stunden pro Tag für Klassen")

    @model_validator(mode='after')
    def validate_double_blocks(self):
        """Prüfe dass Doppelstunden-Blöcke aufeinanderfolgen und
        NICHT über eine Pause gehen."""
        slot_numbers = {s.slot_number for s in self.lesson_slots}
        pause_afters = {p.after_slot for p in self.pauses}
        for db in self.double_blocks:
            if db.slot_first not in slot_numbers:
                raise ValueError(
                    f"Block-Start {db.slot_first} existiert nicht im Zeitraster")
            if db.slot_second not in slot_numbers:
                raise ValueError(
                    f"Block-Ende {db.slot_second} existiert nicht im Zeitraster")
            if db.slot_second != db.slot_first + 1:
                raise ValueError(
                    f"Block {db.slot_first}-{db.slot_second} ist nicht aufeinanderfolgend")
            if db.slot_first in pause_afters:
                raise ValueError(
                    f"Block {db.slot_first}-{db.slot_second} würde über eine Pause gehen!")
        return self


# ─── JAHRGÄNGE + KLASSEN (pro Jahrgang konfigurierbar) ───

class GradeDefinition(BaseModel):
    """Definition eines einzelnen Jahrgangs."""
    # Jahrgangs-Nummer (z.B. 5, 6, 7, ...)
    grade: int
    # Anzahl Parallelklassen in diesem Jahrgang
    num_classes: int = Field(ge=1, le=10)
    # Optional: Bezeichnungen der Klassen (z.B. ["a","b","c","d","e","f"]).
    # Wenn None, werden sie automatisch generiert (a, b, c, ...).
    class_labels: Optional[list[str]] = None
    # Soll-Wochenstunden für diesen Jahrgang
    weekly_hours_target: int = Field(30, ge=25, le=38,
        description="Soll-Wochenstunden für diesen Jahrgang")


class GradeConfig(BaseModel):
    """Konfiguration aller Jahrgänge.

    Pro Jahrgang kann die Anzahl der Klassen unterschiedlich sein!
    Beispiel: Jg.5 hat 6 Klassen, Jg.10 hat nur 5 wegen Abgängen.
    """
    # Definition jedes einzelnen Jahrgangs
    grades: list[GradeDefinition] = Field(
        description="Definition jedes Jahrgangs")

    @property
    def total_classes(self) -> int:
        """Gesamtzahl aller Klassen über alle Jahrgänge."""
        return sum(g.num_classes for g in self.grades)

    @property
    def grade_numbers(self) -> list[int]:
        """Liste aller Jahrgangs-Nummern."""
        return [g.grade for g in self.grades]


# ─── LEHRKRÄFTE ───

class TeacherConfig(BaseModel):
    """Lehrkräfte-Konfiguration (globale Defaults)."""
    # Gesamtzahl der Lehrkräfte an der Schule
    total_count: int = Field(60, ge=10,
        description="Gesamtzahl Lehrkräfte")
    # Wochenstunden für Vollzeit-Deputat
    vollzeit_deputat: int = Field(26, ge=20, le=30,
        description="Wochenstunden Vollzeit-Deputat")
    # Anteil der Teilzeit-Lehrkräfte (0.0 bis 1.0)
    teilzeit_percentage: float = Field(0.30, ge=0.0, le=1.0,
        description="Anteil Teilzeit-Lehrkräfte")
    # Minimales Deputat für Teilzeit-Lehrkräfte
    teilzeit_deputat_min: int = Field(12,
        description="Minimum Deputat Teilzeit")
    # Maximales Deputat für Teilzeit-Lehrkräfte
    teilzeit_deputat_max: int = Field(20,
        description="Maximum Deputat Teilzeit")
    # Globaler Default: max. Unterrichtsstunden pro Tag
    max_hours_per_day: int = Field(6, ge=4, le=8,
        description="Max Unterrichtsstunden pro Tag (globaler Default)")
    # Globaler Default: max. Springstunden pro Tag
    max_gaps_per_day: int = Field(1, ge=0, le=3,
        description="Max Springstunden pro Tag (globaler Default)")
    # Globaler Default: max. Springstunden pro Woche
    max_gaps_per_week: int = Field(3, ge=0, le=10,
        description="Max Springstunden pro Woche (globaler Default)")
    # Mindestauslastung relativ zu deputat_max (0.5–1.0)
    deputat_min_fraction: float = Field(
        0.80, ge=0.5, le=1.0,
        description="Mindestauslastung relativ zu deputat_max (0.5–1.0)"
    )
    # Mehrarbeit-Puffer über dem Vertrags-Deputat (0–6h, typisch 1–3h)
    # Gibt dem Solver Spielraum; z.B. 2 → VZ-Lehrer kann bis zu 28h statt 26h zugewiesen bekommen.
    deputat_max_buffer: int = Field(
        2, ge=0, le=6,
        description="Mehrarbeit-Puffer über Deputat für Solver-Flexibilität (0–6h)"
    )


# ─── FACHRÄUME ───

class SpecialRoomDef(BaseModel):
    """Definition eines Fachraumtyps."""
    # Interner Bezeichner, z.B. "physik", "chemie"
    room_type: str
    # Anzeigename für den Nutzer, z.B. "Physik-Raum"
    display_name: str
    # Anzahl verfügbarer Räume dieses Typs
    count: int = Field(ge=0)


class RoomConfig(BaseModel):
    """Fachraum-Konfiguration. Beliebig erweiterbar."""
    # Liste aller Fachraumtypen mit jeweiliger Anzahl
    special_rooms: list[SpecialRoomDef] = Field(
        description="Liste aller Fachraumtypen mit Anzahl")
    # Normale Klassenräume werden als unbegrenzt modelliert.

    def get_capacity(self, room_type: str) -> int:
        """Gibt die Anzahl verfügbarer Räume für einen Raumtyp zurück.
        Bei unbekanntem Typ (kein Fachraum): 999 (= unbegrenzt)."""
        for r in self.special_rooms:
            if r.room_type == room_type:
                return r.count
        return 999


# ─── KOPPLUNGEN ───

class CouplingConfig(BaseModel):
    """Kopplungs-Konfiguration.

    WICHTIG: Kopplungen können KLASSENÜBERGREIFEND sein!
    Bei Reli/Ethik werden Schüler aus Parallelklassen gemischt.
    ALLE beteiligten Klassen müssen im Kopplungs-Slot frei sein.
    """
    # Gibt an ob Religion/Ethik-Kopplung aktiv ist
    reli_ethik_enabled: bool = Field(True,
        description="Religion/Ethik-Kopplung aktiv")
    # Gruppen für Religion/Ethik-Aufteilung
    reli_groups: list[str] = Field(
        default=["evangelisch", "katholisch", "ethik"],
        description="Gruppen für Reli/Ethik")
    # Ob Reli/Ethik klassenübergreifend stattfindet
    reli_ethik_cross_class: bool = Field(True,
        description="Klassenübergreifend (Parallelklassen gemischt)")
    # Wochenstunden für Religion/Ethik
    reli_ethik_hours: int = Field(2,
        description="Wochenstunden Reli/Ethik")
    # Gibt an ob Wahlpflichtfächer aktiv sind
    wpf_enabled: bool = Field(True,
        description="Wahlpflichtfächer aktiv")
    # Ab welchem Jahrgang WPF angeboten werden
    wpf_start_grade: int = Field(9,
        description="Ab welchem Jahrgang WPF")
    # Angebotene Wahlpflichtfächer
    wpf_subjects: list[str] = Field(
        default=["Informatik", "Französisch"],
        description="Angebotene WPF-Fächer (müssen in SUBJECT_METADATA vorhanden sein)")
    # Wochenstunden für WPF
    wpf_hours: int = Field(3,
        description="Wochenstunden WPF")
    # Ob WPF klassenübergreifend stattfindet
    wpf_cross_class: bool = Field(True,
        description="WPF klassenübergreifend")


# ─── SOLVER ───

class SolverConfig(BaseModel):
    """Solver-Konfiguration und Optimierungsgewichte."""
    # Zeitlimit für den Solver in Sekunden
    time_limit_seconds: int = Field(300, ge=30, le=3600,
        description="Zeitlimit Solver (Sekunden)")
    # Anzahl CPU-Kerne (0 = automatisch alle nutzen)
    num_workers: int = Field(0, ge=0,
        description="CPU-Kerne (0=automatisch)")
    # Gewicht für Minimierung von Springstunden
    weight_gaps: int = Field(200, ge=0,
        description="Gewicht: Springstunden minimieren")
    # Gewicht für gleichmäßige Verteilung der Arbeitslast
    weight_workload_balance: int = Field(50, ge=0,
        description="Gewicht: Gleichmäßige Tagesverteilung")
    # Gewicht für Berücksichtigung von Wunsch-freien Tagen
    weight_day_wishes: int = Field(20, ge=0,
        description="Gewicht: Wunsch-freie Tage")
    # Gewicht für kompakte Lehrer-Pläne (wenig Lücken)
    weight_compact: int = Field(30, ge=0,
        description="Gewicht: Kompakte Lehrer-Pläne")
    # Gewicht für optionale Doppelstunden
    weight_double_lessons: int = Field(40, ge=0,
        description="Gewicht: Optionale Doppelstunden")
    # Gewicht für Verteilung von Hauptfächern über die Woche
    weight_subject_spread: int = Field(60, ge=0,
        description="Gewicht: Hauptfächer über Woche verteilen")
    # Gewicht für Deputat-Auslastung (immer aktiv, auch bei --no-soft)
    # Minimiert sum(dep_max - actual): Solver strebt dep_max an; dep_min ist nur Sicherheitsboden.
    weight_deputat_deviation: int = Field(50, ge=0,
        description="Gewicht: Deputat-Auslastung maximieren (immer aktiv)")
    # Harte Obergrenze Springstunden pro Lehrer/Woche.
    # 0 = kein hartes Limit (empfohlen): kein deutsches Bundesland schreibt eine konkrete
    # Zahl vor. Stark gekoppelte Lehrer (Religion, WPF) haben strukturell 10-15 Lücken/Woche,
    # weil Kopplungszeiten durch Klassenkonflikte fixiert sind – ein enges Limit erzeugt INFEASIBLE.
    # Wer einen schulinternen Richtwert durchsetzen möchte, kann z. B. 14 oder 20 setzen.
    max_gaps_per_week: int = Field(0, ge=0,
        description="Max. Springstunden pro Lehrer/Woche (0=kein Limit, nur Soft-Minimierung)")


# ─── GESAMT-CONFIG ───

class SchoolConfig(BaseModel):
    """Gesamtkonfiguration der Schule."""
    # Name der Schule
    school_name: str = Field("Muster-Gymnasium",
        description="Name der Schule")
    # Schultyp (Gymnasium, Realschule, Gesamtschule)
    school_type: SchoolType = Field(SchoolType.GYMNASIUM)
    # Bundesland (für länderspezifische Regeln)
    bundesland: str = Field("NRW")
    # Vollständiges Zeitraster mit Stunden, Pausen und Blöcken
    time_grid: TimeGridConfig
    # Jahrgangskonfiguration mit Klassen und Wochenstunden
    grades: GradeConfig
    # Lehrkräfte-Konfiguration
    teachers: TeacherConfig = Field(default_factory=TeacherConfig)
    # Fachraum-Konfiguration
    rooms: RoomConfig
    # Kopplungs-Konfiguration (Reli/Ethik, WPF)
    couplings: CouplingConfig = Field(default_factory=CouplingConfig)
    # Solver-Konfiguration und Optimierungsgewichte
    solver: SolverConfig = Field(default_factory=SolverConfig)
