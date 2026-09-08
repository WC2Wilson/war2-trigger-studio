from __future__ import annotations

"""Trigger-owned custom abilities for Warcraft II Remastered.

The engine composes validated effects from already-verified Trigger Studio
primitives.  Cast tasks retain their effect index across simulation-mailbox
deferrals, which prevents a completed native effect from being submitted twice.
Hotkeys and AI polling are local/wall-clock surfaces and are therefore never
advertised as multiplayer-safe.
"""

from dataclasses import dataclass, field
import json
import time
from typing import Any

from ability_defs import normalize_ability, validate_ability_definition
from engine import ActionDeferred
from massive_features import MASSIVE_UNHANDLED
from mission_features_139 import MissionFeature139Mixin
from source_features import SF_HIDDEN
from source_features_128 import SOURCE128_SPELL_ACTIONS


SF_SELECTED = 0x2000
_SPELL_CASTERS: dict[str, set[int]] = {
    "Holy Vision": {12, 44, 52}, "Healing": {12, 44, 52}, "Area Heal": {12, 44, 52}, "Exorcism": {12, 44, 52},
    "Flame Shield": {10, 24}, "Fireball": {10, 24}, "Slow": {10, 24}, "Invisibility": {10, 24}, "Polymorph": {10, 24}, "Blizzard": {10, 24},
    "Eye of Kilrogg": {13, 23, 49}, "Bloodlust": {13, 23, 49}, "Runes": {13, 23, 49},
    "Raise Dead": {11, 21, 51}, "Death Coil": {11, 21, 51}, "Whirlwind": {11, 21, 51}, "Haste": {11, 21, 51}, "Unholy Armor": {11, 21, 51}, "Death and Decay": {11, 21, 51},
}


@dataclass
class AbilityCastTask:
    serial: int
    ability_id: str
    caster_key: tuple[int, int]
    executing_player: int
    target_key: tuple[int, int] | None = None
    x: int = -1
    y: int = -1
    effect_index: int = 0
    started: float = field(default_factory=time.monotonic)
    paid: bool = False
    finalized: bool = False


class AbilityEngineMixin(MissionFeature139Mixin):
    """Version 1.43 Custom Ability Engine mixin."""

    def _init_massive_features(self) -> None:
        super()._init_massive_features()
        self._ability_definitions: dict[str, dict[str, Any]] = {}
        self._ability_enabled: dict[str, bool] = {}
        self._ability_grants: dict[tuple[int, int], set[str]] = {}
        self._ability_revokes: dict[tuple[int, int], set[str]] = {}
        self._ability_cooldowns: dict[tuple[tuple[int, int], str], float] = {}
        self._ability_charges: dict[tuple[tuple[int, int], str], int] = {}
        self._ability_cast_counts: dict[tuple[str, int], int] = {}
        self._ability_hotkey_prev: dict[str, bool] = {}
        self._ability_pending_target: dict[str, Any] | None = None
        self._ability_pending_events: list[tuple[str, Any | None, dict[str, Any]]] = []
        self._ability_tasks: dict[int, AbilityCastTask] = {}
        self._ability_action_task: dict[tuple[Any, ...], int] = {}
        self._ability_next_serial = 1
        self._ability_ai: dict[int, dict[str, Any]] = {}
        self._ability_reload_definitions()

    def _massive_begin_run(self) -> None:
        super()._massive_begin_run()
        self._ability_reload_definitions()
        self._ability_grants.clear()
        self._ability_revokes.clear()
        self._ability_cooldowns.clear()
        self._ability_charges.clear()
        self._ability_cast_counts.clear()
        self._ability_hotkey_prev.clear()
        self._ability_pending_target = None
        self._ability_pending_events.clear()
        self._ability_tasks.clear()
        self._ability_action_task.clear()
        self._ability_next_serial = 1
        self._ability_ai.clear()

    def _ability_reload_definitions(self) -> None:
        definitions: dict[str, dict[str, Any]] = {}
        for index, raw in enumerate(getattr(getattr(self, "scenario", None), "abilities", []) or [], 1):
            ability = normalize_ability(raw, index)
            errors = validate_ability_definition(ability, index=index)
            if errors:
                self.log("ABILITY DISABLED: " + "; ".join(errors))
                continue
            definitions[str(ability["id"]).casefold()] = ability
        self._ability_definitions = definitions
        self._ability_enabled = {key: bool(value.get("enabled", True)) for key, value in definitions.items()}

    # --------------------------------------------------------------- lookup/state
    def _ability_definition(self, value: Any, *, required: bool = True) -> dict[str, Any] | None:
        key = str(value or "").strip().casefold()
        ability = self._ability_definitions.get(key)
        if ability is None and required:
            raise ValueError(f"Unknown custom ability ID: {value!r}")
        return ability

    def _ability_unit_by_key(self, key: tuple[int, int] | None, world: list[Any] | None = None) -> Any | None:
        if key is None:
            return None
        source = world if world is not None else self.units()
        return next((unit for unit in source if self._unit_key_massive(unit) == key and not (int(unit.sflags) & SF_HIDDEN)), None)

    def _ability_selected_units(self, world: list[Any], player: int) -> list[Any]:
        try:
            owner = self._resolve_player_value("Local Human", player)
        except Exception:
            owner = int(player)
        return [unit for unit in world if int(unit.owner) == owner and int(unit.sflags) & SF_SELECTED and not (int(unit.sflags) & SF_HIDDEN)]

    def _ability_resolve_caster(self, args: dict[str, Any], player: int, world: list[Any] | None = None) -> Any:
        reference = str(args.get("caster_reference", "")).strip()
        if reference:
            unit = self._resolve_unit_reference(reference)
        else:
            source = world if world is not None else self.units()
            selected = self._ability_selected_units(source, player)
            unit = selected[0] if selected else None
        if unit is None:
            raise RuntimeError("Custom ability requires a selected caster or a valid caster unit reference")
        return unit

    def _ability_resolve_target(self, args: dict[str, Any]) -> Any | None:
        reference = str(args.get("target_reference", "")).strip()
        if reference:
            return self._resolve_unit_reference(reference)
        if int(self._mission132_target.get("unit_address", 0)):
            return self._mission132_target_unit()
        return None

    def _ability_known(self, caster: Any, ability: dict[str, Any]) -> bool:
        key = self._unit_key_massive(caster)
        aid = str(ability["id"]).casefold()
        if aid in self._ability_revokes.get(key, set()):
            return False
        if aid in self._ability_grants.get(key, set()):
            return True
        allowed = [int(value) for value in ability.get("caster_types", [])]
        return not allowed or int(caster.unit_type) in allowed

    def _ability_charge_count(self, caster: Any, ability: dict[str, Any]) -> int:
        maximum = max(0, int(ability.get("max_charges", 0)))
        if maximum <= 0:
            return -1
        key = (self._unit_key_massive(caster), str(ability["id"]).casefold())
        return int(self._ability_charges.setdefault(key, maximum))

    def _ability_cooldown_remaining(self, caster: Any, ability: dict[str, Any]) -> float:
        key = (self._unit_key_massive(caster), str(ability["id"]).casefold())
        return max(0.0, float(self._ability_cooldowns.get(key, 0.0)) - time.monotonic())

    def _ability_costs(self, ability: dict[str, Any]) -> dict[str, int]:
        return {
            "Gold": max(0, int(ability.get("gold_cost", 0))),
            "Lumber": max(0, int(ability.get("lumber_cost", 0))),
            "Oil": max(0, int(ability.get("oil_cost", 0))),
        }

    def _ability_available_reason(self, caster: Any, ability: dict[str, Any]) -> str:
        aid = str(ability["id"]).casefold()
        if not self._ability_enabled.get(aid, False):
            return "ability disabled"
        if not self._ability_known(caster, ability):
            return "caster does not know ability"
        if self._ability_cooldown_remaining(caster, ability) > 0:
            return "ability on cooldown"
        charges = self._ability_charge_count(caster, ability)
        if charges == 0:
            return "no charges remaining"
        mana_cost = max(0, int(ability.get("mana_cost", 0)))
        if int(getattr(caster, "mana", 0)) < mana_cost:
            return "not enough mana"
        for resource, cost in self._ability_costs(ability).items():
            if cost and self._read_resource(int(caster.owner), resource) < cost:
                return f"not enough {resource.lower()}"
        return ""

    def _ability_target_reason(self, caster: Any, ability: dict[str, Any], target: Any | None, x: int, y: int) -> str:
        mode = str(ability.get("target", "None"))
        if mode == "Self":
            target, x, y = caster, int(caster.x), int(caster.y)
        elif mode in {"Unit", "Enemy Unit", "Allied Unit", "Building"} and target is None:
            return f"{mode.lower()} target required"
        if target is not None:
            x, y = int(target.x), int(target.y)
            if mode == "Enemy Unit" and self._players_allied(int(caster.owner), int(target.owner)):
                return "enemy target required"
            if mode == "Allied Unit" and not self._players_allied(int(caster.owner), int(target.owner)):
                return "allied target required"
            if mode == "Building" and int(target.unit_type) < 58:
                return "building target required"
            if mode in {"Unit", "Enemy Unit", "Allied Unit"} and int(target.unit_type) >= 58:
                return "mobile unit target required"
        if mode not in {"None", "Self"}:
            if x < 0 or y < 0:
                return "target point required"
            distance = max(abs(int(caster.x) - int(x)), abs(int(caster.y) - int(y)))
            if distance > max(0, int(ability.get("range", 0))):
                return f"target outside range {int(ability.get('range', 0))}"
        return ""

    # --------------------------------------------------------------- cast lifecycle
    def _ability_queue_event(self, name: str, unit: Any | None, ability: dict[str, Any], **extra: Any) -> None:
        self._ability_pending_events.append((name, unit, {
            "ability_id": str(ability["id"]), "ability_name": str(ability["name"]), **extra,
        }))

    def _ability_start_cast(self, caster: Any, ability: dict[str, Any], player: int, target: Any | None, x: int, y: int) -> AbilityCastTask:
        reason = self._ability_available_reason(caster, ability) or self._ability_target_reason(caster, ability, target, x, y)
        if reason:
            self._ability_queue_event("Ability Cast Failed", caster, ability, reason=reason)
            raise RuntimeError(f"{ability['name']}: {reason}")
        if str(ability.get("target")) == "Self":
            target, x, y = caster, int(caster.x), int(caster.y)
        elif target is not None:
            x, y = int(target.x), int(target.y)
        elif str(ability.get("target")) == "None":
            x, y = int(caster.x), int(caster.y)
        task = AbilityCastTask(
            serial=self._ability_next_serial,
            ability_id=str(ability["id"]).casefold(),
            caster_key=self._unit_key_massive(caster),
            executing_player=int(player),
            target_key=self._unit_key_massive(target) if target is not None else None,
            x=int(x), y=int(y),
        )
        self._ability_next_serial += 1
        self._ability_tasks[task.serial] = task
        self._ability_queue_event("Ability Cast Started", caster, ability, target_x=task.x, target_y=task.y)
        return task

    def _ability_effect_unit(self, task: AbilityCastTask, recipient: str) -> Any | None:
        if str(recipient) == "Caster":
            return self._ability_unit_by_key(task.caster_key)
        return self._ability_unit_by_key(task.target_key) or self._ability_unit_by_key(task.caster_key)

    def _ability_temp_reference(self, task: AbilityCastTask, suffix: str, unit: Any) -> str:
        name = f"__ability_{task.serial}_{suffix}"
        self._save_reference(name, unit)
        return name

    def _ability_execute_effect(self, task: AbilityCastTask, ability: dict[str, Any], effect: dict[str, Any]) -> None:
        caster = self._ability_unit_by_key(task.caster_key)
        target = self._ability_unit_by_key(task.target_key)
        if caster is None:
            raise RuntimeError("ability caster no longer exists")
        kind = str(effect.get("kind", ""))
        if kind == "Native Spell":
            spell = str(effect.get("spell", "Fireball"))
            if spell not in SOURCE128_SPELL_ACTIONS:
                raise ValueError(f"Unknown native spell {spell!r}")
            allowed = _SPELL_CASTERS.get(spell, set())
            if allowed and int(caster.unit_type) not in allowed and not bool(effect.get("allow_wrong_caster", False)):
                raise RuntimeError(f"{spell} is not valid for caster unit type {caster.unit_type}")
            action_global = int(self.spell_path["action_type_global"])
            if int(self.pm.read_ushort(action_global)) != 0:
                raise ActionDeferred(f"native spell action is busy while queueing {spell}", retry_after=0.05)
            target_ptr = int(target.address) if target is not None else 0
            tx, ty = (0, 0) if target_ptr else (int(task.x), int(task.y))
            self._dispatch_ops([
                ("write_word", action_global, int(SOURCE128_SPELL_ACTIONS[spell])),
                ("call", self.order_callees["set_target"], [caster.address, tx, ty, target_ptr, self.spell_path["do_unit_spell"]]),
                ("write_word", action_global, 0),
            ])
            if int(self.pm.read_ushort(action_global)) != 0:
                raise RuntimeError(f"{spell} cast failed to restore native spell state")
            return
        if kind == "Damage Target":
            if target is None: raise RuntimeError("Damage Target requires a live target")
            self._call_damage_unit(caster, target, max(0, int(effect.get("amount", 25)))); return
        if kind == "Damage Area":
            radius = max(0, int(effect.get("radius", 2))); amount = max(0, int(effect.get("amount", 15)))
            victims = [unit for unit in self.units() if max(abs(int(unit.x)-task.x), abs(int(unit.y)-task.y)) <= radius and not (int(unit.sflags) & SF_HIDDEN) and (bool(effect.get("friendly_fire", False)) or not self._players_allied(int(caster.owner), int(unit.owner)))]
            victims.sort(key=lambda unit: self._distance_sq(caster, unit))
            if len(victims) > 32:
                self.log(f"ABILITY AREA CAP: {ability['name']} affects the nearest 32 of {len(victims)} eligible units")
            if victims:
                self._call_cdecl_batched([(self.damage_unit_address, [caster.address, unit.address, amount]) for unit in victims[:32]])
            return
        if kind == "Heal Target":
            if target is None: raise RuntimeError("Heal Target requires a live target")
            maximum = max(1, int(self._source128_rule_value("Maximum HP", int(target.unit_type))))
            value = min(maximum, max(1, int(target.health) + max(0, int(effect.get("amount", 25)))))
            self._dispatch_ops([("write_word", target.address + 0x22, value)]); return
        if kind == "Restore Mana":
            unit = self._ability_effect_unit(task, str(effect.get("recipient", "Target")))
            if unit is None: raise RuntimeError("Restore Mana requires a live recipient")
            value = min(255, max(0, int(unit.mana) + max(0, int(effect.get("amount", 25)))))
            self._dispatch_ops([("write_bytes", unit.address + 0x26, bytes([value]))]); return
        if kind in {"Teleport Caster", "Teleport Target"}:
            unit = caster if kind == "Teleport Caster" else target
            if unit is None: raise RuntimeError(f"{kind} requires a live unit")
            ref = self._ability_temp_reference(task, "teleport", unit)
            super().massive_action("Teleport Unit Reference", {"reference": ref, "destination": "Anywhere", "x": task.x, "y": task.y}, task.executing_player)
            self.unit_references.pop(ref, None); return
        if kind == "Spawn Unit":
            owner_mode = str(effect.get("owner", "Caster"))
            owner = int(caster.owner) if owner_mode == "Caster" else int(target.owner) if owner_mode == "Target" and target is not None else int(task.executing_player)
            self.action("Create Units", {"player": owner, "unit": int(effect.get("unit_type", 55)), "amount": 1, "location": "Anywhere", "x": task.x, "y": task.y}, task.executing_player); return
        if kind == "Apply Status":
            unit = self._ability_effect_unit(task, str(effect.get("recipient", "Target")))
            if unit is None: raise RuntimeError("Apply Status requires a live recipient")
            ref = self._ability_temp_reference(task, "status", unit)
            super().massive_action("Apply Effect To Unit Reference", {"reference": ref, "effect": str(effect.get("status", "Haste")), "seconds": max(0.1, float(effect.get("seconds", 10.0)))}, task.executing_player)
            self.unit_references.pop(ref, None); return
        if kind == "Create Projectile":
            super().massive_action("Source Create Projectile At Point", {"destination": "Anywhere", "x": task.x, "y": task.y, "missile": int(effect.get("missile", 2)), "count": 1}, task.executing_player); return
        if kind == "Issue Order":
            unit = self._ability_effect_unit(task, str(effect.get("recipient", "Caster")))
            if unit is None: raise RuntimeError("Issue Order requires a live recipient")
            ref = self._ability_temp_reference(task, "order", unit)
            super().massive_action("Order Unit Reference", {"reference": ref, "order": str(effect.get("order", "Attack")), "destination": "Anywhere", "x": task.x, "y": task.y}, task.executing_player)
            self.unit_references.pop(ref, None); return
        if kind == "Kill Target":
            if target is None: raise RuntimeError("Kill Target requires a live target")
            self._call_cdecl(self.damage_callees["unit_kill"], [target.address]); return
        if kind == "Run Trigger Function":
            super().massive_action("Call Trigger Function", {"trigger": str(effect.get("trigger", "Ability Function")), "arguments_json": str(effect.get("arguments_json", "{}"))}, task.executing_player); return
        if kind == "Display Message":
            text = str(effect.get("text", "Ability cast!")).replace("{ability}", str(ability["name"])).replace("{caster}", str(int(caster.unit_type))).replace("{x}", str(task.x)).replace("{y}", str(task.y))
            self._game_message({"text": text, "color": "White — native highlight", "recipients": "All active players", "seconds": 4, "also_log": True}, task.executing_player); return
        if kind == "Play Caster Sound":
            self._call_cdecl(self.source_native_paths["gamesnd_select"], [caster.address]); return
        if kind == "Set Variable":
            name = str(effect.get("name", "AbilityValue")).strip()
            raw = str(effect.get("value", "1"))
            try: value: Any = int(raw, 0)
            except ValueError:
                try: value = float(raw)
                except ValueError: value = raw
            self.variables[name] = value; return
        if kind == "Add Counter":
            name = str(effect.get("name", "AbilityCasts")).strip()
            self.counters[name] = max(0, min(0x7FFFFFFF, int(self.counters.get(name, 0)) + max(0, int(effect.get("amount", 1))))); return
        raise ValueError(f"Unsupported custom ability effect: {kind}")

    def _ability_pay_costs(self, task: AbilityCastTask, caster: Any, ability: dict[str, Any]) -> None:
        operations: list[tuple] = []
        mana_cost = max(0, int(ability.get("mana_cost", 0)))
        if mana_cost:
            if int(caster.mana) < mana_cost: raise RuntimeError("not enough mana when finalizing cast")
            operations.append(("write_bytes", caster.address + 0x26, bytes([int(caster.mana) - mana_cost])))
        for resource, cost in self._ability_costs(ability).items():
            if not cost: continue
            have = self._read_resource(int(caster.owner), resource)
            if have < cost: raise RuntimeError(f"not enough {resource.lower()} when finalizing cast")
            _, address = self._resource_address(int(caster.owner), resource)
            operations.append(("write_dword", address, have - cost))
        if operations:
            self._dispatch_ops(operations)
        task.paid = True

    def _ability_process_task(self, task: AbilityCastTask) -> bool:
        ability = self._ability_definition(task.ability_id)
        caster = self._ability_unit_by_key(task.caster_key)
        if caster is None:
            raise RuntimeError("ability caster disappeared before cast completed")
        effects = list(ability.get("effects", []))
        while task.effect_index < len(effects):
            self._ability_execute_effect(task, ability, effects[task.effect_index])
            task.effect_index += 1
        if not task.paid:
            # Native spell/effect work can change mana before custom costs commit.
            # Refresh the unit snapshot so final payment never overwrites a native
            # deduction with the caster's pre-cast mana value.
            caster = self._ability_unit_by_key(task.caster_key)
            if caster is None:
                raise RuntimeError("ability caster disappeared before cost payment")
            self._ability_pay_costs(task, caster, ability)
        if not task.finalized:
            aid = str(ability["id"]).casefold(); unit_key = self._unit_key_massive(caster)
            cooldown = max(0.0, float(ability.get("cooldown", 0.0)))
            if cooldown: self._ability_cooldowns[(unit_key, aid)] = time.monotonic() + cooldown
            charges = self._ability_charge_count(caster, ability)
            if charges > 0: self._ability_charges[(unit_key, aid)] = charges - 1
            count_key = (aid, int(caster.owner)); self._ability_cast_counts[count_key] = int(self._ability_cast_counts.get(count_key, 0)) + 1
            task.finalized = True
            self._ability_queue_event("Ability Cast Finished", caster, ability, target_x=task.x, target_y=task.y)
            self.log(f"ABILITY CAST: {ability['name']} by P{int(caster.owner)+1} unit {int(caster.unit_type)} at ({task.x},{task.y})")
        self._ability_tasks.pop(task.serial, None)
        for signature, serial in list(self._ability_action_task.items()):
            if serial == task.serial: self._ability_action_task.pop(signature, None)
        return True

    def _ability_fail_task(self, task: AbilityCastTask, reason: str) -> None:
        ability = self._ability_definition(task.ability_id, required=False)
        caster = self._ability_unit_by_key(task.caster_key)
        if ability is not None:
            self._ability_queue_event("Ability Cast Failed", caster, ability, reason=str(reason))
        self._ability_tasks.pop(task.serial, None)
        for signature, serial in list(self._ability_action_task.items()):
            if serial == task.serial: self._ability_action_task.pop(signature, None)

    # ------------------------------------------------------------ hotkeys/targeting
    def _ability_begin_target(self, caster: Any, ability: dict[str, Any], player: int, *, show_prompt: bool = True) -> None:
        target_mode = str(ability.get("target", "Point"))
        mission_kind = "Building" if target_mode == "Building" else "Unit" if target_mode in {"Unit", "Enemy Unit", "Allied Unit"} else "Any"
        serial = int(self._mission132_target.get("serial", 0))
        self._ability_pending_target = {"caster_key": self._unit_key_massive(caster), "ability_id": str(ability["id"]).casefold(), "player": int(player), "serial": serial}
        self._mission132_target.update({"active": True, "selected": False, "x": -1, "y": -1, "unit_address": 0, "unit_type": -1, "unit_owner": -1, "prompt": f"{ability['name']}: choose {target_mode.lower()}", "kind": mission_kind})
        if show_prompt:
            self._game_message({"text": str(self._mission132_target["prompt"]), "color": "White — native highlight", "recipients": "All active players", "seconds": 5, "also_log": False}, player)

    def _ability_poll_hotkeys(self, world: list[Any]) -> None:
        selected = self._ability_selected_units(world, 0)
        for aid, ability in self._ability_definitions.items():
            hotkey = str(ability.get("hotkey", "")).strip()
            if not hotkey:
                continue
            try:
                down = bool(self._mission131_key_state(self._mission131_vk(hotkey)))
            except Exception:
                down = False
            previous = bool(self._ability_hotkey_prev.get(aid, False)); self._ability_hotkey_prev[aid] = down
            if not down or previous or self._ability_pending_target is not None:
                continue
            caster = next((unit for unit in selected if self._ability_known(unit, ability)), None)
            if caster is None:
                continue
            mode = str(ability.get("target", "None"))
            try:
                if mode in {"None", "Self"}:
                    task = self._ability_start_cast(caster, ability, int(caster.owner), caster if mode == "Self" else None, int(caster.x), int(caster.y))
                    self._ability_process_task(task)
                else:
                    self._ability_begin_target(caster, ability, int(caster.owner))
            except ActionDeferred:
                return
            except Exception as exc:
                self.log(f"ABILITY HOTKEY REJECTED: {ability['name']}: {exc}")

    def _ability_poll_target(self) -> None:
        pending = self._ability_pending_target
        if pending is None or not self._mission132_target.get("selected"):
            return
        if int(self._mission132_target.get("serial", 0)) <= int(pending.get("serial", 0)):
            return
        caster = self._ability_unit_by_key(pending["caster_key"]); ability = self._ability_definition(pending["ability_id"], required=False)
        target = self._mission132_target_unit(); x = int(self._mission132_target.get("x", -1)); y = int(self._mission132_target.get("y", -1))
        self._ability_pending_target = None; self._mission132_target["active"] = False
        if caster is None or ability is None:
            return
        if str(ability.get("target")) == "Point":
            # Clicking on a unit's tile is still a ground-point cast. Do not
            # accidentally turn it into a native unit-pointer spell target.
            target = None
        try:
            task = self._ability_start_cast(caster, ability, int(pending["player"]), target, x, y)
            self._ability_process_task(task)
        except ActionDeferred:
            return
        except Exception as exc:
            self.log(f"ABILITY TARGET REJECTED: {ability['name']}: {exc}")

    # ------------------------------------------------------------------------ AI
    def _ability_ai_target(self, caster: Any, ability: dict[str, Any], world: list[Any]) -> tuple[Any | None, int, int] | None:
        mode = str(ability.get("target", "None")); radius = max(0, int(ability.get("range", 0)))
        if mode in {"None", "Self"}: return (caster if mode == "Self" else None, int(caster.x), int(caster.y))
        candidates = [unit for unit in world if unit.address != caster.address and not (int(unit.sflags) & SF_HIDDEN)]
        if mode == "Enemy Unit": candidates = [unit for unit in candidates if not self._players_allied(int(caster.owner), int(unit.owner)) and int(unit.unit_type) < 58]
        elif mode == "Allied Unit": candidates = [unit for unit in candidates if self._players_allied(int(caster.owner), int(unit.owner)) and int(unit.unit_type) < 58]
        elif mode == "Building": candidates = [unit for unit in candidates if int(unit.unit_type) >= 58]
        elif mode == "Unit": candidates = [unit for unit in candidates if int(unit.unit_type) < 58]
        elif mode == "Point": candidates = [unit for unit in candidates if not self._players_allied(int(caster.owner), int(unit.owner))]
        candidates = [unit for unit in candidates if max(abs(int(unit.x)-int(caster.x)), abs(int(unit.y)-int(caster.y))) <= radius]
        if not candidates: return None
        if mode == "Allied Unit":
            candidates.sort(key=lambda unit: (int(unit.health), self._distance_sq(caster, unit)))
        else:
            candidates.sort(key=lambda unit: self._distance_sq(caster, unit))
        target = candidates[0]
        return (None if mode == "Point" else target, int(target.x), int(target.y))

    def _ability_cast_best_ai(self, owner: int, world: list[Any]) -> int:
        abilities = sorted((ability for ability in self._ability_definitions.values() if bool(ability.get("ai_enabled", False))), key=lambda item: -int(item.get("ai_priority", 50)))
        for caster in world:
            if int(caster.owner) != int(owner) or int(caster.sflags) & SF_HIDDEN: continue
            for ability in abilities:
                if self._ability_available_reason(caster, ability): continue
                target = self._ability_ai_target(caster, ability, world)
                if target is None: continue
                unit, x, y = target
                try:
                    task = self._ability_start_cast(caster, ability, owner, unit, x, y)
                    self._ability_process_task(task)
                    return 1
                except ActionDeferred:
                    return 0
                except Exception as exc:
                    self.log(f"ABILITY AI REJECTED: {ability['name']}: {exc}")
        return 0

    def _ability_ai_maintenance(self, world: list[Any]) -> None:
        now = time.monotonic()
        for owner, state in list(self._ability_ai.items()):
            if not state.get("enabled", True) or now < float(state.get("next", 0.0)): continue
            state["next"] = now + max(0.1, float(state.get("interval", 1.0)))
            for _ in range(max(1, min(16, int(state.get("max_casts", 1))))):
                if not self._ability_cast_best_ai(owner, world): break

    # --------------------------------------------------------------- mixin hooks
    def _massive_prepare_pre(self, world: list[Any]) -> bool:
        result = super()._massive_prepare_pre(world)
        if result is False: return False
        # Resume mailbox-backed casts before accepting another local/AI cast.
        action_serials = set(self._ability_action_task.values())
        for task in [item for item in self._ability_tasks.values() if item.serial not in action_serials]:
            try:
                self._ability_process_task(task)
            except ActionDeferred:
                return False
            except Exception as exc:
                self._ability_fail_task(task, str(exc)); self.log(f"ABILITY CAST FAILED: {exc}")
        self._ability_poll_target()
        if any(item.serial not in set(self._ability_action_task.values()) for item in self._ability_tasks.values()): return False
        self._ability_poll_hotkeys(world)
        if any(item.serial not in set(self._ability_action_task.values()) for item in self._ability_tasks.values()): return False
        self._ability_ai_maintenance(world)
        action_serials = set(self._ability_action_task.values())
        return not any(item.serial not in action_serials for item in self._ability_tasks.values())

    def _massive_prepare_events(self, current: dict[tuple[int, int], Any], previous: dict[tuple[int, int], Any]) -> None:
        super()._massive_prepare_events(current, previous)
        pending, self._ability_pending_events = self._ability_pending_events, []
        for event_type, unit, extra in pending:
            self._mission_add_event(event_type, unit, **extra)
        live_keys = set(current)
        self._ability_grants = {key: value for key, value in self._ability_grants.items() if key in live_keys}
        self._ability_revokes = {key: value for key, value in self._ability_revokes.items() if key in live_keys}
        self._ability_cooldowns = {key: value for key, value in self._ability_cooldowns.items() if key[0] in live_keys}
        self._ability_charges = {key: value for key, value in self._ability_charges.items() if key[0] in live_keys}

    # ---------------------------------------------------------------- conditions
    def massive_value(self, kind: str, args: dict[str, Any], player: int) -> Any:
        if kind == "Ability Defined": return 1 if self._ability_definition(args.get("ability_id"), required=False) is not None else 0
        if kind in {"Unit Has Ability", "Ability Available", "Ability On Cooldown", "Ability Charges"}:
            ability = self._ability_definition(args.get("ability_id"), required=False)
            try: caster = self._ability_resolve_caster(args, player)
            except Exception: caster = None
            if ability is None or caster is None: return 0
            if kind == "Unit Has Ability": return 1 if self._ability_known(caster, ability) else 0
            if kind == "Ability Available": return 1 if not self._ability_available_reason(caster, ability) else 0
            if kind == "Ability On Cooldown": return int(self._ability_cooldown_remaining(caster, ability) > 0)
            charges = self._ability_charge_count(caster, ability); return 0x7FFFFFFF if charges < 0 else charges
        if kind == "Ability Targeting":
            wanted = str(args.get("ability_id", "")).strip().casefold()
            return 1 if self._ability_pending_target is not None and (not wanted or self._ability_pending_target.get("ability_id") == wanted) else 0
        if kind in {"Ability Cast Started", "Ability Cast Finished", "Ability Cast Failed"}:
            return self._mission_event_count(kind, args, player)
        if kind == "Ability Cast Count":
            aid = str(args.get("ability_id", "")).strip().casefold(); owner = int(args.get("player", -1))
            return sum(value for (key, cast_owner), value in self._ability_cast_counts.items() if (not aid or key == aid) and (owner < 0 or owner == cast_owner))
        return super().massive_value(kind, args, player)

    # -------------------------------------------------------------------- actions
    def massive_action(self, kind: str, args: dict[str, Any], player: int) -> bool:
        if kind in {"Grant Ability", "Revoke Ability"}:
            ability = self._ability_definition(args.get("ability_id")); caster = self._ability_resolve_caster(args, player); key = self._unit_key_massive(caster); aid = str(ability["id"]).casefold()
            if kind == "Grant Ability": self._ability_grants.setdefault(key, set()).add(aid); self._ability_revokes.setdefault(key, set()).discard(aid)
            else: self._ability_revokes.setdefault(key, set()).add(aid); self._ability_grants.setdefault(key, set()).discard(aid)
            return True
        if kind in {"Enable Ability", "Disable Ability"}:
            ability = self._ability_definition(args.get("ability_id")); self._ability_enabled[str(ability["id"]).casefold()] = kind == "Enable Ability"; return True
        if kind == "Begin Ability Targeting":
            ability = self._ability_definition(args.get("ability_id")); caster = self._ability_resolve_caster(args, player); self._ability_begin_target(caster, ability, player, show_prompt=bool(args.get("show_prompt", True))); return True
        if kind == "Cancel Ability Targeting":
            self._ability_pending_target = None; self._mission132_target["active"] = False; self._mission132_target["selected"] = False; return True
        if kind in {"Cast Ability", "Cast Ability At Point", "Cast Ability On Unit"}:
            ability = self._ability_definition(args.get("ability_id")); caster = self._ability_resolve_caster(args, player)
            target_mode = str(ability.get("target", "None"))
            if kind == "Cast Ability" and target_mode not in {"None", "Self"}:
                raise RuntimeError(f"{ability['name']} uses {target_mode} targeting; choose the matching point/unit cast action")
            if kind == "Cast Ability At Point" and target_mode != "Point":
                raise RuntimeError(f"{ability['name']} does not use Point targeting")
            if kind == "Cast Ability On Unit" and target_mode not in {"Unit", "Enemy Unit", "Allied Unit", "Building"}:
                raise RuntimeError(f"{ability['name']} does not use unit/building targeting")
            target = self._ability_resolve_target(args) if kind == "Cast Ability On Unit" else (caster if str(ability.get("target")) == "Self" else None)
            if kind == "Cast Ability At Point": x, y = self._location_point(str(args.get("location", "Anywhere")), int(args.get("x", caster.x)), int(args.get("y", caster.y)))
            elif target is not None: x, y = int(target.x), int(target.y)
            else: x, y = int(caster.x), int(caster.y)
            signature = (kind, str(ability["id"]).casefold(), self._unit_key_massive(caster), self._unit_key_massive(target) if target else None, x, y, int(player))
            task = self._ability_tasks.get(self._ability_action_task.get(signature, -1))
            if task is None:
                task = self._ability_start_cast(caster, ability, player, target, x, y); self._ability_action_task[signature] = task.serial
            try: return self._ability_process_task(task)
            except ActionDeferred: raise
            except Exception as exc: self._ability_fail_task(task, str(exc)); raise
        if kind == "Reset Ability Cooldown":
            ability = self._ability_definition(args.get("ability_id")); caster = self._ability_resolve_caster(args, player); self._ability_cooldowns.pop((self._unit_key_massive(caster), str(ability["id"]).casefold()), None); return True
        if kind in {"Set Ability Charges", "Add Ability Charges"}:
            ability = self._ability_definition(args.get("ability_id")); caster = self._ability_resolve_caster(args, player); maximum = max(0, int(ability.get("max_charges", 0)))
            if maximum <= 0: raise RuntimeError(f"{ability['name']} has unlimited charges")
            key = (self._unit_key_massive(caster), str(ability["id"]).casefold()); amount = max(0, int(args.get("amount", 0)))
            self._ability_charges[key] = min(maximum, amount if kind == "Set Ability Charges" else self._ability_charge_count(caster, ability) + amount); return True
        if kind in {"Enable Ability AI", "Disable Ability AI"}:
            owner = self._resolve_player_value(args.get("player", player), player)
            if kind == "Enable Ability AI": self._ability_ai[owner] = {"enabled": True, "interval": max(0.1, float(args.get("interval", 1.0))), "max_casts": max(1, int(args.get("max_casts", 1))), "next": 0.0}
            else: self._ability_ai.pop(owner, None)
            return True
        if kind == "Cast Best Ability For AI":
            owner = self._resolve_player_value(args.get("player", player), player); self._ability_cast_best_ai(owner, self.units()); return True
        if kind == "Show Ability Card":
            ability = self._ability_definition(args.get("ability_id")); caster = self._ability_resolve_caster(args, player)
            cooldown = self._ability_cooldown_remaining(caster, ability); charges = self._ability_charge_count(caster, ability)
            cost = ", ".join(f"{value} {name}" for name, value in (("mana", int(ability.get("mana_cost", 0))), ("gold", int(ability.get("gold_cost", 0))), ("lumber", int(ability.get("lumber_cost", 0))), ("oil", int(ability.get("oil_cost", 0)))) if value) or "free"
            text = f"{ability['name']} [{ability.get('hotkey') or 'no hotkey'}] — {ability.get('description','')} | Cost: {cost} | Cooldown: {cooldown:.1f}s | Charges: {'unlimited' if charges < 0 else charges}"
            self._game_message({"text": text, "color": "White — native highlight", "recipients": "All active players", "seconds": max(1, int(args.get("seconds", 7))), "also_log": True}, player); return True
        if kind == "Dump Ability State":
            payload = {"definitions": list(self._ability_definitions), "enabled": self._ability_enabled, "cooldowns": len(self._ability_cooldowns), "charges": len(self._ability_charges), "active_casts": [task.ability_id for task in self._ability_tasks.values()], "targeting": self._ability_pending_target, "ai_players": sorted(self._ability_ai)}
            self.log("ABILITY STATE: " + json.dumps(payload, sort_keys=True)); return True
        return super().massive_action(kind, args, player)
