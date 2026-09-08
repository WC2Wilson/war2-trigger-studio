from __future__ import annotations

"""Portable command-card definitions for Trigger Studio 1.44.

The stock catalog is reconstructed from the Warcraft II source card arrays.  A
definition keeps the original slot/icon/callback metadata, but execution goes
through validated Trigger Studio primitives instead of guessing at the modern
Remastered command-card ABI.
"""

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any


CARD_ACTIONS = (
    "Source Callback", "Train Unit", "Build Structure", "Research Spell",
    "Research Upgrade", "Upgrade Building", "Cast Native Spell", "Cast Custom Ability",
    "Run Trigger Function",
)
CARD_RACES = ("Any", "Human", "Orc")
CARD_TARGETS = ("None", "Self", "Point", "Unit", "Enemy Unit", "Allied Unit", "Building")

_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,96}$")
_HOTKEYS = {"ESCAPE", "SPACE", "ENTER", "TAB", "BACKSPACE", "LEFT", "UP", "RIGHT", "DOWN"}
_HOTKEYS.update(str(index) for index in range(10))
_HOTKEYS.update(chr(ord("A") + index) for index in range(26))
_HOTKEYS.update(f"F{index}" for index in range(1, 13))

# Names used by the original source arrays.  IDs are the verified Remastered
# unit IDs used everywhere else in Trigger Studio.
SOURCE_UNIT_IDS = {
    "H_GRUNT": 0, "O_GRUNT": 1, "H_PEON": 2, "O_PEON": 3,
    "H_CATAPULT": 4, "O_CATAPULT": 5, "H_KNIGHT": 6, "O_OGRE": 7,
    "H_SPEAR": 8, "O_SPEAR": 9, "H_WIZARD": 10, "O_DEATHKNIGHT": 11,
    "H_PALADIN": 12, "O_OGREMAGE": 13, "H_DWARVES": 14, "O_GOBLINS": 15,
    "H_RANGER": 18, "O_BERSERKER": 19, "H_TANKER": 26, "O_TANKER": 27,
    "H_TRANSPORT": 28, "O_TRANSPORT": 29, "H_DESTROYER": 30, "O_DESTROYER": 31,
    "H_BATTLESHIP": 32, "O_BATTLESHIP": 33, "H_SUBMARINE": 38, "O_SUBMARINE": 39,
    "H_FLYER": 40, "O_BALLOON": 41, "H_GRIFFON": 42, "O_DRAGON": 43,
    "H_FARM": 58, "O_FARM": 59, "H_BARRACKS": 60, "O_BARRACKS": 61,
    "H_CHURCH": 62, "O_TEMPLE": 63, "H_TOWER": 64, "O_TOWER": 65,
    "H_STABLES": 66, "O_STABLES": 67, "H_INVENTOR": 68, "O_INVENTOR": 69,
    "H_AVIARY": 70, "O_AVIARY": 71, "H_SHIPYARD": 72, "O_SHIPYARD": 73,
    "H_TOWNHALL": 74, "O_TOWNHALL": 75, "H_LUMBER": 76, "O_LUMBER": 77,
    "H_FOUNDRY": 78, "O_FOUNDRY": 79, "H_WIZARD_TOWER": 80, "O_DEATH_TOWER": 81,
    "H_BLACKSMITH": 82, "O_BLACKSMITH": 83, "H_REFINERY": 84, "O_REFINERY": 85,
    "H_OILRIG": 86, "O_OILRIG": 87, "H_KEEP": 88, "O_STRONGHOLD": 89,
    "H_STORMWIND": 90, "O_BLACK_ROCK": 91, "H_ATOWER": 96, "O_ATOWER": 97,
    "H_CTOWER": 98, "O_CTOWER": 99, "H_WALLUNIT": 102, "O_WALLUNIT": 103,
}

SOURCE_SPELLS = {
    "UG_SP_VISION": "Holy Vision", "UG_SP_HEAL": "Healing", "UG_SP_EXORCISM": "Exorcism",
    "UG_SP_FIRESHIELD": "Flame Shield", "UG_SP_FIREBALL": "Fireball", "UG_SP_SLOW": "Slow",
    "UG_SP_INVIS": "Invisibility", "UG_SP_POLYMORPH": "Polymorph", "UG_SP_BLIZZARD": "Blizzard",
    "UG_SP_EYE": "Eye of Kilrogg", "UG_SP_BLOODLUST": "Bloodlust", "UG_SP_RAISEDEAD": "Raise Dead",
    "UG_SP_DRAINLIFE": "Death Coil", "UG_SP_WHIRLWIND": "Whirlwind", "UG_SP_HASTE": "Haste",
    "UG_SP_ARMOR": "Unholy Armor", "UG_SP_RUNES": "Runes", "UG_SP_ROT": "Death and Decay",
    "UG_SP_PALADIN": "Paladin / Ogre-Mage Conversion", "UG_SP_OGREMAGE": "Paladin / Ogre-Mage Conversion",
}

SOURCE_ORDER_SPELLS = {
    "SPELL_VISION": "Holy Vision", "SPELL_HEAL": "Healing", "SPELL_EXORCISM": "Exorcism",
    "SPELL_FIRESHIELD": "Flame Shield", "SPELL_FIREBALL": "Fireball", "SPELL_SLOW": "Slow",
    "SPELL_INVIS": "Invisibility", "SPELL_POLYMORPH": "Polymorph", "SPELL_BLIZZARD": "Blizzard",
    "SPELL_EYE": "Eye of Kilrogg", "SPELL_BLOODLUST": "Bloodlust", "SPELL_RAISEDEAD": "Raise Dead",
    "SPELL_DRAINLIFE": "Death Coil", "SPELL_WHIRLWIND": "Whirlwind", "SPELL_HASTE": "Haste",
    "SPELL_ARMOR": "Unholy Armor", "SPELL_RUNES": "Runes", "SPELL_ROT": "Death and Decay",
}
SPELL_TARGETS = {
    "Holy Vision": "Point", "Healing": "Allied Unit", "Exorcism": "Point", "Flame Shield": "Unit",
    "Fireball": "Point", "Slow": "Unit", "Invisibility": "Allied Unit", "Polymorph": "Enemy Unit",
    "Blizzard": "Point", "Eye of Kilrogg": "None", "Bloodlust": "Allied Unit", "Raise Dead": "Point",
    "Death Coil": "Point", "Whirlwind": "Point", "Haste": "Unit", "Unholy Armor": "Allied Unit",
    "Runes": "Point", "Death and Decay": "Point",
}

SOURCE_UPGRADES = {
    "UPARROW": "Ranged Attack", "UPSPEAR": "Ranged Attack", "UPBOAT_ATTACK": "Ship Attack",
    "UPOBOAT_ATTACK": "Ship Attack", "UPBOAT_ARMOR": "Ship Armor", "UPOBOAT_ARMOR": "Ship Armor",
    "UPSWORD": "Melee Attack", "UPAXE": "Melee Attack", "UPSHIELD": "Armor", "UPOSHIELD": "Armor",
    "BALDMG": "Siege Damage", "CATDMG": "Siege Damage", "UPRANGERS": "Ranger / Berserker",
    "UPBERSERKERS": "Ranger / Berserker", "UPHSCOUTS": "Scouting", "UPOSCOUTS": "Scouting",
    "UPLONGBOW": "Longbow / Light Axes", "UPLIGHTAXE": "Longbow / Light Axes",
    "UPHMARKS": "Marksmanship / Regeneration", "UPOMARKS": "Marksmanship / Regeneration",
}

# Human/Orc counterparts used by the one-click cross-faction expansion.
RACE_COUNTERPARTS = {value: value ^ 1 for value in range(0, 44)}
RACE_COUNTERPARTS.update({value: value ^ 1 for value in range(58, 104)})


def new_card(index: int = 1) -> dict[str, Any]:
    return {
        "id": f"card_{max(1, int(index))}", "name": f"Trigger Card {max(1, int(index))}",
        "description": "A trigger-authored Warcraft II command card.", "race": "Any", "page": "Custom",
        "slot": 0, "icon": "", "hotkey": "", "producer_types": [], "enabled": True,
        "allow_cross_faction": False, "native_first": True, "action": "Run Trigger Function",
        "unit_type": 0, "building_type": 58, "spell": "Healing", "target": "None", "upgrade": "Melee Attack",
        "ability_id": "", "trigger": "Card Function", "arguments_json": "{}",
        "gold_cost": -1, "lumber_cost": -1, "oil_cost": -1, "seconds": 1.0,
        "source_array": "", "source_row": -1, "source_callback": "", "visibility_callback": "",
        "visibility_parameter": "", "action_parameter": "", "tooltip_token": "", "target_mask": "",
    }


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on", "enabled"}
    return bool(value)


def _int(value: Any, default: int = 0) -> int:
    try: return int(value)
    except (TypeError, ValueError): return default


def normalize_card(raw: Any, index: int = 1) -> dict[str, Any]:
    source = dict(raw) if isinstance(raw, dict) else {}
    result = new_card(index)
    result.update(source)
    for key in ("id", "name", "description", "race", "page", "icon", "hotkey", "action", "spell", "target", "upgrade", "ability_id", "trigger", "arguments_json", "source_array", "source_callback", "visibility_callback", "visibility_parameter", "action_parameter", "tooltip_token", "target_mask"):
        result[key] = str(result.get(key, "")).strip()
    result["hotkey"] = result["hotkey"].upper().removeprefix("VK_")
    result["producer_types"] = sorted({int(value) for value in result.get("producer_types", []) if str(value).strip()})
    for key in ("slot", "unit_type", "building_type", "gold_cost", "lumber_cost", "oil_cost", "source_row"):
        result[key] = _int(result.get(key), int(new_card(index)[key]))
    try: result["seconds"] = float(result.get("seconds", 1.0))
    except (TypeError, ValueError): pass
    for key in ("enabled", "allow_cross_faction", "native_first"):
        result[key] = _bool(result.get(key))
    return result


def validate_card_definition(raw: Any, index: int = 1) -> list[str]:
    card = normalize_card(raw, index)
    label = card.get("name") or f"Card {index}"
    errors: list[str] = []
    if not _ID_RE.fullmatch(str(card["id"])): errors.append(f"{label}: ID must use 1-96 letters, digits, dots, dashes, or underscores")
    if not str(card["name"]).strip(): errors.append(f"Card {index}: name is blank")
    if card["race"] not in CARD_RACES: errors.append(f"{label}: race must be Any, Human, or Orc")
    if card["action"] not in CARD_ACTIONS: errors.append(f"{label}: unsupported card action {card['action']!r}")
    if card["target"] not in CARD_TARGETS: errors.append(f"{label}: unsupported target mode {card['target']!r}")
    if not 0 <= int(card["slot"]) <= 31: errors.append(f"{label}: slot must be 0-31")
    if any(not 0 <= value <= 109 for value in card["producer_types"]): errors.append(f"{label}: producer IDs must be 0-109")
    if card["hotkey"] and card["hotkey"] not in _HOTKEYS: errors.append(f"{label}: unsupported hotkey {card['hotkey']!r}")
    if card["action"] == "Train Unit" and not 0 <= int(card["unit_type"]) <= 57: errors.append(f"{label}: trained unit must be ID 0-57")
    if card["action"] in {"Build Structure", "Upgrade Building"} and not 58 <= int(card["building_type"]) <= 104: errors.append(f"{label}: building must be ID 58-104")
    if float(card.get("seconds", 0)) < 0: errors.append(f"{label}: production time cannot be negative")
    for key in ("gold_cost", "lumber_cost", "oil_cost"):
        if int(card[key]) < -1: errors.append(f"{label}: {key.replace('_', ' ')} must be -1 (native/default) or higher")
    if card["action"] == "Cast Custom Ability" and not card["ability_id"]: errors.append(f"{label}: custom ability ID is blank")
    if card["action"] == "Run Trigger Function":
        if not card["trigger"]: errors.append(f"{label}: trigger function is blank")
        try:
            value = json.loads(card["arguments_json"])
            if not isinstance(value, dict): raise TypeError
        except Exception: errors.append(f"{label}: function arguments must be a JSON object")
    return errors


def validate_cards(cards: Any) -> list[str]:
    if not isinstance(cards, list): return ["Command cards must be stored as a list"]
    errors: list[str] = []; ids: set[str] = set()
    for index, raw in enumerate(cards, 1):
        errors.extend(validate_card_definition(raw, index))
        cid = normalize_card(raw, index)["id"].casefold()
        if cid in ids: errors.append(f"Duplicate command card ID: {cid}")
        ids.add(cid)
    return errors


def _friendly(token: str, fallback: str) -> str:
    text = str(token).removeprefix("STR_").removeprefix("BTN_")
    words = text.replace("_1", "").replace("_", " ").strip().title()
    return words or fallback


def _source_upgrade(symbol: str) -> str:
    body = symbol.removeprefix("UG_")
    body = re.sub(r"[12]$", "", body)
    return SOURCE_UPGRADES.get(body, "Melee Attack")


def _catalog_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "War2_Command_Cards.json"


def stock_cards() -> list[dict[str, Any]]:
    """Return all 418 source card rows as editable trigger-card definitions."""
    raw = json.loads(_catalog_path().read_text(encoding="utf-8"))
    card_owners: dict[str, set[int]] = {}
    for unit_type, array_name in enumerate(raw.get("cards", [])):
        if array_name and unit_type <= 109: card_owners.setdefault(str(array_name), set()).add(unit_type)
    result: list[dict[str, Any]] = []
    for array_name, rows in raw.get("arrays", {}).items():
        race = "Human" if str(array_name).startswith("sgH") else "Orc" if str(array_name).startswith("sgO") else "Any"
        for row_index, row in enumerate(rows):
            if len(row) < 8: continue
            callback = str(row[3]); parameter = str(row[5]); card = new_card(len(result) + 1)
            card.update({
                "id": f"stock.{array_name}.{row_index}", "name": _friendly(str(row[6]), f"{array_name} {row_index + 1}"),
                "description": f"Source command row {array_name}[{row_index}] using {callback}.",
                "race": race, "page": str(array_name), "slot": _int(row[0]), "icon": str(row[1]),
                "producer_types": sorted(card_owners.get(str(array_name), set())), "source_array": str(array_name),
                "source_row": row_index, "source_callback": callback, "visibility_callback": str(row[2]),
                "visibility_parameter": str(row[4]), "action_parameter": parameter,
                "tooltip_token": str(row[6]), "target_mask": str(row[7]), "action": "Source Callback",
            })
            if callback == "bldg_build_man" and parameter in SOURCE_UNIT_IDS:
                card.update(action="Train Unit", unit_type=SOURCE_UNIT_IDS[parameter], seconds=1.0)
            elif callback == "order_place" and parameter in SOURCE_UNIT_IDS:
                card.update(action="Build Structure", building_type=SOURCE_UNIT_IDS[parameter])
            elif callback == "bldg_build_upgrade" and parameter in SOURCE_UNIT_IDS:
                card.update(action="Upgrade Building", building_type=SOURCE_UNIT_IDS[parameter])
            elif callback == "bldg_build_spell" and parameter in SOURCE_SPELLS:
                card.update(action="Research Spell", spell=SOURCE_SPELLS[parameter], seconds=1.0)
            elif callback == "bldg_build_tech":
                card.update(action="Research Upgrade", upgrade=_source_upgrade(parameter), seconds=1.0)
            elif callback == "order_spell" and parameter in SOURCE_ORDER_SPELLS:
                spell = SOURCE_ORDER_SPELLS[parameter]
                card.update(action="Cast Native Spell", spell=spell, target=SPELL_TARGETS[spell])
            result.append(normalize_card(card, len(result) + 1))
    return result


def enable_cross_faction(cards: list[dict[str, Any]]) -> int:
    """Add the opposite-race producer to every racial source-card definition."""
    changed = 0
    for index, raw in enumerate(cards):
        card = normalize_card(raw, index + 1)
        if card["race"] not in {"Human", "Orc"}: continue
        expanded = set(card["producer_types"])
        expanded.update(RACE_COUNTERPARTS[value] for value in list(expanded) if value in RACE_COUNTERPARTS)
        if expanded != set(card["producer_types"]) or not card["allow_cross_faction"]:
            card["producer_types"] = sorted(expanded); card["allow_cross_faction"] = True
            cards[index] = card; changed += 1
    return changed


def duplicate_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [deepcopy(normalize_card(card, index + 1)) for index, card in enumerate(cards)]
