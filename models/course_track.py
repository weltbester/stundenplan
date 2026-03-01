"""Kursschienen-Modell für die Oberstufe (Pydantic v2)."""

from pydantic import BaseModel


class CourseTrack(BaseModel):
    """Kursschiene: Kurse, die an identischen (Tag, Slot)-Paaren stattfinden.

    Alle Kurse in derselben Schiene laufen parallel — Schüler wählen genau
    einen Kurs pro Schiene. Das Modell erzwingt die Gleichzeitigkeit ohne
    individuelle Schüler-Konflikt-Verfolgung.
    """

    id: str               # z.B. "Q1-KS1"
    name: str             # z.B. "Kursschiene 1 (Q1)"
    course_ids: list[str] # SchoolClass-IDs aller Kurse in dieser Schiene
    hours_per_week: int   # Alle Kurse der Schiene teilen diese Wochenstundenzahl
