"""Textual TUI Browser für den Stundenplan.

Startet mit: python main.py browse
Navigation: j/k oder ↑↓, Enter=Auswahl, /=Suche, q=Beenden, ?=Hilfe
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solver.scheduler import ScheduleSolution
    from models.school_data import SchoolData
    from config.schema import SchoolConfig


class StundenplanApp:
    """Textual TUI App für den Stundenplan.

    Lazy-importiert textual um Startzeit zu minimieren.
    """

    def __init__(
        self,
        solution: "ScheduleSolution",
        school_data: "SchoolData",
    ) -> None:
        self.solution = solution
        self.school_data = school_data

    def run(self) -> None:
        """Startet die TUI Anwendung."""
        try:
            from textual.app import App, ComposeResult
            from textual.widgets import (
                Header, Footer, ListView, ListItem, DataTable, Input, Label,
            )
            from textual.containers import Horizontal, Vertical
            from textual.binding import Binding
        except ImportError:
            raise ImportError(
                "textual nicht installiert. Bitte: pip install textual>=0.60"
            )

        solution = self.solution
        school_data = self.school_data
        config = solution.config_snapshot

        class _App(App):
            CSS = """
            ListView { width: 30; border: solid $primary; }
            DataTable { border: solid $secondary; }
            Input { dock: bottom; }
            """
            BINDINGS = [
                Binding("q", "quit", "Beenden"),
                Binding("escape", "quit", "Beenden"),
                Binding("/", "focus_search", "Suche"),
                Binding("?", "show_help", "Hilfe"),
            ]

            def compose(self) -> ComposeResult:
                yield Header()
                with Horizontal():
                    lv = ListView(id="entity_list")
                    yield lv
                    yield DataTable(id="schedule_table")
                yield Input(
                    placeholder="Suche (Klasse oder Lehrer)...", id="search"
                )
                yield Footer()

            def on_mount(self) -> None:
                self._all_items = []
                lv = self.query_one("#entity_list", ListView)

                for cls in sorted(school_data.classes, key=lambda c: c.id):
                    self._all_items.append(("class", cls.id))
                    lv.append(ListItem(Label(f"Klasse {cls.id}")))

                for teacher in sorted(school_data.teachers, key=lambda t: t.id):
                    self._all_items.append(("teacher", teacher.id))
                    lv.append(ListItem(Label(f"{teacher.id} – {teacher.name}")))

                self._show_entity(
                    "class",
                    school_data.classes[0].id if school_data.classes else None,
                )

            def on_list_view_selected(self, event: ListView.Selected) -> None:
                idx = event.list_view.index
                if idx is not None and 0 <= idx < len(self._all_items):
                    kind, eid = self._all_items[idx]
                    self._show_entity(kind, eid)

            def on_input_changed(self, event: Input.Changed) -> None:
                query = event.value.lower()
                lv = self.query_one("#entity_list", ListView)
                lv.clear()
                self._all_items = []
                for cls in sorted(school_data.classes, key=lambda c: c.id):
                    if not query or query in cls.id.lower():
                        self._all_items.append(("class", cls.id))
                        lv.append(ListItem(Label(f"Klasse {cls.id}")))
                for teacher in sorted(school_data.teachers, key=lambda t: t.id):
                    label = f"{teacher.id} – {teacher.name}"
                    if not query or query in label.lower():
                        self._all_items.append(("teacher", teacher.id))
                        lv.append(ListItem(Label(label)))

            def _show_entity(self, kind: str, eid: str | None) -> None:
                if eid is None:
                    return
                from export.tui_renderer import (
                    render_class_rows, render_teacher_rows,
                )

                table = self.query_one("#schedule_table", DataTable)
                table.clear(columns=True)

                day_names = config.time_grid.day_names
                table.add_columns("Std.", "Zeit", *day_names)

                if kind == "class":
                    rows = render_class_rows(eid, solution, school_data, config)
                else:
                    rows = render_teacher_rows(eid, solution, school_data, config)

                for row in rows:
                    table.add_row(*row)

            def action_focus_search(self) -> None:
                self.query_one("#search", Input).focus()

            def action_show_help(self) -> None:
                self.notify(
                    "j/k: Navigation | Enter: Auswählen | /: Suche | q: Beenden",
                    title="Hilfe",
                )

        _App().run()
