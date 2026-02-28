"""Post-Solve Validierung der fertigen Stundenpläne.

Prüft die fertige Lösung auf Constraint-Verletzungen als Sicherheitsnetz
unabhängig vom Solver.
"""

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel

from models.school_data import SchoolData
from solver.scheduler import ScheduleEntry, ScheduleSolution
from export.helpers import count_teacher_actual_hours


class ValidationViolation(BaseModel):
    """Eine einzelne Constraint-Verletzung."""

    severity: Literal["error", "warning"]
    constraint: str      # z.B. "teacher_double_booking"
    description: str
    entity: str          # teacher_id / class_id / room_id


class ValidationReport(BaseModel):
    """Ergebnis der Post-Solve Validierung."""

    violations: list[ValidationViolation]
    is_valid: bool       # True wenn keine Errors (Warnings ok)

    def print_rich(self) -> None:
        """Gibt den Report formatiert über Rich aus."""
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich import box

        console = Console()
        errors = [v for v in self.violations if v.severity == "error"]
        warnings = [v for v in self.violations if v.severity == "warning"]

        status = (
            "[bold green]✓ VALIDE[/bold green]"
            if self.is_valid
            else "[bold red]✗ VERLETZUNGEN GEFUNDEN[/bold red]"
        )
        lines = [status, f"Fehler: {len(errors)} | Warnungen: {len(warnings)}"]
        console.print(Panel("\n".join(lines), title="Lösung-Validierung", border_style="cyan"))

        if not self.violations:
            console.print("[dim]Keine Verletzungen gefunden.[/dim]")
            return

        table = Table(box=box.ROUNDED, show_lines=True)
        table.add_column("Typ", width=8)
        table.add_column("Constraint", width=28)
        table.add_column("Entität", width=12)
        table.add_column("Beschreibung")

        for v in self.violations:
            color = "red" if v.severity == "error" else "yellow"
            table.add_row(
                f"[{color}]{v.severity.upper()}[/{color}]",
                v.constraint,
                v.entity,
                v.description,
            )
        console.print(table)


class SolutionValidator:
    """Prüft eine fertige ScheduleSolution auf Constraint-Verletzungen."""

    def validate(
        self, solution: ScheduleSolution, school_data: SchoolData
    ) -> ValidationReport:
        """Führt alle Validierungschecks durch und gibt einen ValidationReport zurück."""
        violations: list[ValidationViolation] = []

        violations.extend(self._check_teacher_double_booking(solution))
        violations.extend(self._check_class_double_booking(solution, school_data))
        violations.extend(self._check_room_double_booking(solution))
        violations.extend(self._check_assignment_fulfillment(solution, school_data))
        violations.extend(self._check_deputat_bounds(solution, school_data))
        violations.extend(self._check_coupling_consistency(solution, school_data))
        violations.extend(self._check_unavailable_slots(solution, school_data))

        has_errors = any(v.severity == "error" for v in violations)
        return ValidationReport(violations=violations, is_valid=not has_errors)

    # ── Einzelne Prüfungen ────────────────────────────────────────────────────

    def _check_teacher_double_booking(
        self, solution: ScheduleSolution
    ) -> list[ValidationViolation]:
        """Kein Lehrer darf zur selben Zeit in zwei Klassen sein."""
        violations: list[ValidationViolation] = []
        # Zähle Einträge pro (teacher, day, slot); Kopplungen zählen einmal
        seen: dict[tuple, list[str]] = defaultdict(list)
        coupling_seen: set[tuple] = set()

        for e in solution.entries:
            if e.is_coupling and e.coupling_id:
                key = (e.teacher_id, e.day, e.slot_number, e.coupling_id)
                if key in coupling_seen:
                    continue
                coupling_seen.add(key)

            slot_key = (e.teacher_id, e.day, e.slot_number)
            seen[slot_key].append(e.class_id)

        for (teacher_id, day, slot), classes in seen.items():
            if len(classes) > 1:
                violations.append(ValidationViolation(
                    severity="error",
                    constraint="teacher_double_booking",
                    entity=teacher_id,
                    description=(
                        f"Tag {day+1}, Slot {slot}: gleichzeitig in "
                        f"{', '.join(classes)} eingeplant."
                    ),
                ))
        return violations

    def _check_class_double_booking(
        self, solution: ScheduleSolution, school_data: SchoolData
    ) -> list[ValidationViolation]:
        """Eine Klasse darf pro Slot nur einen regulären Eintrag haben.

        Kopplungen (reli_ethik) können mehrere Einträge pro Slot erzeugen –
        das ist korrekt und wird hier nicht als Fehler gewertet.
        """
        violations: list[ValidationViolation] = []

        # Ermittle Kopplungen vom Typ reli_ethik
        reli_coupling_ids: set[str] = {
            c.id for c in school_data.couplings if c.coupling_type == "reli_ethik"
        }

        by_slot: dict[tuple, list[ScheduleEntry]] = defaultdict(list)
        for e in solution.entries:
            by_slot[(e.class_id, e.day, e.slot_number)].append(e)

        for (class_id, day, slot), entries in by_slot.items():
            if len(entries) <= 1:
                continue
            # Alle Einträge aus reli_ethik-Kopplungen → erlaubt (mehrere Gruppen)
            all_reli = all(
                e.is_coupling and e.coupling_id in reli_coupling_ids
                for e in entries
            )
            if not all_reli:
                subjects = [e.subject for e in entries]
                violations.append(ValidationViolation(
                    severity="error",
                    constraint="class_double_booking",
                    entity=class_id,
                    description=(
                        f"Tag {day+1}, Slot {slot}: mehrere Einträge "
                        f"({', '.join(subjects)}) ohne Kopplungserlaubnis."
                    ),
                ))
        return violations

    def _check_room_double_booking(
        self, solution: ScheduleSolution
    ) -> list[ValidationViolation]:
        """Ein Sonderraum darf pro Slot nur einmal belegt sein."""
        violations: list[ValidationViolation] = []
        seen: dict[tuple, list[str]] = defaultdict(list)
        coupling_room_seen: set[tuple] = set()

        for e in solution.entries:
            if not e.room:
                continue
            if e.is_coupling and e.coupling_id:
                key = (e.room, e.day, e.slot_number, e.coupling_id)
                if key in coupling_room_seen:
                    continue
                coupling_room_seen.add(key)
            seen[(e.room, e.day, e.slot_number)].append(e.class_id)

        for (room_id, day, slot), classes in seen.items():
            if len(classes) > 1:
                violations.append(ValidationViolation(
                    severity="error",
                    constraint="room_double_booking",
                    entity=room_id,
                    description=(
                        f"Tag {day+1}, Slot {slot}: gleichzeitig von "
                        f"{', '.join(classes)} belegt."
                    ),
                ))
        return violations

    def _check_assignment_fulfillment(
        self, solution: ScheduleSolution, school_data: SchoolData
    ) -> list[ValidationViolation]:
        """Prüft ob die Soll-Stunden pro Klasse/Fach eingehalten wurden."""
        violations: list[ValidationViolation] = []

        # Tatsächliche Stunden: pro (class_id, subject) zählen
        actual: dict[tuple, int] = defaultdict(int)
        coupling_seen: set[tuple] = set()

        for e in solution.entries:
            if e.is_coupling and e.coupling_id:
                key = (e.class_id, e.coupling_id, e.day, e.slot_number)
                if key in coupling_seen:
                    continue
                coupling_seen.add(key)
            actual[(e.class_id, e.subject)] += 1

        # Erwartete Stunden aus Curriculum
        for cls in school_data.classes:
            for subject, hours in cls.curriculum.items():
                if hours == 0:
                    continue
                got = actual.get((cls.id, subject), 0)
                if got != hours:
                    sev = "error" if abs(got - hours) > 1 else "warning"
                    violations.append(ValidationViolation(
                        severity=sev,
                        constraint="assignment_mismatch",
                        entity=cls.id,
                        description=(
                            f"Fach {subject}: Soll {hours}h, Ist {got}h "
                            f"(Differenz {got - hours:+d}h)."
                        ),
                    ))
        return violations

    def _check_deputat_bounds(
        self, solution: ScheduleSolution, school_data: SchoolData
    ) -> list[ValidationViolation]:
        """Prüft ob Deputat-Grenzen (min ≤ actual ≤ max) eingehalten werden."""
        violations: list[ValidationViolation] = []
        teacher_map = {t.id: t for t in school_data.teachers}

        for teacher in school_data.teachers:
            actual = count_teacher_actual_hours(solution.entries, teacher.id)
            if actual > teacher.deputat_max:
                violations.append(ValidationViolation(
                    severity="error",
                    constraint="deputat_exceeded",
                    entity=teacher.id,
                    description=(
                        f"Ist {actual}h > Max {teacher.deputat_max}h "
                        f"(Überschreitung: +{actual - teacher.deputat_max}h)."
                    ),
                ))
            elif actual < teacher.deputat_min:
                violations.append(ValidationViolation(
                    severity="warning",
                    constraint="deputat_underrun",
                    entity=teacher.id,
                    description=(
                        f"Ist {actual}h < Min {teacher.deputat_min}h "
                        f"(Unterdeckung: {actual - teacher.deputat_min}h)."
                    ),
                ))
        return violations

    def _check_coupling_consistency(
        self, solution: ScheduleSolution, school_data: SchoolData
    ) -> list[ValidationViolation]:
        """Alle Klassen einer Kopplung müssen zur selben Zeit eingeplant sein."""
        violations: list[ValidationViolation] = []

        for coupling in school_data.couplings:
            # Finde alle (day, slot)-Paare für jede beteiligte Klasse
            class_slots: dict[str, set[tuple]] = defaultdict(set)
            for e in solution.entries:
                if e.coupling_id == coupling.id:
                    class_slots[e.class_id].add((e.day, e.slot_number))

            if not class_slots:
                continue

            # Alle beteiligten Klassen sollten dieselben Slots belegen
            all_slot_sets = list(class_slots.values())
            reference = all_slot_sets[0]
            for class_id, slots in class_slots.items():
                if slots != reference:
                    violations.append(ValidationViolation(
                        severity="error",
                        constraint="coupling_inconsistency",
                        entity=coupling.id,
                        description=(
                            f"Klasse {class_id} hat abweichende Slots "
                            f"in Kopplung '{coupling.id}'."
                        ),
                    ))
        return violations

    def _check_unavailable_slots(
        self, solution: ScheduleSolution, school_data: SchoolData
    ) -> list[ValidationViolation]:
        """Kein Lehrer darf in gesperrten Slots eingeplant sein."""
        violations: list[ValidationViolation] = []
        teacher_map = {t.id: t for t in school_data.teachers}

        for e in solution.entries:
            teacher = teacher_map.get(e.teacher_id)
            if teacher and (e.day, e.slot_number) in teacher.unavailable_slots:
                violations.append(ValidationViolation(
                    severity="error",
                    constraint="unavailable_slot_violation",
                    entity=e.teacher_id,
                    description=(
                        f"Tag {e.day+1}, Slot {e.slot_number} ist gesperrt, "
                        f"aber {e.subject} für {e.class_id} eingeplant."
                    ),
                ))
        return violations
