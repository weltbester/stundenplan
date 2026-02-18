"""Konfigurationsmanager: Laden, Speichern, Validieren und interaktives Bearbeiten.

Nutzt ruamel.yaml für YAML-Serialisierung mit Kommentaren.
"""

import json
from datetime import date
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table
from rich import box
from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from config.schema import (
    CouplingConfig,
    GradeConfig,
    GradeDefinition,
    RoomConfig,
    SchoolConfig,
    SolverConfig,
    SpecialRoomDef,
    TeacherConfig,
)

console = Console()
yaml = YAML()
yaml.default_flow_style = False
yaml.width = 120


# ─── YAML-KOMMENTAR-AUFBAU ───

_YAML_HEADER = f"""\
# ============================================
# Stundenplan-Generator — Schulkonfiguration
# Version: 1.1 (Sekundarstufe I)
# Erstellt: {date.today().isoformat()}
# ============================================
"""

_SECTION_COMMENTS = {
    "time_grid": (
        "Zeitraster",
        "Definiert Unterrichtsstunden, Pausen und erlaubte Doppelstunden-Blöcke.\n"
        "Doppelstunden über Pausen hinweg sind NICHT erlaubt.",
    ),
    "grades": (
        "Jahrgänge & Klassen",
        "Pro Jahrgang konfigurierbar: Klassenanzahl und Soll-Wochenstunden.",
    ),
    "teachers": (
        "Lehrkräfte",
        None,
    ),
    "rooms": (
        "Fachräume",
        None,
    ),
    "couplings": (
        "Kopplungen",
        None,
    ),
    "solver": (
        "Solver",
        "Gewichte: höher = stärker optimiert. 0 = deaktiviert.",
    ),
}


class ConfigManager:
    CONFIG_DIR = Path("config")
    DEFAULT_CONFIG = CONFIG_DIR / "school_config.yaml"
    SCENARIOS_DIR = Path("scenarios")

    def first_run_check(self) -> bool:
        """Gibt True zurück wenn noch keine Config existiert (Erstaufruf)."""
        return not self.DEFAULT_CONFIG.exists()

    # ─── Laden ───

    def load(self, path: Optional[Path] = None) -> SchoolConfig:
        """Lade Config aus YAML. Validiert automatisch via Pydantic."""
        target = path or self.DEFAULT_CONFIG
        if not target.exists():
            raise FileNotFoundError(
                f"Konfigurationsdatei nicht gefunden: {target}\n"
                f"Führen Sie 'python main.py setup' aus, um die Schule einzurichten."
            )
        with open(target, "r", encoding="utf-8") as f:
            raw = yaml.load(f)
        try:
            config = SchoolConfig.model_validate(dict(raw))
            return config
        except Exception as e:
            raise ValueError(
                f"Konfigurationsdatei ungültig: {target}\n"
                f"Pydantic-Fehler: {e}"
            ) from e

    # ─── Speichern ───

    def save(self, config: SchoolConfig, path: Optional[Path] = None) -> None:
        """Speichere Config als YAML mit deutschen Kommentaren."""
        target = path or self.DEFAULT_CONFIG
        target.parent.mkdir(parents=True, exist_ok=True)

        data = self._build_commented_yaml(config)

        with open(target, "w", encoding="utf-8") as f:
            f.write(_YAML_HEADER + "\n")
            yaml.dump(data, f)

        console.print(f"[green]✓[/green] Konfiguration gespeichert: {target}")

    def _build_commented_yaml(self, config: SchoolConfig) -> CommentedMap:
        """Baut die YAML-Struktur mit Kommentaren auf."""
        raw = json.loads(config.model_dump_json())
        cm = CommentedMap(raw)

        for field, (label, comment) in _SECTION_COMMENTS.items():
            cm.yaml_set_comment_before_after_key(
                field,
                before=f"\n─── {label} ───" + (f"\n{comment}" if comment else ""),
            )

        # Inline-Kommentar für Solver-Zeitlimit
        if "solver" in cm:
            solver_map = CommentedMap(cm["solver"])
            solver_map.yaml_add_eol_comment(
                "Globaler Default", "max_hours_per_day"
            ) if "max_hours_per_day" in solver_map else None
            cm["solver"] = solver_map

        return cm

    # ─── Szenarios ───

    def save_scenario(self, config: SchoolConfig, name: str,
                      description: str = "") -> None:
        """Speichert eine Config als benanntes Szenario."""
        self.SCENARIOS_DIR.mkdir(parents=True, exist_ok=True)
        path = self.SCENARIOS_DIR / f"{name}.yaml"
        if path.exists():
            if not Confirm.ask(
                f"Szenario '{name}' existiert bereits. Überschreiben?", default=False
            ):
                console.print("[yellow]Abgebrochen.[/yellow]")
                return
        self.save(config, path)
        # Beschreibung in separater Metadaten-Datei
        if description:
            meta_path = self.SCENARIOS_DIR / f"{name}.meta.yaml"
            with open(meta_path, "w", encoding="utf-8") as f:
                yaml.dump({"name": name, "description": description,
                           "created": date.today().isoformat()}, f)
        console.print(f"[green]✓[/green] Szenario '{name}' gespeichert.")

    def list_scenarios(self) -> list[dict]:
        """Listet alle gespeicherten Szenarien auf."""
        if not self.SCENARIOS_DIR.exists():
            return []
        scenarios = []
        for p in sorted(self.SCENARIOS_DIR.glob("*.yaml")):
            if p.stem.endswith(".meta"):
                continue
            meta_path = self.SCENARIOS_DIR / f"{p.stem}.meta.yaml"
            description = ""
            created = ""
            if meta_path.exists():
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = yaml.load(f)
                    description = meta.get("description", "")
                    created = meta.get("created", "")
            scenarios.append({
                "name": p.stem,
                "path": str(p),
                "description": description,
                "created": created,
            })
        return scenarios

    def load_scenario(self, name: str) -> SchoolConfig:
        """Lädt ein gespeichertes Szenario."""
        path = self.SCENARIOS_DIR / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(
                f"Szenario '{name}' nicht gefunden. "
                f"Verfügbar: {[s['name'] for s in self.list_scenarios()]}"
            )
        return self.load(path)

    # ─── Interaktives Bearbeiten ───

    def edit_interactive(self, config: SchoolConfig) -> SchoolConfig:
        """Interaktives Bearbeitungsmenü für die Konfiguration."""
        while True:
            console.print()
            console.print(Panel(
                "[bold]Konfiguration bearbeiten[/bold]",
                border_style="cyan",
            ))
            console.print("  [bold]1.[/bold] Zeitraster (Stunden, Pausen, Blöcke)")
            console.print("  [bold]2.[/bold] Jahrgänge & Klassen")
            console.print("  [bold]3.[/bold] Lehrkräfte")
            console.print("  [bold]4.[/bold] Fachräume")
            console.print("  [bold]5.[/bold] Kopplungen")
            console.print("  [bold]6.[/bold] Solver-Gewichte")
            console.print("  [bold]0.[/bold] Speichern & Zurück")

            choice = Prompt.ask("\nAuswahl", default="0")

            if choice == "1":
                config = config.model_copy(
                    update={"time_grid": self._edit_time_grid(config)}
                )
            elif choice == "2":
                config = config.model_copy(
                    update={"grades": self._edit_grades(config.grades)}
                )
            elif choice == "3":
                config = config.model_copy(
                    update={"teachers": self._edit_teachers(config.teachers)}
                )
            elif choice == "4":
                config = config.model_copy(
                    update={"rooms": self._edit_rooms(config.rooms)}
                )
            elif choice == "5":
                config = config.model_copy(
                    update={"couplings": self._edit_couplings(config.couplings)}
                )
            elif choice == "6":
                config = config.model_copy(
                    update={"solver": self._edit_solver(config.solver)}
                )
            elif choice == "0":
                self.save(config)
                break
            else:
                console.print("[yellow]Ungültige Auswahl.[/yellow]")

        return config

    def _edit_time_grid(self, config: SchoolConfig):
        """Zeitraster-Bearbeitung: startet den Wizard-Schritt neu."""
        from config.wizard import _wizard_time_grid, _show_time_grid_table
        console.print("\n[bold]Aktuelles Zeitraster:[/bold]")
        _show_time_grid_table(config.time_grid)
        return _wizard_time_grid()

    def _edit_grades(self, gc: GradeConfig) -> GradeConfig:
        """Jahrgänge interaktiv anpassen."""
        from config.wizard import _show_grades_table
        console.print("\n[bold]Aktuelle Jahrgangskonfiguration:[/bold]")
        _show_grades_table(gc)

        grades = list(gc.grades)
        while True:
            console.print("\n[1] Jahrgang hinzufügen  [2] Jahrgang bearbeiten  "
                          "[3] Jahrgang entfernen  [0] Fertig")
            sub = Prompt.ask("Auswahl", default="0")
            if sub == "0":
                break
            elif sub == "1":
                g = IntPrompt.ask("Jahrgangs-Nummer")
                n = IntPrompt.ask("Parallelklassen", default=6)
                h = IntPrompt.ask("Soll-Stunden/Woche", default=32)
                grades.append(GradeDefinition(grade=g, num_classes=n,
                                              weekly_hours_target=h))
                grades.sort(key=lambda x: x.grade)
            elif sub == "2":
                g = IntPrompt.ask("Welchen Jahrgang bearbeiten?")
                for i, gd in enumerate(grades):
                    if gd.grade == g:
                        n = IntPrompt.ask("Parallelklassen",
                                          default=gd.num_classes)
                        h = IntPrompt.ask("Soll-Stunden/Woche",
                                          default=gd.weekly_hours_target)
                        grades[i] = GradeDefinition(grade=g, num_classes=n,
                                                    weekly_hours_target=h)
                        break
            elif sub == "3":
                g = IntPrompt.ask("Welchen Jahrgang entfernen?")
                grades = [gd for gd in grades if gd.grade != g]

        return GradeConfig(grades=grades)

    def _edit_teachers(self, tc: TeacherConfig) -> TeacherConfig:
        """Lehrkräfte-Konfiguration interaktiv anpassen."""
        console.print("\n[bold]Aktuelle Lehrkräfte-Konfiguration:[/bold]")
        table = Table(box=box.SIMPLE)
        table.add_column("Parameter", style="bold")
        table.add_column("Aktuell")
        for k, v in tc.model_dump().items():
            table.add_row(k, str(v))
        console.print(table)

        if not Confirm.ask("Änderungen vornehmen?", default=False):
            return tc

        from config.wizard import _wizard_teachers
        return _wizard_teachers()

    def _edit_rooms(self, rc: RoomConfig) -> RoomConfig:
        """Fachräume interaktiv anpassen."""
        from config.wizard import _show_rooms_table
        console.print("\n[bold]Aktuelle Fachräume:[/bold]")
        _show_rooms_table(rc)

        rooms = list(rc.special_rooms)
        while True:
            console.print("\n[1] Raum hinzufügen  [2] Raum bearbeiten  "
                          "[3] Raum entfernen  [0] Fertig")
            sub = Prompt.ask("Auswahl", default="0")
            if sub == "0":
                break
            elif sub == "1":
                rt = Prompt.ask("Kürzel (z.B. physik)")
                dn = Prompt.ask("Anzeigename")
                ct = IntPrompt.ask("Anzahl Räume", default=2)
                rooms.append(SpecialRoomDef(room_type=rt, display_name=dn, count=ct))
            elif sub == "2":
                rt = Prompt.ask("Welchen Raumtyp bearbeiten?")
                for i, r in enumerate(rooms):
                    if r.room_type == rt:
                        ct = IntPrompt.ask("Neue Anzahl Räume", default=r.count)
                        rooms[i] = SpecialRoomDef(room_type=rt,
                                                  display_name=r.display_name,
                                                  count=ct)
                        break
            elif sub == "3":
                rt = Prompt.ask("Welchen Raumtyp entfernen?")
                rooms = [r for r in rooms if r.room_type != rt]

        return RoomConfig(special_rooms=rooms)

    def _edit_couplings(self, cc: CouplingConfig) -> CouplingConfig:
        """Kopplungs-Konfiguration interaktiv anpassen."""
        from config.wizard import _wizard_couplings
        return _wizard_couplings()

    def _edit_solver(self, sc: SolverConfig) -> SolverConfig:
        """Solver-Gewichte interaktiv anpassen."""
        from config.wizard import _wizard_solver
        return _wizard_solver()
