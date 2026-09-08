from __future__ import annotations

"""Regenerate the 1.43 Custom Ability Engine examples from the live schemas."""

from copy import deepcopy
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from ability_defs import new_ability  # noqa: E402
from clause_editor import (  # noqa: E402
    ACTIONS, ACTION_SCHEMAS, CONDITIONS, CONDITION_SCHEMAS,
    ABILITY_ACTIONS_143, ABILITY_CONDITIONS_143,
)


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", value).strip("_")


def args_for(schema) -> dict:
    return {spec.key: deepcopy(spec.default) for spec in schema}


def base_payload() -> dict:
    ability = new_ability()
    ability.update({
        "id": "arcane_bolt", "name": "Arcane Bolt", "description": "A focused custom damage spell.",
        "hotkey": "B", "target": "Enemy Unit", "range": 8, "mana_cost": 20,
        "cooldown": 2.0, "caster_types": [10, 24], "ai_enabled": True,
    })
    return {
        "schema": "war2-trigger-sidecar", "version": 3, "map_file": "",
        "locations": [{"name": "Ability Target", "left": 28, "top": 28, "right": 32, "bottom": 32}],
        "triggers": [], "variables": {}, "timers": {}, "forces": {}, "objectives": {},
        "abilities": [ability],
    }


def write_feature_examples() -> None:
    for kind in ABILITY_ACTIONS_143:
        payload = base_payload()
        if kind == "Cast Ability":
            payload["abilities"][0]["target"] = "None"
            payload["abilities"][0]["effects"] = [{"kind": "Display Message", "text": "Arcane Bolt cast without a target."}]
        elif kind == "Cast Ability At Point":
            payload["abilities"][0]["target"] = "Point"
            payload["abilities"][0]["effects"] = [{"kind": "Damage Area", "amount": 20, "radius": 2, "friendly_fire": False}]
        payload["triggers"] = [{
            "name": f"TEST ACTION - {kind}", "players": [0],
            "conditions": [{"kind": "Always", "args": {}}],
            "actions": [{"kind": kind, "args": args_for(ACTION_SCHEMAS[kind])}],
            "preserved": False, "enabled": True,
            "comment": f"Trigger Studio 1.43 dedicated Custom Ability Engine action example: {kind}.",
            "condition_mode": "All", "start_delay": 0.0, "repeat_interval": 1.0, "max_runs": 1,
        }]
        index = ACTIONS.index(kind) + 1
        path = ROOT / "examples" / "actions" / f"{index:03d}_{slug(kind)}.w2trig.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    for kind in ABILITY_CONDITIONS_143:
        payload = base_payload()
        payload["triggers"] = [{
            "name": f"TEST CONDITION - {kind}", "players": [0],
            "conditions": [{"kind": kind, "args": args_for(CONDITION_SCHEMAS[kind])}],
            "actions": [{"kind": "Game Message", "args": {
                "text": f"Condition fired: {kind}", "color": "White — native highlight",
                "recipients": "Local player only", "seconds": 4, "also_log": True,
            }}],
            "preserved": True, "enabled": True,
            "comment": f"Trigger Studio 1.43 dedicated Custom Ability Engine condition example: {kind}.",
            "condition_mode": "All", "start_delay": 0.0, "repeat_interval": 0.5, "max_runs": 0,
        }]
        index = CONDITIONS.index(kind) + 1
        path = ROOT / "examples" / "conditions" / f"{index:03d}_{slug(kind)}.w2trig.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_showcase() -> None:
    abilities = [
        {
            "id": "arcane_bolt", "name": "Arcane Bolt", "description": "Launch a focused bolt and deal exact native damage.",
            "icon": "Fireball projectile", "hotkey": "B", "target": "Enemy Unit", "range": 8,
            "mana_cost": 20, "gold_cost": 0, "lumber_cost": 0, "oil_cost": 0, "cooldown": 2.0,
            "max_charges": 0, "caster_types": [10, 24], "enabled": True, "ai_enabled": True, "ai_priority": 80,
            "effects": [
                {"kind": "Create Projectile", "missile": 2},
                {"kind": "Damage Target", "amount": 35},
                {"kind": "Display Message", "text": "{ability} hits at {x},{y}"},
            ],
        },
        {
            "id": "aegis", "name": "Aegis", "description": "Heal and protect an allied unit.",
            "icon": "Paladin shield", "hotkey": "A", "target": "Allied Unit", "range": 6,
            "mana_cost": 30, "gold_cost": 0, "lumber_cost": 0, "oil_cost": 0, "cooldown": 8.0,
            "max_charges": 3, "caster_types": [12, 44, 52], "enabled": True, "ai_enabled": True, "ai_priority": 90,
            "effects": [
                {"kind": "Heal Target", "amount": 45},
                {"kind": "Apply Status", "status": "Invincible", "seconds": 4.0, "recipient": "Target"},
            ],
        },
        {
            "id": "blink", "name": "Blink", "description": "Teleport the caster to a selected point.",
            "icon": "Teleport", "hotkey": "T", "target": "Point", "range": 10,
            "mana_cost": 10, "gold_cost": 0, "lumber_cost": 0, "oil_cost": 0, "cooldown": 5.0,
            "max_charges": 0, "caster_types": [], "enabled": True, "ai_enabled": False, "ai_priority": 40,
            "effects": [{"kind": "Teleport Caster"}, {"kind": "Play Caster Sound"}],
        },
        {
            "id": "necrotic_burst", "name": "Necrotic Burst", "description": "Damage enemies around a selected point.",
            "icon": "Black X marker", "hotkey": "N", "target": "Point", "range": 9,
            "mana_cost": 45, "gold_cost": 0, "lumber_cost": 0, "oil_cost": 0, "cooldown": 6.0,
            "max_charges": 0, "caster_types": [11, 21, 51], "enabled": True, "ai_enabled": True, "ai_priority": 85,
            "effects": [
                {"kind": "Create Projectile", "missile": 28},
                {"kind": "Damage Area", "amount": 28, "radius": 3, "friendly_fire": False},
            ],
        },
        {
            "id": "raise_guard", "name": "Raise Guard", "description": "Spend resources to summon Skeleton guards.",
            "icon": "Skeleton", "hotkey": "G", "target": "Point", "range": 6,
            "mana_cost": 0, "gold_cost": 100, "lumber_cost": 25, "oil_cost": 0, "cooldown": 12.0,
            "max_charges": 2, "caster_types": [11, 21, 51], "enabled": True, "ai_enabled": True, "ai_priority": 55,
            "effects": [
                {"kind": "Spawn Unit", "unit_type": 55, "owner": "Caster"},
                {"kind": "Spawn Unit", "unit_type": 55, "owner": "Caster"},
                {"kind": "Spawn Unit", "unit_type": 55, "owner": "Caster"},
                {"kind": "Add Counter", "name": "Summons", "amount": 1},
            ],
        },
    ]
    payload = base_payload(); payload["abilities"] = abilities
    payload["locations"] = [
        {"name": "Ability Target", "left": 28, "top": 28, "right": 32, "bottom": 32},
        {"name": "Enemy Camp", "left": 38, "top": 28, "right": 44, "bottom": 34},
    ]
    payload["variables"] = {"ShowAbilityHelp": 1}; payload["objectives"] = {"Ability Lab": "Select a caster and use B/A/T/N/G."}
    payload["triggers"] = [
        {
            "name": "Ability Lab - Explain controls", "players": [0], "conditions": [{"kind": "Always", "args": {}}],
            "actions": [{"kind": "Game Message", "args": {"text": "CUSTOM ABILITIES: select a valid caster, then use B Arcane Bolt, A Aegis, T Blink, N Necrotic Burst, or G Raise Guard.", "color": "White — native highlight", "recipients": "Local player only", "seconds": 10, "also_log": True}}],
            "preserved": False, "enabled": True, "comment": "Hotkeys open the local target picker. Definitions are editable in Tools -> Custom Ability Engine.", "condition_mode": "All", "start_delay": 0.0, "repeat_interval": 1.0, "max_runs": 1,
        },
        {
            "name": "Ability Lab - Enable enemy AI", "players": [1], "conditions": [{"kind": "Always", "args": {}}],
            "actions": [{"kind": "Enable Ability AI", "args": {"player": 1, "interval": 1.25, "max_casts": 1}}],
            "preserved": False, "enabled": True, "comment": "P2 evaluates definitions marked AI-enabled by priority and legal target.", "condition_mode": "All", "start_delay": 0.5, "repeat_interval": 1.0, "max_runs": 1,
        },
        {
            "name": "Ability Lab - Cast telemetry", "players": [0],
            "conditions": [{"kind": "Ability Cast Finished", "args": {"ability_id": "arcane_bolt", "comparison": "At least", "amount": 1}}],
            "actions": [{"kind": "Game Message", "args": {"text": "Arcane Bolt completed. Cooldown and costs are now committed.", "color": "Yellow / gold — native normal", "recipients": "Local player only", "seconds": 4, "also_log": True}}],
            "preserved": True, "enabled": True, "comment": "Demonstrates first-class ability lifecycle events.", "condition_mode": "All", "start_delay": 0.0, "repeat_interval": 0.25, "max_runs": 0,
        },
    ]
    (ROOT / "examples" / "Custom_Ability_Engine_Showcase_1.43.w2trig.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    write_feature_examples(); write_showcase()
    print("Generated Custom Ability Engine examples.")
