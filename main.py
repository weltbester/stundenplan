"""Stundenplan-Generator — Haupt-CLI.

Verwendung:
  python main.py setup                    Ersteinrichtung (Wizard)
  python main.py config edit              Konfiguration bearbeiten
  python main.py config show              Konfiguration anzeigen
  python main.py generate                 Fake-Daten erzeugen
  python main.py generate --export-json   Fake-Daten + JSON speichern
  python main.py template                 Excel-Import-Vorlage erzeugen
  python main.py import <datei.xlsx>      Excel importieren
  python main.py validate                 Machbarkeits-Check
  python main.py solve                    Stundenplan berechnen
  python main.py solve --small            Schneller Test mit 2 Klassen
  python main.py pin add <ID> <KL> <FA> <TAG> <SLOT>   Pin setzen
  python main.py pin remove <ID> <TAG> <SLOT>           Pin entfernen
  python main.py pin list                               Pins anzeigen
  python main.py export                   Excel + PDF exportieren
  python main.py run                      generate → solve → export
  python main.py scenario save <name>     Szenario speichern
  python main.py scenario load <name>     Szenario laden
  python main.py scenario list            Szenarien auflisten
"""

import sys
import logging
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()

# Standard-Pfad für gespeicherte SchoolData
DEFAULT_DATA_JSON = Path("output/school_data.json")
DEFAULT_SOLUTION_JSON = Path("output/solution.json")
DEFAULT_PINS_JSON = Path("output/pins.json")


def _load_config_or_abort():
    """Lädt die Konfiguration oder bricht mit Fehlermeldung ab."""
    from config.manager import ConfigManager
    mgr = ConfigManager()
    if mgr.first_run_check():
        console.print(
            "[red]Keine Konfiguration gefunden.[/red]\n"
            "Führen Sie zunächst [bold]python main.py setup[/bold] aus."
        )
        sys.exit(1)
    return mgr, mgr.load()


# ─── SETUP ────────────────────────────────────────────────────────────────────

@click.command("setup")
def cmd_setup():
    """Ersteinrichtung: Schulkonfiguration mit dem Setup-Wizard anlegen."""
    from config.wizard import run_wizard
    from config.manager import ConfigManager

    mgr = ConfigManager()
    if not mgr.first_run_check():
        console.print(
            "[yellow]Eine Konfiguration existiert bereits.[/yellow]\n"
            "Verwenden Sie [bold]python main.py config edit[/bold] zum Bearbeiten."
        )
        if not click.confirm("Trotzdem neu einrichten?", default=False):
            return

    config = run_wizard()
    if config is not None:
        mgr.save(config)
        console.print("[bold green]Einrichtung abgeschlossen![/bold green]")
        console.print("Führen Sie jetzt [bold]python main.py generate[/bold] aus.")


# ─── CONFIG ───────────────────────────────────────────────────────────────────

@click.group("config")
def cmd_config():
    """Konfiguration anzeigen oder bearbeiten."""


@cmd_config.command("show")
def config_show():
    """Zeigt die aktuelle Konfiguration an."""
    mgr, config = _load_config_or_abort()

    console.print(Panel(
        f"[bold]{config.school_name}[/bold]  |  "
        f"{config.school_type.value}  |  {config.bundesland}",
        title="Schulkonfiguration",
        border_style="cyan",
    ))

    tg = config.time_grid
    sek1_slots = [s for s in tg.lesson_slots if not s.is_sek2_only]
    table = Table(title="Zeitraster", box=box.ROUNDED)
    table.add_column("Std.")
    table.add_column("Beginn")
    table.add_column("Ende")
    for slot in sek1_slots:
        table.add_row(str(slot.slot_number), slot.start_time, slot.end_time)
    console.print(table)

    table2 = Table(title="Jahrgänge", box=box.ROUNDED)
    table2.add_column("Jahrgang")
    table2.add_column("Klassen")
    table2.add_column("Soll-Stunden")
    for g in config.grades.grades:
        table2.add_row(str(g.grade), str(g.num_classes), str(g.weekly_hours_target))
    table2.add_row("[bold]Gesamt[/bold]", f"[bold]{config.grades.total_classes}[/bold]", "")
    console.print(table2)

    tc = config.teachers
    console.print(
        f"\n[bold]Lehrkräfte:[/bold] {tc.total_count} gesamt | "
        f"Vollzeit: {tc.vollzeit_deputat}h | "
        f"Teilzeit-Anteil: {tc.teilzeit_percentage:.0%}"
    )

    sc = config.solver
    console.print(
        f"[bold]Solver:[/bold] Zeitlimit {sc.time_limit_seconds}s | "
        f"Gewicht Springstunden: {sc.weight_gaps}"
    )


@cmd_config.command("edit")
def config_edit():
    """Bearbeitet die Konfiguration interaktiv."""
    mgr, config = _load_config_or_abort()
    mgr.edit_interactive(config)


# ─── GENERATE ─────────────────────────────────────────────────────────────────

@click.command("generate")
@click.option("--seed", default=42, help="Zufalls-Seed für reproduzierbare Daten.")
@click.option("--export-json", is_flag=True, default=False,
              help="Datensatz als JSON speichern.")
@click.option("--json-path", default=str(DEFAULT_DATA_JSON),
              help="Pfad für JSON-Export.")
@click.option("--validate", "run_validate", is_flag=True, default=True,
              help="Machbarkeits-Check nach Generierung.")
def cmd_generate(seed: int, export_json: bool, json_path: str, run_validate: bool):
    """Erzeugt Testdaten (Lehrkräfte, Klassen, Räume, Kopplungen)."""
    mgr, config = _load_config_or_abort()
    from data.fake_data import FakeDataGenerator

    console.print("[bold]Testdaten werden generiert...[/bold]")
    gen = FakeDataGenerator(config, seed=seed)
    data = gen.generate()
    gen.print_summary(data)

    console.print(f"\n[dim]{data.summary()}[/dim]")

    if run_validate:
        report = data.validate_feasibility()
        report.print_rich()

    if export_json:
        out_path = Path(json_path)
        data.save_json(out_path)
        console.print(f"[green]✓[/green] JSON gespeichert: {out_path}")

    # Einfache Textausgabe (rückwärtskompatibel)
    txt_path = Path("output/fake_data_summary.txt")
    txt_path.parent.mkdir(parents=True, exist_ok=True)
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(data.summary() + "\n\n")
        f.write("=== Lehrkräfte ===\n")
        for t in data.teachers:
            f.write(f"  {t.id:4s} {t.name:35s} {t.deputat}h  {t.subjects}\n")
        f.write("\n=== Klassen ===\n")
        for c in data.classes:
            f.write(f"  {c.id:4s}  {sum(c.curriculum.values())}h/Woche\n")

    console.print(f"[green]✓[/green] Zusammenfassung gespeichert: {txt_path}")


# ─── TEMPLATE ─────────────────────────────────────────────────────────────────

@click.command("template")
@click.option("--output", "-o", default="output/import_vorlage.xlsx",
              help="Ausgabepfad für die Excel-Vorlage.")
def cmd_template(output: str):
    """Erzeugt eine leere Excel-Import-Vorlage."""
    mgr, config = _load_config_or_abort()
    from data.excel_import import generate_template

    out_path = Path(output)
    console.print(f"[bold]Excel-Vorlage wird erzeugt...[/bold]")
    generate_template(config, out_path)
    console.print(f"[green]✓[/green] Vorlage gespeichert: {out_path}")
    console.print(
        "\nBlätter in der Vorlage:\n"
        "  [cyan]Zeitraster[/cyan]    – Stundenraster (vorausgefüllt aus Config)\n"
        "  [cyan]Jahrgänge[/cyan]     – Jahrgangsdefinition (vorausgefüllt)\n"
        "  [cyan]Stundentafel[/cyan]  – Fach × Jahrgang Matrix (vorausgefüllt)\n"
        "  [cyan]Lehrkräfte[/cyan]    – Eingabe: Name, Kürzel, Fächer, Deputat, ...\n"
        "  [cyan]Fachräume[/cyan]     – Fachraum-Typen und Anzahl\n"
        "  [cyan]Kopplungen[/cyan]    – Reli/Ethik + WPF Kopplungen"
    )


# ─── IMPORT ───────────────────────────────────────────────────────────────────

@click.command("import")
@click.argument("datei", type=click.Path(exists=True, path_type=Path))
@click.option("--save-json", is_flag=True, default=False,
              help="Importierte Daten als JSON speichern.")
@click.option("--json-path", default=str(DEFAULT_DATA_JSON),
              help="Pfad für JSON-Export.")
def cmd_import(datei: Path, save_json: bool, json_path: str):
    """Importiert Schuldaten aus einer Excel-Datei."""
    mgr, config = _load_config_or_abort()
    from data.excel_import import import_from_excel, ExcelImportError

    console.print(f"[bold]Importiere:[/bold] {datei}")
    try:
        school_data, report = import_from_excel(datei, config)
    except ExcelImportError as e:
        console.print(f"[red bold]Import fehlgeschlagen:[/red bold]\n{e}")
        sys.exit(1)

    console.print(f"[green]✓[/green] Import erfolgreich!")
    console.print(f"\n{school_data.summary()}")
    report.print_rich()

    if save_json:
        out_path = Path(json_path)
        school_data.save_json(out_path)
        console.print(f"[green]✓[/green] Daten gespeichert: {out_path}")


# ─── VALIDATE ─────────────────────────────────────────────────────────────────

@click.command("validate")
@click.option("--json-path", default=str(DEFAULT_DATA_JSON),
              help="Pfad zur gespeicherten JSON-Datei.")
@click.option("--generate", "gen_first", is_flag=True, default=False,
              help="Testdaten zunächst generieren (Seed 42).")
def cmd_validate(json_path: str, gen_first: bool):
    """Führt einen Machbarkeits-Check auf dem aktuellen Datensatz durch."""
    from models.school_data import SchoolData

    if gen_first:
        mgr, config = _load_config_or_abort()
        from data.fake_data import FakeDataGenerator
        gen = FakeDataGenerator(config, seed=42)
        data = gen.generate()
    else:
        p = Path(json_path)
        if not p.exists():
            console.print(
                f"[red]Keine Datendatei gefunden: {p}[/red]\n"
                "Verwenden Sie [bold]python main.py generate --export-json[/bold] "
                "oder [bold]--generate[/bold] Flag."
            )
            sys.exit(1)
        console.print(f"[bold]Lade Datensatz:[/bold] {p}")
        data = SchoolData.load_json(p)

    console.print(f"\n{data.summary()}\n")
    report = data.validate_feasibility()
    report.print_rich()

    sys.exit(0 if report.is_feasible else 1)


# ─── SOLVE ────────────────────────────────────────────────────────────────────

def _build_mini_school_data():
    """Erzeugt minimalen Datensatz (2 Klassen 5a+7a, 10 Lehrer) für schnelle Tests."""
    from config.schema import (
        SchoolConfig, GradeConfig, GradeDefinition, SchoolType,
        TeacherConfig, SolverConfig,
    )
    from config.defaults import (
        default_time_grid, default_rooms,
        SUBJECT_METADATA, STUNDENTAFEL_GYMNASIUM_SEK1,
    )
    from models.school_data import SchoolData
    from models.subject import Subject
    from models.room import Room
    from models.teacher import Teacher
    from models.school_class import SchoolClass
    from models.coupling import Coupling, CouplingGroup

    config = SchoolConfig(
        school_name="Mini-Test",
        school_type=SchoolType.GYMNASIUM,
        bundesland="NRW",
        time_grid=default_time_grid(),
        grades=GradeConfig(grades=[
            GradeDefinition(grade=5, num_classes=1, weekly_hours_target=30),
            GradeDefinition(grade=7, num_classes=1, weekly_hours_target=32),
        ]),
        rooms=default_rooms(),
        teachers=TeacherConfig(
            total_count=10,
            vollzeit_deputat=26,
            teilzeit_percentage=0.0,
            deputat_tolerance=3,
        ),
        solver=SolverConfig(time_limit_seconds=60, num_workers=4),
    )
    sek1_max = config.time_grid.sek1_max_slot

    subjects = [
        Subject(name=n, short_name=m["short"], category=m["category"],
                is_hauptfach=m["is_hauptfach"], requires_special_room=m["room"],
                double_lesson_required=m["double_required"],
                double_lesson_preferred=m["double_preferred"])
        for n, m in SUBJECT_METADATA.items()
    ]
    rooms = []
    for rd in config.rooms.special_rooms:
        pfx = rd.room_type[:2].upper()
        for i in range(1, rd.count + 1):
            rooms.append(Room(id=f"{pfx}{i}", room_type=rd.room_type,
                              name=f"{rd.display_name} {i}"))
    classes = [
        SchoolClass(id="5a", grade=5, label="a",
                    curriculum={s: h for s, h in STUNDENTAFEL_GYMNASIUM_SEK1[5].items() if h > 0},
                    max_slot=sek1_max),
        SchoolClass(id="7a", grade=7, label="a",
                    curriculum={s: h for s, h in STUNDENTAFEL_GYMNASIUM_SEK1[7].items() if h > 0},
                    max_slot=sek1_max),
    ]
    dep = 7  # 10 × 7h = 70h ≥ Gesamtbedarf (62h inkl. Kopplung)
    teachers = [
        Teacher(id="T01", name="Müller, Anna",   subjects=["Deutsch", "Geschichte"],  deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T02", name="Schmidt, Hans",  subjects=["Mathematik", "Physik"],   deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T03", name="Weber, Eva",     subjects=["Englisch", "Politik"],    deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T04", name="Becker, Klaus",  subjects=["Biologie", "Erdkunde"],   deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T05", name="Koch, Lisa",     subjects=["Kunst", "Musik"],         deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T06", name="Wagner, Tom",    subjects=["Sport", "Chemie"],        deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T07", name="Braun, Sara",    subjects=["Latein", "Deutsch"],      deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T08", name="Wolf, Peter",    subjects=["Religion", "Ethik"],      deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T09", name="Neumann, Maria", subjects=["Religion", "Ethik"],      deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T10", name="Schulz, Ralf",   subjects=["Mathematik", "Deutsch"],  deputat=dep, max_hours_per_day=6, max_gaps_per_day=2),
    ]
    couplings = [
        Coupling(id="reli_5", coupling_type="reli_ethik", involved_class_ids=["5a"],
                 groups=[CouplingGroup(group_name="evangelisch", subject="Religion", hours_per_week=2),
                         CouplingGroup(group_name="ethik", subject="Ethik", hours_per_week=2)],
                 hours_per_week=2, cross_class=True),
        Coupling(id="reli_7", coupling_type="reli_ethik", involved_class_ids=["7a"],
                 groups=[CouplingGroup(group_name="evangelisch", subject="Religion", hours_per_week=2),
                         CouplingGroup(group_name="ethik", subject="Ethik", hours_per_week=2)],
                 hours_per_week=2, cross_class=True),
    ]
    return SchoolData(subjects=subjects, rooms=rooms, classes=classes,
                      teachers=teachers, couplings=couplings, config=config)


def _parse_weights(s: str) -> dict:
    """Parst Gewichte aus einem String wie 'gaps=200,compact=50'."""
    result = {}
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise click.BadParameter(
                f"Ungültiges Format: '{part}'. Erwartet: 'schlüssel=wert'"
            )
        k, v = part.split("=", 1)
        try:
            result[k.strip()] = int(v.strip())
        except ValueError:
            raise click.BadParameter(
                f"Ungültiger Wert für '{k.strip()}': '{v.strip()}' – muss eine ganze Zahl sein."
            )
    return result


@click.command("solve")
@click.option("--time-limit", default=None, type=int,
              help="Zeitlimit in Sekunden (überschreibt Config).")
@click.option("--small", is_flag=True, default=False,
              help="Mini-Datensatz (2 Klassen, 8 Lehrer) für schnelle Tests.")
@click.option("--json-path", default=str(DEFAULT_DATA_JSON),
              help="Pfad zur SchoolData-JSON (wenn nicht --small).")
@click.option("--output", "-o", default=str(DEFAULT_SOLUTION_JSON),
              help="Ausgabepfad für die Lösung (JSON).")
@click.option("--pins-path", default=str(DEFAULT_PINS_JSON),
              help="Pfad zur Pins-JSON-Datei (optional).")
@click.option("--diagnose", is_flag=True, default=False,
              help="Erweiterte Diagnose bei INFEASIBLE: ConstraintRelaxer starten.")
@click.option("--verbose", "-v", is_flag=True, default=False,
              help="Solver-Log aktivieren.")
@click.option("--no-soft", is_flag=True, default=False,
              help="Nur harte Constraints (keine Soft-Optimierung).")
@click.option("--weights", default=None,
              help="Gewichte überschreiben, z.B. 'gaps=200,double_lessons=50'.")
def cmd_solve(time_limit, small, json_path, output, pins_path, diagnose, verbose,
              no_soft, weights):
    """Berechnet den Stundenplan mit CP-SAT Solver."""
    from models.school_data import SchoolData
    from solver.scheduler import ScheduleSolver
    from solver.pinning import PinManager

    if verbose:
        logging.basicConfig(level=logging.INFO,
                            format="%(levelname)s %(message)s")

    # ── Daten laden ──────────────────────────────────────────────────────────
    if small:
        console.print("[bold]Mini-Modus:[/bold] Erzeuge 2-Klassen-Testdaten...")
        data = _build_mini_school_data()
    else:
        p = Path(json_path)
        if not p.exists():
            console.print(
                f"[red]Keine Datendatei gefunden: {p}[/red]\n"
                "Verwenden Sie [bold]python main.py generate --export-json[/bold] "
                "oder das [bold]--small[/bold] Flag."
            )
            sys.exit(1)
        console.print(f"[bold]Lade Datensatz:[/bold] {p}")
        data = SchoolData.load_json(p)

    console.print(f"[dim]{data.summary()}[/dim]\n")

    # ── Machbarkeits-Check ───────────────────────────────────────────────────
    report = data.validate_feasibility()
    if not report.is_feasible:
        report.print_rich()
        console.print("[red bold]Machbarkeits-Check fehlgeschlagen – Solver wird nicht gestartet.[/red bold]")
        sys.exit(1)
    if report.warnings:
        report.print_rich()

    # ── Zeitlimit anpassen ───────────────────────────────────────────────────
    if time_limit is not None:
        data.config.solver.time_limit_seconds = time_limit

    # ── Pins laden ───────────────────────────────────────────────────────────
    pin_manager = PinManager()
    pins_file = Path(pins_path)
    if pins_file.exists():
        pin_manager.load_json(pins_file)
        if len(pin_manager) > 0:
            console.print(f"[cyan]{len(pin_manager)} Pins geladen aus {pins_file}[/cyan]")

    # ── Gewichte parsen ──────────────────────────────────────────────────────
    parsed_weights = None
    if weights:
        try:
            parsed_weights = _parse_weights(weights)
        except click.BadParameter as e:
            console.print(f"[red bold]Ungültige Gewichte:[/red bold] {e}")
            sys.exit(1)

    # ── Solver starten ───────────────────────────────────────────────────────
    use_soft = not no_soft
    soft_label = "mit Soft-Constraints" if use_soft else "nur harte Constraints"
    console.print(
        f"[bold]Starte Solver...[/bold] "
        f"({soft_label}, "
        f"Zeitlimit: {data.config.solver.time_limit_seconds}s, "
        f"Worker: {data.config.solver.num_workers or 'auto'})"
    )

    solver = ScheduleSolver(data)
    with console.status("[bold green]Solver läuft...[/bold green]"):
        solution = solver.solve(
            pins=pin_manager.get_pins(),
            use_soft=use_soft,
            weights=parsed_weights,
        )

    # ── Ergebnis anzeigen ────────────────────────────────────────────────────
    status_color = {
        "OPTIMAL": "green",
        "FEASIBLE": "yellow",
        "INFEASIBLE": "red",
        "UNKNOWN": "red",
        "MODEL_INVALID": "red",
    }.get(solution.solver_status, "white")

    console.print(Panel(
        f"Status: [{status_color}]{solution.solver_status}[/{status_color}]\n"
        f"Zeit: {solution.solve_time_seconds:.1f}s\n"
        f"Einträge: {len(solution.entries)}\n"
        f"Zuweisungen: {len(solution.assignments)}\n"
        f"Variablen: {solution.num_variables} | Constraints: {solution.num_constraints}",
        title="Solver-Ergebnis",
        border_style=status_color,
    ))

    if solution.solver_status not in ("OPTIMAL", "FEASIBLE"):
        if diagnose:
            from solver.constraint_relaxer import ConstraintRelaxer
            console.print("\n[bold yellow]Starte ConstraintRelaxer-Diagnose...[/bold yellow]")
            relaxer = ConstraintRelaxer(data)
            with console.status("[yellow]Relaxierungen werden getestet...[/yellow]"):
                report = relaxer.diagnose(
                    pins=pin_manager.get_pins(),
                    time_limit=min(30, data.config.solver.time_limit_seconds),
                )
            rtable = Table(title="Constraint-Relaxierungen", box=box.ROUNDED)
            rtable.add_column("Relaxierung")
            rtable.add_column("Beschreibung")
            rtable.add_column("Status")
            rtable.add_column("Zeit", justify="right")
            for r in report.relaxations:
                color = "green" if r.status in ("OPTIMAL", "FEASIBLE") else (
                    "yellow" if r.status == "UNKNOWN" else "red"
                )
                rtable.add_row(
                    r.name, r.description,
                    f"[{color}]{r.status}[/{color}]",
                    f"{r.solve_time:.1f}s",
                )
            console.print(rtable)
            console.print(f"\n[bold]Empfehlung:[/bold] {report.recommendation}")
        sys.exit(1)

    # ── Lösung speichern ─────────────────────────────────────────────────────
    out_path = Path(output)
    solution.save_json(out_path)
    console.print(f"[green]✓[/green] Lösung gespeichert: {out_path}")

    # ── Zusammenfassung: Lehrer-Auslastung ───────────────────────────────────
    table = Table(title="Lehrer-Auslastung (Top 10)", box=box.ROUNDED)
    table.add_column("Kürzel")
    table.add_column("Soll", justify="right")
    table.add_column("Ist", justify="right")
    table.add_column("Δ", justify="right")

    teacher_hours: dict[str, int] = {}
    for entry in solution.entries:
        # Reguläre Stunden: 1 Entry = 1 Stunde
        if not entry.is_coupling:
            teacher_hours[entry.teacher_id] = teacher_hours.get(entry.teacher_id, 0) + 1
    # Kopplungs-Stunden: Pro Kopplung die hours_per_week des Lehrers addieren
    # (Kopplungs-Einträge werden einmal pro Klasse erstellt, nicht pro Stunde)
    coupling_hours_per_teacher: dict[str, int] = {}
    coupling_entries_seen: set[tuple] = set()
    for entry in solution.entries:
        if entry.is_coupling and entry.coupling_id:
            key = (entry.teacher_id, entry.coupling_id, entry.day, entry.slot_number)
            if key not in coupling_entries_seen:
                coupling_entries_seen.add(key)
                coupling_hours_per_teacher[entry.teacher_id] = (
                    coupling_hours_per_teacher.get(entry.teacher_id, 0) + 1
                )
    for t_id, h in coupling_hours_per_teacher.items():
        teacher_hours[t_id] = teacher_hours.get(t_id, 0) + h

    teacher_map = {t.id: t for t in data.teachers}
    rows = []
    for t_id, actual in teacher_hours.items():
        teacher = teacher_map.get(t_id)
        if teacher:
            delta = actual - teacher.deputat
            rows.append((t_id, teacher.deputat, actual, delta))

    rows.sort(key=lambda r: abs(r[3]), reverse=True)
    for t_id, soll, ist, delta in rows[:10]:
        color = "green" if abs(delta) <= 1 else "yellow" if abs(delta) <= 2 else "red"
        table.add_row(t_id, str(soll), str(ist), f"[{color}]{delta:+d}[/{color}]")

    if rows:
        console.print(table)


# ─── PIN ──────────────────────────────────────────────────────────────────────

@click.group("pin")
def cmd_pin():
    """Gepinnte Stunden verwalten (fixierte Unterrichtsstunden)."""


@cmd_pin.command("add")
@click.argument("lehrer_id")
@click.argument("klasse")
@click.argument("fach")
@click.argument("tag", type=int)
@click.argument("slot", type=int)
@click.option("--pins-path", default=str(DEFAULT_PINS_JSON),
              help="Pfad zur Pins-JSON-Datei.")
def pin_add(lehrer_id: str, klasse: str, fach: str, tag: int, slot: int, pins_path: str):
    """Setzt einen Pin: Lehrer-ID Klasse Fach Tag(0-4) Slot(1-7).

    Beispiel: python main.py pin add MUE 5a Mathematik 0 1
    """
    from solver.pinning import PinManager, PinnedLesson

    pm = PinManager()
    p = Path(pins_path)
    if p.exists():
        pm.load_json(p)

    pin = PinnedLesson(
        teacher_id=lehrer_id,
        class_id=klasse,
        subject=fach,
        day=tag,
        slot_number=slot,
    )
    pm.add_pin(pin)
    pm.save_json(p)

    day_names = ["Mo", "Di", "Mi", "Do", "Fr"]
    day_str = day_names[tag] if 0 <= tag <= 4 else str(tag)
    console.print(
        f"[green]✓[/green] Pin gesetzt: "
        f"[bold]{lehrer_id.upper()}[/bold] unterrichtet "
        f"[bold]{klasse}[/bold] ({fach}) am [bold]{day_str} Std.{slot}[/bold]"
    )


@cmd_pin.command("remove")
@click.argument("lehrer_id")
@click.argument("tag", type=int)
@click.argument("slot", type=int)
@click.option("--pins-path", default=str(DEFAULT_PINS_JSON),
              help="Pfad zur Pins-JSON-Datei.")
def pin_remove(lehrer_id: str, tag: int, slot: int, pins_path: str):
    """Entfernt einen Pin: Lehrer-ID Tag(0-4) Slot(1-7)."""
    from solver.pinning import PinManager

    pm = PinManager()
    p = Path(pins_path)
    if not p.exists():
        console.print("[yellow]Keine Pins-Datei gefunden.[/yellow]")
        return

    pm.load_json(p)
    removed = pm.remove_pin(lehrer_id, tag, slot)
    if removed:
        pm.save_json(p)
        console.print(f"[green]✓[/green] Pin entfernt: {lehrer_id.upper()} Tag={tag} Slot={slot}")
    else:
        console.print(f"[yellow]Kein passender Pin gefunden für {lehrer_id.upper()} Tag={tag} Slot={slot}[/yellow]")


@cmd_pin.command("list")
@click.option("--pins-path", default=str(DEFAULT_PINS_JSON),
              help="Pfad zur Pins-JSON-Datei.")
def pin_list(pins_path: str):
    """Zeigt alle gesetzten Pins an."""
    from solver.pinning import PinManager

    pm = PinManager()
    p = Path(pins_path)
    if not p.exists():
        console.print("[dim]Keine Pins vorhanden.[/dim]")
        return

    pm.load_json(p)
    pins = pm.get_pins()

    if not pins:
        console.print("[dim]Keine Pins vorhanden.[/dim]")
        return

    day_names = ["Mo", "Di", "Mi", "Do", "Fr"]
    table = Table(title=f"Gepinnte Stunden ({len(pins)})", box=box.ROUNDED)
    table.add_column("Lehrer")
    table.add_column("Klasse")
    table.add_column("Fach")
    table.add_column("Tag")
    table.add_column("Slot", justify="right")

    for pin in pins:
        day_str = day_names[pin.day] if 0 <= pin.day <= 4 else str(pin.day)
        table.add_row(pin.teacher_id, pin.class_id, pin.subject, day_str, str(pin.slot_number))

    console.print(table)


# ─── EXPORT ───────────────────────────────────────────────────────────────────

DEFAULT_EXPORT_DIR = Path("output/export")


@click.command("export")
@click.option(
    "--format", "fmt", default="both",
    type=click.Choice(["excel", "pdf", "both"]),
    help="Ausgabeformat: excel, pdf oder both.",
)
@click.option("--solution-path", default=str(DEFAULT_SOLUTION_JSON),
              help="Pfad zur solution.json.")
@click.option("--data-path", default=str(DEFAULT_DATA_JSON),
              help="Pfad zur school_data.json.")
@click.option("--output-dir", default=str(DEFAULT_EXPORT_DIR),
              help="Ausgabeverzeichnis für Export-Dateien.")
def cmd_export(fmt: str, solution_path: str, data_path: str, output_dir: str):
    """Exportiert den Stundenplan als Excel und/oder PDF."""
    from models.school_data import SchoolData
    from solver.scheduler import ScheduleSolution
    from export import ExcelExporter, PdfExporter

    sol_path = Path(solution_path)
    dat_path = Path(data_path)
    out_dir  = Path(output_dir)

    # Dateien prüfen
    for p, label in [(sol_path, "Lösung"), (dat_path, "Schuldaten")]:
        if not p.exists():
            console.print(f"[red]{label} nicht gefunden: {p}[/red]")
            console.print(
                "Tipp: [bold]python main.py solve --small[/bold] erzeugt eine Beispiel-Lösung."
            )
            sys.exit(1)

    console.print(f"[bold]Lade Daten...[/bold]")
    solution    = ScheduleSolution.load_json(sol_path)
    school_data = SchoolData.load_json(dat_path)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Excel ────────────────────────────────────────────────────────────────
    if fmt in ("excel", "both"):
        xlsx_path = out_dir / "stundenplan.xlsx"
        console.print("[bold]Excel-Export...[/bold]")
        with console.status("[green]Excel wird erstellt...[/green]"):
            ExcelExporter(solution, school_data).export(xlsx_path)
        console.print(f"[green]✓[/green] Excel gespeichert: {xlsx_path}")

    # ── PDF ──────────────────────────────────────────────────────────────────
    if fmt in ("pdf", "both"):
        console.print("[bold]PDF-Export...[/bold]")

        pdf_classes  = out_dir / "klassen_stundenplaene.pdf"
        pdf_teachers = out_dir / "lehrer_stundenplaene.pdf"

        with console.status("[green]PDFs werden erstellt...[/green]"):
            exporter = PdfExporter(solution, school_data)
            exporter.export_class_schedules(pdf_classes)
            exporter.export_teacher_schedules(pdf_teachers)

        console.print(f"[green]✓[/green] Klassen-PDF: {pdf_classes}")
        console.print(f"[green]✓[/green] Lehrer-PDF:  {pdf_teachers}")

    console.print(f"\n[bold green]Export abgeschlossen.[/bold green] → {out_dir}/")


# ─── RUN ──────────────────────────────────────────────────────────────────────

@click.command("run")
@click.option("--seed", default=42, help="Zufalls-Seed.")
@click.option("--no-soft", is_flag=True, default=False,
              help="Nur harte Constraints (schneller).")
@click.option(
    "--format", "fmt", default="both",
    type=click.Choice(["excel", "pdf", "both"]),
    help="Ausgabeformat für den Export.",
)
@click.option("--output-dir", default=str(DEFAULT_EXPORT_DIR),
              help="Ausgabeverzeichnis für Export-Dateien.")
def cmd_run(seed: int, no_soft: bool, fmt: str, output_dir: str):
    """Führt die komplette Pipeline aus: generate → solve → export."""
    import subprocess

    console.print(Panel(
        "[bold]Pipeline: generate → solve → export[/bold]",
        border_style="cyan",
    ))

    # 1. generate --export-json
    console.print("\n[bold cyan]Schritt 1:[/bold cyan] Testdaten generieren...")
    result = subprocess.run(
        [sys.executable, "main.py", "generate", "--export-json", f"--seed={seed}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        console.print(f"[red]generate fehlgeschlagen:[/red]\n{result.stderr}")
        sys.exit(1)
    console.print("[green]✓[/green] Testdaten erstellt.")

    # 2. solve
    console.print("\n[bold cyan]Schritt 2:[/bold cyan] Solver starten...")
    solve_args = [sys.executable, "main.py", "solve"]
    if no_soft:
        solve_args.append("--no-soft")
    result = subprocess.run(solve_args, capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"[red]solve fehlgeschlagen:[/red]\n{result.stderr or result.stdout}")
        sys.exit(1)
    console.print("[green]✓[/green] Lösung berechnet.")

    # 3. export
    console.print("\n[bold cyan]Schritt 3:[/bold cyan] Export...")
    result = subprocess.run(
        [sys.executable, "main.py", "export", f"--format={fmt}",
         f"--output-dir={output_dir}"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        console.print(f"[red]export fehlgeschlagen:[/red]\n{result.stderr}")
        sys.exit(1)
    console.print("[green]✓[/green] Export abgeschlossen.")
    console.print(f"\n[bold green]Pipeline erfolgreich![/bold green] → {output_dir}/")


# ─── SCENARIO ─────────────────────────────────────────────────────────────────

@click.group("scenario")
def cmd_scenario():
    """Szenarien verwalten (speichern, laden, auflisten)."""


@cmd_scenario.command("save")
@click.argument("name")
@click.option("--description", "-d", default="", help="Beschreibung des Szenarios.")
def scenario_save(name: str, description: str):
    """Speichert die aktuelle Konfiguration als Szenario."""
    mgr, config = _load_config_or_abort()
    mgr.save_scenario(config, name, description)


@cmd_scenario.command("load")
@click.argument("name")
def scenario_load(name: str):
    """Lädt ein gespeichertes Szenario als aktive Konfiguration."""
    from config.manager import ConfigManager
    mgr = ConfigManager()
    config = mgr.load_scenario(name)
    mgr.save(config)
    console.print(f"[green]✓[/green] Szenario '{name}' als aktive Config gesetzt.")


@cmd_scenario.command("list")
def scenario_list():
    """Listet alle gespeicherten Szenarien auf."""
    from config.manager import ConfigManager
    mgr = ConfigManager()
    scenarios = mgr.list_scenarios()

    if not scenarios:
        console.print("[dim]Keine Szenarien vorhanden.[/dim]")
        return

    table = Table(title="Gespeicherte Szenarien", box=box.ROUNDED)
    table.add_column("Name", style="bold")
    table.add_column("Erstellt")
    table.add_column("Beschreibung")
    for s in scenarios:
        table.add_row(s["name"], s.get("created", ""), s.get("description", ""))
    console.print(table)


# ─── HAUPT-CLI ────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """Stundenplan-Generator für Gymnasien (Sek I).

    Starten Sie mit: python main.py setup
    """


def main():
    """Einstiegspunkt. Startet automatisch den Wizard beim ersten Aufruf."""
    from config.manager import ConfigManager
    mgr = ConfigManager()

    if len(sys.argv) == 1 and mgr.first_run_check():
        console.print(Panel(
            "[bold]Willkommen beim Stundenplan-Generator![/bold]\n\n"
            "Keine Konfiguration gefunden.\n"
            "Der Setup-Wizard wird jetzt gestartet...",
            border_style="cyan",
        ))
        sys.argv.append("setup")

    cli()


# Befehle registrieren
cli.add_command(cmd_setup)
cli.add_command(cmd_config)
cli.add_command(cmd_generate)
cli.add_command(cmd_template)
cli.add_command(cmd_import)
cli.add_command(cmd_validate)
cli.add_command(cmd_solve)
cli.add_command(cmd_pin)
cli.add_command(cmd_export)
cli.add_command(cmd_run)
cli.add_command(cmd_scenario)


if __name__ == "__main__":
    main()
