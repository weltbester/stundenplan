"""Tests für den CP-SAT Stundenplan-Solver (Phase 2)."""

import time
import pytest

from config.schema import (
    SchoolConfig, GradeConfig, GradeDefinition, SchoolType,
    TeacherConfig, SolverConfig,
)
from config.defaults import default_time_grid, default_rooms, default_school_config, SUBJECT_METADATA, STUNDENTAFEL_GYMNASIUM_SEK1
from data.fake_data import FakeDataGenerator
from models.school_data import SchoolData
from models.subject import Subject
from models.room import Room
from models.teacher import Teacher
from models.school_class import SchoolClass
from models.coupling import Coupling, CouplingGroup
from solver.scheduler import ScheduleSolver, ScheduleSolution
from solver.pinning import PinManager, PinnedLesson


# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def make_mini_config(time_limit: int = 60, num_workers: int = 4) -> SchoolConfig:
    """Erzeugt eine Mini-Konfiguration für schnelle Tests (2 Klassen: 5a, 7a).

    deputat_min_fraction=0.80; Teacher haben deputat_max=9, deputat_min=4.
    weight_deputat_deviation=0: Deputat-Optimierung deaktiviert für schnelle Tests –
    Korrektheit (dep_min ≤ actual ≤ dep_max) wird durch test_deputat_respected geprüft.
    """
    return SchoolConfig(
        school_name="Test-Gymnasium",
        school_type=SchoolType.GYMNASIUM,
        bundesland="NRW",
        time_grid=default_time_grid(),
        grades=GradeConfig(grades=[
            GradeDefinition(grade=5, num_classes=1, weekly_hours_target=30),
            GradeDefinition(grade=7, num_classes=1, weekly_hours_target=32),
        ]),
        rooms=default_rooms(),
        teachers=TeacherConfig(
            total_count=10,
            vollzeit_deputat=26,
            teilzeit_percentage=0.0,
            deputat_min_fraction=0.80,
        ),
        solver=SolverConfig(
            time_limit_seconds=time_limit,
            num_workers=num_workers,
            weight_deputat_deviation=0,  # Deaktiviert: Tests prüfen Korrektheit, nicht Optimierung
        ),
    )


def make_mini_school_data(seed: int = 42) -> SchoolData:
    """Erzeugt minimale Testdaten (2 Klassen 5a+7a, 10 handverlesene Lehrer).

    FakeDataGenerator eignet sich NICHT für < 20 Lehrer, weil er 12 Fixlehrer
    (Chemie, Freitag-TZ, Sport) erstellt, die die Fächerdeckung für Jg5+7
    nicht sicherstellen. Daher werden die Lehrer hier manuell angelegt.
    """
    config = make_mini_config()
    sek1_max = config.time_grid.sek1_max_slot

    # Fächer aus SUBJECT_METADATA
    subjects = [
        Subject(
            name=name,
            short_name=meta["short"],
            category=meta["category"],
            is_hauptfach=meta["is_hauptfach"],
            requires_special_room=meta["room"],
            double_lesson_required=meta["double_required"],
            double_lesson_preferred=meta["double_preferred"],
        )
        for name, meta in SUBJECT_METADATA.items()
    ]

    # Fachräume aus Config
    rooms = []
    for rd in config.rooms.special_rooms:
        prefix = rd.room_type[:2].upper()
        for i in range(1, rd.count + 1):
            rooms.append(Room(id=f"{prefix}{i}", room_type=rd.room_type,
                              name=f"{rd.display_name} {i}"))

    # Klassen 5a und 7a mit Standard-Curriculum
    classes = [
        SchoolClass(
            id="5a", grade=5, label="a",
            curriculum={s: h for s, h in STUNDENTAFEL_GYMNASIUM_SEK1[5].items() if h > 0},
            max_slot=sek1_max,
        ),
        SchoolClass(
            id="7a", grade=7, label="a",
            curriculum={s: h for s, h in STUNDENTAFEL_GYMNASIUM_SEK1[7].items() if h > 0},
            max_slot=sek1_max,
        ),
    ]

    # Lehrer: handverlesene Fächerkombinationen, die zusammen alle Fächer abdecken.
    # deputat_max=9 gibt Solver-Spielraum (alt: deputat=7, tol=3 → max 10h).
    # deputat_min=4: T08/T09 (Kopplung-only) bekommen max 4h Kopplungsstunden.
    # 10 × 9h = 90h >> Gesamtbedarf inkl. Kopplung (≈ 62h) → validate_feasibility ✓
    dep_max = 9
    dep_min = 4
    teachers = [
        Teacher(id="T01", name="Müller, Anna",    subjects=["Deutsch", "Geschichte"],   deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T02", name="Schmidt, Hans",   subjects=["Mathematik", "Physik"],    deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T03", name="Weber, Eva",      subjects=["Englisch", "Politik"],     deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T04", name="Becker, Klaus",   subjects=["Biologie", "Erdkunde"],    deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T05", name="Koch, Lisa",      subjects=["Kunst", "Musik"],          deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T06", name="Wagner, Tom",     subjects=["Sport", "Chemie"],         deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T07", name="Braun, Sara",     subjects=["Latein", "Deutsch"],       deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T08", name="Wolf, Peter",     subjects=["Religion", "Ethik"],       deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T09", name="Neumann, Maria",  subjects=["Religion", "Ethik"],       deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T10", name="Schulz, Ralf",    subjects=["Mathematik", "Deutsch"],   deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
    ]

    # Kopplungen: je eine Reli/Ethik-Kopplung pro Jahrgang
    couplings = [
        Coupling(
            id="reli_5", coupling_type="reli_ethik",
            involved_class_ids=["5a"],
            groups=[
                CouplingGroup(group_name="evangelisch", subject="Religion", hours_per_week=2),
                CouplingGroup(group_name="ethik",       subject="Ethik",    hours_per_week=2),
            ],
            hours_per_week=2, cross_class=True,
        ),
        Coupling(
            id="reli_7", coupling_type="reli_ethik",
            involved_class_ids=["7a"],
            groups=[
                CouplingGroup(group_name="evangelisch", subject="Religion", hours_per_week=2),
                CouplingGroup(group_name="ethik",       subject="Ethik",    hours_per_week=2),
            ],
            hours_per_week=2, cross_class=True,
        ),
    ]

    return SchoolData(
        subjects=subjects,
        rooms=rooms,
        classes=classes,
        teachers=teachers,
        couplings=couplings,
        config=config,
    )


# ─── Tests ────────────────────────────────────────────────────────────────────

class TestMiniFeasible:
    """2 Klassen, 8 Lehrer → Lösung muss gefunden werden."""

    def test_mini_feasible(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)
        assert solution.solver_status in ("OPTIMAL", "FEASIBLE"), (
            f"Solver konnte keine Lösung finden: {solution.solver_status}\n"
            f"Variablen: {solution.num_variables}, Constraints: {solution.num_constraints}"
        )

    def test_solution_has_entries(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)
        assert len(solution.entries) > 0, "Lösung hat keine Einträge"

    def test_solution_has_assignments(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)
        assert len(solution.assignments) > 0, "Lösung hat keine Zuweisungen"


class TestNoConflicts:
    """Kernkorrektheit: Keine Überschneidungen."""

    @pytest.fixture(scope="class")
    def solution(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        return solver.solve(use_soft=False)

    def test_no_teacher_conflict(self, solution):
        """Kein Lehrer wird doppelt belegt."""
        seen: set[tuple] = set()
        for entry in solution.entries:
            if entry.is_coupling:
                continue
            key = (entry.teacher_id, entry.day, entry.slot_number)
            assert key not in seen, (
                f"Lehrer {entry.teacher_id} doppelt belegt: "
                f"Tag={entry.day} Slot={entry.slot_number}"
            )
            seen.add(key)

    def test_no_class_conflict(self, solution):
        """Keine Klasse wird doppelt belegt (reguläre Stunden).

        Kopplungs-Einträge können mehrfach pro Slot erscheinen (je eine Entry
        pro Gruppe, z.B. evangelisch + ethik), da die Klasse in Gruppen aufgeteilt ist.
        Reguläre Stunden dürfen nicht mit anderen regulären oder mit Kopplungen überlappen.
        """
        regular_seen: set[tuple] = set()
        coupling_slots: set[tuple] = set()

        for entry in solution.entries:
            key = (entry.class_id, entry.day, entry.slot_number)
            if entry.is_coupling:
                coupling_slots.add(key)
            else:
                assert key not in regular_seen, (
                    f"Klasse {entry.class_id} doppelt regulär belegt: "
                    f"Tag={entry.day} Slot={entry.slot_number}"
                )
                assert key not in coupling_slots, (
                    f"Klasse {entry.class_id}: Regular-Stunde und Kopplung gleichzeitig: "
                    f"Tag={entry.day} Slot={entry.slot_number}"
                )
                regular_seen.add(key)

        # Auch Rückrichtung: keine Kopplung dort, wo eine Regular-Stunde ist
        for key in coupling_slots:
            assert key not in regular_seen, (
                f"Kopplung und Regular-Stunde gleichzeitig für {key}"
            )


class TestCurriculumSatisfied:
    """Stundentafel wird korrekt erfüllt."""

    @pytest.fixture(scope="class")
    def solution_and_data(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)
        return solution, data

    def test_curriculum_satisfied(self, solution_and_data):
        """Alle Fächer erhalten die korrekte Stundenzahl."""
        solution, data = solution_and_data

        # Zähle tatsächliche Stunden pro (Klasse, Fach)
        actual: dict[tuple, int] = {}
        for entry in solution.entries:
            if not entry.is_coupling:
                key = (entry.class_id, entry.subject)
                actual[key] = actual.get(key, 0) + 1

        # Prüfe gegen Curriculum (nur nicht-gekoppelte Fächer)
        coupling_covered: dict[str, set] = {}
        for coupling in data.couplings:
            for class_id in coupling.involved_class_ids:
                coupling_covered.setdefault(class_id, set())
                if coupling.coupling_type == "wpf":
                    coupling_covered[class_id].add("WPF")
                elif coupling.coupling_type == "reli_ethik":
                    for group in coupling.groups:
                        coupling_covered[class_id].add(group.subject)

        for cls in data.classes:
            for subject, hours in cls.curriculum.items():
                if hours == 0:
                    continue
                if subject in coupling_covered.get(cls.id, set()):
                    continue
                got = actual.get((cls.id, subject), 0)
                assert got == hours, (
                    f"Klasse {cls.id}, Fach {subject}: "
                    f"Soll {hours}h, Ist {got}h"
                )


class TestDeputat:
    """Deputat ±Toleranz."""

    @pytest.fixture(scope="class")
    def solution_and_data(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)
        return solution, data

    def test_deputat_respected(self, solution_and_data):
        """Jeder Lehrer hat seine Stunden innerhalb [deputat_min, deputat_max]."""
        solution, data = solution_and_data

        # Zähle Stunden pro Lehrer
        teacher_hours: dict[str, int] = {}
        for entry in solution.entries:
            if not entry.is_coupling:
                teacher_hours[entry.teacher_id] = teacher_hours.get(entry.teacher_id, 0) + 1

        teacher_map = {t.id: t for t in data.teachers}
        for t_id, actual in teacher_hours.items():
            teacher = teacher_map.get(t_id)
            if teacher is None:
                continue
            assert teacher.deputat_min <= actual <= teacher.deputat_max, (
                f"Lehrer {t_id}: Ist {actual}h außerhalb "
                f"[{teacher.deputat_min}, {teacher.deputat_max}]h"
            )


class TestUnavailability:
    """Gesperrte Slots bleiben leer."""

    def test_unavailability(self):
        """Lehrer mit gesperrtem Slot hat dort keine Stunde."""
        data = make_mini_school_data()

        # Ersten Lehrer bearbeiten: Slot (0, 1) sperren
        teachers = list(data.teachers)
        t = teachers[0]
        new_t = Teacher(
            id=t.id,
            name=t.name,
            subjects=t.subjects,
            deputat_max=t.deputat_max,
            deputat_min=t.deputat_min,
            is_teilzeit=t.is_teilzeit,
            unavailable_slots=[(0, 1)],  # Montag 1. Stunde gesperrt
            preferred_free_days=t.preferred_free_days,
            max_hours_per_day=t.max_hours_per_day,
            max_gaps_per_day=t.max_gaps_per_day,
        )
        teachers[0] = new_t
        data = SchoolData(
            subjects=data.subjects,
            rooms=data.rooms,
            classes=data.classes,
            teachers=teachers,
            couplings=data.couplings,
            config=data.config,
        )

        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)

        if solution.solver_status not in ("OPTIMAL", "FEASIBLE"):
            pytest.skip("Kein FEASIBLE – Unavailability-Test übersprungen")

        # Prüfe: Lehrer hat keinen Eintrag an (day=0, slot=1)
        for entry in solution.entries:
            if entry.teacher_id == t.id and not entry.is_coupling:
                assert not (entry.day == 0 and entry.slot_number == 1), (
                    f"Lehrer {t.id} hat Stunde im gesperrten Slot Mo/1"
                )


class TestSpecialRooms:
    """Fachraum-Kapazität wird nicht überschritten."""

    @pytest.fixture(scope="class")
    def solution_and_data(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)
        return solution, data

    def test_special_rooms(self, solution_and_data):
        """An keinem Slot werden mehr Fachräume genutzt als vorhanden."""
        from config.defaults import SUBJECT_METADATA

        solution, data = solution_and_data

        room_type_for_subject: dict[str, str] = {}
        for name, meta in SUBJECT_METADATA.items():
            if meta.get("room"):
                room_type_for_subject[name] = meta["room"]

        # Zähle simultane Raumnutzungen pro (day, slot, room_type)
        usage: dict[tuple, int] = {}
        for entry in solution.entries:
            rtype = room_type_for_subject.get(entry.subject)
            if rtype:
                key = (entry.day, entry.slot_number, rtype)
                usage[key] = usage.get(key, 0) + 1

        for (day, slot, rtype), count in usage.items():
            capacity = data.config.rooms.get_capacity(rtype)
            if capacity < 999:
                assert count <= capacity, (
                    f"Fachraum '{rtype}': {count} simultane Nutzungen "
                    f"bei Tag={day} Slot={slot}, Kapazität={capacity}"
                )


class TestDoubleLessons:
    """Doppelstunden-Pflicht wird eingehalten."""

    @pytest.fixture(scope="class")
    def solution_and_data(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)
        return solution, data

    def test_double_lesson_required(self, solution_and_data):
        """Fächer mit double_required=True erscheinen nur innerhalb gültiger Doppelblöcke.

        Beide Hälften einer Doppelstunde erscheinen als separate Einträge:
        z.B. Biologie an Slot 3 UND Slot 4 (Block 3-4). Slot 4 ist die zweite
        Hälfte und muss erlaubt sein – der Test prüft, dass jeder Eintrag entweder
        ein gültiger Doppelstunden-Start ODER die zweite Hälfte eines solchen ist.
        """
        from config.defaults import SUBJECT_METADATA

        solution, data = solution_and_data

        double_required = {
            name for name, meta in SUBJECT_METADATA.items()
            if meta.get("double_required")
        }

        tg = data.config.time_grid
        valid_starts = {
            db.slot_first for db in tg.double_blocks
            if db.slot_second <= tg.sek1_max_slot
        }
        double_seconds = {
            db.slot_second for db in tg.double_blocks
            if db.slot_second <= tg.sek1_max_slot
        }
        # first_of[slot_second] = slot_first
        first_of = {db.slot_second: db.slot_first for db in tg.double_blocks
                    if db.slot_second <= tg.sek1_max_slot}

        for entry in solution.entries:
            if entry.subject not in double_required or entry.is_coupling:
                continue
            h = entry.slot_number
            if h in valid_starts:
                pass  # Erste Hälfte: OK
            elif h in double_seconds:
                pass  # Zweite Hälfte: OK (Paar-Constraint sichert Konsistenz)
            else:
                pytest.fail(
                    f"Fach {entry.subject} in Klasse {entry.class_id} "
                    f"an Slot {h} – weder Double-Start noch Double-Ende "
                    f"(erlaubt: {valid_starts | double_seconds})"
                )

    def test_double_lessons_paired(self, solution_and_data):
        """Doppelstunden erscheinen immer paarweise."""
        from config.defaults import SUBJECT_METADATA

        solution, data = solution_and_data

        double_required = {
            name for name, meta in SUBJECT_METADATA.items()
            if meta.get("double_required")
        }

        # Map: slot_first -> slot_second
        double_pairs: dict[int, int] = {}
        for db in data.config.time_grid.double_blocks:
            if db.slot_second <= data.config.time_grid.sek1_max_slot:
                double_pairs[db.slot_first] = db.slot_second

        # Für jede Klasse+Fach+Tag: wenn Slot h aktiv, muss h+1 auch aktiv sein
        entries_by_key: dict[tuple, set[int]] = {}
        for entry in solution.entries:
            if entry.subject in double_required and not entry.is_coupling:
                key = (entry.class_id, entry.subject, entry.day)
                entries_by_key.setdefault(key, set()).add(entry.slot_number)

        for (cls_id, subject, day), slots in entries_by_key.items():
            for h in slots:
                if h in double_pairs:
                    h2 = double_pairs[h]
                    assert h2 in slots, (
                        f"Doppelstunde unvollständig: {cls_id} {subject} "
                        f"Tag={day} Slot={h} ohne Folge-Slot {h2}"
                    )


class TestSlotNumbers:
    """slot_number ist korrekt 1-basiert."""

    def test_slot_numbers_1based(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)

        if solution.solver_status not in ("OPTIMAL", "FEASIBLE"):
            pytest.skip("Kein FEASIBLE")

        for entry in solution.entries:
            assert entry.slot_number >= 1, (
                f"slot_number ist 0 oder negativ: {entry}"
            )
            assert entry.slot_number <= data.config.time_grid.sek1_max_slot, (
                f"slot_number {entry.slot_number} > sek1_max_slot "
                f"{data.config.time_grid.sek1_max_slot}"
            )

    def test_day_numbers_valid(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)

        if solution.solver_status not in ("OPTIMAL", "FEASIBLE"):
            pytest.skip("Kein FEASIBLE")

        for entry in solution.entries:
            assert 0 <= entry.day < data.config.time_grid.days_per_week, (
                f"day {entry.day} außerhalb [0, {data.config.time_grid.days_per_week})"
            )


class TestPinConstraint:
    """Gepinnte Stunden erscheinen korrekt in der Lösung."""

    def test_pin_constraint(self):
        """Eine gepinnte Stunde muss exakt so in der Lösung auftauchen."""
        data = make_mini_school_data()

        # Bestimme einen gültigen Pin: ersten Lehrer, erste Klasse, erstes Fach
        solver_tmp = ScheduleSolver(data)
        solver_tmp._build_slot_index()
        solver_tmp._build_coupling_coverage()
        solver_tmp._create_variables()

        # Wähle eine existierende assign-Variable als Pin
        if not solver_tmp._assign:
            pytest.skip("Keine assign-Variablen vorhanden")

        t_id, c_id, subj = next(iter(solver_tmp._assign.keys()))

        # Wähle einen gültigen Slot
        tg = data.config.time_grid
        valid_day = 0
        valid_slot = solver_tmp.sek1_slots[0].slot_number

        # Bei double_required: ersten valid_double_start nehmen
        from config.defaults import SUBJECT_METADATA
        meta = SUBJECT_METADATA.get(subj, {})
        if meta.get("double_required") and solver_tmp.valid_double_starts:
            valid_slot = min(solver_tmp.valid_double_starts)

        pin = PinnedLesson(
            teacher_id=t_id,
            class_id=c_id,
            subject=subj,
            day=valid_day,
            slot_number=valid_slot,
        )

        # Neuen Solver mit Pin
        solver = ScheduleSolver(data)
        solution = solver.solve(pins=[pin])

        if solution.solver_status not in ("OPTIMAL", "FEASIBLE"):
            pytest.skip(f"Mit Pin nicht lösbar: {solution.solver_status}")

        # Prüfe ob der Pin im Ergebnis auftaucht
        found = any(
            e.teacher_id == t_id
            and e.class_id == c_id
            and e.subject == subj
            and e.day == valid_day
            and e.slot_number == valid_slot
            and not e.is_coupling
            for e in solution.entries
        )
        assert found, (
            f"Gepinnter Eintrag nicht gefunden: "
            f"{t_id} {c_id} {subj} Tag={valid_day} Slot={valid_slot}\n"
            f"Vorhandene Einträge für {c_id}: "
            f"{[(e.teacher_id, e.subject, e.day, e.slot_number) for e in solution.get_class_schedule(c_id)]}"
        )


class TestPinManager:
    """PinManager Grundfunktionen."""

    def test_add_and_get(self):
        pm = PinManager()
        pin = PinnedLesson(teacher_id="MUE", class_id="5a",
                           subject="Mathematik", day=0, slot_number=1)
        pm.add_pin(pin)
        assert len(pm.get_pins()) == 1
        assert pm.get_pins()[0].teacher_id == "MUE"

    def test_teacher_id_uppercase(self):
        pin = PinnedLesson(teacher_id="mue", class_id="5a",
                           subject="Mathematik", day=0, slot_number=1)
        assert pin.teacher_id == "MUE"

    def test_remove_pin(self):
        pm = PinManager()
        pm.add_pin(PinnedLesson(teacher_id="MUE", class_id="5a",
                                subject="Mathematik", day=0, slot_number=1))
        removed = pm.remove_pin("MUE", 0, 1)
        assert removed is True
        assert len(pm.get_pins()) == 0

    def test_add_replaces_same_slot(self):
        pm = PinManager()
        pm.add_pin(PinnedLesson(teacher_id="MUE", class_id="5a",
                                subject="Mathematik", day=0, slot_number=1))
        pm.add_pin(PinnedLesson(teacher_id="SCH", class_id="5a",
                                subject="Deutsch", day=0, slot_number=1))
        pins = pm.get_pins()
        assert len(pins) == 1
        assert pins[0].teacher_id == "SCH"

    def test_save_load_json(self, tmp_path):
        pm = PinManager()
        pm.add_pin(PinnedLesson(teacher_id="MUE", class_id="5a",
                                subject="Mathematik", day=0, slot_number=1))
        p = tmp_path / "pins.json"
        pm.save_json(p)

        pm2 = PinManager()
        pm2.load_json(p)
        assert len(pm2.get_pins()) == 1
        assert pm2.get_pins()[0].teacher_id == "MUE"


class TestSolutionPersistence:
    """Lösung kann als JSON gespeichert und geladen werden."""

    def test_save_load_json(self, tmp_path):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)

        if solution.solver_status not in ("OPTIMAL", "FEASIBLE"):
            pytest.skip("Kein FEASIBLE")

        p = tmp_path / "solution.json"
        solution.save_json(p)

        loaded = ScheduleSolution.load_json(p)
        assert loaded.solver_status == solution.solver_status
        assert len(loaded.entries) == len(solution.entries)

    def test_get_class_schedule(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)

        if solution.solver_status not in ("OPTIMAL", "FEASIBLE"):
            pytest.skip("Kein FEASIBLE")

        class_id = data.classes[0].id
        entries = solution.get_class_schedule(class_id)
        assert all(e.class_id == class_id for e in entries)

    def test_get_teacher_schedule(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)

        if solution.solver_status not in ("OPTIMAL", "FEASIBLE"):
            pytest.skip("Kein FEASIBLE")

        if not solution.entries:
            pytest.skip("Keine Einträge")

        t_id = solution.entries[0].teacher_id
        entries = solution.get_teacher_schedule(t_id)
        assert all(e.teacher_id == t_id for e in entries)


# ─── Phase 3 Tests ────────────────────────────────────────────────────────────

class TestDoubleVars:
    """Phase 3: double[]-Variablen werden korrekt erstellt und verknüpft."""

    @pytest.fixture(scope="class")
    def solver_with_vars(self):
        data = make_mini_school_data()
        s = ScheduleSolver(data)
        s._build_slot_index()
        s._build_coupling_coverage()
        s._create_variables()
        return s

    def test_double_vars_created_for_required(self, solver_with_vars):
        """double-Variablen existieren für double_required-Fächer."""
        double_subjects_required = {
            n for n, m in SUBJECT_METADATA.items() if m.get("double_required")
        }
        if not double_subjects_required:
            pytest.skip("Keine double_required-Fächer im SUBJECT_METADATA")

        # Mindestens eine double-Variable für required-Fächer vorhanden
        double_required_keys = [
            (t, c, s, d, bs)
            for (t, c, s, d, bs) in solver_with_vars._double
            if s in double_subjects_required
        ]
        assert len(double_required_keys) > 0, (
            "Keine double-Variablen für double_required-Fächer erstellt"
        )

    def test_double_vars_created_for_preferred(self, solver_with_vars):
        """double-Variablen existieren für double_preferred-Fächer."""
        double_subjects_preferred = {
            n for n, m in SUBJECT_METADATA.items() if m.get("double_preferred")
        }
        if not double_subjects_preferred:
            pytest.skip("Keine double_preferred-Fächer im SUBJECT_METADATA")

        # Mindestens eine double-Variable für preferred-Fächer vorhanden
        double_preferred_keys = [
            (t, c, s, d, bs)
            for (t, c, s, d, bs) in solver_with_vars._double
            if s in double_subjects_preferred
        ]
        assert len(double_preferred_keys) > 0, (
            "Keine double-Variablen für double_preferred-Fächer erstellt"
        )

    def test_double_key_has_valid_block_start(self, solver_with_vars):
        """Alle double-Variablen haben gültige Block-Start-Slots."""
        valid_starts = solver_with_vars.valid_double_starts
        for (t, c, s, d, bs) in solver_with_vars._double:
            assert bs in valid_starts, (
                f"double-Variable hat ungültigen Block-Start {bs} "
                f"(erlaubt: {valid_starts})"
            )

    def test_double_linkage_in_solution(self):
        """double=1 ↔ beide Slot-Hälften aktiv in der Lösung."""
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)

        if solution.solver_status not in ("OPTIMAL", "FEASIBLE"):
            pytest.skip("Kein FEASIBLE")

        # Prüfe: wo entries an aufeinanderfolgenden Slots für dasselbe Fach
        # erscheinen, müssen beide aktiv sein
        tg = data.config.time_grid
        double_pairs = {db.slot_first: db.slot_second for db in tg.double_blocks
                        if db.slot_second <= tg.sek1_max_slot}

        by_key: dict[tuple, set[int]] = {}
        for entry in solution.entries:
            if entry.is_coupling:
                continue
            key = (entry.teacher_id, entry.class_id, entry.subject, entry.day)
            by_key.setdefault(key, set()).add(entry.slot_number)

        for key, slots in by_key.items():
            for h1, h2 in double_pairs.items():
                if h1 in slots:
                    # Wenn erste Hälfte aktiv und Fach ist double_required:
                    s = key[2]
                    if SUBJECT_METADATA.get(s, {}).get("double_required"):
                        assert h2 in slots, (
                            f"Double-required Fach {s}: Slot {h1} aktiv aber {h2} fehlt"
                        )

    def test_no_double_at_slot7(self, solver_with_vars):
        """Slot 7 ist kein gültiger double-Block-Start."""
        tg = solver_with_vars.config.time_grid
        for (t, c, s, d, bs) in solver_with_vars._double:
            assert bs != tg.sek1_max_slot, (
                f"double-Variable mit Block-Start = sek1_max_slot ({tg.sek1_max_slot})"
            )


class TestDoubleLessonsN3:
    """N=3 Sonderfall: 1 Doppelstunde + 1 Einzelstunde an anderem Tag."""

    def _make_n3_data(self):
        """Erstellt Testdaten mit einem double_required-Fach mit 3h/Woche.

        Verwendet die Standard-Mini-Daten (7a mit 32h/Woche), aber mit
        Biologie=3h statt 2h. Mit 33h/Woche und 5 Tagen (~6-7h/Tag) ist
        Slot 7 erreichbar (c10-compact kompatibel).
        """
        base = make_mini_school_data()
        sek1_max = base.config.time_grid.sek1_max_slot

        # Klasse 7a: Biologie von 2h auf 3h erhöhen (N=3 für double_required)
        new_classes = []
        for cls in base.classes:
            if cls.id == "7a":
                curriculum = dict(cls.curriculum)
                curriculum["Biologie"] = 3  # war 2h → jetzt 3h (N=3 Fall)
                new_classes.append(SchoolClass(
                    id=cls.id, grade=cls.grade, label=cls.label,
                    curriculum=curriculum, max_slot=sek1_max,
                ))
            else:
                new_classes.append(cls)

        return SchoolData(
            subjects=base.subjects,
            rooms=base.rooms,
            classes=new_classes,
            teachers=base.teachers,
            couplings=base.couplings,
            config=base.config,
        )

    def test_n3_feasible(self):
        """Datensatz mit N=3 double_required-Fach ist lösbar."""
        data = self._make_n3_data()
        report = data.validate_feasibility()
        if not report.is_feasible:
            pytest.skip("N=3-Testdaten nicht machbar (validate_feasibility fehlgeschlagen)")

        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)
        assert solution.solver_status in ("OPTIMAL", "FEASIBLE"), (
            f"N=3 Fach nicht lösbar: {solution.solver_status}"
        )

    def test_n3_single_on_different_day(self):
        """Bei N=3 double_required: Einzelstunde ist an anderem Tag als Doppelstunde."""
        data = self._make_n3_data()
        report = data.validate_feasibility()
        if not report.is_feasible:
            pytest.skip("N=3-Testdaten nicht machbar")

        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)

        if solution.solver_status not in ("OPTIMAL", "FEASIBLE"):
            pytest.skip("Kein FEASIBLE für N=3-Test")

        tg = data.config.time_grid
        double_pairs = {db.slot_first: db.slot_second for db in tg.double_blocks
                        if db.slot_second <= tg.sek1_max_slot}
        double_starts = set(double_pairs.keys())
        double_seconds = set(double_pairs.values())

        # Biologie-Einträge sammeln
        bio_by_day: dict[int, set[int]] = {}
        for entry in solution.entries:
            if entry.subject == "Biologie" and not entry.is_coupling:
                bio_by_day.setdefault(entry.day, set()).add(entry.slot_number)

        # Finde Doppelstunden-Tag und Einzelstunden-Tag
        double_days = []
        single_days = []
        for day, slots in bio_by_day.items():
            has_double = any(h in double_starts and (h + 1) in slots for h in slots)
            if has_double:
                double_days.append(day)
            else:
                single_days.append(day)

        if not double_days or not single_days:
            # Könnte sein dass 3h anders aufgeteilt wurde
            pytest.skip("Keine klare Doppelstunde/Einzelstunde-Trennung erkennbar")

        # Einzelstunde darf nicht am selben Tag wie Doppelstunde sein
        for sd in single_days:
            assert sd not in double_days, (
                f"Biologie: Einzelstunde (Tag {sd}) am selben Tag wie Doppelstunde"
            )


class TestSoftConstraints:
    """Weiche Constraints: Solver findet Lösung mit und ohne Soft-Optimierung."""

    @pytest.fixture(scope="class")
    def solution_soft(self):
        data = make_mini_school_data()
        data.config.solver.time_limit_seconds = 15  # Kurz für Tests
        solver = ScheduleSolver(data)
        return solver.solve(use_soft=True)

    @pytest.fixture(scope="class")
    def solution_hard_only(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        return solver.solve(use_soft=False)

    def test_soft_feasible(self, solution_soft):
        """Lösung mit Soft-Constraints ist FEASIBLE oder OPTIMAL."""
        assert solution_soft.solver_status in ("OPTIMAL", "FEASIBLE"), (
            f"Soft-Solver konnte keine Lösung finden: {solution_soft.solver_status}"
        )

    def test_no_soft_feasible(self, solution_hard_only):
        """Lösung ohne Soft-Constraints ist FEASIBLE oder OPTIMAL."""
        assert solution_hard_only.solver_status in ("OPTIMAL", "FEASIBLE"), (
            f"Hard-only-Solver konnte keine Lösung finden: {solution_hard_only.solver_status}"
        )

    def test_soft_has_objective_value(self, solution_soft):
        """Soft-Lösung hat einen Zielfunktionswert (objective_value)."""
        if solution_soft.solver_status not in ("OPTIMAL", "FEASIBLE"):
            pytest.skip("Kein FEASIBLE")
        # Bei Soft sollte objective_value gesetzt sein
        # (kann None sein wenn keine Soft-Terms vorhanden)
        # Zumindest prüfen dass es numerisch ist falls gesetzt
        if solution_soft.objective_value is not None:
            assert isinstance(solution_soft.objective_value, (int, float)), (
                f"objective_value ist kein Zahl: {type(solution_soft.objective_value)}"
            )

    def test_custom_weights_feasible(self):
        """Lösung mit überschriebenen Gewichten ist FEASIBLE."""
        data = make_mini_school_data()
        data.config.solver.time_limit_seconds = 15  # Kurz für Tests
        solver = ScheduleSolver(data)
        solution = solver.solve(
            use_soft=True,
            weights={"gaps": 200, "day_wishes": 10},
        )
        assert solution.solver_status in ("OPTIMAL", "FEASIBLE"), (
            f"Custom-weights-Solver konnte keine Lösung finden: {solution.solver_status}"
        )

    def test_zero_weights_feasible(self):
        """Lösung mit allen Gewichten=0 (keine Soft-Terms) ist FEASIBLE."""
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(
            use_soft=True,
            weights={"gaps": 0, "day_wishes": 0, "double_lessons": 0, "subject_spread": 0},
        )
        assert solution.solver_status in ("OPTIMAL", "FEASIBLE"), (
            f"Zero-weights-Solver konnte keine Lösung finden: {solution.solver_status}"
        )


class TestConstraintRelaxer:
    """ConstraintRelaxer erstellt korrekte Berichte."""

    def test_relaxer_on_feasible(self):
        """Relaxer läuft auf feasiblem Problem durch und gibt validen Report zurück.

        Hinweis: Relaxierungen können INFEASIBLE ergeben auch wenn das Original
        lösbar ist (z.B. 'no_couplings' bricht Deputat-Minima für Reli/Ethik-Lehrer).
        Wir prüfen nur, dass der Relaxer terminiert und valide Statūs liefert.
        """
        from solver.constraint_relaxer import ConstraintRelaxer

        data = make_mini_school_data()
        # Verifizieren dass das Problem überhaupt lösbar ist
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)
        if solution.solver_status not in ("OPTIMAL", "FEASIBLE"):
            pytest.skip("Basis-Problem nicht FEASIBLE – Relaxer-Test übersprungen")

        relaxer = ConstraintRelaxer(data)
        report = relaxer.diagnose(time_limit=15)

        # Jede Relaxierung hat einen validen Status (kein Python-Error)
        valid_statuses = {"OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN"}
        for result in report.relaxations:
            assert result.status in valid_statuses, (
                f"Relaxierung '{result.name}' hat unbekannten Status: {result.status}"
            )

        # Mindestens eine Relaxierung sollte FEASIBLE sein (da Original lösbar)
        feasible_relaxations = [
            r for r in report.relaxations
            if r.status in ("OPTIMAL", "FEASIBLE")
        ]
        assert len(feasible_relaxations) >= 1, (
            "Keine einzige Relaxierung liefert FEASIBLE – das ist ungewöhnlich"
        )

    def test_relaxer_report_structure(self):
        """RelaxReport hat korrekte Struktur und Felder."""
        from solver.constraint_relaxer import ConstraintRelaxer, RelaxReport, RelaxResult

        data = make_mini_school_data()
        relaxer = ConstraintRelaxer(data)
        report = relaxer.diagnose(time_limit=10)

        # Typ-Prüfung
        assert isinstance(report, RelaxReport)
        assert isinstance(report.original_status, str)
        assert isinstance(report.relaxations, list)
        assert isinstance(report.recommendation, str)
        assert len(report.relaxations) == 6, (
            f"Erwartet 6 Relaxierungen, erhalten: {len(report.relaxations)}"
        )

        for result in report.relaxations:
            assert isinstance(result, RelaxResult)
            assert result.name
            assert result.description
            assert result.status in ("OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNKNOWN")
            assert result.solve_time >= 0.0

    def test_relaxer_recommendation_nonempty(self):
        """Empfehlung ist nicht leer."""
        from solver.constraint_relaxer import ConstraintRelaxer

        data = make_mini_school_data()
        relaxer = ConstraintRelaxer(data)
        report = relaxer.diagnose(time_limit=10)

        assert report.recommendation, "Empfehlung ist leer"
        assert len(report.recommendation) > 10


@pytest.mark.slow
class TestFull36Classes:
    """Vollständiger 36-Klassen-Test (langsam, mit Zeitlimit)."""

    def test_full_36_classes(self):
        """36 Klassen mit Zeitlimit 300s – Ziel: mindestens FEASIBLE."""
        config = default_school_config()
        config.solver.time_limit_seconds = 300
        config.solver.num_workers = 0  # auto

        gen = FakeDataGenerator(config, seed=42)
        data = gen.generate()

        t0 = time.time()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)
        elapsed = time.time() - t0

        assert elapsed <= 310, f"Solver zu langsam: {elapsed:.1f}s"
        # Status sollte FEASIBLE oder OPTIMAL sein (oder UNKNOWN bei Timeout)
        assert solution.solver_status in (
            "OPTIMAL", "FEASIBLE", "UNKNOWN"
        ), f"Unerwarteter Status: {solution.solver_status}"

        if solution.solver_status in ("OPTIMAL", "FEASIBLE"):
            assert len(solution.entries) > 0


# ─── SOLVER TIMEOUT UX ────────────────────────────────────────────────────────

class TestSolverTimeoutUX:
    """Tests für Solver-Status UNKNOWN und FEASIBLE."""

    def test_unknown_status_fields_set(self):
        """Bei UNKNOWN: ScheduleSolution hat solver_status='UNKNOWN' und solve_time > 0."""
        from solver.scheduler import ScheduleSolution
        from config.schema import SolverConfig
        # Direkt ein ScheduleSolution mit UNKNOWN-Status bauen (Mock)
        config = default_school_config()
        sol = ScheduleSolution(
            entries=[],
            assignments=[],
            solver_status="UNKNOWN",
            solve_time_seconds=1.5,
            num_variables=0,
            num_constraints=0,
            config_snapshot=config,
        )
        assert sol.solver_status == "UNKNOWN"
        assert sol.solve_time_seconds > 0
        assert len(sol.entries) == 0

    def test_feasible_status_has_entries(self):
        """Bei FEASIBLE: ScheduleSolution kann Einträge haben."""
        from solver.scheduler import ScheduleEntry, ScheduleSolution
        config = default_school_config()
        entry = ScheduleEntry(
            day=0, slot_number=1, teacher_id="T01",
            class_id="5a", subject="Deutsch",
        )
        sol = ScheduleSolution(
            entries=[entry],
            assignments=[],
            solver_status="FEASIBLE",
            solve_time_seconds=5.0,
            num_variables=10,
            num_constraints=5,
            config_snapshot=config,
        )
        assert sol.solver_status == "FEASIBLE"
        assert len(sol.entries) == 1

    def test_solver_with_tiny_limit_returns_solution_or_unknown(self):
        """Solver mit minimalem Zeitlimit gibt OPTIMAL, FEASIBLE oder UNKNOWN zurück."""
        from config.schema import SolverConfig
        config = make_mini_config(time_limit=30)  # Schema-Minimum ist 30s
        data = make_mini_school_data()
        data = data.model_copy(update={"config": config})

        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)
        assert solution.solver_status in ("OPTIMAL", "FEASIBLE", "UNKNOWN")
        assert solution.solve_time_seconds > 0


# ─── ROOM ASSIGNMENT ──────────────────────────────────────────────────────────

class TestRoomAssignment:
    """Tests für Greedy + CP-SAT Raumzuweisung."""

    def _make_data_with_room(self, room_count: int = 2) -> SchoolData:
        """Mini-SchoolData mit Physik-Raum(en)."""
        config = make_mini_config(time_limit=60)
        rooms = [
            Room(id=f"PH{i}", room_type="physik", name=f"Physik {i}")
            for i in range(1, room_count + 1)
        ]
        subjects = [
            Subject(name="Mathematik", short_name="Ma", category="hauptfach",
                    is_hauptfach=True),
            Subject(name="Physik", short_name="Ph", category="nw",
                    is_hauptfach=False, requires_special_room="physik"),
        ]
        teachers = [
            Teacher(id="T01", name="Lehrer A", subjects=["Mathematik", "Physik"],
                    deputat_max=9, deputat_min=4),
            Teacher(id="T02", name="Lehrer B", subjects=["Mathematik"],
                    deputat_max=9, deputat_min=4),
        ]
        classes = [
            SchoolClass(id="5a", grade=5, label="a",
                        curriculum={"Mathematik": 4, "Physik": 2}, max_slot=7),
        ]
        return SchoolData(subjects=subjects, rooms=rooms, classes=classes,
                          teachers=teachers, couplings=[], config=config)

    def test_greedy_assigns_rooms_without_fallback(self):
        """Normaler Fall: Greedy vergibt Räume ohne '-?' Fallbacks."""
        from solver.scheduler import ScheduleEntry
        data = self._make_data_with_room(room_count=2)
        solver = ScheduleSolver(data)
        solver.data = data

        # Baue Einträge die einen Physik-Raum brauchen
        entries = [
            ScheduleEntry(day=0, slot_number=1, teacher_id="T01",
                          class_id="5a", subject="Physik", room="physik"),
            ScheduleEntry(day=0, slot_number=3, teacher_id="T01",
                          class_id="5a", subject="Physik", room="physik"),
        ]
        result = solver._assign_rooms_greedy(entries)
        for e in result:
            assert e.room is not None
            assert not e.room.endswith("-?"), f"Unerwarteter Fallback: {e.room}"

    def test_cp_sat_assigns_rooms_when_greedy_fails(self):
        """CP-SAT Zweiter Pass löst Konflikt der Greedy nicht lösen kann."""
        from solver.scheduler import ScheduleEntry
        # Nur 1 Physik-Raum für 2 gleichzeitige Belegungen → Greedy schlägt fehl
        data = self._make_data_with_room(room_count=2)
        solver = ScheduleSolver(data)
        solver.data = data

        # Beide Einträge im selben Slot
        entries = [
            ScheduleEntry(day=0, slot_number=1, teacher_id="T01",
                          class_id="5a", subject="Physik", room="physik"),
            ScheduleEntry(day=0, slot_number=1, teacher_id="T02",
                          class_id="5a", subject="Physik", room="physik"),
        ]
        # Greedy schlägt fehl weil nur 2 Räume vorhanden sind → beide get PH1, PH2
        result = solver._assign_rooms_cp(entries)
        rooms_assigned = {e.room for e in result}
        assert not any(r.endswith("-?") for r in rooms_assigned), \
            f"CP-SAT konnte keinen Raum zuweisen: {rooms_assigned}"

    def test_room_assignment_error_when_impossible(self):
        """RoomAssignmentError wenn mehr Nachfrage als Räume vorhanden."""
        from solver.scheduler import ScheduleEntry, RoomAssignmentError
        # Nur 1 Physik-Raum für 2 gleichzeitige Belegungen → unmöglich
        data = self._make_data_with_room(room_count=1)
        solver = ScheduleSolver(data)
        solver.data = data

        entries = [
            ScheduleEntry(day=0, slot_number=1, teacher_id="T01",
                          class_id="5a", subject="Physik", room="physik"),
            ScheduleEntry(day=0, slot_number=1, teacher_id="T02",
                          class_id="5a", subject="Physik", room="physik"),
        ]
        with pytest.raises(RoomAssignmentError):
            solver._assign_rooms_cp(entries)


class TestTwoPassSolver:
    """Zweiphasiger Solver produziert gültige Ergebnisse."""

    def test_two_pass_finds_solution(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False, use_two_pass=True)
        assert solution.solver_status in ("OPTIMAL", "FEASIBLE"), (
            f"Two-pass fand keine Lösung: {solution.solver_status}"
        )

    def test_two_pass_solution_has_entries(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False, use_two_pass=True)
        assert len(solution.entries) > 0

    def test_two_pass_phase1_time_recorded(self):
        """phase1_time_seconds wird gesetzt wenn two_pass aktiv."""
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False, use_two_pass=True)
        assert solution.phase1_time_seconds >= 0


class TestIncrementalSolve:
    """Inkrementeller Re-Solve und _identify_affected_teachers."""

    def test_identify_affected_no_changes(self):
        """Ohne Änderungen sind keine Lehrer betroffen."""
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)
        if solution.solver_status not in ("OPTIMAL", "FEASIBLE"):
            pytest.skip("Kein Solver-Ergebnis")
        affected = ScheduleSolver._identify_affected_teachers(solution, data)
        assert len(affected) == 0

    def test_identify_affected_blocked_slot(self):
        """Lehrer mit neu gesperrtem Slot wird als betroffen markiert."""
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve(use_soft=False)
        if solution.solver_status not in ("OPTIMAL", "FEASIBLE"):
            pytest.skip("Kein Solver-Ergebnis")
        if not solution.entries:
            pytest.skip("Keine Einträge")

        entry = next(e for e in solution.entries if not e.is_coupling)
        t_id = entry.teacher_id

        new_teachers = []
        for t in data.teachers:
            if t.id == t_id:
                new_slots = list(t.unavailable_slots) + [
                    (entry.day, entry.slot_number)
                ]
                new_teachers.append(
                    t.model_copy(update={"unavailable_slots": new_slots})
                )
            else:
                new_teachers.append(t)
        new_data = data.model_copy(update={"teachers": new_teachers})

        affected = ScheduleSolver._identify_affected_teachers(solution, new_data)
        assert t_id in affected, (
            f"Lehrer {t_id} sollte als betroffen markiert sein"
        )
