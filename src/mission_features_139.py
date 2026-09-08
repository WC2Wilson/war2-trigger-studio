from __future__ import annotations

import time
from typing import Any

from mission_features_132 import MissionFeature132Mixin
from source_features import BUILD_UNIT, BUILD_TECH, BUILD_SPELL, BUILD_UPGRADE
from source_features_128 import (
    IS_PEON, IS_TANKER, IS_GOLDMINE, IS_OILPATCH,
    PEON_LOADED, SOURCE128_SPELL_ACTIONS,
)


class MissionFeature139Mixin(MissionFeature132Mixin):
    """1.39 legacy completion surface.

    This layer promotes the remaining mission-author-facing legacy source ideas to
    explicit Trigger Studio conditions/actions.  It deliberately does *not* turn
    an unverified legacy symbol into a guessed Remastered call.  Where the exact
    modern callback/object ABI is still unknown, the feature is state-backed,
    best-evidence/inferred, or fail-closed and says so in the editor help.
    """

    _SPELL_ACTION_TO_NAME = {int(v): str(k) for k, v in SOURCE128_SPELL_ACTIONS.items()}

    def _init_massive_features(self) -> None:
        super()._init_massive_features()
        self._mission139_pending_events: list[tuple[str, Any | None, dict[str, Any]]] = []
        self._mission139_paused_prev: set[tuple[int, int]] = set()
        self._mission139_resource_prev: dict[tuple[int, int], int] = {}
        self._mission139_game_mode_prev: int | None = None
        self._mission139_relations_prev: bytes | None = None
        self._mission139_vision_prev: bytes | None = None
        self._mission139_ai_goal_met: set[int] = set()
        self._mission139_ui: dict[str, dict[str, Any]] = {
            "briefing": {"active": False, "scrolling": False, "finished": False, "rect": (0, 0, 0, 0), "image": "", "text": "", "until": 0.0},
            "objectives": {"open": False},
            "transmission": {"active": False, "portrait": "", "until": 0.0},
            "slideshow": {"active": False, "finished": False, "index": 0, "until": 0.0},
            "fmv": {"active": False, "finished": False, "until": 0.0, "movie": ""},
            "finale": {"active": False, "finished": False, "until": 0.0, "text": ""},
            "fade": {"active": False, "finished": True, "percent": 0, "until": 0.0, "target": 0},
            "results": {"open": False},
        }
        self._mission139_music_until = 0.0
        self._mission132_campaign_map.setdefault("scale", 1.0)
        self._mission132_campaign_map.setdefault("screen_x", 0)
        self._mission132_campaign_map.setdefault("screen_y", 0)

    def _massive_begin_run(self) -> None:
        super()._massive_begin_run()
        self._mission139_pending_events.clear()
        self._mission139_paused_prev.clear()
        self._mission139_resource_prev.clear()
        self._mission139_game_mode_prev = None
        self._mission139_relations_prev = None
        self._mission139_vision_prev = None
        self._mission139_ai_goal_met.clear()
        for name, state in self._mission139_ui.items():
            if name == "fade":
                state.update({"active": False, "finished": True, "percent": 0, "until": 0.0, "target": 0})
            elif name == "objectives" or name == "results":
                state["open"] = False
            else:
                state.update({"active": False, "finished": False, "until": 0.0})
        self._mission139_music_until = 0.0
        self._mission132_campaign_map.setdefault("scale", 1.0)
        self._mission132_campaign_map.setdefault("screen_x", 0)
        self._mission132_campaign_map.setdefault("screen_y", 0)

    # ------------------------------------------------------------ event helpers
    def _mission139_queue_event(self, event_type: str, unit: Any | None = None, **extra: Any) -> None:
        self._mission139_pending_events.append((str(event_type), unit, dict(extra)))

    def _mission139_copy_events(self, source: str, target: str, **fixed: Any) -> None:
        for record in list(self._mission_events.get(source, ())):
            unit = record.get("unit")
            extra = {k: v for k, v in record.items() if k not in {"event_type", "unit", "key", "address", "player", "unit_type", "x", "y", "health", "mana", "amount"}}
            extra.update(fixed)
            self._mission_add_event(target, unit, **extra)

    def _mission_event_matches(self, record: dict[str, Any], args: dict[str, Any], player: int) -> bool:
        if not super()._mission_event_matches(record, args, player):
            return False
        # 1.39 event-specific optional filters. Empty / -1 means any.
        for field in ("source_player", "target_player", "production_order", "production_parm", "trained_unit", "missile_type", "old_relation", "new_relation"):
            if field not in args or args.get(field) in {None, "", -1, "-1", "Any"}:
                continue
            try:
                if int(record.get(field, -999999)) != int(args.get(field)):
                    return False
            except Exception:
                return False
        for field in ("impact_kind", "evidence"):
            wanted = str(args.get(field, "")).strip()
            if wanted and wanted.casefold() not in {"any", "-1"} and str(record.get(field, "")).strip().casefold() != wanted.casefold():
                return False
        return True

    def _mission139_read_game_mode(self) -> int | None:
        try:
            if hasattr(self, "_get_game_mode"):
                return int(self._get_game_mode())
            return int(self.pm.read_ushort(self.base + 0x51C184))
        except Exception:
            return None

    def _mission139_tick_ui(self) -> None:
        now = time.monotonic()
        timed = {
            "briefing": "Briefing Finished",
            "transmission": "Transmission Finished",
            "slideshow": "Slideshow Finished",
            "fmv": "FMV Finished",
            "finale": "Finale Finished",
            "fade": "Fade Finished",
        }
        for key, event_name in timed.items():
            state = self._mission139_ui[key]
            until = float(state.get("until", 0.0) or 0.0)
            if bool(state.get("active")) and until > 0.0 and now >= until:
                state["active"] = False
                state["finished"] = True
                if key == "briefing":
                    state["scrolling"] = False
                if key == "fade":
                    state["percent"] = int(state.get("target", state.get("percent", 0)))
                self._mission139_queue_event(event_name)
        if self._mission_music_state.get("state") == "Playing" and self._mission139_music_until > 0 and now >= self._mission139_music_until:
            self._mission_music_state["state"] = "Stopped"
            self._mission139_music_until = 0.0
            self._mission139_queue_event("Music Finished")

    # ------------------------------------------------------------ event sampling
    def _massive_prepare_events(self, current: dict[tuple[int, int], Any], previous: dict[tuple[int, int], Any]) -> None:
        old_runtime = dict(getattr(self, "_mission_runtime_by_key", {}))
        old_paused = set(self._mission139_paused_prev)
        old_resource = dict(self._mission139_resource_prev)
        super()._massive_prepare_events(current, previous)

        # Flush action/timer events only after 1.30 resets _mission_events.
        self._mission139_tick_ui()
        pending, self._mission139_pending_events = self._mission139_pending_events, []
        for event_type, unit, extra in pending:
            self._mission_add_event(event_type, unit, **extra)

        # Promote existing best-evidence events to the cleaner 1.39 names.
        self._mission139_copy_events("Player Issued Order (Inferred)", "Player Issued Native Order", evidence="best-evidence")
        self._mission139_copy_events("Player Command Button Used (Inferred)", "Native Command Button Clicked", evidence="best-evidence")
        self._mission139_copy_events("Attack Connected", "Attack Hit", evidence="best-evidence")
        self._mission139_copy_events("Projectile Impacted Unit", "Projectile Impact", impact_kind="Unit", evidence="best-evidence")
        self._mission139_copy_events("Projectile Impacted Terrain", "Projectile Impact", impact_kind="Terrain", evidence="best-evidence")
        self._mission139_copy_events("Enemy Entered Actor Sight", "Unit Entered Player Vision", evidence="actor-sight")
        self._mission139_copy_events("Enemy Left Actor Sight", "Unit Left Player Vision", evidence="actor-sight")
        self._mission139_copy_events("Enemy Entered Actor Attack Range", "Unit Entered Attack Range", evidence="actor-range")
        self._mission139_copy_events("Enemy Left Actor Attack Range", "Unit Left Attack Range", evidence="actor-range")

        # A projectile classified as a miss is also our best available attack-miss edge.
        for record in list(self._mission_events.get("Projectile Missed", ())):
            owner_addr = int(record.get("projectile_owner_unit", 0) or 0)
            attacker = next((u for u in current.values() if int(u.address) == owner_addr), None)
            self._mission_add_event("Attack Missed", attacker, inferred=True, missile_type=int(record.get("missile_type", -1)))

        # Production cancellation/hold/resume. Completion generally reaches the native
        # total before UF_BUILD_ON clears; a pre-total disappearance is best evidence
        # of cancel/interruption and is explicitly labeled as such in help.
        current_runtime = dict(getattr(self, "_mission_runtime_by_key", {}))
        for key, old_rt in old_runtime.items():
            new_rt = current_runtime.get(key)
            if not old_rt.get("production_active"):
                continue
            if new_rt is not None and new_rt.get("production_active"):
                continue
            old_cur = int(old_rt.get("production_current", 0) or 0)
            old_total = int(old_rt.get("production_total", 0) or 0)
            if old_total > 0 and old_cur >= old_total:
                continue
            unit = current.get(key) or previous.get(key)
            order = int(old_rt.get("production_order", -1))
            parm = int(old_rt.get("production_parm", -1))
            self._mission_add_event("Production Cancelled", unit, inferred=True, production_order=order, production_parm=parm)
            if order == BUILD_UNIT:
                self._mission_add_event("Training Cancelled", unit, inferred=True, trained_unit=parm)
            elif order in {BUILD_TECH, BUILD_SPELL}:
                self._mission_add_event("Research Cancelled", unit, inferred=True, production_order=order, production_parm=parm)
            elif order == BUILD_UPGRADE:
                self._mission_add_event("Upgrade Cancelled", unit, inferred=True, production_parm=parm)

        for record in list(self._mission_events.get("Technology Research Started", ())):
            # 1.30 used this label for both tech and BUILD_UPGRADE. Publish the exact
            # authored distinction when the order is available.
            if int(record.get("production_order", -1)) == BUILD_UPGRADE:
                self._mission_add_event("Upgrade Started", record.get("unit"), production_parm=int(record.get("production_parm", -1)))

        paused_now = set(getattr(self, "_source128_paused_production", {}).keys())
        for key in paused_now - old_paused:
            self._mission_add_event("Production Paused Event", current.get(key) or previous.get(key))
        for key in old_paused - paused_now:
            self._mission_add_event("Production Resumed", current.get(key) or previous.get(key))
        self._mission139_paused_prev = paused_now

        # Worker resource lifecycle aliases and harvested-cargo edge.
        for key, rt in current_runtime.items():
            old_rt = old_runtime.get(key)
            unit = current.get(key)
            if old_rt is None or unit is None:
                continue
            flags = int(rt.get("type_flags", 0))
            if not flags & (IS_PEON | IS_TANKER):
                continue
            old_hidden, hidden = bool(old_rt.get("hidden")), bool(rt.get("hidden"))
            if hidden and not old_hidden:
                self._mission_add_event("Tanker Entered Oil Patch" if flags & IS_TANKER else "Worker Entered Gold Mine", unit, inferred=True)
            elif old_hidden and not hidden:
                self._mission_add_event("Tanker Exited Oil Patch" if flags & IS_TANKER else "Worker Exited Gold Mine", unit, inferred=True)
            old_cargo, cargo = int(old_rt.get("cargo_flags", 0)), int(rt.get("cargo_flags", 0))
            old_amt, amt = int(old_rt.get("cargo_amount", 0)), int(rt.get("cargo_amount", 0))
            if not (old_cargo & PEON_LOADED) and (cargo & PEON_LOADED) and amt > 0:
                resource = self._mission_resource_from_cargo(cargo)
                self._mission_add_event("Resource Harvested", unit, resource=resource, amount=max(1, amt - old_amt), inferred=True)

        # Resource node depletion from the native +0x8A remaining counter.
        resources_now: dict[tuple[int, int], int] = {}
        for key, unit in current.items():
            try:
                flags = int(self._source128_flags(int(unit.unit_type)))
            except Exception:
                flags = 0
            if not flags & (IS_GOLDMINE | IS_OILPATCH):
                continue
            try:
                remain = int(self.pm.read_ushort(int(unit.address) + 0x8A))
            except Exception:
                continue
            resources_now[key] = remain
            if key in old_resource and int(old_resource[key]) > 0 and remain <= 0:
                self._mission_add_event("Resource Node Depleted", unit, resource="Oil" if flags & IS_OILPATCH else "Gold", old_remaining=int(old_resource[key]))
        self._mission139_resource_prev = resources_now

        # Spell cast lifecycle from source-validated native action IDs.
        spell_actions = self._SPELL_ACTION_TO_NAME
        for key, unit in current.items():
            rt = current_runtime.get(key, {})
            old_rt = old_runtime.get(key, {})
            cur = int(rt.get("action", -1)); old = int(old_rt.get("action", -1))
            if cur in spell_actions and old not in spell_actions:
                self._mission_add_event("Spell Cast Started", unit, spell=spell_actions[cur], inferred=True)
            if old in spell_actions and cur not in spell_actions:
                self._mission_add_event("Spell Cast Finished", unit, spell=spell_actions[old], inferred=True)
        for key, old_unit in previous.items():
            if key in current:
                continue
            old = int(old_runtime.get(key, {}).get("action", -1))
            if old in spell_actions:
                self._mission_add_event("Spell Cast Interrupted", old_unit, spell=spell_actions[old], inferred=True)

        # Game mode edges.
        mode = self._mission139_read_game_mode()
        if mode is not None and self._mission139_game_mode_prev is not None and mode != self._mission139_game_mode_prev:
            if mode != 3:
                self._mission_add_event("Game Paused Event", None, old_mode=self._mission139_game_mode_prev, new_mode=mode)
            elif self._mission139_game_mode_prev != 3:
                self._mission_add_event("Game Resumed Event", None, old_mode=self._mission139_game_mode_prev, new_mode=mode)
        self._mission139_game_mode_prev = mode

        # Track the actual native Objectives submenu state when the 1.38 bridge is
        # available. This turns manual Escape/Menu closes into real lifecycle edges
        # instead of requiring the authored Close Objectives Screen action.
        try:
            addresses = self._native_objectives_addresses()
            native_obj_open = int(self.pm.read_uint(addresses["pause_mode"])) == 2
            authored_open = bool(self._mission139_ui["objectives"].get("open"))
            if native_obj_open != authored_open:
                self._mission139_ui["objectives"]["open"] = native_obj_open
                self._mission_add_event("Objectives Screen Opened" if native_obj_open else "Objectives Screen Closed", None, evidence="native-pause-state")
        except Exception:
            pass

        # Diplomacy/shared-vision matrix changes use already resolved 1.0.2.2818 data.
        try:
            rel_addr = int(self.diplomacy_path["relations"])
            # Warcraft stores each relation row at a 16-byte stride even though
            # only the P1-P8 cells are mission-facing. Compact those 8x8 cells
            # before edge comparison so padding/extra slots cannot be misattributed.
            relations = bytes(
                self.pm.read_uchar(rel_addr + source * 16 + target)
                for source in range(8) for target in range(8)
            )
            if self._mission139_relations_prev is not None:
                for idx, (before, after) in enumerate(zip(self._mission139_relations_prev, relations)):
                    if before != after:
                        self._mission_add_event("Diplomacy Changed", None, source_player=idx // 8, target_player=idx % 8, old_relation=int(before), new_relation=int(after))
            self._mission139_relations_prev = relations
            vis_addr = int(self.diplomacy_path["shared_vision"])
            vision = bytes(self.pm.read_bytes(vis_addr, 8))
            if self._mission139_vision_prev is not None:
                for source, (before, after) in enumerate(zip(self._mission139_vision_prev, vision)):
                    if before != after:
                        self._mission_add_event("Shared Vision Changed", None, source_player=source, old_mask=int(before), new_mask=int(after))
            self._mission139_vision_prev = vision
        except Exception:
            pass

        # Trigger-owned legacy-style AI build goals: publish completion edge once.
        met_now: set[int] = set()
        for owner, goal in dict(getattr(self, "_source128_ai_build_goals", {})).items():
            building_type, count = int(goal[0]), max(1, int(goal[1]))
            have = sum(1 for u in current.values() if int(u.owner) == int(owner) and int(u.unit_type) == building_type)
            if have >= count:
                met_now.add(int(owner))
                if int(owner) not in self._mission139_ai_goal_met:
                    self._mission_add_event("AI Build Goal Met", None, player=int(owner), unit_type=building_type, amount=have, required=count)
        self._mission139_ai_goal_met = met_now

    # ---------------------------------------------------------------- conditions
    def massive_value(self, kind: str, args: dict[str, Any], player: int) -> Any:
        event_conditions = {
            "Player Issued Native Order", "Native Command Button Clicked", "Attack Hit", "Attack Missed", "Projectile Impact",
            "Production Cancelled", "Training Cancelled", "Research Cancelled", "Upgrade Started", "Upgrade Cancelled", "Production Resumed", "Production Paused Event",
            "Worker Entered Gold Mine", "Worker Exited Gold Mine", "Tanker Entered Oil Patch", "Tanker Exited Oil Patch", "Resource Harvested", "Resource Node Depleted",
            "Spell Cast Started", "Spell Cast Finished", "Spell Cast Interrupted", "Unit Entered Player Vision", "Unit Left Player Vision", "Unit Entered Attack Range", "Unit Left Attack Range",
            "Briefing Finished", "Objectives Screen Opened", "Objectives Screen Closed", "Transmission Started", "Transmission Finished", "Slideshow Finished", "Campaign Map Finished",
            "FMV Finished", "Finale Finished", "Fade Finished", "Music Finished", "Results Screen Opened", "Results Screen Closed",
            "Before Native Save", "After Native Save", "After Native Load", "Game Paused Event", "Game Resumed Event", "Diplomacy Changed", "Shared Vision Changed", "AI Build Goal Met",
        }
        if kind in event_conditions:
            return self._mission_event_count(kind, args, player)
        if kind == "Briefing Active":
            return "Yes" if self._mission139_ui["briefing"].get("active") else "No"
        if kind == "Briefing Scrolling":
            return "Yes" if self._mission139_ui["briefing"].get("scrolling") else "No"
        if kind == "Objectives Screen Is Open":
            return "Yes" if self._mission139_ui["objectives"].get("open") else "No"
        if kind == "Transmission Active":
            return "Yes" if self._mission139_ui["transmission"].get("active") else "No"
        if kind == "Slideshow Active":
            return "Yes" if self._mission139_ui["slideshow"].get("active") else "No"
        if kind == "FMV Active":
            return "Yes" if self._mission139_ui["fmv"].get("active") else "No"
        if kind == "Finale Active":
            return "Yes" if self._mission139_ui["finale"].get("active") else "No"
        if kind == "Fade Active":
            return "Yes" if self._mission139_ui["fade"].get("active") else "No"
        if kind == "Fade Percent":
            return int(self._mission139_ui["fade"].get("percent", 0))
        if kind == "Music Playing":
            return "Yes" if self._mission_music_state.get("state") == "Playing" else "No"
        if kind == "Results Screen Is Open":
            return "Yes" if self._mission139_ui["results"].get("open") else "No"
        if kind == "Hard Cutscene Input Lock Active":
            # 1.39 exposes the authoring state but does not claim a verified modern
            # keyboard/mouse dispatcher hook. Source Lock Player Input remains local.
            return "Yes" if bool(getattr(self, "_source128_input_locked", False)) else "No"
        if kind == "Native Camera Zoom State":
            return float(getattr(self, "_mission132_zoom_state", 1.0))
        if kind == "Campaign Map Scale":
            return float(self._mission132_campaign_map.get("scale", 1.0))
        if kind == "Campaign Map Screen X":
            return int(self._mission132_campaign_map.get("screen_x", 0))
        if kind == "Campaign Map Screen Y":
            return int(self._mission132_campaign_map.get("screen_y", 0))
        return super().massive_value(kind, args, player)

    # ------------------------------------------------------------------ actions
    def massive_action(self, kind: str, args: dict[str, Any], player: int) -> bool:
        now = time.monotonic()

        # legacy reference module-shaped briefing controls.
        if kind == "Set Briefing Text Area":
            self._mission139_ui["briefing"]["rect"] = (int(args.get("left", 0)), int(args.get("top", 0)), int(args.get("right", 640)), int(args.get("bottom", 480)))
            return True
        if kind == "Set Briefing Image":
            self._mission139_ui["briefing"]["image"] = str(args.get("image", ""))
            return True
        if kind in {"Activate Briefing", "Start Scrolling Briefing"}:
            state = self._mission139_ui["briefing"]
            state.update({"active": True, "finished": False, "scrolling": kind == "Start Scrolling Briefing" or bool(args.get("scrolling", False)), "text": str(args.get("text", args.get("story", "")))})
            seconds = max(0.0, float(args.get("seconds", 0.0)))
            state["until"] = now + seconds if seconds else 0.0
            if state["text"]:
                self._game_message({"text": state["text"], "color": str(args.get("color", "White — native highlight")), "recipients": str(args.get("recipients", "All active players")), "seconds": max(1, int(args.get("message_seconds", 6))), "also_log": False}, player)
            return True
        if kind == "Stop Scrolling Briefing":
            self._mission139_ui["briefing"]["scrolling"] = False
            return True
        if kind == "Deactivate Briefing":
            state = self._mission139_ui["briefing"]
            was = bool(state.get("active"))
            state.update({"active": False, "scrolling": False, "finished": True, "until": 0.0})
            if was:
                self._mission139_queue_event("Briefing Finished")
            return True

        # Objectives source control. Existing 1.38 native open/override path remains
        # authoritative; these are convenient legacy-style authoring operations.
        if kind == "Append Trigger Objective":
            name = str(args.get("name", f"Objective {len(self._campaign_objectives)+1}"))
            return super().massive_action("Set Campaign Objective", {**args, "name": name, "text": str(args.get("text", name))}, player)
        if kind == "Replace Trigger Objective List":
            super().massive_action("Clear All Campaign Objectives", {}, player)
            lines = [line.strip() for line in str(args.get("objectives", "")).replace(";", "\n").splitlines() if line.strip()]
            for index, line in enumerate(lines, 1):
                super().massive_action("Set Campaign Objective", {"name": f"Objective {index}", "text": line, "announce": False}, player)
            return True
        if kind == "Open Objectives Screen":
            result = super().massive_action("Open Scenario Objectives", args, player)
            self._mission139_ui["objectives"]["open"] = True
            self._mission139_queue_event("Objectives Screen Opened")
            return result
        if kind == "Close Objectives Screen":
            if self._mission139_ui["objectives"].get("open"):
                self._mission139_ui["objectives"]["open"] = False
                self._mission139_queue_event("Objectives Screen Closed")
            return True

        # Portrait/transmission queue. Safe fallback uses validated Scene Transmission.
        if kind == "Set Transmission Portrait":
            self._mission139_ui["transmission"]["portrait"] = str(args.get("portrait", args.get("actor", "")))
            return True
        if kind == "Clear Transmission Portrait":
            self._mission139_ui["transmission"]["portrait"] = ""
            return True
        if kind == "Start Portrait Transmission":
            state = self._mission139_ui["transmission"]
            seconds = max(0.0, float(args.get("seconds", 4.0)))
            state.update({"active": True, "until": now + seconds if seconds else 0.0})
            self._mission139_queue_event("Transmission Started")
            safe = dict(args)
            safe.setdefault("actor", state.get("portrait", ""))
            safe.setdefault("text", str(args.get("text", "Transmission")))
            safe.setdefault("seconds", seconds)
            # Keep this non-blocking: Scene Transmission can intentionally defer the
            # action scheduler, which would cause this wrapper to re-stage the same
            # transmission. The validated Warcraft map-message path is the safe
            # presentation primitive; portrait ownership remains state-backed.
            self._game_message({"text": safe["text"], "recipients": str(args.get("recipients", "All active players")), "seconds": max(1, int(seconds or 4)), "also_log": False}, player)
            return True
        if kind == "Stop Portrait Transmission":
            state = self._mission139_ui["transmission"]
            if state.get("active"):
                state.update({"active": False, "until": 0.0})
                self._mission139_queue_event("Transmission Finished")
            return True

        # Slideshow/interlude authoring layer.
        if kind == "Start Campaign Slideshow":
            state = self._mission139_ui["slideshow"]
            state.update({"active": True, "finished": False, "index": 0, "until": 0.0})
            title = str(args.get("title", "SLIDESHOW"))
            if title:
                self._game_message({"text": title, "color": "White — native highlight", "recipients": str(args.get("recipients", "All active players")), "seconds": 3, "also_log": False}, player)
            return True
        if kind in {"Show Slideshow Frame", "Next Slideshow Frame"}:
            state = self._mission139_ui["slideshow"]
            state["active"] = True; state["finished"] = False
            if kind == "Next Slideshow Frame":
                state["index"] = int(state.get("index", 0)) + 1
            else:
                state["index"] = max(0, int(args.get("index", state.get("index", 0))))
            text = str(args.get("text", args.get("caption", f"Slide {int(state['index'])+1}")))
            seconds = max(0.0, float(args.get("seconds", 0.0)))
            state["until"] = now + seconds if seconds else 0.0
            self._game_message({"text": text, "color": str(args.get("color", "White — native highlight")), "recipients": str(args.get("recipients", "All active players")), "seconds": max(1, int(args.get("message_seconds", seconds or 4))), "also_log": False}, player)
            return True
        if kind == "Stop Campaign Slideshow":
            state = self._mission139_ui["slideshow"]
            if state.get("active"):
                state.update({"active": False, "finished": True, "until": 0.0})
                self._mission139_queue_event("Slideshow Finished")
            return True
        if kind == "Start Native Campaign Map":
            return super().massive_action("Show Campaign Map", args, player)
        if kind == "Add Native Campaign Dot":
            return super().massive_action("Add Campaign Dot", args, player)
        if kind == "Draw Native Campaign Route Segment":
            return super().massive_action("Draw Campaign Route", args, player)
        if kind == "Set Campaign Map Scale":
            self._mission132_campaign_map["scale"] = max(0.05, float(args.get("scale", 1.0)))
            return True
        if kind == "Set Campaign Map Position":
            self._mission132_campaign_map["screen_x"] = int(args.get("x", 0))
            self._mission132_campaign_map["screen_y"] = int(args.get("y", 0))
            return True
        if kind == "Stop Native Campaign Map":
            result = super().massive_action("Hide Campaign Map", args, player)
            self._mission139_queue_event("Campaign Map Finished")
            return result

        # Finale/FMV state-backed authoring. require_native=True fails closed.
        if kind == "Play FMV":
            if bool(args.get("require_native", False)):
                raise RuntimeError("Play FMV: native Remastered movie-player ABI is not verified; failed closed")
            state = self._mission139_ui["fmv"]
            seconds = max(0.0, float(args.get("seconds", 5.0)))
            state.update({"active": True, "finished": False, "until": now + seconds if seconds else 0.0, "movie": str(args.get("movie", ""))})
            text = str(args.get("fallback_text", "")) or ("CINEMATIC" + (f"\n{state['movie']}" if state["movie"] else ""))
            self._game_message({"text": text, "color": "White — native highlight", "recipients": str(args.get("recipients", "All active players")), "seconds": max(1, int(seconds or 5)), "also_log": False}, player)
            return True
        if kind == "Stop FMV":
            state = self._mission139_ui["fmv"]
            if state.get("active"):
                state.update({"active": False, "finished": True, "until": 0.0}); self._mission139_queue_event("FMV Finished")
            return True
        if kind == "Start Finale":
            state = self._mission139_ui["finale"]
            seconds = max(0.0, float(args.get("seconds", 0.0)))
            state.update({"active": True, "finished": False, "until": now + seconds if seconds else 0.0, "text": str(args.get("text", "FINALE"))})
            if state["text"]:
                self._game_message({"text": state["text"], "color": "White — native highlight", "recipients": str(args.get("recipients", "All active players")), "seconds": max(1, int(args.get("message_seconds", 6))), "also_log": False}, player)
            return True
        if kind == "Show Scrolling Finale Text":
            text = str(args.get("text", ""))
            self._mission139_ui["finale"]["text"] = text
            self._game_message({"text": text, "color": str(args.get("color", "White — native highlight")), "recipients": str(args.get("recipients", "All active players")), "seconds": max(1, int(args.get("seconds", 6))), "also_log": False}, player)
            return True
        if kind == "Stop Finale":
            state = self._mission139_ui["finale"]
            if state.get("active"):
                state.update({"active": False, "finished": True, "until": 0.0}); self._mission139_queue_event("Finale Finished")
            return True

        # Screen fade authoring. Native renderer remains a separate ABI target.
        if kind in {"Fade Screen In", "Fade Screen Out", "Fade Screen To Black"}:
            state = self._mission139_ui["fade"]
            target = 0 if kind == "Fade Screen In" else 100
            seconds = max(0.0, float(args.get("seconds", 0.75)))
            state.update({"active": seconds > 0, "finished": seconds <= 0, "target": target, "until": now + seconds if seconds else 0.0})
            if seconds <= 0:
                state["percent"] = target; self._mission139_queue_event("Fade Finished")
            return True
        if kind == "Set Screen Fade Percent":
            state = self._mission139_ui["fade"]
            state.update({"active": False, "finished": True, "percent": max(0, min(100, int(args.get("percent", 0)))), "until": 0.0})
            return True

        # Music stream authoring aliases. Exact native stream is still fail-closed,
        # but state and timing are first-class and useful to mission logic.
        if kind == "Play Native Campaign Music":
            if bool(args.get("require_native", False)):
                raise RuntimeError("Native campaign music stream ABI is not verified; failed closed")
            self._mission_music_state = {"track": str(args.get("track", "")), "state": "Playing", "volume": max(0, min(100, int(args.get("volume", 100))))}
            seconds = max(0.0, float(args.get("estimated_seconds", 0.0)))
            self._mission139_music_until = now + seconds if seconds else 0.0
            return True
        if kind == "Fade Native Music":
            self._mission_music_state["volume"] = max(0, min(100, int(args.get("to_volume", 0))))
            if int(self._mission_music_state["volume"]) <= 0:
                self._mission_music_state["state"] = "Stopped"; self._mission139_queue_event("Music Finished")
            return True
        if kind == "Stop Native Music":
            was = self._mission_music_state.get("state") == "Playing"
            self._mission_music_state["state"] = "Stopped"; self._mission139_music_until = 0.0
            if was: self._mission139_queue_event("Music Finished")
            return True
        if kind == "Set Native Music Volume":
            self._mission_music_state["volume"] = max(0, min(100, int(args.get("volume", 100))))
            return True

        # Mission results presentation state.
        if kind in {"Open Mission Results", "Open Victory Statistics"}:
            self._mission139_ui["results"]["open"] = True
            self._mission139_queue_event("Results Screen Opened")
            return super().massive_action("Show Victory Statistics" if kind.endswith("Victory Statistics") else "Show Mission Results", args, player)
        if kind == "Close Mission Results":
            if self._mission139_ui["results"].get("open"):
                self._mission139_ui["results"]["open"] = False; self._mission139_queue_event("Results Screen Closed")
            return True

        # Input lock: safe authoring state only; never patches an unverified UI vtable.
        if kind == "Lock Gameplay Input":
            return super().massive_action("Source Lock Player Input", args, player)
        if kind == "Unlock Gameplay Input":
            return super().massive_action("Source Unlock Player Input", args, player)

        # Native save lifecycle markers. These are explicit integration hooks for
        # authored save actions; they do not pretend we intercept arbitrary Ctrl+S.
        if kind == "Mark Before Native Save":
            self._mission139_queue_event("Before Native Save"); return True
        if kind == "Mark After Native Save":
            self._mission139_queue_event("After Native Save"); return True
        if kind == "Mark After Native Load":
            self._mission139_queue_event("After Native Load"); return True

        # Camera aliases retain 1.32's authored zoom state and fail-closed boundary.
        if kind == "Native Camera Shrink":
            return super().massive_action("Scene Camera Zoom Out", {**args, "fallback_to_state_only": True}, player)
        if kind == "Native Camera Expand":
            return super().massive_action("Scene Camera Zoom In", {**args, "fallback_to_state_only": True}, player)

        # One convenience for mission authors who want to explicitly clear edge history.
        if kind in {"Clear Source Event History", "Clear legacy Event History"}:
            self._mission_events.clear(); self._available_events.clear(); self._mission139_pending_events.clear(); return True

        return super().massive_action(kind, args, player)
