"""Testdaten-Profil "nrw-g9": ein NRW-Gymnasium mit realistischer Besetzung.

Unterschiede zum bisherigen Generator (data/fake_data.py):

- Stundentafel NRW G9 (config/nrw_g9.py) mit Sprachen-Schiene,
  Religionslehre/Praktische Philosophie und Wahlpflicht; jede Kopplung
  hat so viele Gruppen wie der Jahrgang Klassen.
- Die Lehrkräfte entstehen aus dem Bedarf: je Fach so viele Stunden,
  wie die Stundentafel verlangt, plus ein kleiner Zuschlag. Es gibt
  also für jedes Fach Lehrkräfte, und die Summe der Soll-Stunden liegt
  nur wenige Prozent über dem Bedarf.
- Soll 25,5 Stunden bei Vollzeit, enge Grenzen um das Soll.
- Ein Teil des Deputats liegt in der Sekundarstufe II. Diese Stunden
  fehlen im Sek-I-Soll und erscheinen als Sperrzeiten. Wie an einer
  echten Schule liegen sie in wenigen gemeinsamen Oberstufen-Schienen
  (dieselben Doppelstunden für alle), nicht zufällig je Lehrkraft:
  zufällige Sperren lassen gekoppelten Gruppen kaum gemeinsame Zeiten.
- Teilzeitkräfte haben einen freien Tag oder gesperrte Randstunden.
"""

import math
import random
from collections import Counter
from typing import Optional

from pydantic import BaseModel

from config.defaults import SECOND_LANGUAGE_SUBJECT
from config.nrw_g9 import STUNDENTAFEL_NRW_G9
from config.schema import (
    GradeConfig, SchoolConfig, SchoolType, TimeGridConfig,
)
from data.coupling_builder import (
    RELIGION_SUBJECT, parallel_coupling, reli_group_subject,
)
from data.fake_data import (
    FIRST_NAMES_F, FIRST_NAMES_M, LAST_NAMES, CurriculumTable,
    FakeDataGenerator,
)
from models.coupling import (
    COUPLING_TYPE_BAND, COUPLING_TYPE_RELI_ETHIK, COUPLING_TYPE_WPF,
    WPF_CURRICULUM_SUBJECT, Coupling,
)
from models.fixed_assignment import coupling_subjects_by_class
from models.school_class import SchoolClass
from models.school_data import SchoolData
from models.subject import default_subjects
from models.teacher import HALF_LESSONS_PER_LESSON, Teacher
from solver.distribution import (
    lessons_every_day, sek1_slot_numbers, weekly_lessons,
)

SUPPORT_SUBJECT = "Ergänzungsstunde"
# Lehrkräfte dieser Fächer übernehmen auch die Ergänzungsstunden.
SUPPORT_HOST_SUBJECTS = ("Deutsch", "Mathematik", "Englisch")
MAX_SUBJECTS = 3
# Anteil des Sek-I-Solls, den das erste Fach höchstens bekommt.
MAIN_SUBJECT_SHARE = 0.6
# Kleinere Reste eines Fachs werden nicht mehr eigens besetzt.
MIN_SHARE_HOURS = 1.0
# Kleinere Stellen werden auf vorhandene Lehrkräfte verteilt.
MIN_POST_HOURS = 4.0
# Für parallele Gruppen eines Fachs gibt es so viele Lehrkräfte mehr,
# als gleichzeitig gebraucht werden.
SPARE_TEACHERS = 2
# Nach allen Sperrzeiten bleiben so viele Stunden über der Obergrenze frei.
RESERVE_HOURS = 4
FEMALE_SHARE = 0.55
MIN_TEACHER_COUNT = 10
MAX_DIGIT = 10

# Übliche Fächerkombinationen (in beide Richtungen).
_SUBJECT_PAIRS: tuple[tuple[str, str], ...] = (
    ("Deutsch", "Geschichte"), ("Deutsch", "Englisch"),
    ("Deutsch", "Religion"), ("Deutsch", "Praktische Philosophie"),
    ("Deutsch", "Erdkunde"), ("Deutsch", "Wirtschaft-Politik"),
    ("Deutsch", "Kunst"), ("Deutsch", "Musik"),
    ("Deutsch", "Französisch"), ("Deutsch", "Latein"),
    ("Deutsch", "Sport"),
    ("Mathematik", "Physik"), ("Mathematik", "Informatik"),
    ("Mathematik", "Chemie"), ("Mathematik", "Biologie"),
    ("Mathematik", "Sport"), ("Mathematik", "Erdkunde"),
    ("Mathematik", "Musik"), ("Mathematik", "Religion"),
    ("Englisch", "Geschichte"), ("Englisch", "Französisch"),
    ("Englisch", "Erdkunde"), ("Englisch", "Sport"),
    ("Englisch", "Wirtschaft-Politik"), ("Englisch", "Biologie"),
    ("Englisch", "Kunst"), ("Englisch", "Musik"),
    ("Englisch", "Religion"), ("Englisch", "Praktische Philosophie"),
    ("Englisch", "Latein"),
    ("Biologie", "Chemie"), ("Biologie", "Sport"),
    ("Biologie", "Erdkunde"),
    ("Physik", "Chemie"), ("Physik", "Informatik"), ("Physik", "Sport"),
    ("Geschichte", "Wirtschaft-Politik"), ("Geschichte", "Latein"),
    ("Geschichte", "Französisch"), ("Geschichte", "Sport"),
    ("Geschichte", "Religion"), ("Geschichte", "Erdkunde"),
    ("Geschichte", "Praktische Philosophie"), ("Geschichte", "Kunst"),
    ("Erdkunde", "Wirtschaft-Politik"), ("Erdkunde", "Sport"),
    ("Wirtschaft-Politik", "Sport"),
)


def _partners() -> dict[str, set[str]]:
    partners: dict[str, set[str]] = {}
    for first, second in _SUBJECT_PAIRS:
        partners.setdefault(first, set()).add(second)
        partners.setdefault(second, set()).add(first)
    return partners


PARTNERS = _partners()


class NrwProfile(BaseModel):
    """Stellschrauben des Profils "nrw-g9"."""

    # Soll-Stunden einer Vollzeitkraft (NRW, Gymnasium)
    full_time_hours: float = 25.5
    part_time_share: float = 0.30
    # Summe der Sek-I-Soll-Stunden über dem Unterrichtsbedarf
    capacity_margin: float = 0.04
    # Grenzen um das Soll: Soll aufgerundet + 1, Soll abgerundet − 2
    deputat_max_buffer: int = 1
    deputat_min_buffer: int = 2
    # Anteil des Deputats in der Sek II: mögliche Werte und ihre Gewichte
    sek2_shares: tuple[float, ...] = (0.0, 0.25, 0.4, 0.55)
    sek2_share_weights: tuple[int, ...] = (15, 25, 35, 25)
    # Anteil der Sek-II-Stunden, die in das Sek-I-Raster fallen
    sek2_morning_fraction: float = 0.75
    # Zahl der Oberstufen-Schienen im Sek-I-Raster (je eine Doppelstunde
    # an einem Tag); nur dort liegen die Sek-II-Sperren.
    sek2_band_count: int = 8
    # In jeder Stunde, in der jede Klasse Unterricht haben muss, bleiben
    # mindestens so viele Lehrkräfte frei: Klassen mal (1 + Reserve).
    attendance_reserve: float = 0.15
    # Teilzeit: ganzer freier Tag; sonst gesperrte Randstunden
    free_day_probability: float = 0.5
    edge_block_probability: float = 0.3
    # Vollzeit: Wunsch nach einem freien Tag (weich)
    day_wish_probability: float = 0.15
    min_sek1_hours: float = 6.0
    reli_groups: tuple[str, ...] = (
        "evangelisch", "katholisch", "Praktische Philosophie",
    )
    wpf_subjects: tuple[str, ...] = (
        "Informatik", "Wirtschaft-Politik", "Biologie",
    )


class StaffPost(BaseModel):
    """Eine geplante Stelle: Deputat und Stunden je Fach in der Sek I."""

    total_hours: float          # ganzes Deputat (Sek I + Sek II)
    is_part_time: bool
    shares: dict[str, float]    # Fach → geplante Sek-I-Stunden

    @property
    def sek1_hours(self) -> float:
        return round_half(sum(self.shares.values()))


def round_half(hours: float) -> float:
    """Rundet auf halbe Unterrichtsstunden."""
    return round(hours * HALF_LESSONS_PER_LESSON) / HALF_LESSONS_PER_LESSON


def nrw_g9_config(
    base: SchoolConfig,
    profile: NrwProfile,
    curriculum: CurriculumTable = STUNDENTAFEL_NRW_G9,
) -> SchoolConfig:
    """Konfiguration des Profils: Klassen, Zeitraster und Räume aus
    `base`; Kopplungen, Deputatsgrenzen und Soll-Stunden nach NRW G9
    (Soll-Stunden je Jahrgang aus `curriculum`)."""
    grades = GradeConfig(grades=[
        grade.model_copy(update={
            "weekly_hours_target": sum(curriculum[grade.grade].values()),
        }) if grade.grade in curriculum else grade
        for grade in base.grades.grades
    ])
    return base.model_copy(update={
        "bundesland": "NRW",
        "school_type": SchoolType.GYMNASIUM,
        "grades": grades,
        "teachers": base.teachers.model_copy(update={
            "deputat_max_buffer": profile.deputat_max_buffer,
            "deputat_min_buffer": profile.deputat_min_buffer,
        }),
        "couplings": base.couplings.model_copy(update={
            "reli_groups": list(profile.reli_groups),
            "wpf_subjects": list(profile.wpf_subjects),
        }),
    })


def nrw_couplings(
    classes: list[SchoolClass], config: SchoolConfig
) -> list[Coupling]:
    """Kopplungen je Jahrgang mit einer Gruppe je Klasse.

    Welche Kopplungen ein Jahrgang hat und mit wie vielen Stunden,
    bestimmt seine Stundentafel (Religion, WPF, 2. Fremdsprache).
    """
    settings = config.couplings
    classes_by_grade: dict[int, list[SchoolClass]] = {}
    for school_class in classes:
        classes_by_grade.setdefault(school_class.grade, []).append(
            school_class
        )

    kinds_by_subject: dict[str, tuple[str, str, list]] = {}
    if settings.reli_ethik_enabled:
        kinds_by_subject[RELIGION_SUBJECT] = (
            "reli", COUPLING_TYPE_RELI_ETHIK,
            [(name, reli_group_subject(name))
             for name in settings.reli_groups],
        )
    if settings.wpf_enabled:
        kinds_by_subject[WPF_CURRICULUM_SUBJECT] = (
            "wpf", COUPLING_TYPE_WPF,
            [(f"{name}-WPF", name) for name in settings.wpf_subjects],
        )
    kinds_by_subject[SECOND_LANGUAGE_SUBJECT] = (
        "fs2", COUPLING_TYPE_BAND,
        [(name, name) for name in settings.second_language_subjects],
    )

    couplings: list[Coupling] = []
    for subject, (prefix, coupling_type, kinds) in kinds_by_subject.items():
        for grade, grade_classes in sorted(classes_by_grade.items()):
            hours = grade_classes[0].curriculum.get(subject, 0)
            if hours <= 0 or not kinds:
                continue
            couplings.append(parallel_coupling(
                f"{prefix}_{grade}", coupling_type,
                [school_class.id for school_class in grade_classes],
                kinds, hours,
                subject if coupling_type == COUPLING_TYPE_BAND else None,
            ))
    return couplings


def teaching_demand(
    classes: list[SchoolClass], couplings: list[Coupling]
) -> dict[str, float]:
    """Fach → Wochenstunden, die Lehrkräfte dieses Fachs geben müssen.

    Gekoppelter Unterricht zählt je Gruppe unter dem Fach der Gruppe.
    """
    covered = coupling_subjects_by_class(couplings)
    demand: dict[str, float] = {}
    for school_class in classes:
        for subject, hours in school_class.curriculum.items():
            if subject not in covered.get(school_class.id, set()):
                demand[subject] = demand.get(subject, 0) + hours
    for coupling in couplings:
        for group in coupling.groups:
            demand[group.subject] = (
                demand.get(group.subject, 0) + group.hours_per_week
            )
    return dict(sorted(demand.items()))


def parallel_group_counts(couplings: list[Coupling]) -> dict[str, int]:
    """Fach → größte Zahl gleichzeitiger Gruppen in einer Kopplung."""
    counts: dict[str, int] = {}
    for coupling in couplings:
        in_coupling: dict[str, int] = {}
        for group in coupling.groups:
            in_coupling[group.subject] = in_coupling.get(group.subject, 0) + 1
        for subject, count in in_coupling.items():
            counts[subject] = max(counts.get(subject, 0), count)
    return counts


class StaffPlanner:
    """Leitet aus dem Bedarf je Fach die Stellen der Schule ab.

    Jede Stelle bekommt zuerst das Fach mit dem größten offenen Bedarf,
    danach passende Zweit- und Drittfächer, bis ihr Sek-I-Soll gefüllt
    ist. So ist am Ende jedes Fach besetzt und die Summe der Soll-Stunden
    entspricht dem Bedarf plus Zuschlag.
    """

    def __init__(
        self,
        demand: dict[str, float],
        parallel: dict[str, int],
        profile: NrwProfile,
        part_time_range: tuple[int, int],
        rng: random.Random,
    ) -> None:
        self._profile = profile
        self._part_time_range = part_time_range
        self._rng = rng
        planned = self._with_support_on_hosts(demand)
        self._needs = {
            subject: hours * (1 + profile.capacity_margin)
            for subject, hours in planned.items()
        }
        self._caps = {
            subject: self._needs[subject] / (count + SPARE_TEACHERS)
            for subject, count in parallel.items()
            if subject in self._needs
        }

    @staticmethod
    def _with_support_on_hosts(demand: dict[str, float]) -> dict[str, float]:
        """Verteilt die Ergänzungsstunden auf die Fächer ihrer Lehrkräfte."""
        hosts = [s for s in SUPPORT_HOST_SUBJECTS if demand.get(s, 0) > 0]
        support = demand.get(SUPPORT_SUBJECT, 0)
        if not hosts or support <= 0:
            return dict(demand)
        planned = {
            subject: hours for subject, hours in demand.items()
            if subject != SUPPORT_SUBJECT
        }
        for host in hosts:
            planned[host] += support / len(hosts)
        return planned

    def plan(self) -> list[StaffPost]:
        """Alle Stellen, bis kein Fach mehr nennenswerten Bedarf hat."""
        posts: list[StaffPost] = []
        while max(self._needs.values(), default=0) >= MIN_SHARE_HOURS:
            total_hours, is_part_time, sek1_hours = self._draw_contract()
            shares = self._fill(sek1_hours)
            post = StaffPost(
                total_hours=total_hours, is_part_time=is_part_time,
                shares=shares,
            )
            too_small = sum(shares.values()) < MIN_POST_HOURS
            if not (too_small and self._absorb(shares, posts)):
                posts.append(post)
        return posts

    def _draw_contract(self) -> tuple[float, bool, float]:
        """(Deputat, Teilzeit, Sek-I-Soll) einer neuen Stelle."""
        profile = self._profile
        is_part_time = self._rng.random() < profile.part_time_share
        total_hours = profile.full_time_hours
        if is_part_time:
            low, high = self._part_time_range
            steps = (high - low) * HALF_LESSONS_PER_LESSON
            total_hours = low + (
                self._rng.randint(0, steps) / HALF_LESSONS_PER_LESSON
            )
        sek2_share = self._rng.choices(
            profile.sek2_shares, weights=profile.sek2_share_weights
        )[0]
        sek1_hours = round_half(total_hours * (1 - sek2_share))
        sek1_hours = min(total_hours, max(profile.min_sek1_hours, sek1_hours))
        return total_hours, is_part_time, sek1_hours

    def _fill(self, target: float) -> dict[str, float]:
        """Füllt eine Stelle mit bis zu MAX_SUBJECTS Fächern."""
        shares: dict[str, float] = {}
        first = max(self._needs, key=lambda s: (self._needs[s], s))
        self._take(shares, first, target * MAIN_SUBJECT_SHARE)
        while len(shares) < MAX_SUBJECTS:
            open_hours = target - sum(shares.values())
            partner = self._pick_partner(shares)
            if open_hours < MIN_SHARE_HOURS or partner is None:
                break
            self._take(shares, partner, open_hours)
        for subject in list(shares):
            self._take(shares, subject, target - sum(shares.values()))
        return shares

    def _take(
        self, shares: dict[str, float], subject: str, wanted: float
    ) -> None:
        """Bucht höchstens `wanted` Stunden des Fachs auf die Stelle."""
        cap_left = (
            self._caps.get(subject, float("inf")) - shares.get(subject, 0)
        )
        hours = min(wanted, self._needs[subject], cap_left)
        if hours <= 0:
            return
        shares[subject] = shares.get(subject, 0) + hours
        self._needs[subject] -= hours

    def _pick_partner(self, shares: dict[str, float]) -> Optional[str]:
        """Nächstes Fach: bevorzugt eine übliche Kombination, gewichtet
        nach offenem Bedarf."""
        open_subjects = [
            subject for subject, hours in self._needs.items()
            if subject not in shares and hours >= MIN_SHARE_HOURS
        ]
        usual = [
            subject for subject in open_subjects
            if any(subject in PARTNERS.get(own, ()) for own in shares)
        ]
        pool = usual or open_subjects
        if not pool:
            return None
        weights = [self._needs[subject] for subject in pool]
        return self._rng.choices(pool, weights=weights)[0]

    @staticmethod
    def _absorb(shares: dict[str, float], posts: list[StaffPost]) -> bool:
        """Verteilt eine zu kleine Stelle auf vorhandene Lehrkräfte.

        Jedes Fach geht an die Stelle mit dem meisten Sek-II-Anteil, die
        das Fach schon hat oder noch ein Fach aufnehmen kann. False,
        wenn das nicht für alle Fächer gelingt (dann bleibt die Stelle).
        """
        chosen: dict[str, StaffPost] = {}
        for subject, hours in shares.items():
            candidates = [
                post for post in posts
                if post.total_hours - post.sek1_hours >= hours
                and (subject in post.shares
                     or len(post.shares) < MAX_SUBJECTS)
            ]
            if not candidates:
                return False
            chosen[subject] = max(
                candidates,
                key=lambda post: (
                    subject in post.shares,
                    post.total_hours - post.sek1_hours,
                ),
            )
        for subject, post in chosen.items():
            post.shares[subject] = post.shares.get(subject, 0) + shares[
                subject
            ]
        return True


def make_abbreviation(last_name: str, used: set[str]) -> str:
    """Eindeutiges Kürzel aus dem Nachnamen (ohne Zufall)."""
    base = (
        last_name.upper()
        .replace("Ä", "AE").replace("Ö", "OE").replace("Ü", "UE")
        .replace("ß", "SS")
    )
    candidates = [base[:3], base[:2] + base[-1], base[0] + base[2:4]]
    candidates += [f"{base[:2]}{digit}" for digit in range(MAX_DIGIT)]
    candidates += [
        f"{base[0]}{first}{second}"
        for first in range(MAX_DIGIT) for second in range(MAX_DIGIT)
    ]
    for candidate in candidates:
        if candidate not in used:
            used.add(candidate)
            return candidate
    raise ValueError(f"Kein freies Kürzel für '{last_name}'.")


def attendance_by_slot(
    classes: list[SchoolClass],
    couplings: list[Coupling],
    time_grid: TimeGridConfig,
) -> dict[int, int]:
    """Stunde → Zahl der Klassen, die an JEDEM Tag in ihr Unterricht haben.

    Ein Klassentag beginnt ohne Lücke in der ersten Stunde (C10). Eine
    Klasse mit k Pflichtstunden je Tag (`lessons_every_day`) belegt
    daher an jedem Tag die ersten k Stunden.
    """
    slots = sek1_slot_numbers(time_grid)
    every_day = [
        lessons_every_day(weekly, time_grid.days_per_week, len(slots))
        for weekly in weekly_lessons(classes, couplings).values()
    ]
    return {
        slot: sum(1 for needed in every_day if needed > position)
        for position, slot in enumerate(slots)
    }


class AttendanceGuard:
    """Hält in jeder Stunde genug Lehrkräfte für die Klassen frei.

    Sind in einer Stunde, in der jede Klasse Unterricht haben muss,
    weniger Lehrkräfte frei als Klassen, gibt es keinen Plan. Der Solver
    kann das (Schubfachprinzip) nicht beweisen und sucht bis zum
    Zeitlimit. Der Wächter lässt eine Sperre nur zu, solange in jeder
    ihrer Stunden mindestens Klassen × (1 + Reserve) Lehrkräfte frei
    bleiben.
    """

    def __init__(
        self,
        attendance: dict[int, int],
        days: int,
        teacher_count: int,
        reserve: float,
    ) -> None:
        self._max_blocked: dict[tuple[int, int], int] = {
            (day, slot): teacher_count - math.ceil(needed * (1 + reserve))
            for day in range(days)
            for slot, needed in attendance.items()
            if needed > 0
        }
        self._blocked: Counter[tuple[int, int]] = Counter()

    def allows(self, unit: set[tuple[int, int]]) -> bool:
        """Darf eine weitere Lehrkraft in allen Stunden von `unit` fehlen?"""
        return all(
            self._blocked[slot] < self._max_blocked[slot]
            for slot in unit
            if slot in self._max_blocked
        )

    def record(self, blocked: set[tuple[int, int]]) -> None:
        """Merkt sich die Sperrzeiten einer fertigen Lehrkraft."""
        self._blocked.update(blocked)


class NrwDataGenerator:
    """Erzeugt den Datensatz des Profils "nrw-g9"."""

    def __init__(
        self,
        config: SchoolConfig,
        seed: Optional[int] = None,
        profile: Optional[NrwProfile] = None,
        curriculum: CurriculumTable = STUNDENTAFEL_NRW_G9,
    ) -> None:
        """`curriculum`: Stundentafel der Klassen (Standard: NRW G9).
        Die Lehrkräfte entstehen aus dem Bedarf dieser Tafel."""
        self.profile = profile or NrwProfile()
        self._curriculum = curriculum
        self.config = nrw_g9_config(config, self.profile, curriculum)
        self._rng = random.Random(seed)
        self._used_abbreviations: set[str] = set()
        self._sek2_bands = self._draw_sek2_bands()

    def generate(self) -> SchoolData:
        """Vollständiger Datensatz: Klassen, Kopplungen, Lehrkräfte."""
        base = FakeDataGenerator(self.config, curriculum=self._curriculum)
        classes = base.generate_classes()
        couplings = nrw_couplings(classes, self.config)
        teachers_config = self.config.teachers
        planner = StaffPlanner(
            teaching_demand(classes, couplings),
            parallel_group_counts(couplings),
            self.profile,
            (teachers_config.teilzeit_deputat_min,
             teachers_config.teilzeit_deputat_max),
            self._rng,
        )
        posts = planner.plan()
        guard = AttendanceGuard(
            attendance_by_slot(classes, couplings, self.config.time_grid),
            self.config.time_grid.days_per_week,
            len(posts),
            self.profile.attendance_reserve,
        )
        teachers = [self._teacher(post, guard) for post in posts]
        return SchoolData(
            subjects=default_subjects(),
            rooms=base.generate_rooms(),
            classes=classes,
            teachers=teachers,
            couplings=couplings,
            config=self._config_with_count(len(teachers)),
        )

    def _config_with_count(self, teacher_count: int) -> SchoolConfig:
        """Trägt die Zahl der Lehrkräfte in die Konfiguration ein."""
        if teacher_count < MIN_TEACHER_COUNT:
            return self.config
        return self.config.model_copy(update={
            "teachers": self.config.teachers.model_copy(
                update={"total_count": teacher_count}
            ),
        })

    def _teacher(self, post: StaffPost, guard: AttendanceGuard) -> Teacher:
        """Lehrkraft zu einer Stelle: Name, Fächer, Grenzen, Sperrzeiten."""
        rng = self._rng
        first_names = (
            FIRST_NAMES_F if rng.random() < FEMALE_SHARE else FIRST_NAMES_M
        )
        first_name = rng.choice(first_names)
        last_name = rng.choice(LAST_NAMES)
        settings = self.config.teachers
        lower, upper = settings.deputat_bounds(post.sek1_hours)
        wishes: list[int] = []
        if (not post.is_part_time
                and rng.random() < self.profile.day_wish_probability):
            wishes = [rng.randrange(self.config.time_grid.days_per_week)]
        return Teacher(
            id=make_abbreviation(last_name, self._used_abbreviations),
            name=f"{last_name}, {first_name}",
            subjects=self._subjects(post),
            deputat_max=upper,
            deputat_min=lower,
            deputat_soll=post.sek1_hours,
            is_teilzeit=post.is_part_time,
            unavailable_slots=self._blocked_slots(post, upper, guard),
            preferred_free_days=wishes,
            max_hours_per_day=settings.max_hours_per_day,
            max_gaps_per_day=settings.max_gaps_per_day,
        )

    @staticmethod
    def _subjects(post: StaffPost) -> list[str]:
        """Fächer nach Stundenanteil; dazu ggf. die Ergänzungsstunde."""
        subjects = sorted(post.shares, key=lambda s: (-post.shares[s], s))
        hosts_support = any(s in SUPPORT_HOST_SUBJECTS for s in subjects)
        if hosts_support and len(subjects) < MAX_SUBJECTS:
            subjects.append(SUPPORT_SUBJECT)
        return subjects

    # ─── Sperrzeiten ──────────────────────────────────────────────────────

    def _blocked_slots(
        self, post: StaffPost, upper_bound: int, guard: AttendanceGuard
    ) -> list[tuple[int, int]]:
        """Sperrzeiten: Teilzeit-Regelung und Stunden in der Sek II.

        Eine Sperre entfällt, wenn danach weniger als die Obergrenze plus
        RESERVE_HOURS unterrichtbar wäre oder wenn `guard` sie nicht
        zulässt (zu wenige freie Lehrkräfte für die Klassen).
        """
        blocked: set[tuple[int, int]] = set()
        if post.is_part_time:
            wanted = self._part_time_block()
            teachable = self._teachable(blocked | wanted)
            if (teachable >= upper_bound + RESERVE_HOURS
                    and guard.allows(wanted)):
                blocked |= wanted

        sek2_hours = post.total_hours - post.sek1_hours
        open_count = round(sek2_hours * self.profile.sek2_morning_fraction)
        units = [set(unit) for unit in self._sek2_bands]
        self._rng.shuffle(units)
        for unit in units:
            if open_count <= 0:
                break
            fits = len(unit) <= open_count and blocked.isdisjoint(unit)
            teachable = self._teachable(blocked | unit)
            if (fits and teachable >= upper_bound + RESERVE_HOURS
                    and guard.allows(unit)):
                blocked |= unit
                open_count -= len(unit)
        guard.record(blocked)
        return sorted(blocked)

    def _slot_numbers(self) -> list[int]:
        return list(range(1, self.config.time_grid.sek1_max_slot + 1))

    def _part_time_block(self) -> set[tuple[int, int]]:
        """Freier Tag, gesperrte Randstunden oder nichts."""
        rng = self._rng
        days = range(self.config.time_grid.days_per_week)
        slots = self._slot_numbers()
        roll = rng.random()
        if roll < self.profile.free_day_probability:
            free_day = rng.choice(list(days))
            return {(free_day, slot) for slot in slots}
        roll -= self.profile.free_day_probability
        if roll >= self.profile.edge_block_probability:
            return set()
        # Eine Randstunde an allen Tagen: späterer Beginn oder früheres
        # Ende. Zwei Randstunden täglich nehmen gerade die Stunden weg,
        # die Klassen mit 32 Wochenstunden fast jeden Tag brauchen.
        edge = rng.choice((slots[0], slots[-1]))
        return {(day, edge) for day in days}

    def _draw_sek2_bands(self) -> list[frozenset[tuple[int, int]]]:
        """Die Oberstufen-Schienen der Schule: `sek2_band_count`
        Doppelblöcke (Tag, Block), möglichst gleichmäßig über die Tage."""
        grid = self.config.time_grid
        slots = set(self._slot_numbers())
        blocks = [
            (block.slot_first, block.slot_second)
            for block in grid.double_blocks
            if slots.issuperset({block.slot_first, block.slot_second})
        ]
        days = list(range(grid.days_per_week))
        if not blocks:
            return []
        units = [
            frozenset((day, slot) for slot in block)
            for day in days for block in blocks
        ]
        by_day = {
            day: [u for u in units if next(iter(u))[0] == day]
            for day in days
        }
        for day_units in by_day.values():
            self._rng.shuffle(day_units)
        chosen: list[frozenset[tuple[int, int]]] = []
        while len(chosen) < min(self.profile.sek2_band_count, len(units)):
            for day in days:
                if by_day[day] and len(chosen) < self.profile.sek2_band_count:
                    chosen.append(by_day[day].pop())
        return chosen

    def _teachable(self, blocked: set[tuple[int, int]]) -> int:
        """Unterrichtbare Wochenstunden bei diesen Sperrzeiten."""
        grid = self.config.time_grid
        slots = self._slot_numbers()
        per_day = self.config.teachers.max_hours_per_day
        return sum(
            min(per_day, sum((day, slot) not in blocked for slot in slots))
            for day in range(grid.days_per_week)
        )
