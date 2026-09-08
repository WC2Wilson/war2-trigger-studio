from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path
from typing import Any

from engine import ActionDeferred
from campaign_features import CampaignFeatureMixin
from massive_features import CountdownState
from source_features import (
    BUILD_UNIT,
    BUILD_TECH,
    BUILD_SPELL,
    BUILD_UPGRADE,
    UF_BUILD_ON,
    PEON_LOADED,
    PEON_HARVEST_GOLD,
    PEON_HARVEST_LUMBER,
    EMPTY_CARGO_SLOT,
)
from source_features_128 import (
    SF_HIDDEN,
    SF_COMPLETED,
    SF_SELECTED,
    IS_PEON,
    IS_TANKER,
    IS_TRANSPORT,
    IS_GOLDMINE,
    IS_OILPATCH,
    SOURCE128_SPELL_ACTIONS,
)
from ultimate_features import SPELL_BITS, UPGRADE_ROWS


MISSION130_EVENT_TYPES = (
    "Construction Started",
    "Construction Completed",
    "Construction Cancelled",
    "Training Started",
    "Unit Trained",
    "Technology Research Started",
    "Technology Research Completed",
    "Spell Research Started",
    "Spell Research Completed",
    "Upgrade Completed",
    "Resource Deposited",
    "Worker Returned Resources",
    "Worker Entered Resource",
    "Worker Entered Mine",
    "Worker Entered Oil Patch",
    "Worker Exited Resource",
    "Passenger Boarded Transport",
    "Passenger Unloaded Transport",
    "Unit Captured",
    "Unit Rescued",
    "Projectile Hit Unit",
    "Projectile Hit Location",
    "Unit Order Changed",
    "Player Issued Order (Inferred)",
    "Player Command Button Used (Inferred)",
    "Unit Selected",
    "Unit Deselected",
    "Actor Selected",
    "Actor Deselected",
    "Enemy Entered Actor Sight",
    "Enemy Left Actor Sight",
    "Enemy Entered Actor Attack Range",
    "Enemy Left Actor Attack Range",
)

EVENT_CONDITION_ALIASES = {name: name for name in MISSION130_EVENT_TYPES}


class MissionFeature130Mixin(CampaignFeatureMixin):
    """Trigger Studio 1.30 complete mission-scripting layer.

    The legacy source is used as the feature checklist, but this implementation keeps
    Remastered safety boundaries explicit:

    * simulation/gameplay mutations use already verified native callbacks or known
      state layouts;
    * campaign presentation uses the safe Warcraft in-game message/camera/audio
      routes unless a modern Remastered front-end ABI has been proven;
    * modern native objectives/briefing/portrait/movie/save-front-end calls are
      present as experimental fail-closed actions with optional safe fallback.

    This prevents the editor from turning source-code similarity into an unsafe
    guess about modern C++ object ownership or calling conventions.
    """

    CHECKPOINT_VERSION = 1300
    CHECKPOINT_DIRNAME = "checkpoints"
    UI_PROBE_STRINGS = (
        b"fe_objectives",
        b"objectives_header",
        b"objectives_background",
        b"hide_objectives",
        b"generic_objectives",
    )

    def _init_massive_features(self) -> None:
        super()._init_massive_features()
        self._mission_events: dict[str, list[dict[str, Any]]] = {}
        self._mission_runtime_by_key: dict[tuple[int, int], dict[str, Any]] = {}
        self._mission_missiles: dict[int, dict[str, Any]] = {}
        self._mission_spell_bits: dict[int, int] = {}
        self._mission_tech_levels: bytes | None = None
        self._mission_actor_sight_pairs: set[tuple[str, tuple[int, int]]] = set()
        self._mission_actor_attack_pairs: set[tuple[str, tuple[int, int]]] = set()
        self._mission_transmissions: list[dict[str, Any]] = []
        self._mission_soft_input_lock = False
        self._mission_input_lock_mode = "Off"
        self._mission_soft_lock_logged = False
        self._mission_ui_probe: dict[str, Any] | None = None
        self._mission_checkpoint_last = ""
        self._mission_checkpoint_restore_serial = 0
        self._mission_audio_until = 0.0
        self._mission_music_state: dict[str, Any] = {"track": "", "state": "Stopped", "volume": 100}
        self._mission_screen_fade_state = "Visible"

    def _massive_begin_run(self) -> None:
        super()._massive_begin_run()
        self._mission_events.clear()
        self._mission_runtime_by_key.clear()
        self._mission_missiles.clear()
        self._mission_spell_bits.clear()
        self._mission_tech_levels = None
        self._mission_actor_sight_pairs.clear()
        self._mission_actor_attack_pairs.clear()
        self._mission_transmissions.clear()
        self._mission_soft_input_lock = False
        self._mission_input_lock_mode = "Off"
        self._mission_soft_lock_logged = False
        self._mission_checkpoint_last = ""
        self._mission_audio_until = 0.0
        self._mission_music_state = {"track": "", "state": "Stopped", "volume": 100}
        self._mission_screen_fade_state = "Visible"

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _mission_actor_names(raw: Any) -> list[str]:
        text = str(raw or "").replace(";", ",")
        return [part.strip() for part in text.split(",") if part.strip()]

    def _mission_add_event(self, event_type: str, unit: Any | None = None, **extra: Any) -> None:
        record: dict[str, Any] = {"event_type": str(event_type), "amount": int(extra.pop("amount", 1))}
        if unit is not None:
            record.update({
                "unit": unit,
                "key": self._unit_key_massive(unit),
                "address": int(unit.address),
                "player": int(unit.owner),
                "unit_type": int(unit.unit_type),
                "x": int(unit.x),
                "y": int(unit.y),
                "health": int(unit.health),
                "mana": int(getattr(unit, "mana", 0)),
            })
        record.update(extra)
        self._mission_events.setdefault(str(event_type), []).append(record)
        self._available_events.add(str(event_type))

    def _mission_prime_record(self, record: dict[str, Any]) -> None:
        unit = record.get("unit")
        self._set_event_context(str(record.get("event_type", "Mission Event")), unit, int(record.get("amount", 1)), unit)
        for key, value in record.items():
            if key not in {"unit"}:
                self._event_context[key] = value

    def _prime_event_context(self, event_type: str) -> bool:
        if super()._prime_event_context(event_type):
            return True
        records = self._mission_events.get(str(event_type), [])
        if records:
            self._mission_prime_record(records[0])
            return True
        return False

    def _mission_unit_runtime(self, unit: Any) -> dict[str, Any]:
        result: dict[str, Any] = {
            "selected": bool(int(unit.sflags) & SF_SELECTED),
            "hidden": bool(int(unit.sflags) & SF_HIDDEN),
            "action": int(unit.action),
            "next_action": int(unit.next_action),
            "target_x": int(unit.target_x),
            "target_y": int(unit.target_y),
            "target_unit": int(unit.target_unit),
            "owner": int(unit.owner),
            "unit_type": int(unit.unit_type),
            "x": int(unit.x),
            "y": int(unit.y),
        }
        try:
            type_flags = int(self._source128_flags(int(unit.unit_type)))
        except Exception:
            type_flags = 0
        result["type_flags"] = type_flags
        if int(unit.unit_type) >= 58:
            try:
                flags = int(self.pm.read_ushort(unit.address + 0x1C))
                result.update({
                    "build_flags": flags,
                    "production_active": bool(flags & UF_BUILD_ON),
                    "production_order": int(self.pm.read_uchar(unit.address + 0x6C)) if flags & UF_BUILD_ON else -1,
                    "production_parm": int(self.pm.read_uchar(unit.address + 0x6D)) if flags & UF_BUILD_ON else -1,
                    "production_current": int(self.pm.read_ushort(unit.address + 0x6E)) if flags & UF_BUILD_ON else 0,
                    "production_total": int(self.pm.read_ushort(unit.address + 0x70)) if flags & UF_BUILD_ON else 0,
                })
            except Exception:
                result.update({"production_active": False, "production_order": -1, "production_parm": -1})
        if type_flags & (IS_PEON | IS_TANKER):
            try:
                result["cargo_flags"] = int(self.pm.read_uchar(unit.address + 0x75))
                result["cargo_amount"] = int(self.pm.read_ushort(unit.address + 0x78))
            except Exception:
                result["cargo_flags"] = 0
                result["cargo_amount"] = 0
        if type_flags & IS_TRANSPORT:
            try:
                result["transport_slots"] = tuple(int(v) for v in self._source_transport_slots(unit))
            except Exception:
                result["transport_slots"] = tuple()
        return result

    @staticmethod
    def _mission_resource_from_cargo(flags: int) -> str:
        if flags & PEON_HARVEST_GOLD:
            return "Gold"
        if flags & PEON_HARVEST_LUMBER:
            return "Lumber"
        return "Oil"

    def _mission_slot_lookup(self, snapshot: dict[tuple[int, int], Any]) -> dict[int, Any]:
        result: dict[int, Any] = {}
        pool = int(getattr(self, "unit_pool", 0))
        if not pool:
            return result
        for unit in snapshot.values():
            slot = (int(unit.address) - pool) // 152
            if 0 <= slot < int(getattr(self, "max_units", 1600)):
                result[slot] = unit
        return result

    def _mission_sample_progression(self) -> tuple[dict[int, int], bytes | None]:
        spells: dict[int, int] = {}
        tech: bytes | None = None
        try:
            tables = self._resolve_progression_tables()
            for owner in range(8):
                spells[owner] = int(self.pm.read_uint(int(tables["spells"]) + owner * 4))
            if "tech_levels" in tables:
                tech = bytes(self.pm.read_bytes(int(tables["tech_levels"]), 176))
        except Exception:
            pass
        return spells, tech

    def _mission_sample_missiles(self) -> dict[int, dict[str, Any]]:
        result: dict[int, dict[str, Any]] = {}
        try:
            for missile in self._active_missiles():
                result[int(missile.address)] = {
                    "address": int(missile.address), "x": int(missile.x), "y": int(missile.y),
                    "target_x": int(missile.target_x), "target_y": int(missile.target_y),
                    "target_unit": int(missile.target_unit), "owner_unit": int(missile.owner_unit),
                    "missile_type": int(missile.missile_type), "action": int(missile.action),
                    "damage": int(missile.damage),
                }
        except Exception:
            pass
        return result

    def _mission_unit_by_address(self, *snapshots: dict[tuple[int, int], Any], address: int) -> Any | None:
        address = int(address)
        if not address:
            return None
        for snapshot in snapshots:
            for unit in snapshot.values():
                if int(unit.address) == address:
                    return unit
        return None

    def _mission_event_matches(self, record: dict[str, Any], args: dict[str, Any], player: int) -> bool:
        unit = record.get("unit")
        if "player" in args and args.get("player") not in {None, ""}:
            wanted_owner = int(args.get("player", player))
            actual_owner = int(record.get("player", getattr(unit, "owner", -1)))
            if wanted_owner >= 0 and actual_owner != wanted_owner:
                return False
        if unit is not None:
            if "unit" in args:
                wanted = args.get("unit", "Any")
                if wanted != "Any" and str(wanted).strip() not in {"", "-1"} and int(wanted) != int(record.get("unit_type", unit.unit_type)):
                    return False
            location_name = str(args.get("location", "Anywhere"))
            if location_name and location_name != "Anywhere":
                try:
                    location = self._find_location(location_name)
                except Exception:
                    return False
                if not (int(location.left) <= int(record.get("x", unit.x)) <= int(location.right) and int(location.top) <= int(record.get("y", unit.y)) <= int(location.bottom)):
                    return False
        handled = {"resource", "actor", "target_actor", "spell", "upgrade"}
        for field in handled:
            wanted = str(args.get(field, "")).strip()
            if wanted and wanted not in {"Any", "Any actor", "Any spell", "Any upgrade", "Any resource"}:
                actual = str(record.get(field, "")).strip()
                if actual.casefold() != wanted.casefold():
                    return False

        # 1.40: event-specific editor fields are automatically filterable when
        # the runtime record publishes the same key. This keeps event conditions
        # customizable without hard-coding a separate matcher for every new legacy
        # edge. Comparison/count fields are evaluation controls, not record data.
        reserved = {"player", "unit", "location", "comparison", "amount", "negate", *handled}
        wildcards = {"", "any", "-1", "none"}
        for field, wanted in args.items():
            if field in reserved or field not in record:
                continue
            if str(wanted).strip().casefold() in wildcards:
                continue
            actual = record.get(field)
            try:
                # Bool is intentionally compared as its integer value too.
                if isinstance(actual, (int, float, bool)) or isinstance(wanted, (int, float, bool)):
                    if float(actual) != float(wanted):
                        return False
                    continue
            except (TypeError, ValueError):
                pass
            if str(actual).strip().casefold() != str(wanted).strip().casefold():
                return False
        return True

    def _mission_event_count(self, event_type: str, args: dict[str, Any], player: int) -> int:
        records = self._mission_events.get(event_type)
        if records is not None:
            matches = [r for r in records if self._mission_event_matches(r, args, player)]
            if matches:
                self._mission_prime_record(matches[0])
            return len(matches)
        # Bridge the original MassiveFeature events into the same generic counter.
        if event_type == "Unit Created":
            units = list(getattr(self, "created_units", []))
        elif event_type == "Unit Died":
            units = list(getattr(self, "died_units", []))
        elif event_type == "Unit Removed":
            units = list(getattr(self, "removed_units", []))
        else:
            units = []
        if units:
            matches = []
            for unit in units:
                record = {"event_type": event_type, "unit": unit, "player": int(unit.owner), "unit_type": int(unit.unit_type), "x": int(unit.x), "y": int(unit.y), "amount": 1}
                if self._mission_event_matches(record, args, player):
                    matches.append(record)
            if matches:
                self._mission_prime_record(matches[0])
            return len(matches)
        if event_type in getattr(self, "_available_events", set()):
            self._prime_event_context(event_type)
            return 1
        return 0

    def _mission_probe_campaign_ui(self, *, force: bool = False) -> dict[str, Any]:
        if self._mission_ui_probe is not None and not force:
            return self._mission_ui_probe
        result = {"status": "Unavailable", "found": [], "missing": [], "abi": "Unverified"}
        try:
            image = bytes(self.pm.read_bytes(self.base, self.image_size))
            for marker in self.UI_PROBE_STRINGS:
                if marker in image:
                    result["found"].append(marker.decode("ascii", errors="replace"))
                else:
                    result["missing"].append(marker.decode("ascii", errors="replace"))
            result["status"] = "Detected / ABI Unverified" if len(result["found"]) >= 4 else "Unavailable"
        except Exception as exc:
            result["error"] = str(exc)
        self._mission_ui_probe = result
        return result

    @classmethod
    def _mission_checkpoint_dir(cls) -> Path:
        path = Path(__file__).resolve().with_name(cls.CHECKPOINT_DIRNAME)
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _mission_checkpoint_slug(name: Any) -> str:
        text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "checkpoint").strip()).strip("._")
        return text[:96] or "checkpoint"

    def _mission_checkpoint_path(self, name: Any) -> Path:
        return self._mission_checkpoint_dir() / (self._mission_checkpoint_slug(name) + ".json")

    def _mission_checkpoint_payload(self, name: str) -> dict[str, Any]:
        now = time.monotonic()
        timers: dict[str, Any] = {}
        for timer_name, timer in self.countdown_timers.items():
            timers[str(timer_name)] = {
                "duration": float(timer.duration), "remaining": float(timer.value(now)),
                "running": bool(timer.running), "ever_started": bool(timer.ever_started),
            }
        actors: dict[str, Any] = {}
        for actor_name, meta in self._campaign_actor_meta.items():
            unit = self._resolve_unit_reference(actor_name)
            record = dict(meta)
            record["state"] = self._campaign_actor_state(actor_name)
            if unit is not None:
                record.update({
                    "owner": int(unit.owner), "unit_type": int(unit.unit_type), "x": int(unit.x), "y": int(unit.y),
                    "health": int(unit.health), "mana": int(getattr(unit, "mana", 0)), "sflags": int(unit.sflags),
                })
            actors[str(actor_name)] = record
        resources: dict[str, dict[str, int]] = {}
        for owner in range(8):
            try:
                resources[str(owner)] = {name: int(self._read_resource(owner, name)) for name in ("Gold", "Lumber", "Oil")}
            except Exception:
                pass
        return {
            "format": "War2TriggerStudioCampaignCheckpoint",
            "version": self.CHECKPOINT_VERSION,
            "name": str(name),
            "saved_unix": time.time(),
            "map_file": str(getattr(getattr(self, "scenario", None), "map_file", "") or ""),
            "variables": dict(self.variables),
            "counters": {str(k): int(v) for k, v in dict(getattr(self, "counters", {})).items()},
            "switches": dict(getattr(self, "switches", {})),
            "timers": timers,
            "campaign_objectives": self._campaign_objectives,
            "rescue_totals": self._campaign_rescue_totals,
            "capture_totals": self._campaign_capture_totals,
            "rescue_goal": self._campaign_rescue_goal,
            "transmissions": self._mission_transmissions[-8:],
            "actors": actors,
            "resources": resources,
            "camera": list(self._campaign_current_camera() or (0, 0)),
        }

    def _mission_write_checkpoint(self, name: str) -> Path:
        path = self._mission_checkpoint_path(name)
        payload = self._mission_checkpoint_payload(name)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp.replace(path)
        self._mission_checkpoint_last = str(path)
        self.log(f"CAMPAIGN CHECKPOINT SAVED: {path.name}")
        return path

    def _mission_restore_actor(self, name: str, record: dict[str, Any], *, recreate_missing: bool, player: int) -> None:
        owner = int(record.get("owner", player)); unit_type = int(record.get("unit_type", 0)); x = int(record.get("x", 0)); y = int(record.get("y", 0))
        candidates = [u for u in self.units() if int(u.owner) == owner and int(u.unit_type) == unit_type]
        unit = min(candidates, key=lambda u: (int(u.x)-x)**2 + (int(u.y)-y)**2, default=None)
        if unit is None and recreate_missing and str(record.get("state", "Alive")) not in {"Dead", "Removed", "Missing"}:
            before = {int(u.address) for u in self.units()}
            self.action("Create Units", {"player": owner, "new_unit": unit_type, "amount": 1, "location": "Anywhere", "x": x, "y": y}, player)
            created = [u for u in self.units() if int(u.address) not in before and int(u.owner) == owner and int(u.unit_type) == unit_type]
            unit = min(created, key=lambda u: (int(u.x)-x)**2 + (int(u.y)-y)**2, default=None)
        self._campaign_register_actor(name, unit, created=bool(record.get("created", False)))
        if unit is None:
            self._campaign_actor_status[name] = str(record.get("state", "Missing"))
            return
        try:
            if int(unit.unit_type) < 58 and (int(unit.x), int(unit.y)) != (x, y):
                moved = self._move_mobile_unit(unit, x, y)
                self._save_reference(name, moved); unit = moved
        except Exception:
            pass
        # Use the existing generation-safe reference actions so checkpoint restore
        # inherits the runtime's proven HP/mana write semantics.
        try:
            super().massive_action("Set Unit Reference Health", {"reference": name, "amount": int(record.get("health", unit.health))}, player)
        except Exception:
            pass
        try:
            super().massive_action("Set Unit Reference Mana", {"reference": name, "amount": int(record.get("mana", getattr(unit, "mana", 0)))}, player)
        except Exception:
            pass

    def _mission_load_checkpoint(self, name: str, *, restore_resources: bool, restore_camera: bool, recreate_missing: bool, player: int) -> Path:
        path = self._mission_checkpoint_path(name)
        if not path.exists():
            raise RuntimeError(f"Campaign checkpoint does not exist: {path.name}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("format") != "War2TriggerStudioCampaignCheckpoint":
            raise RuntimeError(f"Not a Trigger Studio campaign checkpoint: {path.name}")
        self.variables = dict(data.get("variables", {}))
        if hasattr(self, "counters"):
            self.counters.clear(); self.counters.update({str(k): int(v) for k, v in dict(data.get("counters", {})).items()})
        if hasattr(self, "switches"):
            self.switches.clear(); self.switches.update(dict(data.get("switches", {})))
        self.countdown_timers = {}
        now = time.monotonic()
        for timer_name, raw in dict(data.get("timers", {})).items():
            remaining = max(0.0, float(raw.get("remaining", 0.0)))
            timer = CountdownState(float(raw.get("duration", remaining)), remaining)
            timer.running = bool(raw.get("running", False)) and remaining > 0
            timer.ever_started = bool(raw.get("ever_started", False))
            timer.end_at = now + remaining if timer.running else 0.0
            self.countdown_timers[str(timer_name)] = timer
        self._campaign_objectives = {str(k): dict(v) for k, v in dict(data.get("campaign_objectives", {})).items()}
        self.objectives = {name: str(rec.get("text", name)) for name, rec in self._campaign_objectives.items()}
        self.completed_objectives = {name for name, rec in self._campaign_objectives.items() if str(rec.get("state")) == "Completed"}
        self._campaign_rescue_totals = {int(k): int(v) for k, v in dict(data.get("rescue_totals", {})).items()}
        self._campaign_capture_totals = {int(k): int(v) for k, v in dict(data.get("capture_totals", {})).items()}
        self._campaign_rescue_goal = {int(k): int(v) for k, v in dict(data.get("rescue_goal", {})).items()}
        self._mission_transmissions = [dict(v) for v in list(data.get("transmissions", []))][-8:]
        if restore_resources:
            for owner_text, resource_row in dict(data.get("resources", {})).items():
                owner = int(owner_text)
                for resource, amount in dict(resource_row).items():
                    try:
                        _name, address = self._resource_address(owner, resource)
                        self.pm.write_uint(address, max(0, min(0x7FFFFFFF, int(amount))))
                    except Exception:
                        pass
        self._campaign_actor_meta.clear(); self._campaign_actor_status.clear()
        for actor_name, record in dict(data.get("actors", {})).items():
            self._mission_restore_actor(str(actor_name), dict(record), recreate_missing=recreate_missing, player=player)
        if restore_camera:
            camera = list(data.get("camera", [0, 0]))
            if len(camera) >= 2:
                self._campaign_camera_call(int(camera[0]), int(camera[1]))
        self._campaign_hud_next = 0.0
        self._mission_checkpoint_restore_serial += 1
        self._mission_checkpoint_last = str(path)
        self.log(f"CAMPAIGN CHECKPOINT LOADED: {path.name}")
        return path

    def _mission_experimental_fallback(self, feature: str, args: dict[str, Any], player: int, fallback) -> bool:
        probe = self._mission_probe_campaign_ui()
        if not bool(args.get("fallback_to_safe", True)):
            raise RuntimeError(
                f"{feature}: Remastered front-end markers are {probe.get('status')}, but the modern C++ ABI is still unverified. "
                "The experimental native call failed closed instead of guessing an allocator/calling convention."
            )
        self.log(f"EXPERIMENTAL {feature}: native ABI unverified; safe Trigger Studio fallback used")
        return bool(fallback())

    # --------------------------------------------------------------- maintenance
    def _massive_prepare_pre(self, world: list[Any]) -> bool:
        result = super()._massive_prepare_pre(world)
        if result is False:
            return False
        if self._mission_soft_input_lock and self._campaign_cutscene_active:
            selected = [u for u in world if int(u.sflags) & SF_SELECTED]
            if selected:
                # Deselect through the native-verified cleanup callback when possible;
                # use the proven selected flag as a secondary fail-safe.
                for unit in selected:
                    try:
                        if "deselect_unit" in getattr(self, "remove_callees", {}):
                            self._call_cdecl(self.remove_callees["deselect_unit"], [unit.address])
                        else:
                            flags = int(self.pm.read_ushort(unit.address + 0x1E))
                            self.pm.write_ushort(unit.address + 0x1E, flags & ~SF_SELECTED)
                    except ActionDeferred:
                        return False
                    except Exception:
                        pass
            if not self._mission_soft_lock_logged:
                self.log("CUTSCENE INPUT: soft lock active (continuous native deselection; hard Remastered input callback remains experimental/fail-closed)")
                self._mission_soft_lock_logged = True
        return True

    def _massive_prepare_events(self, current: dict[tuple[int, int], Any], previous: dict[tuple[int, int], Any]) -> None:
        super()._massive_prepare_events(current, previous)
        self._mission_events = {}
        current_runtime = {key: self._mission_unit_runtime(unit) for key, unit in current.items()}
        old_runtime = self._mission_runtime_by_key
        current_by_slot = self._mission_slot_lookup(current)
        previous_by_slot = self._mission_slot_lookup(previous)

        # ------------------------- construction, selection, order, ownership
        for key, unit in current.items():
            rt = current_runtime.get(key, {})
            old_rt = old_runtime.get(key)
            old_unit = previous.get(key)
            if int(unit.unit_type) >= 58:
                if old_unit is None and not (int(unit.sflags) & SF_COMPLETED):
                    self._mission_add_event("Construction Started", unit)
                elif old_unit is not None and not (int(old_unit.sflags) & SF_COMPLETED) and (int(unit.sflags) & SF_COMPLETED):
                    self._mission_add_event("Construction Completed", unit)
            if old_rt is not None:
                if bool(rt.get("selected")) and not bool(old_rt.get("selected")):
                    self._mission_add_event("Unit Selected", unit)
                if bool(old_rt.get("selected")) and not bool(rt.get("selected")):
                    self._mission_add_event("Unit Deselected", unit)
                before_order = (old_rt.get("action"), old_rt.get("next_action"), old_rt.get("target_x"), old_rt.get("target_y"), old_rt.get("target_unit"))
                after_order = (rt.get("action"), rt.get("next_action"), rt.get("target_x"), rt.get("target_y"), rt.get("target_unit"))
                if before_order != after_order:
                    self._mission_add_event("Unit Order Changed", unit, old_action=old_rt.get("action", -1), new_action=rt.get("action", -1), old_next_action=old_rt.get("next_action", -1), new_next_action=rt.get("next_action", -1))
                    # A selected local-human unit changing order is the safest available
                    # non-hook approximation of a player-issued command. AI/combat can
                    # still alter a selected unit, so the event name and context remain
                    # explicitly Inferred rather than claiming an exact UI click hook.
                    try:
                        local_player = int(self.pm.read_uchar(self.message_path["local_player"]))
                    except Exception:
                        local_player = -1
                    if int(unit.owner) == local_player and (bool(rt.get("selected")) or bool(old_rt.get("selected"))):
                        self._mission_add_event("Player Issued Order (Inferred)", unit, inferred=True, old_action=old_rt.get("action", -1), new_action=rt.get("action", -1), old_next_action=old_rt.get("next_action", -1), new_next_action=rt.get("next_action", -1))
                        self._mission_add_event("Player Command Button Used (Inferred)", unit, inferred=True, command_guess=f"action {rt.get('action', -1)} / next {rt.get('next_action', -1)}", note="selected local unit order changed; exact command-button callback remains unhooked")
                if int(old_rt.get("owner", unit.owner)) != int(unit.owner):
                    self._mission_add_event("Unit Captured", unit, old_owner=int(old_rt.get("owner", -1)), new_owner=int(unit.owner))

        for key, old_unit in previous.items():
            if key not in current and int(old_unit.unit_type) >= 58 and not (int(old_unit.sflags) & SF_COMPLETED):
                self._mission_add_event("Construction Cancelled", old_unit, inferred=True, note="construction ended before completion; native cancel-vs-destruction hook not yet separated")

        # Named actor selection convenience events.
        for actor_name in list(self._campaign_actor_meta):
            actor = self._resolve_unit_reference(actor_name)
            if actor is None:
                continue
            key = self._unit_key_massive(actor)
            rt = current_runtime.get(key); old_rt = old_runtime.get(key)
            if rt is not None and old_rt is not None:
                if bool(rt.get("selected")) and not bool(old_rt.get("selected")):
                    self._mission_add_event("Actor Selected", actor, actor=actor_name)
                if bool(old_rt.get("selected")) and not bool(rt.get("selected")):
                    self._mission_add_event("Actor Deselected", actor, actor=actor_name)

        # ---------------------------------------- production lifecycle edges
        production_labels = {
            BUILD_UNIT: ("Training Started", "Unit Trained"),
            BUILD_TECH: ("Technology Research Started", "Technology Research Completed"),
            BUILD_SPELL: ("Spell Research Started", None),
            BUILD_UPGRADE: ("Technology Research Started", "Technology Research Completed"),
        }
        for key, unit in current.items():
            if int(unit.unit_type) < 58:
                continue
            rt = current_runtime.get(key, {}); old_rt = old_runtime.get(key)
            if old_rt is None:
                continue
            old_active = bool(old_rt.get("production_active", False)); active = bool(rt.get("production_active", False))
            old_order = int(old_rt.get("production_order", -1)); order = int(rt.get("production_order", -1))
            old_parm = int(old_rt.get("production_parm", -1)); parm = int(rt.get("production_parm", -1))
            if active and (not old_active or order != old_order or parm != old_parm):
                label = production_labels.get(order, (None, None))[0]
                if label:
                    extras: dict[str, Any] = {"production_order": order, "production_parm": parm}
                    if order == BUILD_UNIT: extras["trained_unit"] = parm
                    if order in {BUILD_TECH, BUILD_UPGRADE}:
                        extras["upgrade"] = next((name for name, row in UPGRADE_ROWS.items() if int(row) == parm), f"Row {parm}")
                    if order == BUILD_SPELL:
                        extras["spell"] = next((name for name, bit in SPELL_BITS.items() if int(bit) == parm), f"Bit {parm}")
                    self._mission_add_event(label, unit, **extras)
                    try:
                        local_player = int(self.pm.read_uchar(self.message_path["local_player"]))
                    except Exception:
                        local_player = -1
                    if int(unit.owner) == local_player and bool(rt.get("selected")):
                        self._mission_add_event("Player Command Button Used (Inferred)", unit, inferred=True, command_guess=label, production_order=order, production_parm=parm, note="selected local building entered native production state")
            if old_active and (not active or order != old_order or parm != old_parm):
                label = production_labels.get(old_order, (None, None))[1]
                if label:
                    event_unit = unit
                    extras = {"production_order": old_order, "production_parm": old_parm}
                    if old_order == BUILD_UNIT:
                        extras["trained_unit"] = old_parm
                        candidate = next((u for u in getattr(self, "created_units", []) if int(u.owner) == int(unit.owner) and int(u.unit_type) == old_parm), None)
                        if candidate is not None: event_unit = candidate
                    if old_order in {BUILD_TECH, BUILD_UPGRADE}:
                        extras["upgrade"] = next((name for name, row in UPGRADE_ROWS.items() if int(row) == old_parm), f"Row {old_parm}")
                    self._mission_add_event(label, event_unit, **extras)

        # ------------------------------------------ worker cargo/resource edges
        for key, unit in current.items():
            rt = current_runtime.get(key, {}); old_rt = old_runtime.get(key)
            if old_rt is None or not (int(rt.get("type_flags", 0)) & (IS_PEON | IS_TANKER)):
                continue
            old_cargo = int(old_rt.get("cargo_flags", 0)); cargo = int(rt.get("cargo_flags", 0))
            old_amount = int(old_rt.get("cargo_amount", 0))
            if old_cargo & PEON_LOADED and not (cargo & PEON_LOADED) and old_amount > 0:
                resource_name = self._mission_resource_from_cargo(old_cargo)
                self._mission_add_event("Resource Deposited", unit, resource=resource_name, amount=old_amount)
                self._mission_add_event("Worker Returned Resources", unit, resource=resource_name, amount=old_amount)
            # Hidden worker transitions are the source engine's mine/oil-patch
            # occupancy behavior. Exclude transport cargo to avoid conflating board.
            if bool(rt.get("hidden")) != bool(old_rt.get("hidden")):
                loaded_in_transport = False
                try:
                    loaded_in_transport = self._source_find_transport_for(unit) is not None
                except Exception:
                    pass
                if not loaded_in_transport:
                    if rt.get("hidden"):
                        self._mission_add_event("Worker Entered Resource", unit, inferred=True)
                        if int(rt.get("type_flags", 0)) & IS_TANKER:
                            self._mission_add_event("Worker Entered Oil Patch", unit, inferred=True)
                        else:
                            self._mission_add_event("Worker Entered Mine", unit, inferred=True)
                    else:
                        self._mission_add_event("Worker Exited Resource", unit, inferred=True)

        # --------------------------------------------------- transport cargo
        for key, transport in current.items():
            rt = current_runtime.get(key, {}); old_rt = old_runtime.get(key)
            if not (int(rt.get("type_flags", 0)) & IS_TRANSPORT) or old_rt is None:
                continue
            old_slots = {int(v) for v in old_rt.get("transport_slots", ()) if int(v) != EMPTY_CARGO_SLOT}
            new_slots = {int(v) for v in rt.get("transport_slots", ()) if int(v) != EMPTY_CARGO_SLOT}
            for slot in sorted(new_slots - old_slots):
                passenger = current_by_slot.get(slot) or previous_by_slot.get(slot)
                self._mission_add_event("Passenger Boarded Transport", passenger or transport, transport_address=int(transport.address), transport_unit_type=int(transport.unit_type), passenger_slot=slot)
            for slot in sorted(old_slots - new_slots):
                passenger = current_by_slot.get(slot) or previous_by_slot.get(slot)
                self._mission_add_event("Passenger Unloaded Transport", passenger or transport, transport_address=int(transport.address), transport_unit_type=int(transport.unit_type), passenger_slot=slot)

        # Native-verified rescue edge already maintained by 1.29; publish event too.
        for key in getattr(self, "_source128_rescued_recent", set()):
            unit = current.get(key)
            if unit is not None:
                self._mission_add_event("Unit Rescued", unit)

        # ------------------------------------------- spell / upgrade completion
        spells, tech = self._mission_sample_progression()
        if self._mission_spell_bits:
            for owner, value in spells.items():
                added = int(value) & ~int(self._mission_spell_bits.get(owner, 0))
                if added:
                    for name, bit_index in SPELL_BITS.items():
                        mask = 1 << int(bit_index)
                        if added & mask:
                            self._mission_add_event("Spell Research Completed", None, player=owner, spell=name, spell_bit=int(bit_index))
        if tech is not None and self._mission_tech_levels is not None and len(tech) >= 176 and len(self._mission_tech_levels) >= 176:
            for name, row in UPGRADE_ROWS.items():
                row = int(row)
                for owner in range(8):
                    index = row * 16 + owner
                    if tech[index] > self._mission_tech_levels[index]:
                        self._mission_add_event("Upgrade Completed", None, player=owner, upgrade=name, old_level=int(self._mission_tech_levels[index]), new_level=int(tech[index]), amount=int(tech[index]-self._mission_tech_levels[index]))
        self._mission_spell_bits = spells
        self._mission_tech_levels = tech

        # ----------------------------------------------- projectile end/hit
        missiles = self._mission_sample_missiles()
        for address, old in self._mission_missiles.items():
            if address in missiles:
                continue
            target = self._mission_unit_by_address(current, previous, address=int(old.get("target_unit", 0)))
            extras = {
                "missile_type": int(old.get("missile_type", -1)),
                "projectile_owner_unit": int(old.get("owner_unit", 0)),
                "inferred": True,
                "note": "derived from projectile disappearance at its stored native target; exact impact-vs-expiry hook remains unverified",
            }
            if target is not None:
                self._mission_add_event("Projectile Hit Unit", target, **extras)
            else:
                self._mission_add_event("Projectile Hit Location", None, x=int(old.get("target_x", old.get("x", 0))), y=int(old.get("target_y", old.get("y", 0))), **extras)
        self._mission_missiles = missiles

        # ----------------------------------------------- actor sight/range edges
        current_sight: set[tuple[str, tuple[int, int]]] = set()
        current_attack: set[tuple[str, tuple[int, int]]] = set()
        for actor_name in list(self._campaign_actor_meta):
            actor = self._resolve_unit_reference(actor_name)
            if actor is None:
                continue
            try:
                sight_range = max(1, int(self._source128_rule_value("Sight", int(actor.unit_type))))
                attack_range = max(1, int(self._source128_rule_value("Attack Range", int(actor.unit_type))))
            except Exception:
                sight_range, attack_range = 9, 1
            for key, enemy in current.items():
                if int(enemy.owner) == int(actor.owner) or int(enemy.address) == int(actor.address):
                    continue
                try:
                    if self._players_allied(int(actor.owner), int(enemy.owner)):
                        continue
                except Exception:
                    pass
                distance = max(abs(int(actor.x)-int(enemy.x)), abs(int(actor.y)-int(enemy.y)))
                pair = (actor_name, key)
                if distance <= sight_range:
                    current_sight.add(pair)
                    if pair not in self._mission_actor_sight_pairs:
                        self._mission_add_event("Enemy Entered Actor Sight", enemy, actor=actor_name, distance=distance)
                if distance <= attack_range:
                    current_attack.add(pair)
                    if pair not in self._mission_actor_attack_pairs:
                        self._mission_add_event("Enemy Entered Actor Attack Range", enemy, actor=actor_name, distance=distance)
        for actor_name, key in self._mission_actor_sight_pairs - current_sight:
            enemy = current.get(key) or previous.get(key)
            if enemy is not None:
                self._mission_add_event("Enemy Left Actor Sight", enemy, actor=actor_name)
        for actor_name, key in self._mission_actor_attack_pairs - current_attack:
            enemy = current.get(key) or previous.get(key)
            if enemy is not None:
                self._mission_add_event("Enemy Left Actor Attack Range", enemy, actor=actor_name)
        self._mission_actor_sight_pairs = current_sight
        self._mission_actor_attack_pairs = current_attack

        self._mission_runtime_by_key = current_runtime

    # ---------------------------------------------------------------- conditions
    def massive_value(self, kind: str, args: dict[str, Any], player: int) -> Any:
        if kind in EVENT_CONDITION_ALIASES:
            return self._mission_event_count(EVENT_CONDITION_ALIASES[kind], args, player)
        if kind == "Mission Event Count":
            return self._mission_event_count(str(args.get("event_type", "Unit Created")), args, player)
        if kind == "Transmission History Count":
            return len(self._mission_transmissions)
        if kind == "Campaign Checkpoint Exists":
            return int(self._mission_checkpoint_path(args.get("name", "checkpoint")).exists())
        if kind == "Campaign UI Capability":
            return str(self._mission_probe_campaign_ui().get("status", "Unavailable"))
        if kind == "Cutscene Input Lock State":
            if self._mission_soft_input_lock and self._campaign_cutscene_active:
                return "Soft Locked"
            if self._mission_input_lock_mode.startswith("Experimental"):
                return "Experimental / Fail Closed"
            return "Unlocked"
        return super().massive_value(kind, args, player)

    # ------------------------------------------------------------------ actions
    def massive_action(self, kind: str, args: dict[str, Any], player: int) -> bool:
        # Upgrade 1.29 Begin Cutscene so existing authored scenes automatically gain
        # the stronger 1.30 soft input lock without changing their JSON.
        if kind == "Begin Cutscene":
            result = super().massive_action(kind, args, player)
            mode = str(args.get("input_mode", "Soft Lock" if bool(args.get("mark_input_locked", True)) else "Off"))
            if mode == "Experimental Native (Fail Closed)":
                if not bool(args.get("fallback_to_soft_lock", True)):
                    raise RuntimeError("Native cutscene input gate is not ABI-verified for the current Remastered front end; action failed closed")
                self.log("CUTSCENE INPUT: experimental native gate unverified; falling back to continuous soft lock")
                mode = "Soft Lock"
            self._mission_input_lock_mode = mode
            self._mission_soft_input_lock = mode == "Soft Lock"
            self._mission_soft_lock_logged = False
            return result
        if kind == "End Cutscene":
            result = super().massive_action(kind, args, player)
            self._mission_soft_input_lock = False; self._mission_input_lock_mode = "Off"; self._mission_soft_lock_logged = False
            return result
        if kind == "Lock Cutscene Input":
            mode = str(args.get("mode", "Soft Lock"))
            if mode == "Experimental Native (Fail Closed)":
                if not bool(args.get("fallback_to_soft_lock", True)):
                    raise RuntimeError("Hard Remastered input callback is not ABI-verified; Lock Cutscene Input failed closed")
                self.log("CUTSCENE INPUT: hard-native mode unverified; using soft lock")
                mode = "Soft Lock"
            self._mission_input_lock_mode = mode; self._mission_soft_input_lock = mode == "Soft Lock"; self._mission_soft_lock_logged = False
            return True
        if kind == "Unlock Cutscene Input":
            self._mission_input_lock_mode = "Off"; self._mission_soft_input_lock = False; self._mission_soft_lock_logged = False
            return True

        # ------------------------------------------------ transmissions/history
        if kind in {"Scene Transmission", "Scene Narration"}:
            actor_name = str(args.get("actor", "")).strip() if kind == "Scene Transmission" else ""
            actor = self._campaign_actor(actor_name, required=False) if actor_name else None
            speaker = str(args.get("speaker", actor_name or "Narrator")).strip()
            text = str(args.get("text", "")).strip()
            seconds = max(0.1, float(args.get("seconds", 4.0)))
            state = self._cached_action_value("mission_transmission", lambda: {"started": time.monotonic(), "published": False})
            if not state["published"]:
                if actor is not None and bool(args.get("center_camera", False)):
                    self._campaign_camera_call(int(actor.x), int(actor.y))
                if actor is not None and bool(args.get("voice_bark", True)):
                    try: self._call_cdecl(self.source_native_paths["gamesnd_select"], [actor.address])
                    except Exception: pass
                message = f"{speaker}: {text}" if speaker else text
                self._game_message({"text": message, "color": args.get("color", "White — native highlight"), "recipients": args.get("recipients", "All active players"), "seconds": max(1, int(math.ceil(seconds))), "also_log": True}, player)
                entry = {"time": time.time(), "actor": actor_name, "speaker": speaker, "text": text}
                self._mission_transmissions.append(entry); self._mission_transmissions = self._mission_transmissions[-8:]
                state["published"] = True
            if bool(args.get("wait", True)) and time.monotonic() - float(state["started"]) < seconds:
                raise ActionDeferred("Transmission still playing", retry_after=0.10)
            return True
        if kind == "Show Transmission History":
            if not self._mission_transmissions:
                text = "TRANSMISSIONS: none"
            else:
                lines = ["LAST TRANSMISSIONS"]
                lines.extend(f"{entry.get('speaker','')}: {entry.get('text','')}" for entry in self._mission_transmissions[-8:])
                text = "\n".join(lines)
            self._game_message({"text": text, "color": args.get("color", "White — native highlight"), "recipients": args.get("recipients", "All active players"), "seconds": int(args.get("seconds", 8)), "also_log": True}, player)
            return True
        if kind == "Clear Transmission History":
            self._mission_transmissions.clear(); return True

        # ------------------------------------------------ checkpoint/save state
        if kind == "Save Campaign Checkpoint":
            self._mission_write_checkpoint(str(args.get("name", "checkpoint"))); return True
        if kind == "Load Campaign Checkpoint":
            self._mission_load_checkpoint(str(args.get("name", "checkpoint")), restore_resources=bool(args.get("restore_resources", True)), restore_camera=bool(args.get("restore_camera", True)), recreate_missing=bool(args.get("recreate_missing_actors", False)), player=player); return True
        if kind == "Delete Campaign Checkpoint":
            path = self._mission_checkpoint_path(args.get("name", "checkpoint"))
            if path.exists(): path.unlink(); self.log(f"CAMPAIGN CHECKPOINT DELETED: {path.name}")
            return True

        # -------------------------------------------------- actor choreography
        if kind == "Scene Actor Follow Actor":
            actor = self._campaign_actor(args.get("actor", "Actor")); target = self._campaign_actor(args.get("target_actor", "Target"))
            self._call_cdecl(self.order_callees["set_target"], [actor.address, int(target.x), int(target.y), target.address, self.source_native_paths["do_follow"]]); return True
        if kind == "Scene Actor Flee From Actor":
            actor = self._campaign_actor(args.get("actor", "Actor")); target = self._campaign_actor(args.get("target_actor", "Target"))
            distance = max(1, int(args.get("distance", 6))); dx = int(actor.x)-int(target.x); dy = int(actor.y)-int(target.y)
            if dx == 0 and dy == 0: dx = 1
            scale = max(abs(dx), abs(dy), 1); x = int(actor.x) + round(dx * distance / scale); y = int(actor.y) + round(dy * distance / scale)
            x=max(0,min(self.map_width-1,x)); y=max(0,min(self.map_height-1,y))
            self._call_cdecl(self.order_callees["set_target"], [actor.address, x, y, 0, self.order_callees["do_move"]]); return True
        if kind in {"Scene Actor Repair Actor", "Scene Actor Demolish Actor", "Scene Actor Harvest Actor"}:
            actor = self._campaign_actor(args.get("actor", "Actor")); target = self._campaign_actor(args.get("target_actor", "Target"))
            callback = {"Scene Actor Repair Actor":"do_repair", "Scene Actor Demolish Actor":"do_demolish", "Scene Actor Harvest Actor":"do_harvest"}[kind]
            self._call_cdecl(self.order_callees["set_target"], [actor.address, int(target.x), int(target.y), target.address, self.source_native_paths[callback]]); return True
        if kind == "Scene Actor Return Resources":
            actor = self._campaign_actor(args.get("actor", "Actor")); self._call_cdecl(self.order_callees["set_target"], [actor.address, int(actor.x), int(actor.y), 0, self.source_native_paths["do_return"]]); return True
        if kind == "Scene Actor Board Transport":
            actor = self._campaign_actor(args.get("actor", "Actor")); transport = self._campaign_actor(args.get("transport_actor", "Transport"))
            self._call_cdecl(self.order_callees["set_target"], [actor.address, int(transport.x), int(transport.y), transport.address, self.order_callees["do_move"]]); return True
        if kind == "Scene Actor Unload From Transport":
            actor = self._campaign_actor(args.get("actor", "Actor")); transport = self._source_find_transport_for(actor)
            if transport is None:
                raise RuntimeError(f"Scene actor {args.get('actor','Actor')} is not loaded in a native-verified transport")
            self._call_cdecl(self.source_native_paths["unit_unload_transport"], [transport.address, actor.address]); return True
        if kind in {"Scene Actor Rescue To Player", "Scene Actor Capture By Player"}:
            name = str(args.get("actor", "Actor")); actor = self._campaign_actor(name); new_owner = int(args.get("new_owner", player))
            self._call_cdecl(self.capture_unit_address, [actor.address, new_owner, 0])
            refreshed = next((u for u in self.units() if int(u.address)==int(actor.address)), None)
            self._campaign_register_actor(name, refreshed, created=bool(self._campaign_actor_meta.get(name,{}).get("created",False)))
            sound_key = "gamesnd_select" if kind.endswith("Capture By Player") else "gamesnd_select"
            if refreshed is not None:
                try: self._call_cdecl(self.source_native_paths[sound_key],[refreshed.address])
                except Exception: pass
            return True
        if kind in {"Scene Actor Cast Spell On Actor", "Scene Actor Cast Spell At Point"}:
            caster = self._campaign_actor(args.get("actor", "Caster"))
            spell = str(args.get("spell", "Fireball"))
            if spell not in SOURCE128_SPELL_ACTIONS:
                raise ValueError(f"{spell} is not one of the native-verified native spell actions")
            allowed = {
                "Holy Vision": {12,44,52}, "Healing": {12,44,52}, "Area Heal": {12,44,52}, "Exorcism": {12,44,52},
                "Flame Shield": {10,24}, "Fireball": {10,24}, "Slow": {10,24}, "Invisibility": {10,24}, "Polymorph": {10,24}, "Blizzard": {10,24},
                "Eye of Kilrogg": {13,23,49}, "Bloodlust": {13,23,49}, "Runes": {13,23,49},
                "Raise Dead": {11,21,51}, "Death Coil": {11,21,51}, "Whirlwind": {11,21,51}, "Haste": {11,21,51}, "Unholy Armor": {11,21,51}, "Death and Decay": {11,21,51},
            }.get(spell, set())
            if allowed and int(caster.unit_type) not in allowed and not bool(args.get("allow_wrong_caster", False)):
                raise RuntimeError(f"{spell} is not valid for scene actor unit type {caster.unit_type}; enable Allow wrong caster only for deliberate engine research")
            action_global = int(self.spell_path["action_type_global"]); spell_id = int(SOURCE128_SPELL_ACTIONS[spell])
            if int(self.pm.read_ushort(action_global)) != 0:
                raise ActionDeferred(f"gwActionType busy while queueing {spell}", retry_after=0.05)
            if kind == "Scene Actor Cast Spell On Actor":
                target = self._campaign_actor(args.get("target_actor", "Target"))
                target_x, target_y, target_ptr = 0, 0, int(target.address)
            else:
                target_x, target_y = self._campaign_point(args); target_ptr = 0
            self._dispatch_ops([
                ("write_word", action_global, spell_id),
                ("call", self.order_callees["set_target"], [caster.address, int(target_x), int(target_y), int(target_ptr), self.spell_path["do_unit_spell"]]),
                ("write_word", action_global, 0),
            ])
            if int(self.pm.read_ushort(action_global)) != 0:
                raise RuntimeError(f"Scene {spell} cast failed to restore gwActionType")
            self.log(f"SCENE SPELL: {args.get('actor','Caster')} queued native {spell} action {spell_id}")
            return True
        if kind in {"Scene Actor Train Unit", "Scene Actor Research Technology", "Scene Actor Research Spell", "Scene Actor Upgrade Building"}:
            actor = self._campaign_actor(args.get("actor", "Building"))
            if int(actor.unit_type) < 58:
                raise RuntimeError(f"{kind} requires a named building actor")
            if kind == "Scene Actor Train Unit":
                order, parm = BUILD_UNIT, int(args.get("new_unit", 0))
            elif kind == "Scene Actor Research Technology":
                upgrade = str(args.get("upgrade", "Melee Attack"))
                if upgrade not in UPGRADE_ROWS: raise ValueError(f"Unknown source technology: {upgrade}")
                order, parm = BUILD_TECH, int(UPGRADE_ROWS[upgrade])
            elif kind == "Scene Actor Research Spell":
                spell = str(args.get("spell", "Holy Vision"))
                if spell not in SPELL_BITS: raise ValueError(f"Unknown source spell: {spell}")
                order, parm = BUILD_SPELL, int(SPELL_BITS[spell])
            else:
                order, parm = BUILD_UPGRADE, int(args.get("new_building", 58))
            result = self._call_cdecl(self.source_native_paths["bldg_build_start"], [actor.address, parm & 0xFF, order & 0xFF])
            if not result:
                self.log(f"SCENE PRODUCTION: {kind} was rejected by Warcraft prerequisites/cost/busy checks")
            return True
        if kind in {"Scene Actor Cancel Production", "Scene Actor Complete Production"}:
            actor = self._campaign_actor(args.get("actor", "Building"))
            if int(actor.unit_type) < 58: raise RuntimeError(f"{kind} requires a named building actor")
            flags = int(self.pm.read_ushort(actor.address + 0x1C))
            if not flags & UF_BUILD_ON: return True
            if kind == "Scene Actor Cancel Production":
                self._dispatch_ops([("or_word", actor.address + 0x1C, 0x0020), ("call", self.source_native_paths["bldg_dispatch_build"], [actor.address])])
            else:
                total = int(self.pm.read_ushort(actor.address + 0x70))
                self._dispatch_ops([("write_word", actor.address + 0x6E, total), ("call", self.source_native_paths["bldg_dispatch_build"], [actor.address])])
            return True
        if kind in {"Scene Group Move", "Scene Group Attack", "Scene Group Patrol", "Scene Group Die", "Scene Group Face"}:
            names = self._mission_actor_names(args.get("actors", "")); actors = [self._campaign_actor(name) for name in names]
            if kind == "Scene Group Die":
                for actor in actors: self._call_cdecl(self.damage_callees["unit_kill"], [actor.address])
                for name in names: self._campaign_actor_status[name] = "Dead"
                return True
            if kind == "Scene Group Face":
                facing = int(args.get("facing",0)) & 7
                self._dispatch_ops([op for actor in actors for op in (("write_byte", actor.address+0x0A, facing), ("or_byte", actor.address+0x06, 0x20))])
                return True
            x,y = self._campaign_point(args)
            callback = self.order_callees["do_move"] if kind=="Scene Group Move" else self.order_callees["do_attack"] if kind=="Scene Group Attack" else self.order_callees["do_patrol"]
            self._call_cdecl_batched([(self.order_callees["set_target"], [actor.address,x,y,0,callback]) for actor in actors]); return True

        # -------------------------------------------------- scene selection/build
        if kind in {"Scene Actor Select", "Scene Actor Deselect"}:
            actor = self._campaign_actor(args.get("actor", "Actor"))
            flags = int(self.pm.read_ushort(actor.address + 0x1E))
            if kind == "Scene Actor Select":
                self.pm.write_ushort(actor.address + 0x1E, flags | SF_SELECTED)
            else:
                try:
                    if "deselect_unit" in getattr(self, "remove_callees", {}):
                        self._call_cdecl(self.remove_callees["deselect_unit"], [actor.address])
                    else:
                        self.pm.write_ushort(actor.address + 0x1E, flags & ~SF_SELECTED)
                except Exception:
                    self.pm.write_ushort(actor.address + 0x1E, flags & ~SF_SELECTED)
            return True
        if kind == "Scene Actor Voice":
            actor = self._campaign_actor(args.get("actor", "Actor"))
            event = str(args.get("event", "Selection"))
            exact_callback = {
                "Selection": "gamesnd_select", "Under Attack": "gamesnd_under_attack", "Harvest": "gamesnd_harvest",
                "Unit Death": "gamesnd_kill_man", "Building Destruction": "gamesnd_kill_bldg",
            }.get(event)
            if exact_callback:
                self._call_cdecl(self.source_native_paths[exact_callback], [actor.address])
            elif event == "Spell Sound":
                sound_id = self._spell_sound_id(args.get("sound", "Thunder"))
                self._call_cdecl(self.source_native_paths["gamesnd_spell"], [actor.address, sound_id])
            else:
                # The legacy tree names additional contextual entry points (ack,
                # attack, build, rescue, capture, dock), but their individual
                # 2818 Remastered starts are not all independently validated yet.
                # Use the already-verified selection callback rather than guessing.
                self._call_cdecl(self.source_native_paths["gamesnd_select"], [actor.address])
                self.log(f"SCENE VOICE: {event} used verified Selection fallback; exact 2818 GAMESND callback not independently validated")
            self._mission_audio_until = max(self._mission_audio_until, time.monotonic() + max(0.0, float(args.get("estimated_seconds", 1.5))))
            return True
        if kind == "Scene Actor Build Building":
            actor_name = str(args.get("actor", "Worker")); worker = self._campaign_actor(actor_name)
            x, y = self._campaign_point(args)
            forwarded = {
                "player": int(worker.owner), "new_building": int(args.get("new_building", 58)),
                "count": 1, "location": "Anywhere", "x": x, "y": y,
            }
            foundations = self._source128_create_foundation(forwarded, int(worker.owner))
            if not foundations:
                raise RuntimeError(f"Scene Actor Build Building: no legal native foundation at ({x},{y})")
            foundation = foundations[0]
            building_actor = str(args.get("building_actor", "")).strip()
            if building_actor:
                self._campaign_register_actor(building_actor, foundation, created=True)
                self._save_reference(building_actor, foundation)
            self._call_cdecl(self.order_callees["set_target"], [worker.address, int(foundation.x), int(foundation.y), foundation.address, self.source_native_paths["do_repair"]])
            return True

        # ------------------------------------------------ presentation timing / legacy-shaped API
        if kind == "Scene Wait For Audio":
            seconds = max(0.0, float(args.get("seconds", 0.0)))
            state = self._cached_action_value("mission_wait_audio", lambda: {"until": max(self._mission_audio_until, time.monotonic() + seconds)})
            remaining = float(state["until"]) - time.monotonic()
            if remaining > 0:
                raise ActionDeferred("Waiting for scene audio", retry_after=min(0.10, remaining))
            return True
        if kind in {"Scene Fade In (Experimental)", "Scene Fade Out (Experimental)"}:
            direction = "Visible" if "Fade In" in kind else "Black"
            seconds = max(0.0, float(args.get("seconds", 0.75)))
            if not bool(args.get("fallback_to_timing_only", True)):
                raise RuntimeError(f"{kind}: Remastered fade renderer ABI is not verified; failed closed")
            state = self._cached_action_value("mission_screen_fade", lambda: {"started": time.monotonic(), "logged": False})
            if not state["logged"]:
                self.log(f"EXPERIMENTAL {kind}: the source fade path exists, but the Remastered renderer ABI is unverified; timing-only fallback used")
                state["logged"] = True
            if time.monotonic() - float(state["started"]) < seconds:
                raise ActionDeferred("Authored screen fade timing", retry_after=0.05)
            self._mission_screen_fade_state = direction
            return True
        if kind in {"Scene Set Music (Experimental)", "Scene Fade Music (Experimental)", "Scene Stop Music (Experimental)"}:
            if not bool(args.get("fallback_to_state_only", True)):
                raise RuntimeError(f"{kind}: Remastered music-stream ABI is not verified; failed closed")
            if kind == "Scene Set Music (Experimental)":
                self._mission_music_state = {"track": str(args.get("track", "")), "state": "Playing", "volume": max(0, min(100, int(args.get("volume", 100))))}
            elif kind == "Scene Stop Music (Experimental)":
                self._mission_music_state["state"] = "Stopped"
            else:
                seconds = max(0.0, float(args.get("seconds", 1.0)))
                state = self._cached_action_value("mission_music_fade", lambda: {"started": time.monotonic()})
                if time.monotonic() - float(state["started"]) < seconds:
                    raise ActionDeferred("Authored music fade timing", retry_after=0.05)
                self._mission_music_state["volume"] = max(0, min(100, int(args.get("to_volume", 0))))
                if self._mission_music_state["volume"] == 0:
                    self._mission_music_state["state"] = "Stopped"
            self.log(f"EXPERIMENTAL {kind}: state authored; native Remastered music stream call remains fail-closed")
            return True

        # ------------------------------------------ campaign UI/source probes
        if kind == "Probe Campaign UI":
            probe = self._mission_probe_campaign_ui(force=True)
            self.log("CAMPAIGN UI PROBE: " + json.dumps(probe, sort_keys=True))
            if bool(args.get("show_message", True)):
                self._game_message({"text": f"Campaign UI: {probe.get('status')} ({len(probe.get('found',[]))}/{len(self.UI_PROBE_STRINGS)} markers)", "color":"White — native highlight", "recipients":"All active players", "seconds":5, "also_log":False}, player)
            return True
        if kind == "Show Native Objectives HUD (Experimental)":
            return super(MissionFeature130Mixin,self).massive_action(kind, args, player)
        if kind == "Open Native Scenario Objectives (Experimental)":
            return super(MissionFeature130Mixin,self).massive_action(kind, args, player)
        if kind == "Show Native Mission Briefing (Experimental)":
            return self._mission_experimental_fallback(kind,args,player,lambda: super(MissionFeature130Mixin,self).massive_action("Show Mission Briefing",args,player))
        if kind == "Native Portrait Transmission (Experimental)":
            return self._mission_experimental_fallback(kind,args,player,lambda: self.massive_action("Scene Transmission",args,player))
        if kind == "Native Campaign Interlude (Experimental)":
            safe={"title":args.get("title","INTERLUDE"),"subtitle":args.get("subtitle",args.get("text","")),"seconds":args.get("seconds",5),"recipients":args.get("recipients","All active players"),"color":args.get("color","White — native highlight")}
            return self._mission_experimental_fallback(kind,args,player,lambda: super(MissionFeature130Mixin,self).massive_action("Show Act Card",safe,player))
        if kind == "Play Cinematic Movie (Experimental)":
            def fallback_movie():
                title=str(args.get("title","CINEMATIC")); movie=str(args.get("movie","")); text=str(args.get("fallback_text", "")) or f"{title}\n{movie or 'Movie playback requested'}"
                return self._campaign_timed_message("experimental_movie",text,float(args.get("seconds",5)),player,color=str(args.get("color","White — native highlight")),recipients=str(args.get("recipients","All active players")))
            return self._mission_experimental_fallback(kind,args,player,fallback_movie)
        if kind == "Native Save Extension (Experimental)":
            return self._mission_experimental_fallback(kind,args,player,lambda: bool(self._mission_write_checkpoint(str(args.get("name","checkpoint")))))

        return super().massive_action(kind, args, player)
