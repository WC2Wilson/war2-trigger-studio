from __future__ import annotations

"""Visual editor for Trigger Studio 1.44 command-card definitions."""

from copy import deepcopy
import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from card_defs import CARD_ACTIONS, CARD_RACES, CARD_TARGETS, enable_cross_faction, new_card, normalize_card, stock_cards, validate_card_definition, validate_cards
from ultimate_features import SPELL_BITS, UPGRADE_ROWS


BG = "#171a1f"; MUTED = "#9aa5af"


def _center(window: tk.Toplevel, parent: tk.Misc) -> None:
    window.update_idletasks(); x = max(0, parent.winfo_rootx() + (parent.winfo_width() - window.winfo_width()) // 2); y = max(0, parent.winfo_rooty() + (parent.winfo_height() - window.winfo_height()) // 2); window.geometry(f"+{x}+{y}")


class CardEditDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, card: dict[str, Any]):
        super().__init__(parent); self.title("Trigger Command Card"); self.geometry("900x760"); self.minsize(780, 680); self.configure(bg=BG)
        self.result: dict[str, Any] | None = None; self._source = normalize_card(card); self.vars: dict[str, tk.Variable] = {}
        outer = ttk.Frame(self, padding=14); outer.pack(fill="both", expand=True)
        heading = ttk.Frame(outer); heading.pack(fill="x", pady=(0, 10)); ttk.Label(heading, text="TRIGGER COMMAND CARD", font=("Segoe UI Semibold", 14)).pack(side="left"); ttk.Label(heading, text="source row, producer access, action, cost, and timing", foreground=MUTED).pack(side="left", padx=14)
        notebook = ttk.Notebook(outer); notebook.pack(fill="both", expand=True)
        general = ttk.Frame(notebook, padding=14); action = ttk.Frame(notebook, padding=14); source = ttk.Frame(notebook, padding=14)
        notebook.add(general, text="Card & producers"); notebook.add(action, text="Action & economy"); notebook.add(source, text="Source metadata")
        self._build_general(general); self._build_action(action); self._build_source(source)
        buttons = ttk.Frame(outer); buttons.pack(fill="x", pady=(12, 0)); ttk.Label(buttons, text="Costs of -1 use native unit cost where available; other fallback costs default to 0.", foreground=MUTED).pack(side="left")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(6, 0)); ttk.Button(buttons, text="Save Card", style="Accent.TButton", command=self._accept).pack(side="right")
        self.protocol("WM_DELETE_WINDOW", self.destroy); self.transient(parent); self.grab_set(); _center(self, parent)

    def _entry(self, page: ttk.Frame, row: int, key: str, label: str, *, width: int = 34) -> None:
        ttk.Label(page, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5); var = tk.StringVar(value=str(self._source.get(key, ""))); self.vars[key] = var; ttk.Entry(page, textvariable=var, width=width).grid(row=row, column=1, sticky="ew", pady=5)

    def _choice(self, page: ttk.Frame, row: int, key: str, label: str, values: tuple[str, ...]) -> None:
        ttk.Label(page, text=label).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=5); var = tk.StringVar(value=str(self._source.get(key, values[0]))); self.vars[key] = var; ttk.Combobox(page, textvariable=var, values=values, state="readonly").grid(row=row, column=1, sticky="ew", pady=5)

    def _build_general(self, page: ttk.Frame) -> None:
        for row, item in enumerate((("id","Stable ID"),("name","Display name"),("description","Description"),("page","Card page"),("slot","Panel slot (0-31)"),("icon","Icon/source token"),("hotkey","Local hotkey"),("producer_types","Producer unit/building IDs"))): self._entry(page,row,*item)
        self.vars["producer_types"].set(", ".join(str(value) for value in self._source.get("producer_types", [])))
        self._choice(page, 8, "race", "Source race", CARD_RACES)
        for row, (key, label) in enumerate((("enabled","Enabled at start"),("allow_cross_faction","Allow cross-faction fallback"),("native_first","Try verified native production first")), start=9):
            var = tk.BooleanVar(value=bool(self._source.get(key, True))); self.vars[key] = var; ttk.Checkbutton(page, text=label, variable=var).grid(row=row, column=0, columnspan=2, sticky="w", pady=5)
        ttk.Label(page, text="Empty producer IDs means any selected unit. Cross-faction expansion adds the opposite Human/Orc producer IDs.", foreground=MUTED, wraplength=720, justify="left").grid(row=12,column=0,columnspan=2,sticky="w",pady=(16,0)); page.columnconfigure(1,weight=1)

    def _build_action(self, page: ttk.Frame) -> None:
        self._choice(page,0,"action","Action",CARD_ACTIONS)
        for row, item in enumerate((("unit_type","Unit to train (0-57)"),("building_type","Structure/building (58-104)")),start=1): self._entry(page,row,*item)
        self._choice(page,3,"spell","Spell",tuple(SPELL_BITS)); self._choice(page,4,"target","Spell target mode",CARD_TARGETS); self._choice(page,5,"upgrade","Technology",tuple(UPGRADE_ROWS))
        for row,item in enumerate((("ability_id","Custom ability ID"),("trigger","Trigger function"),("arguments_json","Function arguments JSON"),("gold_cost","Gold (-1 default)"),("lumber_cost","Lumber (-1 default)"),("oil_cost","Oil (-1 default)"),("seconds","Fallback production seconds")),start=6): self._entry(page,row,*item)
        ttk.Label(page,text="Source Callback cards emit Card Clicked so any trigger can implement the row. Production cards execute directly; native-spell cards use the Custom Ability targeting path and may be granted across races.",foreground=MUTED,wraplength=720,justify="left").grid(row=13,column=0,columnspan=2,sticky="w",pady=(16,0)); page.columnconfigure(1,weight=1)

    def _build_source(self, page: ttk.Frame) -> None:
        for row,item in enumerate((("source_array","Source card array"),("source_row","Source row"),("source_callback","Source action callback"),("visibility_callback","Source visibility callback"),("visibility_parameter","Visibility parameter"),("action_parameter","Action parameter"),("tooltip_token","Tooltip token"),("target_mask","Target mask"))): self._entry(page,row,*item)
        ttk.Label(page,text="Metadata is retained for all 418 source rows. It is documentation and routing data; Trigger Studio does not jump to an unverified modern callback address.",foreground=MUTED,wraplength=720,justify="left").grid(row=8,column=0,columnspan=2,sticky="w",pady=(16,0)); page.columnconfigure(1,weight=1)

    def _accept(self) -> None:
        raw = {key: var.get() for key,var in self.vars.items()}
        raw["producer_types"] = [part.strip() for part in str(raw.get("producer_types","")).replace(";",",").split(",") if part.strip()]
        errors = validate_card_definition(raw)
        if errors: messagebox.showerror("Invalid command card","\n".join(errors),parent=self); return
        self.result = normalize_card(raw); self.destroy()


class CardManagerDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, scenario: Any, on_changed: Callable[[], None]):
        super().__init__(parent); self.title("All Cards Trigger Engine"); self.geometry("1100x700"); self.minsize(880,560); self.configure(bg=BG); self.scenario=scenario; self.on_changed=on_changed
        outer=ttk.Frame(self,padding=12); outer.pack(fill="both",expand=True)
        header=ttk.Frame(outer); header.pack(fill="x",pady=(0,8)); ttk.Label(header,text="ALL CARDS TRIGGER ENGINE",font=("Segoe UI Semibold",14)).pack(side="left"); self.summary_var=tk.StringVar(); ttk.Label(header,textvariable=self.summary_var,foreground=MUTED).pack(side="left",padx=14)
        toolbar=ttk.Frame(outer); toolbar.pack(fill="x",pady=(0,8))
        for text,command in (("Add",self._add),("Edit",self._edit),("Duplicate",self._duplicate),("Delete",self._delete),("Add Full Source Catalog",self._add_stock),("Enable Human ↔ Orc",self._cross),("Validate",self._validate),("Import",self._import),("Export",self._export)): ttk.Button(toolbar,text=text,command=command).pack(side="left",padx=(0,5))
        box=ttk.Frame(outer); box.pack(fill="both",expand=True); columns=("name","race","page","slot","producers","action","payload","cross")
        self.tree=ttk.Treeview(box,columns=columns,show="headings",selectmode="browse")
        labels=("Card","Race","Page","Slot","Producers","Action","Payload","Cross")
        widths=(180,65,140,45,120,120,190,45)
        for key,label,width in zip(columns,labels,widths): self.tree.heading(key,text=label); self.tree.column(key,width=width,stretch=key in {"name","payload"})
        scroll=ttk.Scrollbar(box,orient="vertical",command=self.tree.yview); self.tree.configure(yscrollcommand=scroll.set); self.tree.pack(side="left",fill="both",expand=True); scroll.pack(side="right",fill="y"); self.tree.bind("<Double-1>",lambda _e:self._edit())
        ttk.Label(outer,text="Full Source Catalog imports 61 arrays / 418 rows. Enable Human ↔ Orc adds opposite-race producers and turns on the safe fallback policy.",foreground=MUTED,wraplength=1000,justify="left").pack(fill="x",pady=(8,0)); self._refresh()

    def _cards(self) -> list[dict[str,Any]]: return self.scenario.cards
    def _index(self) -> int | None:
        selected=self.tree.selection(); return int(selected[0]) if selected else None
    @staticmethod
    def _payload(card: dict[str,Any]) -> str:
        action=card.get("action"); return {"Train Unit":f"unit {card.get('unit_type')}","Build Structure":f"building {card.get('building_type')}","Upgrade Building":f"building {card.get('building_type')}","Research Spell":str(card.get("spell")),"Research Upgrade":str(card.get("upgrade")),"Cast Native Spell":f"{card.get('spell')} / {card.get('target')}","Cast Custom Ability":str(card.get("ability_id")),"Run Trigger Function":str(card.get("trigger"))}.get(str(action),str(card.get("source_callback","")))
    def _refresh(self,select: int|None=None) -> None:
        for item in self.tree.get_children(): self.tree.delete(item)
        for index,raw in enumerate(self._cards()):
            card=normalize_card(raw,index+1); producers=", ".join(str(x) for x in card["producer_types"][:8])+("…" if len(card["producer_types"])>8 else "")
            self.tree.insert("","end",iid=str(index),values=(card["name"],card["race"],card["page"],card["slot"],producers,card["action"],self._payload(card),"Yes" if card["allow_cross_faction"] else ""))
        self.summary_var.set(f"{len(self._cards())} card definition(s) • saved inside this trigger sidecar")
        if select is not None and 0<=select<len(self._cards()): self.tree.selection_set(str(select)); self.tree.focus(str(select)); self.tree.see(str(select))
    def _changed(self) -> None: self.on_changed()
    def _add(self) -> None:
        dialog=CardEditDialog(self,new_card(len(self._cards())+1)); self.wait_window(dialog)
        if dialog.result is not None: self._cards().append(dialog.result); self._refresh(len(self._cards())-1); self._changed()
    def _edit(self) -> None:
        index=self._index()
        if index is None:return
        dialog=CardEditDialog(self,self._cards()[index]); self.wait_window(dialog)
        if dialog.result is not None:self._cards()[index]=dialog.result;self._refresh(index);self._changed()
    def _duplicate(self) -> None:
        index=self._index()
        if index is None:return
        card=deepcopy(normalize_card(self._cards()[index],index+2));card["id"]+= ".copy";card["name"]+=" Copy";self._cards().insert(index+1,card);self._refresh(index+1);self._changed()
    def _delete(self) -> None:
        index=self._index()
        if index is None:return
        if messagebox.askyesno("Delete command card",f"Delete {normalize_card(self._cards()[index]).get('name')}?",parent=self):self._cards().pop(index);self._refresh(min(index,len(self._cards())-1));self._changed()
    def _add_stock(self) -> None:
        existing={str(card.get("id","")).casefold() for card in self._cards()}; additions=[card for card in stock_cards() if str(card["id"]).casefold() not in existing]; self._cards().extend(additions);self._refresh(len(self._cards())-1);self._changed();messagebox.showinfo("Source catalog",f"Added {len(additions)} source command rows. Existing IDs were kept.",parent=self)
    def _cross(self) -> None:
        changed=enable_cross_faction(self._cards());self._refresh();self._changed();messagebox.showinfo("Cross-faction cards",f"Enabled opposite-race producers on {changed} racial card definitions.",parent=self)
    def _validate(self) -> None:
        errors=validate_cards(self._cards());messagebox.showerror("Command card validation","\n".join(errors),parent=self) if errors else messagebox.showinfo("Command card validation",f"All {len(self._cards())} command cards are valid.",parent=self)
    def _import(self) -> None:
        path=filedialog.askopenfilename(parent=self,title="Import command cards",filetypes=(("Card JSON","*.json"),("All files","*.*")))
        if not path:return
        try:
            raw=json.loads(Path(path).read_text(encoding="utf-8"));items=raw.get("cards",[]) if isinstance(raw,dict) else raw
            normalized=[normalize_card(item,index+1) for index,item in enumerate(items)];errors=validate_cards(normalized)
            if errors:raise ValueError("\n".join(errors))
            existing={str(item.get("id","")).casefold() for item in self._cards()}; additions=[item for item in normalized if str(item["id"]).casefold() not in existing];self._cards().extend(additions);self._refresh(len(self._cards())-1);self._changed()
        except Exception as exc:messagebox.showerror("Import command cards",str(exc),parent=self)
    def _export(self) -> None:
        path=filedialog.asksaveasfilename(parent=self,title="Export command cards",defaultextension=".json",filetypes=(("Card JSON","*.json"),))
        if path:
            try:Path(path).write_text(json.dumps({"format":"war2-trigger-cards","version":1,"cards":self._cards()},indent=2),encoding="utf-8")
            except Exception as exc:messagebox.showerror("Export command cards",str(exc),parent=self)
