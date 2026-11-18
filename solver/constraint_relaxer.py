"""Systematische INFEASIBLE-Diagnose durch schrittweise Constraint-Lockerung."""

import copy
import time
import logging
from typing import Optional

from pydantic import BaseModel

from models.school_data import SchoolData
from solver.pinning import PinnedLesson
from solver.time_budget import effective_time_limit

logger = logging.getLogger(__name__)


# ─── Ergebnis-Modelle ─────────────────────────────────────────────────────────

class RelaxResult(BaseModel):
    """Ergebnis einer einzelnen Constraint-Lockerung."""
    name: str
    description: str
    status: str        # "FEASIBLE" / "INFEASIBLE" / "UNKNOWN"
    solve_time: float


class RelaxReport(BaseModel):
    """Vollständiger Bericht der Constraint-Relaxierung."""
    original_status: str
    relaxations: list[RelaxResult]
    recommendation: str


# ─── ConstraintRelaxer ────────────────────────────────────────────────────────

class ConstraintRelaxer:
    """Systematische Diagnose bei INFEASIBLE durch schrittweise Lockerung.

    Testet 6 Relaxierungen, um die Ursache von INFEASIBLE zu identifizieren:
      1. Ohne Doppelstunden-Pflicht (double_required=False für alle Fächer)
      2. Ohne Fachraum-Limits (unbegrenzte Kapazität)
      3. Ohne Kopplungen (leere Kopplungsliste)
      4. Erweiterte Deputat-Grenzen (deputat_min auf 25% gesenkt)
      5. Ohne Springstunden-Limit (max_gaps_per_week=0)
      6. Alle obigen kombiniert
    """

    def __init__(self, school_data: SchoolData) -> None:
        self.data = school_data

    def diagnose(
        self,
        pins: list[PinnedLesson] = [],
        time_limit: int = 30,
    ) -> RelaxReport:
        """Führt alle Relaxierungen durch und erstellt einen Bericht.

        Args:
            pins: Optionale Pins (werden an alle Relaxierungs-Solver weitergegeben)
            time_limit: Zeitlimit pro Relaxierung in Sekunden
        """
        # Erst originales Problem prüfen
        original_status = self._run_solver(self.data, pins, time_limit)

        results: list[RelaxResult] = []

        # 1. Ohne Doppelstunden-Pflicht
        results.append(self._test_relaxation(
            name="no_double_required",
            description="Alle double_required=False (Doppelstunden optional)",
            data=self._relax_no_double_required(),
            pins=pins,
            time_limit=time_limit,
        ))

        # 2. Ohne Fachraum-Limits
        results.append(self._test_relaxation(
            name="no_room_limits",
            description="Alle Fachraum-Kapazitäten unbegrenzt",
            data=self._relax_no_room_limits(),
            pins=pins,
            time_limit=time_limit,
        ))

        # 3. Ohne Kopplungen
        results.append(self._test_relaxation(
            name="no_couplings",
            description="Alle Kopplungen entfernt",
            data=self._relax_no_couplings(),
            pins=pins,
            time_limit=time_limit,
        ))

        # 4. Erweiterte Deputat-Grenzen
        results.append(self._test_relaxation(
            name="wider_deputat_bounds",
            description="deputat_min auf 50% von deputat_max gesenkt",
            data=self._relax_wider_deputat_bounds(),
            pins=pins,
            time_limit=time_limit,
        ))

        # 5. Ohne Springstunden-Limit
        results.append(self._test_relaxation(
            name="no_gap_limit",
            description="Springstunden-Limit deaktiviert (max_gaps_per_week=0)",
            data=self._relax_no_gap_limit(),
            pins=pins,
            time_limit=time_limit,
        ))

        # 6. Alle kombiniert
        results.append(self._test_relaxation(
            name="all_combined",
            description="Alle Relaxierungen kombiniert",
            data=self._relax_all_combined(),
            pins=pins,
            time_limit=time_limit,
        ))

        recommendation = self._build_recommendation(results)
        logger.info(f"ConstraintRelaxer: {recommendation}")

        return RelaxReport(
            original_status=original_status,
            relaxations=results,
            recommendation=recommendation,
        )

    # ─── Einzel-Relaxierungen ─────────────────────────────────────────────────

    def _relax_no_double_required(self) -> SchoolData:
        """Erstellt Datensatz, in dem kein Fach Doppelstunden erzwingt."""
        relaxed_subjects = [
            subject.model_copy(update={"double_lesson_required": False})
            for subject in self.data.subjects
        ]
        return SchoolData(
            subjects=relaxed_subjects,
            rooms=self.data.rooms,
            classes=self.data.classes,
            teachers=self.data.teachers,
            couplings=self.data.couplings,
            config=self.data.config,
            fixed_assignments=self.data.fixed_assignments,
        )

    def _relax_no_room_limits(self) -> SchoolData:
        """Erstellt Datensatz mit unbegrenzten Fachraum-Kapazitäten."""
        from config.schema import RoomConfig, SpecialRoomDef

        new_config = self.data.config.model_copy(deep=True)
        new_rooms = RoomConfig(
            special_rooms=[
                SpecialRoomDef(
                    room_type=r.room_type,
                    display_name=r.display_name,
                    count=999,
                )
                for r in new_config.rooms.special_rooms
            ]
        )
        new_config.rooms = new_rooms
        return SchoolData(
            subjects=self.data.subjects,
            rooms=self.data.rooms,
            classes=self.data.classes,
            teachers=self.data.teachers,
            couplings=self.data.couplings,
            config=new_config,
            fixed_assignments=self.data.fixed_assignments,
        )

    def _relax_no_couplings(self) -> SchoolData:
        """Erstellt Datensatz ohne Kopplungen."""
        return SchoolData(
            subjects=self.data.subjects,
            rooms=self.data.rooms,
            classes=self.data.classes,
            teachers=self.data.teachers,
            couplings=[],
            config=self.data.config,
            fixed_assignments=self.data.fixed_assignments,
        )

    def _relax_no_gap_limit(self) -> SchoolData:
        """Deaktiviert das harte Springstunden-Limit (max_gaps_per_week=0)."""
        new_config = self.data.config.model_copy(deep=True)
        new_config.solver.max_gaps_per_week = 0
        return SchoolData(
            subjects=self.data.subjects,
            rooms=self.data.rooms,
            classes=self.data.classes,
            teachers=self.data.teachers,
            couplings=self.data.couplings,
            config=new_config,
            fixed_assignments=self.data.fixed_assignments,
        )

    def _relax_wider_deputat_bounds(self) -> SchoolData:
        """Senkt deputat_min auf 25% von deputat_max für maximale Solver-Flexibilität.

        25% statt 50%: wirkt auch wenn deputat_min_fraction bereits 0.5 ist (kein No-Op).
        """
        new_teachers = [
            t.model_copy(update={"deputat_min": max(1, round(t.deputat_max * 0.25))})
            for t in self.data.teachers
        ]
        return SchoolData(
            subjects=self.data.subjects,
            rooms=self.data.rooms,
            classes=self.data.classes,
            teachers=new_teachers,
            couplings=self.data.couplings,
            config=self.data.config,
            fixed_assignments=self.data.fixed_assignments,
        )

    def _relax_all_combined(self) -> SchoolData:
        """Alle Relaxierungen kombiniert."""
        from config.schema import RoomConfig, SpecialRoomDef

        new_config = self.data.config.model_copy(deep=True)

        # Fachraum-Kapazitäten unbegrenzt
        new_config.rooms = RoomConfig(
            special_rooms=[
                SpecialRoomDef(
                    room_type=r.room_type,
                    display_name=r.display_name,
                    count=999,
                )
                for r in new_config.rooms.special_rooms
            ]
        )

        # deputat_min auf 25% senken (konsistent mit _relax_wider_deputat_bounds)
        new_teachers = [
            t.model_copy(update={"deputat_min": max(1, round(t.deputat_max * 0.25))})
            for t in self.data.teachers
        ]

        # Springstunden-Limit aufheben
        new_config.solver.max_gaps_per_week = 0

        return SchoolData(
            subjects=self.data.subjects,
            rooms=self.data.rooms,
            classes=self.data.classes,
            teachers=new_teachers,
            couplings=[],  # Kopplungen entfernen
            config=new_config,
            fixed_assignments=self.data.fixed_assignments,
        )

    # ─── Solver-Ausführung ────────────────────────────────────────────────────

    def _test_relaxation(
        self,
        name: str,
        description: str,
        data: SchoolData,
        pins: list[PinnedLesson],
        time_limit: int,
    ) -> RelaxResult:
        """Testet eine einzelne Relaxierung."""
        status, elapsed = self._run_solver_timed(data, pins, time_limit)

        logger.info(f"  Relaxierung '{name}': {status} ({elapsed:.1f}s)")
        return RelaxResult(
            name=name,
            description=description,
            status=status,
            solve_time=elapsed,
        )

    def _run_solver(
        self,
        data: SchoolData,
        pins: list[PinnedLesson],
        time_limit: int,
    ) -> str:
        """Führt den Solver aus und gibt den Status zurück."""
        status, _ = self._run_solver_timed(data, pins, time_limit)
        return status

    def _run_solver_timed(
        self,
        data: SchoolData,
        pins: list[PinnedLesson],
        time_limit: int,
    ) -> tuple[str, float]:
        """Führt den Solver aus und gibt (Status, Zeit) zurück."""
        from solver.scheduler import ScheduleSolver

        t0 = time.time()
        try:
            # Zeitlimit setzen
            modified_data = data
            configured = effective_time_limit(
                data.config.solver.time_limit_seconds, len(data.classes)
            )
            if configured > time_limit:
                new_config = data.config.model_copy(deep=True)
                new_config.solver.time_limit_seconds = time_limit
                new_config.solver.num_workers = 2
                modified_data = SchoolData(
                    subjects=data.subjects,
                    rooms=data.rooms,
                    classes=data.classes,
                    teachers=data.teachers,
                    couplings=data.couplings,
                    config=new_config,
                    fixed_assignments=data.fixed_assignments,
                )

            solver = ScheduleSolver(modified_data)
            solution = solver.solve(pins=pins, use_soft=False)
            elapsed = time.time() - t0
            return solution.solver_status, elapsed
        except Exception as e:
            elapsed = time.time() - t0
            logger.warning(f"Solver-Ausnahme: {e}")
            return "UNKNOWN", elapsed

    # ─── Empfehlung ───────────────────────────────────────────────────────────

    def _build_recommendation(self, results: list[RelaxResult]) -> str:
        """Erstellt eine menschenlesbare Empfehlung basierend auf den Ergebnissen."""
        feasible = [r for r in results if r.status in ("OPTIMAL", "FEASIBLE")]
        infeasible = [r for r in results if r.status == "INFEASIBLE"]

        if not feasible:
            if all(r.status == "UNKNOWN" for r in results):
                return (
                    "Alle Relaxierungen endeten mit UNKNOWN (Zeitlimit?). "
                    "Erhöhen Sie time_limit oder vereinfachen Sie das Problem."
                )
            return (
                "Problem bleibt INFEASIBLE auch nach allen Relaxierungen. "
                "Möglicherweise fehlen Lehrer mit den benötigten Fächern. "
                "Prüfen Sie die Kapazitätsdiagnose."
            )

        # Spezifische Empfehlungen basierend auf welche Relaxierung hilft
        fixes = []
        by_name = {r.name: r.status for r in results}

        if by_name.get("no_double_required") in ("OPTIMAL", "FEASIBLE"):
            fixes.append(
                "Doppelstunden-Pflicht: Einige double_required-Fächer haben "
                "zu wenig Stunden oder zu wenig Slot-Kombinationen verfügbar."
            )
        if by_name.get("no_room_limits") in ("OPTIMAL", "FEASIBLE"):
            fixes.append(
                "Fachraum-Kapazität: Zu viele Klassen brauchen gleichzeitig "
                "denselben Fachraum. Mehr Räume hinzufügen oder Stunden spreizen."
            )
        if by_name.get("no_couplings") in ("OPTIMAL", "FEASIBLE"):
            fixes.append(
                "Kopplungen: Die Kopplungs-Constraints verursachen Konflikte. "
                "Prüfen Sie Überschneidungen zwischen Kopplungs- und regulären Stunden."
            )
        if by_name.get("wider_deputat_bounds") in ("OPTIMAL", "FEASIBLE"):
            fixes.append(
                "Deputat-Grenzen: Die Deputat-Untergrenzen sind zu eng. "
                "Senken Sie deputat_min_fraction in der Konfiguration."
            )
        if by_name.get("no_gap_limit") in ("OPTIMAL", "FEASIBLE"):
            fixes.append(
                "Springstunden-Limit: max_gaps_per_week ist zu eng für die aktuelle "
                "Lehrer-/Klassen-Konfiguration. Erhöhen Sie den Wert oder setzen Sie "
                "ihn auf 0 (nur Soft-Minimierung)."
            )

        if fixes:
            return "Mögliche Ursachen:\n" + "\n".join(f"  • {f}" for f in fixes)

        if by_name.get("all_combined") in ("OPTIMAL", "FEASIBLE"):
            return (
                "Erst alle Relaxierungen kombiniert helfen. "
                "Das Problem hat mehrere gleichzeitige Constraints-Konflikte."
            )

        return "Unklare Ursache. Prüfen Sie Lehrer-Fach-Abdeckung und Raumkapazitäten."
