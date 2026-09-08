from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import random
import time
from typing import Any

from engine import FunctionReturn
from massive_features import MASSIVE_UNHANDLED, MassiveFeatureMixin, ORDER_ACTIONS, STATUS_OFFSETS
from ultimate_features import UltimateFeatureMixin, TimedEffect


@dataclass
class AuraState:
    name: str
    source_reference: str
    effect: str
    radius: int
    relation: str
    amount: int
    interval: float
    group: str = ""
    enabled: bool = True
    next_tick: float = 0.0
    affected: set[tuple[int, int]] = field(default_factory=set)


@dataclass
class SquadControllerState:
    name: str
    group: str
    profile: str
    formation: str
    spacing: int
    destination: str
    x: int
    y: int
    retreat_location: str
    retreat_x: int
    retreat_y: int
    retreat_morale: int
    cadence: float
    initial_count: int
    enabled: bool = True
    state: str = "Active"
    next_update: float = 0.0
    morale_override: int | None = None


@dataclass
class ReinforcementDirectorState:
    name: str
    stages: list[dict[str, Any]]
    started_at: float
    next_stage: int = 0
    enabled: bool = True
    state: str = "Active"


@dataclass
class VoteState:
    name: str
    question: str
    options: list[str]
    eligible_players: set[int]
    votes: dict[int, str] = field(default_factory=dict)
    state: str = "Open"
    winner: str = ""


class AdvancedFeatureMixin(UltimateFeatureMixin):
    """1.26 high-level world systems layered above the stable 1.25 runtime.

    These systems intentionally avoid new executable hooks. They compose the
    validated unit creation, order, resource, status, group, reference, timer,
    and trigger-engine primitives already used by the stable live adapter.
    """

    def _init_massive_features(self) -> None:
        super()._init_massive_features()
        self._function_frames: list[dict[str, Any]] = []
        self.runtime_lists: dict[str, list[Any]] = {}
        self.runtime_flags: dict[str, bool] = {}
        self.trigger_cooldowns: dict[str, float] = {}
        self.custom_currencies: dict[tuple[int, str], int] = {}
        self.shop_items: dict[str, dict[str, Any]] = {}
        self.inventory_capacity: dict[tuple[int, int], int] = {}
        self.equipment: dict[tuple[int, int], dict[str, str]] = {}
        self.auras: dict[str, AuraState] = {}
        self.squad_controllers: dict[str, SquadControllerState] = {}
        self.reinforcement_directors: dict[str, ReinforcementDirectorState] = {}
        self.votes: dict[str, VoteState] = {}
        self._advanced_next_maintenance = 0.0
        self._advanced_rng = random.Random(time.time_ns() ^ 0x1260)

    def _massive_begin_run(self) -> None:
        super()._massive_begin_run()
        self._function_frames.clear()
        self.runtime_lists.clear()
        self.runtime_flags.clear()
        self.trigger_cooldowns.clear()
        self.custom_currencies.clear()
        self.shop_items.clear()
        self.inventory_capacity.clear()
        self.equipment.clear()
        self.auras.clear()
        self.squad_controllers.clear()
        self.reinforcement_directors.clear()
        self.votes.clear()
        self._advanced_next_maintenance = 0.0

    # ------------------------------------------------------------ expressions
    def _numeric_variable(self, name: Any) -> int:
        key = str(name or "Variable 1").strip()
        if self._function_frames:
            frame = self._function_frames[-1]
            if key in frame["locals"]:
                value = frame["locals"][key]
                try:
                    return int(value)
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Local variable {key!r} is not numeric: {value!r}") from exc
        return super()._numeric_variable(key)

    def _message_function_value(self, function: str, argument_text: str, executing_player: int) -> str:
        name = function.strip().casefold().replace(" ", "_")
        argument = argument_text.strip()
        if name in {"local", "argument", "param"}:
            if not self._function_frames:
                return "0"
            return str(self._function_frames[-1]["locals"].get(argument, 0))
        if name in {"list", "runtime_list"}:
            return ", ".join(str(item) for item in self.runtime_lists.get(argument, []))
        if name in {"list_length", "list_count"}:
            return str(len(self.runtime_lists.get(argument, [])))
        if name in {"currency", "custom_currency"}:
            parts = [part.strip() for part in argument_text.split("|")]
            owner = executing_player if len(parts) < 2 or not parts[1] else max(0, int(parts[1]) - 1)
            return str(self.custom_currencies.get((owner, parts[0] or "Credits"), 0))
        if name == "shop_stock":
            return str(int(self.shop_items.get(argument, {}).get("stock", 0)))
        if name == "vote":
            vote = self.votes.get(argument)
            return vote.winner if vote and vote.winner else (vote.state if vote else "Missing")
        if name == "squad_morale":
            state = self.squad_controllers.get(argument)
            return str(self._squad_morale(state) if state else 0)
        if name in {"reinforcement_stage", "director_stage"}:
            state = self.reinforcement_directors.get(argument)
            return str(state.next_stage if state else 0)
        if name in {"flag", "runtime_flag"}:
            return "1" if self.runtime_flags.get(argument, False) else "0"
        return super()._message_function_value(function, argument_text, executing_player)

    # --------------------------------------------------------------- functions
    @staticmethod
    def _parse_object(raw: Any, label: str) -> dict[str, Any]:
        if isinstance(raw, dict):
            return dict(raw)
        text = str(raw or "{}").strip() or "{}"
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{label} must be a JSON object: {exc.msg}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{label} must be a JSON object")
        return value

    @staticmethod
    def _parse_list(raw: Any, label: str) -> list[Any]:
        if isinstance(raw, list):
            return list(raw)
        text = str(raw or "[]").strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{label} must be valid JSON or comma-separated text: {exc.msg}") from exc
            if not isinstance(value, list):
                raise ValueError(f"{label} must be a JSON list")
            return value
        return [part.strip() for part in text.split(",") if part.strip()]

    def _function_local(self, name: Any, default: Any = 0) -> Any:
        if not self._function_frames:
            return default
        return self._function_frames[-1]["locals"].get(str(name or "Local 1").strip(), default)

    # -------------------------------------------------------------- inventory
    def _reference_unit_and_key(self, reference: Any) -> tuple[Any, tuple[int, int]]:
        unit = self._resolve_unit_reference(reference)
        if unit is None:
            raise RuntimeError("The named unit reference is missing or dead")
        return unit, self._unit_key_massive(unit)

    def _hero_record(self, reference: Any) -> tuple[Any, tuple[int, int], dict[str, Any]]:
        unit, key = self._reference_unit_and_key(reference)
        state = self.hero_state.setdefault(key, {
            "level": 1, "xp": 0, "next_level_xp": 100, "growth": 1.25,
            "xp_per_kill": 10, "hp_per_level": 10,
        })
        state.setdefault("attributes", {"Strength": 0, "Agility": 0, "Intelligence": 0, "Vitality": 0})
        state.setdefault("skill_points", 0)
        state.setdefault("skills", {})
        return unit, key, state

    def _inventory_used(self, key: tuple[int, int]) -> int:
        return sum(max(0, int(amount)) for amount in self.inventory.get(key, {}).values())

    def _attribute_total(self, key: tuple[int, int], attribute: str) -> int:
        base = int(self.hero_state.get(key, {}).get("attributes", {}).get(attribute, 0))
        equipped = self.equipment.get(key, {})
        for item_name in equipped.values():
            bonuses = self.shop_items.get(item_name, {}).get("bonuses", {})
            base += int(bonuses.get(attribute, 0))
        return base

    def _currency_amount(self, owner: int, name: str) -> int:
        return max(0, int(self.custom_currencies.get((owner, name), 0)))

    def _set_currency(self, owner: int, name: str, value: int) -> None:
        if not 0 <= owner <= 15:
            raise ValueError("Custom currency owner must be Player 1 through Player 16")
        key = (owner, str(name or "Credits").strip() or "Credits")
        self.custom_currencies[key] = max(0, min(0x7FFFFFFF, int(value)))

    def _pay_price(self, owner: int, item: dict[str, Any], quantity: int) -> int:
        total = max(0, int(item.get("price", 0))) * quantity
        mode = str(item.get("currency_type", "Gold"))
        if mode in {"Gold", "Lumber", "Oil"}:
            available = self._read_resource(owner, mode)
            if available < total:
                raise RuntimeError(f"P{owner + 1} cannot afford {total} {mode}")
            self.action("Subtract Resources", {"player": owner, "resource": mode, "amount": total}, owner)
        else:
            currency = str(item.get("currency_name", "Credits"))
            available = self._currency_amount(owner, currency)
            if available < total:
                raise RuntimeError(f"P{owner + 1} cannot afford {total} {currency}")
            self._set_currency(owner, currency, available - total)
        return total

    def _refund_price(self, owner: int, item: dict[str, Any], quantity: int, percent: int) -> int:
        amount = round(max(0, int(item.get("price", 0))) * quantity * max(0, min(100, percent)) / 100)
        mode = str(item.get("currency_type", "Gold"))
        if mode in {"Gold", "Lumber", "Oil"}:
            self.action("Add Resources", {"player": owner, "resource": mode, "amount": amount}, owner)
        else:
            currency = str(item.get("currency_name", "Credits"))
            self._set_currency(owner, currency, self._currency_amount(owner, currency) + amount)
        return amount

    def _use_item(self, reference: str, item_name: str, quantity: int, player: int) -> None:
        unit, key = self._reference_unit_and_key(reference)
        bag = self.inventory.setdefault(key, {})
        available = int(bag.get(item_name, 0))
        quantity = max(1, int(quantity))
        if available < quantity:
            raise RuntimeError(f"Inventory contains only {available} x {item_name}")
        item = self.shop_items.get(item_name)
        if item is None:
            raise RuntimeError(f"Shop item {item_name!r} has no registered use effect")
        effect = str(item.get("effect", "Heal"))
        amount = max(0, int(item.get("effect_amount", 0))) * quantity
        duration = max(0.1, float(item.get("duration", 5.0)))
        if effect == "Heal":
            hp = min(self._max_hp(unit), int(unit.health) + amount)
            self._dispatch_ops([("write_word", unit.address + 0x22, hp)])
        elif effect == "Mana":
            mana = min(255, int(unit.mana) + amount)
            self._dispatch_ops([("write_bytes", unit.address + 0x26, bytes([mana]))])
        elif effect == "Experience":
            _unit, _key, state = self._hero_record(reference)
            state["xp"] = int(state.get("xp", 0)) + amount
        elif effect == "Shield":
            self._apply_custom_effect(unit, TimedEffect("Shield", time.monotonic() + duration, amount=amount))
        elif effect in STATUS_OFFSETS:
            self._write_status(unit, effect, amount or 250)
        elif effect == "Custom Currency":
            currency = str(item.get("effect_currency", "Credits"))
            self._set_currency(int(unit.owner), currency, self._currency_amount(int(unit.owner), currency) + amount)
        else:
            raise ValueError(f"Unsupported item effect: {effect}")
        bag[item_name] = available - quantity
        if bag[item_name] <= 0:
            bag.pop(item_name, None)

    # ------------------------------------------------------------------- aura
    def _players_allied(self, source_owner: int, target_owner: int) -> bool:
        if source_owner == target_owner:
            return True
        if not (0 <= source_owner <= 7 and 0 <= target_owner <= 7):
            return False
        try:
            value = int(self.pm.read_uchar(self.diplomacy_path["relations"] + source_owner * 16 + target_owner))
            return self._relation_is_allied(source_owner, target_owner, value)
        except Exception:
            return False

    def _aura_targets(self, aura: AuraState, world: list[Any]) -> tuple[Any | None, list[Any]]:
        source = self._resolve_unit_reference(aura.source_reference)
        if source is None:
            aura.affected.clear()
            return None, []
        candidates = self._group_units(aura.group) if aura.group else world
        radius_sq = max(0, int(aura.radius)) ** 2
        targets: list[Any] = []
        for unit in candidates:
            if int(unit.sflags) & 0x000F:
                continue
            allied = self._players_allied(int(source.owner), int(unit.owner))
            if aura.relation == "Allies" and not allied:
                continue
            if aura.relation == "Enemies" and allied:
                continue
            if self._distance_sq(source, unit) <= radius_sq:
                targets.append(unit)
        return source, targets[:128]

    def _pulse_aura(self, aura: AuraState, world: list[Any], now: float) -> int:
        source, targets = self._aura_targets(aura, world)
        if source is None:
            return 0
        aura.affected = {self._unit_key_massive(unit) for unit in targets}
        effect = aura.effect
        amount = max(0, int(aura.amount))
        writes: list[tuple] = []
        for unit in targets:
            if effect == "Health Regeneration":
                hp = min(self._max_hp(unit), int(unit.health) + amount)
                if hp != int(unit.health):
                    writes.append(("write_word", unit.address + 0x22, hp))
            elif effect == "Mana Regeneration":
                mana = min(255, int(unit.mana) + amount)
                if mana != int(unit.mana):
                    writes.append(("write_bytes", unit.address + 0x26, bytes([mana])))
            elif effect == "Damage":
                self._call_damage_unit(source, unit, max(1, amount))
            elif effect == "Shield":
                self._apply_custom_effect(unit, TimedEffect("Shield", now + aura.interval * 2.5, amount=max(1, amount)))
            elif effect == "Silence":
                self._apply_custom_effect(unit, TimedEffect("Silence", now + aura.interval * 2.5))
            elif effect in STATUS_OFFSETS:
                self._write_status(unit, effect, amount or 250)
        if writes:
            self._dispatch_ops(writes[:256])
        aura.next_tick = now + max(0.20, float(aura.interval))
        return len(targets)

    # ------------------------------------------------------------------ squad
    def _squad_morale(self, state: SquadControllerState | None) -> int:
        if state is None:
            return 0
        if state.morale_override is not None:
            return max(0, min(100, int(state.morale_override)))
        live = len(self._group_units(state.group))
        return max(0, min(100, round(live * 100 / max(1, state.initial_count))))

    def _location_point(self, name: str, x: int, y: int) -> tuple[int, int]:
        if name and name != "Anywhere":
            loc = self._find_location(name)
            return ((int(loc.left) + int(loc.right)) // 2, (int(loc.top) + int(loc.bottom)) // 2)
        return (max(0, min(self.map_width - 1, int(x))), max(0, min(self.map_height - 1, int(y))))

    def _rally_squad(self, state: SquadControllerState, force: bool = False) -> int:
        units = self._group_units(state.group)
        if not units:
            state.state = "Complete"
            return 0
        morale = self._squad_morale(state)
        retreat = morale <= state.retreat_morale and (state.retreat_location != "Anywhere" or state.retreat_x or state.retreat_y)
        if retreat:
            dx, dy = self._location_point(state.retreat_location, state.retreat_x, state.retreat_y)
            order = "Move"
            state.state = "Retreating"
        else:
            dx, dy = self._location_point(state.destination, state.x, state.y)
            order = "Attack" if state.profile in {"Attack", "Aggressive", "Protect Casters"} else "Move"
            state.state = "Active"
        points = self._formation_points(len(units), dx, dy, state.formation, state.spacing)
        calls: list[tuple[int, list[int]]] = []
        callback = self.order_callees["do_attack" if order == "Attack" else "do_move"]
        guarded = set(getattr(self, "_auto_spell_route_guards", set())) | set(getattr(self, "_auto_spell_parking", set()))
        for unit, (tx, ty) in zip(units, points):
            key = self._unit_key_massive(unit)
            if key in guarded or int(unit.action) in ORDER_ACTIONS["Cast Spell"]:
                continue
            if not force and int(unit.action) not in ORDER_ACTIONS["Idle"] and int(unit.target_unit):
                continue
            calls.append((self.order_callees["set_target"], [unit.address, tx, ty, 0, callback]))
            if order == "Attack":
                self._attack_routes[key] = (tx, ty)
        if calls:
            self._call_cdecl_batched(calls[:128])
        return len(calls)

    # --------------------------------------------------------- reinforcements
    def _spawn_reinforcement_stage(self, state: ReinforcementDirectorState, stage: dict[str, Any]) -> int:
        waves = stage.get("waves", [])
        if not isinstance(waves, list):
            raise ValueError("Reinforcement stage waves must be a list")
        total = 0
        for wave in waves[:64]:
            if not isinstance(wave, dict):
                continue
            owner = int(wave.get("player", 0))
            args = {
                "player": owner,
                "unit": int(wave.get("unit", 0)),
                "amount_expression": str(wave.get("amount_expression", wave.get("amount", 1))),
                "spawn_location": str(wave.get("spawn_location", "Anywhere")),
                "spawn_x": int(wave.get("spawn_x", 0)),
                "spawn_y": int(wave.get("spawn_y", 0)),
                "formation": str(wave.get("formation", "Grid")),
                "spacing": max(1, int(wave.get("spacing", 1))),
                "health_percent": max(1, min(100, int(wave.get("health_percent", 100)))),
                "mana": max(0, min(255, int(wave.get("mana", 0)))),
                "facing": int(wave.get("facing", 0)),
                "group": str(wave.get("group", f"{state.name} Stage {state.next_stage + 1}")),
                "order": str(wave.get("order", "Attack")),
                "destination": str(wave.get("destination", "Anywhere")),
                "destination_x": int(wave.get("destination_x", 0)),
                "destination_y": int(wave.get("destination_y", 0)),
            }
            requested = max(1, min(64, int(self._evaluate_expression(args["amount_expression"], owner))))
            MassiveFeatureMixin.massive_action(self, "Create Wave", args, owner)
            total += requested
        return total

    # ----------------------------------------------------------- maintenance
    def _maintain_advanced_systems(self, world: list[Any], now: float) -> None:
        for aura in list(self.auras.values()):
            if aura.enabled and now >= aura.next_tick:
                self._pulse_aura(aura, world, now)
        for state in list(self.squad_controllers.values()):
            if not state.enabled or state.state in {"Stopped", "Complete"} or now < state.next_update:
                continue
            state.next_update = now + max(0.25, state.cadence)
            self._rally_squad(state, force=False)
        for state in list(self.reinforcement_directors.values()):
            if not state.enabled or state.state != "Active":
                continue
            if state.next_stage >= len(state.stages):
                state.state = "Complete"
                continue
            stage = state.stages[state.next_stage]
            due = state.started_at + max(0.0, float(stage.get("delay", stage.get("at", 0))))
            if now < due:
                continue
            spawned = self._spawn_reinforcement_stage(state, stage)
            state.next_stage += 1
            self.log(f"REINFORCEMENT DIRECTOR: {state.name} stage {state.next_stage}/{len(state.stages)} spawned {spawned} unit(s)")
            if state.next_stage >= len(state.stages):
                state.state = "Complete"

    def _massive_prepare_pre(self, world: list[Any]) -> bool:
        result = super()._massive_prepare_pre(world)
        if result is False:
            return False
        now = time.monotonic()
        if now >= self._advanced_next_maintenance:
            self._advanced_next_maintenance = now + 0.20
            self._maintain_advanced_systems(world, now)
        return True

    # ------------------------------------------------------------- conditions
    def massive_value(self, kind: str, args: dict[str, Any], player: int) -> Any:
        if kind == "Local Variable":
            value = self._function_local(args.get("name", "Local 1"), 0)
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0
        if kind == "Function Depth":
            return len(self._function_frames)
        if kind == "List Length":
            return len(self.runtime_lists.get(str(args.get("name", "List 1")), []))
        if kind == "List Contains":
            name = str(args.get("name", "List 1"))
            value = args.get("value", "")
            return 1 if value in self.runtime_lists.get(name, []) or str(value) in [str(item) for item in self.runtime_lists.get(name, [])] else 0
        if kind == "List Numeric Item":
            values = self.runtime_lists.get(str(args.get("name", "List 1")), [])
            index = int(args.get("index", 0))
            if not values or not -len(values) <= index < len(values):
                return 0
            try:
                return int(values[index])
            except (TypeError, ValueError):
                return 0
        if kind == "Runtime Flag":
            return 1 if self.runtime_flags.get(str(args.get("name", "Flag 1")), False) else 0
        if kind == "Trigger Cooldown Ready":
            return 1 if time.monotonic() >= float(self.trigger_cooldowns.get(str(args.get("name", "Cooldown 1")), 0.0)) else 0
        if kind == "Custom Currency":
            return self._currency_amount(int(args.get("player", player)), str(args.get("currency", "Credits")))
        if kind == "Shop Item Stock":
            return int(self.shop_items.get(str(args.get("item", "Health Potion")), {}).get("stock", 0))
        if kind == "Inventory Capacity Remaining":
            unit = self._resolve_unit_reference(args.get("reference", "Hero"))
            if unit is None:
                return 0
            key = self._unit_key_massive(unit)
            return max(0, int(self.inventory_capacity.get(key, 8)) - self._inventory_used(key))
        if kind == "Item Equipped":
            unit = self._resolve_unit_reference(args.get("reference", "Hero"))
            if unit is None:
                return 0
            equipped = self.equipment.get(self._unit_key_massive(unit), {})
            item = str(args.get("item", "Iron Sword"))
            slot = str(args.get("slot", "Any"))
            return 1 if (item in equipped.values() if slot == "Any" else equipped.get(slot) == item) else 0
        if kind in {"Hero Attribute", "Hero Skill Level", "Hero Skill Points"}:
            unit = self._resolve_unit_reference(args.get("reference", "Hero"))
            if unit is None:
                return 0
            key = self._unit_key_massive(unit)
            state = self.hero_state.get(key, {})
            if kind == "Hero Attribute":
                return self._attribute_total(key, str(args.get("attribute", "Strength")))
            if kind == "Hero Skill Level":
                return int(state.get("skills", {}).get(str(args.get("skill", "Skill 1")), 0))
            return int(state.get("skill_points", 0))
        if kind == "Aura Enabled":
            aura = self.auras.get(str(args.get("name", "Aura 1")))
            return 1 if aura and aura.enabled else 0
        if kind == "Unit In Aura":
            aura = self.auras.get(str(args.get("name", "Aura 1")))
            if aura is None or not aura.enabled:
                return 0
            _source, targets = self._aura_targets(aura, self.units())
            selected = {self._unit_key_massive(unit) for unit in self._selected_units(args, player)}
            return sum(1 for unit in targets if self._unit_key_massive(unit) in selected)
        if kind == "Squad Controller State":
            state = self.squad_controllers.get(str(args.get("name", "Squad 1")))
            return state.state if state else "Missing"
        if kind == "Squad Morale":
            return self._squad_morale(self.squad_controllers.get(str(args.get("name", "Squad 1"))))
        if kind == "Reinforcement Director State":
            state = self.reinforcement_directors.get(str(args.get("name", "Reinforcements 1")))
            return state.state if state else "Missing"
        if kind == "Reinforcement Stage":
            state = self.reinforcement_directors.get(str(args.get("name", "Reinforcements 1")))
            return int(state.next_stage if state else 0)
        if kind == "Vote State":
            vote = self.votes.get(str(args.get("name", "Vote 1")))
            return vote.state if vote else "Missing"
        if kind == "Vote Count":
            vote = self.votes.get(str(args.get("name", "Vote 1")))
            option = str(args.get("option", "Yes"))
            return sum(1 for choice in vote.votes.values() if choice == option) if vote else 0
        if kind == "Player Voted":
            vote = self.votes.get(str(args.get("name", "Vote 1")))
            owner = int(args.get("player", player))
            return 1 if vote and owner in vote.votes else 0
        if kind in {"Unit Group Average Health Percent", "Unit Group Wounded Count", "Unit Group Near Location"}:
            units = self._group_units(args.get("group", "Unit Group 1"))
            if kind == "Unit Group Average Health Percent":
                if not units:
                    return 0
                return round(sum(int(unit.health) * 100 / max(1, self._max_hp(unit)) for unit in units) / len(units))
            if kind == "Unit Group Wounded Count":
                threshold = max(0, min(100, int(args.get("health_percent", 50))))
                return sum(1 for unit in units if int(unit.health) * 100 / max(1, self._max_hp(unit)) <= threshold)
            location = self._find_location(str(args.get("location", "Location 1")))
            radius = max(0, int(args.get("radius", 0)))
            left, right = int(location.left) - radius, int(location.right) + radius
            top, bottom = int(location.top) - radius, int(location.bottom) + radius
            return sum(1 for unit in units if left <= int(unit.x) <= right and top <= int(unit.y) <= bottom)
        return super().massive_value(kind, args, player)

    # ---------------------------------------------------------------- actions
    def massive_action(self, kind: str, args: dict[str, Any], player: int) -> bool:
        # Synchronous trigger functions and local variables.
        if kind == "Call Trigger Function":
            engine = getattr(self, "engine", None)
            if engine is None:
                raise RuntimeError("Trigger functions require an active TriggerEngine")
            target_name = str(args.get("trigger", "")).strip()
            target_index = engine.find_trigger_index(target_name)
            if target_index is None:
                raise ValueError(f"Unknown trigger function: {target_name}")
            target = engine.scenario.triggers[target_index]
            forbidden = [action.kind for action in target.actions if action.kind in {"Wait", "Random Wait", "Breakpoint"}]
            if forbidden:
                raise RuntimeError(f"Trigger function {target.name} contains asynchronous action {forbidden[0]}")
            if len(self._function_frames) >= 16:
                raise RuntimeError("Trigger-function call depth exceeded 16")
            if target_index in engine._call_stack:
                raise RuntimeError(f"Recursive trigger-function call blocked: {target.name}")
            raw = self._parse_object(args.get("arguments_json", "{}"), "Function arguments")
            locals_dict: dict[str, Any] = {}
            for name, value in raw.items():
                if isinstance(value, str) and value.startswith("="):
                    value = self._evaluate_expression(value[1:], player)
                locals_dict[str(name)] = value
            frame = {"name": target.name, "locals": locals_dict, "return": args.get("default_return", 0)}
            self._function_frames.append(frame)
            engine._call_stack.append(target_index)
            try:
                engine._execute_actions(target_index, player, 0, time.monotonic(), called=True)
            finally:
                engine._call_stack.pop()
                completed = self._function_frames.pop()
            destination = str(args.get("return_variable", "")).strip()
            if destination:
                self._set_variable(destination, completed.get("return", 0))
            self.log(f"TRIGGER FUNCTION: {target.name} returned {completed.get('return', 0)!r}")
            return True
        if kind == "Set Local Variable":
            if not self._function_frames:
                raise RuntimeError("Set Local Variable is valid only inside Call Trigger Function")
            name = str(args.get("name", "Local 1")).strip()
            value = args.get("value", 0)
            if bool(args.get("use_expression", True)):
                value = self._evaluate_expression(args.get("expression", str(value)), player)
            self._function_frames[-1]["locals"][name] = value
            return True
        if kind == "Copy Local To Variable":
            value = self._function_local(args.get("local", "Local 1"), 0)
            self._set_variable(args.get("variable", "Variable 1"), value)
            return True
        if kind == "Return From Function":
            if not self._function_frames:
                raise RuntimeError("Return From Function is valid only inside Call Trigger Function")
            value = args.get("value", 0)
            if bool(args.get("use_expression", True)):
                value = self._evaluate_expression(args.get("expression", str(value)), player)
            self._function_frames[-1]["return"] = value
            raise FunctionReturn()

        # Runtime lists and flags.
        if kind in {"Create List", "Append To List", "Remove From List", "Set List Item", "Pop List To Variable", "Clear List", "Shuffle List", "Sort List", "Choose Random List Item"}:
            name = str(args.get("name", "List 1")).strip()
            values = self.runtime_lists.setdefault(name, [])
            if kind == "Create List":
                self.runtime_lists[name] = self._parse_list(args.get("values", "[]"), "List values")
            elif kind == "Append To List":
                value = args.get("value", "")
                if bool(args.get("use_expression", False)):
                    value = self._evaluate_expression(args.get("expression", "0"), player)
                values.append(value)
            elif kind == "Remove From List":
                wanted = args.get("value", "")
                values[:] = [item for item in values if str(item) != str(wanted)]
            elif kind == "Set List Item":
                index = int(args.get("index", 0))
                if not -len(values) <= index < len(values):
                    raise IndexError("List item index is outside the current list")
                value = args.get("value", "")
                if bool(args.get("use_expression", False)):
                    value = self._evaluate_expression(args.get("expression", "0"), player)
                values[index] = value
            elif kind == "Pop List To Variable":
                if not values:
                    raise RuntimeError(f"Runtime list {name!r} is empty")
                index = int(args.get("index", -1))
                value = values.pop(index)
                self._set_variable(args.get("variable", "Variable 1"), value)
            elif kind == "Clear List":
                values.clear()
            elif kind == "Shuffle List":
                self._advanced_rng.shuffle(values)
            elif kind == "Sort List":
                reverse = bool(args.get("descending", False))
                values.sort(key=lambda item: (str(type(item)), str(item)), reverse=reverse)
            else:
                if not values:
                    raise RuntimeError(f"Runtime list {name!r} is empty")
                self._set_variable(args.get("variable", "Variable 1"), self._advanced_rng.choice(values))
            return True
        if kind in {"Set Runtime Flag", "Clear Runtime Flag", "Toggle Runtime Flag"}:
            name = str(args.get("name", "Flag 1")).strip()
            if kind == "Set Runtime Flag": self.runtime_flags[name] = True
            elif kind == "Clear Runtime Flag": self.runtime_flags[name] = False
            else: self.runtime_flags[name] = not self.runtime_flags.get(name, False)
            return True
        if kind in {"Set Trigger Cooldown", "Clear Trigger Cooldown"}:
            name = str(args.get("name", "Cooldown 1")).strip()
            if kind == "Clear Trigger Cooldown":
                self.trigger_cooldowns.pop(name, None)
            else:
                self.trigger_cooldowns[name] = time.monotonic() + max(0.0, float(args.get("seconds", 1.0)))
            return True

        # Custom currencies, shops, equipment, and hero advancement.
        if kind in {"Set Custom Currency", "Add Custom Currency", "Subtract Custom Currency"}:
            owner = int(args.get("player", player))
            currency = str(args.get("currency", "Credits"))
            before = self._currency_amount(owner, currency)
            amount = max(0, int(args.get("amount", 0)))
            after = amount if kind == "Set Custom Currency" else before + amount if kind == "Add Custom Currency" else max(0, before - amount)
            self._set_currency(owner, currency, after)
            return True
        if kind == "Register Shop Item":
            name = str(args.get("item", "Health Potion")).strip()
            if not name:
                raise ValueError("Shop item name cannot be blank")
            bonuses = self._parse_object(args.get("bonuses_json", "{}"), "Equipment bonuses")
            self.shop_items[name] = {
                "price": max(0, int(args.get("price", 100))),
                "currency_type": str(args.get("currency_type", "Gold")),
                "currency_name": str(args.get("currency_name", "Credits")),
                "stock": max(0, int(args.get("stock", 10))),
                "max_stock": max(0, int(args.get("max_stock", args.get("stock", 10)))),
                "effect": str(args.get("effect", "Heal")),
                "effect_amount": max(0, int(args.get("effect_amount", 40))),
                "duration": max(0.1, float(args.get("duration", 5.0))),
                "effect_currency": str(args.get("effect_currency", "Credits")),
                "slot": str(args.get("slot", "Consumable")),
                "bonuses": {str(key): int(value) for key, value in bonuses.items()},
            }
            return True
        if kind == "Set Shop Stock":
            item = self.shop_items.get(str(args.get("item", "Health Potion")))
            if item is None:
                raise ValueError("Unknown shop item")
            item["stock"] = max(0, min(int(item.get("max_stock", 999999)), int(args.get("amount", 0))))
            return True
        if kind == "Buy Shop Item":
            reference = str(args.get("reference", "Hero"))
            unit, key = self._reference_unit_and_key(reference)
            item_name = str(args.get("item", "Health Potion"))
            item = self.shop_items.get(item_name)
            if item is None:
                raise ValueError(f"Unknown shop item: {item_name}")
            quantity = max(1, int(args.get("amount", 1)))
            if int(item.get("stock", 0)) < quantity:
                raise RuntimeError(f"Shop has only {item.get('stock', 0)} x {item_name}")
            capacity = int(self.inventory_capacity.get(key, 8))
            if self._inventory_used(key) + quantity > capacity:
                raise RuntimeError(f"Inventory capacity {capacity} would be exceeded")
            self._pay_price(int(args.get("player", unit.owner)), item, quantity)
            bag = self.inventory.setdefault(key, {})
            bag[item_name] = int(bag.get(item_name, 0)) + quantity
            item["stock"] = int(item.get("stock", 0)) - quantity
            return True
        if kind == "Sell Inventory Item":
            reference = str(args.get("reference", "Hero"))
            unit, key = self._reference_unit_and_key(reference)
            item_name = str(args.get("item", "Health Potion"))
            quantity = max(1, int(args.get("amount", 1)))
            bag = self.inventory.setdefault(key, {})
            if int(bag.get(item_name, 0)) < quantity:
                raise RuntimeError("Not enough items to sell")
            item = self.shop_items.get(item_name)
            if item is None:
                raise ValueError("The item is not registered in a shop")
            bag[item_name] -= quantity
            if bag[item_name] <= 0: bag.pop(item_name, None)
            item["stock"] = min(int(item.get("max_stock", 999999)), int(item.get("stock", 0)) + quantity)
            self._refund_price(int(args.get("player", unit.owner)), item, quantity, int(args.get("refund_percent", 50)))
            return True
        if kind in {"Equip Inventory Item", "Unequip Inventory Item"}:
            unit, key = self._reference_unit_and_key(args.get("reference", "Hero"))
            item_name = str(args.get("item", "Iron Sword"))
            slot = str(args.get("slot", "Weapon"))
            equipped = self.equipment.setdefault(key, {})
            if kind == "Equip Inventory Item":
                if int(self.inventory.get(key, {}).get(item_name, 0)) <= 0:
                    raise RuntimeError("The referenced unit does not own that item")
                equipped[slot] = item_name
            elif equipped.get(slot) == item_name or item_name == "Any":
                equipped.pop(slot, None)
            return True
        if kind == "Use Inventory Item":
            self._use_item(str(args.get("reference", "Hero")), str(args.get("item", "Health Potion")), int(args.get("amount", 1)), player)
            return True
        if kind == "Set Inventory Capacity":
            _unit, key = self._reference_unit_and_key(args.get("reference", "Hero"))
            capacity = max(0, min(999, int(args.get("capacity", 8))))
            if capacity < self._inventory_used(key):
                raise RuntimeError("New capacity is below the number of items currently held")
            self.inventory_capacity[key] = capacity
            return True
        if kind in {"Set Hero Attribute", "Add Hero Attribute", "Give Hero Skill Point", "Learn Hero Skill", "Reset Hero Skills"}:
            _unit, _key, state = self._hero_record(args.get("reference", "Hero"))
            if kind in {"Set Hero Attribute", "Add Hero Attribute"}:
                attribute = str(args.get("attribute", "Strength"))
                attrs = state["attributes"]
                amount = int(args.get("amount", 1))
                attrs[attribute] = max(0, amount if kind == "Set Hero Attribute" else int(attrs.get(attribute, 0)) + amount)
            elif kind == "Give Hero Skill Point":
                state["skill_points"] = max(0, int(state.get("skill_points", 0)) + int(args.get("amount", 1)))
            elif kind == "Learn Hero Skill":
                skill = str(args.get("skill", "Skill 1"))
                cost = max(0, int(args.get("cost", 1)))
                if int(state.get("skill_points", 0)) < cost:
                    raise RuntimeError("Not enough hero skill points")
                state["skill_points"] -= cost
                state["skills"][skill] = int(state["skills"].get(skill, 0)) + max(1, int(args.get("levels", 1)))
            else:
                refund = sum(int(level) for level in state.get("skills", {}).values()) if bool(args.get("refund", True)) else 0
                state["skills"] = {}
                state["skill_points"] = int(state.get("skill_points", 0)) + refund
            return True

        # Auras, squads, and staged reinforcement directors.
        if kind == "Enable Aura":
            name = str(args.get("name", "Aura 1"))
            self.auras[name] = AuraState(
                name=name,
                source_reference=str(args.get("source_reference", "Aura Source")),
                effect=str(args.get("effect", "Health Regeneration")),
                radius=max(1, min(32, int(args.get("radius", 6)))),
                relation=str(args.get("relation", "Allies")),
                amount=max(0, int(args.get("amount", 3))),
                interval=max(0.20, float(args.get("interval", 1.0))),
                group=str(args.get("group", "")).strip(),
                next_tick=time.monotonic(),
            )
            return True
        if kind == "Disable Aura":
            aura = self.auras.get(str(args.get("name", "Aura 1")))
            if aura: aura.enabled = False; aura.affected.clear()
            return True
        if kind == "Pulse Aura Now":
            aura = self.auras.get(str(args.get("name", "Aura 1")))
            if aura is None:
                raise ValueError("Unknown aura")
            count = self._pulse_aura(aura, self.units(), time.monotonic())
            self.log(f"AURA: {aura.name} affected {count} unit(s)")
            return True
        if kind == "Start Squad Controller":
            name = str(args.get("name", "Squad 1"))
            group = str(args.get("group", "Unit Group 1"))
            initial = len(self._group_units(group))
            self.squad_controllers[name] = SquadControllerState(
                name=name, group=group, profile=str(args.get("profile", "Attack")),
                formation=str(args.get("formation", "Grid")), spacing=max(1, int(args.get("spacing", 1))),
                destination=str(args.get("destination", "Anywhere")), x=int(args.get("x", 0)), y=int(args.get("y", 0)),
                retreat_location=str(args.get("retreat_location", "Anywhere")), retreat_x=int(args.get("retreat_x", 0)), retreat_y=int(args.get("retreat_y", 0)),
                retreat_morale=max(0, min(100, int(args.get("retreat_morale", 20)))), cadence=max(0.25, float(args.get("cadence", 1.0))),
                initial_count=max(1, initial), next_update=time.monotonic(),
            )
            return True
        if kind == "Stop Squad Controller":
            state = self.squad_controllers.get(str(args.get("name", "Squad 1")))
            if state: state.enabled = False; state.state = "Stopped"
            return True
        if kind in {"Set Squad Destination", "Set Squad Formation", "Set Squad Morale", "Rally Squad"}:
            state = self.squad_controllers.get(str(args.get("name", "Squad 1")))
            if state is None:
                raise ValueError("Unknown squad controller")
            if kind == "Set Squad Destination":
                state.destination = str(args.get("destination", "Anywhere")); state.x = int(args.get("x", 0)); state.y = int(args.get("y", 0))
            elif kind == "Set Squad Formation":
                state.formation = str(args.get("formation", "Grid")); state.spacing = max(1, int(args.get("spacing", 1)))
            elif kind == "Set Squad Morale":
                state.morale_override = max(0, min(100, int(args.get("morale", 100))))
            else:
                self._rally_squad(state, force=True)
            return True
        if kind == "Start Reinforcement Director":
            name = str(args.get("name", "Reinforcements 1"))
            stages = self._parse_list(args.get("stages_json", "[]"), "Reinforcement stages")
            if any(not isinstance(stage, dict) for stage in stages):
                raise ValueError("Every reinforcement stage must be a JSON object")
            self.reinforcement_directors[name] = ReinforcementDirectorState(name, [dict(stage) for stage in stages], time.monotonic())
            return True
        if kind == "Stop Reinforcement Director":
            state = self.reinforcement_directors.get(str(args.get("name", "Reinforcements 1")))
            if state: state.enabled = False; state.state = "Stopped"
            return True
        if kind == "Advance Reinforcement Stage":
            state = self.reinforcement_directors.get(str(args.get("name", "Reinforcements 1")))
            if state is None:
                raise ValueError("Unknown reinforcement director")
            if state.next_stage < len(state.stages):
                state.stages[state.next_stage]["delay"] = 0
                state.started_at = time.monotonic()
            return True

        # Trigger-driven voting. Chat parsing is deliberately not implied.
        if kind == "Start Vote":
            name = str(args.get("name", "Vote 1"))
            options = [str(value) for value in self._parse_list(args.get("options", '["Yes", "No"]'), "Vote options")]
            if len(options) < 2:
                raise ValueError("A vote requires at least two options")
            force = str(args.get("force", "All Players"))
            eligible = set(range(8)) if force == "All Players" else set(int(owner) for owner in getattr(self.scenario, "forces", {}).get(force, []))
            self.votes[name] = VoteState(name, str(args.get("question", name)), options, eligible)
            return True
        if kind == "Cast Vote":
            vote = self.votes.get(str(args.get("name", "Vote 1")))
            if vote is None or vote.state != "Open":
                raise RuntimeError("Vote is not open")
            owner = int(args.get("player", player))
            choice = str(args.get("option", "Yes"))
            if owner not in vote.eligible_players:
                raise RuntimeError("Player is not eligible for this vote")
            if choice not in vote.options:
                raise ValueError("Vote option is not registered")
            vote.votes[owner] = choice
            return True
        if kind == "Close Vote":
            vote = self.votes.get(str(args.get("name", "Vote 1")))
            if vote is None:
                raise ValueError("Unknown vote")
            counts = {option: sum(1 for choice in vote.votes.values() if choice == option) for option in vote.options}
            best = max(counts.values(), default=0)
            winners = [option for option, count in counts.items() if count == best]
            vote.winner = winners[0] if len(winners) == 1 else str(args.get("tie_result", "Tie"))
            vote.state = "Closed"
            destination = str(args.get("result_variable", "Vote Result")).strip()
            if destination: self.variables[destination] = vote.winner
            return True
        if kind == "Reset Vote":
            vote = self.votes.get(str(args.get("name", "Vote 1")))
            if vote: vote.votes.clear(); vote.winner = ""; vote.state = "Open"
            return True

        if kind == "Dump World Systems":
            self.log(
                "WORLD SYSTEMS: "
                f"functions={len(self._function_frames)}, lists={len(self.runtime_lists)}, shops={len(self.shop_items)}, "
                f"auras={len(self.auras)}, squads={len(self.squad_controllers)}, "
                f"reinforcement_directors={len(self.reinforcement_directors)}, votes={len(self.votes)}"
            )
            return True

        return super().massive_action(kind, args, player)
