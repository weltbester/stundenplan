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
  python main.py show 5a                  Stundenplan Klasse 5a im Terminal
  python main.py show MÜL                 Stundenplan Lehrer MÜL im Terminal
  python main.py quality                  Qualitätsbericht anzeigen
  python main.py substitute --teacher T01 Vertretungsoptionen
"""

__version__ = "1.1"

import sys
import logging
from pathlib import Path

try:
    import rich_click as click

    rc = click.rich_click

    # ── Grundeinstellungen ────────────────────────────────────────────────────
    rc.USE_RICH_MARKUP       = True
    rc.USE_MARKDOWN          = False
    rc.SHOW_ARGUMENTS        = True
    rc.SHOW_METAVARS_COLUMN  = True
    rc.MAX_WIDTH             = 100
    rc.COLOR_SYSTEM          = "truecolor"

    # ── Header / Footer ───────────────────────────────────────────────────────
    rc.HEADER_TEXT = (
        "\n[bold cyan]╔═════════════════════════════════════════════════╗[/bold cyan]\n"
        "[bold cyan]║[/bold cyan]  [bold white]Stundenplan-Generator[/bold white]"
        f"  [dim]Gymnasium Sek I — v{__version__}[/dim]  "
        "[bold cyan]║[/bold cyan]\n"
        "[bold cyan]╚═════════════════════════════════════════════════╝[/bold cyan]\n"
    )
    rc.FOOTER_TEXT = (
        "\n[dim]Erster Start? Führen Sie [bold]python main.py setup[/bold] aus.[/dim]\n"
        "[dim]Logs:          [italic]output/stundenplan.log[/italic][/dim]\n"
    )

    # ── Befehle in logische Gruppen aufteilen ─────────────────────────────────
    rc.COMMAND_GROUPS = {
        "main.py": [
            {
                "name": "Einrichtung",
                "commands": ["setup", "config"],
            },
            {
                "name": "Datenverwaltung",
                "commands": ["generate", "template", "import", "validate"],
            },
            {
                "name": "Solver",
                "commands": ["solve", "pin"],
            },
            {
                "name": "Export & Anzeige",
                "commands": ["export", "show", "run"],
            },
            {
                "name": "Analyse",
                "commands": ["quality", "substitute"],
            },
            {
                "name": "Szenarien",
                "commands": ["scenario"],
            },
        ]
    }

    # ── Optionen für 'solve' in Gruppen aufteilen ─────────────────────────────
    rc.OPTION_GROUPS = {
        "main.py solve": [
            {
                "name": "Datenpfade",
                "options": ["--json-path", "--output", "--pins-path"],
            },
            {
                "name": "Solver-Verhalten",
                "options": [
                    "--time-limit", "--no-soft", "--weights",
                    "--diagnose", "--verbose",
                ],
            },
            {
                "name": "Schnelltest",
                "options": ["--small"],
            },
        ],
        "main.py export": [
            {
                "name": "Format & Ausgabe",
                "options": ["--format", "--output-dir"],
            },
            {
                "name": "Datenpfade",
                "options": ["--solution-path", "--data-path"],
            },
        ],
        "main.py substitute": [
            {
                "name": "Abwesenheit",
                "options": ["--teacher", "--day", "--slot", "--top"],
            },
            {
                "name": "Datenpfade",
                "options": ["--json-path", "--solution-path"],
            },
        ],
        "main.py show": [
            {
                "name": "Datenpfade",
                "options": ["--json-path", "--solution-path"],
            },
        ],
    }

    # ── Farben & Panel-Stile ──────────────────────────────────────────────────
    # Befehls-Panel
    rc.STYLE_COMMANDS_PANEL_BORDER    = "bold cyan"
    rc.STYLE_COMMANDS_PANEL_BOX       = "ROUNDED"
    rc.STYLE_COMMANDS_PANEL_TITLE_STYLE = "bold white on dark_blue"
    rc.STYLE_COMMANDS_PANEL_PADDING   = (0, 1)

    # Options-Panel
    rc.STYLE_OPTIONS_PANEL_BORDER     = "bold blue"
    rc.STYLE_OPTIONS_PANEL_BOX        = "ROUNDED"
    rc.STYLE_OPTIONS_PANEL_TITLE_STYLE = "bold white on dark_blue"
    rc.STYLE_OPTIONS_PANEL_PADDING    = (0, 1)

    # Tabellen-Zebra-Streifen (nur Befehls-Tabelle, nicht Optionen)
    rc.STYLE_COMMANDS_TABLE_ROW_STYLES = ["", "dim"]
    rc.STYLE_OPTIONS_TABLE_ROW_STYLES  = []
    rc.STYLE_COMMANDS_TABLE_PADDING    = (0, 2)
    rc.STYLE_OPTIONS_TABLE_PADDING     = (0, 2)
    rc.STYLE_COMMANDS_TABLE_LEADING    = 1

    # Text-Stile
    rc.STYLE_HELPTEXT_FIRST_LINE = "bold"
    rc.STYLE_HELPTEXT             = ""
    rc.STYLE_OPTION               = "bold yellow"
    rc.STYLE_SWITCH               = "bold green"
    rc.STYLE_ARGUMENT             = "bold magenta"
    rc.STYLE_COMMAND              = "bold cyan"
    rc.STYLE_METAVAR              = "italic dim"
    rc.STYLE_METAVAR_SEPARATOR    = "dim"
    rc.STYLE_USAGE                = "bold white"
    rc.STYLE_USAGE_COMMAND        = "bold cyan"
    rc.STYLE_HEADER_TEXT          = ""
    rc.STYLE_FOOTER_TEXT          = ""

    # Fehler-Panel
    rc.STYLE_ERRORS_PANEL_BORDER  = "bold red"
    rc.STYLE_ERRORS_PANEL_BOX     = "ROUNDED"
    rc.ERRORS_PANEL_TITLE         = "Fehler"

    # Panel-Titel-Labels
    rc.OPTIONS_PANEL_TITLE        = "Optionen"
    rc.COMMANDS_PANEL_TITLE       = "Befehle"
    rc.ARGUMENTS_PANEL_TITLE      = "Argumente"

    # Hilfetext-Einrückung
    rc.PADDING_HELPTEXT           = (0, 1, 0, 1)

except ImportError:
    import click

from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()

# ─── LOGGING ──────────────────────────────────────────────────────────────────

_LOG_FILE = Path("output/stundenplan.log")


def _setup_logging(verbose: bool = False) -> None:
    """Richtet Logging mit RichHandler (Konsole) + FileHandler (Log-Datei) ein."""
    level = logging.DEBUG if verbose else logging.INFO
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

    handlers: list[logging.Handler] = [
        RichHandler(
            console=console,
            rich_tracebacks=True,
            show_path=False,
            markup=True,
        ),
        logging.FileHandler(_LOG_FILE, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
        force=True,
    )
    # Unterdrücke OR-Tools-Rauschen auf Konsole (landet trotzdem im Log)
    logging.getLogger("ortools").setLevel(logging.WARNING)

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
    """[bold]Erzeugt realistische Testdaten[/bold] (Lehrkräfte, Klassen, Räume, Kopplungen).

    Enthält absichtliche Engpässe (Chemie-Mangel, Freitag-Cluster,
    Fachraum-Limits) für einen realistischen Solver-Test.
    """
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
            f.write(f"  {t.id:4s} {t.name:35s} {t.deputat_min}-{t.deputat_max}h  {t.subjects}\n")
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
@click.option("--solution-path", default=str(DEFAULT_SOLUTION_JSON),
              help="Pfad zur solution.json für Post-Solve-Validierung.")
@click.option("--solution", "validate_solution", is_flag=True, default=False,
              help="Post-Solve-Validierung der fertigen Lösung ausführen.")
def cmd_validate(json_path: str, gen_first: bool,
                 solution_path: str, validate_solution: bool):
    """Führt einen Machbarkeits-Check auf dem aktuellen Datensatz durch.

    Mit --solution wird zusätzlich die fertige Lösung auf Constraint-Verletzungen geprüft.
    """
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

    # Post-Solve Validierung
    if validate_solution:
        sol_path = Path(solution_path)
        if not sol_path.exists():
            console.print(
                f"[red]Lösung nicht gefunden: {sol_path}[/red]\n"
                "Führen Sie zunächst [bold]python main.py solve[/bold] aus."
            )
            sys.exit(1)
        from solver.scheduler import ScheduleSolution
        from analysis.solution_validator import SolutionValidator

        console.print(f"\n[bold]Lade Lösung:[/bold] {sol_path}")
        solution = ScheduleSolution.load_json(sol_path)
        validator = SolutionValidator()
        with console.status("[green]Validiere Lösung...[/green]"):
            val_report = validator.validate(solution, data)
        val_report.print_rich()
        if not val_report.is_valid:
            sys.exit(1)

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
            deputat_min_fraction=0.80,
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
    dep_max = 9  # 10 × 9h = 90h >> Gesamtbedarf (62h inkl. Kopplung) → Solver-Spielraum
    dep_min = 4  # T08/T09 (Kopplung-only) bekommen max 4h Kopplungsstunden → dep_min ≤ 4
    teachers = [
        Teacher(id="T01", name="Müller, Anna",   subjects=["Deutsch", "Geschichte"],  deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T02", name="Schmidt, Hans",  subjects=["Mathematik", "Physik"],   deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T03", name="Weber, Eva",     subjects=["Englisch", "Politik"],    deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T04", name="Becker, Klaus",  subjects=["Biologie", "Erdkunde"],   deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T05", name="Koch, Lisa",     subjects=["Kunst", "Musik"],         deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T06", name="Wagner, Tom",    subjects=["Sport", "Chemie"],        deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T07", name="Braun, Sara",    subjects=["Latein", "Deutsch"],      deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T08", name="Wolf, Peter",    subjects=["Religion", "Ethik"],      deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T09", name="Neumann, Maria", subjects=["Religion", "Ethik"],      deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
        Teacher(id="T10", name="Schulz, Ralf",   subjects=["Mathematik", "Deutsch"],  deputat_max=dep_max, deputat_min=dep_min, max_hours_per_day=6, max_gaps_per_day=2),
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
    """[bold]Berechnet den Stundenplan[/bold] mit Google OR-Tools CP-SAT.

    Standardmäßig werden harte Constraints gelöst und anschließend
    [cyan]Soft-Constraints optimiert[/cyan] (Springstunden, Deputat,
    Doppelstunden, Fächerverteilung). Mit [yellow]--no-soft[/yellow] nur
    harte Constraints — deutlich schneller.
    """
    from models.school_data import SchoolData
    from solver.scheduler import ScheduleSolver
    from solver.pinning import PinManager

    _setup_logging(verbose=verbose)

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
    table.add_column("Min-Max", justify="right")
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
            delta = actual - teacher.deputat_max
            rows.append((t_id, f"{teacher.deputat_min}-{teacher.deputat_max}", actual, delta, teacher))

    rows.sort(key=lambda r: abs(r[3]), reverse=True)
    for t_id, minmax, ist, delta, teacher in rows[:10]:
        if teacher.deputat_min <= ist <= teacher.deputat_max:
            color = "green"
        elif ist < teacher.deputat_min:
            color = "red"
        else:
            color = "yellow"
        table.add_row(t_id, minmax, f"[{color}]{ist}[/{color}]", f"[{color}]{delta:+d}[/{color}]")

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
    """[bold]Exportiert den Stundenplan[/bold] als Excel-Arbeitsmappe und/oder PDF.

    Die Ausgabe enthält je ein Blatt pro [cyan]Klasse[/cyan],
    [cyan]Lehrer[/cyan] und [cyan]Fachraum[/cyan] sowie eine
    Übersichtsseite mit Deputat-Statistiken.
    """
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
    """[bold]Komplette Pipeline:[/bold] [cyan]generate → solve → export[/cyan].

    Erzeugt Testdaten, berechnet den Stundenplan und exportiert das
    Ergebnis in einem einzigen Schritt.
    """
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


# ─── QUALITY ──────────────────────────────────────────────────────────────────

@click.command("quality")
@click.option("--json-path", default=str(DEFAULT_DATA_JSON),
              help="Pfad zur school_data.json.")
@click.option("--solution-path", default=str(DEFAULT_SOLUTION_JSON),
              help="Pfad zur solution.json.")
@click.option(
    "--format", "fmt", default="console",
    type=click.Choice(["console", "excel", "both"]),
    help="Ausgabeformat: console, excel oder both.",
)
@click.option("--output-dir", default=str(DEFAULT_EXPORT_DIR),
              help="Ausgabeverzeichnis für Excel-Export.")
def cmd_quality(json_path: str, solution_path: str, fmt: str, output_dir: str):
    """Erstellt einen Qualitätsbericht (Lehrer-Auslastung, Klassen-Qualität, KPIs)."""
    from models.school_data import SchoolData
    from solver.scheduler import ScheduleSolution
    from analysis.quality_report import QualityAnalyzer

    sol_path = Path(solution_path)
    dat_path = Path(json_path)

    for p, label in [(sol_path, "Lösung"), (dat_path, "Schuldaten")]:
        if not p.exists():
            console.print(f"[red]{label} nicht gefunden: {p}[/red]")
            sys.exit(1)

    console.print("[bold]Lade Daten...[/bold]")
    solution    = ScheduleSolution.load_json(sol_path)
    school_data = SchoolData.load_json(dat_path)

    analyzer = QualityAnalyzer()
    with console.status("[green]Analysiere Lösung...[/green]"):
        report = analyzer.analyze(solution, school_data)

    if fmt in ("console", "both"):
        analyzer.print_rich(report, school_data.config)

    if fmt in ("excel", "both"):
        from export.excel_export import ExcelExporter
        out_dir  = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        xlsx_path = out_dir / "stundenplan.xlsx"
        console.print(f"[bold]Excel-Export mit Qualitätsblatt:[/bold] {xlsx_path}")
        with console.status("[green]Excel wird erstellt...[/green]"):
            ExcelExporter(solution, school_data).export(xlsx_path, quality_report=report)
        console.print(f"[green]✓[/green] Excel gespeichert: {xlsx_path}")


# ─── SUBSTITUTE ───────────────────────────────────────────────────────────────

@click.command("substitute")
@click.option("--teacher", "-t", required=True,
              help="Lehrer-ID des abwesenden Lehrers (z.B. T01).")
@click.option("--day", "-d", default=None,
              help="Wochentag (z.B. 'montag', 'mo', '0'). Optional: alle Tage.")
@click.option("--slot", "-s", default=None, type=int,
              help="Slot-Nummer (1-basiert). Optional: alle Slots.")
@click.option("--json-path", default=str(DEFAULT_DATA_JSON),
              help="Pfad zur school_data.json.")
@click.option("--solution-path", default=str(DEFAULT_SOLUTION_JSON),
              help="Pfad zur solution.json.")
@click.option("--top", default=5, show_default=True,
              help="Maximal so viele Kandidaten pro Slot anzeigen.")
def cmd_substitute(teacher: str, day, slot, json_path: str,
                   solution_path: str, top: int):
    """Findet geeignete Vertreter für einen abwesenden Lehrer.

    Ohne --day/--slot werden Kandidaten für alle Slots des Lehrers angezeigt.

    Beispiele:

      python main.py substitute --teacher T01

      python main.py substitute --teacher T01 --day montag --slot 3
    """
    from models.school_data import SchoolData
    from solver.scheduler import ScheduleSolution
    from analysis.substitution_helper import SubstitutionFinder

    sol_path = Path(solution_path)
    dat_path = Path(json_path)

    for p, label in [(sol_path, "Lösung"), (dat_path, "Schuldaten")]:
        if not p.exists():
            console.print(f"[red]{label} nicht gefunden: {p}[/red]")
            sys.exit(1)

    solution    = ScheduleSolution.load_json(sol_path)
    school_data = SchoolData.load_json(dat_path)
    day_names   = school_data.config.time_grid.day_names

    teacher_id = teacher.upper()
    finder = SubstitutionFinder()

    # Lehrer prüfen
    teacher_obj = next(
        (t for t in school_data.teachers if t.id == teacher_id), None
    )
    if teacher_obj is None:
        console.print(f"[red]Lehrer '{teacher_id}' nicht gefunden.[/red]")
        sys.exit(1)

    def _resolve_day(day_str: str) -> int | None:
        """Wandelt Tages-String in Index um (0=Mo..4=Fr)."""
        day_lower = day_str.lower().strip()
        aliases = {
            "mo": 0, "montag": 0, "0": 0,
            "di": 1, "dienstag": 1, "1": 1,
            "mi": 2, "mittwoch": 2, "2": 2,
            "do": 3, "donnerstag": 3, "3": 3,
            "fr": 4, "freitag": 4, "4": 4,
        }
        return aliases.get(day_lower)

    console.print(
        f"\n[bold]Vertretungssuche für:[/bold] "
        f"{teacher_id} – {teacher_obj.name}\n"
        f"Fächer: {', '.join(teacher_obj.subjects)}\n"
    )

    if day is not None and slot is not None:
        # Einzelner Slot
        day_idx = _resolve_day(str(day))
        if day_idx is None:
            console.print(f"[red]Unbekannter Tag: '{day}'[/red]")
            sys.exit(1)
        day_name = day_names[day_idx] if day_idx < len(day_names) else str(day_idx)
        candidates = finder.find_substitutes(
            teacher_id, day_idx, slot, solution, school_data
        )
        _print_substitute_table(
            console, candidates[:top],
            title=f"Vertreter für {teacher_id} am {day_name}, Slot {slot}",
        )
    else:
        # Alle Slots des Lehrers
        all_candidates = finder.find_all_for_teacher(teacher_id, solution, school_data)
        if not all_candidates:
            console.print(
                f"[yellow]Lehrer {teacher_id} hat keine Stunden in der Lösung.[/yellow]"
            )
            return
        for slot_key, candidates in sorted(all_candidates.items()):
            _print_substitute_table(
                console, candidates[:top],
                title=f"Vertreter für {teacher_id} – {slot_key}",
            )


def _print_substitute_table(console, candidates, title: str) -> None:
    """Gibt eine Kandidaten-Tabelle aus."""
    if not candidates:
        console.print(f"[dim]{title}: Keine Kandidaten gefunden.[/dim]")
        return

    table = Table(title=title, box=box.ROUNDED, show_lines=False)
    table.add_column("ID", width=8)
    table.add_column("Name", width=25)
    table.add_column("Gemeinsame Fächer", width=30)
    table.add_column("Verfügbar", width=10, justify="center")
    table.add_column("Ist/Max", justify="right", width=8)
    table.add_column("Score", justify="right", width=8)

    for c in candidates:
        avail_str = "[green]Ja[/green]" if c.is_available_at_slot else "[red]Nein[/red]"
        score_color = (
            "green" if c.score >= 70
            else "yellow" if c.score >= 40
            else "red"
        )
        table.add_row(
            c.teacher_id,
            c.name,
            ", ".join(c.subjects_match),
            avail_str,
            f"{c.current_load_hours}/{int(c.load_ratio * 100)}%",
            f"[{score_color}]{c.score:.0f}[/{score_color}]",
        )
    console.print(table)


# ─── SHOW (Terminal-Viewer) ───────────────────────────────────────────────────

# Rich-Stile für Fachkategorien (statt Hex: Näherungswerte als rich-Farbnamen)
_CATEGORY_STYLE: dict[str, str] = {
    "hauptfach":    "bold blue",
    "sprache":      "bold yellow",
    "nw":           "bold green",
    "musisch":      "bold magenta",
    "sport":        "bold red",
    "gesellschaft": "bold cyan",
    "wpf":          "dim white",
    "sonstig":      "dim white",
}


def _subject_style(subject_name: str, subjects) -> str:
    """Gibt einen rich-Stil für ein Fach zurück."""
    for s in subjects:
        if s.name == subject_name:
            return _CATEGORY_STYLE.get(s.category, "dim white")
    return "dim white"


@click.command("show")
@click.argument("kennung")
@click.option("--json-path", default=str(DEFAULT_DATA_JSON),
              show_default=True, help="Pfad zur SchoolData-JSON.")
@click.option("--solution-path", default=str(DEFAULT_SOLUTION_JSON),
              show_default=True, help="Pfad zur Lösungs-JSON.")
def cmd_show(kennung: str, json_path: str, solution_path: str):
    """[bold]Zeigt einen Stundenplan im Terminal an.[/bold]

    [bold magenta]KENNUNG[/bold magenta] ist entweder eine
    [cyan]Klassen-ID[/cyan] (z.B. [bold]5a[/bold], [bold]10c[/bold])
    oder ein [cyan]Lehrer-Kürzel[/cyan] (z.B. [bold]MÜL[/bold]).
    Springstunden werden [red]rot[/red] hinterlegt.
    """
    from models.school_data import SchoolData
    from solver.scheduler import ScheduleSolution
    from export.helpers import (
        build_time_grid_rows, get_coupling_label, count_gaps,
        count_teacher_actual_hours,
    )
    from config.schema import LessonSlot, PauseSlot

    data_path = Path(json_path)
    sol_path = Path(solution_path)
    if not data_path.exists() or not sol_path.exists():
        console.print(
            "[red]Keine gespeicherte Lösung gefunden.[/red]\n"
            "Führen Sie zuerst [bold]python main.py solve[/bold] aus."
        )
        sys.exit(1)

    school_data = SchoolData.load_json(data_path)
    solution = ScheduleSolution.load_json(sol_path)
    config = solution.config_snapshot

    # ── Identifiziere Modus: Klasse oder Lehrer? ─────────────────────────────
    class_ids = {c.id for c in school_data.classes}
    teacher_ids = {t.id for t in school_data.teachers}

    # Suche case-insensitive
    kennung_lower = kennung.lower()
    matched_class = next(
        (cid for cid in class_ids if cid.lower() == kennung_lower), None
    )
    matched_teacher = next(
        (tid for tid in teacher_ids if tid.lower() == kennung_lower), None
    )

    if matched_class:
        _show_class_schedule(
            matched_class, solution, school_data, config,
            build_time_grid_rows, get_coupling_label, LessonSlot, PauseSlot,
        )
    elif matched_teacher:
        _show_teacher_schedule(
            matched_teacher, solution, school_data, config,
            build_time_grid_rows, count_gaps,
            count_teacher_actual_hours, LessonSlot, PauseSlot,
        )
    else:
        console.print(
            f"[red]Kennung '[bold]{kennung}[/bold]' nicht gefunden.[/red]\n"
            f"Gültige Klassen: {', '.join(sorted(class_ids)[:10])} ...\n"
            f"Gültige Lehrer:  {', '.join(sorted(teacher_ids)[:10])} ..."
        )
        sys.exit(1)


def _show_class_schedule(
    class_id, solution, school_data, config,
    build_time_grid_rows, get_coupling_label, LessonSlot, PauseSlot,
) -> None:
    """Zeigt den Stundenplan einer Klasse als rich-Tabelle."""
    cls = next(c for c in school_data.classes if c.id == class_id)
    entries = solution.get_class_schedule(class_id)

    # Index: (day, slot_number) → entry
    slot_map: dict[tuple[int, int], object] = {}
    for e in entries:
        slot_map[(e.day, e.slot_number)] = e

    day_names = config.time_grid.day_names
    time_rows = build_time_grid_rows(config, max_slot=cls.max_slot)

    table = Table(
        title=f"Stundenplan Klasse [bold]{class_id}[/bold]",
        box=box.ROUNDED,
        show_lines=True,
        header_style="bold white on blue",
    )
    table.add_column("Std.", width=5, justify="center")
    table.add_column("Zeit", width=13, justify="center")
    for d in day_names:
        table.add_column(d, width=18, justify="center")

    for row in time_rows:
        if isinstance(row, PauseSlot):
            table.add_row(
                "—", row.label,
                *["─" * 10] * len(day_names),
                style="dim",
            )
            continue

        slot = row  # LessonSlot
        cells = []
        for day_idx in range(len(day_names)):
            entry = slot_map.get((day_idx, slot.slot_number))
            if entry is None:
                cells.append("[dim]—[/dim]")
            else:
                label = get_coupling_label(entry, school_data)
                subj = entry.subject
                if label:
                    abbrev = label[:3].lower() + "."
                    subj = f"{subj} ({abbrev})"
                style = _subject_style(entry.subject, school_data.subjects)
                room_part = f"\n[dim]{entry.room}[/dim]" if entry.room else ""
                cells.append(
                    f"[{style}]{subj}[/{style}]\n"
                    f"[dim]{entry.teacher_id}[/dim]{room_part}"
                )

        table.add_row(
            str(slot.slot_number),
            f"{slot.start_time}–{slot.end_time}",
            *cells,
        )

    console.print(table)
    console.print(
        f"[dim]Klasse {class_id} | Jahrgang {cls.grade} | "
        f"Soll: {sum(cls.curriculum.values())}h/Woche[/dim]"
    )


def _show_teacher_schedule(
    teacher_id, solution, school_data, config,
    build_time_grid_rows, count_gaps, count_teacher_actual_hours,
    LessonSlot, PauseSlot,
) -> None:
    """Zeigt den Stundenplan eines Lehrers als rich-Tabelle."""
    teacher = next(t for t in school_data.teachers if t.id == teacher_id)
    entries = solution.get_teacher_schedule(teacher_id)

    # Bestimme max genutzten Slot
    used_slots = [e.slot_number for e in entries]
    max_slot = max(used_slots) if used_slots else config.time_grid.sek1_max_slot
    time_rows = build_time_grid_rows(config, max_slot=max_slot)

    # Index: (day, slot_number) → entry
    # Kopplungen können mehrere Entries pro Slot haben → nimm ersten
    slot_map: dict[tuple[int, int], object] = {}
    for e in entries:
        key = (e.day, e.slot_number)
        if key not in slot_map:
            slot_map[key] = e

    day_names = config.time_grid.day_names

    # Ermittle Springstunden pro Tag für Farbmarkierung
    from collections import defaultdict
    by_day: dict[int, list[int]] = defaultdict(list)
    for e in entries:
        by_day[e.day].append(e.slot_number)
    gap_slots: set[tuple[int, int]] = set()
    for day_idx, slots in by_day.items():
        unique = sorted(set(slots))
        if len(unique) > 1:
            first, last = unique[0], unique[-1]
            for h in range(first + 1, last):
                if h not in unique:
                    gap_slots.add((day_idx, h))

    ist_hours = count_teacher_actual_hours(entries, teacher_id)
    gaps_total = count_gaps(entries)

    table = Table(
        title=(
            f"Stundenplan [bold]{teacher_id}[/bold] — "
            f"{teacher.name} | "
            f"Deputat: {teacher.deputat_min}–{teacher.deputat_max}h | "
            f"Ist: {ist_hours}h | Springstd: {gaps_total}"
        ),
        box=box.ROUNDED,
        show_lines=True,
        header_style="bold white on blue",
    )
    table.add_column("Std.", width=5, justify="center")
    table.add_column("Zeit", width=13, justify="center")
    for d in day_names:
        table.add_column(d, width=18, justify="center")

    for row in time_rows:
        if isinstance(row, PauseSlot):
            table.add_row(
                "—", row.label,
                *["─" * 10] * len(day_names),
                style="dim",
            )
            continue

        slot = row
        cells = []
        row_style = None
        for day_idx in range(len(day_names)):
            key = (day_idx, slot.slot_number)
            entry = slot_map.get(key)
            if entry is None:
                if key in gap_slots:
                    cells.append("[bold red]↕ Springstunde[/bold red]")
                    row_style = "on dark_red"
                else:
                    cells.append("[dim]—[/dim]")
            else:
                style = _subject_style(entry.subject, school_data.subjects)
                room_part = f"\n[dim]{entry.room}[/dim]" if entry.room else ""
                cells.append(
                    f"[{style}]{entry.subject}[/{style}]\n"
                    f"[dim]{entry.class_id}[/dim]{room_part}"
                )

        table.add_row(
            str(slot.slot_number),
            f"{slot.start_time}–{slot.end_time}",
            *cells,
            style=row_style,
        )

    console.print(table)
    subjects_str = ", ".join(sorted(set(teacher.subjects)))
    console.print(
        f"[dim]Fächer: {subjects_str} | "
        f"{'Teilzeit' if teacher.is_teilzeit else 'Vollzeit'}[/dim]"
    )


# ─── HAUPT-CLI ────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """[bold]Automatischer Stundenplan-Generator[/bold] für Gymnasien (Sekundarstufe I).

    Löst die Stundenzuweisung als [cyan]Constraint-Satisfaction-Problem[/cyan]
    mit [cyan]Google OR-Tools CP-SAT[/cyan]. Unterstützt Kopplungen,
    Doppelstunden, Fachräume und Deputat-Grenzen.
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
cli.add_command(cmd_quality)
cli.add_command(cmd_substitute)
cli.add_command(cmd_show)


if __name__ == "__main__":
    main()
