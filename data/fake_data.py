"""Testdaten-Generator für den Stundenplan-Generator.

Erzeugt realistische Fake-Daten mit absichtlichen Engpässen für robuste Tests.

Absichtliche Engpässe:
  1. Chemie-Engpass: Nur 2 Chemie-Lehrkräfte → Auslastung ~92%
  2. Fachraum-Engpass: 2 Chemie-Räume reichen gerade so
  3. Freitag-Cluster: 4 Teilzeit-Lehrkräfte wollen Fr frei
  4. Stark eingeschränkter Lehrer: Mo+Fr gesperrt, Di nur Std. 1-3
  5. Knapper Pool: Fach-spezifische Kapazität nahe am Bedarf

Lösbarkeits-Garantien (feste Lehrkräfte im Pool):
  - Mathematik: 2 dedizierte VZ-Lehrer → mind. 52h Kapazität
  - Englisch: 2 dedizierte VZ-Lehrer → mind. 52h Kapazität
  - Religion/Ethik: 3 dedizierte VZ-Lehrer (je mit regulärem Zweitfach)
  - WPF Informatik: 1 dedizierter VZ-Lehrer für Kopplungsgruppe
  - WPF Französisch: 1 dedizierter VZ-Lehrer für Kopplungsgruppe
"""

import random
import string
from typing import Optional

from config.schema import SchoolConfig
from config.defaults import STUNDENTAFEL_GYMNASIUM_SEK1, SUBJECT_METADATA
from models.teacher import Teacher
from models.school_class import SchoolClass
from models.subject import Subject
from models.room import Room
from models.coupling import Coupling, CouplingGroup
from models.school_data import SchoolData

# ─── Namens-Listen ────────────────────────────────────────────────────────────

_FIRST_NAMES_M = [
    "Andreas", "Bernd", "Christian", "Dieter", "Franz", "Hans", "Jürgen",
    "Klaus", "Ludwig", "Markus", "Michael", "Norbert", "Peter", "Stefan",
    "Thomas", "Tobias", "Ulrich", "Werner", "Yusuf", "Martin", "Robert",
    "Wolfgang", "Rainer", "Manfred", "Helmut", "Gerhard", "Günter",
]

_FIRST_NAMES_F = [
    "Anna", "Birgit", "Christine", "Eva", "Gabi", "Iris", "Kathrin",
    "Karin", "Lena", "Maria", "Olga", "Renate", "Sandra", "Tanja",
    "Ulrike", "Vera", "Xenia", "Zoe", "Monika", "Sabine", "Heike",
    "Ute", "Claudia", "Petra", "Ingrid", "Brigitte", "Elisabeth",
]

_LAST_NAMES = [
    "Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer",
    "Wagner", "Becker", "Schulz", "Hoffmann", "Schäfer", "Koch",
    "Bauer", "Richter", "Klein", "Wolf", "Schröder", "Neumann",
    "Schwarz", "Zimmermann", "Braun", "Krüger", "Hofmann", "Hartmann",
    "Lange", "Schmitt", "Werner", "Schmitz", "Krause", "Meier",
    "Lehmann", "Schmid", "Schulze", "Maier", "Köhler", "Herrmann",
    "Kaiser", "Fuchs", "Lang", "Weiß", "Berger", "Roth", "Simon",
    "Frank", "Berg", "Friedrich", "Engel", "Huber", "Vogel", "Beck",
]

# ─── Fächerkombinationen (gewichtet) ─────────────────────────────────────────
# WICHTIG: Chemie und Sport werden NICHT aufgenommen → separate Pflicht-Lehrer!
# (Analog zu Chemie-Engpass: Sport wird deterministisch über feste Lehrer abgedeckt.)

_SUBJECT_COMBOS: list[tuple[list[str], int]] = [
    (["Mathematik", "Physik"], 8),
    (["Deutsch", "Geschichte"], 8),
    (["Englisch", "Französisch"], 6),
    (["Biologie", "Erdkunde"], 5),
    (["Mathematik", "Informatik"], 5),
    (["Erdkunde", "Politik"], 5),
    (["Physik", "Informatik"], 4),
    (["Latein", "Deutsch"], 4),
    (["Geschichte", "Politik"], 4),
    (["Kunst", "Geschichte"], 4),   # Kein Kunst-Allein → Deputat via 2. Fach sicherbar
    (["Musik", "Deutsch"], 4),      # Kein Musik-Allein → Deputat via 2. Fach sicherbar
    (["Deutsch", "Kunst"], 3),
    (["Englisch", "Geschichte"], 3),
    (["Mathematik", "Deutsch"], 3),
    (["Musik", "Kunst"], 2),
    (["Französisch", "Latein"], 2),
    (["Englisch", "Politik"], 2),
    (["Biologie", "Physik"], 3),  # ersetzt Religion/Ethik-Kombos (die Kopplungs-Engpass erzeugten)
]

_COMBO_WEIGHTS = [w for _, w in _SUBJECT_COMBOS]
_COMBO_SUBJECTS = [s for s, _ in _SUBJECT_COMBOS]


def _make_abbreviation(last_name: str, used: set[str]) -> str:
    """Generiert ein eindeutiges 3-Zeichen-Kürzel aus dem Nachnamen."""
    base = (
        last_name.upper()
        .replace("Ä", "AE").replace("Ö", "OE").replace("Ü", "UE")
        .replace("ß", "SS")
    )
    # Kandidaten: erste 3 Buchstaben, dann Varianten
    candidates = [
        base[:3],
        base[:2] + base[-1],
        base[0] + base[2:4],
        base[:2] + str(len(used) % 10),
    ]
    for c in candidates:
        c = c[:3].ljust(3, "X")
        if c not in used:
            used.add(c)
            return c
    # Fallback: alphanumerisch
    while True:
        c = "".join(random.choices(string.ascii_uppercase, k=3))
        if c not in used:
            used.add(c)
            return c


class FakeDataGenerator:
    """Generiert vollständige Testdaten auf Basis der SchoolConfig."""

    def __init__(self, config: SchoolConfig, seed: Optional[int] = None) -> None:
        self.config = config
        self.rng = random.Random(seed)
        self._used_abbreviations: set[str] = set()

    # ─── Fächer ───────────────────────────────────────────────────────────────

    def _generate_subjects(self) -> list[Subject]:
        """Erzeugt alle Fächer aus den SUBJECT_METADATA."""
        subjects = []
        for name, meta in SUBJECT_METADATA.items():
            subjects.append(Subject(
                name=name,
                short_name=meta["short"],
                category=meta["category"],
                is_hauptfach=meta["is_hauptfach"],
                requires_special_room=meta["room"],
                double_lesson_required=meta["double_required"],
                double_lesson_preferred=meta["double_preferred"],
            ))
        return subjects

    # ─── Klassen ──────────────────────────────────────────────────────────────

    def _generate_classes(self) -> list[SchoolClass]:
        """Erzeugt alle Klassen gemäß GradeConfig mit Curriculum aus STUNDENTAFEL."""
        classes = []
        sek1_max = self.config.time_grid.sek1_max_slot

        for grade_def in self.config.grades.grades:
            grade = grade_def.grade
            labels = grade_def.class_labels
            if labels is None:
                labels = list(string.ascii_lowercase[:grade_def.num_classes])

            # Curriculum für diesen Jahrgang (nur Fächer mit > 0 Stunden)
            raw_curriculum = STUNDENTAFEL_GYMNASIUM_SEK1.get(grade, {})
            curriculum = {f: h for f, h in raw_curriculum.items() if h > 0}

            for label in labels[:grade_def.num_classes]:
                classes.append(SchoolClass(
                    id=f"{grade}{label}",
                    grade=grade,
                    label=label,
                    curriculum=curriculum.copy(),
                    max_slot=sek1_max,
                ))
        return classes

    # ─── Räume ────────────────────────────────────────────────────────────────

    def _generate_rooms(self) -> list[Room]:
        """Erzeugt alle Fachräume gemäß RoomConfig."""
        rooms = []
        for room_def in self.config.rooms.special_rooms:
            prefix = room_def.room_type[:2].upper()
            for i in range(1, room_def.count + 1):
                rooms.append(Room(
                    id=f"{prefix}{i}",
                    room_type=room_def.room_type,
                    name=f"{room_def.display_name} {i}",
                ))
        return rooms

    # ─── Lehrkräfte ───────────────────────────────────────────────────────────

    def _make_teacher(
        self,
        subjects: list[str],
        deputat: int,
        is_teilzeit: bool = False,
        preferred_free_days: Optional[list[int]] = None,
        unavailable_slots: Optional[list[tuple[int, int]]] = None,
    ) -> Teacher:
        """Erstellt eine Lehrkraft mit zufälligem Namen."""
        first_names = _FIRST_NAMES_F if self.rng.random() < 0.55 else _FIRST_NAMES_M
        first = self.rng.choice(first_names)
        last = self.rng.choice(_LAST_NAMES)
        abbr = _make_abbreviation(last, self._used_abbreviations)

        tc = self.config.teachers
        deputat_max = deputat + tc.deputat_max_buffer
        deputat_min = max(1, round(deputat_max * tc.deputat_min_fraction))
        return Teacher(
            id=abbr,
            name=f"{last}, {first}",
            subjects=subjects,
            deputat_max=deputat_max,
            deputat_min=deputat_min,
            is_teilzeit=is_teilzeit,
            preferred_free_days=preferred_free_days or [],
            unavailable_slots=unavailable_slots or [],
            max_hours_per_day=tc.max_hours_per_day,
            max_gaps_per_day=tc.max_gaps_per_day,
        )

    def _generate_teachers(self) -> list[Teacher]:
        """Erzeugt alle Lehrkräfte mit Engpässen gemäß Spec.

        Feste Lehrkräfte (25):
          - 2 Chemie-Lehrkräfte        (Engpass #1+#2: 52h vs. 48h Bedarf → 92%)
          - 4 Freitag-TZ               (Engpass #3: Freitag-Cluster)
          - 1 stark eingeschränkt      (Engpass #4: Mo+Fr+Di-nachmittags gesperrt)
          - 5 Sport-Lehrkräfte         (Pflicht-Abdeckung: 130h vs. 108h Bedarf)
          - 2 Mathematik-VZ            (Lösbarkeits-Garantie: +52h Kapazität)
          - 2 Englisch-VZ              (Lösbarkeits-Garantie: +52h Kapazität)
          - 2 Religion-TZ + 1 Ethik-TZ (Kopplung: 3 TZ-Lehrer, je 1 pro Gruppe)
          - 1 Informatik-VZ + 1 Français-VZ (WPF-Kopplungsgruppen)
          - 2 Kunst-VZ + 2 Musik-VZ    (Lösbarkeits-Garantie: 4×26h=104h vs. 72h Bedarf)
        Restliche (tc.total_count − 25) Lehrkräfte: gewichtete Fächerkombinationen.
        Wichtig: _SUBJECT_COMBOS enthält KEINE Musik- oder Kunst-Allein-Einträge,
        um Single-Subject-Deputat-Violations zu vermeiden (4×22h=88h > 72h Bedarf).

        Puffer-Kalkulation (Default: total=60, VZ=26h, TZ_min=12h, 30% TZ):
          Feste: 2×26 + 4×12 + 16 + 5×26 + 4×26 + 3×12 + 2×26 + 4×26 = 542h
          Zufällig (35): 10 TZ×12 + 25 VZ×26 = 770h (8 TZ bereits fix → nur 10 TZ verbleibend)
          Gesamt: 1312h, Bedarf: ~1170h → Puffer ≈ 12%
        """
        tc = self.config.teachers
        teachers: list[Teacher] = []
        sek1_max = self.config.time_grid.sek1_max_slot

        # ── Engpass #1/#2: Chemie-Lehrkräfte (absichtlich knapp) ───────────
        # Bedarf Jg.7-10: 4 Jahrgänge × 6 Klassen × 2h = 48h/Woche
        # Kapazität: 26 + 26 = 52h → 92% Auslastung → Warnung
        teachers.append(self._make_teacher(
            subjects=["Chemie"],
            deputat=tc.vollzeit_deputat,
        ))
        teachers.append(self._make_teacher(
            subjects=["Chemie", "Biologie"],
            deputat=tc.vollzeit_deputat,
        ))

        # ── Engpass #3: Freitag-Cluster (4 Teilzeit mit Fr-Wunsch) ─────────
        # Deputat = Minimum für deterministischen Puffer
        for _ in range(4):
            subjects = self.rng.choices(
                _COMBO_SUBJECTS, weights=_COMBO_WEIGHTS
            )[0]
            teachers.append(self._make_teacher(
                subjects=subjects,
                deputat=tc.teilzeit_deputat_min,
                is_teilzeit=True,
                preferred_free_days=[4],  # Freitag
            ))

        # ── Engpass #4: Stark eingeschränkte Lehrkraft ──────────────────────
        # Mo (Tag 0) und Fr (Tag 4) komplett gesperrt
        # Di (Tag 1) nur Slots 1-3 verfügbar
        blocked: list[tuple[int, int]] = []
        for slot in range(1, sek1_max + 1):
            blocked.append((0, slot))  # Montag gesperrt
            blocked.append((4, slot))  # Freitag gesperrt
        for slot in range(4, sek1_max + 1):
            blocked.append((1, slot))  # Di nachmittags gesperrt
        subjects = self.rng.choices(_COMBO_SUBJECTS, weights=_COMBO_WEIGHTS)[0]
        teachers.append(self._make_teacher(
            subjects=subjects,
            deputat=16,
            is_teilzeit=True,
            unavailable_slots=blocked,
        ))

        # ── Sport-Basisabdeckung: 5 VZ Sport-Lehrkräfte ─────────────────────
        # Sport wird NICHT in _SUBJECT_COMBOS aufgenommen → deterministisch.
        # Bedarf: 36 Klassen × 3h = 108h. Kapazität: 5 × 26h = 130h (~20% Puffer).
        for sport_subjects in [
            ["Sport"],
            ["Sport", "Biologie"],
            ["Sport", "Biologie"],
            ["Sport", "Geschichte"],
            ["Sport", "Erdkunde"],
        ]:
            teachers.append(self._make_teacher(
                subjects=sport_subjects,
                deputat=tc.vollzeit_deputat,
            ))

        # ── Mathematik-Basisabdeckung: 2 dedizierte VZ ──────────────────────
        # Bedarf: 144h. Fixpool sichert mind. 52h, Zufallspool ergänzt auf ~200h.
        teachers.append(self._make_teacher(
            subjects=["Mathematik", "Physik"],
            deputat=tc.vollzeit_deputat,
        ))
        teachers.append(self._make_teacher(
            subjects=["Mathematik", "Deutsch"],
            deputat=tc.vollzeit_deputat,
        ))

        # ── Englisch-Basisabdeckung: 2 dedizierte VZ ────────────────────────
        # Bedarf: 120h. Fixpool sichert mind. 52h.
        teachers.append(self._make_teacher(
            subjects=["Englisch", "Geschichte"],
            deputat=tc.vollzeit_deputat,
        ))
        teachers.append(self._make_teacher(
            subjects=["Englisch", "Politik"],
            deputat=tc.vollzeit_deputat,
        ))

        # ── Religion/Ethik-Basisabdeckung: 3 dedizierte TZ ──────────────────
        # Kopplung braucht je 1 Lehrer pro Gruppe (evang, kath, ethik).
        # ACHTUNG: "Religion" und "Ethik" sind coupling-covered → kein regulärer
        # Unterricht → Deputat fast ausschließlich über Kopplungs-Stunden erreichbar.
        # TZ-Status (12h): reicht aus, denn 6 Kopplungsgruppen × 2h = 12h Deputat.
        teachers.append(self._make_teacher(
            subjects=["Religion", "Geschichte"],
            deputat=tc.teilzeit_deputat_min,
            is_teilzeit=True,
        ))
        teachers.append(self._make_teacher(
            subjects=["Religion", "Politik"],
            deputat=tc.teilzeit_deputat_min,
            is_teilzeit=True,
        ))
        teachers.append(self._make_teacher(
            subjects=["Ethik", "Geschichte"],
            deputat=tc.teilzeit_deputat_min,
            is_teilzeit=True,
        ))

        # ── WPF-Basisabdeckung: 2 dedizierte VZ ─────────────────────────────
        # WPF-Kopplung hat Gruppen für Informatik und Französisch.
        # Min. je 1 Lehrer pro WPF-Gruppe garantiert Lösbarkeit.
        teachers.append(self._make_teacher(
            subjects=["Informatik", "Mathematik"],
            deputat=tc.vollzeit_deputat,
        ))
        teachers.append(self._make_teacher(
            subjects=["Französisch", "Englisch"],
            deputat=tc.vollzeit_deputat,
        ))

        # ── Kunst-Basisabdeckung: 2 dedizierte VZ ───────────────────────────
        # Bedarf: 72h. 2×26h=52h Fixpool + Zufallspool → mind. 78h Gesamtkapazität.
        # WICHTIG: Mehrfach-Fach-Lehrer (kein Kunst-Allein), damit Deputat via
        # Zweitfach füllbar ist. Single-Subject-Lehrer würden 4×22h=88h > 72h erzwingen.
        teachers.append(self._make_teacher(
            subjects=["Kunst", "Deutsch"],
            deputat=tc.vollzeit_deputat,
        ))
        teachers.append(self._make_teacher(
            subjects=["Kunst", "Biologie"],
            deputat=tc.vollzeit_deputat,
        ))

        # ── Musik-Basisabdeckung: 2 dedizierte VZ ───────────────────────────
        # Bedarf: 72h. 2×26h=52h Fixpool + Zufallspool → mind. 78h Gesamtkapazität.
        teachers.append(self._make_teacher(
            subjects=["Musik", "Geschichte"],
            deputat=tc.vollzeit_deputat,
        ))
        teachers.append(self._make_teacher(
            subjects=["Musik", "Physik"],
            deputat=tc.vollzeit_deputat,
        ))

        # ── Restliche Lehrkräfte (tc.total_count − 25) ───────────────────────
        # TZ-Deputat = Minimum für deterministischen Gesamtpuffer (~12%)
        # TZ-Anzahl: Config-Quote minus bereits platzierte TZ (4 Freitag + 1 restricted + 3 Reli/Ethik = 8)
        remaining = tc.total_count - len(teachers)
        num_teilzeit_remaining = max(
            0,
            int(tc.total_count * tc.teilzeit_percentage) - 8  # 8 TZ bereits platziert
        )
        for i in range(remaining):
            is_tz = i < num_teilzeit_remaining
            dep = tc.teilzeit_deputat_min if is_tz else tc.vollzeit_deputat

            subjects = self.rng.choices(_COMBO_SUBJECTS, weights=_COMBO_WEIGHTS)[0]

            # 20% Chance auf einen Wunschtag (Mo-Do; Freitag schon im Cluster)
            free_wishes: list[int] = []
            if self.rng.random() < 0.20:
                free_wishes = [self.rng.choice([0, 1, 2, 3])]

            teachers.append(self._make_teacher(
                subjects=subjects,
                deputat=dep,
                is_teilzeit=is_tz,
                preferred_free_days=free_wishes,
            ))

        return teachers

    # ─── Kopplungen ───────────────────────────────────────────────────────────

    def _generate_couplings(self, classes: list[SchoolClass]) -> list[Coupling]:
        """Erzeugt Kopplungen für Reli/Ethik und WPF gemäß CouplingConfig."""
        cc = self.config.couplings
        couplings: list[Coupling] = []

        if cc.reli_ethik_enabled:
            couplings.extend(self._generate_reli_couplings(classes, cc))

        if cc.wpf_enabled:
            couplings.extend(self._generate_wpf_couplings(classes, cc))

        return couplings

    def _generate_reli_couplings(self, classes: list[SchoolClass], cc) -> list[Coupling]:
        """Eine Reli/Ethik-Kopplung pro Jahrgang über alle Parallelklassen."""
        couplings = []
        by_grade: dict[int, list[str]] = {}
        for cls in classes:
            by_grade.setdefault(cls.grade, []).append(cls.id)

        for grade, class_ids in sorted(by_grade.items()):
            # Gruppen: alle reli_groups → Fach "Religion" außer Ethik → "Ethik"
            groups = []
            for group_name in cc.reli_groups:
                subject = "Ethik" if group_name.lower() == "ethik" else "Religion"
                groups.append(CouplingGroup(
                    group_name=group_name,
                    subject=subject,
                    hours_per_week=cc.reli_ethik_hours,
                ))

            couplings.append(Coupling(
                id=f"reli_{grade}",
                coupling_type="reli_ethik",
                involved_class_ids=class_ids,
                groups=groups,
                hours_per_week=cc.reli_ethik_hours,
                cross_class=cc.reli_ethik_cross_class,
            ))
        return couplings

    def _generate_wpf_couplings(self, classes: list[SchoolClass], cc) -> list[Coupling]:
        """WPF-Kopplungen für Jahrgänge ab wpf_start_grade."""
        couplings = []
        by_grade: dict[int, list[str]] = {}
        for cls in classes:
            if cls.grade >= cc.wpf_start_grade:
                by_grade.setdefault(cls.grade, []).append(cls.id)

        for grade, class_ids in sorted(by_grade.items()):
            groups = [
                CouplingGroup(
                    group_name=f"{subj}-WPF",
                    subject=subj,
                    hours_per_week=cc.wpf_hours,
                )
                for subj in cc.wpf_subjects
            ]

            couplings.append(Coupling(
                id=f"wpf_{grade}",
                coupling_type="wpf",
                involved_class_ids=class_ids,
                groups=groups,
                hours_per_week=cc.wpf_hours,
                cross_class=cc.wpf_cross_class,
            ))
        return couplings

    # ─── Vollständiger Datensatz ──────────────────────────────────────────────

    def generate(self) -> SchoolData:
        """Erzeugt den vollständigen Datensatz als SchoolData-Objekt."""
        subjects = self._generate_subjects()
        rooms = self._generate_rooms()
        classes = self._generate_classes()
        teachers = self._generate_teachers()
        couplings = self._generate_couplings(classes)
        return SchoolData(
            subjects=subjects,
            rooms=rooms,
            classes=classes,
            teachers=teachers,
            couplings=couplings,
            config=self.config,
        )

    def generate_all(self) -> dict:
        """Kompatibilitätsmethode – gibt dict zurück (deprecated, nutze generate())."""
        data = self.generate()
        return {
            "subjects": data.subjects,
            "classes": data.classes,
            "rooms": data.rooms,
            "teachers": data.teachers,
            "couplings": data.couplings,
        }

    # ─── Ausgabe ──────────────────────────────────────────────────────────────

    def print_summary(self, data: SchoolData | dict) -> None:
        """Gibt eine Rich-Tabelle mit Übersicht der erzeugten Daten aus."""
        from rich.console import Console
        from rich.table import Table
        from rich import box

        if isinstance(data, dict):
            subjects = data["subjects"]
            classes = data["classes"]
            rooms = data["rooms"]
            teachers = data["teachers"]
            couplings = data["couplings"]
        else:
            subjects = data.subjects
            classes = data.classes
            rooms = data.rooms
            teachers = data.teachers
            couplings = data.couplings

        console = Console()
        table = Table(title="Erzeugte Testdaten", box=box.ROUNDED)
        table.add_column("Kategorie", style="bold cyan")
        table.add_column("Anzahl", justify="right")
        table.add_column("Details")

        num_teilzeit = sum(1 for t in teachers if t.is_teilzeit)
        table.add_row("Fächer", str(len(subjects)), "")
        table.add_row("Klassen", str(len(classes)),
                      f"{len(set(c.grade for c in classes))} Jahrgänge")
        table.add_row("Räume (Fachräume)", str(len(rooms)), "")
        table.add_row("Lehrkräfte", str(len(teachers)),
                      f"{num_teilzeit} Teilzeit, {len(teachers)-num_teilzeit} Vollzeit")
        table.add_row("Kopplungen", str(len(couplings)), "")

        console.print(table)
