"""CP-SAT Stundenplan-Solver (Google OR-Tools).

Architektur:
  - Entscheidungsvariablen auf zwei Ebenen:
      assign[t, c, s]        – Lehrer t unterrichtet Klasse c im Fach s
      slot[t, c, s, day, h]  – wann findet diese Stunde statt
  - Kopplungsvariablen separat
  - Alle harten Constraints implementiert
  - Optionale Pins (fixierte Stunden)
"""

import os
import time
import logging
from pathlib import Path
from typing import Optional

from pydantic import BaseModel
from ortools.sat.python import cp_model

from config.schema import SchoolConfig
from config.defaults import SUBJECT_METADATA
from models.school_data import SchoolData
from models.teacher import Teacher
from models.school_class import SchoolClass
from models.coupling import Coupling
from solver.pinning import PinnedLesson

logger = logging.getLogger(__name__)


# ─── Ergebnis-Modelle ─────────────────────────────────────────────────────────

class ScheduleEntry(BaseModel):
    """Eine einzelne Unterrichtsstunde im fertigen Stundenplan."""

    day: int              # 0-basiert (0=Mo, 4=Fr)
    slot_number: int      # 1-basiert (wie Zeitraster)
    teacher_id: str
    class_id: str
    subject: str
    room: Optional[str] = None
    is_coupling: bool = False
    coupling_id: Optional[str] = None


class TeacherAssignment(BaseModel):
    """Zuweisung eines Lehrers zu einer Klasse+Fach."""

    teacher_id: str
    class_id: str
    subject: str
    hours_per_week: int


class ScheduleSolution(BaseModel):
    """Vollständige Lösung des Stundenplan-Solvers."""

    entries: list[ScheduleEntry]
    assignments: list[TeacherAssignment]
    solver_status: str
    solve_time_seconds: float
    objective_value: Optional[float] = None
    num_variables: int
    num_constraints: int
    config_snapshot: SchoolConfig

    def get_class_schedule(self, class_id: str) -> list[ScheduleEntry]:
        """Alle Einträge für eine bestimmte Klasse."""
        return [e for e in self.entries if e.class_id == class_id]

    def get_teacher_schedule(self, teacher_id: str) -> list[ScheduleEntry]:
        """Alle Einträge für einen bestimmten Lehrer."""
        return [e for e in self.entries if e.teacher_id == teacher_id]

    def save_json(self, path: Path) -> None:
        """Speichert die Lösung als JSON-Datei."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def load_json(cls, path: Path) -> "ScheduleSolution":
        """Lädt eine gespeicherte Lösung aus JSON."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Lösung nicht gefunden: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return cls.model_validate_json(f.read())


# ─── Progress-Callback ────────────────────────────────────────────────────────

class SolveProgressCallback(cp_model.CpSolverSolutionCallback):
    """Zeigt Solver-Fortschritt während der Suche."""

    def __init__(self) -> None:
        super().__init__()
        self._solution_count = 0
        self._start_time = time.time()

    def on_solution_callback(self) -> None:
        self._solution_count += 1
        elapsed = time.time() - self._start_time
        obj = self.objective_value
        logger.info(
            f"  Lösung #{self._solution_count} | "
            f"Zeit: {elapsed:.1f}s | "
            f"Obj: {obj:.0f}"
        )

    @property
    def solution_count(self) -> int:
        return self._solution_count


# ─── Haupt-Solver ─────────────────────────────────────────────────────────────

class ScheduleSolver:
    """CP-SAT basierter Stundenplan-Solver.

    Verwendung:
        solver = ScheduleSolver(school_data)
        solution = solver.solve(pins=[...])
    """

    def __init__(self, school_data: SchoolData) -> None:
        self.data = school_data
        self.config = school_data.config
        self._model = cp_model.CpModel()

        # Lookup-Strukturen (werden in _build_slot_index befüllt)
        self.sek1_slots: list = []         # LessonSlot-Objekte für Sek I
        self.slot_index: dict = {}         # (day, slot_number) -> int-Index
        self.valid_double_starts: set = {} # slot_numbers die Doppelstunden starten dürfen

        # Entscheidungsvariablen
        self._assign: dict = {}   # (teacher_id, class_id, subject) -> BoolVar
        self._slot: dict = {}     # (teacher_id, class_id, subject, day, slot_nr) -> BoolVar

        # Kopplungsvariablen
        self._coupling_slot: dict = {}    # (coupling_id, day, slot_nr) -> BoolVar
        self._coupling_assign: dict = {}  # (coupling_id, group_idx, teacher_id) -> BoolVar

        # Doppelstunden-Variablen (Phase 3)
        self._double: dict = {}  # (teacher_id, class_id, subject, day, block_start) -> BoolVar

        # Schnell-Indizes für Soft-Constraints (vermeiden O(|slots|)-Scans)
        self._sidx_teacher_day_slot: dict = {}  # (teacher_id, day, slot_nr) → [BoolVar]
        self._sidx_tcsd: dict = {}              # (teacher_id, class_id, subj, day) → [BoolVar]

        # Subject-Metadaten-Cache
        self._subject_meta: dict = {}
        for name, meta in SUBJECT_METADATA.items():
            self._subject_meta[name] = meta

        # Kopplungs-bedeckte Fächer pro Klasse
        self._coupling_covered: dict[str, set[str]] = {}  # class_id -> set of subjects

        # Pins (werden von solve() gesetzt)
        self._pinned_lessons: list[PinnedLesson] = []

    # ─── Öffentliche API ──────────────────────────────────────────────────────

    def solve(
        self,
        pins: list[PinnedLesson] = [],
        use_soft: bool = True,
        weights: Optional[dict] = None,
    ) -> ScheduleSolution:
        """Löst das Stundenplan-Problem und gibt eine Lösung zurück."""
        self._pinned_lessons = list(pins)

        t0 = time.time()

        self._build_slot_index()
        self._build_coupling_coverage()
        self._create_variables()
        self._add_constraints()

        time_limit = self.config.solver.time_limit_seconds
        num_workers = self.config.solver.num_workers or os.cpu_count() or 4

        if use_soft:
            # Warm-Start: Schnell feasible Lösung ohne Soft finden, dann als Hint verwenden
            pre_limit = min(90, time_limit // 3)
            pre_solver = cp_model.CpSolver()
            pre_solver.parameters.max_time_in_seconds = pre_limit
            pre_solver.parameters.num_workers = num_workers
            pre_solver.parameters.log_search_progress = False
            pre_status = pre_solver.solve(self._model)
            if pre_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                logger.info(f"Warm-Start: feasible Lösung in {pre_solver.wall_time:.1f}s gefunden – setze Hints")
                for var in self._slot.values():
                    self._model.add_hint(var, pre_solver.value(var))
                for var in self._assign.values():
                    self._model.add_hint(var, pre_solver.value(var))
                for var in self._double.values():
                    self._model.add_hint(var, pre_solver.value(var))
            else:
                logger.warning("Warm-Start: keine feasible Lösung gefunden – Soft-Solve ohne Hints")

            self._add_soft_objective(weights)

        # Solver konfigurieren
        cp_solver = cp_model.CpSolver()
        cp_solver.parameters.max_time_in_seconds = time_limit
        cp_solver.parameters.num_workers = num_workers
        cp_solver.parameters.log_search_progress = False

        callback = SolveProgressCallback()
        status = cp_solver.solve(self._model, callback)

        elapsed = time.time() - t0
        status_name = cp_solver.status_name(status)

        logger.info(
            f"Solver beendet: {status_name} | "
            f"Zeit: {elapsed:.1f}s | "
            f"Lösungen: {callback.solution_count}"
        )

        if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return self._extract_solution(cp_solver, elapsed, status_name)
        else:
            if status == cp_model.INFEASIBLE:
                self._diagnose_infeasible()
            # Leere Lösung zurückgeben
            return ScheduleSolution(
                entries=[],
                assignments=[],
                solver_status=status_name,
                solve_time_seconds=elapsed,
                num_variables=self._model.proto.variables.__len__(),
                num_constraints=len(self._model.proto.constraints),
                config_snapshot=self.config,
            )

    # ─── Slot-Index-Aufbau ────────────────────────────────────────────────────

    def _build_slot_index(self) -> None:
        """Erstellt Mapping von (day, slot_number) auf int-Index."""
        tg = self.config.time_grid

        self.sek1_slots = [
            s for s in tg.lesson_slots
            if not s.is_sek2_only and s.slot_number <= tg.sek1_max_slot
        ]

        self.slot_index = {}
        for day in range(tg.days_per_week):
            for slot in self.sek1_slots:
                key = (day, slot.slot_number)
                self.slot_index[key] = len(self.slot_index)

        # Welche slot_numbers dürfen Doppelstunden starten?
        self.valid_double_starts = set()
        for db in tg.double_blocks:
            if db.slot_second <= tg.sek1_max_slot:
                self.valid_double_starts.add(db.slot_first)

    def _build_coupling_coverage(self) -> None:
        """Bestimmt welche Fächer pro Klasse über Kopplungen abgedeckt werden."""
        self._coupling_covered = {}
        for cls in self.data.classes:
            self._coupling_covered[cls.id] = set()

        for coupling in self.data.couplings:
            for class_id in coupling.involved_class_ids:
                if coupling.coupling_type == "wpf":
                    self._coupling_covered.setdefault(class_id, set()).add("WPF")
                elif coupling.coupling_type == "reli_ethik":
                    for group in coupling.groups:
                        self._coupling_covered.setdefault(class_id, set()).add(group.subject)

    # ─── Variablen erstellen ──────────────────────────────────────────────────

    def _create_variables(self) -> None:
        """Erstellt alle Entscheidungsvariablen."""
        self._create_assign_and_slot_vars()
        self._create_coupling_vars()
        self._create_double_vars()

    def _create_assign_and_slot_vars(self) -> None:
        """Ebene 1 (assign) und Ebene 2 (slot) Variablen."""
        tg = self.config.time_grid

        # Lehrer-Lookup: Fach -> Liste von Lehrern
        teachers_by_subject: dict[str, list[Teacher]] = {}
        for teacher in self.data.teachers:
            for subj in teacher.subjects:
                teachers_by_subject.setdefault(subj, []).append(teacher)

        for cls in self.data.classes:
            coupled_subjects = self._coupling_covered.get(cls.id, set())

            for subject, hours in cls.curriculum.items():
                if hours == 0:
                    continue
                if subject in coupled_subjects:
                    continue  # Wird über Kopplung abgedeckt

                qualified = teachers_by_subject.get(subject, [])
                if not qualified:
                    continue

                for teacher in qualified:
                    # assign[t, c, s]
                    key = (teacher.id, cls.id, subject)
                    var = self._model.new_bool_var(f"assign_{teacher.id}_{cls.id}_{subject}")
                    self._assign[key] = var

                    # slot[t, c, s, day, slot_nr]
                    for day in range(tg.days_per_week):
                        for slot in self.sek1_slots:
                            skey = (teacher.id, cls.id, subject, day, slot.slot_number)
                            svar = self._model.new_bool_var(
                                f"slot_{teacher.id}_{cls.id}_{subject}_{day}_{slot.slot_number}"
                            )
                            self._slot[skey] = svar
                            # Schnell-Indizes befüllen
                            tds_key = (teacher.id, day, slot.slot_number)
                            self._sidx_teacher_day_slot.setdefault(tds_key, []).append(svar)
                            tcsd_key = (teacher.id, cls.id, subject, day)
                            self._sidx_tcsd.setdefault(tcsd_key, []).append(svar)

    def _create_coupling_vars(self) -> None:
        """Variablen für Kopplungen."""
        tg = self.config.time_grid

        # Lehrer-Lookup für Kopplungs-Fächer
        teachers_by_subject: dict[str, list[Teacher]] = {}
        for teacher in self.data.teachers:
            for subj in teacher.subjects:
                teachers_by_subject.setdefault(subj, []).append(teacher)

        for coupling in self.data.couplings:
            # coupling_slot[k_id, day, slot_nr] – wann findet die Kopplung statt
            for day in range(tg.days_per_week):
                for slot in self.sek1_slots:
                    key = (coupling.id, day, slot.slot_number)
                    var = self._model.new_bool_var(
                        f"cslot_{coupling.id}_{day}_{slot.slot_number}"
                    )
                    self._coupling_slot[key] = var

            # coupling_assign[k_id, group_idx, teacher_id] – wer unterrichtet die Gruppe
            for g_idx, group in enumerate(coupling.groups):
                qualified = teachers_by_subject.get(group.subject, [])
                for teacher in qualified:
                    key = (coupling.id, g_idx, teacher.id)
                    var = self._model.new_bool_var(
                        f"cassign_{coupling.id}_{g_idx}_{teacher.id}"
                    )
                    self._coupling_assign[key] = var

    def _create_double_vars(self) -> None:
        """Erzeugt double[t,c,s,day,bs]-Variablen für alle Doppelstunden-Fächer.

        Wird für double_required UND double_preferred Fächer erstellt.
        Nur wenn BEIDE Slot-Variablen (bs und bs+1) existieren.
        """
        tg = self.config.time_grid
        double_subjects = {
            n for n, m in SUBJECT_METADATA.items()
            if m.get("double_required") or m.get("double_preferred")
        }

        # double_pairs: slot_first -> slot_second
        double_pairs: dict[int, int] = {}
        for db in tg.double_blocks:
            if db.slot_second <= tg.sek1_max_slot:
                double_pairs[db.slot_first] = db.slot_second

        for (t, c, s) in self._assign:
            if s not in double_subjects:
                continue
            for day in range(tg.days_per_week):
                for bs in self.valid_double_starts:
                    h_next = double_pairs.get(bs)
                    if h_next is None:
                        continue
                    if (t, c, s, day, bs) in self._slot and (t, c, s, day, h_next) in self._slot:
                        self._double[(t, c, s, day, bs)] = self._model.new_bool_var(
                            f"double_{t}_{c}_{s}_{day}_{bs}"
                        )

    # ─── Constraints ──────────────────────────────────────────────────────────

    def _add_constraints(self) -> None:
        """Fügt alle harten Constraints zum Modell hinzu."""
        self._c1_slot_implies_assign()
        self._c2_exactly_one_teacher()
        self._c3_curriculum_satisfied()
        self._c4_no_teacher_conflict()
        self._c5_no_class_conflict()
        self._c6_teacher_unavailability()
        self._c7_deputat_bounds()
        self._c8_special_room_capacity()
        self._c9_double_lesson_required()
        self._c9b_double_linkage()
        self._c10_compact_class_schedule()
        self._c11_max_hours_per_day()
        self._c12_coupling_constraints()
        self._c13_pin_constraints()

    def _c1_slot_implies_assign(self) -> None:
        """slot[t,c,s,d,h] <= assign[t,c,s]"""
        for (t, c, s, d, h), svar in self._slot.items():
            akey = (t, c, s)
            if akey in self._assign:
                self._model.add_implication(svar, self._assign[akey])

    def _c2_exactly_one_teacher(self) -> None:
        """Genau ein Lehrer pro (Klasse, Fach)."""
        # Gruppiere assign-Variablen nach (class, subject)
        by_cs: dict[tuple, list] = {}
        for (t, c, s), var in self._assign.items():
            by_cs.setdefault((c, s), []).append(var)

        for (c, s), vars_ in by_cs.items():
            self._model.add_exactly_one(vars_)

    def _c3_curriculum_satisfied(self) -> None:
        """Summe der Slot-Variablen == Curriculum-Stunden pro (Klasse, Fach)."""
        tg = self.config.time_grid
        coupled_by_class: dict[str, set[str]] = self._coupling_covered

        for cls in self.data.classes:
            for subject, hours in cls.curriculum.items():
                if hours == 0:
                    continue
                if subject in coupled_by_class.get(cls.id, set()):
                    continue

                # Alle slot-Variablen für diese Klasse+Fach
                slot_vars = [
                    self._slot[key]
                    for key in self._slot
                    if key[1] == cls.id and key[2] == subject
                ]
                if slot_vars:
                    self._model.add(sum(slot_vars) == hours)

    def _c4_no_teacher_conflict(self) -> None:
        """Kein Lehrer doppelt belegt an einem Slot."""
        tg = self.config.time_grid

        for teacher in self.data.teachers:
            for day in range(tg.days_per_week):
                for slot in self.sek1_slots:
                    h = slot.slot_number
                    # Reguläre Slot-Variablen dieses Lehrers an (day, h)
                    slot_vars = [
                        self._slot[key]
                        for key in self._slot
                        if key[0] == teacher.id and key[3] == day and key[4] == h
                    ]
                    # Kopplungs-Slots wo dieser Lehrer beteiligt ist
                    coupling_vars = [
                        self._coupling_assign[(k_id, g_idx, teacher.id)]
                        for (k_id, g_idx, t_id) in self._coupling_assign
                        if t_id == teacher.id
                        and (k_id, day, h) in self._coupling_slot
                        for _ in [self._coupling_slot.get((k_id, day, h))]
                        if _ is not None
                    ]
                    # Kombinierte Constraint: Lehrer kann nur an einem Ort sein
                    # Für Kopplungen: coupling_slot * coupling_assign
                    all_vars = slot_vars[:]

                    # Für jede Kopplung: Lehrer ist bei Kopplungs-Slot belastet wenn
                    # coupling_slot[k,d,h]=1 AND coupling_assign[k,g,t]=1
                    for coupling in self.data.couplings:
                        for g_idx, group in enumerate(coupling.groups):
                            ca_key = (coupling.id, g_idx, teacher.id)
                            cs_key = (coupling.id, day, h)
                            if ca_key in self._coupling_assign and cs_key in self._coupling_slot:
                                # auxiliary: coupling_busy = ca AND cs
                                busy = self._model.new_bool_var(
                                    f"busy_{teacher.id}_{coupling.id}_{g_idx}_{day}_{h}"
                                )
                                ca = self._coupling_assign[ca_key]
                                cs = self._coupling_slot[cs_key]
                                self._model.add_bool_and([ca, cs]).only_enforce_if(busy)
                                self._model.add_bool_or([ca.negated(), cs.negated()]).only_enforce_if(busy.negated())
                                all_vars.append(busy)

                    if all_vars:
                        self._model.add(sum(all_vars) <= 1)

    def _c5_no_class_conflict(self) -> None:
        """Keine Klasse doppelt belegt an einem Slot."""
        tg = self.config.time_grid

        for cls in self.data.classes:
            for day in range(tg.days_per_week):
                for slot in self.sek1_slots:
                    h = slot.slot_number
                    # Reguläre Slots dieser Klasse
                    slot_vars = [
                        self._slot[key]
                        for key in self._slot
                        if key[1] == cls.id and key[3] == day and key[4] == h
                    ]
                    # Kopplungs-Slots für diese Klasse
                    coupling_slot_vars = [
                        self._coupling_slot[(coupling.id, day, h)]
                        for coupling in self.data.couplings
                        if cls.id in coupling.involved_class_ids
                        and (coupling.id, day, h) in self._coupling_slot
                    ]

                    all_vars = slot_vars + coupling_slot_vars
                    if all_vars:
                        self._model.add(sum(all_vars) <= 1)

    def _c6_teacher_unavailability(self) -> None:
        """Gesperrte Slots bleiben leer."""
        for teacher in self.data.teachers:
            for (day, slot_nr) in teacher.unavailable_slots:
                # Reguläre Slots
                for key, var in self._slot.items():
                    if key[0] == teacher.id and key[3] == day and key[4] == slot_nr:
                        self._model.add(var == 0)
                # Kopplungs-Assign wenn Slot gesperrt
                for coupling in self.data.couplings:
                    cs_key = (coupling.id, day, slot_nr)
                    if cs_key in self._coupling_slot:
                        for g_idx in range(len(coupling.groups)):
                            ca_key = (coupling.id, g_idx, teacher.id)
                            if ca_key in self._coupling_assign:
                                # Wenn Lehrer den Slot hat UND Kopplung an dem Slot stattfindet
                                # → Lehrer kann nicht zugewiesen sein wenn Slot gesperrt
                                # Einfacher: coupling_assign von gesperrten Slots entkoppeln
                                # via: coupling_slot[k,d,h] AND coupling_assign[k,g,t] == 0
                                # Da coupling_slot[k,d,h] == 1 möglich, coupling_assign == 0
                                # Hier: wenn Slot für t gesperrt → coupling_assign[k,g,t] = 0
                                # → Lehrer kann diese Gruppe nicht übernehmen wenn
                                #   die Kopplung auf einen seiner gesperrten Slots fällt.
                                # Wir können das nicht direkt erzwingen ohne zu wissen wann.
                                # Stattdessen: separate Verknüpfung via auxiliary in _c4.
                                pass

    def _c7_deputat_bounds(self) -> None:
        """Deputat ±Toleranz."""
        tol = self.config.teachers.deputat_tolerance

        for teacher in self.data.teachers:
            # Alle Slot-Variablen dieses Lehrers
            slot_vars = [
                var for key, var in self._slot.items()
                if key[0] == teacher.id
            ]
            # Kopplungs-Stunden: coupling_assign * hours_per_week
            # Vereinfachung: coupling_assign bedeutet 'hours_per_week' Stunden pro Woche
            # Aber da coupling_slot pro Slot gezählt wird, zählen wir anders:
            # Die Gesamtstunden eines Lehrers in Kopplungen = sum über alle Kopplungen
            # wo er einer Gruppe zugewiesen ist: coupling.hours_per_week

            # coupling_assigned[k, g, t] = 1 bedeutet: Lehrer unterrichtet die Gruppe
            # mit group.hours_per_week Stunden

            coupling_terms = []
            for coupling in self.data.couplings:
                for g_idx, group in enumerate(coupling.groups):
                    ca_key = (coupling.id, g_idx, teacher.id)
                    if ca_key in self._coupling_assign:
                        # Skalierte Variable: hours × bool
                        h = group.hours_per_week
                        if h > 0:
                            coupling_terms.append(
                                self._coupling_assign[ca_key] * h
                            )

            total_hours = sum(slot_vars) + sum(coupling_terms) if (slot_vars or coupling_terms) else self._model.new_constant(0)

            if slot_vars or coupling_terms:
                self._model.add(sum(slot_vars) + sum(coupling_terms) >= teacher.deputat - tol)
                self._model.add(sum(slot_vars) + sum(coupling_terms) <= teacher.deputat + tol)

    def _c8_special_room_capacity(self) -> None:
        """Fachraum-Kapazität: Nicht mehr Stunden als Räume vorhanden."""
        tg = self.config.time_grid

        # Für jede Raum-Typ und jeden Slot: max room_count simultane Nutzungen
        room_type_for_subject: dict[str, str] = {}
        for name, meta in SUBJECT_METADATA.items():
            if meta.get("room"):
                room_type_for_subject[name] = meta["room"]

        for day in range(tg.days_per_week):
            for slot in self.sek1_slots:
                h = slot.slot_number
                # Gruppiere nach Raumtyp
                by_room_type: dict[str, list] = {}
                for (t, c, s, d, sh), var in self._slot.items():
                    if d == day and sh == h:
                        rtype = room_type_for_subject.get(s)
                        if rtype:
                            by_room_type.setdefault(rtype, []).append(var)

                for rtype, vars_ in by_room_type.items():
                    capacity = self.config.rooms.get_capacity(rtype)
                    if capacity < 999:  # Begrenzte Kapazität
                        self._model.add(sum(vars_) <= capacity)

    def _c9_double_lesson_required(self) -> None:
        """Fächer mit double_required=True dürfen nur in gültigen Doppelstunden-Blöcken stattfinden.

        Semantik je nach N (Stunden/Woche):
          N=1: Einzelstunde erlaubt (Warnung), keine Doppelstunden-Pflicht
          N=2: exakt 1 Doppelstunde; Slot-7 und andere Single-Slots verboten
          N=3: 1 Doppelstunde + 1 Einzelstunde an ANDEREM Tag als die Doppelstunde
          N=4: exakt 2 Doppelstunden; Slot-7 verboten
          N=5: 2 Doppelstunden + 1 Einzelstunde an anderem Tag

        Immer: Bidirektionale Implication für double-Paare (bs ↔ bs+1).
        """
        tg = self.config.time_grid

        double_required_subjects = {
            name for name, meta in SUBJECT_METADATA.items()
            if meta.get("double_required")
        }

        # Erste → zweite Slot-Nummer jedes Doppelstunden-Blocks
        double_pairs: dict[int, int] = {}
        double_seconds: set[int] = set()
        for db in tg.double_blocks:
            if db.slot_second <= tg.sek1_max_slot:
                double_pairs[db.slot_first] = db.slot_second
                double_seconds.add(db.slot_second)

        # Slot-Nummern die weder double_start noch double_second sind (z.B. Slot 7)
        all_slot_numbers = {s.slot_number for s in self.sek1_slots}
        single_only_slots = all_slot_numbers - set(double_pairs.keys()) - double_seconds

        # Curriculum-Lookup: (class_id, subject) -> hours
        curriculum: dict[tuple, int] = {}
        for cls in self.data.classes:
            for subj, hrs in cls.curriculum.items():
                curriculum[(cls.id, subj)] = hrs

        for (t, c, s, day, h), var in self._slot.items():
            if s not in double_required_subjects:
                continue

            n = curriculum.get((c, s), 0)
            n_rest = n % 2  # 0 = gerade; 1 = ungerade

            if h in self.valid_double_starts:
                # Erste Hälfte: wenn aktiv, muss zweite Hälfte auch aktiv sein
                h_next = double_pairs.get(h)
                if h_next is not None:
                    next_key = (t, c, s, day, h_next)
                    if next_key in self._slot:
                        # var=1 ↔ next_var=1 (Doppelstunden sind immer Paare)
                        self._model.add_implication(var, self._slot[next_key])
                        self._model.add_implication(self._slot[next_key], var)
                    else:
                        self._model.add(var == 0)
            elif h in double_seconds:
                # Zweite Hälfte: wird durch Implication von der ersten Hälfte gesteuert.
                pass
            else:
                # Single-only-Slot (z.B. Slot 7)
                if n_rest == 0:
                    # Gerade Stundenzahl: kein Einzelslot benötigt
                    self._model.add(var == 0)
                elif n <= 1:
                    # N=1: nur Einzelstunde möglich, erlaubt
                    pass
                else:
                    # N_rest=1 und N>=3: Einzelstunde erlaubt, aber nicht am selben Tag
                    # wie eine Doppelstunde dieses Fachs
                    for bs in self.valid_double_starts:
                        bs_key = (t, c, s, day, bs)
                        if bs_key in self._slot:
                            # slot[bs] + slot[h] <= 1 (am selben Tag)
                            self._model.add(self._slot[bs_key] + var <= 1)

    def _c9b_double_linkage(self) -> None:
        """Verknüpft double[]-Variablen bidirektional mit den slot[]-Paaren.

        Für alle double-Fächer (required + preferred):
          double[t,c,s,d,bs] = 1 ↔ slot[t,c,s,d,bs]=1 AND slot[t,c,s,d,bs+1]=1

        Implementiert durch drei Implications:
          1. double → slot_bs
          2. double → slot_bs+1
          3. slot_bs + slot_bs+1 - 1 ≤ double
        """
        tg = self.config.time_grid

        double_pairs: dict[int, int] = {}
        for db in tg.double_blocks:
            if db.slot_second <= tg.sek1_max_slot:
                double_pairs[db.slot_first] = db.slot_second

        for (t, c, s, day, bs), dvar in self._double.items():
            h_next = double_pairs.get(bs)
            if h_next is None:
                continue
            slot_bs = self._slot.get((t, c, s, day, bs))
            slot_bs_next = self._slot.get((t, c, s, day, h_next))
            if slot_bs is None or slot_bs_next is None:
                continue

            # double → slot_bs
            self._model.add_implication(dvar, slot_bs)
            # double → slot_bs+1
            self._model.add_implication(dvar, slot_bs_next)
            # slot_bs + slot_bs+1 - 1 ≤ double  (i.e. both active → double)
            self._model.add(slot_bs + slot_bs_next - 1 <= dvar)

    def _c10_compact_class_schedule(self) -> None:
        """Keine Lücken im Stundenplan einer Klasse (Stunden sind kompakt)."""
        tg = self.config.time_grid
        days = tg.days_per_week

        slot_numbers = sorted({s.slot_number for s in self.sek1_slots})

        for cls in self.data.classes:
            for day in range(days):
                # class_active[c, day, h] = 1 wenn Klasse in diesem Slot eine Stunde hat
                active: dict[int, cp_model.IntVar] = {}
                for h in slot_numbers:
                    slot_vars = [
                        self._slot[key]
                        for key in self._slot
                        if key[1] == cls.id and key[3] == day and key[4] == h
                    ]
                    coupling_vars = [
                        self._coupling_slot[(coupling.id, day, h)]
                        for coupling in self.data.couplings
                        if cls.id in coupling.involved_class_ids
                        and (coupling.id, day, h) in self._coupling_slot
                    ]
                    all_vars = slot_vars + coupling_vars
                    if all_vars:
                        a = self._model.new_bool_var(f"active_{cls.id}_{day}_{h}")
                        # a=1 iff any slot is active
                        self._model.add_bool_or(all_vars).only_enforce_if(a)
                        self._model.add(sum(all_vars) == 0).only_enforce_if(a.negated())
                        active[h] = a
                    else:
                        # Kein Unterricht möglich in diesem Slot
                        a = self._model.new_constant(0)
                        active[h] = a

                # Kompaktheitsbedingung: wenn h+1 aktiv, dann muss h aktiv sein
                # (keine Freistunden am Anfang)
                for i in range(len(slot_numbers) - 1):
                    h_curr = slot_numbers[i]
                    h_next = slot_numbers[i + 1]
                    # Nur konsekutive Sek-I-Slots (nicht über Pausen hinweg gebrochen)
                    # Hier vereinfacht: alle Sek-I-Slots
                    if h_curr in active and h_next in active:
                        # h_next aktiv → h_curr aktiv
                        if isinstance(active[h_next], cp_model.IntVar):
                            self._model.add_implication(active[h_next], active[h_curr])

    def _c11_max_hours_per_day(self) -> None:
        """Maximale Stunden pro Tag pro Lehrer."""
        tg = self.config.time_grid

        for teacher in self.data.teachers:
            for day in range(tg.days_per_week):
                day_vars = [
                    var for key, var in self._slot.items()
                    if key[0] == teacher.id and key[3] == day
                ]
                # Kopplungsstunden am Tag zählen
                for coupling in self.data.couplings:
                    for g_idx, group in enumerate(coupling.groups):
                        ca_key = (coupling.id, g_idx, teacher.id)
                        if ca_key not in self._coupling_assign:
                            continue
                        # Stunden dieser Kopplung an diesem Tag
                        for slot in self.sek1_slots:
                            cs_key = (coupling.id, day, slot.slot_number)
                            if cs_key in self._coupling_slot:
                                # Auxiliary: busy an diesem Slot für diesen Lehrer
                                busy = self._model.new_bool_var(
                                    f"maxh_{teacher.id}_{coupling.id}_{g_idx}_{day}_{slot.slot_number}"
                                )
                                ca = self._coupling_assign[ca_key]
                                cs = self._coupling_slot[cs_key]
                                self._model.add_bool_and([ca, cs]).only_enforce_if(busy)
                                self._model.add_bool_or(
                                    [ca.negated(), cs.negated()]
                                ).only_enforce_if(busy.negated())
                                day_vars.append(busy)

                if day_vars:
                    self._model.add(sum(day_vars) <= teacher.max_hours_per_day)

    def _c12_coupling_constraints(self) -> None:
        """Constraints für Kopplungen."""
        tg = self.config.time_grid

        for coupling in self.data.couplings:
            # 1. Gesamtstunden der Kopplung pro Woche
            cs_all = [
                self._coupling_slot[(coupling.id, day, slot.slot_number)]
                for day in range(tg.days_per_week)
                for slot in self.sek1_slots
                if (coupling.id, day, slot.slot_number) in self._coupling_slot
            ]
            if cs_all:
                self._model.add(sum(cs_all) == coupling.hours_per_week)

            # 2. Genau ein Lehrer pro Gruppe
            for g_idx, group in enumerate(coupling.groups):
                ca_vars = [
                    self._coupling_assign[(coupling.id, g_idx, t.id)]
                    for t in self.data.teachers
                    if (coupling.id, g_idx, t.id) in self._coupling_assign
                ]
                if ca_vars:
                    self._model.add_exactly_one(ca_vars)

            # 3. Kein Klassen-Konflikt: beteiligte Klassen sind während Kopplungs-Slot blockiert
            # (bereits in _c5 via coupling_slot_vars abgedeckt)

            # 4. Lehrer-Verfügbarkeit: coupling_assign[k,g,t] → Lehrer t ist an den
            #    Kopplungs-Slots verfügbar (Unavailability)
            for g_idx, group in enumerate(coupling.groups):
                for teacher in self.data.teachers:
                    ca_key = (coupling.id, g_idx, teacher.id)
                    if ca_key not in self._coupling_assign:
                        continue
                    ca = self._coupling_assign[ca_key]
                    # Wenn dieser Lehrer zugewiesen ist, muss er an jedem Kopplungs-Slot verfügbar sein
                    for (day, slot_nr) in teacher.unavailable_slots:
                        cs_key = (coupling.id, day, slot_nr)
                        if cs_key in self._coupling_slot:
                            # ca=1 → coupling_slot[k,d,h]=0
                            self._model.add_implication(ca, self._coupling_slot[cs_key].negated())

    def _c13_pin_constraints(self) -> None:
        """Gepinnte Stunden werden als harte Constraints gesetzt."""
        for pin in self._pinned_lessons:
            key = (pin.teacher_id, pin.class_id, pin.subject, pin.day, pin.slot_number)
            if key in self._slot:
                self._model.add(self._slot[key] == 1)
            else:
                logger.warning(
                    f"Pin ignoriert (Variable nicht vorhanden): "
                    f"{pin.teacher_id} {pin.class_id} {pin.subject} "
                    f"Tag={pin.day} Slot={pin.slot_number}"
                )

    # ─── Ergebnis-Extraktion ──────────────────────────────────────────────────

    def _extract_solution(
        self, cp_solver: cp_model.CpSolver, elapsed: float, status_name: str
    ) -> ScheduleSolution:
        """Extrahiert die Lösung aus dem gelösten Modell."""
        entries: list[ScheduleEntry] = []
        assignments: list[TeacherAssignment] = []

        # TeacherAssignments aus assign-Variablen
        for (t, c, s), var in self._assign.items():
            if cp_solver.value(var) == 1:
                # Stunden zählen
                hours = sum(
                    cp_solver.value(self._slot[key])
                    for key in self._slot
                    if key[0] == t and key[1] == c and key[2] == s
                )
                assignments.append(TeacherAssignment(
                    teacher_id=t,
                    class_id=c,
                    subject=s,
                    hours_per_week=int(hours),
                ))

        # ScheduleEntries aus slot-Variablen
        room_type_for_subject: dict[str, Optional[str]] = {
            name: meta.get("room") for name, meta in SUBJECT_METADATA.items()
        }

        for (t, c, s, day, h), var in self._slot.items():
            if cp_solver.value(var) == 1:
                entries.append(ScheduleEntry(
                    day=day,
                    slot_number=h,
                    teacher_id=t,
                    class_id=c,
                    subject=s,
                    room=room_type_for_subject.get(s),
                    is_coupling=False,
                ))

        # Kopplungs-Einträge
        for coupling in self.data.couplings:
            tg = self.config.time_grid
            for day in range(tg.days_per_week):
                for slot in self.sek1_slots:
                    h = slot.slot_number
                    cs_key = (coupling.id, day, h)
                    if cs_key not in self._coupling_slot:
                        continue
                    if cp_solver.value(self._coupling_slot[cs_key]) != 1:
                        continue

                    # Welcher Lehrer hat welche Gruppe?
                    for g_idx, group in enumerate(coupling.groups):
                        assigned_teacher = None
                        for teacher in self.data.teachers:
                            ca_key = (coupling.id, g_idx, teacher.id)
                            if ca_key in self._coupling_assign:
                                if cp_solver.value(self._coupling_assign[ca_key]) == 1:
                                    assigned_teacher = teacher.id
                                    break

                        if assigned_teacher is None:
                            continue

                        # Eine Entry pro beteiligter Klasse
                        for class_id in coupling.involved_class_ids:
                            entries.append(ScheduleEntry(
                                day=day,
                                slot_number=h,
                                teacher_id=assigned_teacher,
                                class_id=class_id,
                                subject=group.subject,
                                is_coupling=True,
                                coupling_id=coupling.id,
                            ))

        obj_val = None
        try:
            obj_val = float(cp_solver.objective_value)
        except Exception:
            pass

        return ScheduleSolution(
            entries=entries,
            assignments=assignments,
            solver_status=status_name,
            solve_time_seconds=elapsed,
            objective_value=obj_val,
            num_variables=len(self._slot) + len(self._assign)
                          + len(self._coupling_slot) + len(self._coupling_assign),
            num_constraints=len(self._model.proto.constraints),
            config_snapshot=self.config,
        )

    # ─── INFEASIBLE-Diagnostik ────────────────────────────────────────────────

    def _diagnose_infeasible(self) -> None:
        """Gibt strukturierte Diagnose aus wenn das Problem unlösbar ist."""
        tg = self.config.time_grid
        total_slots = tg.sek1_max_slot * tg.days_per_week

        total_need = sum(sum(c.curriculum.values()) for c in self.data.classes)
        total_dep = sum(t.deputat for t in self.data.teachers)
        delta = total_dep - total_need

        num_vars = len(self._slot) + len(self._assign)
        num_cons = len(self._model.proto.constraints)

        logger.error(
            f"INFEASIBLE – {num_vars} Variablen, {num_cons} Constraints"
        )
        logger.error(
            f"Tipp: Überprüfen Sie die Konfiguration auf Konflikte."
        )
        logger.error(
            f"Gesamtdeputat: {total_dep}h | Gesamtbedarf: {total_need}h | Δ={delta:+d}h"
        )

        # Kopplungs-abgedeckte Fächer bestimmen (diese brauchen keinen direkten Lehrer)
        coupling_covered: set[str] = set()
        for coupling in self.data.couplings:
            if coupling.coupling_type == "wpf":
                coupling_covered.add("WPF")
            elif coupling.coupling_type == "reli_ethik":
                for group in coupling.groups:
                    coupling_covered.add(group.subject)

        # Pro Fach: Lehrer-Kapazität vs. Bedarf (nur nicht-Kopplungs-Fächer)
        subject_need: dict[str, int] = {}
        for cls in self.data.classes:
            for subj, hours in cls.curriculum.items():
                if hours > 0:
                    subject_need[subj] = subject_need.get(subj, 0) + hours

        subject_cap: dict[str, int] = {}
        for teacher in self.data.teachers:
            for subj in teacher.subjects:
                subject_cap[subj] = subject_cap.get(subj, 0) + teacher.deputat

        for subj, need in sorted(subject_need.items()):
            if subj in coupling_covered:
                continue  # Wird via Kopplung abgedeckt, kein direkter Kapazitäts-Check
            cap = subject_cap.get(subj, 0)
            if cap < need:
                logger.error(
                    f"  Fach '{subj}': Kapazität {cap}h < Bedarf {need}h "
                    f"(Mangel: {need - cap}h)"
                )

        # Fachraum-Kapazität
        room_type_for_subject: dict[str, str] = {}
        for name, meta in SUBJECT_METADATA.items():
            if meta.get("room"):
                room_type_for_subject[name] = meta["room"]

        for subj, rtype in room_type_for_subject.items():
            need = subject_need.get(subj, 0)
            if need == 0:
                continue
            cap = self.config.rooms.get_capacity(rtype)
            if cap < 999:
                max_slots = cap * total_slots
                if need > max_slots:
                    logger.error(
                        f"  Fachraum '{rtype}': Bedarf {need}h > "
                        f"verfügbare Slots {max_slots} ({cap} Räume × {total_slots})"
                    )

    # ─── Soft-Constraints / Zielfunktion ──────────────────────────────────────

    def _add_soft_objective(self, weights: Optional[dict] = None) -> None:
        """Fügt weiche Zielfunktion (Minimierung) zum Modell hinzu.

        Gewichte können über den weights-Parameter überschrieben werden.
        """
        sc = self.config.solver
        w = {
            "gaps":           sc.weight_gaps,
            "day_wishes":     sc.weight_day_wishes,
            "double_lessons": sc.weight_double_lessons,
            "subject_spread": sc.weight_subject_spread,
        }
        if weights:
            w.update(weights)

        terms = []
        if w["gaps"] > 0:
            terms.extend(self._soft_gap_penalties(w["gaps"]))
        if w["day_wishes"] > 0:
            terms.extend(self._soft_day_wish_penalties(w["day_wishes"]))
        if w["double_lessons"] > 0:
            terms.extend(self._soft_double_preferred_bonuses(w["double_lessons"]))
        if w["subject_spread"] > 0:
            terms.extend(self._soft_subject_spread_penalties(w["subject_spread"]))

        if terms:
            self._model.minimize(sum(terms))

    def _soft_gap_penalties(self, weight: int) -> list:
        """Springstunden-Strafe: Lehrer hat freie Stunde zwischen zwei belegten Stunden."""
        tg = self.config.time_grid
        slot_numbers = sorted({s.slot_number for s in self.sek1_slots})
        terms = []

        for teacher in self.data.teachers:
            t = teacher.id
            for day in range(tg.days_per_week):
                # Aktive Slots für diesen Lehrer+Tag – O(1) via Index
                active: dict[int, object] = {}
                for h in slot_numbers:
                    reg_vars = self._sidx_teacher_day_slot.get((t, day, h), [])
                    if reg_vars:
                        a = self._model.new_bool_var(f"soft_act_{t}_{day}_{h}")
                        self._model.add_bool_or(reg_vars).only_enforce_if(a)
                        self._model.add(sum(reg_vars) == 0).only_enforce_if(a.negated())
                        active[h] = a

                active_hs = sorted(active.keys())
                if len(active_hs) < 3:
                    continue  # Mindestens 3 Slots für eine Lücke nötig

                for i, h in enumerate(active_hs):
                    before_vars = [active[h2] for h2 in active_hs[:i]]
                    after_vars = [active[h2] for h2 in active_hs[i + 1:]]
                    if not before_vars or not after_vars:
                        continue

                    before = self._model.new_bool_var(f"soft_bef_{t}_{day}_{h}")
                    after_ = self._model.new_bool_var(f"soft_aft_{t}_{day}_{h}")
                    is_gap = self._model.new_bool_var(f"soft_gap_{t}_{day}_{h}")

                    self._model.add_bool_or(before_vars).only_enforce_if(before)
                    self._model.add_bool_and(
                        [v.negated() for v in before_vars]
                    ).only_enforce_if(before.negated())

                    self._model.add_bool_or(after_vars).only_enforce_if(after_)
                    self._model.add_bool_and(
                        [v.negated() for v in after_vars]
                    ).only_enforce_if(after_.negated())

                    # is_gap = before AND after AND NOT active[h]
                    self._model.add_bool_and(
                        [before, after_, active[h].negated()]
                    ).only_enforce_if(is_gap)
                    self._model.add_bool_or(
                        [before.negated(), after_.negated(), active[h]]
                    ).only_enforce_if(is_gap.negated())

                    terms.append(is_gap * weight)

        return terms

    def _soft_day_wish_penalties(self, weight: int) -> list:
        """Strafe wenn Lehrer an einem bevorzugt freien Tag unterrichtet."""
        tg = self.config.time_grid
        terms = []

        for teacher in self.data.teachers:
            if not teacher.preferred_free_days:
                continue
            t = teacher.id
            for pref_day in teacher.preferred_free_days:
                if pref_day < 0 or pref_day >= tg.days_per_week:
                    continue
                day_vars = [
                    self._slot[k] for k in self._slot
                    if k[0] == t and k[3] == pref_day
                ]
                if day_vars:
                    has_lesson = self._model.new_bool_var(
                        f"soft_daywish_{t}_{pref_day}"
                    )
                    self._model.add_bool_or(day_vars).only_enforce_if(has_lesson)
                    self._model.add(sum(day_vars) == 0).only_enforce_if(
                        has_lesson.negated()
                    )
                    terms.append(has_lesson * weight)

        return terms

    def _soft_double_preferred_bonuses(self, weight: int) -> list:
        """Bonus für Doppelstunden bei double_preferred-Fächern (negativer Zielfunktionsterm)."""
        double_preferred = {
            n for n, m in SUBJECT_METADATA.items()
            if m.get("double_preferred")
        }
        terms = []
        for (t, c, s, day, bs), dvar in self._double.items():
            if s in double_preferred:
                terms.append(-weight * dvar)
        return terms

    def _soft_subject_spread_penalties(self, weight: int) -> list:
        """Strafe wenn ein Hauptfach an zu vielen verschiedenen Tagen unterrichtet wird.

        Zählt die Tage, an denen jedes Hauptfach in jeder Klasse vorkommt.
        Je mehr Tage, desto höher die Strafe (fördert Bündelung in Doppelstunden).
        """
        tg = self.config.time_grid
        hauptfach_subjects = {
            n for n, m in SUBJECT_METADATA.items()
            if m.get("is_hauptfach")
        }
        terms = []

        for (t, c, s) in self._assign:
            if s not in hauptfach_subjects:
                continue
            for day in range(tg.days_per_week):
                day_vars = self._sidx_tcsd.get((t, c, s, day), [])
                if day_vars:
                    day_active = self._model.new_bool_var(
                        f"soft_spread_{t}_{c}_{s}_{day}"
                    )
                    self._model.add_bool_or(day_vars).only_enforce_if(day_active)
                    self._model.add(sum(day_vars) == 0).only_enforce_if(
                        day_active.negated()
                    )
                    terms.append(day_active * weight)

        return terms
