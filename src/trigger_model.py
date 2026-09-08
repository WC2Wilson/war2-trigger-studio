from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from feature_metadata import canonical_kind
from ability_defs import normalize_ability, validate_abilities
from card_defs import normalize_card, validate_cards

SCHEMA = "war2-trigger-sidecar"
VERSION = 4
SUPPORTED_VERSIONS = {1, 2, 3, 4}


@dataclass
class Location:
    name: str
    left: int
    top: int
    right: int
    bottom: int

    def normalize(self) -> None:
        self.left, self.right = sorted((int(self.left), int(self.right)))
        self.top, self.bottom = sorted((int(self.top), int(self.bottom)))


@dataclass
class Clause:
    kind: str
    args: dict[str, Any] = field(default_factory=dict)


@dataclass
class Trigger:
    name: str = "New Trigger"
    players: list[int] = field(default_factory=lambda: [0])
    conditions: list[Clause] = field(default_factory=list)
    actions: list[Clause] = field(default_factory=list)
    preserved: bool = False
    enabled: bool = True
    comment: str = ""
    # All = classic StarCraft AND behavior. Any enables an OR-style trigger.
    condition_mode: str = "All"
    # Trigger-level timing is handled by TriggerEngine. It never blocks Warcraft's
    # main thread and is safe to use with delayed action sequences.
    start_delay: float = 0.0
    repeat_interval: float = 1.0
    max_runs: int = 1  # 0 means unlimited; only used when preserved is true.


@dataclass
class Scenario:
    map_file: str = ""
    locations: list[Location] = field(default_factory=list)
    triggers: list[Trigger] = field(default_factory=list)
    # These are initial values. The live runtime owns mutable copies while a run
    # is active. Keeping them in the sidecar makes RPG/defense maps portable.
    variables: dict[str, Any] = field(default_factory=dict)
    timers: dict[str, float] = field(default_factory=dict)
    forces: dict[str, list[int]] = field(default_factory=dict)
    objectives: dict[str, str] = field(default_factory=dict)
    # Version 3: portable definitions consumed by the Custom Ability Engine.
    # Runtime cooldowns, charges, grants, and targeting state are intentionally
    # transient and are reset when a trigger run starts.
    abilities: list[dict[str, Any]] = field(default_factory=list)
    # Version 4: source-catalog and custom command cards. Runtime grants,
    # hotkey edges, and production tasks are intentionally transient.
    cards: list[dict[str, Any]] = field(default_factory=list)

    def validate(self) -> list[str]:
        errors: list[str] = []
        errors.extend(validate_abilities(self.abilities))
        errors.extend(validate_cards(self.cards))
        names: set[str] = set()
        for i, loc in enumerate(self.locations):
            loc.normalize()
            if not loc.name.strip():
                errors.append(f"Location {i + 1} has no name")
            if loc.name.casefold() in names:
                errors.append(f"Duplicate location: {loc.name}")
            names.add(loc.name.casefold())
        trigger_names: set[str] = set()
        for i, trig in enumerate(self.triggers):
            if not trig.name.strip():
                errors.append(f"Trigger {i + 1} has no name")
            folded = trig.name.strip().casefold()
            if folded in trigger_names:
                errors.append(f"Duplicate trigger name: {trig.name}")
            trigger_names.add(folded)
            if not trig.players:
                errors.append(f"{trig.name}: no executing players")
            if not trig.conditions:
                errors.append(f"{trig.name}: no conditions (use Always explicitly)")
            if not trig.actions:
                errors.append(f"{trig.name}: no actions")
            if str(trig.condition_mode) not in {"All", "Any"}:
                errors.append(f"{trig.name}: condition mode must be All or Any")
            if float(trig.start_delay) < 0:
                errors.append(f"{trig.name}: start delay cannot be negative")
            if float(trig.repeat_interval) < 0:
                errors.append(f"{trig.name}: repeat interval cannot be negative")
            if int(trig.max_runs) < 0:
                errors.append(f"{trig.name}: max runs cannot be negative")
            if trig.preserved and float(trig.repeat_interval) == 0:
                errors.append(
                    f"{trig.name}: repeating with a zero-second interval would run every engine cycle; "
                    "use at least 0.25 seconds"
                )
        for name, players in self.forces.items():
            if not str(name).strip():
                errors.append("A Force has no name")
            if not players:
                errors.append(f"Force {name}: no players")
            if any(not 0 <= int(player) <= 15 for player in players):
                errors.append(f"Force {name}: player outside P1-P16")

        location_names = {loc.name for loc in self.locations}
        trigger_names_exact = {trig.name.strip().casefold() for trig in self.triggers}
        ability_ids = {str(normalize_ability(item, index).get("id", "")).casefold() for index, item in enumerate(self.abilities, 1)}
        card_ids = {str(normalize_card(item, index).get("id", "")).casefold() for index, item in enumerate(self.cards, 1)}
        for ability_index, raw_ability in enumerate(self.abilities, 1):
            ability = normalize_ability(raw_ability, ability_index)
            for effect_index, effect in enumerate(ability.get("effects", []), 1):
                if str(effect.get("kind")) != "Run Trigger Function":
                    continue
                target = str(effect.get("trigger", "")).strip()
                if not target or target.casefold() not in trigger_names_exact:
                    errors.append(f"{ability.get('name', ability.get('id'))}: effect {effect_index} references unknown trigger function {target!r}")
                    continue
                target_trigger = next(item for item in self.triggers if item.name.strip().casefold() == target.casefold())
                forbidden = [action.kind for action in target_trigger.actions if action.kind in {"Wait", "Random Wait", "Breakpoint"}]
                if forbidden:
                    errors.append(f"{ability.get('name', ability.get('id'))}: effect {effect_index} function {target!r} contains asynchronous action {forbidden[0]}")
        for card_index, raw_card in enumerate(self.cards, 1):
            card = normalize_card(raw_card, card_index)
            if card.get("action") == "Run Trigger Function":
                target = str(card.get("trigger", "")).strip()
                if not target or target.casefold() not in trigger_names_exact:
                    errors.append(f"{card.get('name', card.get('id'))}: references unknown trigger function {target!r}")
                else:
                    target_trigger = next(item for item in self.triggers if item.name.strip().casefold() == target.casefold())
                    forbidden = [action.kind for action in target_trigger.actions if action.kind in {"Wait", "Random Wait", "Breakpoint"}]
                    if forbidden: errors.append(f"{card.get('name', card.get('id'))}: function {target!r} contains asynchronous action {forbidden[0]}")
            if card.get("action") == "Cast Custom Ability" and str(card.get("ability_id", "")).casefold() not in ability_ids:
                errors.append(f"{card.get('name', card.get('id'))}: references unknown custom ability {card.get('ability_id')!r}")
        location_fields = {
            "location", "source_location", "destination", "spawn_location",
            "count_location", "attacker_location", "caster_location",
            "target_location", "unit_location", "retreat_location",
            "anchor_location", "start_location",
        }
        trigger_ref_kinds = {"Enable Trigger", "Disable Trigger", "Toggle Trigger", "Reset Trigger", "Run Trigger", "Trigger Enabled", "Run Trigger For Each Unit In Group", "Run Trigger For Each Player", "Call Trigger Function"}
        for trig in self.triggers:
            for clause in [*trig.conditions, *trig.actions]:
                if clause.kind in trigger_ref_kinds:
                    target = str(clause.args.get("trigger", "")).strip()
                    if not target or target.casefold() not in trigger_names_exact:
                        errors.append(f"{trig.name}: {clause.kind} references unknown trigger {target!r}")
                for field_name in location_fields:
                    if field_name not in clause.args:
                        continue
                    value = str(clause.args.get(field_name, "Anywhere"))
                    if value and value != "Anywhere" and value not in location_names:
                        errors.append(f"{trig.name}: {clause.kind} references unknown location {value!r}")
                source_destination_point_kinds = {
                    "Source Attack Area", "Source Attack Ground", "Source Attack Wall",
                    "Source Patrol Move", "Source Demolish", "Source Harvest",
                    "Source Unload All", "Source Find Walkable Point",
                    "Source Find Buildable Point", "Source Location Walkable",
                    "Source Location Buildable", "Source Play Explosion Sound At Point",
                    "Source Create Projectile At Point", "Source Create Explosion Projectile",
                    "Source Order Worker To Build", "Source Place Building Foundation",
                    "Source Find Nearest Building Site", "Source Find Shore Point",
                    "Source Find Dock Point", "Source Find Undock Point",
                    "Source Reveal Radius", "Source Begin Tree Harvest",
                    "Source Tree Is Reachable", "Source Unit Can Reach Location",
                    "Source Locations On Same Island", "Source Trigger Rune",
                    "Source Set Rune Lifetime", "Source Remove Rune", "Source Place Rune",
                    "Source Projectile Hit Location", "Source Set Projectile Target",
                    "Source Create Tower Projectile", "Source Create Fire Projectile",
                    "Source Create Flame Spin", "Source Create Black X Marker",
                    "Source Create Stationary Projectile", "Source Show Minimap Marker",
                    "Source Set Local Camera",
                }
                source_location_point_kinds = {
                    "Source Tile Value", "Source Tile Is Tree", "Source Tile Is Rock",
                    "Source Tile Is Wall", "Source Tile Is Demolishable",
                    "Source Location Is Visible", "Source Location Is Explored",
                    "Source Tile Region Type", "Source Wall Is Connected",
                    "Source Rune Exists At Location", "Source Rune Owner",
                    "Source Rune Lifetime",
                }
                source_terrain_kinds = {
                    "Source Set Tiles", "Source Remove Trees", "Source Remove Rocks",
                    "Source Place Walls", "Source Destroy Walls",
                    "Source Damage Terrain", "Source Native Demolish Tile",
                    "Source Remove Terrain Region", "Source Rebuild Wall Connections",
                    "Source Rebuild Shore Regions", "Source Refresh Terrain Pathing",
                    "Source Reveal Area For Player", "Source Find Reachable Tree",
                    "Source Find Nearest Reachable Tree",
                }
                source_filtered_tile_kinds = {
                    "Source Tile Is Tree", "Source Tile Is Rock", "Source Tile Is Wall",
                    "Source Tile Is Demolishable", "Source Remove Trees",
                    "Source Remove Rocks", "Source Destroy Walls",
                    "Source Find Reachable Tree", "Source Find Nearest Reachable Tree",
                }
                campaign_destination_point_kinds = {
                    "Scene Actor Walk", "Scene Actor Patrol", "Scene Actor Attack",
                    "Scene Actor Teleport", "Scene Camera Cut", "Scene Camera Pan",
                    "Scene Play Sound", "Scene Wait For Actor At Location",
                    "Scene Wait For All Actors At Location", "Scene Group Move",
                    "Scene Group Attack", "Scene Group Patrol",
                    "Scene Actor Cast Spell At Point", "Scene Actor Build Building",
                }
                campaign_location_point_kinds = {
                    "Scene Create Actor", "Scene Actor At Location",
                    "Campaign All Actors In Location",
                }
                mission132_location_point_kinds = {
                    "Deal Native Area Damage", "Damage Units Around Point",
                    "Add Campaign Dot", "Pulse Campaign Location", "Cast Ability At Point",
                }
                ability_reference_actions = {
                    "Grant Ability", "Revoke Ability", "Enable Ability", "Disable Ability",
                    "Begin Ability Targeting", "Cast Ability", "Cast Ability At Point",
                    "Cast Ability On Unit", "Reset Ability Cooldown", "Set Ability Charges",
                    "Add Ability Charges", "Show Ability Card",
                }
                if clause.kind in ability_reference_actions:
                    ability_id = str(clause.args.get("ability_id", "")).strip().casefold()
                    if not ability_id or ability_id not in ability_ids:
                        errors.append(f"{trig.name}: {clause.kind} references unknown custom ability {clause.args.get('ability_id', '')!r}")
                card_reference_clauses = {
                    "Card Defined", "Producer Has Card", "Card Available", "Card Clicked",
                    "Card Production Started", "Card Production Finished", "Card Production Failed",
                    "Card Production Active", "Card Click Count", "Grant Card", "Revoke Card",
                    "Enable Card", "Disable Card", "Activate Card",
                }
                if clause.kind in card_reference_clauses:
                    card_id = str(clause.args.get("card_id", "")).strip().casefold()
                    if not card_id or card_id not in card_ids:
                        errors.append(f"{trig.name}: {clause.kind} references unknown command card {clause.args.get('card_id', '')!r}")
                if clause.kind in campaign_destination_point_kinds:
                    destination = str(clause.args.get("destination", "Anywhere"))
                    # Scene Actor Attack may use a named target actor instead of a point.
                    has_actor_target = clause.kind == "Scene Actor Attack" and bool(str(clause.args.get("target_actor", "")).strip())
                    # Scene Play Sound may use an actor instead of a point.
                    has_sound_actor = clause.kind == "Scene Play Sound" and bool(str(clause.args.get("actor", "")).strip())
                    if destination == "Anywhere" and not has_actor_target and not has_sound_actor and ("x" not in clause.args or "y" not in clause.args):
                        errors.append(f"{trig.name}: {clause.kind} at Anywhere requires X and Y")
                if clause.kind in campaign_location_point_kinds:
                    destination = str(clause.args.get("location", "Anywhere"))
                    if destination == "Anywhere" and ("x" not in clause.args or "y" not in clause.args):
                        errors.append(f"{trig.name}: {clause.kind} at Anywhere requires X and Y")

                if clause.kind in mission132_location_point_kinds:
                    destination = str(clause.args.get("location", "Anywhere"))
                    if destination == "Anywhere" and ("x" not in clause.args or "y" not in clause.args):
                        errors.append(f"{trig.name}: {clause.kind} at Anywhere requires X and Y")
                if clause.kind == "Draw Campaign Route":
                    route_names = [x.strip() for x in str(clause.args.get("locations", "")).replace(";", ",").split(",") if x.strip()]
                    if not route_names:
                        errors.append(f"{trig.name}: Draw Campaign Route requires one or more location names")
                    for route_name in route_names:
                        if route_name not in location_names:
                            errors.append(f"{trig.name}: Draw Campaign Route references unknown location {route_name!r}")

                if clause.kind in source_destination_point_kinds:
                    destination = str(clause.args.get("destination", "Anywhere"))
                    if destination == "Anywhere" and ("x" not in clause.args or "y" not in clause.args):
                        errors.append(f"{trig.name}: {clause.kind} at Anywhere requires X and Y")
                if clause.kind in source_location_point_kinds:
                    destination = str(clause.args.get("location", "Anywhere"))
                    if destination == "Anywhere" and ("x" not in clause.args or "y" not in clause.args):
                        errors.append(f"{trig.name}: {clause.kind} at Anywhere requires X and Y")
                if clause.kind in source_terrain_kinds:
                    destination = str(clause.args.get("location", "Anywhere"))
                    if destination == "Anywhere" and ("x" not in clause.args or "y" not in clause.args):
                        errors.append(f"{trig.name}: {clause.kind} at Anywhere requires top-left X and Y")
                    try:
                        if int(clause.args.get("width", 1)) <= 0 or int(clause.args.get("height", 1)) <= 0:
                            errors.append(f"{trig.name}: {clause.kind} width and height must be positive")
                    except (TypeError, ValueError):
                        errors.append(f"{trig.name}: {clause.kind} width and height must be integers")
                if clause.kind in source_filtered_tile_kinds:
                    raw_tiles = str(clause.args.get("tile_values", "")).strip()
                    if not raw_tiles:
                        errors.append(f"{trig.name}: {clause.kind} requires one or more MTXM Tile values")
                    else:
                        try:
                            [int(part.strip(), 0) for part in raw_tiles.replace(";", ",").split(",") if part.strip()]
                        except ValueError:
                            errors.append(f"{trig.name}: {clause.kind} Tile values must be decimal or 0x-prefixed integers")
                if clause.kind == "Source Set Production Progress":
                    try:
                        percent = int(clause.args.get("percent", 50))
                        if not 0 <= percent <= 100:
                            errors.append(f"{trig.name}: Source Set Production Progress percent must be 0-100")
                    except (TypeError, ValueError):
                        errors.append(f"{trig.name}: Source Set Production Progress percent must be an integer")
                if clause.kind in {"Source Play Animation", "Source Freeze Animation"}:
                    for key, high in (("animation", 255), ("frame", 255), ("facing", 7)):
                        if key not in clause.args or clause.args.get(key) in (None, ""):
                            continue
                        try:
                            value = int(clause.args[key])
                            if not 0 <= value <= high:
                                errors.append(f"{trig.name}: {clause.kind} {key} must be 0-{high}")
                        except (TypeError, ValueError):
                            errors.append(f"{trig.name}: {clause.kind} {key} must be an integer")
                if clause.kind == "Create Wave":
                    if not str(clause.args.get("amount_expression", "")).strip():
                        errors.append(f"{trig.name}: Create Wave amount expression is blank")
                    if str(clause.args.get("order", "Attack")) != "None":
                        destination = str(clause.args.get("destination", "Anywhere"))
                        if destination == "Anywhere" and ("destination_x" not in clause.args or "destination_y" not in clause.args):
                            errors.append(f"{trig.name}: Create Wave at Anywhere requires destination X and Y")
                if clause.kind in {"Create Units", "Create Completed Buildings"}:
                    if str(clause.args.get("location", "Anywhere")) == "Anywhere" and ("x" not in clause.args or "y" not in clause.args):
                        errors.append(f"{trig.name}: {clause.kind} at Anywhere requires X and Y")
                if clause.kind == "Create Sapper Assault":
                    if str(clause.args.get("spawn_location", "Anywhere")) == "Anywhere" and ("spawn_x" not in clause.args or "spawn_y" not in clause.args):
                        errors.append(f"{trig.name}: Create Sapper Assault at Anywhere requires spawn X and Y")
                    unit = clause.args.get("unit", 14)
                    try:
                        unit = int(unit)
                    except (TypeError, ValueError):
                        unit = -1
                    if unit not in {14, 15}:
                        errors.append(f"{trig.name}: Create Sapper Assault unit must be Dwarves (14) or Goblins (15)")
                if clause.kind == "Order Sappers Demolish":
                    if str(clause.args.get("destination", "Anywhere")) == "Anywhere" and ("x" not in clause.args or "y" not in clause.args):
                        errors.append(f"{trig.name}: Order Sappers Demolish at Anywhere requires X and Y")
                if clause.kind == "Start TD Stream Wave":
                    if str(clause.args.get("spawn_location", "Anywhere")) == "Anywhere" and ("spawn_x" not in clause.args or "spawn_y" not in clause.args):
                        errors.append(f"{trig.name}: Start TD Stream Wave at Anywhere requires spawn X and Y")
                    try:
                        total = int(clause.args.get("total", 200))
                        batch = int(clause.args.get("batch_size", 3))
                        max_hp = int(clause.args.get("max_hp", 100))
                        lanes = int(clause.args.get("lane_count", 3))
                        if total <= 0:
                            errors.append(f"{trig.name}: Start TD Stream Wave total must be positive")
                        if not 1 <= batch <= 32:
                            errors.append(f"{trig.name}: Start TD Stream Wave batch_size must be 1-32")
                        if not 1 <= max_hp <= 65535:
                            errors.append(f"{trig.name}: Start TD Stream Wave max_hp must be 1-65535")
                        if lanes not in {1, 3, 5}:
                            errors.append(f"{trig.name}: Start TD Stream Wave lane_count must be 1, 3, or 5")
                    except (TypeError, ValueError):
                        errors.append(f"{trig.name}: Start TD Stream Wave numeric fields are invalid")
                    raw_roster = clause.args.get("unit_roster_json", "")
                    if raw_roster not in (None, "", []):
                        try:
                            roster = json.loads(raw_roster) if isinstance(raw_roster, str) else raw_roster
                            if not isinstance(roster, list) or not roster or any(not 0 <= int(value) <= 57 for value in roster):
                                raise TypeError
                        except Exception:
                            errors.append(f"{trig.name}: Start TD Stream Wave unit_roster_json must be a non-empty JSON list of unit IDs 0-57")
                    raw_route = clause.args.get("route_json", "[]")
                    try:
                        route = json.loads(raw_route) if isinstance(raw_route, str) else raw_route
                        if not isinstance(route, list) or not route:
                            raise TypeError
                    except Exception:
                        errors.append(f"{trig.name}: Start TD Stream Wave route_json must be a non-empty JSON list")
                if clause.kind == "Start TD Native HP Ladder":
                    if str(clause.args.get("spawn_location", "Anywhere")) == "Anywhere" and ("spawn_x" not in clause.args or "spawn_y" not in clause.args):
                        errors.append(f"{trig.name}: Start TD Native HP Ladder at Anywhere requires spawn X and Y")
                    try:
                        total_start = int(clause.args.get("total_start", 160))
                        total_growth = int(clause.args.get("total_growth", 5))
                        batch = int(clause.args.get("batch_size", 4))
                        interval = float(clause.args.get("interval", 0.30))
                        lanes = int(clause.args.get("lane_count", 3))
                        hp_start = float(clause.args.get("hp_scale_start_percent", 150.0))
                        hp_growth = float(clause.args.get("hp_scale_growth_percent", 10.0))
                        floor_start = int(clause.args.get("hp_floor_start", 80))
                        floor_growth = int(clause.args.get("hp_floor_growth", 15))
                        if total_start <= 0:
                            errors.append(f"{trig.name}: Start TD Native HP Ladder total_start must be positive")
                        if total_growth < 0:
                            errors.append(f"{trig.name}: Start TD Native HP Ladder total_growth cannot be negative")
                        if not 1 <= batch <= 32:
                            errors.append(f"{trig.name}: Start TD Native HP Ladder batch_size must be 1-32")
                        if interval < 0.20:
                            errors.append(f"{trig.name}: Start TD Native HP Ladder interval must be at least 0.20 seconds")
                        if lanes not in {1, 3, 5}:
                            errors.append(f"{trig.name}: Start TD Native HP Ladder lane_count must be 1, 3, or 5")
                        if hp_start < 100 or hp_growth < 0:
                            errors.append(f"{trig.name}: Start TD Native HP Ladder HP scale must start at >=100% with non-negative growth")
                        if floor_start <= 0 or floor_growth < 0:
                            errors.append(f"{trig.name}: Start TD Native HP Ladder HP floor must be positive with non-negative growth")
                    except (TypeError, ValueError):
                        errors.append(f"{trig.name}: Start TD Native HP Ladder numeric fields are invalid")
                    raw_unused = clause.args.get("unused_unit_ids_json", "[34,36,37,48,54]")
                    try:
                        unused = json.loads(raw_unused) if isinstance(raw_unused, str) else raw_unused
                        if not isinstance(unused, list) or any(not 0 <= int(value) <= 57 for value in unused):
                            raise TypeError
                    except Exception:
                        errors.append(f"{trig.name}: Start TD Native HP Ladder unused_unit_ids_json must be a JSON list of IDs 0-57")
                    raw_route = clause.args.get("route_json", "[]")
                    try:
                        route = json.loads(raw_route) if isinstance(raw_route, str) else raw_route
                        if not isinstance(route, list) or not route:
                            raise TypeError
                    except Exception:
                        errors.append(f"{trig.name}: Start TD Native HP Ladder route_json must be a non-empty JSON list")
                if clause.kind == "Start Wave Director":
                    if str(clause.args.get("spawn_location", "Anywhere")) == "Anywhere" and ("spawn_x" not in clause.args or "spawn_y" not in clause.args):
                        errors.append(f"{trig.name}: Start Wave Director at Anywhere requires spawn X and Y")
                    if str(clause.args.get("destination", "Anywhere")) == "Anywhere" and ("destination_x" not in clause.args or "destination_y" not in clause.args):
                        errors.append(f"{trig.name}: Start Wave Director at Anywhere requires destination X and Y")
                if clause.kind == "Start Boss Controller":
                    raw = clause.args.get("phases_json", "[]")
                    try:
                        phases = json.loads(raw) if isinstance(raw, str) else raw
                        if not isinstance(phases, list):
                            raise TypeError
                    except Exception:
                        errors.append(f"{trig.name}: Start Boss Controller phases_json must be a JSON list")
                if clause.kind == "Call Trigger Function":
                    target_name = str(clause.args.get("trigger", "")).strip().casefold()
                    target = next((candidate for candidate in self.triggers if candidate.name.strip().casefold() == target_name), None)
                    if target is not None:
                        forbidden = [action.kind for action in target.actions if action.kind in {"Wait", "Random Wait", "Breakpoint"}]
                        if forbidden:
                            errors.append(f"{trig.name}: function {target.name!r} contains asynchronous action {forbidden[0]}")
                    raw = clause.args.get("arguments_json", "{}")
                    try:
                        value = json.loads(raw) if isinstance(raw, str) else raw
                        if not isinstance(value, dict):
                            raise TypeError
                    except Exception:
                        errors.append(f"{trig.name}: Call Trigger Function arguments_json must be a JSON object")
                if clause.kind == "Register Shop Item":
                    raw = clause.args.get("bonuses_json", "{}")
                    try:
                        value = json.loads(raw) if isinstance(raw, str) else raw
                        if not isinstance(value, dict):
                            raise TypeError
                    except Exception:
                        errors.append(f"{trig.name}: Register Shop Item bonuses_json must be a JSON object")
                if clause.kind == "Start Vote":
                    raw = clause.args.get("options", "[]")
                    try:
                        value = json.loads(raw) if isinstance(raw, str) and raw.strip().startswith("[") else [item.strip() for item in str(raw).split(",") if item.strip()]
                        if not isinstance(value, list) or len(value) < 2:
                            raise TypeError
                    except Exception:
                        errors.append(f"{trig.name}: Start Vote requires at least two options")
                if clause.kind == "Start Reinforcement Director":
                    raw = clause.args.get("stages_json", "[]")
                    try:
                        stages = json.loads(raw) if isinstance(raw, str) else raw
                        if not isinstance(stages, list) or any(not isinstance(stage, dict) for stage in stages):
                            raise TypeError
                    except Exception:
                        errors.append(f"{trig.name}: Start Reinforcement Director stages_json must be a JSON list of objects")
                        stages = []
                    for stage_index, stage in enumerate(stages):
                        waves = stage.get("waves", [])
                        if not isinstance(waves, list):
                            errors.append(f"{trig.name}: reinforcement stage {stage_index + 1} waves must be a list")
                            continue
                        for wave_index, wave in enumerate(waves):
                            if not isinstance(wave, dict):
                                errors.append(f"{trig.name}: reinforcement stage {stage_index + 1} wave {wave_index + 1} must be an object")
                                continue
                            for field_name in ("spawn_location", "destination"):
                                location = str(wave.get(field_name, "Anywhere"))
                                if location != "Anywhere" and location not in location_names:
                                    errors.append(f"{trig.name}: reinforcement stage {stage_index + 1} wave {wave_index + 1} references unknown location {location!r}")
                            if str(wave.get("spawn_location", "Anywhere")) == "Anywhere" and ("spawn_x" not in wave or "spawn_y" not in wave):
                                errors.append(f"{trig.name}: reinforcement stage {stage_index + 1} wave {wave_index + 1} at Anywhere requires spawn_x and spawn_y")
                            if str(wave.get("order", "Attack")) != "None" and str(wave.get("destination", "Anywhere")) == "Anywhere" and ("destination_x" not in wave or "destination_y" not in wave):
                                errors.append(f"{trig.name}: reinforcement stage {stage_index + 1} wave {wave_index + 1} requires destination_x and destination_y")
        return errors

    def warnings(self) -> list[str]:
        warnings: list[str] = []
        for trig in self.triggers:
            called = any(action.kind == "Run Trigger" for action in trig.actions)
            if called and not trig.preserved and trig.max_runs == 1:
                pass
            if "spawn" in trig.name.casefold() and not any(action.kind in {"Create Units", "Create Completed Buildings", "Create Wave", "Create Units At Event", "Create Sapper Assault", "Start Wave Director", "Train Units Instantly At Buildings", "Start Reinforcement Director"} for action in trig.actions):
                warnings.append(f"{trig.name}: name suggests spawning, but it contains no creation action")
            if any(condition.kind in {"Unit Created", "Unit Damaged", "Unit Healed", "Unit Under Attack", "Command", "Bring"} for condition in trig.conditions):
                if not any(action.kind in {"Create Units", "Create Completed Buildings", "Create Wave", "Create Units At Event", "Create Sapper Assault", "Start Wave Director", "Train Units Instantly At Buildings", "Start Reinforcement Director"} for source in self.triggers for action in source.actions):
                    warnings.append(f"{trig.name}: waits for live units, but this sidecar contains no unit-creation action; it depends on units already present in the map")
        return sorted(set(warnings))

    def canonicalize_aliases(self) -> int:
        changed = 0
        for trigger in self.triggers:
            for clause in trigger.conditions:
                canonical = canonical_kind("condition", clause.kind)
                if canonical != clause.kind:
                    clause.kind = canonical; changed += 1
            for clause in trigger.actions:
                canonical = canonical_kind("action", clause.kind)
                if canonical != clause.kind:
                    clause.kind = canonical; changed += 1
        return changed

    def save(self, path: str | Path) -> None:
        self.canonicalize_aliases()
        payload = {"schema": SCHEMA, "version": VERSION, **asdict(self)}
        Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "Scenario":
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        version = int(raw.get("version", 1))
        if raw.get("schema") != SCHEMA or version not in SUPPORTED_VERSIONS:
            raise ValueError("Unsupported Warcraft II trigger sidecar schema/version")

        triggers: list[Trigger] = []
        for item in raw.get("triggers", []):
            preserved = bool(item.get("preserved", False))
            # Old sidecars had only Preserve Trigger. Preserve their old behavior:
            # preserved triggers repeat forever, one-shot triggers run once.
            default_max_runs = 0 if preserved else 1
            triggers.append(Trigger(
                name=item.get("name", "New Trigger"),
                players=[int(x) for x in item.get("players", [0])],
                conditions=[Clause(canonical_kind("condition", str(x.get("kind", "Always"))), dict(x.get("args", {}))) for x in item.get("conditions", [])],
                actions=[Clause(canonical_kind("action", str(x.get("kind", "Comment"))), dict(x.get("args", {}))) for x in item.get("actions", [])],
                preserved=preserved,
                enabled=bool(item.get("enabled", True)),
                comment=item.get("comment", ""),
                condition_mode=str(item.get("condition_mode", "All")),
                start_delay=float(item.get("start_delay", 0.0)),
                repeat_interval=float(item.get("repeat_interval", 1.0)),
                max_runs=int(item.get("max_runs", default_max_runs)),
            ))
        raw_abilities = raw.get("abilities", [])
        if not isinstance(raw_abilities, list):
            raise ValueError("Custom abilities must be a JSON list")
        raw_cards = raw.get("cards", [])
        if not isinstance(raw_cards, list):
            raise ValueError("Command cards must be a JSON list")
        return cls(
            map_file=raw.get("map_file", ""),
            locations=[Location(**x) for x in raw.get("locations", [])],
            triggers=triggers,
            variables=dict(raw.get("variables", {})),
            timers={str(k): float(v) for k, v in dict(raw.get("timers", {})).items()},
            forces={str(k): [int(x) for x in v] for k, v in dict(raw.get("forces", {})).items()},
            objectives={str(k): str(v) for k, v in dict(raw.get("objectives", {})).items()},
            abilities=[normalize_ability(item, index) for index, item in enumerate(raw_abilities, 1)],
            cards=[normalize_card(item, index) for index, item in enumerate(raw_cards, 1)],
        )
