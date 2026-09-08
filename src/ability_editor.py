from __future__ import annotations

"""Visual authoring dialogs for Trigger Studio's Custom Ability Engine."""

from copy import deepcopy
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from ability_defs import (
    ABILITY_EFFECT_FIELDS, ABILITY_EFFECTS, ABILITY_TARGETS,
    new_ability, new_effect, normalize_ability, normalize_effect,
    validate_ability_definition, validate_abilities,
)


BG = "#171a1f"
PANEL = "#20242b"
PANEL_2 = "#15181d"
TEXT = "#e1e5e9"
MUTED = "#9aa5af"
ACCENT = "#4f84a8"


def _center(window: tk.Toplevel, parent: tk.Misc) -> None:
    window.update_idletasks()
    x = max(0, parent.winfo_rootx() + (parent.winfo_width() - window.winfo_width()) // 2)
    y = max(0, parent.winfo_rooty() + (parent.winfo_height() - window.winfo_height()) // 2)
    window.geometry(f"+{x}+{y}")


class EffectEditorDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, effect: dict[str, Any] | None = None):
        super().__init__(parent)
        self.title("Ability Effect")
        self.configure(bg=BG)
        self.resizable(False, False)
        self.result: dict[str, Any] | None = None
        self._source = normalize_effect(effect or new_effect())
        self.kind_var = tk.StringVar(value=str(self._source.get("kind", ABILITY_EFFECTS[0])))
        self._vars: dict[str, tk.Variable] = {}

        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Effect type").grid(row=0, column=0, sticky="w", pady=(0, 8))
        kind = ttk.Combobox(outer, textvariable=self.kind_var, values=ABILITY_EFFECTS, state="readonly", width=31)
        kind.grid(row=0, column=1, sticky="ew", pady=(0, 8))
        kind.bind("<<ComboboxSelected>>", lambda _event: self._build_fields())
        self.fields = ttk.LabelFrame(outer, text="Effect parameters", padding=10)
        self.fields.grid(row=1, column=0, columnspan=2, sticky="nsew")
        buttons = ttk.Frame(outer)
        buttons.grid(row=2, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="Save Effect", style="Accent.TButton", command=self._accept).pack(side="right")
        outer.columnconfigure(1, weight=1)
        self._build_fields()
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.transient(parent); self.grab_set(); _center(self, parent)

    def _build_fields(self) -> None:
        for child in self.fields.winfo_children(): child.destroy()
        old = dict(self._vars); self._vars = {}
        kind = self.kind_var.get()
        current = self._source if self._source.get("kind") == kind else new_effect(kind)
        for row, spec in enumerate(ABILITY_EFFECT_FIELDS.get(kind, ())):
            key = str(spec["key"]); value = current.get(key, spec.get("default"))
            ttk.Label(self.fields, text=str(spec["label"])).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
            if spec["kind"] == "bool":
                var: tk.Variable = tk.BooleanVar(value=bool(value)); widget = ttk.Checkbutton(self.fields, variable=var)
            else:
                var = tk.StringVar(value=str(value))
                if spec["kind"] == "choice": widget = ttk.Combobox(self.fields, textvariable=var, values=spec.get("choices", ()), state="readonly", width=33)
                else: widget = ttk.Entry(self.fields, textvariable=var, width=36)
            widget.grid(row=row, column=1, sticky="ew", pady=5)
            self._vars[key] = var
        self.fields.columnconfigure(1, weight=1)
        if not ABILITY_EFFECT_FIELDS.get(kind):
            ttk.Label(self.fields, text="This effect uses the cast target and needs no extra parameters.", foreground=MUTED).grid(row=0, column=0, padx=4, pady=12)

    def _accept(self) -> None:
        raw: dict[str, Any] = {"kind": self.kind_var.get()}
        for spec in ABILITY_EFFECT_FIELDS.get(self.kind_var.get(), ()):
            value = self._vars[str(spec["key"])].get()
            try:
                if spec["kind"] == "int": value = int(str(value), 0)
                elif spec["kind"] == "float": value = float(value)
                elif spec["kind"] == "bool": value = bool(value)
            except (TypeError, ValueError):
                messagebox.showerror("Invalid effect", f"{spec['label']} must be {spec['kind']}.", parent=self); return
            raw[str(spec["key"])] = value
        probe = new_ability(); probe["effects"] = [raw]
        errors = [line for line in validate_ability_definition(probe) if "effect 1" in line]
        if errors:
            messagebox.showerror("Invalid effect", "\n".join(errors), parent=self); return
        self.result = normalize_effect(raw); self.destroy()


class AbilityEditDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, ability: dict[str, Any]):
        super().__init__(parent)
        self.title("Custom Ability")
        self.geometry("860x760")
        self.minsize(760, 650)
        self.configure(bg=BG)
        self.result: dict[str, Any] | None = None
        self._source = normalize_ability(ability)
        self.effects = deepcopy(self._source.get("effects", []))
        self.vars: dict[str, tk.Variable] = {}

        outer = ttk.Frame(self, padding=14); outer.pack(fill="both", expand=True)
        title = ttk.Frame(outer); title.pack(fill="x", pady=(0, 10))
        ttk.Label(title, text="CUSTOM ABILITY", font=("Segoe UI Semibold", 14)).pack(side="left")
        ttk.Label(title, text="Definition, costs, targeting, effects, and AI policy", foreground=MUTED).pack(side="left", padx=14)
        notebook = ttk.Notebook(outer); notebook.pack(fill="both", expand=True)
        general = ttk.Frame(notebook, padding=14); effects_page = ttk.Frame(notebook, padding=10)
        notebook.add(general, text="Definition"); notebook.add(effects_page, text="Effects")
        self._build_general(general); self._build_effects(effects_page)
        buttons = ttk.Frame(outer); buttons.pack(fill="x", pady=(12, 0))
        ttk.Label(buttons, text="Unlimited charges = 0. Empty caster IDs = any unit.", foreground=MUTED).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(buttons, text="Save Ability", style="Accent.TButton", command=self._accept).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.transient(parent); self.grab_set(); _center(self, parent)

    def _entry(self, parent: ttk.Frame, row: int, key: str, label: str, *, width: int = 28) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5)
        var = tk.StringVar(value=str(self._source.get(key, ""))); self.vars[key] = var
        ttk.Entry(parent, textvariable=var, width=width).grid(row=row, column=1, sticky="ew", pady=5)

    def _build_general(self, page: ttk.Frame) -> None:
        left = ttk.LabelFrame(page, text="Identity & input", padding=10); right = ttk.LabelFrame(page, text="Rules & economy", padding=10)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 7)); right.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self._entry(left, 0, "id", "Stable ID")
        self._entry(left, 1, "name", "Display name")
        self._entry(left, 2, "description", "Description")
        self._entry(left, 3, "icon", "Icon/asset note")
        self._entry(left, 4, "hotkey", "Local hotkey")
        ttk.Label(left, text="Target mode").grid(row=5, column=0, sticky="w", padx=(0, 12), pady=5)
        self.vars["target"] = tk.StringVar(value=str(self._source.get("target", "Enemy Unit")))
        ttk.Combobox(left, textvariable=self.vars["target"], values=ABILITY_TARGETS, state="readonly").grid(row=5, column=1, sticky="ew", pady=5)
        self._entry(left, 6, "range", "Range (tiles)")
        self._entry(left, 7, "caster_types", "Caster unit IDs")
        self.vars["caster_types"].set(", ".join(str(value) for value in self._source.get("caster_types", [])))

        for row, (key, label) in enumerate((
            ("mana_cost", "Mana cost"), ("gold_cost", "Gold cost"), ("lumber_cost", "Lumber cost"),
            ("oil_cost", "Oil cost"), ("cooldown", "Cooldown (seconds)"), ("max_charges", "Maximum charges"),
            ("ai_priority", "AI priority"),
        )): self._entry(right, row, key, label)
        self.vars["enabled"] = tk.BooleanVar(value=bool(self._source.get("enabled", True)))
        self.vars["ai_enabled"] = tk.BooleanVar(value=bool(self._source.get("ai_enabled", False)))
        ttk.Checkbutton(right, text="Enabled when triggers start", variable=self.vars["enabled"]).grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 3))
        ttk.Checkbutton(right, text="AI may evaluate this ability", variable=self.vars["ai_enabled"]).grid(row=8, column=0, columnspan=2, sticky="w", pady=3)
        note = "Hotkeys and ability AI are local/wall-clock features. They are intentionally not marked multiplayer-safe."
        ttk.Label(page, text=note, foreground=MUTED, wraplength=750, justify="left").grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        left.columnconfigure(1, weight=1); right.columnconfigure(1, weight=1); page.columnconfigure(0, weight=1); page.columnconfigure(1, weight=1); page.rowconfigure(0, weight=1)

    def _build_effects(self, page: ttk.Frame) -> None:
        toolbar = ttk.Frame(page); toolbar.pack(fill="x", pady=(0, 8))
        ttk.Label(toolbar, text="Effects execute top-to-bottom as one resumable cast.", foreground=MUTED).pack(side="left")
        for text, command in (("Add", self._add_effect), ("Edit", self._edit_effect), ("Duplicate", self._duplicate_effect), ("Delete", self._delete_effect), ("Up", lambda: self._move_effect(-1)), ("Down", lambda: self._move_effect(1))):
            ttk.Button(toolbar, text=text, command=command).pack(side="right", padx=(4, 0))
        box = ttk.Frame(page); box.pack(fill="both", expand=True)
        self.effect_tree = ttk.Treeview(box, columns=("type", "details"), show="headings", selectmode="browse")
        self.effect_tree.heading("type", text="Effect"); self.effect_tree.heading("details", text="Parameters")
        self.effect_tree.column("type", width=180, stretch=False); self.effect_tree.column("details", width=560)
        scroll = ttk.Scrollbar(box, orient="vertical", command=self.effect_tree.yview); self.effect_tree.configure(yscrollcommand=scroll.set)
        self.effect_tree.pack(side="left", fill="both", expand=True); scroll.pack(side="right", fill="y")
        self.effect_tree.bind("<Double-1>", lambda _event: self._edit_effect())
        self._refresh_effects()

    def _effect_index(self) -> int | None:
        selected = self.effect_tree.selection(); return int(selected[0]) if selected else None

    @staticmethod
    def _effect_summary(effect: dict[str, Any]) -> str:
        return ", ".join(f"{key.replace('_',' ')}={value}" for key, value in effect.items() if key != "kind") or "Uses cast target"

    def _refresh_effects(self, select: int | None = None) -> None:
        for item in self.effect_tree.get_children(): self.effect_tree.delete(item)
        for index, effect in enumerate(self.effects): self.effect_tree.insert("", "end", iid=str(index), values=(effect.get("kind", ""), self._effect_summary(effect)))
        if select is not None and 0 <= select < len(self.effects): self.effect_tree.selection_set(str(select)); self.effect_tree.focus(str(select))

    def _add_effect(self) -> None:
        dialog = EffectEditorDialog(self, new_effect()); self.wait_window(dialog)
        if dialog.result is not None: self.effects.append(dialog.result); self._refresh_effects(len(self.effects)-1)

    def _edit_effect(self) -> None:
        index = self._effect_index()
        if index is None: return
        dialog = EffectEditorDialog(self, self.effects[index]); self.wait_window(dialog)
        if dialog.result is not None: self.effects[index] = dialog.result; self._refresh_effects(index)

    def _duplicate_effect(self) -> None:
        index = self._effect_index()
        if index is None: return
        self.effects.insert(index+1, deepcopy(self.effects[index])); self._refresh_effects(index+1)

    def _delete_effect(self) -> None:
        index = self._effect_index()
        if index is None: return
        self.effects.pop(index); self._refresh_effects(min(index, len(self.effects)-1))

    def _move_effect(self, delta: int) -> None:
        index = self._effect_index()
        if index is None or not 0 <= index+delta < len(self.effects): return
        self.effects[index], self.effects[index+delta] = self.effects[index+delta], self.effects[index]; self._refresh_effects(index+delta)

    def _accept(self) -> None:
        raw: dict[str, Any] = {key: var.get() for key, var in self.vars.items()}
        for key in ("range", "mana_cost", "gold_cost", "lumber_cost", "oil_cost", "max_charges", "ai_priority"):
            try: raw[key] = int(str(raw[key]), 0)
            except (TypeError, ValueError): pass
        try: raw["cooldown"] = float(raw["cooldown"])
        except (TypeError, ValueError): pass
        raw["caster_types"] = [part.strip() for part in str(raw.get("caster_types", "")).replace(";", ",").split(",") if part.strip()]
        raw["effects"] = deepcopy(self.effects)
        errors = validate_ability_definition(raw)
        if errors: messagebox.showerror("Invalid ability", "\n".join(errors), parent=self); return
        self.result = normalize_ability(raw); self.destroy()


class AbilityManagerDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, scenario: Any, on_change: Callable[[], None] | None = None):
        super().__init__(parent)
        self.title("Custom Ability Engine")
        self.geometry("1120x680")
        self.minsize(900, 520)
        self.configure(bg=BG)
        self.scenario = scenario
        self.on_change = on_change

        outer = ttk.Frame(self, padding=12); outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer); header.pack(fill="x", pady=(0, 10))
        ttk.Label(header, text="CUSTOM ABILITY ENGINE", font=("Segoe UI Semibold", 15)).pack(side="left")
        ttk.Label(header, text="Compose target rules, costs, cooldowns, effects, hotkeys, and AI casts", foreground=MUTED).pack(side="left", padx=16)
        toolbar = ttk.Frame(outer); toolbar.pack(fill="x", pady=(0, 8))
        for text, command in (("Add Ability", self._add), ("Edit", self._edit), ("Duplicate", self._duplicate), ("Delete", self._delete), ("Import JSON", self._import), ("Export JSON", self._export)):
            ttk.Button(toolbar, text=text, command=command).pack(side="left", padx=(0, 5))
        ttk.Button(toolbar, text="Validate All", command=self._validate).pack(side="right")
        box = ttk.Frame(outer); box.pack(fill="both", expand=True)
        columns = ("id", "name", "target", "hotkey", "cost", "cooldown", "charges", "effects", "ai")
        self.tree = ttk.Treeview(box, columns=columns, show="headings", selectmode="browse")
        headings = {"id":"ID", "name":"Name", "target":"Target", "hotkey":"Key", "cost":"Costs", "cooldown":"Cooldown", "charges":"Charges", "effects":"Effects", "ai":"AI"}
        widths = {"id":130,"name":180,"target":100,"hotkey":55,"cost":180,"cooldown":75,"charges":65,"effects":60,"ai":45}
        for key in columns: self.tree.heading(key, text=headings[key]); self.tree.column(key, width=widths[key], stretch=key in {"name","cost"})
        yscroll = ttk.Scrollbar(box, orient="vertical", command=self.tree.yview); xscroll = ttk.Scrollbar(box, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew"); yscroll.grid(row=0, column=1, sticky="ns"); xscroll.grid(row=1, column=0, sticky="ew")
        box.rowconfigure(0, weight=1); box.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", lambda _event: self._edit())
        footer = ttk.Frame(outer); footer.pack(fill="x", pady=(10, 0))
        self.summary_var = tk.StringVar(); ttk.Label(footer, textvariable=self.summary_var, foreground=MUTED).pack(side="left")
        ttk.Button(footer, text="Close", command=self.destroy).pack(side="right")
        self._refresh(); self.protocol("WM_DELETE_WINDOW", self.destroy)

    def _abilities(self) -> list[dict[str, Any]]: return self.scenario.abilities
    def _selected(self) -> int | None:
        selected = self.tree.selection(); return int(selected[0]) if selected else None
    def _changed(self) -> None:
        if self.on_change: self.on_change()

    def _refresh(self, select: int | None = None) -> None:
        for item in self.tree.get_children(): self.tree.delete(item)
        for index, raw in enumerate(self._abilities()):
            ability = normalize_ability(raw, index+1); costs = []
            for label, key in (("M","mana_cost"),("G","gold_cost"),("L","lumber_cost"),("O","oil_cost")):
                if int(ability.get(key, 0)): costs.append(f"{label}{int(ability[key])}")
            self.tree.insert("", "end", iid=str(index), values=(ability["id"], ability["name"], ability["target"], ability.get("hotkey") or "—", "/".join(costs) or "Free", f"{float(ability['cooldown']):g}s", ability["max_charges"] or "∞", len(ability["effects"]), "Yes" if ability.get("ai_enabled") else "No"))
        self.summary_var.set(f"{len(self._abilities())} ability definition(s) • saved inside this trigger sidecar")
        if select is not None and 0 <= select < len(self._abilities()): self.tree.selection_set(str(select)); self.tree.focus(str(select)); self.tree.see(str(select))

    def _add(self) -> None:
        dialog = AbilityEditDialog(self, new_ability(len(self._abilities())+1)); self.wait_window(dialog)
        if dialog.result is not None: self._abilities().append(dialog.result); self._refresh(len(self._abilities())-1); self._changed()
    def _edit(self) -> None:
        index = self._selected()
        if index is None: return
        dialog = AbilityEditDialog(self, self._abilities()[index]); self.wait_window(dialog)
        if dialog.result is not None: self._abilities()[index] = dialog.result; self._refresh(index); self._changed()
    def _duplicate(self) -> None:
        index = self._selected()
        if index is None: return
        copy = normalize_ability(deepcopy(self._abilities()[index]), len(self._abilities())+1); copy["id"] = f"{copy['id']}_copy"; copy["name"] = f"{copy['name']} Copy"
        self._abilities().insert(index+1, copy); self._refresh(index+1); self._changed()
    def _delete(self) -> None:
        index = self._selected()
        if index is None: return
        name = normalize_ability(self._abilities()[index]).get("name", "this ability")
        if messagebox.askyesno("Delete ability", f"Delete {name}?\n\nTriggers that reference its ID will no longer cast it.", parent=self):
            self._abilities().pop(index); self._refresh(min(index, len(self._abilities())-1)); self._changed()
    def _validate(self) -> None:
        errors = validate_abilities(self._abilities())
        messagebox.showinfo("Ability validation" if not errors else "Ability validation errors", "All custom ability definitions are valid." if not errors else "\n".join(errors), parent=self)
    def _import(self) -> None:
        path = filedialog.askopenfilename(parent=self, title="Import custom abilities", filetypes=(("Ability JSON", "*.json"), ("All files", "*.*")))
        if not path: return
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8")); items = raw.get("abilities", []) if isinstance(raw, dict) else raw
            if not isinstance(items, list): raise ValueError("Ability file must contain a JSON list or an abilities list")
            normalized = [normalize_ability(item, index+1) for index, item in enumerate(items)]; errors = validate_abilities(normalized)
            if errors: raise ValueError("\n".join(errors))
            existing = {str(item.get("id", "")).casefold() for item in self._abilities()}
            duplicates = [item["id"] for item in normalized if str(item["id"]).casefold() in existing]
            if duplicates: raise ValueError("Duplicate IDs already in this sidecar: " + ", ".join(duplicates))
            self._abilities().extend(normalized); self._refresh(len(self._abilities())-1); self._changed()
        except Exception as exc: messagebox.showerror("Import abilities", str(exc), parent=self)
    def _export(self) -> None:
        path = filedialog.asksaveasfilename(parent=self, title="Export custom abilities", defaultextension=".json", filetypes=(("Ability JSON", "*.json"),))
        if not path: return
        try:
            Path(path).write_text(json.dumps({"format":"war2-custom-abilities", "version":1, "abilities":self._abilities()}, indent=2), encoding="utf-8")
        except Exception as exc: messagebox.showerror("Export abilities", str(exc), parent=self)
