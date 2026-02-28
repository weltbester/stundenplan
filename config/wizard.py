"""Interaktiver Setup-Wizard für die Ersteinrichtung des Stundenplan-Generators.

Führt den Nutzer Schritt für Schritt durch alle Konfigurationsbereiche.
Nutzt rich für schöne Konsolenausgabe.
"""

import sys
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, FloatPrompt, IntPrompt, Prompt
from rich.table import Table
from rich import box

from config.schema import (
    CouplingConfig,
    DoubleBlock,
    GradeConfig,
    GradeDefinition,
    LessonSlot,
    PauseSlot,
    RoomConfig,
    SchoolConfig,
    SchoolType,
    SolverConfig,
    SpecialRoomDef,
    TeacherConfig,
    TimeGridConfig,
)
from config.defaults import default_rooms, default_time_grid, default_grades

console = Console()


def _header(title: str) -> None:
    console.print()
    console.print(Panel(f"[bold cyan]{title}[/bold cyan]", expand=False))


def _info(text: str) -> None:
    console.print(f"[dim]{text}[/dim]")


def _success(text: str) -> None:
    console.print(f"[green]✓[/green] {text}")


def _warn(text: str) -> None:
    console.print(f"[yellow]⚠[/yellow]  {text}")


def _show_time_grid_table(tg: TimeGridConfig) -> None:
    """Zeigt das Zeitraster als rich-Tabelle an."""
    table = Table(title="Zeitraster", box=box.ROUNDED)
    table.add_column("Std.", style="bold", width=5)
    table.add_column("Beginn", width=8)
    table.add_column("Ende", width=8)
    table.add_column("Info", width=20)

    pause_afters = {p.after_slot: p for p in tg.pauses}
    double_starts = {db.slot_first for db in tg.double_blocks}

    for slot in tg.lesson_slots:
        info_parts = []
        if slot.is_sek2_only:
            info_parts.append("[dim]SII only[/dim]")
        if slot.slot_number in double_starts:
            info_parts.append("[blue]Doppelst.-Block[/blue]")
        table.add_row(
            str(slot.slot_number),
            slot.start_time,
            slot.end_time,
            " | ".join(info_parts),
        )
        if slot.slot_number in pause_afters:
            p = pause_afters[slot.slot_number]
            table.add_row(
                "",
                f"[yellow]{p.duration_minutes} min[/yellow]",
                "",
                f"[yellow]{p.label}[/yellow]",
            )
    console.print(table)


def _show_grades_table(gc: GradeConfig) -> None:
    """Zeigt die Jahrgangskonfiguration als Tabelle an."""
    table = Table(title="Jahrgänge & Klassen", box=box.ROUNDED)
    table.add_column("Jahrgang", style="bold")
    table.add_column("Klassen")
    table.add_column("Soll-Std./Woche")
    for g in gc.grades:
        table.add_row(str(g.grade), str(g.num_classes), str(g.weekly_hours_target))
    table.add_row(
        "[bold]Gesamt[/bold]",
        f"[bold]{gc.total_classes}[/bold]",
        "",
    )
    console.print(table)


def _show_rooms_table(rc: RoomConfig) -> None:
    """Zeigt die Fachraum-Konfiguration als Tabelle an."""
    table = Table(title="Fachräume", box=box.ROUNDED)
    table.add_column("Typ", style="bold")
    table.add_column("Bezeichnung")
    table.add_column("Anzahl")
    for r in rc.special_rooms:
        table.add_row(r.room_type, r.display_name, str(r.count))
    console.print(table)


# ─── SCHRITT 1: Schule ───

def _wizard_school() -> tuple[str, SchoolType, str]:
    _header("Schritt 1 — Schule")
    _info("Bitte geben Sie die Schuldaten ein.")

    name = Prompt.ask("Name der Schule", default="Muster-Gymnasium")

    console.print("Schultyp: [1] Gymnasium  [2] Realschule  [3] Gesamtschule")
    typ_input = Prompt.ask("Schultyp wählen", default="1")
    school_type_map = {"1": SchoolType.GYMNASIUM, "2": SchoolType.REALSCHULE,
                       "3": SchoolType.GESAMTSCHULE}
    school_type = school_type_map.get(typ_input, SchoolType.GYMNASIUM)

    bundesland = Prompt.ask("Bundesland (Kürzel)", default="NRW")
    return name, school_type, bundesland


# ─── SCHRITT 2: Zeitraster ───

def _wizard_time_grid() -> TimeGridConfig:
    _header("Schritt 2 — Zeitraster")
    default_tg = default_time_grid()
    _show_time_grid_table(default_tg)

    if Confirm.ask("Standard-Zeitraster übernehmen?", default=True):
        _success("Standard-Zeitraster übernommen.")
        return default_tg

    console.print("\n[bold]Eigenes Zeitraster eingeben[/bold]")
    num_slots = IntPrompt.ask("Anzahl Unterrichtsstunden pro Tag", default=7)

    lesson_slots: list[LessonSlot] = []
    for i in range(1, num_slots + 1):
        console.print(f"\n[cyan]{i}. Stunde:[/cyan]")
        start = Prompt.ask(f"  Beginn (HH:MM)", default=f"0{6+i}:00" if 6 + i < 10 else f"{6+i}:00")
        end = Prompt.ask(f"  Ende   (HH:MM)", default=f"0{6+i}:45" if 6 + i < 10 else f"{6+i}:45")
        lesson_slots.append(LessonSlot(slot_number=i, start_time=start, end_time=end))

    console.print("\n[bold]Pausen definieren[/bold]")
    pauses: list[PauseSlot] = []
    num_pauses = IntPrompt.ask("Anzahl Pausen", default=2)
    for _ in range(num_pauses):
        after = IntPrompt.ask("  Pause nach Stunde Nr.")
        dur = IntPrompt.ask("  Dauer (Minuten)", default=15)
        label = Prompt.ask("  Bezeichnung", default="Pause")
        pauses.append(PauseSlot(after_slot=after, duration_minutes=dur, label=label))

    pause_afters = {p.after_slot for p in pauses}
    console.print("\n[bold]Doppelstunden-Blöcke definieren[/bold]")
    _info("Nur aufeinanderfolgende Stunden-Paare, die NICHT über eine Pause gehen!")
    double_blocks: list[DoubleBlock] = []
    num_blocks = IntPrompt.ask("Anzahl erlaubter Doppelstunden-Blöcke", default=3)
    for _ in range(num_blocks):
        first = IntPrompt.ask("  Erste Stunde des Blocks")
        second = first + 1
        if first in pause_afters:
            _warn(f"Achtung: Nach Stunde {first} liegt eine Pause — dieser Block ist ungültig!")
            continue
        console.print(f"  → Block {first}-{second}")
        double_blocks.append(DoubleBlock(slot_first=first, slot_second=second))

    sek1_max = IntPrompt.ask("Letzte Stunde für Sek-I-Klassen", default=7)

    try:
        tg = TimeGridConfig(
            days_per_week=5,
            day_names=["Mo", "Di", "Mi", "Do", "Fr"],
            lesson_slots=lesson_slots,
            pauses=pauses,
            double_blocks=double_blocks,
            sek1_max_slot=sek1_max,
        )
        _success("Zeitraster konfiguriert und validiert.")
        return tg
    except Exception as e:
        _warn(f"Validierungsfehler: {e}")
        _warn("Standard-Zeitraster wird verwendet.")
        return default_time_grid()


# ─── SCHRITT 3: Jahrgänge ───

def _wizard_grades() -> GradeConfig:
    _header("Schritt 3 — Jahrgänge & Klassen")
    default_gc = default_grades()
    _show_grades_table(default_gc)

    if Confirm.ask("Standard-Jahrgangskonfiguration übernehmen?", default=True):
        _success("Standard-Jahrgangskonfiguration übernommen.")
        return default_gc

    grade_start = IntPrompt.ask("Erster Jahrgang", default=5)
    grade_end = IntPrompt.ask("Letzter Jahrgang", default=10)

    grades: list[GradeDefinition] = []
    default_hours_map = {5: 30, 6: 31, 7: 32, 8: 32, 9: 34, 10: 34}
    for g in range(grade_start, grade_end + 1):
        console.print(f"\n[cyan]Jahrgang {g}:[/cyan]")
        num = IntPrompt.ask(f"  Parallelklassen", default=6)
        hrs = IntPrompt.ask(f"  Soll-Wochenstunden",
                            default=default_hours_map.get(g, 32))
        grades.append(GradeDefinition(grade=g, num_classes=num,
                                      weekly_hours_target=hrs))

    gc = GradeConfig(grades=grades)
    console.print(
        f"\n[bold]Gesamt:[/bold] {gc.total_classes} Klassen in "
        f"{len(gc.grades)} Jahrgängen"
    )
    _success("Jahrgangskonfiguration abgeschlossen.")
    return gc


# ─── SCHRITT 4: Lehrkräfte ───

def _wizard_teachers() -> TeacherConfig:
    _header("Schritt 4 — Lehrkräfte")
    total = IntPrompt.ask("Anzahl Lehrkräfte gesamt", default=105)
    vollzeit = IntPrompt.ask("Vollzeit-Deputat (Wochenstunden)", default=26)
    tz_pct = FloatPrompt.ask("Anteil Teilzeit-Lehrkräfte (0.0–1.0)", default=0.30)
    tz_min = IntPrompt.ask("Teilzeit-Deputat Minimum", default=12)
    tz_max = IntPrompt.ask("Teilzeit-Deputat Maximum", default=20)
    max_day = IntPrompt.ask("Max. Unterrichtsstunden pro Tag (global)", default=6)
    max_gaps_day = IntPrompt.ask("Max. Springstunden pro Tag (global)", default=1)
    max_gaps_week = IntPrompt.ask("Max. Springstunden pro Woche (global)", default=3)
    fraction = FloatPrompt.ask(
        "Mindest-Auslastung der Lehrkräfte (0.5–1.0, z.B. 0.50 = Sicherheitsboden)",
        default=0.50,
    )
    buffer = IntPrompt.ask(
        "Mehrarbeit-Puffer über Vertrags-Deputat (Stunden, 0–6; größerer Wert = mehr Solver-Spielraum)",
        default=6,
    )

    _success("Lehrkräfte-Konfiguration abgeschlossen.")
    return TeacherConfig(
        total_count=total,
        vollzeit_deputat=vollzeit,
        teilzeit_percentage=tz_pct,
        teilzeit_deputat_min=tz_min,
        teilzeit_deputat_max=tz_max,
        max_hours_per_day=max_day,
        max_gaps_per_day=max_gaps_day,
        max_gaps_per_week=max_gaps_week,
        deputat_min_fraction=fraction,
        deputat_max_buffer=buffer,
    )


# ─── SCHRITT 5: Fachräume ───

def _wizard_rooms() -> RoomConfig:
    _header("Schritt 5 — Fachräume")
    default_rc = default_rooms()
    _show_rooms_table(default_rc)

    if Confirm.ask("Standard-Fachräume übernehmen?", default=True):
        _success("Standard-Fachräume übernommen.")
        return default_rc

    rooms: list[SpecialRoomDef] = []
    num = IntPrompt.ask("Anzahl Fachraumtypen", default=7)
    for i in range(num):
        console.print(f"\n[cyan]Fachraumtyp {i + 1}:[/cyan]")
        rt = Prompt.ask("  Kürzel (z.B. physik)")
        dn = Prompt.ask("  Anzeigename (z.B. Physik-Raum)")
        ct = IntPrompt.ask("  Anzahl verfügbarer Räume", default=2)
        rooms.append(SpecialRoomDef(room_type=rt, display_name=dn, count=ct))

    _success("Fachraum-Konfiguration abgeschlossen.")
    return RoomConfig(special_rooms=rooms)


# ─── SCHRITT 6: Kopplungen ───

def _wizard_couplings() -> CouplingConfig:
    _header("Schritt 6 — Kopplungen (Reli/Ethik & WPF)")
    _info("Kopplungen verbinden Schüler aus Parallelklassen in gemeinsamen Gruppen.")

    reli = Confirm.ask("Religion/Ethik-Kopplung aktivieren?", default=True)
    reli_cross = False
    reli_hours = 2
    if reli:
        reli_cross = Confirm.ask("  Klassenübergreifend (Parallelklassen gemischt)?",
                                  default=True)
        reli_hours = IntPrompt.ask("  Wochenstunden Reli/Ethik", default=2)

    wpf = Confirm.ask("Wahlpflichtfächer (WPF) aktivieren?", default=True)
    wpf_start = 9
    wpf_hours = 3
    wpf_cross = True
    if wpf:
        wpf_start = IntPrompt.ask("  Ab welchem Jahrgang WPF?", default=9)
        wpf_hours = IntPrompt.ask("  Wochenstunden WPF", default=3)
        wpf_cross = Confirm.ask("  Klassenübergreifend?", default=True)

    _success("Kopplungs-Konfiguration abgeschlossen.")
    return CouplingConfig(
        reli_ethik_enabled=reli,
        reli_ethik_cross_class=reli_cross,
        reli_ethik_hours=reli_hours,
        wpf_enabled=wpf,
        wpf_start_grade=wpf_start,
        wpf_hours=wpf_hours,
        wpf_cross_class=wpf_cross,
    )


# ─── SCHRITT 7: Solver ───

def _wizard_solver() -> SolverConfig:
    _header("Schritt 7 — Solver-Gewichte")
    _info(
        "Gewichte steuern, wie stark der Solver bestimmte Ziele optimiert.\n"
        "Höher = wichtiger. 0 = deaktiviert."
    )

    table = Table(box=box.SIMPLE)
    table.add_column("Ziel", style="bold")
    table.add_column("Default")
    table.add_column("Bedeutung")
    rows = [
        ("Springstunden", "100", "Springstunden für Lehrkräfte minimieren"),
        ("Arbeitslast", "50",  "Gleichmäßige Tagesverteilung"),
        ("Wunsch-freie Tage", "20", "Wunsch-freie Tage berücksichtigen"),
        ("Kompakte Pläne", "30", "Lehrkräfte-Pläne kompakt halten"),
        ("Doppelstunden", "40", "Optionale Doppelstunden bevorzugen"),
        ("Hauptfach-Verteilung", "60", "Hauptfächer über Woche verteilen"),
    ]
    for r in rows:
        table.add_row(*r)
    console.print(table)

    if Confirm.ask("Standard-Gewichte übernehmen?", default=True):
        _success("Standard-Solver-Gewichte übernommen.")
        return SolverConfig()

    time_limit = IntPrompt.ask("Zeitlimit (Sekunden)", default=300)
    workers = IntPrompt.ask("CPU-Kerne (0=automatisch)", default=0)
    w_gaps = IntPrompt.ask("Gewicht Springstunden", default=100)
    w_wb = IntPrompt.ask("Gewicht Arbeitslast", default=50)
    w_dw = IntPrompt.ask("Gewicht Wunsch-freie Tage", default=20)
    w_cmp = IntPrompt.ask("Gewicht Kompakte Pläne", default=30)
    w_dbl = IntPrompt.ask("Gewicht Doppelstunden", default=40)
    w_spr = IntPrompt.ask("Gewicht Hauptfach-Verteilung", default=60)

    _success("Solver-Konfiguration abgeschlossen.")
    return SolverConfig(
        time_limit_seconds=time_limit,
        num_workers=workers,
        weight_gaps=w_gaps,
        weight_workload_balance=w_wb,
        weight_day_wishes=w_dw,
        weight_compact=w_cmp,
        weight_double_lessons=w_dbl,
        weight_subject_spread=w_spr,
    )


# ─── ZUSAMMENFASSUNG ───

def _show_summary(config: SchoolConfig) -> None:
    _header("Zusammenfassung")
    table = Table(box=box.ROUNDED, title="Konfigurationsübersicht")
    table.add_column("Bereich", style="bold cyan")
    table.add_column("Wert")

    table.add_row("Schule", config.school_name)
    table.add_row("Typ", config.school_type.value)
    table.add_row("Bundesland", config.bundesland)
    table.add_row(
        "Zeitraster",
        f"{len([s for s in config.time_grid.lesson_slots if not s.is_sek2_only])} "
        f"Stunden/Tag, {config.time_grid.days_per_week} Tage/Woche"
    )
    table.add_row(
        "Jahrgänge",
        f"{len(config.grades.grades)} Jahrgänge, "
        f"{config.grades.total_classes} Klassen gesamt"
    )
    table.add_row("Lehrkräfte", str(config.teachers.total_count))
    table.add_row(
        "Fachräume",
        f"{len(config.rooms.special_rooms)} Typen konfiguriert"
    )
    table.add_row(
        "Kopplungen",
        f"Reli/Ethik: {'✓' if config.couplings.reli_ethik_enabled else '✗'}, "
        f"WPF: {'✓' if config.couplings.wpf_enabled else '✗'}"
    )
    table.add_row("Solver-Zeitlimit",
                  f"{config.solver.time_limit_seconds}s")
    console.print(table)


# ─── HAUPT-WIZARD ───

def run_wizard() -> Optional[SchoolConfig]:
    """Führt den vollständigen interaktiven Setup-Wizard aus.

    Returns:
        Fertige SchoolConfig oder None, wenn der Nutzer abbricht.
    """
    console.print()
    console.print(Panel(
        "[bold]Willkommen beim Stundenplan-Generator![/bold]\n\n"
        "Diese Version (v1) unterstützt die [cyan]Sekundarstufe I[/cyan] "
        "(Jahrgänge 5–10).\n"
        "Die Oberstufe (Jg. 11–13) folgt in v2.\n\n"
        "Der Wizard führt Sie durch alle Konfigurationsbereiche.\n"
        "[dim]Standard-Werte können mit Enter übernommen werden.[/dim]",
        title="[bold cyan]Stundenplan-Generator v1[/bold cyan]",
        border_style="cyan",
    ))

    if not Confirm.ask("\nMöchten Sie jetzt die Schule einrichten?", default=True):
        console.print("[yellow]Einrichtung abgebrochen.[/yellow]")
        return None

    try:
        name, school_type, bundesland = _wizard_school()
        time_grid = _wizard_time_grid()
        grades = _wizard_grades()
        teachers = _wizard_teachers()
        rooms = _wizard_rooms()
        couplings = _wizard_couplings()
        solver = _wizard_solver()

        config = SchoolConfig(
            school_name=name,
            school_type=school_type,
            bundesland=bundesland,
            time_grid=time_grid,
            grades=grades,
            teachers=teachers,
            rooms=rooms,
            couplings=couplings,
            solver=solver,
        )

        _show_summary(config)

        if not Confirm.ask("\nKonfiguration speichern?", default=True):
            console.print("[yellow]Konfiguration wird nicht gespeichert.[/yellow]")
            return None

        _success("Konfiguration wird gespeichert...")
        return config

    except KeyboardInterrupt:
        console.print("\n[yellow]Wizard abgebrochen.[/yellow]")
        return None
    except Exception as e:
        console.print(f"\n[red]Fehler während der Konfiguration: {e}[/red]")
        return None
