"""Qualitätsbericht für fertige Stundenpläne.

Analysiert Lehrer-Auslastung, Klassen-Qualität und berechnet
zusammenfassende Metriken.
"""

from collections import defaultdict

from pydantic import BaseModel

from models.school_data import SchoolData
from solver.scheduler import ScheduleSolution
from export.helpers import (
    count_gaps, count_teacher_actual_hours, detect_double_starts,
)


# ─── Metriken-Modelle ─────────────────────────────────────────────────────────

class TeacherQualityMetrics(BaseModel):
    """Qualitäts-Metriken für eine einzelne Lehrkraft."""

    teacher_id: str
    name: str
    actual_hours: int
    dep_min: int
    dep_max: int
    gaps_total: int
    gaps_per_day: dict[str, int]
    hours_per_day: dict[str, int]
    free_days: int
    subjects_taught: list[str]


class ClassQualityMetrics(BaseModel):
    """Qualitäts-Metriken für eine einzelne Klasse."""

    class_id: str
    name: str
    total_hours: int
    hours_per_day: dict[str, int]
    double_requested: int
    double_fulfilled: int
    subject_spread_score: float  # 0.0–1.0


class ScheduleQualityReport(BaseModel):
    """Vollständiger Qualitätsbericht für eine ScheduleSolution."""

    teacher_metrics: list[TeacherQualityMetrics]
    class_metrics: list[ClassQualityMetrics]
    total_gaps: int
    avg_gaps_per_teacher: float
    deputat_fairness_index: float   # Jain's fairness index (1.0 = perfekt)
    double_fulfillment_rate: float  # 0.0–1.0
    solver_status: str
    solve_time: float


# ─── Analyzer ─────────────────────────────────────────────────────────────────

class QualityAnalyzer:
    """Berechnet Qualitätsmetriken für eine fertige ScheduleSolution."""

    def analyze(
        self, solution: ScheduleSolution, school_data: SchoolData
    ) -> ScheduleQualityReport:
        """Hauptmethode: berechnet alle Metriken und gibt einen Report zurück."""
        teacher_metrics = self._teacher_metrics(solution, school_data)
        class_metrics = self._class_metrics(solution, school_data)

        total_gaps = sum(m.gaps_total for m in teacher_metrics)
        n = len(teacher_metrics)
        avg_gaps = total_gaps / n if n > 0 else 0.0

        # Jain's Fairness Index: (Σ actual_i)² / (n * Σ actual_i²)
        actuals = [m.actual_hours for m in teacher_metrics]
        sum_a = sum(actuals)
        sum_sq = sum(a * a for a in actuals)
        if sum_sq > 0:
            fairness = (sum_a ** 2) / (n * sum_sq)
        else:
            fairness = 1.0

        total_requested = sum(m.double_requested for m in class_metrics)
        total_fulfilled = sum(m.double_fulfilled for m in class_metrics)
        double_rate = (
            total_fulfilled / total_requested if total_requested > 0 else 1.0
        )

        return ScheduleQualityReport(
            teacher_metrics=teacher_metrics,
            class_metrics=class_metrics,
            total_gaps=total_gaps,
            avg_gaps_per_teacher=round(avg_gaps, 2),
            deputat_fairness_index=round(fairness, 4),
            double_fulfillment_rate=round(double_rate, 4),
            solver_status=solution.solver_status,
            solve_time=round(solution.solve_time_seconds, 1),
        )

    def print_rich(
        self, report: ScheduleQualityReport, config=None
    ) -> None:
        """Gibt den Qualitätsbericht formatiert über Rich aus."""
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich import box

        console = Console()

        # KPI-Übersicht
        fairness_color = (
            "green" if report.deputat_fairness_index >= 0.95
            else "yellow" if report.deputat_fairness_index >= 0.85
            else "red"
        )
        double_color = (
            "green" if report.double_fulfillment_rate >= 0.90
            else "yellow" if report.double_fulfillment_rate >= 0.70
            else "red"
        )
        console.print(Panel(
            f"Status: [bold]{report.solver_status}[/bold] | "
            f"Zeit: {report.solve_time}s\n"
            f"Gesamt-Springstunden: [bold]{report.total_gaps}[/bold] | "
            f"Ø Springstunden/Lehrer: [bold]{report.avg_gaps_per_teacher:.1f}[/bold]\n"
            f"Deputat-Fairness (Jain): "
            f"[{fairness_color}]{report.deputat_fairness_index:.4f}[/{fairness_color}] "
            f"(1.0 = perfekt)\n"
            f"Doppelstunden-Rate: "
            f"[{double_color}]{report.double_fulfillment_rate:.1%}[/{double_color}]",
            title="Qualitätsbericht – Übersicht",
            border_style="cyan",
        ))

        # Lehrer-Tabelle
        t_table = Table(title="Lehrer-Auslastung", box=box.ROUNDED, show_lines=False)
        t_table.add_column("ID", width=8)
        t_table.add_column("Name", width=25)
        t_table.add_column("Min", justify="right", width=5)
        t_table.add_column("Max", justify="right", width=5)
        t_table.add_column("Ist", justify="right", width=5)
        t_table.add_column("Gaps", justify="right", width=6)
        t_table.add_column("Freie Tage", justify="right", width=10)
        t_table.add_column("Status", width=10)

        for m in sorted(report.teacher_metrics, key=lambda x: x.teacher_id):
            if m.actual_hours < m.dep_min:
                status = "[red]Unter Min[/red]"
            elif m.actual_hours > m.dep_max:
                status = "[yellow]Über Max[/yellow]"
            else:
                status = "[green]OK[/green]"
            t_table.add_row(
                m.teacher_id, m.name,
                str(m.dep_min), str(m.dep_max),
                str(m.actual_hours),
                str(m.gaps_total),
                str(m.free_days),
                status,
            )
        console.print(t_table)

        # Klassen-Tabelle
        c_table = Table(title="Klassen-Qualität", box=box.ROUNDED, show_lines=False)
        c_table.add_column("Klasse", width=8)
        c_table.add_column("Stunden", justify="right", width=8)
        c_table.add_column("Doppelstd. Soll", justify="right", width=16)
        c_table.add_column("Doppelstd. Ist", justify="right", width=15)
        c_table.add_column("Spread-Score", justify="right", width=12)

        for m in sorted(report.class_metrics, key=lambda x: x.class_id):
            spread_color = (
                "green" if m.subject_spread_score >= 0.7
                else "yellow" if m.subject_spread_score >= 0.4
                else "red"
            )
            c_table.add_row(
                m.class_id, str(m.total_hours),
                str(m.double_requested), str(m.double_fulfilled),
                f"[{spread_color}]{m.subject_spread_score:.2f}[/{spread_color}]",
            )
        console.print(c_table)

    # ── Private Berechnungen ──────────────────────────────────────────────────

    def _teacher_metrics(
        self, solution: ScheduleSolution, school_data: SchoolData
    ) -> list[TeacherQualityMetrics]:
        """Berechnet Metriken für alle Lehrer."""
        day_names = school_data.config.time_grid.day_names
        metrics = []

        for teacher in school_data.teachers:
            entries = solution.get_teacher_schedule(teacher.id)
            actual = count_teacher_actual_hours(solution.entries, teacher.id)

            # Springstunden gesamt und pro Tag
            t_entries_dedup = _dedup_teacher_entries(entries)
            gaps_total = count_gaps(t_entries_dedup)

            gaps_per_day: dict[str, int] = {}
            hours_per_day: dict[str, int] = {}
            days_with_lessons = set()

            by_day: dict[int, list] = defaultdict(list)
            for e in t_entries_dedup:
                by_day[e.day].append(e.slot_number)

            for day_idx in range(school_data.config.time_grid.days_per_week):
                slots = sorted(set(by_day.get(day_idx, [])))
                day_name = day_names[day_idx] if day_idx < len(day_names) else str(day_idx)
                hours_per_day[day_name] = len(slots)
                if slots:
                    days_with_lessons.add(day_idx)
                    gap = slots[-1] - slots[0] + 1 - len(slots) if len(slots) > 1 else 0
                    gaps_per_day[day_name] = gap
                else:
                    gaps_per_day[day_name] = 0

            free_days = school_data.config.time_grid.days_per_week - len(days_with_lessons)

            # Tatsächlich unterrichtete Fächer
            subjects_taught = list({e.subject for e in entries})

            metrics.append(TeacherQualityMetrics(
                teacher_id=teacher.id,
                name=teacher.name,
                actual_hours=actual,
                dep_min=teacher.deputat_min,
                dep_max=teacher.deputat_max,
                gaps_total=gaps_total,
                gaps_per_day=gaps_per_day,
                hours_per_day=hours_per_day,
                free_days=free_days,
                subjects_taught=sorted(subjects_taught),
            ))

        return metrics

    def _class_metrics(
        self, solution: ScheduleSolution, school_data: SchoolData
    ) -> list[ClassQualityMetrics]:
        """Berechnet Metriken für alle Klassen."""
        day_names = school_data.config.time_grid.day_names
        double_blocks = school_data.config.time_grid.double_blocks
        metrics = []

        # Welche Fächer wünschen Doppelstunden?
        subject_map = {s.name: s for s in school_data.subjects}
        double_preferred_subjects: set[str] = {
            s.name for s in school_data.subjects
            if s.double_lesson_required or s.double_lesson_preferred
        }

        for cls in school_data.classes:
            entries = solution.get_class_schedule(cls.id)
            total_hours = sum(1 for e in entries if not _is_duplicate_coupling(e, entries))

            # Stunden pro Tag
            by_day: dict[int, list[int]] = defaultdict(list)
            seen_coupling: set[tuple] = set()
            for e in entries:
                if e.is_coupling and e.coupling_id:
                    key = (e.coupling_id, e.day, e.slot_number)
                    if key in seen_coupling:
                        continue
                    seen_coupling.add(key)
                by_day[e.day].append(e.slot_number)

            hours_per_day: dict[str, int] = {}
            for day_idx in range(school_data.config.time_grid.days_per_week):
                day_name = day_names[day_idx] if day_idx < len(day_names) else str(day_idx)
                hours_per_day[day_name] = len(set(by_day.get(day_idx, [])))

            # Doppelstunden: Soll vs. Ist
            double_requested = sum(
                hours // 2
                for subj, hours in cls.curriculum.items()
                if subj in double_preferred_subjects and hours >= 2
            )
            double_starts = detect_double_starts(entries, double_blocks)
            double_fulfilled = len(double_starts)

            # Subject spread score: Wie gleichmäßig sind Fächer über die Woche verteilt?
            spread_score = _compute_spread_score(entries, school_data.config.time_grid.days_per_week)

            metrics.append(ClassQualityMetrics(
                class_id=cls.id,
                name=f"{cls.grade}{cls.label}",
                total_hours=total_hours,
                hours_per_day=hours_per_day,
                double_requested=double_requested,
                double_fulfilled=double_fulfilled,
                subject_spread_score=round(spread_score, 3),
            ))

        return metrics


# ─── Hilfsfunktionen ──────────────────────────────────────────────────────────

def _dedup_teacher_entries(entries):
    """Entfernt duplizierte Kopplungseinträge (ein Lehrer, mehrere Klassen)."""
    seen: set[tuple] = set()
    result = []
    for e in entries:
        if e.is_coupling and e.coupling_id:
            key = (e.coupling_id, e.day, e.slot_number)
            if key in seen:
                continue
            seen.add(key)
        result.append(e)
    return result


def _is_duplicate_coupling(entry, all_entries) -> bool:
    """True wenn dieser Kopplungseintrag bereits durch einen früheren in der Liste zählt."""
    if not (entry.is_coupling and entry.coupling_id):
        return False
    first = next(
        (e for e in all_entries
         if e.coupling_id == entry.coupling_id
         and e.day == entry.day
         and e.slot_number == entry.slot_number),
        None,
    )
    return first is not entry


def _compute_spread_score(entries, days_per_week: int) -> float:
    """Berechnet wie gleichmäßig Fächer über die Woche verteilt sind.

    Score 0.0–1.0:
    - 1.0 = jedes Fach ist auf möglichst viele verschiedene Tage verteilt
    - 0.0 = alle Stunden eines Fachs liegen am selben Tag
    """
    # Sammle Tage pro Fach
    subject_days: dict[str, set[int]] = defaultdict(set)
    subject_hours: dict[str, int] = defaultdict(int)

    seen_coupling: set[tuple] = set()
    for e in entries:
        if e.is_coupling and e.coupling_id:
            key = (e.coupling_id, e.day, e.slot_number)
            if key in seen_coupling:
                continue
            seen_coupling.add(key)
        subject_days[e.subject].add(e.day)
        subject_hours[e.subject] += 1

    if not subject_hours:
        return 1.0

    # Für jedes Fach: Verhältnis (Anzahl verschiedener Tage) / min(Stunden, days_per_week)
    scores = []
    for subj, hours in subject_hours.items():
        max_days = min(hours, days_per_week)
        actual_days = len(subject_days[subj])
        scores.append(actual_days / max_days if max_days > 0 else 1.0)

    return sum(scores) / len(scores)
