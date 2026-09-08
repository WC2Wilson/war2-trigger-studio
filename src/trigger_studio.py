from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from clause_editor import (
    ACTIONS,
    ACTION_CATEGORIES,
    CONDITIONS,
    CONDITION_CATEGORIES,
    KIND_HELP,
    clause_summary,
    edit_clause,
)
from engine import TriggerEngine
from live import LiveAdapter
from pud import PudMap
from trigger_model import Clause, Location, Scenario, Trigger
from feature_metadata import display_kind, multiplayer_note, trigger_multiplayer_safe
from ability_editor import AbilityManagerDialog
from card_editor import CardManagerDialog


BG = "#171a1f"
PANEL = "#20242b"
PANEL_2 = "#15181d"
TEXT = "#e1e5e9"
MUTED = "#9aa5af"
SELECT = "#2b3440"
SELECT_2 = "#354452"
ACCENT = "#4f84a8"
BORDER = "#30363f"


class ToolTip:
    def __init__(self, widget: tk.Widget, text: str):
        self.widget = widget
        self.text = text
        self.popup: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        self.after_id: str | None = None

    def _schedule(self, _event=None):
        self._hide()
        self.after_id = self.widget.after(450, self._show)

    def _show(self):
        if self.popup or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.popup = tk.Toplevel(self.widget)
        self.popup.overrideredirect(True)
        self.popup.geometry(f"+{x}+{y}")
        label = tk.Label(
            self.popup,
            text=self.text,
            bg="#111419",
            fg=TEXT,
            bd=1,
            relief="solid",
            padx=8,
            pady=6,
            wraplength=360,
            justify="left",
        )
        label.pack()

    def _hide(self, _event=None):
        if self.after_id:
            try:
                self.widget.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None
        if self.popup:
            self.popup.destroy()
            self.popup = None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Warcraft II Trigger Studio 1.44.0")
        self.geometry("1540x940")
        self.minsize(1180, 720)
        self.configure(bg=BG)

        self.scenario = Scenario()
        self.current: Path | None = None
        self.pud: PudMap | None = None
        self.live: LiveAdapter | None = None
        self.live_engine: TriggerEngine | None = None
        self.live_running = False
        self._live_runtime_error_streak = 0

        # 1.40/1.42 automation. Auto mode watches for Warcraft, waits until a match is
        # actually in GAME_RUN, attaches, identifies the live map when possible,
        # switches to the matching open sidecar, and starts triggers. Manual
        # Start/Stop remain authoritative for deep testing.
        self.auto_live_var = tk.BooleanVar(value=True)
        self._auto_probe_after_id: str | None = None
        self._auto_match_serial = 0
        self._auto_running_seen = False
        self._auto_manual_stop_serial: int | None = None
        self._auto_attaching = False
        self._auto_detected_map = ""
        self._auto_last_pid: int | None = None
        self._auto_absent_streak = 0
        self._auto_not_running_streak = 0

        # 1.42 professional shell/status indicators. These are display-only and
        # deliberately do not replace the existing manual Start/Stop semantics.
        self.current_file_var = tk.StringVar(value="No trigger file open")
        self.connection_badge_var = tk.StringVar(value="WARCRAFT  WAITING")
        self.engine_badge_var = tk.StringVar(value="TRIGGERS  STOPPED")
        self.map_badge_var = tk.StringVar(value="MAP  —")

        # Multiple trigger sidecars can stay open at once. Each entry keeps its
        # in-memory Scenario object, so unsaved edits survive while the author
        # switches between mission01 / mission02 / mission03 from Screen ->
        # Trigger Files.
        self._open_trigger_files: dict[Path, Scenario] = {}
        self._trigger_file_order: list[Path] = []
        self._base_title = "Warcraft II Trigger Studio 1.44.0"

        self._shown_trigger: int | None = None
        self._loading_trigger = False
        self._clipboard_clause: Clause | None = None
        self._clause_drag_start: dict[str, int | None] = {"condition": None, "action": None}
        self._trigger_drag_start: int | None = None
        self._palette_drag: tuple[str, str] | None = None
        self._location_window: tk.Toplevel | None = None
        self._json_window: tk.Toplevel | None = None
        self._ability_window: AbilityManagerDialog | None = None
        self._card_window: CardManagerDialog | None = None
        self.loc_tree: ttk.Treeview | None = None

        self._style()
        self._build_menubar()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._shutdown)
        self.refresh()
        self._auto_probe_after_id = self.after(500, self._auto_live_tick)

    # ------------------------------------------------------------------ styling
    def _style(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure(
            ".",
            background=PANEL,
            foreground=TEXT,
            fieldbackground=PANEL_2,
            bordercolor=BORDER,
            darkcolor=PANEL,
            lightcolor=PANEL,
            focuscolor=PANEL,
            troughcolor=PANEL_2,
        )
        s.map(
            ".",
            background=[("active", "#282e36"), ("selected", SELECT)],
            foreground=[("disabled", "#6f7881"), ("selected", TEXT)],
        )
        s.configure("TButton", padding=(8, 6), focuscolor=PANEL, borderwidth=1)
        s.map("TButton", background=[("active", "#2a3038"), ("pressed", SELECT_2)])
        s.configure("Accent.TButton", background="#29445a")
        s.map("Accent.TButton", background=[("active", "#345a76"), ("pressed", "#223a4d")])
        s.configure("TEntry", padding=5, insertcolor="#c7ccd1")
        s.configure("TCombobox", padding=4, arrowsize=14)
        s.map(
            "TCombobox",
            fieldbackground=[("readonly", PANEL_2), ("disabled", "#1b1f24")],
            selectbackground=[("readonly", SELECT)],
            selectforeground=[("readonly", TEXT)],
        )
        s.configure("TCheckbutton", focuscolor=PANEL)
        s.configure("TLabelframe", bordercolor=BORDER, borderwidth=1, relief="solid")
        s.configure("TLabelframe.Label", font=("Segoe UI", 10, "bold"), foreground="#cbd4dc")
        s.configure("Clause.Treeview", background=PANEL_2, fieldbackground=PANEL_2, foreground=TEXT, rowheight=38, borderwidth=0, relief="flat")
        s.map("Clause.Treeview", background=[("selected", SELECT)], foreground=[("selected", TEXT)])
        s.configure("Palette.Treeview", background=PANEL_2, fieldbackground=PANEL_2, foreground=TEXT, rowheight=27, borderwidth=0, relief="flat")
        s.map("Palette.Treeview", background=[("selected", SELECT)], foreground=[("selected", TEXT)])
        s.configure("Location.Treeview", background=PANEL_2, fieldbackground=PANEL_2, foreground=TEXT, rowheight=28)
        s.map("Location.Treeview", background=[("selected", SELECT)], foreground=[("selected", TEXT)])
        s.configure("Vertical.TScrollbar", background="#2a3038", arrowcolor=MUTED)
        s.configure("Horizontal.TScrollbar", background="#2a3038", arrowcolor=MUTED)

        # 1.42 desktop shell / toolbar
        s.configure("AppHeader.TFrame", background="#111419")
        s.configure("Toolbar.TFrame", background="#1b1f25")
        s.configure("AppTitle.TLabel", background="#111419", foreground="#f3f6f8", font=("Segoe UI Semibold", 13))
        s.configure("FilePath.TLabel", background="#111419", foreground=MUTED, font=("Segoe UI", 9))
        s.configure("Toolbar.TButton", padding=(10, 5), font=("Segoe UI", 9))
        s.configure("Run.TButton", padding=(12, 5), background="#29445a", font=("Segoe UI Semibold", 9))
        s.map("Run.TButton", background=[("active", "#345a76"), ("pressed", "#223a4d")])
        s.configure("Stop.TButton", padding=(12, 5), background="#493038", font=("Segoe UI Semibold", 9))
        s.map("Stop.TButton", background=[("active", "#60404a"), ("pressed", "#3b272e")])
        s.configure("Badge.TLabel", background="#252b33", foreground="#cbd4dc", padding=(8, 3), font=("Segoe UI Semibold", 8))
        s.configure("BadgeGood.TLabel", background="#244232", foreground="#c8f0d7", padding=(8, 3), font=("Segoe UI Semibold", 8))
        s.configure("BadgeRun.TLabel", background="#29445a", foreground="#d9efff", padding=(8, 3), font=("Segoe UI Semibold", 8))
        s.configure("Status.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))

        # ttk combobox drop-down lists are classic Tk widgets on Windows.
        self.option_add("*TCombobox*Listbox.background", PANEL_2)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.option_add("*TCombobox*Listbox.selectBackground", SELECT)
        self.option_add("*TCombobox*Listbox.selectForeground", TEXT)
        self.option_add("*TCombobox*Listbox.borderWidth", 0)

    @staticmethod
    def _dark_text(parent, **kwargs) -> tk.Text:
        options = dict(
            bg="#111419",
            fg=TEXT,
            insertbackground="#c7ccd1",
            selectbackground=SELECT,
            selectforeground=TEXT,
            highlightthickness=0,
            relief="flat",
        )
        options.update(kwargs)
        return tk.Text(parent, **options)

    @staticmethod
    def _dark_listbox(parent, **kwargs) -> tk.Listbox:
        options = dict(
            bg=PANEL_2,
            fg=TEXT,
            selectbackground=SELECT,
            selectforeground=TEXT,
            activestyle="none",
            highlightthickness=0,
            relief="flat",
            exportselection=False,
        )
        options.update(kwargs)
        return tk.Listbox(parent, **options)

    @staticmethod
    def _dark_toggle(parent, text: str, variable: tk.BooleanVar, command: Callable | None = None, width: int = 0) -> tk.Checkbutton:
        return tk.Checkbutton(
            parent,
            text=text,
            variable=variable,
            command=command,
            indicatoron=False,
            width=width,
            bg=PANEL,
            fg=TEXT,
            activebackground="#2a3038",
            activeforeground=TEXT,
            selectcolor=SELECT_2,
            disabledforeground="#6f7881",
            highlightthickness=0,
            bd=1,
            relief="flat",
            offrelief="flat",
            overrelief="flat",
            padx=6,
            pady=3,
            font=("Segoe UI", 9),
        )

    # --------------------------------------------------------------- menu bar
    def _menu(self, parent):
        return tk.Menu(parent, tearoff=False, bg=PANEL, fg=TEXT, activebackground=SELECT, activeforeground=TEXT)

    def _build_menubar(self):
        """Build a conventional desktop menu bar.

        1.40 exposed only Screen -> Trigger Files; 1.42 keeps that workspace
        feature but moves it into a normal File/Edit/View/Run/Tools/Help shell.
        """
        menubar = self._menu(self)

        file_menu = self._menu(menubar)
        file_menu.add_command(label="Open Trigger Files...", accelerator="Ctrl+O", command=self.open_sidecar)
        file_menu.add_command(label="Open PUD Map...", accelerator="Ctrl+Shift+O", command=self.open_pud)
        file_menu.add_separator()
        file_menu.add_command(label="Save", accelerator="Ctrl+S", command=self.save)
        file_menu.add_command(label="Save As...", accelerator="Ctrl+Shift+S", command=self.save_as)
        file_menu.add_separator()
        self.trigger_files_menu = self._menu(file_menu)
        file_menu.add_cascade(label="Trigger Files", menu=self.trigger_files_menu)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", accelerator="Alt+F4", command=self._shutdown)
        menubar.add_cascade(label="File", menu=file_menu)

        edit_menu = self._menu(menubar)
        edit_menu.add_command(label="Add Trigger", accelerator="Ctrl+N", command=self.add_trigger)
        edit_menu.add_command(label="Duplicate Trigger", accelerator="Ctrl+D", command=self.clone_trigger)
        edit_menu.add_command(label="Delete Trigger", command=self.delete_trigger)
        edit_menu.add_separator()
        edit_menu.add_command(label="Advanced Trigger JSON...", command=self.show_advanced_json)
        menubar.add_cascade(label="Edit", menu=edit_menu)

        view_menu = self._menu(menubar)
        view_menu.add_command(label="Live Console", accelerator="Ctrl+`", command=self.toggle_console)
        view_menu.add_separator()
        view_menu.add_command(label="Map Information...", command=self.show_map_info)
        view_menu.add_command(label="Locations...", command=self.show_locations)
        view_menu.add_command(label="Forces...", command=self.show_forces)
        view_menu.add_command(label="Project State...", command=self.show_project_state)
        menubar.add_cascade(label="View", menu=view_menu)

        run_menu = self._menu(menubar)
        run_menu.add_checkbutton(label="AUTO Attach + Start", variable=self.auto_live_var, command=self._auto_mode_changed)
        run_menu.add_separator()
        run_menu.add_command(label="Attach to Warcraft II", accelerator="F4", command=self.attach_live)
        run_menu.add_command(label="Detach", accelerator="Shift+F4", command=self.detach_live)
        run_menu.add_separator()
        run_menu.add_command(label="Start Triggers", accelerator="F5", command=self.start_live)
        run_menu.add_command(label="Stop Triggers", accelerator="Shift+F5", command=self.stop_live)
        run_menu.add_command(label="Continue", accelerator="F6", command=self.continue_live)
        run_menu.add_command(label="Step", accelerator="F7", command=self.step_live)
        menubar.add_cascade(label="Run", menu=run_menu)

        tools_menu = self._menu(menubar)
        tools_menu.add_command(label="Custom Ability Engine...", command=self.show_abilities)
        tools_menu.add_command(label="All Cards Trigger Engine...", command=self.show_cards)
        tools_menu.add_separator()
        tools_menu.add_command(label="Validate Trigger File", accelerator="Ctrl+Shift+V", command=self.validate)
        tools_menu.add_command(label="Arm Blank Map Guard...", command=self.arm_blank_map_guard)
        tools_menu.add_separator()
        tools_menu.add_command(label="Live Units Snapshot", command=self.list_live_units)
        tools_menu.add_command(label="Live Players", command=self.list_live_players)
        tools_menu.add_command(label="Live Combat Statistics", command=self.list_live_statistics)
        tools_menu.add_command(label="Trigger Diagnostics", command=self.show_trigger_diagnostics)
        tools_menu.add_command(label="Runtime State", command=self.show_runtime_state)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = self._menu(menubar)
        help_menu.add_command(label="Feature Manual", accelerator="F1", command=self.open_feature_manual)
        help_menu.add_command(label="Open Example Catalog", command=self.open_example_catalog)
        help_menu.add_command(label="Documentation Coverage Report", command=self.open_documentation_coverage)
        help_menu.add_separator()
        help_menu.add_command(label="About Trigger Studio", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.config(menu=menubar)
        self._bind_shortcuts()
        self._refresh_trigger_files_menu()

    def _bind_shortcuts(self):
        bindings = {
            "<Control-o>": self.open_sidecar,
            "<Control-Shift-O>": self.open_pud,
            "<Control-s>": self.save,
            "<Control-Shift-S>": self.save_as,
            "<Control-n>": self.add_trigger,
            "<Control-d>": self.clone_trigger,
            "<Control-grave>": self.toggle_console,
            "<F1>": self.open_feature_manual,
            "<F4>": self.attach_live,
            "<Shift-F4>": self.detach_live,
            "<F5>": self.start_live,
            "<Shift-F5>": self.stop_live,
            "<F6>": self.continue_live,
            "<F7>": self.step_live,
        }
        for sequence, command in bindings.items():
            self.bind_all(sequence, lambda _e, fn=command: fn(), add="+")

    def _refresh_trigger_files_menu(self):
        menu = getattr(self, "trigger_files_menu", None)
        if menu is None:
            return
        menu.delete(0, "end")
        menu.add_command(label="Add Trigger Files...", command=self.open_sidecar)
        menu.add_command(label="Close Current Trigger File", command=self.close_current_trigger_file, state="normal" if self.current else "disabled")
        menu.add_separator()
        if not self._trigger_file_order:
            menu.add_command(label="(no trigger files open)", state="disabled")
            return
        current = self.current.resolve() if self.current else None
        for path in list(self._trigger_file_order):
            if path not in self._open_trigger_files:
                continue
            marker = "● " if current == path else "   "
            menu.add_command(label=marker + path.name, command=lambda p=path: self._switch_trigger_file(p))

    def _update_window_title(self):
        if self.current:
            self.title(f"{self._base_title} — {self.current.name}")
            if hasattr(self, "current_file_var"):
                self.current_file_var.set(self.current.name)
        else:
            self.title(self._base_title)
            if hasattr(self, "current_file_var"):
                self.current_file_var.set("No trigger file open")

    def _remember_current_trigger_file(self):
        if self.current is None:
            return
        path = self.current.resolve()
        self.current = path
        self._open_trigger_files[path] = self.scenario
        if path not in self._trigger_file_order:
            self._trigger_file_order.append(path)

    def _switch_trigger_file(self, path: Path, automatic: bool = False):
        path = Path(path).resolve()
        scenario = self._open_trigger_files.get(path)
        if scenario is None:
            return
        if self.current and self.current.resolve() == path:
            self._refresh_trigger_files_menu()
            return
        if self._shown_trigger is not None:
            self._commit_trigger_details(self._shown_trigger, silent=True)
        self._remember_current_trigger_file()
        self.stop_live(manual=not automatic)
        self.current = path
        self.scenario = scenario
        if self.live:
            self.live.scenario = self.scenario
            # Feature state is scenario-derived. Reinitialize it while the live
            # runner is stopped so a later Start uses this file's objectives,
            # actors, variables, etc. Existing native attach/dispatcher state stays.
            try:
                self.live._init_massive_features()
            except Exception as exc:
                self.live_log(f"Trigger-file runtime state refresh warning: {exc}")
            self.live_engine = TriggerEngine(self.scenario, self.live)
        self._shown_trigger = None
        self.refresh()
        self._refresh_trigger_files_menu()
        self._update_window_title()
        self.status.set(f"Switched to {path.name}")

    def close_current_trigger_file(self):
        if self.current is None:
            return
        if self._shown_trigger is not None:
            self._commit_trigger_details(self._shown_trigger, silent=True)
        closing = self.current.resolve()
        try:
            index = self._trigger_file_order.index(closing)
        except ValueError:
            index = 0
        self.stop_live()
        self._open_trigger_files.pop(closing, None)
        self._trigger_file_order = [p for p in self._trigger_file_order if p != closing]
        if self._trigger_file_order:
            index = min(index, len(self._trigger_file_order) - 1)
            next_path = self._trigger_file_order[index]
            self.current = None
            self._shown_trigger = None
            self._switch_trigger_file(next_path)
        else:
            self.current = None
            self.scenario = Scenario()
            if self.live:
                self.live.scenario = self.scenario
                try:
                    self.live._init_massive_features()
                except Exception as exc:
                    self.live_log(f"Trigger-file runtime state refresh warning: {exc}")
                self.live_engine = TriggerEngine(self.scenario, self.live)
            self._shown_trigger = None
            self.refresh()
            self._refresh_trigger_files_menu()
            self._update_window_title()
            self.status.set(f"Closed {closing.name}")

    # -------------------------------------------------------------------- layout
    def _build(self):
        self._build_app_header()
        self._build_toolbar()

        main = tk.PanedWindow(
            self,
            orient="horizontal",
            bg=BG,
            sashwidth=6,
            sashrelief="flat",
            bd=0,
            relief="flat",
            opaqueresize=True,
        )
        main.pack(fill="both", expand=True, padx=10, pady=(8, 6))

        left = ttk.Frame(main, width=275)
        center = ttk.Frame(main)
        right = ttk.Frame(main, width=320)
        main.add(left, minsize=235, width=280)
        main.add(center, minsize=620)
        main.add(right, minsize=275, width=325)

        self._build_trigger_sidebar(left)
        self._build_trigger_editor(center)
        self._build_palette(right)
        self._build_live_console()
        self._ensure_console_window()
        self.console_window.withdraw()

        self.status_bar = ttk.Frame(self)
        self.status_bar.pack(fill="x", padx=10, pady=(0, 8))
        self.status = tk.StringVar(value="Ready")
        ttk.Label(self.status_bar, textvariable=self.status, style="Status.TLabel").pack(side="left", padx=4)
        ttk.Label(
            self.status_bar,
            text="M = multiplayer-eligible  •  Drag palette items into Conditions/Actions  •  Manual Start/Stop always override AUTO",
            style="Status.TLabel",
        ).pack(side="right", padx=4)
        self._refresh_runtime_badges()

    def _build_app_header(self):
        header = ttk.Frame(self, style="AppHeader.TFrame")
        header.pack(fill="x")
        title_box = ttk.Frame(header, style="AppHeader.TFrame")
        title_box.pack(side="left", padx=(14, 10), pady=(8, 7))
        ttk.Label(title_box, text="Warcraft II Trigger Studio", style="AppTitle.TLabel").pack(anchor="w")
        ttk.Label(title_box, textvariable=self.current_file_var, style="FilePath.TLabel").pack(anchor="w", pady=(1, 0))

        badges = ttk.Frame(header, style="AppHeader.TFrame")
        badges.pack(side="right", padx=12, pady=10)
        self.connection_badge = ttk.Label(badges, textvariable=self.connection_badge_var, style="Badge.TLabel")
        self.connection_badge.pack(side="left", padx=3)
        self.engine_badge = ttk.Label(badges, textvariable=self.engine_badge_var, style="Badge.TLabel")
        self.engine_badge.pack(side="left", padx=3)
        self.map_badge = ttk.Label(badges, textvariable=self.map_badge_var, style="Badge.TLabel")
        self.map_badge.pack(side="left", padx=3)

    def _button(self, parent, text: str, command: Callable, tip: str = "", style: str | None = None):
        button = ttk.Button(parent, text=text, command=command, style=style or "Toolbar.TButton")
        if tip:
            ToolTip(button, tip)
        return button

    def _toolbar_separator(self, parent):
        ttk.Separator(parent, orient="vertical").pack(side="left", fill="y", padx=7, pady=4)

    def _build_toolbar(self):
        """Compact command bar; secondary operations live in the menus."""
        bar = ttk.Frame(self, style="Toolbar.TFrame")
        bar.pack(fill="x", padx=0, pady=0)
        inner = ttk.Frame(bar, style="Toolbar.TFrame")
        inner.pack(fill="x", padx=10, pady=6)

        self._button(inner, "Open", self.open_sidecar, "Open one or more .w2trig.json trigger files.").pack(side="left", padx=2)
        self._button(inner, "Save", self.save, "Save the active trigger file.").pack(side="left", padx=2)
        self._button(inner, "Validate", self.validate, "Validate the active trigger file.").pack(side="left", padx=2)
        self._button(inner, "Abilities", self.show_abilities, "Open the Custom Ability Engine definition editor.").pack(side="left", padx=2)
        self._button(inner, "Cards", self.show_cards, "Open all source and custom command cards as trigger definitions.").pack(side="left", padx=2)
        self._toolbar_separator(inner)

        self._button(inner, "Attach", self.attach_live, "Manually attach to a running Warcraft II match. F4").pack(side="left", padx=2)
        self._button(inner, "Detach", self.detach_live, "Detach and restore Warcraft hook bytes. Shift+F4").pack(side="left", padx=2)
        self._button(inner, "▶  Start", self.start_live, "Start trigger execution. F5", "Run.TButton").pack(side="left", padx=2)
        self._button(inner, "■  Stop", self.stop_live, "Stop trigger execution. Shift+F5", "Stop.TButton").pack(side="left", padx=2)
        self._button(inner, "Continue", self.continue_live, "Continue after a breakpoint. F6").pack(side="left", padx=2)
        self._button(inner, "Step", self.step_live, "Evaluate one debugger cycle. F7").pack(side="left", padx=2)
        self._toolbar_separator(inner)

        auto_toggle = self._dark_toggle(inner, "AUTO Attach + Start", self.auto_live_var, self._auto_mode_changed, width=17)
        auto_toggle.pack(side="left", padx=3)
        ToolTip(auto_toggle, "Default ON. Waits for GAME_RUN, attaches, detects the map/sidecar, and starts triggers. Manual Stop/Detach holds AUTO for the rest of that match.")

        self._button(inner, "Console", self.toggle_console, "Show or hide the live console. Ctrl+`").pack(side="right", padx=2)

    def _refresh_runtime_badges(self):
        if not hasattr(self, "connection_badge_var"):
            return
        attached = self.live is not None
        self.connection_badge_var.set("WARCRAFT  ATTACHED" if attached else ("WARCRAFT  AUTO" if self.auto_live_var.get() else "WARCRAFT  WAITING"))
        self.engine_badge_var.set("TRIGGERS  RUNNING" if self.live_running else "TRIGGERS  STOPPED")
        self.map_badge_var.set("MAP  " + (self._auto_detected_map or "—"))
        if hasattr(self, "connection_badge"):
            self.connection_badge.configure(style="BadgeGood.TLabel" if attached else "Badge.TLabel")
            self.engine_badge.configure(style="BadgeRun.TLabel" if self.live_running else "Badge.TLabel")
            self.map_badge.configure(style="BadgeGood.TLabel" if self._auto_detected_map else "Badge.TLabel")

    def _build_trigger_sidebar(self, parent):
        frame = ttk.LabelFrame(parent, text="Triggers")
        frame.pack(fill="both", expand=True)

        self.trigger_list = self._dark_listbox(frame, width=31, font=("Segoe UI", 10))
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.trigger_list.yview)
        self.trigger_list.configure(yscrollcommand=scroll.set)
        self.trigger_list.pack(side="left", fill="both", expand=True, padx=(6, 0), pady=6)
        scroll.pack(side="right", fill="y", padx=(0, 6), pady=6)

        self.trigger_list.bind("<<ListboxSelect>>", lambda _e: self.show_trigger())
        self.trigger_list.bind("<ButtonPress-1>", self._trigger_drag_press, add="+")
        self.trigger_list.bind("<ButtonRelease-1>", self._trigger_drag_release, add="+")
        self.trigger_list.bind("<Double-1>", lambda _e: self.trigger_name_entry.focus_set(), add="+")

        controls = ttk.Frame(parent)
        controls.pack(fill="x", pady=(6, 0))
        trigger_buttons = [
            ("New", self.add_trigger, "Create a one-shot Always trigger."),
            ("Clone", self.clone_trigger, "Duplicate the selected trigger."),
            ("Delete", self.delete_trigger, "Delete the selected trigger."),
            ("Up", lambda: self.move_trigger(-1), "Move the trigger up."),
            ("Down", lambda: self.move_trigger(1), "Move the trigger down."),
        ]
        for i, (text, cmd, tip) in enumerate(trigger_buttons):
            self._button(controls, text, cmd, tip).grid(row=i // 3, column=i % 3, sticky="ew", padx=2, pady=2)
        for column in range(3):
            controls.columnconfigure(column, weight=1)

        note = ttk.Label(
            parent,
            text="Drag trigger names to change execution order.",
            foreground=MUTED,
            wraplength=255,
            justify="left",
        )
        note.pack(fill="x", padx=4, pady=(8, 0))

    def _build_trigger_editor(self, parent):
        details = ttk.LabelFrame(parent, text="Trigger settings")
        details.pack(fill="x", padx=(6, 6), pady=(0, 6))

        self.trigger_name_var = tk.StringVar()
        self.trigger_enabled_var = tk.BooleanVar(value=True)
        self.trigger_repeat_var = tk.BooleanVar(value=False)
        self.start_delay_var = tk.StringVar(value="0")
        self.repeat_interval_var = tk.StringVar(value="1")
        self.max_runs_var = tk.StringVar(value="0")
        self.condition_mode_var = tk.StringVar(value="All")

        ttk.Label(details, text="Name").grid(row=0, column=0, sticky="w", padx=(8, 4), pady=7)
        self.trigger_name_entry = ttk.Entry(details, textvariable=self.trigger_name_var)
        self.trigger_name_entry.grid(row=0, column=1, columnspan=3, sticky="ew", padx=4, pady=7)
        self._dark_toggle(details, "Enabled", self.trigger_enabled_var).grid(row=0, column=4, sticky="w", padx=8)
        self._button(details, "Apply", lambda: self._commit_trigger_details(self.selected()), "Apply metadata and timing changes.").grid(row=0, column=5, padx=8)

        ttk.Label(details, text="Players").grid(row=1, column=0, sticky="nw", padx=(8, 4), pady=6)
        player_frame = ttk.Frame(details)
        player_frame.grid(row=1, column=1, columnspan=5, sticky="ew", padx=4, pady=4)
        self.player_vars = [tk.BooleanVar(value=(i == 0)) for i in range(16)]
        for i, var in enumerate(self.player_vars):
            self._dark_toggle(player_frame, f"P{i + 1}", var, width=3).grid(row=i // 8, column=i % 8, sticky="ew", padx=2, pady=2)
        group_row = ttk.Frame(player_frame)
        group_row.grid(row=2, column=0, columnspan=8, sticky="ew", pady=(4, 0))
        self._button(group_row, "P1-P8", lambda: self._set_player_selection(range(8)), "Select the eight normal Warcraft player slots.").pack(side="left", padx=2)
        self._button(group_row, "P1-P16", lambda: self._set_player_selection(range(16)), "Select every trigger owner slot.").pack(side="left", padx=2)
        self._button(group_row, "None", lambda: self._set_player_selection(()), "Clear every executing player.").pack(side="left", padx=2)
        self.force_choice_var = tk.StringVar(value="")
        self.force_choice_box = ttk.Combobox(group_row, textvariable=self.force_choice_var, state="readonly", width=18)
        self.force_choice_box.pack(side="left", padx=(12, 3))
        self._button(group_row, "Apply Force", self._apply_force_selection, "Replace the checked players with the selected custom Force.").pack(side="left", padx=2)

        self._dark_toggle(
            details,
            "Repeat / preserve this trigger while conditions are true",
            self.trigger_repeat_var,
            command=self._toggle_repeat_fields,
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=6)
        ttk.Label(details, text="Start delay (sec)").grid(row=2, column=2, sticky="e", padx=(8, 3))
        self.start_delay_entry = ttk.Entry(details, textvariable=self.start_delay_var, width=8)
        self.start_delay_entry.grid(row=2, column=3, sticky="w", padx=(0, 8))
        ttk.Label(details, text="Repeat every (sec)").grid(row=2, column=4, sticky="e", padx=(8, 3))
        self.repeat_interval_entry = ttk.Entry(details, textvariable=self.repeat_interval_var, width=8)
        self.repeat_interval_entry.grid(row=2, column=5, sticky="w", padx=(0, 8))

        ttk.Label(details, text="Condition logic").grid(row=3, column=0, sticky="e", padx=(8, 3), pady=(0, 7))
        ttk.Combobox(details, textvariable=self.condition_mode_var, values=("All", "Any"), state="readonly", width=8).grid(row=3, column=1, sticky="w", padx=(0, 8), pady=(0, 7))
        ttk.Label(details, text="Max runs").grid(row=3, column=2, sticky="e", padx=(8, 3), pady=(0, 7))
        self.max_runs_entry = ttk.Entry(details, textvariable=self.max_runs_var, width=8)
        self.max_runs_entry.grid(row=3, column=3, sticky="w", padx=(0, 8), pady=(0, 7))
        ttk.Label(
            details,
            text="0 = unlimited. Leave Repeat unchecked for one-shot messages/actions. Wait pauses only later actions and never blocks the game.",
            foreground=MUTED,
            wraplength=430,
            justify="left",
        ).grid(row=3, column=4, columnspan=2, sticky="w", padx=8, pady=(0, 7))

        ttk.Label(details, text="Comment").grid(row=4, column=0, sticky="nw", padx=(8, 4), pady=(2, 8))
        self.trigger_comment = self._dark_text(details, height=2, wrap="word")
        self.trigger_comment.grid(row=4, column=1, columnspan=5, sticky="ew", padx=4, pady=(2, 8))
        details.columnconfigure(1, weight=1)
        details.columnconfigure(3, weight=0)
        details.columnconfigure(5, weight=0)

        build_area = ttk.Frame(parent)
        build_area.pack(fill="both", expand=True, padx=6, pady=(0, 0))
        build_area.rowconfigure(0, weight=1)
        build_area.rowconfigure(1, weight=1)
        build_area.columnconfigure(0, weight=1)

        condition_frame = ttk.LabelFrame(build_area, text="Conditions — All = AND, Any = OR; each row can be inverted with NOT")
        action_frame = ttk.LabelFrame(build_area, text="Actions — run from top to bottom")
        condition_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 4))
        action_frame.grid(row=1, column=0, sticky="nsew", pady=(4, 0))
        self.condition_tree = self._build_clause_tree(condition_frame, "condition")
        self.action_tree = self._build_clause_tree(action_frame, "action")
        self._toggle_repeat_fields()

    def _build_clause_tree(self, parent: ttk.Frame, mode: str) -> ttk.Treeview:
        container = ttk.Frame(parent)
        container.pack(fill="both", expand=True, padx=6, pady=(6, 3))
        tree = ttk.Treeview(container, show="tree", selectmode="browse", style="Clause.Treeview", takefocus=False, height=4)
        scroll = ttk.Scrollbar(container, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        tree.bind("<Double-1>", lambda _e, m=mode: self.edit_selected_clause(m))
        tree.bind("<Delete>", lambda _e, m=mode: self.delete_clause(m))
        tree.bind("<Return>", lambda _e, m=mode: self.edit_selected_clause(m))
        tree.bind("<<TreeviewSelect>>", lambda _e, m=mode: self._show_selected_clause_help(m))
        tree.bind("<ButtonPress-1>", lambda e, m=mode: self._clause_drag_press(m, e), add="+")
        tree.bind("<B1-Motion>", lambda e, m=mode: self._clause_drag_motion(m, e), add="+")
        tree.bind("<ButtonRelease-1>", lambda e, m=mode: self._clause_drag_release(m, e), add="+")

        controls = ttk.Frame(parent)
        controls.pack(fill="x", padx=6, pady=(3, 6))
        for text, command, tip in [
            ("Add", lambda m=mode: self.add_clause(m), f"Add a {mode}."),
            ("Edit", lambda m=mode: self.edit_selected_clause(m), f"Edit the selected {mode}."),
            ("Clone", lambda m=mode: self.clone_clause(m), f"Duplicate the selected {mode}."),
            ("Copy", lambda m=mode: self.copy_clause(m), "Copy for pasting into another trigger."),
            ("Paste", lambda m=mode: self.paste_clause(m), "Paste after the selected row."),
            ("Delete", lambda m=mode: self.delete_clause(m), f"Delete the selected {mode}."),
            ("Up", lambda m=mode: self.move_clause(m, -1), "Move up."),
            ("Down", lambda m=mode: self.move_clause(m, 1), "Move down."),
        ]:
            self._button(controls, text, command, tip).pack(side="left", padx=2)
        ttk.Label(controls, text="Drag rows to reorder", foreground=MUTED).pack(side="right", padx=4)
        return tree

    def _build_palette(self, parent):
        palette_frame = ttk.LabelFrame(parent, text="Build palette")
        palette_frame.pack(fill="both", expand=True)
        ttk.Label(
            palette_frame,
            text="Drag or double-click a type. Capital M marks multiplayer-eligible primitives; unbadged items are local/inferred/timing-sensitive.",
            wraplength=285,
            justify="left",
            foreground=MUTED,
        ).pack(fill="x", padx=8, pady=(8, 5))

        search_row = ttk.Frame(palette_frame)
        search_row.pack(fill="x", padx=7, pady=(0, 6))
        ttk.Label(search_row, text="Search").pack(side="left", padx=(0, 5))
        self.palette_search_var = tk.StringVar()
        search = ttk.Entry(search_row, textvariable=self.palette_search_var)
        search.pack(side="left", fill="x", expand=True)
        self.palette_search_var.trace_add("write", lambda *_: self._refresh_palette())

        tree_box = ttk.Frame(palette_frame)
        tree_box.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.palette_tree = ttk.Treeview(tree_box, show="tree", style="Palette.Treeview", selectmode="browse", takefocus=False)
        scroll = ttk.Scrollbar(tree_box, orient="vertical", command=self.palette_tree.yview)
        self.palette_tree.configure(yscrollcommand=scroll.set)
        self.palette_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.palette_tree.bind("<<TreeviewSelect>>", self._palette_selected)
        self.palette_tree.bind("<Double-1>", self._palette_double_click)
        self.palette_tree.bind("<ButtonPress-1>", self._palette_drag_press, add="+")
        self.palette_tree.bind("<ButtonRelease-1>", self._palette_drag_release, add="+")

        help_frame = ttk.LabelFrame(parent, text="What this does")
        help_frame.pack(fill="x", pady=(6, 0))
        self.help_title_var = tk.StringVar(value="Select a condition or action")
        ttk.Label(help_frame, textvariable=self.help_title_var, font=("Segoe UI", 10, "bold")).pack(fill="x", padx=8, pady=(8, 3))
        self.help_text_var = tk.StringVar(value="The explanation for the selected item appears here. Field-specific help also appears inside the editor dialog.")
        ttk.Label(
            help_frame,
            textvariable=self.help_text_var,
            wraplength=295,
            justify="left",
            foreground="#c3cbd2",
        ).pack(fill="x", padx=8, pady=(0, 9))
        self._refresh_palette()

    def _build_live_console(self):
        self.console_visible = False
        self.console_window = None
        # Keep the same Text instance API expected by the live logger, but host it
        # in a dedicated resizable window instead of shrinking the editor.
        self.live_text = None

    def _ensure_console_window(self):
        if self.console_window is not None and self.console_window.winfo_exists():
            return
        window = tk.Toplevel(self)
        window.title("Warcraft II Trigger Console")
        window.geometry("1100x650")
        window.minsize(700, 350)
        window.protocol("WM_DELETE_WINDOW", lambda: self._set_console_visible(False))
        frame = ttk.Frame(window)
        frame.pack(fill="both", expand=True, padx=8, pady=8)
        self.live_text = self._dark_text(frame, height=20, font=("Consolas", 10), fg="#8fd3ff", wrap="none")
        yscroll = ttk.Scrollbar(frame, orient="vertical", command=self.live_text.yview)
        xscroll = ttk.Scrollbar(frame, orient="horizontal", command=self.live_text.xview)
        self.live_text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.live_text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1); frame.columnconfigure(0, weight=1)
        self.console_window = window

    def toggle_console(self):
        self._set_console_visible(not self.console_visible)

    def _set_console_visible(self, visible: bool):
        self.console_visible = bool(visible)
        self._ensure_console_window()
        if self.console_visible:
            self.console_window.deiconify(); self.console_window.lift(); self.console_window.focus_force()
        else:
            self.console_window.withdraw()

    # -------------------------------------------------------------- palette/help
    def _refresh_palette(self):
        query = self.palette_search_var.get().strip().casefold() if hasattr(self, "palette_search_var") else ""
        for item in self.palette_tree.get_children():
            self.palette_tree.delete(item)
        for mode, title, categories in (
            ("condition", "CONDITIONS", CONDITION_CATEGORIES),
            ("action", "ACTIONS", ACTION_CATEGORIES),
        ):
            root = self.palette_tree.insert("", "end", text=title, open=True, values=(mode, ""))
            any_added = False
            for category, kinds in categories.items():
                filtered = [kind for kind in kinds if not query or query in kind.casefold() or query in KIND_HELP.get(kind, "").casefold()]
                if not filtered:
                    continue
                cat = self.palette_tree.insert(root, "end", text=category, open=bool(query), values=(mode, ""))
                for kind in filtered:
                    self.palette_tree.insert(cat, "end", text=display_kind(mode, kind), values=(mode, kind))
                    any_added = True
            if not any_added:
                self.palette_tree.delete(root)

    def _palette_item(self, event=None) -> tuple[str, str] | None:
        item = ""
        if event is not None:
            item = self.palette_tree.identify_row(event.y)
        if not item:
            selected = self.palette_tree.selection()
            item = selected[0] if selected else ""
        if not item:
            return None
        values = self.palette_tree.item(item, "values")
        if len(values) < 2 or not values[1]:
            return None
        return str(values[0]), str(values[1])

    def _palette_selected(self, _event=None):
        item = self._palette_item()
        if item:
            self._show_kind_help(item[1])

    def _palette_double_click(self, event):
        item = self._palette_item(event)
        if item:
            self.add_clause(item[0], preset_kind=item[1])

    def _palette_drag_press(self, event):
        item_id = self.palette_tree.identify_row(event.y)
        if item_id:
            self.palette_tree.selection_set(item_id)
        self._palette_drag = self._palette_item(event)

    def _palette_drag_release(self, event):
        payload = self._palette_drag
        self._palette_drag = None
        if not payload:
            return
        widget = self.winfo_containing(event.x_root, event.y_root)
        mode, kind = payload
        target_tree = self.condition_tree if mode == "condition" else self.action_tree
        if not self._is_descendant(widget, target_tree):
            self.status.set(f"Drop {kind} into the {mode.title()} box")
            return
        local_y = event.y_root - target_tree.winfo_rooty()
        row = target_tree.identify_row(local_y)
        insert_at = int(row) if row else len(self._clauses(mode))
        self.add_clause(mode, preset_kind=kind, insert_at=insert_at)

    @staticmethod
    def _is_descendant(widget: tk.Widget | None, ancestor: tk.Widget) -> bool:
        while widget is not None:
            if widget == ancestor:
                return True
            parent_name = widget.winfo_parent()
            if not parent_name:
                break
            try:
                widget = widget._nametowidget(parent_name)
            except KeyError:
                break
        return False

    def _show_kind_help(self, kind: str, summary: str = ""):
        mode = "condition" if kind in CONDITIONS else "action"
        self.help_title_var.set(display_kind(mode, kind))
        text = KIND_HELP.get(kind, "Configure this item using the fields in its editor.")
        text = text + "\n\n" + multiplayer_note(mode, kind)
        if summary:
            text = f"{summary}\n\n{text}"
        self.help_text_var.set(text)

    def _show_selected_clause_help(self, mode: str):
        index = self._selected_clause_index(mode)
        if index is None:
            return
        clauses = self._clauses(mode)
        if not 0 <= index < len(clauses):
            return
        trigger_index = self.selected()
        player = 0
        if trigger_index is not None and self.scenario.triggers[trigger_index].players:
            player = self.scenario.triggers[trigger_index].players[0]
        clause = clauses[index]
        self._show_kind_help(clause.kind, clause_summary(clause, player))

    # ------------------------------------------------------------- 1.40 auto match
    @staticmethod
    def _normalize_map_key(value: str | Path | None) -> str:
        if value is None:
            return ""
        text = str(value).strip().replace("\\", "/")
        name = text.rsplit("/", 1)[-1].casefold()
        for suffix in (".w2trig.json", ".w2trig", ".pud", ".json"):
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        return "".join(ch for ch in name if ch.isalnum())

    def _sidecar_map_index(self) -> dict[str, list[Path]]:
        index: dict[str, list[Path]] = {}
        items = dict(self._open_trigger_files)
        if self.current is not None:
            items[self.current.resolve()] = self.scenario
        for path, scenario in items.items():
            keys: set[str] = set()
            if getattr(scenario, "map_file", ""):
                keys.add(self._normalize_map_key(scenario.map_file))
            keys.add(self._normalize_map_key(path.name))
            for key in keys:
                if key:
                    index.setdefault(key, []).append(path)
        return index

    def _known_map_candidates(self) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        items = list(self._open_trigger_files.items())
        if self.current is not None and self.current.resolve() not in self._open_trigger_files:
            items.append((self.current.resolve(), self.scenario))
        for path, scenario in items:
            values = []
            if getattr(scenario, "map_file", ""):
                values.append(str(scenario.map_file))
            stem = path.name
            lower = stem.casefold()
            if lower.endswith(".w2trig.json"):
                stem = stem[: -len(".w2trig.json")]
            elif lower.endswith(".json"):
                stem = stem[:-5]
            if stem:
                values.append(stem if stem.casefold().endswith(".pud") else stem + ".pud")
            for value in values:
                name = value.replace("\\", "/").rsplit("/", 1)[-1]
                key = name.casefold()
                if key and key not in seen:
                    seen.add(key)
                    result.append(name)
        if self.pud is not None:
            name = self.pud.path.name
            if name.casefold() not in seen:
                result.append(name)
        return result

    def _auto_sidecar_directories(self) -> list[Path]:
        dirs: list[Path] = []
        for path in self._trigger_file_order:
            dirs.append(path.parent)
        if self.current is not None:
            dirs.append(self.current.resolve().parent)
        dirs.extend([Path.cwd(), Path(__file__).resolve().parent.parent])
        out: list[Path] = []
        seen: set[Path] = set()
        for directory in dirs:
            try:
                resolved = directory.resolve()
            except Exception:
                continue
            if resolved in seen or not resolved.is_dir():
                continue
            seen.add(resolved)
            out.append(resolved)
        return out

    def _auto_discover_sidecar(self, map_name: str) -> Path | None:
        """Find a not-yet-open sidecar next to the user's other mission files."""
        key = self._normalize_map_key(map_name)
        if not key:
            return None
        raw_name = str(map_name).replace("\\", "/").rsplit("/", 1)[-1]
        stem = raw_name[:-4] if raw_name.casefold().endswith(".pud") else raw_name
        direct_names = (f"{stem}.w2trig.json", f"{raw_name}.w2trig.json")
        for directory in self._auto_sidecar_directories():
            for filename in direct_names:
                candidate = directory / filename
                if candidate.is_file():
                    return candidate.resolve()

        # If files were named differently, inspect the small set of sidecars in
        # the same mission folders and compare their declared map_file metadata.
        scanned = 0
        for directory in self._auto_sidecar_directories():
            try:
                candidates = list(directory.glob("*.w2trig.json"))[:200]
            except Exception:
                continue
            for candidate in candidates:
                scanned += 1
                if scanned > 400:
                    return None
                try:
                    scenario = Scenario.load(candidate)
                except Exception:
                    continue
                if self._normalize_map_key(getattr(scenario, "map_file", "")) == key:
                    return candidate.resolve()
        return None

    def _auto_select_sidecar_for_map(self, map_names: list[str]) -> Path | None:
        index = self._sidecar_map_index()
        # detect_map_names returns candidates in confidence order. Prefer the first
        # candidate that maps unambiguously instead of letting stale map strings
        # elsewhere in Warcraft's heap make a current match look ambiguous.
        for map_name in map_names:
            key = self._normalize_map_key(map_name)
            paths: list[Path] = []
            for path in index.get(key, ()):
                if path not in paths:
                    paths.append(path)
            if len(paths) == 1:
                path = paths[0]
                if self.current is None or self.current.resolve() != path:
                    self._switch_trigger_file(path, automatic=True)
                self._refresh_trigger_files_menu()
                self.live_log(f"AUTO MAP: {map_name} -> {path.name}")
                return path
            if len(paths) > 1:
                self.live_log(
                    f"AUTO MAP: {map_name} matches multiple open sidecars; keeping current: "
                    + ", ".join(path.name for path in paths)
                )
                return None

        for map_name in map_names:
            path = self._auto_discover_sidecar(map_name)
            if path is None:
                continue
            try:
                scenario = Scenario.load(path)
                self._open_trigger_files[path] = scenario
                if path not in self._trigger_file_order:
                    self._trigger_file_order.append(path)
                self.live_log(f"AUTO MAP: opened matching sidecar {path.name}")
                if self.current is None or self.current.resolve() != path:
                    self._switch_trigger_file(path, automatic=True)
                self._refresh_trigger_files_menu()
                return path
            except Exception as exc:
                self.live_log(f"AUTO MAP: could not open {path.name}: {exc}")
        return None

    def _detect_live_map(self, automatic: bool = False) -> list[str]:
        if not self.live:
            return []
        try:
            names = self.live.detect_map_names(self._known_map_candidates())
        except Exception as exc:
            self.live_log(f"MAP DETECT warning: {exc}")
            return []
        if names:
            self._auto_detected_map = names[0]
            self.live_log("LIVE MAP: " + ", ".join(names))
            if automatic:
                self._auto_select_sidecar_for_map(names)
            self._refresh_runtime_badges()
            return names
        self._auto_detected_map = ""
        self._refresh_runtime_badges()
        self.live_log(
            "LIVE MAP: filename was not found in readable process strings; "
            "keeping the selected trigger sidecar"
        )
        return []

    def _auto_mode_changed(self):
        self._refresh_runtime_badges()
        if self.auto_live_var.get():
            self.status.set("AUTO mode enabled — waiting for Warcraft II / next running match")
            if self._auto_probe_after_id is None:
                self._auto_probe_after_id = self.after(150, self._auto_live_tick)
        else:
            self.status.set("AUTO mode disabled — manual Attach / Start / Stop remain available")

    def _auto_live_tick(self):
        self._auto_probe_after_id = None
        try:
            if not self.auto_live_var.get():
                return
            probe = LiveAdapter.probe_process_state()
            if not probe.get("present"):
                self._auto_absent_streak += 1
                self._auto_not_running_streak = 0
                if self._auto_absent_streak >= 2:
                    if self.live is not None:
                        self.detach_live(quiet=True, manual=False)
                    self._auto_running_seen = False
                    self._auto_last_pid = None
                    self._auto_detected_map = ""
                    self._refresh_runtime_badges()
                return

            self._auto_absent_streak = 0
            pid = probe.get("pid")
            running = bool(probe.get("running"))
            if not running:
                self._auto_not_running_streak += 1
                if self._auto_not_running_streak >= 2:
                    if self.live is not None:
                        self.detach_live(quiet=True, manual=False)
                    self._auto_running_seen = False
                    self._auto_last_pid = pid
                    self._auto_detected_map = ""
                    self._refresh_runtime_badges()
                    self.status.set(
                        f"AUTO: Warcraft detected (mode {probe.get('mode')}); waiting for match start"
                    )
                return

            self._auto_not_running_streak = 0
            if (not self._auto_running_seen) or (pid is not None and pid != self._auto_last_pid):
                self._auto_match_serial += 1
                self._auto_running_seen = True
                self._auto_last_pid = pid
                self._auto_manual_stop_serial = None
                self._auto_detected_map = ""
                self.live_log(
                    f"AUTO MATCH #{self._auto_match_serial}: GAME_RUN detected"
                    + (f" in PID {pid}" if pid else "")
                    + f"; map dimension {probe.get('dimension')}"
                )

            # Manual Stop/Detach is authoritative for the remainder of this match.
            if self._auto_manual_stop_serial == self._auto_match_serial:
                return

            if self.live is None and not self._auto_attaching:
                self._auto_attaching = True
                try:
                    self.attach_live(automatic=True)
                finally:
                    self._auto_attaching = False

            if self.live is not None and not self.live_running and self._auto_manual_stop_serial != self._auto_match_serial:
                self.start_live(automatic=True)
        except Exception as exc:
            # AUTO mode must never throw out of Tk's polling callback. A failed
            # attach remains visible in the console and the watcher retries only
            # while a valid running match is present.
            self.live_log(f"AUTO watcher warning: {exc}")
        finally:
            if self.winfo_exists() and self.auto_live_var.get():
                self._auto_probe_after_id = self.after(850, self._auto_live_tick)

    # --------------------------------------------------------------- live runtime
    def live_log(self, text):
        # Professional shell behavior: logging never steals focus by opening the
        # console. The Console button/menu remains one click away for diagnostics.
        self._ensure_console_window()
        stamp = __import__("time").strftime("%H:%M:%S")
        self.live_text.insert("end", f"[{stamp}] {text}\n")
        self.live_text.see("end")

    def open_feature_manual(self):
        runtime_dir = Path(__file__).resolve().parent
        candidates = [
            runtime_dir.parent / "docs" / "FEATURES.html",
            runtime_dir / "FEATURES.html",
        ]
        page = next((p for p in candidates if p.exists()), None)
        if page is None:
            messagebox.showerror("Feature Manual", "FEATURES.html was not found in the distribution.")
            return
        try:
            webbrowser.open(page.as_uri())
            self.status.set("Opened complete HTML feature manual")
        except Exception as exc:
            messagebox.showerror("Feature Manual", str(exc))

    def open_example_catalog(self):
        runtime_dir = Path(__file__).resolve().parent
        candidates = [runtime_dir.parent / "docs" / "EXAMPLES.html", runtime_dir / "EXAMPLES.html"]
        page = next((p for p in candidates if p.exists()), None)
        if page is None:
            messagebox.showerror("Examples", "EXAMPLES.html was not found in the distribution.")
            return
        webbrowser.open(page.as_uri())
        self.status.set("Opened trigger example catalog")

    def open_documentation_coverage(self):
        runtime_dir = Path(__file__).resolve().parent
        candidates = [
            runtime_dir.parent / "docs" / "FEATURE_COMPLETENESS_1.44.0.txt",
            runtime_dir / "FEATURE_COMPLETENESS_1.44.0.txt",
        ]
        report = next((p for p in candidates if p.exists()), None)
        if report is None:
            messagebox.showerror("Documentation Coverage", "FEATURE_COMPLETENESS_1.44.0.txt was not found in the distribution.")
            return
        try:
            webbrowser.open(report.as_uri())
            self.status.set("Opened feature documentation coverage report")
        except Exception as exc:
            messagebox.showerror("Documentation Coverage", str(exc))

    def show_about(self):
        messagebox.showinfo(
            "About Warcraft II Trigger Studio",
            "Warcraft II Trigger Studio 1.44.0\n\n"
            "Runtime trigger authoring for Warcraft II Remastered.\n"
            "Custom Ability Engine: targeted casts, effects, costs, cooldowns, charges, hotkeys, and trigger-owned AI.\n"
            "All Cards Trigger Engine: 418 source rows, card events, and Human/Orc cross-faction production and spells.\n"
            "Capital M = multiplayer-eligible primitive.\n"
            "AUTO Attach + Start remains enabled by default; manual controls remain authoritative.\n\n"
            "Editable source is included with this release.",
        )

    def detach_live(self, quiet: bool = False, manual: bool = True):
        self.stop_live(manual=manual)
        adapter = self.live
        self.live = None
        self.live_engine = None
        if adapter is not None:
            try:
                adapter.close()
                if not quiet:
                    self.live_log("Detached cleanly; Warcraft hook bytes restored")
            except Exception as exc:
                if not quiet:
                    messagebox.showerror("Live detach", str(exc))
                else:
                    self.live_log(f"Previous live-adapter cleanup warning: {exc}")
        self._refresh_runtime_badges()
        if not quiet:
            self.status.set("Detached from Warcraft II")

    def _shutdown(self):
        try:
            if self._auto_probe_after_id:
                try:
                    self.after_cancel(self._auto_probe_after_id)
                except tk.TclError:
                    pass
                self._auto_probe_after_id = None
            self.detach_live(quiet=True, manual=False)
        finally:
            self.destroy()

    def show_abilities(self):
        """Open the map-sidecar ability definition editor."""
        if self._ability_window is not None and self._ability_window.winfo_exists():
            if self._ability_window.scenario is self.scenario:
                self._ability_window.deiconify(); self._ability_window.lift(); self._ability_window.focus_force()
                return
            self._ability_window.destroy()
        def changed():
            self.status.set(f"Custom abilities updated ({len(self.scenario.abilities)} definition(s)); save the trigger file to keep them")
        self._ability_window = AbilityManagerDialog(self, self.scenario, changed)
        self._ability_window.protocol("WM_DELETE_WINDOW", self._close_abilities)
        self._ability_window.lift(); self._ability_window.focus_force()

    def _close_abilities(self):
        if self._ability_window is not None and self._ability_window.winfo_exists():
            self._ability_window.destroy()
        self._ability_window = None

    def show_cards(self):
        """Open the map-sidecar command-card definition editor."""
        if self._card_window is not None and self._card_window.winfo_exists():
            if self._card_window.scenario is self.scenario:
                self._card_window.deiconify(); self._card_window.lift(); self._card_window.focus_force()
                return
            self._card_window.destroy()
        def changed():
            self.status.set(f"Trigger cards updated ({len(self.scenario.cards)} definition(s)); save the trigger file to keep them")
        self._card_window = CardManagerDialog(self, self.scenario, changed)
        self._card_window.protocol("WM_DELETE_WINDOW", self._close_cards)
        self._card_window.lift(); self._card_window.focus_force()

    def _close_cards(self):
        if self._card_window is not None and self._card_window.winfo_exists():
            self._card_window.destroy()
        self._card_window = None

    def arm_blank_map_guard(self):
        # 1.35 assumed blank_map_guard.py lived next to trigger_studio.py. In the
        # packaged runtime __file__ can point at an embedded/fake runtime folder,
        # so the GUI incorrectly reported "Missing blank_map_guard.py".
        #
        # Do not route command-line arguments through War2TriggerStudio.exe: the
        # tiny launcher intentionally starts app.py but does not forward its own
        # argv. Call the shipped app.py with the current Python interpreter so
        # `guard arm --wait` arrives intact.
        module_dir = Path(__file__).resolve().parent
        release_roots = [module_dir.parent, Path.cwd()]
        try:
            creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            app = next((base / "app.py" for base in release_roots if (base / "app.py").exists()), None)
            python_exe = Path(sys.executable).resolve()
            if python_exe.name.lower().startswith("pythonw"):
                console_python = python_exe.with_name("python.exe")
                if console_python.exists():
                    python_exe = console_python
            if app is not None:
                cmd = [str(python_exe), str(app), "guard", "arm", "--wait"]
                cwd = str(app.parent)
            else:
                guard = module_dir / "blank_map_guard.py"
                if not guard.exists():
                    messagebox.showerror("Blank Map Guard", "Blank Map Guard runtime is missing from this release")
                    return
                cmd = [str(python_exe), str(guard), "arm", "--wait"]
                cwd = str(guard.parent)
            subprocess.Popen(cmd, cwd=cwd, creationflags=creationflags)
            self.status.set("Blank Map Guard launched; it will signature-scan Warcraft before the empty map starts")
        except Exception as exc:
            messagebox.showerror("Blank Map Guard", str(exc))

    def attach_live(self, automatic: bool = False):
        # Never overwrite a live adapter without restoring its executable hooks.
        self.detach_live(quiet=True, manual=False)
        adapter = LiveAdapter(self.scenario, self.live_log)
        try:
            adapter.attach()
            self.live = adapter
            self.live_engine = TriggerEngine(self.scenario, self.live)
            detected = self._detect_live_map(automatic=automatic)
            units = self.live.units()
            self.live_log(f"Snapshot contains {len(units)} active unit(s)")
            for line in self.live.player_mapping_report():
                self.live_log(line)
            mode = getattr(adapter, "compatibility_mode", "Validated")
            map_suffix = f" — map {detected[0]}" if detected else ""
            self.status.set(f"Attached to Warcraft II — {mode}{map_suffix}")
            self._refresh_runtime_badges()
            self.live_log(f"COMPATIBILITY MODE: {mode}")
            if automatic:
                active = self.current.name if self.current else "unsaved/current trigger set"
                self.live_log(f"AUTO ATTACH: active trigger sidecar is {active}")
            return True
        except Exception as exc:
            try:
                adapter.close()
            except Exception as cleanup_exc:
                self.live_log(f"Failed-attach cleanup warning: {cleanup_exc}")
            self.live = None
            self.live_engine = None
            self._refresh_runtime_badges()
            if automatic:
                self._auto_manual_stop_serial = self._auto_match_serial
                self.live_log(f"AUTO ATTACH FAILED for this match: {exc}")
                self.status.set("AUTO attach failed; manual Attach remains available")
            else:
                messagebox.showerror("Live attach", str(exc))
            return False

    def start_live(self, automatic: bool = False):
        if not self.live:
            if not automatic:
                messagebox.showwarning("Live triggers", "Attach to a running match first.")
            return False
        if self.live_running:
            return True
        if not automatic:
            self._auto_manual_stop_serial = None
        self._commit_trigger_details(self._shown_trigger, silent=True)
        errors = self.scenario.validate()
        if errors:
            if automatic:
                self._auto_manual_stop_serial = self._auto_match_serial
                for error in errors:
                    self.live_log(f"AUTO VALIDATION ERROR: {error}")
                self.status.set("AUTO start blocked by trigger validation; fix it or use manual testing")
            else:
                messagebox.showerror("Trigger validation", "\n".join(errors))
            return False
        for warning in self.scenario.warnings():
            self.live_log(f"PREFLIGHT WARNING: {warning}")
        try:
            self.live.begin_trigger_run()
            self.live_engine = TriggerEngine(self.scenario, self.live)
        except Exception as exc:
            if automatic:
                self._auto_manual_stop_serial = self._auto_match_serial
                self.live_log(f"AUTO START FAILED for this match: {exc}")
                self.status.set("AUTO start failed; manual Start remains available")
            else:
                messagebox.showerror("Live triggers", str(exc))
            return False
        self.live_running = True
        self._live_runtime_error_streak = 0
        self._refresh_runtime_badges()
        prefix = "AUTO START: " if automatic else ""
        self.live_log(prefix + "Live trigger engine started; non-blocking timer scheduler reset")
        for trigger in self.scenario.triggers:
            if (
                trigger.enabled
                and not trigger.preserved
                and any(action.kind in {"Game Message", "Player Chat"} for action in trigger.actions)
            ):
                self.live_log(
                    f"MESSAGE NOTE: {trigger.name} is one-shot. Check Repeat / preserve "
                    "and use Max runs 0 for unlimited repeated messages."
                )
        self._live_tick()
        return True

    def stop_live(self, manual: bool = True):
        if manual and self.auto_live_var.get() and self.live is not None:
            # A user can click Attach/Start/Stop faster than the 850 ms watcher.
            # Claim the current attached match here so AUTO cannot immediately
            # undo a deliberate manual Stop/Detach on its next poll.
            if not self._auto_running_seen:
                self._auto_match_serial += 1
                self._auto_running_seen = True
                try:
                    self._auto_last_pid = int(getattr(self.live.pm, "process_id", 0) or 0) or self._auto_last_pid
                except Exception:
                    pass
            self._auto_manual_stop_serial = self._auto_match_serial
            self.live_log(
                f"AUTO HOLD: manual Stop/Detach owns match #{self._auto_match_serial}; "
                "automatic restart is disabled until the next match starts"
            )
        if self.live_running:
            self.live_log("Live trigger engine stopped")
        self.live_running = False
        self._refresh_runtime_badges()
        if self.live:
            try:
                self.live._td_stream_restore_all_type_overrides()
            except Exception as exc:
                self.live_log(f"TD stream cleanup warning: {exc}")

    def continue_live(self):
        if not self.live_engine:
            messagebox.showwarning("Continue", "Start the live trigger engine first.")
            return
        self.live_engine.continue_execution()
        self.status.set("Trigger debugger continued")

    def step_live(self):
        if not self.live_engine:
            messagebox.showwarning("Step", "Start the live trigger engine first.")
            return
        self._ensure_console_window()
        self._set_console_visible(True)
        fired = self.live_engine.step_once()
        for item in fired:
            self.live_log("STEP FIRED: " + item)
        self.status.set("Trigger debugger stepped one cycle")

    def _live_tick(self):
        if not self.live_running:
            return
        try:
            if not self.live_engine:
                raise RuntimeError("Live engine is unavailable")
            fired = self.live_engine.cycle()
            self._live_runtime_error_streak = 0
            for item in fired:
                self.live_log("FIRED: " + item)
        except Exception as exc:
            # Runtime diagnostics belong in the console. Do not block Warcraft
            # with a modal box. A single memory-read miss can be transient, but a
            # stream of ERROR_PARTIAL_COPY / GetLastError 299 normally means the
            # match allocation or process died (as in the 1.37 native-objectives
            # crash). Halt after four consecutive copies instead of spamming the
            # same error forever; the author can restart/reattach after Warcraft.
            self._live_runtime_error_streak += 1
            text = str(exc)
            partial_copy = "GetLastError: 299" in text or "ERROR_PARTIAL_COPY" in text
            if partial_copy and self._live_runtime_error_streak >= 4:
                self.live_log(
                    "LIVE ENGINE HALTED: four consecutive ERROR_PARTIAL_COPY failures; "
                    "Warcraft/match memory is no longer stable. Restart or reattach before continuing."
                )
                self.status.set("Live trigger engine halted after repeated memory-copy failures")
                self.live_running = False
                return
            self.live_log("RUNTIME ERROR: " + text + "; engine will retry next cycle")
            self.status.set("Live trigger engine running with logged errors")
        self.after(250, self._live_tick)

    def show_trigger_diagnostics(self):
        if not self.live_engine:
            messagebox.showwarning("Trigger state", "Start the live trigger engine first.")
            return
        self._ensure_console_window()
        self._set_console_visible(True)
        self.live_log("=" * 72)
        for line in self.live_engine.diagnostic_report():
            self.live_log(line)
        self.live_log("=" * 72)

    def show_runtime_state(self):
        if not self.live:
            messagebox.showwarning("Runtime state", "Attach to a running match first.")
            return
        self._ensure_console_window()
        self._set_console_visible(True)
        self.live_log("=" * 72)
        self.live_log("MASSIVE RUNTIME STATE")
        variables = getattr(self.live, "variables", {})
        counters = getattr(self.live, "counters", {})
        timers = getattr(self.live, "countdown_timers", {})
        objectives = getattr(self.live, "objectives", {})
        follows = getattr(self.live, "_follow_locations", {})
        for name in sorted(variables): self.live_log(f"VARIABLE {name} = {variables[name]!r}")
        for name in sorted(counters): self.live_log(f"COUNTER {name} = {counters[name]}")
        for name in sorted(timers): self.live_log(f"TIMER {name} = {timers[name].value():.2f}s ({'running' if timers[name].running else 'stopped'})")
        for name in sorted(objectives):
            state = "complete" if name in getattr(self.live, "completed_objectives", set()) else "active"
            self.live_log(f"OBJECTIVE {name} [{state}] = {objectives[name]}")
        for name, selector in sorted(follows.items()): self.live_log(f"FOLLOW LOCATION {name}: {selector}")
        if not any((variables, counters, timers, objectives, follows)):
            self.live_log("No variables, counters, timers, objectives, or followed locations are active.")
        self.live_log("=" * 72)

    def list_live_units(self):
        if not self.live:
            messagebox.showwarning("Unit snapshot", "Attach to a running match first.")
            return
        try:
            self.live_log("=" * 72)
            for line in self.live.unit_report():
                self.live_log(line)
            self.live_log("=" * 72)
        except Exception as exc:
            messagebox.showerror("Unit snapshot", str(exc))

    def list_live_players(self):
        if not self.live:
            messagebox.showwarning("Player mapping", "Attach to a running match first.")
            return
        try:
            self.live_log("=" * 72)
            for line in self.live.player_mapping_report():
                self.live_log(line)
            self.live_log("=" * 72)
        except Exception as exc:
            messagebox.showerror("Player mapping", str(exc))

    def list_live_statistics(self):
        if not self.live:
            messagebox.showwarning("Combat statistics", "Attach to a running match first.")
            return
        try:
            self.live_log("=" * 72)
            for line in self.live.statistics_report():
                self.live_log(line)
            self.live_log("=" * 72)
        except Exception as exc:
            messagebox.showerror("Combat statistics", str(exc))

    # ------------------------------------------------------------- trigger details
    def selected(self) -> int | None:
        selection = self.trigger_list.curselection()
        return int(selection[0]) if selection else None

    def _select_trigger(self, index: int | None):
        self.trigger_list.selection_clear(0, "end")
        if index is not None and 0 <= index < len(self.scenario.triggers):
            self.trigger_list.selection_set(index)
            self.trigger_list.activate(index)
            self.trigger_list.see(index)

    def refresh(self, select_index: int | None = None):
        chosen = self.selected() if select_index is None else select_index
        self._loading_trigger = True
        try:
            self.trigger_list.delete(0, "end")
            for trigger in self.scenario.triggers:
                self.trigger_list.insert("end", self._trigger_row_text(trigger))
            if self.scenario.triggers:
                index = min(chosen if chosen is not None else 0, len(self.scenario.triggers) - 1)
                self._select_trigger(index)
            else:
                self._shown_trigger = None
                self._clear_trigger_editor()
            self._refresh_location_tree()
            if hasattr(self, "force_choice_box"):
                names = tuple(self.scenario.forces)
                self.force_choice_box.configure(values=names)
                if names and self.force_choice_var.get() not in names:
                    self.force_choice_var.set(names[0])
        finally:
            self._loading_trigger = False
        if self.scenario.triggers:
            self.show_trigger(force=True)

    @staticmethod
    def _trigger_row_text(trigger: Trigger) -> str:
        state = "ON" if trigger.enabled else "OFF"
        mp = "M " if trigger_multiplayer_safe(trigger) else ""
        if trigger.preserved:
            runs = "∞" if int(trigger.max_runs) == 0 else str(trigger.max_runs)
            timing = f"  ↻ {trigger.repeat_interval:g}s ×{runs}"
        elif float(trigger.start_delay) > 0:
            timing = f"  after {trigger.start_delay:g}s"
        else:
            timing = ""
        return f"[{state}] {mp}{trigger.name}{timing}"

    def _set_player_selection(self, players):
        selected = {int(player) for player in players}
        for index, var in enumerate(self.player_vars):
            var.set(index in selected)

    def _apply_force_selection(self):
        name = self.force_choice_var.get().strip()
        if not name or name not in self.scenario.forces:
            messagebox.showinfo("Apply Force", "Create or select a Force first.")
            return
        self._set_player_selection(self.scenario.forces[name])
        self.status.set(f"Applied Force {name} to the trigger's executing players")

    def show_trigger(self, force: bool = False):
        if self._loading_trigger and not force:
            return
        index = self.selected()
        if index is None:
            return
        if self._shown_trigger is not None and self._shown_trigger != index:
            self._commit_trigger_details(self._shown_trigger, silent=True)
        trigger = self.scenario.triggers[index]
        self._shown_trigger = index
        self._loading_trigger = True
        try:
            self.trigger_name_var.set(trigger.name)
            self.trigger_enabled_var.set(trigger.enabled)
            self.trigger_repeat_var.set(trigger.preserved)
            self.start_delay_var.set(f"{float(trigger.start_delay):g}")
            self.repeat_interval_var.set(f"{float(trigger.repeat_interval):g}")
            self.max_runs_var.set(str(int(trigger.max_runs)))
            self.condition_mode_var.set(str(getattr(trigger, "condition_mode", "All")))
            for i, var in enumerate(self.player_vars):
                var.set(i in trigger.players)
            self.trigger_comment.delete("1.0", "end")
            self.trigger_comment.insert("1.0", trigger.comment)
            self._toggle_repeat_fields()
            self._refresh_clause_views()
        finally:
            self._loading_trigger = False

    def _clear_trigger_editor(self):
        self.trigger_name_var.set("")
        self.trigger_enabled_var.set(False)
        self.trigger_repeat_var.set(False)
        self.start_delay_var.set("0")
        self.repeat_interval_var.set("1")
        self.max_runs_var.set("0")
        self.condition_mode_var.set("All")
        for var in self.player_vars:
            var.set(False)
        self.trigger_comment.delete("1.0", "end")
        for tree in (self.condition_tree, self.action_tree):
            for item in tree.get_children():
                tree.delete(item)
        self._toggle_repeat_fields()

    def _toggle_repeat_fields(self):
        state = "normal" if self.trigger_repeat_var.get() else "disabled"
        self.repeat_interval_entry.configure(state=state)
        self.max_runs_entry.configure(state=state)

    def _commit_trigger_details(self, index: int | None, silent: bool = False) -> bool:
        if self._loading_trigger or index is None or not 0 <= index < len(self.scenario.triggers):
            return False
        trigger = self.scenario.triggers[index]
        name = self.trigger_name_var.get().strip()
        players = [i for i, var in enumerate(self.player_vars) if var.get()]
        try:
            start_delay = float(self.start_delay_var.get().strip() or 0)
            repeat = bool(self.trigger_repeat_var.get())
            repeat_interval = float(self.repeat_interval_var.get().strip() or 1)
            max_runs = int(self.max_runs_var.get().strip() or 0)
            condition_mode = self.condition_mode_var.get().strip() or "All"
            if condition_mode not in {"All", "Any"}:
                raise ValueError("Condition logic must be All or Any")
            if start_delay < 0:
                raise ValueError("Start delay cannot be negative")
            if repeat and repeat_interval < 0.25:
                raise ValueError("Repeat interval must be at least 0.25 seconds")
            if max_runs < 0:
                raise ValueError("Max runs cannot be negative")
        except ValueError as exc:
            if not silent:
                messagebox.showerror("Trigger timing", str(exc))
            return False
        if not silent and not name:
            messagebox.showerror("Trigger", "Trigger name cannot be blank")
            return False
        if not silent and not players:
            messagebox.showerror("Trigger", "Select at least one executing player")
            return False

        trigger.name = name or trigger.name
        trigger.players = players or trigger.players
        trigger.enabled = bool(self.trigger_enabled_var.get())
        trigger.preserved = repeat
        trigger.start_delay = start_delay
        trigger.repeat_interval = repeat_interval if repeat else max(0.25, repeat_interval)
        trigger.max_runs = max_runs if repeat else 1
        trigger.condition_mode = condition_mode
        trigger.comment = self.trigger_comment.get("1.0", "end-1c")
        self._update_trigger_list_row(index)
        if not silent:
            self.status.set(f"Updated {trigger.name}")
        return True

    def _update_trigger_list_row(self, index: int):
        if not 0 <= index < len(self.scenario.triggers):
            return
        selected_rows = tuple(int(item) for item in self.trigger_list.curselection())
        self.trigger_list.delete(index)
        self.trigger_list.insert(index, self._trigger_row_text(self.scenario.triggers[index]))
        self.trigger_list.selection_clear(0, "end")
        for row in selected_rows:
            if 0 <= row < self.trigger_list.size():
                self.trigger_list.selection_set(row)

    def add_trigger(self):
        self._commit_trigger_details(self._shown_trigger, silent=True)
        self.scenario.triggers.append(
            Trigger(
                conditions=[Clause("Always")],
                actions=[Clause("Display Text", {"text": "Trigger fired"})],
                start_delay=0.0,
                repeat_interval=1.0,
                max_runs=1,
            )
        )
        self.refresh(len(self.scenario.triggers) - 1)

    def clone_trigger(self):
        index = self.selected()
        if index is None:
            return
        self._commit_trigger_details(index, silent=True)
        trigger = self.scenario.triggers[index]
        payload = json.loads(json.dumps(trigger, default=lambda obj: obj.__dict__))
        payload["name"] += " Copy"
        payload["conditions"] = [Clause(**item) for item in payload["conditions"]]
        payload["actions"] = [Clause(**item) for item in payload["actions"]]
        self.scenario.triggers.insert(index + 1, Trigger(**payload))
        self.refresh(index + 1)

    def delete_trigger(self):
        index = self.selected()
        if index is not None and messagebox.askyesno("Delete", "Delete selected trigger?"):
            self.scenario.triggers.pop(index)
            self._shown_trigger = None
            self.refresh(min(index, len(self.scenario.triggers) - 1) if self.scenario.triggers else None)

    def move_trigger(self, delta: int):
        index = self.selected()
        if index is None or not 0 <= index + delta < len(self.scenario.triggers):
            return
        self._commit_trigger_details(index, silent=True)
        self.scenario.triggers[index], self.scenario.triggers[index + delta] = (
            self.scenario.triggers[index + delta],
            self.scenario.triggers[index],
        )
        self._shown_trigger = None
        self.refresh(index + delta)

    def _trigger_drag_press(self, event):
        self._commit_trigger_details(self._shown_trigger, silent=True)
        self._trigger_drag_start = self.trigger_list.nearest(event.y) if self.trigger_list.size() else None

    def _trigger_drag_release(self, event):
        start = self._trigger_drag_start
        self._trigger_drag_start = None
        if start is None or not self.scenario.triggers:
            return
        target = self.trigger_list.nearest(event.y)
        if target == start or not (0 <= target < len(self.scenario.triggers)):
            return
        trigger = self.scenario.triggers.pop(start)
        self.scenario.triggers.insert(target, trigger)
        self._shown_trigger = None
        self.refresh(target)

    # ------------------------------------------------------------------ clauses
    def _clauses(self, mode: str) -> list[Clause]:
        index = self.selected()
        if index is None:
            return []
        return self.scenario.triggers[index].conditions if mode == "condition" else self.scenario.triggers[index].actions

    def _clause_tree(self, mode: str) -> ttk.Treeview:
        return self.condition_tree if mode == "condition" else self.action_tree

    def _selected_clause_index(self, mode: str) -> int | None:
        selection = self._clause_tree(mode).selection()
        return int(selection[0]) if selection else None

    def _refresh_clause_views(self, select_mode: str | None = None, select_index: int | None = None):
        trigger_index = self.selected()
        if trigger_index is None:
            return
        trigger = self.scenario.triggers[trigger_index]
        executing_player = trigger.players[0] if trigger.players else 0
        for mode, tree, clauses in (
            ("condition", self.condition_tree, trigger.conditions),
            ("action", self.action_tree, trigger.actions),
        ):
            for item in tree.get_children():
                tree.delete(item)
            for index, clause in enumerate(clauses):
                prefix = "IF" if mode == "condition" else "DO"
                shown_kind = display_kind(mode, clause.kind)
                text = f"  {index + 1:02d}   {prefix} {shown_kind}  —  {clause_summary(clause, executing_player)}"
                tree.insert("", "end", iid=str(index), text=text)
            if mode == select_mode and select_index is not None and 0 <= select_index < len(clauses):
                tree.selection_set(str(select_index))
                tree.focus(str(select_index))
                tree.see(str(select_index))

    def add_clause(self, mode: str, preset_kind: str | None = None, insert_at: int | None = None):
        if self.selected() is None:
            messagebox.showinfo("Trigger builder", "Create or select a trigger first.")
            return
        preview = self._preview_sound if mode == "action" else None
        clause = edit_clause(self, self.scenario, mode, live_preview=preview, initial_kind=preset_kind)
        if clause is None:
            return
        clauses = self._clauses(mode)
        position = len(clauses) if insert_at is None else max(0, min(insert_at, len(clauses)))
        clauses.insert(position, clause)
        self._refresh_clause_views(mode, position)
        self._show_kind_help(clause.kind, clause_summary(clause))
        if mode == "action" and clause.kind in {"Game Message", "Player Chat"}:
            trigger_index = self.selected()
            trigger = self.scenario.triggers[trigger_index] if trigger_index is not None else None
            if trigger is not None and not trigger.preserved:
                self.status.set(
                    f"Added {clause.kind}. This trigger is currently one-shot; "
                    "check Repeat / preserve to send it again."
                )

    def edit_selected_clause(self, mode: str):
        index = self._selected_clause_index(mode)
        if index is None:
            return
        clauses = self._clauses(mode)
        preview = self._preview_sound if mode == "action" else None
        replacement = edit_clause(self, self.scenario, mode, clauses[index], live_preview=preview)
        if replacement is None:
            return
        clauses[index] = replacement
        self._refresh_clause_views(mode, index)
        self._show_kind_help(replacement.kind, clause_summary(replacement))

    def clone_clause(self, mode: str):
        index = self._selected_clause_index(mode)
        if index is None:
            return
        clauses = self._clauses(mode)
        source = clauses[index]
        clauses.insert(index + 1, Clause(source.kind, json.loads(json.dumps(source.args))))
        self._refresh_clause_views(mode, index + 1)

    def copy_clause(self, mode: str):
        index = self._selected_clause_index(mode)
        if index is None:
            return
        source = self._clauses(mode)[index]
        self._clipboard_clause = Clause(source.kind, json.loads(json.dumps(source.args)))
        self.status.set(f"Copied {source.kind}")

    def paste_clause(self, mode: str):
        if self._clipboard_clause is None:
            messagebox.showinfo("Paste", "Copy a condition or action first.")
            return
        allowed = CONDITIONS if mode == "condition" else ACTIONS
        if self._clipboard_clause.kind not in allowed:
            messagebox.showerror("Paste", f"{self._clipboard_clause.kind} is not a valid {mode}.")
            return
        clauses = self._clauses(mode)
        index = self._selected_clause_index(mode)
        insert_at = len(clauses) if index is None else index + 1
        clauses.insert(insert_at, Clause(self._clipboard_clause.kind, json.loads(json.dumps(self._clipboard_clause.args))))
        self._refresh_clause_views(mode, insert_at)

    def delete_clause(self, mode: str):
        index = self._selected_clause_index(mode)
        if index is None:
            return
        clauses = self._clauses(mode)
        kind = clauses[index].kind
        if messagebox.askyesno("Delete", f"Delete {kind}?"):
            clauses.pop(index)
            self._refresh_clause_views(mode, min(index, len(clauses) - 1) if clauses else None)

    def move_clause(self, mode: str, delta: int):
        index = self._selected_clause_index(mode)
        clauses = self._clauses(mode)
        if index is None or not 0 <= index + delta < len(clauses):
            return
        clauses[index], clauses[index + delta] = clauses[index + delta], clauses[index]
        self._refresh_clause_views(mode, index + delta)

    def _clause_drag_press(self, mode: str, event):
        tree = self._clause_tree(mode)
        row = tree.identify_row(event.y)
        self._clause_drag_start[mode] = int(row) if row else None
        if row:
            tree.selection_set(row)

    def _clause_drag_motion(self, mode: str, event):
        row = self._clause_tree(mode).identify_row(event.y)
        if row:
            self._clause_tree(mode).selection_set(row)

    def _clause_drag_release(self, mode: str, event):
        start = self._clause_drag_start.get(mode)
        self._clause_drag_start[mode] = None
        if start is None:
            return
        tree = self._clause_tree(mode)
        row = tree.identify_row(event.y)
        if not row:
            return
        target = int(row)
        clauses = self._clauses(mode)
        if target == start or not (0 <= start < len(clauses) and 0 <= target < len(clauses)):
            return
        clause = clauses.pop(start)
        clauses.insert(target, clause)
        self._refresh_clause_views(mode, target)

    def _preview_sound(self, args: dict):
        if not self.live:
            raise RuntimeError("Attach to a running Warcraft II match before previewing a sound")
        trigger_index = self.selected()
        player = 0
        if trigger_index is not None and self.scenario.triggers[trigger_index].players:
            player = self.scenario.triggers[trigger_index].players[0]
        self.live.action("Play Sound", args, player)
        self.status.set("Played native sound preview")

    # ------------------------------------------------------------ files/dialogs
    def open_pud(self):
        path = filedialog.askopenfilename(filetypes=[("Warcraft II maps", "*.pud"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.pud = PudMap.read(path)
        except Exception as exc:
            messagebox.showerror("PUD error", str(exc))
            return
        self.scenario.map_file = Path(path).name
        self.status.set(f"Opened {Path(path).name}")
        self.show_map_info()

    def open_sidecar(self):
        paths = filedialog.askopenfilenames(filetypes=[("War2 triggers", "*.w2trig.json"), ("JSON", "*.json")])
        if not paths:
            return
        loaded: list[Path] = []
        errors: list[str] = []
        for raw in paths:
            path = Path(raw).resolve()
            if path in self._open_trigger_files:
                loaded.append(path)
                continue
            try:
                scenario = Scenario.load(path)
                self._open_trigger_files[path] = scenario
                self._trigger_file_order.append(path)
                loaded.append(path)
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")
        if loaded:
            # Activate the last file selected in the picker. All the other files
            # remain open in Screen -> Trigger Files.
            if self.current is None:
                self.current = None
            self._switch_trigger_file(loaded[-1])
            if len(loaded) > 1:
                self.status.set(f"Opened {len(loaded)} trigger files; active: {loaded[-1].name}")
        self._refresh_trigger_files_menu()
        if errors:
            messagebox.showerror("Trigger error", "Could not open:\n\n" + "\n".join(errors))

    def save(self):
        if not self._commit_trigger_details(self._shown_trigger, silent=False) and self._shown_trigger is not None:
            return
        if not self.current:
            return self.save_as()
        try:
            self.scenario.save(self.current)
            self._remember_current_trigger_file()
            self._refresh_trigger_files_menu()
            self._update_window_title()
            self.status.set(f"Saved {self.current.name}")
        except Exception as exc:
            messagebox.showerror("Save error", str(exc))

    def save_as(self):
        path = filedialog.asksaveasfilename(defaultextension=".w2trig.json", filetypes=[("War2 triggers", "*.w2trig.json")])
        if not path:
            return
        old = self.current.resolve() if self.current else None
        new = Path(path).resolve()
        if old is not None and old != new:
            self._open_trigger_files.pop(old, None)
            self._trigger_file_order = [new if item == old else item for item in self._trigger_file_order]
        self.current = new
        self._remember_current_trigger_file()
        self.save()

    def validate(self):
        self._commit_trigger_details(self._shown_trigger, silent=True)
        errors = self.scenario.validate()
        warnings = self.scenario.warnings()
        if errors:
            messagebox.showerror("Validation", "\n".join(errors))
        elif warnings:
            messagebox.showwarning("Validation", "No blocking errors.\n\nWarnings:\n" + "\n".join(warnings))
        else:
            messagebox.showinfo("Validation", "No errors or semantic warnings found.")

    def show_map_info(self):
        window = tk.Toplevel(self)
        window.title("Map information")
        window.geometry("760x560")
        window.configure(bg=BG)
        text = self._dark_text(window, font=("Consolas", 10), wrap="word")
        text.pack(fill="both", expand=True, padx=10, pady=10)
        if self.pud:
            content = self.pud.summary()
        elif self.scenario.map_file:
            content = f"Trigger sidecar map: {self.scenario.map_file}\n\nOpen the PUD to inspect its chunks and dimensions."
        else:
            content = "No PUD is loaded. Use Open PUD to read map metadata and dimensions."
        text.insert("1.0", content)
        text.configure(state="disabled")

    def show_locations(self):
        if self._location_window and self._location_window.winfo_exists():
            self._location_window.lift()
            return
        window = tk.Toplevel(self)
        self._location_window = window
        window.title("Trigger locations")
        window.geometry("820x560")
        window.minsize(680, 430)
        window.configure(bg=BG)
        window.protocol("WM_DELETE_WINDOW", self._close_locations)

        top = ttk.LabelFrame(window, text="Add rectangular location")
        top.pack(fill="x", padx=10, pady=10)
        self.loc_vars = [tk.StringVar(value=x) for x in ("Location 1", "0", "0", "31", "31")]
        for column, (label, var) in enumerate(zip(("Name", "Left", "Top", "Right", "Bottom"), self.loc_vars)):
            ttk.Label(top, text=label).grid(row=0, column=column, sticky="w", padx=5, pady=(7, 2))
            ttk.Entry(top, textvariable=var, width=20 if label == "Name" else 9).grid(row=1, column=column, sticky="ew", padx=5, pady=(0, 8))
        self._button(top, "Add", self.add_location, "Add the rectangle and make it available in location dropdowns.").grid(row=1, column=5, padx=6)
        self._button(top, "Delete", self.delete_location, "Delete the selected location.").grid(row=1, column=6, padx=6)
        top.columnconfigure(0, weight=1)

        box = ttk.Frame(window)
        box.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.loc_tree = ttk.Treeview(box, columns=("left", "top", "right", "bottom"), show="tree headings", style="Location.Treeview")
        self.loc_tree.heading("#0", text="Name")
        self.loc_tree.column("#0", width=250)
        for column in ("left", "top", "right", "bottom"):
            self.loc_tree.heading(column, text=column.title())
            self.loc_tree.column(column, width=100, anchor="center")
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.loc_tree.yview)
        self.loc_tree.configure(yscrollcommand=scroll.set)
        self.loc_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._refresh_location_tree()

    def _close_locations(self):
        if self._location_window:
            self._location_window.destroy()
        self._location_window = None
        self.loc_tree = None

    def _refresh_location_tree(self):
        if not self.loc_tree or not self.loc_tree.winfo_exists():
            return
        for item in self.loc_tree.get_children():
            self.loc_tree.delete(item)
        for loc in self.scenario.locations:
            self.loc_tree.insert("", "end", text=loc.name, values=(loc.left, loc.top, loc.right, loc.bottom))

    def add_location(self):
        try:
            location = Location(self.loc_vars[0].get().strip(), *[int(var.get()) for var in self.loc_vars[1:]])
            location.normalize()
            if not location.name:
                raise ValueError("Location name cannot be blank")
            if any(existing.name.casefold() == location.name.casefold() for existing in self.scenario.locations):
                raise ValueError(f"Location already exists: {location.name}")
            self.scenario.locations.append(location)
            self._refresh_location_tree()
            self.status.set(f"Added location {location.name}")
        except ValueError as exc:
            messagebox.showerror("Location", str(exc))

    def delete_location(self):
        if not self.loc_tree:
            return
        selected = self.loc_tree.selection()
        if not selected:
            return
        name = self.loc_tree.item(selected[0], "text")
        if messagebox.askyesno("Delete location", f"Delete location {name!r}? Existing clauses keep the name until edited."):
            self.scenario.locations = [loc for loc in self.scenario.locations if loc.name != name]
            self._refresh_location_tree()

    def show_forces(self):
        if not self.scenario.forces:
            self.scenario.forces = {
                "Force 1": [0],
                "Force 2": [1],
                "Force 3": [2],
                "Force 4": [3],
            }
        window = tk.Toplevel(self)
        window.title("StarCraft-style Forces")
        window.geometry("700x470")
        window.configure(bg=BG)
        window.transient(self)

        left = ttk.LabelFrame(window, text="Forces")
        left.pack(side="left", fill="y", padx=(10, 5), pady=10)
        force_list = tk.Listbox(left, width=24, bg=PANEL_2, fg=TEXT, selectbackground=SELECT_2, exportselection=False)
        force_list.pack(fill="both", expand=True, padx=6, pady=6)

        right = ttk.LabelFrame(window, text="Force members")
        right.pack(side="left", fill="both", expand=True, padx=(5, 10), pady=10)
        name_var = tk.StringVar()
        ttk.Label(right, text="Name").grid(row=0, column=0, sticky="w", padx=8, pady=8)
        ttk.Entry(right, textvariable=name_var).grid(row=0, column=1, columnspan=3, sticky="ew", padx=8, pady=8)
        vars_ = [tk.BooleanVar() for _ in range(16)]
        for player, var in enumerate(vars_):
            self._dark_toggle(right, f"Player {player + 1}", var, width=9).grid(row=1 + player // 4, column=player % 4, sticky="ew", padx=4, pady=4)
        for col in range(4): right.columnconfigure(col, weight=1)

        def reload_list(select_name=None):
            force_list.delete(0, "end")
            names = list(self.scenario.forces)
            for item in names: force_list.insert("end", item)
            if names:
                index = names.index(select_name) if select_name in names else 0
                force_list.selection_set(index); force_list.activate(index)
                load_selected()
            if hasattr(self, "force_choice_box"):
                self.force_choice_box.configure(values=tuple(names))

        def load_selected(_event=None):
            selected = force_list.curselection()
            if not selected: return
            name = force_list.get(selected[0])
            name_var.set(name)
            members = set(self.scenario.forces.get(name, []))
            for player, var in enumerate(vars_): var.set(player in members)

        def save_force():
            selected = force_list.curselection()
            old_name = force_list.get(selected[0]) if selected else None
            name = name_var.get().strip()
            members = [player for player, var in enumerate(vars_) if var.get()]
            if not name:
                messagebox.showerror("Force", "Force name cannot be blank.", parent=window); return
            if not members:
                messagebox.showerror("Force", "Select at least one player.", parent=window); return
            if old_name and old_name != name: self.scenario.forces.pop(old_name, None)
            self.scenario.forces[name] = members
            reload_list(name)
            self.status.set(f"Saved Force {name}")

        def new_force():
            force_list.selection_clear(0, "end")
            base = "Force"; number = 1
            while f"{base} {number}" in self.scenario.forces: number += 1
            name_var.set(f"{base} {number}")
            for var in vars_: var.set(False)

        def delete_force():
            selected = force_list.curselection()
            if not selected: return
            name = force_list.get(selected[0])
            if messagebox.askyesno("Delete Force", f"Delete {name}?", parent=window):
                self.scenario.forces.pop(name, None); reload_list()

        force_list.bind("<<ListboxSelect>>", load_selected)
        buttons = ttk.Frame(right)
        buttons.grid(row=6, column=0, columnspan=4, sticky="ew", padx=8, pady=12)
        self._button(buttons, "New", new_force).pack(side="left", padx=3)
        self._button(buttons, "Delete", delete_force).pack(side="left", padx=3)
        self._button(buttons, "Save", save_force, style="Accent.TButton").pack(side="right", padx=3)
        reload_list()

    def show_project_state(self):
        """Edit portable scenario-level state without requiring raw sidecar edits."""
        window = tk.Toplevel(self)
        window.title("Project State — Variables, Timers, Objectives")
        window.geometry("820x650")
        window.configure(bg=BG)
        window.transient(self)

        ttk.Label(
            window,
            text=(
                "These values are copied into the live runtime each time Start is pressed. "
                "Use JSON objects: variables may contain numbers/text/booleans, timers are seconds, "
                "and objectives map names to display text."
            ),
            foreground=MUTED,
            wraplength=780,
            justify="left",
        ).pack(fill="x", padx=12, pady=(12, 8))

        notebook = ttk.Notebook(window)
        notebook.pack(fill="both", expand=True, padx=10, pady=6)
        editors: dict[str, tk.Text] = {}
        payloads = {
            "Variables": self.scenario.variables,
            "Timers": self.scenario.timers,
            "Objectives": self.scenario.objectives,
        }
        for label, payload in payloads.items():
            frame = ttk.Frame(notebook)
            notebook.add(frame, text=label)
            text = self._dark_text(frame, font=("Consolas", 11), wrap="none")
            yscroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
            xscroll = ttk.Scrollbar(frame, orient="horizontal", command=text.xview)
            text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
            text.grid(row=0, column=0, sticky="nsew")
            yscroll.grid(row=0, column=1, sticky="ns")
            xscroll.grid(row=1, column=0, sticky="ew")
            frame.rowconfigure(0, weight=1)
            frame.columnconfigure(0, weight=1)
            text.insert("1.0", json.dumps(payload, indent=2))
            editors[label] = text

        def save_state():
            try:
                raw_variables = json.loads(editors["Variables"].get("1.0", "end").strip() or "{}")
                raw_timers = json.loads(editors["Timers"].get("1.0", "end").strip() or "{}")
                raw_objectives = json.loads(editors["Objectives"].get("1.0", "end").strip() or "{}")
                if not isinstance(raw_variables, dict) or not isinstance(raw_timers, dict) or not isinstance(raw_objectives, dict):
                    raise ValueError("Each tab must contain one JSON object.")
                timers = {str(name): float(seconds) for name, seconds in raw_timers.items()}
                if any(seconds < 0 for seconds in timers.values()):
                    raise ValueError("Timer values cannot be negative.")
                self.scenario.variables = {str(name): value for name, value in raw_variables.items()}
                self.scenario.timers = timers
                self.scenario.objectives = {str(name): str(value) for name, value in raw_objectives.items()}
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                messagebox.showerror("Project State", str(exc), parent=window)
                return
            self.status.set(
                f"Saved {len(self.scenario.variables)} variable(s), "
                f"{len(self.scenario.timers)} timer(s), and "
                f"{len(self.scenario.objectives)} objective(s)"
            )
            window.destroy()

        buttons = ttk.Frame(window)
        buttons.pack(fill="x", padx=10, pady=(4, 10))
        self._button(buttons, "Cancel", window.destroy).pack(side="right", padx=3)
        self._button(buttons, "Save Project State", save_state, style="Accent.TButton").pack(side="right", padx=3)

    def show_advanced_json(self):
        index = self.selected()
        if index is None:
            messagebox.showinfo("Advanced JSON", "Create or select a trigger first.")
            return
        self._commit_trigger_details(index, silent=True)
        if self._json_window and self._json_window.winfo_exists():
            self._json_window.destroy()
        window = tk.Toplevel(self)
        self._json_window = window
        window.title(f"Advanced JSON — {self.scenario.triggers[index].name}")
        window.geometry("820x700")
        window.configure(bg=BG)
        text = self._dark_text(window, font=("Consolas", 10), wrap="none")
        yscroll = ttk.Scrollbar(window, orient="vertical", command=text.yview)
        xscroll = ttk.Scrollbar(window, orient="horizontal", command=text.xview)
        text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        text.grid(row=0, column=0, sticky="nsew", padx=(10, 0), pady=(10, 0))
        yscroll.grid(row=0, column=1, sticky="ns", padx=(0, 10), pady=(10, 0))
        xscroll.grid(row=1, column=0, sticky="ew", padx=(10, 0))
        window.rowconfigure(0, weight=1)
        window.columnconfigure(0, weight=1)
        text.insert("1.0", json.dumps(self.scenario.triggers[index], default=lambda obj: obj.__dict__, indent=2))
        buttons = ttk.Frame(window)
        buttons.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=10)
        ttk.Label(buttons, text="Players are zero-based in JSON. Visual fields remain the safer default.", foreground=MUTED).pack(side="left")
        self._button(buttons, "Apply JSON", lambda: self.apply_trigger_json(index, text, window), "Replace the selected trigger with this JSON.").pack(side="right")

    def apply_trigger_json(self, index: int, text: tk.Text, window: tk.Toplevel):
        try:
            data = json.loads(text.get("1.0", "end"))
            preserved = bool(data.get("preserved", False))
            trigger = Trigger(
                name=data.get("name", "New Trigger"),
                players=[int(x) for x in data.get("players", [0])],
                conditions=[Clause(**item) for item in data.get("conditions", [])],
                actions=[Clause(**item) for item in data.get("actions", [])],
                preserved=preserved,
                enabled=bool(data.get("enabled", True)),
                comment=data.get("comment", ""),
                condition_mode=str(data.get("condition_mode", "All")),
                start_delay=float(data.get("start_delay", 0)),
                repeat_interval=float(data.get("repeat_interval", 1)),
                max_runs=int(data.get("max_runs", 0 if preserved else 1)),
            )
            self.scenario.triggers[index] = trigger
            self._shown_trigger = None
            self.refresh(index)
            self.status.set("Applied advanced trigger JSON")
            window.destroy()
        except Exception as exc:
            messagebox.showerror("Invalid trigger JSON", str(exc), parent=window)


if __name__ == "__main__":
    App().mainloop()
