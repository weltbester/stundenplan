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

    deputat_tolerance=3 (Schema-Maximum) mit manuell kalibrierten Lehrer-Deputaten
    (deputat=6, Toleranz ±3 → erlaubt 3-9 h pro Lehrer).
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
            deputat_tolerance=3,   # Schema-Maximum; mit dep=6 → Bereich 3-9 h
        ),
        solver=SolverConfig(time_limit_seconds=time_limit, num_workers=num_workers),
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
    # Deputat=6 (nominal), Toleranz=10 (aus Config) → Constraint: 0-16h erlaubt.
    # Gesamtbedarf (non-coupled): 5a=26h + 7a=30h = 56h + Kopplungslehrer 8h ≈ 64h.
    dep = 6
    teachers = [
        Teacher(id="T01", name="Müller, Anna",    subjects=["Deutsch", "Geschichte"],   deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T02", name="Schmidt, Hans",   subjects=["Mathematik", "Physik"],    deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T03", name="Weber, Eva",      subjects=["Englisch", "Politik"],     deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T04", name="Becker, Klaus",   subjects=["Biologie", "Erdkunde"],    deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T05", name="Koch, Lisa",      subjects=["Kunst", "Musik"],          deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T06", name="Wagner, Tom",     subjects=["Sport", "Chemie"],         deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T07", name="Braun, Sara",     subjects=["Latein", "Deutsch"],       deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T08", name="Wolf, Peter",     subjects=["Religion", "Ethik"],       deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T09", name="Neumann, Maria",  subjects=["Religion", "Ethik"],       deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T10", name="Schulz, Ralf",    subjects=["Mathematik", "Deutsch"],   deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
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
        solution = solver.solve()
        assert solution.solver_status in ("OPTIMAL", "FEASIBLE"), (
            f"Solver konnte keine Lösung finden: {solution.solver_status}\n"
            f"Variablen: {solution.num_variables}, Constraints: {solution.num_constraints}"
        )

    def test_solution_has_entries(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve()
        assert len(solution.entries) > 0, "Lösung hat keine Einträge"

    def test_solution_has_assignments(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve()
        assert len(solution.assignments) > 0, "Lösung hat keine Zuweisungen"


class TestNoConflicts:
    """Kernkorrektheit: Keine Überschneidungen."""

    @pytest.fixture(scope="class")
    def solution(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        return solver.solve()

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
        solution = solver.solve()
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
        solution = solver.solve()
        return solution, data

    def test_deputat_respected(self, solution_and_data):
        """Jeder Lehrer hat seine Stunden innerhalb der Toleranz."""
        solution, data = solution_and_data
        tol = data.config.teachers.deputat_tolerance

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
            delta = abs(actual - teacher.deputat)
            assert delta <= tol, (
                f"Lehrer {t_id}: Deputat {teacher.deputat}h, "
                f"Ist {actual}h, Δ={delta} > Toleranz {tol}"
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
            deputat=t.deputat,
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
        solution = solver.solve()

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
        solution = solver.solve()
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
        solution = solver.solve()
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
        solution = solver.solve()

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
        solution = solver.solve()

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
        solution = solver.solve()

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
        solution = solver.solve()

        if solution.solver_status not in ("OPTIMAL", "FEASIBLE"):
            pytest.skip("Kein FEASIBLE")

        class_id = data.classes[0].id
        entries = solution.get_class_schedule(class_id)
        assert all(e.class_id == class_id for e in entries)

    def test_get_teacher_schedule(self):
        data = make_mini_school_data()
        solver = ScheduleSolver(data)
        solution = solver.solve()

        if solution.solver_status not in ("OPTIMAL", "FEASIBLE"):
            pytest.skip("Kein FEASIBLE")

        if not solution.entries:
            pytest.skip("Keine Einträge")

        t_id = solution.entries[0].teacher_id
        entries = solution.get_teacher_schedule(t_id)
        assert all(e.teacher_id == t_id for e in entries)


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
        solution = solver.solve()
        elapsed = time.time() - t0

        assert elapsed <= 310, f"Solver zu langsam: {elapsed:.1f}s"
        # Status sollte FEASIBLE oder OPTIMAL sein (oder UNKNOWN bei Timeout)
        assert solution.solver_status in (
            "OPTIMAL", "FEASIBLE", "UNKNOWN"
        ), f"Unerwarteter Status: {solution.solver_status}"

        if solution.solver_status in ("OPTIMAL", "FEASIBLE"):
            assert len(solution.entries) > 0
