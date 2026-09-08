from __future__ import annotations

"""Generate dedicated 1.44 card-trigger examples and the full cross-faction showcase."""

from copy import deepcopy
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from card_defs import enable_cross_faction, stock_cards
from clause_editor import ACTIONS, ACTION_SCHEMAS, CARD_ACTIONS_144, CARD_CONDITIONS_144, CONDITIONS, CONDITION_SCHEMAS


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")


def defaults(schema) -> dict:
    return {spec.key: deepcopy(spec.default) for spec in schema}


def base_payload() -> dict:
    card = next(item for item in stock_cards() if item["id"] == "stock.sgHBarracksCard.0")
    return {
        "schema": "war2-trigger-sidecar", "version": 4, "map_file": "",
        "locations": [], "variables": {}, "timers": {}, "forces": {}, "objectives": {},
        "abilities": [], "cards": [card], "triggers": [],
    }


for kind in CARD_ACTIONS_144:
    payload = base_payload(); args = defaults(ACTION_SCHEMAS[kind])
    payload["triggers"] = [{
        "name": f"TEST ACTION - {kind}", "players": [0], "conditions": [{"kind": "Always", "args": {}}],
        "actions": [{"kind": kind, "args": args}], "preserved": False, "enabled": True,
        "comment": f"Trigger Studio 1.44 dedicated All Cards Trigger Engine action example: {kind}.",
        "condition_mode": "All", "start_delay": 0.0, "repeat_interval": 1.0, "max_runs": 1,
    }]
    index = ACTIONS.index(kind) + 1
    (ROOT / "examples" / "actions" / f"{index:03d}_{slug(kind)}.w2trig.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

for kind in CARD_CONDITIONS_144:
    payload = base_payload(); args = defaults(CONDITION_SCHEMAS[kind])
    payload["triggers"] = [{
        "name": f"TEST CONDITION - {kind}", "players": [0], "conditions": [{"kind": kind, "args": args}],
        "actions": [{"kind": "Display Text", "args": {"text": f"{kind} passed"}}], "preserved": False, "enabled": True,
        "comment": f"Trigger Studio 1.44 dedicated All Cards Trigger Engine condition example: {kind}.",
        "condition_mode": "All", "start_delay": 0.0, "repeat_interval": 1.0, "max_runs": 1,
    }]
    index = CONDITIONS.index(kind) + 1
    (ROOT / "examples" / "conditions" / f"{index:03d}_{slug(kind)}.w2trig.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

cards = stock_cards(); enable_cross_faction(cards)
hotkeys = {
    "stock.sgHBarracksCard.0": "1", "stock.sgHBarracksCard.1": "2", "stock.sgHBarracksCard.2": "3",
    "stock.sgHBarracksCard.3": "4", "stock.sgHBarracksCard.4": "5", "stock.sgHBarracksCard.5": "6",
    "stock.sgOBarracksCard.0": "F1", "stock.sgOBarracksCard.1": "F2", "stock.sgOBarracksCard.2": "F3",
    "stock.sgOBarracksCard.3": "F4", "stock.sgOBarracksCard.4": "F5", "stock.sgOBarracksCard.5": "F6",
}
for card in cards:
    if card["id"] in hotkeys: card["hotkey"] = hotkeys[card["id"]]

showcase = {
    "schema": "war2-trigger-sidecar", "version": 4, "map_file": "",
    "locations": [], "variables": {}, "timers": {}, "forces": {}, "objectives": {}, "abilities": [], "cards": cards,
    "triggers": [
        {
            "name": "SHOW HUMAN BARRACKS CARD PAGE", "players": [0], "conditions": [{"kind": "Always", "args": {}}],
            "actions": [{"kind": "Show Trigger Card Page", "args": {"producer_reference": "", "page": "sgHBarracksCard", "title": "HUMAN UNITS ON EITHER BARRACKS", "seconds": 10}}],
            "preserved": False, "enabled": True, "comment": "Select a Human Barracks or Orc Barracks before starting. Cross-faction producer IDs are already enabled.",
            "condition_mode": "All", "start_delay": 0.0, "repeat_interval": 1.0, "max_runs": 1,
        },
        {
            "name": "FOOTMAN CARD CLICK EVENT", "players": [0],
            "conditions": [{"kind": "Card Clicked", "args": {"card_id": "stock.sgHBarracksCard.0", "comparison": "At least", "amount": 1, "negate": False}}],
            "actions": [{"kind": "Display Text", "args": {"text": "The Footman source card fired as a trigger."}}],
            "preserved": True, "enabled": True, "comment": "The same event works when an Orc Barracks trains the Human unit through the cross-faction card.",
            "condition_mode": "All", "start_delay": 0.0, "repeat_interval": 0.25, "max_runs": 0,
        },
        {
            "name": "FOOTMAN CROSS-FACTION FINISHED", "players": [0],
            "conditions": [{"kind": "Card Production Finished", "args": {"card_id": "stock.sgHBarracksCard.0", "comparison": "At least", "amount": 1, "negate": False}}],
            "actions": [{"kind": "Display Text", "args": {"text": "Footman card production finished."}}],
            "preserved": True, "enabled": True, "comment": "Native production is used when accepted; otherwise the authored timed fallback creates the unit and emits this event.",
            "condition_mode": "All", "start_delay": 0.0, "repeat_interval": 0.25, "max_runs": 0,
        },
    ],
}
(ROOT / "examples" / "All_Cards_Cross_Faction_Showcase_1.44.w2trig.json").write_text(json.dumps(showcase, indent=2), encoding="utf-8")
print(json.dumps({"actions": len(CARD_ACTIONS_144), "conditions": len(CARD_CONDITIONS_144), "catalog_cards": len(cards)}, indent=2))
