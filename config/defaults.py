from config.schema import (
    TimeGridConfig,
    LessonSlot,
    PauseSlot,
    DoubleBlock,
    GradeConfig,
    GradeDefinition,
    RoomConfig,
    SpecialRoomDef,
    SchoolConfig,
    SchoolType,
)


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
            PauseSlot(after_slot=6, duration_minutes=20, label="Mittagspause"),
        ],
        double_blocks=[
            DoubleBlock(slot_first=1, slot_second=2),   # Block 1-2
            DoubleBlock(slot_first=3, slot_second=4),   # Block 3-4
            DoubleBlock(slot_first=5, slot_second=6),   # Block 5-6
            # Stunde 7 hat keinen Partner → keine Doppelstunde möglich
            DoubleBlock(slot_first=9, slot_second=10),  # Block 9-10 (Sek II)
        ],
        sek1_max_slot=7,
        sek2_max_slot=10,
        min_hours_per_day=5,
    )


def default_grades() -> GradeConfig:
    """Standard: 6 Jahrgänge × 6 Klassen = 36 Klassen."""
    return GradeConfig(
        grades=[
            GradeDefinition(grade=5, num_classes=6, weekly_hours_target=30),
            GradeDefinition(grade=6, num_classes=6, weekly_hours_target=31),
            GradeDefinition(grade=7, num_classes=6, weekly_hours_target=32),
            GradeDefinition(grade=8, num_classes=6, weekly_hours_target=32),
            GradeDefinition(grade=9, num_classes=6, weekly_hours_target=34),
            GradeDefinition(grade=10, num_classes=6, weekly_hours_target=34),
        ]
    )


def default_oberstufe_grades() -> GradeConfig:
    """Oberstufen-Jahrgänge: EF (11), Q1 (12), Q2 (13) mit je 2 Kursen."""
    return GradeConfig(
        grades=[
            GradeDefinition(grade=11, num_classes=2, weekly_hours_target=32),
            GradeDefinition(grade=12, num_classes=2, weekly_hours_target=34),
            GradeDefinition(grade=13, num_classes=2, weekly_hours_target=34),
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
                display_name="Bio-Raum", count=3),   # 36 Klassen brauchen 3 Bio-Räume
            SpecialRoomDef(room_type="informatik",
                display_name="Informatik-Raum", count=2),
            SpecialRoomDef(room_type="kunst",
                display_name="Kunst-Raum", count=3),  # 36 Klassen brauchen 3 Kunst-Räume
            SpecialRoomDef(room_type="musik",
                display_name="Musik-Raum", count=3),  # 36 Klassen brauchen 3 Musik-Räume
            SpecialRoomDef(room_type="sport",
                display_name="Sporthalle", count=4),  # 36 Klassen × 3h brauchen 4 Hallen
        ]
    )


def default_school_config() -> SchoolConfig:
    """Komplette Default-Konfiguration für ein Gymnasium Sek I."""
    return SchoolConfig(
        school_name="Muster-Gymnasium",
        school_type=SchoolType.GYMNASIUM,
        bundesland="NRW",
        time_grid=default_time_grid(),
        grades=default_grades(),
        rooms=default_rooms(),
    )


# ─── STUNDENTAFEL ───
# Jahrgang → Fach → Wochenstunden.
# Muss zum weekly_hours_target des Jahrgangs passen!

STUNDENTAFEL_GYMNASIUM_SEK1: dict[int, dict[str, int]] = {
    5: {
        "Deutsch":      4,
        "Mathematik":   4,
        "Englisch":     4,
        "Biologie":     2,
        "Erdkunde":     2,
        "Geschichte":   2,
        "Politik":      1,
        "Kunst":        2,
        "Musik":        2,
        "Religion":     2,
        "Sport":        3,
        "Physik":       0,
        "Chemie":       0,
        "Informatik":   0,
        "Latein":       0,
        "Französisch":  0,
        "WPF":          0,
    },  # Summe: 28 → +2 für Diff./Förderung → 30h
    6: {
        "Deutsch":      4,
        "Mathematik":   4,
        "Englisch":     4,
        "Biologie":     2,
        "Erdkunde":     2,
        "Geschichte":   2,
        "Politik":      1,
        "Kunst":        2,
        "Musik":        2,
        "Religion":     2,
        "Sport":        3,
        "Physik":       0,
        "Chemie":       0,
        "Informatik":   0,
        "Latein":       3,   # 2. Fremdsprache (Latein ODER Französisch)
        "Französisch":  0,
        "WPF":          0,
    },  # Summe: 31h
    7: {
        "Deutsch":      4,
        "Mathematik":   4,
        "Englisch":     3,
        "Biologie":     2,
        "Erdkunde":     2,
        "Geschichte":   2,
        "Politik":      1,
        "Kunst":        2,
        "Musik":        2,
        "Religion":     2,
        "Sport":        3,
        "Physik":       2,
        "Chemie":       2,
        "Informatik":   0,
        "Latein":       3,   # 2. FS oder 3. FS
        "Französisch":  0,
        "WPF":          0,
    },  # Summe: 32h (ohne WPF)
    8: {
        "Deutsch":      4,
        "Mathematik":   4,
        "Englisch":     3,
        "Biologie":     2,
        "Erdkunde":     2,
        "Geschichte":   2,
        "Politik":      2,
        "Kunst":        2,
        "Musik":        2,
        "Religion":     2,
        "Sport":        3,
        "Physik":       2,
        "Chemie":       2,
        "Informatik":   0,
        "Latein":       2,
        "Französisch":  0,
        "WPF":          0,
    },  # Summe: 32h
    9: {
        "Deutsch":      4,
        "Mathematik":   4,
        "Englisch":     3,
        "Biologie":     2,
        "Erdkunde":     1,   # 2→1: Slot-Budget (37h → 34h)
        "Geschichte":   2,
        "Politik":      2,
        "Kunst":        2,
        "Musik":        2,
        "Religion":     2,
        "Sport":        3,
        "Physik":       2,
        "Chemie":       2,
        "Informatik":   0,
        "Latein":       0,   # entfernt: WPF-Block ersetzt Latein-Slot
        "Französisch":  0,
        "WPF":          3,   # Wahlpflichtfach ab Jg. 9 (via Kopplung)
    },  # Summe: 34h (29h regular + 2h Reli-Kopplung + 3h WPF-Kopplung), 1 Slot frei
    10: {
        "Deutsch":      4,
        "Mathematik":   4,
        "Englisch":     3,
        "Biologie":     2,
        "Erdkunde":     1,   # 2→1: Slot-Budget
        "Geschichte":   2,   # 3→2: Slot-Budget (38h → 34h)
        "Politik":      2,
        "Kunst":        2,
        "Musik":        2,
        "Religion":     2,
        "Sport":        3,
        "Physik":       2,
        "Chemie":       2,
        "Informatik":   0,
        "Latein":       0,   # entfernt: WPF-Block ersetzt Latein-Slot
        "Französisch":  0,
        "WPF":          3,
    },  # Summe: 34h (29h regular + 2h Reli-Kopplung + 3h WPF-Kopplung), 1 Slot frei
}


# ─── OBERSTUFEN-STUNDENTAFEL ───
# LK: 5h/Woche, GK: 3h/Woche. Selbe Fächer wie Sek I → bestehende Lehrer deckend.
# Jahrgang 11 = EF (Einführungsphase), 12 = Q1, 13 = Q2.

STUNDENTAFEL_OBERSTUFE_GYMNASIUM: dict[int, dict[str, dict[str, int]]] = {
    11: {  # EF
        "LK": {"Mathematik": 5, "Deutsch": 5},
        "GK": {"Englisch": 3, "Geschichte": 3, "Biologie": 3, "Sport": 3},
    },
    12: {  # Q1
        "LK": {"Mathematik": 5, "Deutsch": 5},
        "GK": {"Englisch": 3, "Geschichte": 3, "Chemie": 3, "Sport": 3},
    },
    13: {  # Q2
        "LK": {"Mathematik": 5, "Deutsch": 5},
        "GK": {"Englisch": 3, "Geschichte": 3, "Physik": 3, "Sport": 3},
    },
}

# ─── FACH-METADATEN ───
# Pro Fach: Kürzel, Kategorie, ob Hauptfach, benötigter Raumtyp,
# ob Doppelstunden vorgeschrieben/bevorzugt sind.

SUBJECT_METADATA: dict[str, dict] = {
    "Deutsch": {
        "short":            "De",
        "category":         "hauptfach",
        "is_hauptfach":     True,
        "room":             None,        # kein Fachraum nötig
        "double_required":  False,
        "double_preferred": True,
    },
    "Mathematik": {
        "short":            "Ma",
        "category":         "hauptfach",
        "is_hauptfach":     True,
        "room":             None,
        "double_required":  False,
        "double_preferred": True,
    },
    "Englisch": {
        "short":            "En",
        "category":         "sprache",
        "is_hauptfach":     True,
        "room":             None,
        "double_required":  False,
        "double_preferred": True,
    },
    "Physik": {
        "short":            "Ph",
        "category":         "nw",
        "is_hauptfach":     False,
        "room":             "physik",
        "double_required":  True,
        "double_preferred": False,
    },
    "Chemie": {
        "short":            "Ch",
        "category":         "nw",
        "is_hauptfach":     False,
        "room":             "chemie",
        "double_required":  True,
        "double_preferred": False,
    },
    "Biologie": {
        "short":            "Bi",
        "category":         "nw",
        "is_hauptfach":     False,
        "room":             "biologie",
        "double_required":  True,
        "double_preferred": False,
    },
    "Informatik": {
        "short":            "If",
        "category":         "nw",
        "is_hauptfach":     False,
        "room":             "informatik",
        "double_required":  True,
        "double_preferred": False,
    },
    "Kunst": {
        "short":            "Ku",
        "category":         "musisch",
        "is_hauptfach":     False,
        "room":             "kunst",
        "double_required":  True,
        "double_preferred": False,
    },
    "Musik": {
        "short":            "Mu",
        "category":         "musisch",
        "is_hauptfach":     False,
        "room":             "musik",
        "double_required":  True,
        "double_preferred": False,
    },
    "Sport": {
        "short":            "Sp",
        "category":         "sport",
        "is_hauptfach":     False,
        "room":             "sport",
        "double_required":  False,   # 3h/Woche ungerade → Pflicht-Doppel unmöglich
        "double_preferred": True,
    },
    "Geschichte": {
        "short":            "Ge",
        "category":         "gesellschaft",
        "is_hauptfach":     False,
        "room":             None,
        "double_required":  False,
        "double_preferred": False,
    },
    "Erdkunde": {
        "short":            "Ek",
        "category":         "gesellschaft",
        "is_hauptfach":     False,
        "room":             None,
        "double_required":  False,
        "double_preferred": False,
    },
    "Politik": {
        "short":            "Pk",
        "category":         "gesellschaft",
        "is_hauptfach":     False,
        "room":             None,
        "double_required":  False,
        "double_preferred": False,
    },
    "Religion": {
        "short":            "Re",
        "category":         "gesellschaft",
        "is_hauptfach":     False,
        "room":             None,
        "double_required":  False,
        "double_preferred": False,
    },
    "Ethik": {
        "short":            "Et",
        "category":         "gesellschaft",
        "is_hauptfach":     False,
        "room":             None,
        "double_required":  False,
        "double_preferred": False,
    },
    "Latein": {
        "short":            "La",
        "category":         "sprache",
        "is_hauptfach":     True,
        "room":             None,
        "double_required":  False,
        "double_preferred": True,
    },
    "Französisch": {
        "short":            "Fr",
        "category":         "sprache",
        "is_hauptfach":     True,
        "room":             None,
        "double_required":  False,
        "double_preferred": True,
    },
    "WPF": {
        "short":            "WP",
        "category":         "wpf",
        "is_hauptfach":     False,
        "room":             None,   # je nach gewähltem WPF-Fach
        "double_required":  False,
        "double_preferred": False,
    },
}
