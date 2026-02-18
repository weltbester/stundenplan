"""SchoolData: Vollständiger Schuldatensatz + Machbarkeits-Check (Pydantic v2)."""

import json
from pathlib import Path

from pydantic import BaseModel

from models.subject import Subject
from models.teacher import Teacher
from models.school_class import SchoolClass
from models.room import Room
from models.coupling import Coupling
from config.schema import SchoolConfig


class FeasibilityReport(BaseModel):
    """Ergebnis des Machbarkeits-Checks."""

    is_feasible: bool
    errors: list[str]      # Kritische Probleme (Lösung unmöglich)
    warnings: list[str]    # Hinweise (Lösung schwierig aber möglich)

    def print_rich(self) -> None:
        """Gibt den Report formatiert über Rich aus."""
        from rich.console import Console
        from rich.panel import Panel
        from rich import box

        console = Console()
        if self.is_feasible:
            status = "[bold green]✓ LÖSBAR[/bold green]"
        else:
            status = "[bold red]✗ NICHT LÖSBAR[/bold red]"

        lines = [status]
        if self.errors:
            lines.append("\n[red bold]Fehler (kritisch):[/red bold]")
            for e in self.errors:
                lines.append(f"  [red]• {e}[/red]")
        if self.warnings:
            lines.append("\n[yellow bold]Warnungen:[/yellow bold]")
            for w in self.warnings:
                lines.append(f"  [yellow]• {w}[/yellow]")
        if not self.errors and not self.warnings:
            lines.append("[dim]Keine Probleme gefunden.[/dim]")

        console.print(Panel("\n".join(lines), title="Machbarkeits-Check", border_style="cyan"))


class SchoolData(BaseModel):
    """Vollständiger Schuldatensatz: Fächer, Räume, Klassen, Lehrer, Kopplungen."""

    subjects: list[Subject]
    rooms: list[Room]
    classes: list[SchoolClass]
    teachers: list[Teacher]
    couplings: list[Coupling]
    config: SchoolConfig

    # ─── Übersicht ───

    def summary(self) -> str:
        """Kurze Übersicht über den Datensatz."""
        total_need = sum(sum(c.curriculum.values()) for c in self.classes)
        total_dep = sum(t.deputat for t in self.teachers)
        num_teilzeit = sum(1 for t in self.teachers if t.is_teilzeit)
        lines = [
            f"Schule: {self.config.school_name}",
            f"Klassen: {len(self.classes)} "
            f"({len(set(c.grade for c in self.classes))} Jahrgänge)",
            f"Fächer: {len(self.subjects)}",
            f"Lehrkräfte: {len(self.teachers)} "
            f"({num_teilzeit} Teilzeit, {len(self.teachers)-num_teilzeit} Vollzeit)",
            f"Gesamtdeputat: {total_dep}h/Woche",
            f"Gesamtbedarf (Curriculum): {total_need}h/Woche",
            f"Puffer: {total_dep - total_need:+d}h "
            f"({(total_dep/total_need - 1)*100:.1f}%)" if total_need else "",
            f"Räume (Fachräume): {len(self.rooms)}",
            f"Kopplungen: {len(self.couplings)}",
        ]
        return "\n".join(l for l in lines if l)

    # ─── Machbarkeits-Check ───

    def validate_feasibility(self) -> FeasibilityReport:
        """Prüft ob die Konfiguration grundsätzlich lösbar ist.

        Prüfungen:
        1. Pro Fach: Gesamtbedarf ≤ Fachlehrer-Kapazität
        2. Fachräume: Stundenbedarf ≤ verfügbare Raumslots
        3. Jeder Lehrer: freie Slots ≥ Deputat
        4. Kopplungen: qualifizierte Lehrer vorhanden
        5. Gesamtbilanz: Summe Deputate ≥ Summe Stundenbedarf
        """
        errors: list[str] = []
        warnings: list[str] = []

        tg = self.config.time_grid
        sek1_max = tg.sek1_max_slot
        days = tg.days_per_week
        total_slots_per_week = sek1_max * days  # z.B. 7 × 5 = 35

        # Anzahl Doppelstunden-Blöcke pro Tag (für Fachraum-Check)
        double_blocks_per_day = len(tg.double_blocks)

        subject_map = {s.name: s for s in self.subjects}

        # ── 5. Gesamtbilanz ──────────────────────────────────────────────
        total_deputat = sum(t.deputat for t in self.teachers)
        total_need = sum(sum(c.curriculum.values()) for c in self.classes)

        if total_need == 0:
            warnings.append("Kein Curriculum definiert – Machbarkeit kann nicht geprüft werden.")
        elif total_deputat < total_need:
            errors.append(
                f"Gesamtbilanz: Lehrerkapazität ({total_deputat}h) < Gesamtbedarf ({total_need}h). "
                f"Fehlen mindestens {total_need - total_deputat}h. Mehr Lehrkräfte benötigt."
            )
        elif total_deputat < total_need * 1.05:
            puffer = (total_deputat / total_need - 1) * 100
            warnings.append(
                f"Gesamtbilanz sehr knapp: {total_deputat}h Kapazität bei {total_need}h Bedarf "
                f"(nur {puffer:.1f}% Puffer – Stundenplan schwer zu erstellen)."
            )

        # ── 3. Jeder Lehrer: verfügbare Slots ≥ Deputat ─────────────────
        for teacher in self.teachers:
            available = total_slots_per_week - len(teacher.unavailable_slots)
            if available < teacher.deputat:
                errors.append(
                    f"Lehrkraft {teacher.id} ({teacher.name}): Nur {available} verfügbare Slots "
                    f"bei Deputat {teacher.deputat}h. Sperrzeiten reduzieren oder Deputat anpassen."
                )
            elif available - teacher.deputat < 2:
                warnings.append(
                    f"Lehrkraft {teacher.id}: Sehr wenig Spielraum – "
                    f"{available} Slots bei {teacher.deputat}h Deputat."
                )

        # Freitag-Cluster-Warnung
        freitag_wunsch = [t for t in self.teachers if 4 in t.preferred_free_days]
        if len(freitag_wunsch) >= 4:
            warnings.append(
                f"Freitag-Cluster: {len(freitag_wunsch)} Lehrkräfte wünschen Freitag frei "
                f"({', '.join(t.id for t in freitag_wunsch[:6])}"
                f"{'...' if len(freitag_wunsch) > 6 else ''}) – "
                f"Stundenplan-Erststellung an Freitagen schwierig."
            )

        # ── 1. Pro Fach: Gesamtbedarf ≤ Fachlehrer-Kapazität ────────────
        subject_need: dict[str, int] = {}
        for cls in self.classes:
            for subj, hours in cls.curriculum.items():
                if hours > 0:
                    subject_need[subj] = subject_need.get(subj, 0) + hours

        # Fächer, die über Kopplungen abgedeckt werden → kein direkter Kapazitäts-Check.
        # Für WPF: Curriculum-Eintrag "WPF" wird via Kopplung besetzt.
        # Für Reli/Ethik: "Religion" im Curriculum entspricht dem Kopplungs-Pool;
        #   der tatsächliche Bedarf je Lehrer ist wegen Gruppenaufteilung viel kleiner
        #   (z.B. 36 Klassen × 2h → 3 Gruppen à je 12h ≠ 72h für einen Lehrer).
        #   Die Lehrerkapazität wird separat im Kopplungs-Check (Abschnitt 4) geprüft.
        coupling_covered: set[str] = set()
        for coupling in self.couplings:
            if coupling.coupling_type == "wpf":
                coupling_covered.add("WPF")
            elif coupling.coupling_type == "reli_ethik":
                # Alle Fächer der Gruppen (Religion, Ethik) vom Haupt-Check ausschließen
                for group in coupling.groups:
                    coupling_covered.add(group.subject)

        # Lehrer-Kapazität pro Fach (Summe aller Deputate der Lehrkräfte dieses Fachs)
        subject_capacity: dict[str, int] = {}
        for teacher in self.teachers:
            for subj in teacher.subjects:
                subject_capacity[subj] = subject_capacity.get(subj, 0) + teacher.deputat

        for subj_name, need in subject_need.items():
            if subj_name in coupling_covered:
                continue  # Wird via Kopplung abgedeckt, kein direkter Lehrer-Check
            cap = subject_capacity.get(subj_name, 0)
            if cap == 0:
                errors.append(
                    f"Fach '{subj_name}': Kein Lehrer verfügbar! "
                    f"({need}h/Woche werden benötigt)"
                )
            elif cap < need * 0.90:
                # Deutlicher Mangel: Kapazität < 90% des Bedarfs → kritisch
                errors.append(
                    f"Fach '{subj_name}': Lehrerkapazität ({cap}h) deutlich unter Bedarf "
                    f"({need}h, {need - cap}h Mangel). Zusätzliche Lehrkraft benötigt."
                )
            elif cap < need:
                # Geringfügiger Mangel: Rough-Approximation, oft durch Fächeraufteilung lösbar
                util = need / cap * 100
                warnings.append(
                    f"Fach '{subj_name}': Kapazität ({cap}h) knapp unter Bedarf ({need}h) – "
                    f"Fächeraufteilung der Mehrtach-Lehrer beachten."
                )
            elif cap < need * 1.10:
                util = need / cap * 100
                warnings.append(
                    f"Fach '{subj_name}': Auslastung sehr hoch – "
                    f"{need}h Bedarf bei {cap}h Kapazität ({util:.0f}%)."
                )

        # ── 2. Fachräume: Bedarf ≤ verfügbare Raumslots ─────────────────
        room_counts: dict[str, int] = {}
        for room in self.rooms:
            room_counts[room.room_type] = room_counts.get(room.room_type, 0) + 1

        for subj_name, need_hours in subject_need.items():
            subj = subject_map.get(subj_name)
            if not subj or not subj.requires_special_room:
                continue

            room_type = subj.requires_special_room
            room_count = room_counts.get(room_type, 0)

            if room_count == 0:
                errors.append(
                    f"Fach '{subj_name}': Benötigt Fachraum '{room_type}', "
                    f"aber keine solchen Räume konfiguriert!"
                )
                continue

            if subj.double_lesson_required:
                # Pro Klasse: floor(hours/2) Doppelstunden-Events (z.B. 2h→1, 3h→1, 4h→2)
                events_needed = sum(
                    cls.curriculum.get(subj_name, 0) // 2
                    for cls in self.classes
                )
                max_events = room_count * double_blocks_per_day * days
                util = events_needed / max_events if max_events > 0 else float("inf")
                if util > 1.0:
                    errors.append(
                        f"Fachraum-Engpass '{subj_name}': {events_needed} Doppelstunden-Events "
                        f"benötigt, aber nur {max_events} möglich "
                        f"({room_count} Räume × {double_blocks_per_day} Blöcke × {days} Tage)."
                    )
                elif util > 0.85:
                    warnings.append(
                        f"Fachraum-Engpass '{subj_name}': Hohe Auslastung "
                        f"{events_needed}/{max_events} Doppelstunden-Slots "
                        f"({util*100:.0f}%) – {room_count} {room_type}-Räume."
                    )
            else:
                # Einzelstunden: Bedarf / (Räume × Tage) als Durchschnitt
                max_per_week = room_count * sek1_max * days
                if need_hours > max_per_week:
                    errors.append(
                        f"Fachraum-Engpass '{subj_name}': {need_hours}h/Woche benötigt, "
                        f"aber nur {max_per_week} Raumslots verfügbar."
                    )

        # ── 4. Kopplungen: qualifizierte Lehrer vorhanden ────────────────
        for coupling in self.couplings:
            for group in coupling.groups:
                cap = subject_capacity.get(group.subject, 0)
                if cap == 0:
                    errors.append(
                        f"Kopplung '{coupling.id}', Gruppe '{group.group_name}': "
                        f"Kein Lehrer für Fach '{group.subject}' vorhanden!"
                    )

        return FeasibilityReport(
            is_feasible=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    # ─── Persistenz ────────────────────────────────────────────────────────

    def save_json(self, path: Path) -> None:
        """Speichert den kompletten Datensatz als JSON-Datei."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))

    @classmethod
    def load_json(cls, path: Path) -> "SchoolData":
        """Lädt einen Datensatz aus einer JSON-Datei."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"JSON-Datei nicht gefunden: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return cls.model_validate_json(f.read())
