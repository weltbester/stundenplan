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
  python main.py export                   Excel + PDF exportieren
  python main.py run                      generate → solve → export
  python main.py scenario save <name>     Szenario speichern
  python main.py scenario load <name>     Szenario laden
  python main.py scenario list            Szenarien auflisten
"""

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()

# Standard-Pfad für gespeicherte SchoolData
DEFAULT_DATA_JSON = Path("output/school_data.json")


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

@click.command("solve")
def cmd_solve():
    """Berechnet den Stundenplan (Solver — Phase 2)."""
    console.print(
        "[yellow]Solver wird in Phase 2 implementiert.[/yellow]\n"
        "Aktuell: Phase 1 (Datenmodell & Fake-Daten)."
    )


# ─── EXPORT ───────────────────────────────────────────────────────────────────

@click.command("export")
def cmd_export():
    """Exportiert den Stundenplan als Excel und PDF (Phase 4)."""
    console.print(
        "[yellow]Export wird in Phase 4 implementiert.[/yellow]\n"
        "Aktuell: Phase 1 (Datenmodell & Fake-Daten)."
    )


# ─── RUN ──────────────────────────────────────────────────────────────────────

@click.command("run")
def cmd_run():
    """Führt generate → solve → export aus."""
    console.print("[bold]Pipeline: generate → solve → export[/bold]")
    console.print(
        "[yellow]Solver und Export werden in späteren Phasen implementiert.[/yellow]"
    )


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
cli.add_command(cmd_export)
cli.add_command(cmd_run)
cli.add_command(cmd_scenario)


if __name__ == "__main__":
    main()
