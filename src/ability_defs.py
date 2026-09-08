from __future__ import annotations

"""Portable definition and validation layer for the Custom Ability Engine.

This module deliberately has no live-process imports.  Ability sidecars can be
edited, validated, imported, and exported on any platform; the Windows-only
runtime consumes the same normalized dictionaries when a match is attached.
"""

from copy import deepcopy
import re
from typing import Any


ABILITY_TARGETS = (
    "None", "Self", "Point", "Unit", "Enemy Unit", "Allied Unit", "Building",
)

ABILITY_EFFECT_FIELDS: dict[str, tuple[dict[str, Any], ...]] = {
    "Native Spell": (
        {"key": "spell", "label": "Native spell", "kind": "choice", "default": "Fireball", "choices": (
            "Holy Vision", "Healing", "Area Heal", "Exorcism", "Flame Shield", "Fireball", "Slow",
            "Invisibility", "Polymorph", "Blizzard", "Eye of Kilrogg", "Bloodlust", "Runes",
            "Raise Dead", "Death Coil", "Whirlwind", "Haste", "Unholy Armor", "Death and Decay",
        )},
        {"key": "allow_wrong_caster", "label": "Allow nonstandard caster", "kind": "bool", "default": False},
    ),
    "Damage Target": (
        {"key": "amount", "label": "Damage", "kind": "int", "default": 25},
    ),
    "Damage Area": (
        {"key": "amount", "label": "Damage", "kind": "int", "default": 15},
        {"key": "radius", "label": "Radius (tiles)", "kind": "int", "default": 2},
        {"key": "friendly_fire", "label": "Damage allies", "kind": "bool", "default": False},
    ),
    "Heal Target": (
        {"key": "amount", "label": "Health restored", "kind": "int", "default": 25},
    ),
    "Restore Mana": (
        {"key": "amount", "label": "Mana restored", "kind": "int", "default": 25},
        {"key": "recipient", "label": "Recipient", "kind": "choice", "default": "Target", "choices": ("Caster", "Target")},
    ),
    "Teleport Caster": (),
    "Teleport Target": (),
    "Spawn Unit": (
        {"key": "unit_type", "label": "Unit type ID", "kind": "int", "default": 55},
        {"key": "owner", "label": "Owner", "kind": "choice", "default": "Caster", "choices": ("Caster", "Target", "Executing Player")},
    ),
    "Apply Status": (
        {"key": "status", "label": "Status/effect", "kind": "choice", "default": "Haste", "choices": (
            "Haste", "Slow", "Bloodlust", "Invisibility", "Flame Shield", "Unholy Armor",
            "Invincible", "Stunned", "Poisoned", "Burning", "Frozen", "Silenced",
        )},
        {"key": "seconds", "label": "Duration (seconds)", "kind": "float", "default": 10.0},
        {"key": "recipient", "label": "Recipient", "kind": "choice", "default": "Target", "choices": ("Caster", "Target")},
    ),
    "Create Projectile": (
        {"key": "missile", "label": "Projectile ID", "kind": "int", "default": 2},
    ),
    "Issue Order": (
        {"key": "order", "label": "Order", "kind": "choice", "default": "Attack", "choices": ("Move", "Attack", "Patrol")},
        {"key": "recipient", "label": "Recipient", "kind": "choice", "default": "Caster", "choices": ("Caster", "Target")},
    ),
    "Kill Target": (),
    "Run Trigger Function": (
        {"key": "trigger", "label": "Trigger function", "kind": "text", "default": "Ability Function"},
        {"key": "arguments_json", "label": "Arguments JSON", "kind": "text", "default": "{}"},
    ),
    "Display Message": (
        {"key": "text", "label": "Message", "kind": "text", "default": "Ability cast!"},
    ),
    "Play Caster Sound": (),
    "Set Variable": (
        {"key": "name", "label": "Variable", "kind": "text", "default": "AbilityValue"},
        {"key": "value", "label": "Value", "kind": "text", "default": "1"},
    ),
    "Add Counter": (
        {"key": "name", "label": "Counter", "kind": "text", "default": "AbilityCasts"},
        {"key": "amount", "label": "Amount", "kind": "int", "default": 1},
    ),
}

ABILITY_EFFECTS = tuple(ABILITY_EFFECT_FIELDS)
_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_HOTKEYS = {"ESCAPE", "SPACE", "ENTER", "TAB", "BACKSPACE", "LEFT", "UP", "RIGHT", "DOWN"}
_HOTKEYS.update(str(index) for index in range(10))
_HOTKEYS.update(chr(ord("A") + index) for index in range(26))
_HOTKEYS.update(f"F{index}" for index in range(1, 13))


def new_effect(kind: str = "Damage Target") -> dict[str, Any]:
    if kind not in ABILITY_EFFECT_FIELDS:
        kind = ABILITY_EFFECTS[0]
    result: dict[str, Any] = {"kind": kind}
    for field in ABILITY_EFFECT_FIELDS[kind]:
        result[field["key"]] = deepcopy(field.get("default"))
    return result


def new_ability(index: int = 1) -> dict[str, Any]:
    return {
        "id": f"ability_{max(1, int(index))}",
        "name": f"Custom Ability {max(1, int(index))}",
        "description": "A trigger-authored Warcraft II ability.",
        "icon": "",
        "hotkey": "",
        "target": "Enemy Unit",
        "range": 8,
        "mana_cost": 0,
        "gold_cost": 0,
        "lumber_cost": 0,
        "oil_cost": 0,
        "cooldown": 0.0,
        "max_charges": 0,
        "caster_types": [],
        "enabled": True,
        "ai_enabled": False,
        "ai_priority": 50,
        "effects": [new_effect("Damage Target")],
    }


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "yes", "true", "on", "enabled"}
    return bool(value)


def _coerce_number(value: Any, *, floating: bool = False) -> int | float:
    if value in (None, ""):
        return 0.0 if floating else 0
    return float(value) if floating else int(value)


def normalize_effect(raw: Any) -> dict[str, Any]:
    item = dict(raw) if isinstance(raw, dict) else {}
    kind = str(item.get("kind", "Damage Target")).strip()
    if kind not in ABILITY_EFFECT_FIELDS:
        return {"kind": kind}
    normalized: dict[str, Any] = {"kind": kind}
    for spec in ABILITY_EFFECT_FIELDS[kind]:
        value = item.get(spec["key"], deepcopy(spec.get("default")))
        if spec["kind"] == "bool":
            value = _coerce_bool(value)
        elif spec["kind"] == "int":
            try:
                value = int(value)
            except (TypeError, ValueError):
                pass
        elif spec["kind"] == "float":
            try:
                value = float(value)
            except (TypeError, ValueError):
                pass
        else:
            value = str(value)
        normalized[spec["key"]] = value
    return normalized


def normalize_ability(raw: Any, index: int = 1) -> dict[str, Any]:
    base = new_ability(index)
    item = dict(raw) if isinstance(raw, dict) else {}
    base.update({key: value for key, value in item.items() if key != "effects"})
    for key in ("id", "name", "description", "icon", "hotkey", "target"):
        base[key] = str(base.get(key, "")).strip()
    for key in ("range", "mana_cost", "gold_cost", "lumber_cost", "oil_cost", "max_charges", "ai_priority"):
        try:
            base[key] = int(base.get(key, 0))
        except (TypeError, ValueError):
            pass
    try:
        base["cooldown"] = float(base.get("cooldown", 0.0))
    except (TypeError, ValueError):
        pass
    caster_types = base.get("caster_types", [])
    if isinstance(caster_types, str):
        caster_types = [part.strip() for part in caster_types.replace(";", ",").split(",") if part.strip()]
    converted: list[Any] = []
    for value in caster_types if isinstance(caster_types, (list, tuple)) else []:
        try:
            converted.append(int(value))
        except (TypeError, ValueError):
            converted.append(value)
    base["caster_types"] = converted
    base["enabled"] = _coerce_bool(base.get("enabled", True))
    base["ai_enabled"] = _coerce_bool(base.get("ai_enabled", False))
    effects = item.get("effects", base["effects"])
    base["effects"] = [normalize_effect(effect) for effect in effects] if isinstance(effects, list) else []
    return base


def validate_ability_definition(raw: Any, *, index: int = 1) -> list[str]:
    ability = normalize_ability(raw, index)
    label = ability.get("name") or ability.get("id") or f"Ability {index}"
    errors: list[str] = []
    if not _ID_RE.fullmatch(str(ability.get("id", ""))):
        errors.append(f"{label}: ID must use 1-64 letters, numbers, dots, underscores, or hyphens")
    if not str(ability.get("name", "")).strip():
        errors.append(f"{label}: name is blank")
    if ability.get("target") not in ABILITY_TARGETS:
        errors.append(f"{label}: unknown target mode {ability.get('target')!r}")
    hotkey = str(ability.get("hotkey", "")).strip()
    if hotkey and hotkey.upper().removeprefix("VK_") not in _HOTKEYS:
        try:
            numeric_hotkey = int(hotkey, 0)
            if not 0 <= numeric_hotkey <= 0xFF:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{label}: unsupported local hotkey {hotkey!r}")
    for key, title in (
        ("range", "range"), ("mana_cost", "mana cost"), ("gold_cost", "gold cost"),
        ("lumber_cost", "lumber cost"), ("oil_cost", "oil cost"),
        ("max_charges", "maximum charges"), ("ai_priority", "AI priority"),
    ):
        try:
            if int(ability.get(key, 0)) < 0:
                errors.append(f"{label}: {title} cannot be negative")
        except (TypeError, ValueError):
            errors.append(f"{label}: {title} must be a whole number")
    try:
        if float(ability.get("cooldown", 0.0)) < 0:
            errors.append(f"{label}: cooldown cannot be negative")
    except (TypeError, ValueError):
        errors.append(f"{label}: cooldown must be numeric")
    for caster in ability.get("caster_types", []):
        try:
            caster_id = int(caster)
            if not 0 <= caster_id <= 105:
                raise ValueError
        except (TypeError, ValueError):
            errors.append(f"{label}: caster type {caster!r} is not a Warcraft unit ID (0-105)")
    effects = ability.get("effects", [])
    if not effects:
        errors.append(f"{label}: add at least one effect")
    for effect_index, effect in enumerate(effects, 1):
        kind = str(effect.get("kind", "")) if isinstance(effect, dict) else ""
        if kind not in ABILITY_EFFECT_FIELDS:
            errors.append(f"{label}: effect {effect_index} has unknown kind {kind!r}")
            continue
        normalized = normalize_effect(effect)
        for spec in ABILITY_EFFECT_FIELDS[kind]:
            value = normalized.get(spec["key"])
            if spec["kind"] in {"int", "float"}:
                try:
                    number = _coerce_number(value, floating=spec["kind"] == "float")
                    if number < 0:
                        errors.append(f"{label}: effect {effect_index} {spec['label'].lower()} cannot be negative")
                except (TypeError, ValueError):
                    errors.append(f"{label}: effect {effect_index} {spec['label'].lower()} must be numeric")
            if spec["kind"] == "choice" and value not in spec.get("choices", ()):
                errors.append(f"{label}: effect {effect_index} has invalid {spec['label'].lower()} {value!r}")
            if spec["kind"] == "text" and not str(value).strip():
                errors.append(f"{label}: effect {effect_index} {spec['label'].lower()} is blank")
        if kind == "Run Trigger Function":
            import json
            try:
                parsed = json.loads(str(normalized.get("arguments_json", "{}")))
                if not isinstance(parsed, dict):
                    raise TypeError
            except Exception:
                errors.append(f"{label}: effect {effect_index} arguments must be a JSON object")
        limits = {
            "Damage Target": (("amount", 0, 65535),),
            "Damage Area": (("amount", 0, 65535), ("radius", 0, 32)),
            "Heal Target": (("amount", 0, 65535),),
            "Restore Mana": (("amount", 0, 255),),
            "Spawn Unit": (("unit_type", 0, 57),),
            "Create Projectile": (("missile", 0, 29),),
            "Add Counter": (("amount", 0, 0x7FFFFFFF),),
        }.get(kind, ())
        for key, low, high in limits:
            try:
                value = int(normalized.get(key, 0))
                if not low <= value <= high:
                    errors.append(f"{label}: effect {effect_index} {key.replace('_', ' ')} must be {low}-{high}")
            except (TypeError, ValueError):
                pass
    return errors


def validate_abilities(abilities: Any) -> list[str]:
    if not isinstance(abilities, list):
        return ["Custom abilities must be stored as a list"]
    errors: list[str] = []
    ids: set[str] = set()
    hotkeys: set[str] = set()
    for index, raw in enumerate(abilities, 1):
        errors.extend(validate_ability_definition(raw, index=index))
        ability_id = str(normalize_ability(raw, index).get("id", "")).casefold()
        if ability_id in ids:
            errors.append(f"Duplicate custom ability ID: {ability_id}")
        ids.add(ability_id)
        hotkey = str(normalize_ability(raw, index).get("hotkey", "")).strip().upper().removeprefix("VK_")
        if hotkey:
            if hotkey in hotkeys:
                errors.append(f"Duplicate custom ability hotkey: {hotkey}")
            hotkeys.add(hotkey)
    return errors
