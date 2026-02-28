"""Vertretungshelfer: findet geeignete Vertreter für abwesende Lehrer.

Bewertet Kandidaten nach Fachkompetenz, Auslastung und Verfügbarkeit.
"""

from collections import defaultdict

from pydantic import BaseModel

from models.school_data import SchoolData
from solver.scheduler import ScheduleSolution
from export.helpers import count_teacher_actual_hours


class SubstituteCandidate(BaseModel):
    """Ein Kandidat für eine Vertretung."""

    teacher_id: str
    name: str
    subjects_match: list[str]       # Gemeinsame Fächer mit dem Fehlenden
    is_available_at_slot: bool      # Nicht im fraglichen Slot verplant
    current_load_hours: int         # Tatsächliche Stunden diese Woche
    load_ratio: float               # actual / dep_max (0.0–1.0+)
    score: float                    # 0–100 (höher = besser)


class SubstitutionFinder:
    """Findet passende Vertreter für abwesende Lehrkräfte."""

    def find_substitutes(
        self,
        absent_teacher_id: str,
        day: int,
        slot_number: int,
        solution: ScheduleSolution,
        school_data: SchoolData,
    ) -> list[SubstituteCandidate]:
        """Findet Vertreter für einen bestimmten Slot.

        Filtert: mind. 1 gemeinsames Fach, nicht im selben Slot verplant.
        Sortiert nach Score (höher = besser).
        """
        absent_teacher = next(
            (t for t in school_data.teachers if t.id == absent_teacher_id), None
        )
        if absent_teacher is None:
            return []

        absent_subjects = set(absent_teacher.subjects)

        # Welche Lehrer sind im fraglichen Slot belegt?
        busy_teachers: set[str] = set()
        for e in solution.entries:
            if e.day == day and e.slot_number == slot_number:
                busy_teachers.add(e.teacher_id)

        candidates = []
        for teacher in school_data.teachers:
            if teacher.id == absent_teacher_id:
                continue

            common_subjects = list(absent_subjects & set(teacher.subjects))
            if not common_subjects:
                continue

            available = teacher.id not in busy_teachers
            actual = count_teacher_actual_hours(solution.entries, teacher.id)
            load_ratio = actual / teacher.deputat_max if teacher.deputat_max > 0 else 1.0

            score = self._compute_score(
                common_subjects=common_subjects,
                absent_subjects=absent_subjects,
                is_available=available,
                load_ratio=load_ratio,
            )

            candidates.append(SubstituteCandidate(
                teacher_id=teacher.id,
                name=teacher.name,
                subjects_match=sorted(common_subjects),
                is_available_at_slot=available,
                current_load_hours=actual,
                load_ratio=round(load_ratio, 3),
                score=round(score, 1),
            ))

        # Nur Kandidaten mit Fachübereinstimmung; nach Score sortieren
        candidates.sort(key=lambda c: c.score, reverse=True)
        return candidates

    def find_all_for_teacher(
        self,
        teacher_id: str,
        solution: ScheduleSolution,
        school_data: SchoolData,
    ) -> dict[str, list[SubstituteCandidate]]:
        """Findet Vertreter für alle Slots eines Lehrers.

        Gibt ein Dict zurück: key = "Tag-Slot" (z.B. "Mo-3"),
        value = sortierte Kandidatenliste.
        """
        day_names = school_data.config.time_grid.day_names
        result: dict[str, list[SubstituteCandidate]] = {}

        # Sammle alle Slots dieses Lehrers
        teacher_slots: set[tuple] = set()
        seen_coupling: set[tuple] = set()

        for e in solution.entries:
            if e.teacher_id != teacher_id:
                continue
            if e.is_coupling and e.coupling_id:
                key = (e.coupling_id, e.day, e.slot_number)
                if key in seen_coupling:
                    continue
                seen_coupling.add(key)
            teacher_slots.add((e.day, e.slot_number))

        for (day, slot) in sorted(teacher_slots):
            day_name = day_names[day] if day < len(day_names) else str(day)
            key = f"{day_name}-{slot}"
            result[key] = self.find_substitutes(
                absent_teacher_id=teacher_id,
                day=day,
                slot_number=slot,
                solution=solution,
                school_data=school_data,
            )

        return result

    # ── Score-Berechnung ──────────────────────────────────────────────────────

    def _compute_score(
        self,
        common_subjects: list[str],
        absent_subjects: set[str],
        is_available: bool,
        load_ratio: float,
    ) -> float:
        """Berechnet den Eignung-Score eines Kandidaten (0–100).

        Zusammensetzung:
        - Fachübereinstimmung: bis 50 Punkte
          (Anteil gemeinsamer Fächer × 50)
        - Verfügbarkeit: 20 Punkte (wenn nicht belegt)
        - Auslastung: bis 30 Punkte ((1 - load_ratio) × 30)
        """
        subject_ratio = len(common_subjects) / max(len(absent_subjects), 1)
        subject_score = min(subject_ratio, 1.0) * 50.0

        availability_score = 20.0 if is_available else 0.0

        # Weniger ausgelastet = mehr Punkte; bei load_ratio ≥ 1 keine Punkte
        load_score = max(0.0, (1.0 - load_ratio)) * 30.0

        return subject_score + availability_score + load_score
