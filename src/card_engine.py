from __future__ import annotations

"""Trigger-owned command-card runtime for Warcraft II Remastered.

Native production is attempted first.  When an authored cross-faction pairing is
rejected by Warcraft's stock producer rules, unit training and research can use a
timed trigger-owned fallback built from validated resource/progression/creation
primitives.  No unverified modern C++ command-card object is patched.
"""

from dataclasses import dataclass, field
import hashlib
import json
import time
from typing import Any

from ability_engine import AbilityEngineMixin
from card_defs import normalize_card, validate_card_definition
from engine import ActionDeferred
from source_features import BUILD_SPELL, BUILD_TECH, BUILD_UNIT, BUILD_UPGRADE, SF_HIDDEN, UF_BUILD_ON
from ultimate_features import SPELL_BITS, UPGRADE_ROWS


@dataclass
class CardProductionTask:
    card_id: str
    producer_key: tuple[int, int]
    owner: int
    mode: str
    started: float = field(default_factory=time.monotonic)
    finish_at: float = 0.0
    costs: tuple[int, int, int] = (0, 0, 0)
    finishing: bool = False


class CardEngineMixin(AbilityEngineMixin):
    """Version 1.44 All Cards Trigger Engine mixin."""

    def _init_massive_features(self) -> None:
        super()._init_massive_features()
        self._card_definitions: dict[str, dict[str, Any]] = {}
        self._card_enabled: dict[str, bool] = {}
        self._card_grants: dict[tuple[int, int], set[str]] = {}
        self._card_revokes: dict[tuple[int, int], set[str]] = {}
        self._card_hotkey_prev: dict[str, bool] = {}
        self._card_events: list[tuple[str, Any | None, dict[str, Any]]] = []
        self._card_tasks: dict[tuple[int, int], CardProductionTask] = {}
        self._card_click_counts: dict[tuple[str, int], int] = {}
        self._card_spell_ability_ids: dict[str, str] = {}
        self._card_reload_definitions()

    def _massive_begin_run(self) -> None:
        super()._massive_begin_run()
        self._card_reload_definitions()
        self._card_grants.clear(); self._card_revokes.clear(); self._card_hotkey_prev.clear()
        self._card_events.clear(); self._card_tasks.clear(); self._card_click_counts.clear()

    def _card_reload_definitions(self) -> None:
        definitions: dict[str, dict[str, Any]] = {}
        for index, raw in enumerate(getattr(getattr(self, "scenario", None), "cards", []) or [], 1):
            card = normalize_card(raw, index); errors = validate_card_definition(card, index)
            if errors:
                self.log("CARD DISABLED: " + "; ".join(errors)); continue
            definitions[str(card["id"]).casefold()] = card
        self._card_definitions = definitions
        self._card_enabled = {key: bool(value.get("enabled", True)) for key, value in definitions.items()}
        self._card_spell_ability_ids = {}
        for cid, card in definitions.items():
            if str(card.get("action")) != "Cast Native Spell": continue
            aid = "cardspell." + hashlib.sha1(cid.encode("utf-8")).hexdigest()[:20]
            ability = {
                "id": aid, "name": str(card.get("name", card.get("spell", "Native Spell"))),
                "description": f"Native spell routed by command card {card.get('id')}", "icon": str(card.get("icon", "")),
                "hotkey": "", "target": str(card.get("target", "None")), "range": 32,
                "mana_cost": 0, "gold_cost": 0, "lumber_cost": 0, "oil_cost": 0,
                "cooldown": 0.0, "max_charges": 0, "caster_types": [], "enabled": True,
                "ai_enabled": False, "ai_priority": 50,
                "effects": [{"kind": "Native Spell", "spell": str(card.get("spell", "Healing")), "allow_wrong_caster": bool(card.get("allow_cross_faction", False))}],
            }
            self._ability_definitions[aid.casefold()] = ability; self._ability_enabled[aid.casefold()] = True
            self._card_spell_ability_ids[cid] = aid

    def _card_definition(self, value: Any, *, required: bool = True) -> dict[str, Any] | None:
        card = self._card_definitions.get(str(value or "").strip().casefold())
        if card is None and required: raise ValueError(f"Unknown command card ID: {value!r}")
        return card

    def _card_unit_by_key(self, key: tuple[int, int], world: list[Any] | None = None) -> Any | None:
        source = world if world is not None else self.units()
        return next((unit for unit in source if self._unit_key_massive(unit) == key and not (int(unit.sflags) & SF_HIDDEN)), None)

    def _card_resolve_producer(self, args: dict[str, Any], player: int, world: list[Any] | None = None) -> Any:
        reference = str(args.get("producer_reference", "")).strip()
        if reference:
            unit = self._resolve_unit_reference(reference)
        else:
            source = world if world is not None else self.units()
            selected = self._ability_selected_units(source, player)
            unit = selected[0] if selected else None
        if unit is None: raise RuntimeError("Command card requires a selected producer or a valid producer unit reference")
        return unit

    def _card_known(self, producer: Any, card: dict[str, Any]) -> bool:
        key = self._unit_key_massive(producer); cid = str(card["id"]).casefold()
        if cid in self._card_revokes.get(key, set()): return False
        if cid in self._card_grants.get(key, set()): return True
        allowed = {int(value) for value in card.get("producer_types", [])}
        return not allowed or int(producer.unit_type) in allowed

    def _card_available_reason(self, producer: Any, card: dict[str, Any]) -> str:
        cid = str(card["id"]).casefold(); key = self._unit_key_massive(producer)
        if not self._card_enabled.get(cid, False): return "card disabled"
        if not self._card_known(producer, card): return "producer does not have card"
        if key in self._card_tasks: return "producer already has trigger-card production"
        if card.get("action") in {"Train Unit", "Research Spell", "Research Upgrade", "Upgrade Building"}:
            try:
                if int(self.pm.read_ushort(producer.address + 0x1C)) & UF_BUILD_ON: return "producer is busy"
            except Exception: return "producer state is unavailable"
        if card.get("action") == "Train Unit":
            try:
                if not bool(super().massive_value("Source Player Has Enough Food", {"player": int(producer.owner), "food": 1}, int(producer.owner))): return "not enough food"
            except Exception: pass
        costs = self._card_costs(producer, card)
        for resource, cost in zip(("Gold", "Lumber", "Oil"), costs):
            if cost and self._read_resource(int(producer.owner), resource) < cost: return f"not enough {resource.lower()}"
        return ""

    def _card_costs(self, producer: Any, card: dict[str, Any]) -> tuple[int, int, int]:
        defaults = self._mission132_unit_cost(int(card.get("unit_type", 0))) if card.get("action") == "Train Unit" else (0, 0, 0)
        values = []
        for index, key in enumerate(("gold_cost", "lumber_cost", "oil_cost")):
            authored = int(card.get(key, -1)); values.append(defaults[index] if authored < 0 else authored)
        return tuple(values)  # type: ignore[return-value]

    def _card_queue_event(self, event: str, producer: Any | None, card: dict[str, Any], **extra: Any) -> None:
        payload = {"card_id": str(card["id"]), "card_name": str(card["name"]), **extra}
        self._card_events.append((event, producer, payload))

    def _card_native_order(self, card: dict[str, Any]) -> tuple[int, int] | None:
        action = str(card.get("action"))
        if action == "Train Unit": return BUILD_UNIT, int(card.get("unit_type", 0))
        if action == "Research Spell":
            spell = str(card.get("spell", "Healing"))
            if spell not in SPELL_BITS: raise ValueError(f"Unknown spell {spell!r}")
            return BUILD_SPELL, int(SPELL_BITS[spell])
        if action == "Research Upgrade":
            upgrade = str(card.get("upgrade", "Melee Attack"))
            if upgrade not in UPGRADE_ROWS: raise ValueError(f"Unknown upgrade {upgrade!r}")
            return BUILD_TECH, int(UPGRADE_ROWS[upgrade])
        if action == "Upgrade Building": return BUILD_UPGRADE, int(card.get("building_type", 58))
        return None

    def _card_start_production(self, producer: Any, card: dict[str, Any], player: int) -> None:
        reason = self._card_available_reason(producer, card)
        if reason:
            self._card_queue_event("Card Production Failed", producer, card, reason=reason)
            raise RuntimeError(f"{card['name']}: {reason}")
        key = self._unit_key_massive(producer); native = self._card_native_order(card)
        if bool(card.get("native_first", True)) and native is not None:
            if self._source128_direct_start(producer, native[0], native[1]):
                self._card_tasks[key] = CardProductionTask(str(card["id"]).casefold(), key, int(producer.owner), "native")
                self._card_queue_event("Card Production Started", producer, card, mode="native")
                return
        if not bool(card.get("allow_cross_faction", False)):
            reason = "Warcraft rejected this producer/card pairing and cross-faction fallback is disabled"
            self._card_queue_event("Card Production Failed", producer, card, reason=reason); raise RuntimeError(reason)
        if str(card.get("action")) == "Upgrade Building":
            reason = "cross-faction building replacement has no validated trigger fallback"
            self._card_queue_event("Card Production Failed", producer, card, reason=reason); raise RuntimeError(reason)
        costs = self._card_costs(producer, card)
        if not self._mission132_apply_cost(int(producer.owner), costs):
            reason = "resources changed before fallback payment"
            self._card_queue_event("Card Production Failed", producer, card, reason=reason); raise RuntimeError(reason)
        seconds = max(0.0, float(card.get("seconds", 1.0)))
        self._card_tasks[key] = CardProductionTask(str(card["id"]).casefold(), key, int(producer.owner), "cross-faction", finish_at=time.monotonic() + seconds, costs=costs)
        self._card_queue_event("Card Production Started", producer, card, mode="cross-faction", seconds=seconds)

    def _card_finish_fallback(self, task: CardProductionTask, producer: Any, card: dict[str, Any]) -> None:
        action = str(card.get("action")); owner = int(task.owner)
        if action == "Train Unit":
            self.action("Create Units", {"player": owner, "unit": int(card.get("unit_type", 0)), "amount": 1, "location": "Anywhere", "x": int(producer.x), "y": int(producer.y)}, owner)
        elif action == "Research Spell":
            super().massive_action("Give Spell", {"player": owner, "spell": str(card.get("spell", "Healing"))}, owner)
        elif action == "Research Upgrade":
            super().massive_action("Add Upgrade Level", {"player": owner, "upgrade": str(card.get("upgrade", "Melee Attack")), "amount": 1}, owner)
        else:
            raise RuntimeError(f"No trigger fallback for card action {action}")

    def _card_activate(self, producer: Any, card: dict[str, Any], player: int) -> None:
        cid = str(card["id"]).casefold(); owner = int(producer.owner)
        action = str(card.get("action"))
        if action == "Source Callback":
            pass
        elif action in {"Train Unit", "Research Spell", "Research Upgrade", "Upgrade Building"}:
            self._card_start_production(producer, card, player)
        elif action == "Build Structure":
            super().massive_action("Begin Building Placement", {"player": owner, "building": int(card.get("building_type", 58)), "show_prompt": True}, player)
        elif action == "Run Trigger Function":
            super().massive_action("Call Trigger Function", {"trigger": str(card.get("trigger", "Card Function")), "arguments_json": str(card.get("arguments_json", "{}"))}, player)
        elif action == "Cast Native Spell":
            reference = f"__card_producer_{producer.address:X}"; self._save_reference(reference, producer)
            aid = self._card_spell_ability_ids.get(cid)
            if not aid: raise RuntimeError("native-spell card ability bridge is unavailable")
            if str(card.get("target", "None")) in {"None", "Self"}:
                super().massive_action("Cast Ability", {"ability_id": aid, "caster_reference": reference}, player)
            else:
                super().massive_action("Begin Ability Targeting", {"ability_id": aid, "caster_reference": reference, "show_prompt": True}, player)
        elif action == "Cast Custom Ability":
            reference = f"__card_producer_{producer.address:X}"; self._save_reference(reference, producer)
            super().massive_action("Cast Ability", {"ability_id": str(card.get("ability_id", "")), "caster_reference": reference}, player)
        else:
            raise RuntimeError(f"Unsupported card action {action}")
        # Commit the click only after a non-deferred route accepts it. This keeps
        # simulation-mailbox retries from emitting duplicate card edges.
        self._card_click_counts[(cid, owner)] = int(self._card_click_counts.get((cid, owner), 0)) + 1
        self._card_queue_event("Card Clicked", producer, card)

    def _card_poll_hotkeys(self, world: list[Any]) -> None:
        selected = self._ability_selected_units(world, 0)
        if not selected: return
        producer = selected[0]
        eligible = sorted((card for card in self._card_definitions.values() if card.get("hotkey") and self._card_known(producer, card)), key=lambda card: (str(card.get("page")), int(card.get("slot", 0)), str(card.get("id"))))
        seen: set[str] = set()
        for card in eligible:
            hotkey = str(card.get("hotkey", ""));
            if hotkey in seen: continue
            seen.add(hotkey)
            try: down = bool(self._mission131_key_state(self._mission131_vk(hotkey)))
            except Exception: down = False
            previous = bool(self._card_hotkey_prev.get(hotkey, False)); self._card_hotkey_prev[hotkey] = down
            if down and not previous:
                try: self._card_activate(producer, card, int(producer.owner))
                except ActionDeferred: return
                except Exception as exc: self.log(f"CARD HOTKEY REJECTED: {card['name']}: {exc}")

    def _massive_prepare_pre(self, world: list[Any]) -> bool:
        result = super()._massive_prepare_pre(world)
        if result is False: return False
        now = time.monotonic()
        for key, task in list(self._card_tasks.items()):
            producer = self._card_unit_by_key(key, world); card = self._card_definition(task.card_id, required=False)
            if card is None:
                self._card_tasks.pop(key, None); continue
            if producer is None:
                self._card_queue_event("Card Production Failed", None, card, reason="producer no longer exists")
                self._card_tasks.pop(key, None); continue
            if task.mode == "native":
                try: active = bool(int(self.pm.read_ushort(producer.address + 0x1C)) & UF_BUILD_ON)
                except Exception: active = True
                if active: continue
            elif now < task.finish_at: continue
            else:
                try:
                    task.finishing = True; self._card_finish_fallback(task, producer, card)
                except ActionDeferred: return False
                except Exception as exc:
                    self._mission132_apply_cost(task.owner, task.costs, refund=True)
                    self._card_queue_event("Card Production Failed", producer, card, reason=str(exc))
                    self._card_tasks.pop(key, None); self.log(f"CARD PRODUCTION FAILED: {card['name']}: {exc}"); continue
            self._card_queue_event("Card Production Finished", producer, card, mode=task.mode)
            self._card_tasks.pop(key, None)
        self._card_poll_hotkeys(world)
        return True

    def _massive_prepare_events(self, current: dict[tuple[int, int], Any], previous: dict[tuple[int, int], Any]) -> None:
        super()._massive_prepare_events(current, previous)
        pending, self._card_events = self._card_events, []
        for event, producer, extra in pending: self._mission_add_event(event, producer, **extra)
        live = set(current)
        self._card_grants = {key: value for key, value in self._card_grants.items() if key in live}
        self._card_revokes = {key: value for key, value in self._card_revokes.items() if key in live}

    def massive_value(self, kind: str, args: dict[str, Any], player: int) -> Any:
        if kind == "Card Defined": return int(self._card_definition(args.get("card_id"), required=False) is not None)
        if kind in {"Producer Has Card", "Card Available", "Card Production Active"}:
            card = self._card_definition(args.get("card_id"), required=False)
            try: producer = self._card_resolve_producer(args, player)
            except Exception: producer = None
            if card is None or producer is None: return 0
            if kind == "Producer Has Card": return int(self._card_known(producer, card))
            if kind == "Card Available": return int(not self._card_available_reason(producer, card))
            return int(self._unit_key_massive(producer) in self._card_tasks)
        if kind in {"Card Clicked", "Card Production Started", "Card Production Finished", "Card Production Failed"}:
            return self._mission_event_count(kind, args, player)
        if kind == "Card Click Count":
            cid = str(args.get("card_id", "")).strip().casefold(); owner = int(args.get("player", -1))
            return sum(value for (key, card_owner), value in self._card_click_counts.items() if (not cid or cid == key) and (owner < 0 or owner == card_owner))
        return super().massive_value(kind, args, player)

    def massive_action(self, kind: str, args: dict[str, Any], player: int) -> bool:
        if kind in {"Grant Card", "Revoke Card"}:
            card = self._card_definition(args.get("card_id")); producer = self._card_resolve_producer(args, player)
            key = self._unit_key_massive(producer); cid = str(card["id"]).casefold()
            if kind == "Grant Card": self._card_grants.setdefault(key, set()).add(cid); self._card_revokes.setdefault(key, set()).discard(cid)
            else: self._card_revokes.setdefault(key, set()).add(cid); self._card_grants.setdefault(key, set()).discard(cid)
            return True
        if kind in {"Enable Card", "Disable Card"}:
            card = self._card_definition(args.get("card_id")); self._card_enabled[str(card["id"]).casefold()] = kind == "Enable Card"; return True
        if kind in {"Enable All Human Cards", "Enable All Orc Cards", "Enable All Cards", "Disable All Cards"}:
            wanted = "Human" if "Human" in kind else "Orc" if "Orc" in kind else None
            enabled = kind != "Disable All Cards"
            for cid, card in self._card_definitions.items():
                if wanted is None or str(card.get("race")) == wanted: self._card_enabled[cid] = enabled
            return True
        if kind == "Activate Card":
            card = self._card_definition(args.get("card_id")); producer = self._card_resolve_producer(args, player); self._card_activate(producer, card, player); return True
        if kind == "Cancel Trigger Card Production":
            producer = self._card_resolve_producer(args, player); key = self._unit_key_massive(producer); task = self._card_tasks.pop(key, None)
            if task and task.mode == "cross-faction": self._mission132_apply_cost(task.owner, task.costs, refund=True)
            return True
        if kind == "Show Trigger Card Page":
            producer = self._card_resolve_producer(args, player); page = str(args.get("page", "")).strip()
            cards = [card for card in self._card_definitions.values() if self._card_enabled.get(str(card["id"]).casefold(), False) and self._card_known(producer, card) and (not page or str(card.get("page")) == page)]
            cards.sort(key=lambda card: (str(card.get("page")), int(card.get("slot", 0)), str(card.get("name"))))
            lines = [str(args.get("title", "TRIGGER CARDS"))]
            for card in cards[:32]:
                key = str(card.get("hotkey", "")); prefix = f"[{key}] " if key else f"[{int(card.get('slot',0))+1}] "
                lines.append(prefix + str(card.get("name")))
            if len(cards) > 32: lines.append(f"...and {len(cards)-32} more; filter by page")
            self._game_message({"text": "\n".join(lines), "color": "White — native highlight", "recipients": "All active players", "seconds": max(1, int(args.get("seconds", 8))), "also_log": False}, player); return True
        if kind == "Dump Card State":
            payload = {"definitions": len(self._card_definitions), "enabled": sum(self._card_enabled.values()), "active": [task.card_id for task in self._card_tasks.values()], "clicks": sum(self._card_click_counts.values())}
            self.log("CARD STATE: " + json.dumps(payload, sort_keys=True)); return True
        return super().massive_action(kind, args, player)
