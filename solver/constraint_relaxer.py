"""Systematische INFEASIBLE-Diagnose durch schrittweise Constraint-Lockerung."""

import copy
import time
import logging
from typing import Optional

from pydantic import BaseModel

from models.school_data import SchoolData
from solver.pinning import PinnedLesson

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

    Testet 5 Relaxierungen, um die Ursache von INFEASIBLE zu identifizieren:
      1. Ohne Doppelstunden-Pflicht (double_required=False für alle Fächer)
      2. Ohne Fachraum-Limits (unbegrenzte Kapazität)
      3. Ohne Kopplungen (leere Kopplungsliste)
      4. Doppelte Deputat-Toleranz
      5. Alle obigen kombiniert
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

        # 4. Doppelte Deputat-Toleranz
        results.append(self._test_relaxation(
            name="double_tolerance",
            description="Deputat-Toleranz verdoppelt",
            data=self._relax_double_tolerance(),
            pins=pins,
            time_limit=time_limit,
        ))

        # 5. Alle kombiniert
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
        """Erstellt Datensatz ohne double_required-Constraints (nur Config-Ebene).

        Da double_required im SUBJECT_METADATA steckt (nicht im SchoolData),
        wird stattdessen ein überschriebener Solver verwendet. Wir modifizieren
        die config so, dass double_required ignoriert wird.

        Trick: Wir geben die identischen Daten zurück, aber mit einem Marker
        im config-Snapshot. Der Solver wird mit einem modifizierten Context aufgerufen.
        Da wir ScheduleSolver nicht direkt patchbar ist ohne Subclassing, erstellen
        wir eine Hilfsdaten-Kopie und setzen alle Klassen-Curricula auf 0 für
        double_required-Fächer → nein, das wäre zu destruktiv.

        Stattdessen: Wir überschreiben SUBJECT_METADATA temporär.
        Da das ein globales Dict ist, clonen wir den Solver-Lauf in einem
        Subprocess-ähnlichen Kontext. Für Einfachheit: wir patchen lokal.
        """
        return self.data  # Wird speziell behandelt in _run_no_double_required

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
        )

    def _relax_double_tolerance(self) -> SchoolData:
        """Erstellt Datensatz mit doppelter Deputat-Toleranz."""
        new_config = self.data.config.model_copy(deep=True)
        old_tol = new_config.teachers.deputat_tolerance
        # Schema-Maximum ist 6; verdoppeln bis max 6
        new_tol = min(old_tol * 2, 6)
        new_config.teachers.deputat_tolerance = new_tol
        return SchoolData(
            subjects=self.data.subjects,
            rooms=self.data.rooms,
            classes=self.data.classes,
            teachers=self.data.teachers,
            couplings=self.data.couplings,
            config=new_config,
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

        # Deputat-Toleranz verdoppeln
        new_config.teachers.deputat_tolerance = min(
            new_config.teachers.deputat_tolerance * 2, 6
        )

        return SchoolData(
            subjects=self.data.subjects,
            rooms=self.data.rooms,
            classes=self.data.classes,
            teachers=self.data.teachers,
            couplings=[],  # Kopplungen entfernen
            config=new_config,
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
        if name == "no_double_required":
            status, elapsed = self._run_no_double_required(pins, time_limit)
        else:
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
            if data.config.solver.time_limit_seconds > time_limit:
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
                )

            solver = ScheduleSolver(modified_data)
            solution = solver.solve(pins=pins, use_soft=False)
            elapsed = time.time() - t0
            return solution.solver_status, elapsed
        except Exception as e:
            elapsed = time.time() - t0
            logger.warning(f"Solver-Ausnahme: {e}")
            return "UNKNOWN", elapsed

    def _run_no_double_required(
        self,
        pins: list[PinnedLesson],
        time_limit: int,
    ) -> tuple[str, float]:
        """Führt den Solver ohne double_required-Constraints aus.

        Patcht SUBJECT_METADATA temporär, um alle double_required=False zu setzen.
        Thread-safe ist dies nicht; für Diagnose-Zwecke (single-threaded) ausreichend.
        """
        from config.defaults import SUBJECT_METADATA
        from solver.scheduler import ScheduleSolver

        # Temporär patchen
        originals = {}
        for name, meta in SUBJECT_METADATA.items():
            if meta.get("double_required"):
                originals[name] = meta["double_required"]
                meta["double_required"] = False

        try:
            t0 = time.time()
            new_config = self.data.config.model_copy(deep=True)
            if new_config.solver.time_limit_seconds > time_limit:
                new_config.solver.time_limit_seconds = time_limit
                new_config.solver.num_workers = 2
            modified_data = SchoolData(
                subjects=self.data.subjects,
                rooms=self.data.rooms,
                classes=self.data.classes,
                teachers=self.data.teachers,
                couplings=self.data.couplings,
                config=new_config,
            )
            solver = ScheduleSolver(modified_data)
            solution = solver.solve(pins=pins, use_soft=False)
            elapsed = time.time() - t0
            return solution.solver_status, elapsed
        except Exception as e:
            elapsed = time.time() - t0
            logger.warning(f"Solver-Ausnahme (no_double_required): {e}")
            return "UNKNOWN", elapsed
        finally:
            # Patch zurücksetzen
            for name, orig_val in originals.items():
                SUBJECT_METADATA[name]["double_required"] = orig_val

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
        if by_name.get("double_tolerance") in ("OPTIMAL", "FEASIBLE"):
            fixes.append(
                "Deputat-Toleranz: Die Deputat-Grenzen sind zu eng. "
                "Erhöhen Sie deputat_tolerance in der Konfiguration."
            )

        if fixes:
            return "Mögliche Ursachen:\n" + "\n".join(f"  • {f}" for f in fixes)

        if by_name.get("all_combined") in ("OPTIMAL", "FEASIBLE"):
            return (
                "Erst alle Relaxierungen kombiniert helfen. "
                "Das Problem hat mehrere gleichzeitige Constraints-Konflikte."
            )

        return "Unklare Ursache. Prüfen Sie Lehrer-Fach-Abdeckung und Raumkapazitäten."
