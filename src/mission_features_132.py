from __future__ import annotations

import ctypes
import math
import os
import time
from ctypes import wintypes
from typing import Any

from engine import ActionDeferred
from mission_features_131 import MissionFeature131Mixin
from source_features import BUILD_UNIT, BUILD_TECH, BUILD_SPELL, BUILD_UPGRADE, UF_BUILD_ON
from source_features_128 import SF_COMPLETED, SF_HIDDEN
from ultimate_features import SPELL_BITS, UPGRADE_ROWS


# Native-verified unit cost arrays resolved by the 1.0.2.2818 UNITDATA loader work.
# Warcraft stores unit costs in 10-resource steps, matching reference module's
# gbUnit*CostTbl[bParm] * COST_STEP_VALUE contract.
UNIT_GOLD_COST_RVA_2818 = 0x00517980
UNIT_LUMBER_COST_RVA_2818 = 0x005179F0
UNIT_OIL_COST_RVA_2818 = 0x00517A60
COST_STEP_VALUE = 10


class _POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


class MissionFeature132Mixin(MissionFeature131Mixin):
    """1.32 legacy mission-surface expansion.

    The legacy source is used as an authoring checklist. 1.32 adds every remaining
    useful mission-facing surface identified in reference module, reference module, game_evt.c,
    reference module, reference module, reference module, reference module, reference module, reference module, reference module,
    reference module, and unit.c.

    Safety rule: where the Remastered 1.0.2.2818 native ABI has not been proven,
    the action is implemented as trigger-owned/state-backed behavior or an
    explicit Experimental/fail-closed bridge. Nothing silently jumps to a guessed
    C++ address.
    """

    def _init_massive_features(self) -> None:
        super()._init_massive_features()
        self._mission132_target: dict[str, Any] = {
            "active": False, "selected": False, "x": -1, "y": -1,
            "unit_address": 0, "unit_type": -1, "unit_owner": -1,
            "serial": 0, "prompt": "Select a target", "kind": "Any",
        }
        self._mission132_placement: dict[str, Any] = {
            "active": False, "building_type": 58, "owner": 0, "valid": False,
            "candidate": None, "placed": False, "placed_serial": 0,
            "complete": False,
        }
        self._mission132_input_map: dict[str, float] = {
            "viewport_left": 0.0, "viewport_top": 0.0,
            "pixel_scale_x": 1.0, "pixel_scale_y": 1.0,
            # Negative minimap bounds = disabled until explicitly configured.
            "minimap_left": -1.0, "minimap_top": -1.0,
            "minimap_right": -1.0, "minimap_bottom": -1.0,
        }
        self._mission132_mouse_prev = {"left": False, "right": False, "middle": False}
        self._mission132_mouse_last_client = (-1, -1)
        self._mission132_mouse_last_tile = (-1, -1)
        self._mission132_mouse_edges: list[dict[str, Any]] = []
        self._mission132_custom_buttons: dict[str, dict[str, Any]] = {}
        self._mission132_button_key_prev: dict[str, bool] = {}
        self._mission132_button_click_serial: dict[str, int] = {}
        self._mission132_auto_build: dict[str, dict[str, Any]] = {}
        self._mission132_animation_loops: dict[str, dict[str, Any]] = {}
        self._mission132_animation_prev: dict[str, tuple[int, int, int]] = {}
        self._mission132_projectiles_prev: dict[int, dict[str, Any]] = {}
        self._mission132_result_state: dict[str, Any] = {"rank": "", "bonus": 0, "mission_time": 0.0}
        self._mission132_campaign_map: dict[str, Any] = {"visible": False, "title": "", "dots": [], "routes": []}
        self._mission132_cursor_state: dict[str, Any] = {"visible": True, "cursor": "Default"}
        self._mission132_zoom_state = 1.0
        self._mission132_sound_looping = False
        self._mission132_sound_file = ""
        self._mission132_sound_started = 0.0
        self._mission132_command_serial = 0
        self._mission132_construction_progress: dict[tuple[int, int], int] = {}

    def _massive_begin_run(self) -> None:
        super()._massive_begin_run()
        self._mission132_target.update({"active": False, "selected": False, "x": -1, "y": -1, "unit_address": 0, "unit_type": -1, "unit_owner": -1})
        self._mission132_placement.update({"active": False, "valid": False, "candidate": None, "placed": False})
        self._mission132_mouse_edges.clear()
        self._mission132_custom_buttons.clear()
        self._mission132_button_key_prev.clear()
        self._mission132_button_click_serial.clear()
        self._mission132_auto_build.clear()
        self._mission132_animation_loops.clear()
        self._mission132_animation_prev.clear()
        self._mission132_projectiles_prev.clear()
        self._mission132_campaign_map = {"visible": False, "title": "", "dots": [], "routes": []}
        self._mission132_cursor_state = {"visible": True, "cursor": "Default"}
        self._mission132_zoom_state = 1.0
        self._mission132_sound_looping = False
        self._mission132_sound_file = ""
        self._mission132_sound_started = 0.0
        self._mission132_command_serial = 0
        self._mission132_construction_progress.clear()

    # ----------------------------------------------------------------- local input
    def _mission132_hwnd(self) -> int:
        if not os.name == "nt":
            return 0
        pid = int(getattr(getattr(self, "pm", None), "process_id", 0) or 0)
        if not pid:
            return 0
        user32 = ctypes.windll.user32
        found: list[int] = []
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @WNDENUMPROC
        def cb(hwnd, _lparam):
            if not user32.IsWindowVisible(hwnd):
                return True
            out_pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(out_pid))
            if int(out_pid.value) == pid:
                rect = _RECT()
                if user32.GetClientRect(hwnd, ctypes.byref(rect)) and rect.right > rect.left and rect.bottom > rect.top:
                    found.append(int(hwnd))
                    return False
            return True

        try:
            user32.EnumWindows(cb, 0)
        except Exception:
            return 0
        return found[0] if found else 0

    def _mission132_mouse_client(self) -> tuple[int, int, int, int] | None:
        if not os.name == "nt":
            return None
        hwnd = self._mission132_hwnd()
        if not hwnd:
            return None
        user32 = ctypes.windll.user32
        pt = _POINT()
        rect = _RECT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return None
        if not user32.ScreenToClient(hwnd, ctypes.byref(pt)):
            return None
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return None
        return int(pt.x), int(pt.y), int(rect.right - rect.left), int(rect.bottom - rect.top)

    def _mission132_mouse_world_tile(self) -> tuple[int, int] | None:
        client = self._mission132_mouse_client()
        if client is None:
            return None
        cx, cy, cw, ch = client
        if not (0 <= cx < cw and 0 <= cy < ch):
            return None
        cam = self._campaign_current_camera() or (0, 0)
        cfg = self._mission132_input_map
        sx = max(0.05, float(cfg.get("pixel_scale_x", 1.0)))
        sy = max(0.05, float(cfg.get("pixel_scale_y", 1.0)))
        vx = float(cfg.get("viewport_left", 0.0))
        vy = float(cfg.get("viewport_top", 0.0))
        # The legacy source works in 32-pixel matrix cells. Remastered can scale its
        # client surface, so 1.32 makes scale/margins author-configurable rather
        # than pretending the local Windows cursor is an exact native reference module hook.
        tx = int(cam[0] + max(0.0, cx - vx) / (32.0 * sx))
        ty = int(cam[1] + max(0.0, cy - vy) / (32.0 * sy))
        return max(0, min(int(self.map_width) - 1, tx)), max(0, min(int(self.map_height) - 1, ty))

    def _mission132_mouse_in_minimap(self, cx: int, cy: int) -> bool:
        cfg = self._mission132_input_map
        l, t, r, b = (float(cfg.get(k, -1.0)) for k in ("minimap_left", "minimap_top", "minimap_right", "minimap_bottom"))
        return l >= 0 and t >= 0 and r > l and b > t and l <= cx <= r and t <= cy <= b

    def _mission132_capture_target(self, world: list[Any], x: int, y: int) -> None:
        nearest = None
        best = 999999
        for unit in world:
            if int(unit.sflags) & SF_HIDDEN:
                continue
            d = max(abs(int(unit.x) - int(x)), abs(int(unit.y) - int(y)))
            if d <= 1 and d < best:
                nearest, best = unit, d
        wanted_kind = str(self._mission132_target.get("kind", "Any")).strip().casefold()
        if wanted_kind in {"unit", "building"}:
            if nearest is None:
                self.log(f"TARGET REJECTED v1.32: {wanted_kind} required at ({x},{y}); no unit under cursor")
                return
            is_building = int(nearest.unit_type) >= 58
            if wanted_kind == "unit" and is_building:
                self.log(f"TARGET REJECTED v1.32: mobile unit required at ({x},{y}); building type {int(nearest.unit_type)} found")
                return
            if wanted_kind == "building" and not is_building:
                self.log(f"TARGET REJECTED v1.32: building required at ({x},{y}); mobile type {int(nearest.unit_type)} found")
                return
        self._mission132_target.update({
            "selected": True, "x": int(x), "y": int(y), "serial": int(self._mission132_target.get("serial", 0)) + 1,
            "unit_address": int(nearest.address) if nearest is not None else 0,
            "unit_type": int(nearest.unit_type) if nearest is not None else -1,
            "unit_owner": int(nearest.owner) if nearest is not None else -1,
        })
        self.log(f"TARGET SELECTED v1.32: tile=({x},{y})" + (f" unit=P{int(nearest.owner)+1} type {int(nearest.unit_type)}" if nearest else ""))

    def _mission132_placement_valid(self, x: int, y: int, building_type: int) -> bool:
        if not (58 <= int(building_type) <= 104 and 0 <= x < int(self.map_width) and 0 <= y < int(self.map_height)):
            return False
        # Best available no-side-effect validation: if a live prototype of the
        # same type exists, reuse Warcraft's verified placeable() callback. On a
        # truly blank map there may be no prototype, so fall back to collision-free
        # occupancy and let native unit_create/mtx_place_bldg make the final call.
        proto = next((u for u in self.units() if int(u.unit_type) == int(building_type)), None)
        if proto is not None:
            try:
                return bool(self._source128_placeable(proto, int(x), int(y)))
            except Exception:
                pass
        return not any(max(abs(int(u.x)-x), abs(int(u.y)-y)) <= 1 for u in self.units() if not (int(u.sflags) & SF_HIDDEN))

    def _massive_prepare_pre(self, world: list[Any]) -> bool:
        result = super()._massive_prepare_pre(world)
        if result is False:
            return False

        # Poll local mouse edges. This is deliberately local presentation input,
        # analogous to the source game_evt.c hooks, not synchronized MP state.
        self._mission132_mouse_edges.clear()
        if os.name == "nt":
            user32 = ctypes.windll.user32
            states = {
                "left": bool(user32.GetAsyncKeyState(0x01) & 0x8000),
                "right": bool(user32.GetAsyncKeyState(0x02) & 0x8000),
                "middle": bool(user32.GetAsyncKeyState(0x04) & 0x8000),
            }
            client = self._mission132_mouse_client()
            tile = self._mission132_mouse_world_tile()
            old_client = self._mission132_mouse_last_client
            if client is not None:
                cx, cy, _cw, _ch = client
                if (cx, cy) != old_client and tile is not None and tile != self._mission132_mouse_last_tile:
                    self._mission132_mouse_edges.append({"event_type": "Mouse Moved Over Tile", "x": tile[0], "y": tile[1], "client_x": cx, "client_y": cy})
                self._mission132_mouse_last_client = (cx, cy)
                if tile is not None:
                    self._mission132_mouse_last_tile = tile
            for name, down in states.items():
                prev = bool(self._mission132_mouse_prev.get(name, False))
                if down and not prev and tile is not None:
                    event = {"event_type": ("Left Clicked Map" if name == "left" else "Right Clicked Map" if name == "right" else "Middle Clicked Map"), "x": tile[0], "y": tile[1]}
                    if client is not None:
                        event.update({"client_x": client[0], "client_y": client[1]})
                        if self._mission132_mouse_in_minimap(client[0], client[1]):
                            self._mission132_mouse_edges.append({"event_type": "Minimap Clicked", **event})
                    self._mission132_mouse_edges.append(event)
                    if name == "left" and self._mission132_target.get("active"):
                        self._mission132_capture_target(world, tile[0], tile[1])
                        if self._mission132_placement.get("active"):
                            valid = self._mission132_placement_valid(tile[0], tile[1], int(self._mission132_placement.get("building_type", 58)))
                            self._mission132_placement["candidate"] = tile
                            self._mission132_placement["valid"] = valid
                self._mission132_mouse_prev[name] = down

            # A held minimap left-button plus client movement is exposed as Drag.
            if states["left"] and client is not None and self._mission132_mouse_in_minimap(client[0], client[1]):
                if old_client != (-1, -1) and (client[0], client[1]) != old_client:
                    self._mission132_mouse_edges.append({"event_type": "Minimap Dragged", "x": tile[0] if tile else -1, "y": tile[1] if tile else -1})

        # Keep authored animation loops alive without inventing a renderer callback.
        for actor_name, spec in list(self._mission132_animation_loops.items()):
            actor = self._resolve_unit_reference(actor_name)
            if actor is None:
                self._mission132_animation_loops.pop(actor_name, None)
                continue
            try:
                self.pm.write_uchar(actor.address + 0x08, int(spec.get("animation", 0)) & 0xFF)
                if spec.get("hold_frame") is not None:
                    self.pm.write_uchar(actor.address + 0x09, int(spec.get("hold_frame", 0)) & 0xFF)
                self.pm.write_uchar(actor.address + 0x07, max(1, int(spec.get("timer", 1))) & 0xFF)
            except Exception:
                self._mission132_animation_loops.pop(actor_name, None)

        # Trigger-owned auto-production/autoupgrade model based on the source
        # bldg_auto_build/bldg_auto_upgrade behavior, but using the verified
        # Remastered bldg_build_start callback rather than legacy-only globals.
        for actor_name, state in list(self._mission132_auto_build.items()):
            if not state.get("enabled", False) or state.get("paused", False):
                continue
            building = self._resolve_unit_reference(actor_name)
            if building is None or int(building.unit_type) < 58:
                continue
            try:
                if self.pm.read_ushort(building.address + 0x1C) & UF_BUILD_ON:
                    continue
            except Exception:
                continue
            items = list(state.get("items", []))
            if not items:
                continue
            idx = int(state.get("index", 0)) % len(items)
            order = int(state.get("order", BUILD_UNIT))
            parm = int(items[idx])
            try:
                if self._source128_direct_start(building, order, parm):
                    state["index"] = (idx + 1) % len(items) if state.get("loop", True) else min(len(items), idx + 1)
                    state["waiting"] = False
                else:
                    state["waiting"] = True
            except ActionDeferred:
                return False
            except Exception:
                state["waiting"] = True
        return True

    def _mission_sample_missiles(self) -> dict[int, dict[str, Any]]:
        """Augment the 1.30 projectile snapshot with native lifetime at +0x38.

        reference module distinguishes ordinary lifetime expiry from impact/destruction. The
        modern exact impact callback is still not bound, but retaining the native
        lifetime makes the inferred end classification materially less ambiguous.
        """
        result = super()._mission_sample_missiles()
        for address, record in result.items():
            try:
                record["life"] = int(self.pm.read_short(int(address) + 0x38))
            except Exception:
                record["life"] = 0
        return result

    def _massive_prepare_events(self, current: dict[tuple[int, int], Any], previous: dict[tuple[int, int], Any]) -> None:
        # Capture the 1.30 missile snapshot before super replaces it so we can
        # classify disappearance with better proximity/lifetime evidence.
        old_missiles = dict(getattr(self, "_mission132_projectiles_prev", {}))
        super()._massive_prepare_events(current, previous)

        for raw in self._mission132_mouse_edges:
            self._mission_add_event(str(raw.get("event_type")), None, **{k: v for k, v in raw.items() if k != "event_type"})

        # Construction progress edges based on native HP progress while incomplete.
        new_progress: dict[tuple[int, int], int] = {}
        for key, unit in current.items():
            if int(unit.unit_type) < 58 or int(unit.sflags) & SF_COMPLETED:
                continue
            try:
                maximum = max(1, int(self._source128_rule_value("Maximum HP", int(unit.unit_type))))
                pct = max(0, min(100, round(int(unit.health) * 100 / maximum)))
            except Exception:
                pct = 0
            new_progress[key] = pct
            if key in self._mission132_construction_progress and self._mission132_construction_progress[key] != pct:
                self._mission_add_event("Construction Progress Changed", unit, old_progress=self._mission132_construction_progress[key], new_progress=pct)
        self._mission132_construction_progress = new_progress

        # Animation edges for named scene actors.
        new_anim: dict[str, tuple[int, int, int]] = {}
        for actor_name in list(self._campaign_actor_meta):
            actor = self._resolve_unit_reference(actor_name)
            if actor is None:
                continue
            try:
                snap = (int(self.pm.read_uchar(actor.address + 0x08)), int(self.pm.read_uchar(actor.address + 0x09)), int(self.pm.read_uchar(actor.address + 0x07)))
            except Exception:
                continue
            old = self._mission132_animation_prev.get(actor_name)
            if old is not None:
                if snap[0] != old[0]:
                    self._mission_add_event("Animation Started", actor, actor=actor_name, animation=snap[0], old_animation=old[0], frame=snap[1])
                if old[2] > 0 and snap[2] == 0:
                    self._mission_add_event("Animation Finished", actor, actor=actor_name, animation=snap[0], frame=snap[1])
            new_anim[actor_name] = snap
        self._mission132_animation_prev = new_anim

        # Attack-connected inference: attacker retains target and target HP drops.
        for key, unit in current.items():
            old_unit = previous.get(key)
            if old_unit is None or not int(getattr(unit, "target_unit", 0)):
                continue
            target = next((u for u in current.values() if int(u.address) == int(unit.target_unit)), None)
            old_target = next((u for u in previous.values() if target is not None and int(u.address) == int(target.address)), None)
            if target is not None and old_target is not None and int(target.health) < int(old_target.health):
                self._mission_add_event("Attack Connected", target, attacker_address=int(unit.address), attacker_player=int(unit.owner), attacker_unit_type=int(unit.unit_type), damage=max(0, int(old_target.health)-int(target.health)), inferred=True)

        # Better native projectile end classification than the 1.30 generic Hit.
        now_missiles = self._mission_sample_missiles()
        for address, old in old_missiles.items():
            if address in now_missiles:
                continue
            tx, ty = int(old.get("target_x", old.get("x", 0))), int(old.get("target_y", old.get("y", 0)))
            x, y = int(old.get("x", 0)), int(old.get("y", 0))
            # Missile coordinates are world pixels in the native TThing header.
            near = max(abs(tx-x), abs(ty-y)) <= 48
            target = self._mission_unit_by_address(current, previous, address=int(old.get("target_unit", 0)))
            extra = {"missile_type": int(old.get("missile_type", -1)), "projectile_owner_unit": int(old.get("owner_unit", 0)), "inferred": True}
            if target is not None and near:
                self._mission_add_event("Projectile Impacted Unit", target, **extra)
            elif target is None and near:
                self._mission_add_event("Projectile Impacted Terrain", None, x=tx >> 5, y=ty >> 5, **extra)
            elif int(old.get("life", 1)) <= 1:
                self._mission_add_event("Projectile Native Expired", None, x=x >> 5, y=y >> 5, **extra)
            else:
                self._mission_add_event("Projectile Missed", target, x=x >> 5, y=y >> 5, **extra)
        self._mission132_projectiles_prev = now_missiles

    # -------------------------------------------------------------------- helpers
    @staticmethod
    def _mission132_parse_int_list(raw: Any) -> list[int]:
        out: list[int] = []
        for part in str(raw or "").replace(";", ",").split(","):
            part = part.strip()
            if not part:
                continue
            try:
                out.append(int(part, 0))
            except Exception:
                # Allow upgrade display names through UPGRADE_ROWS.
                if part in UPGRADE_ROWS:
                    out.append(int(UPGRADE_ROWS[part]))
        return out

    def _mission132_unit_cost(self, unit_type: int) -> tuple[int, int, int]:
        unit_type = int(unit_type)
        if not 0 <= unit_type < 110:
            raise ValueError(f"Invalid Warcraft unit type: {unit_type}")
        if int(getattr(self, "build_timestamp", 0)) == 0x699E13E7:
            try:
                vals = tuple(int(self.pm.read_uchar(self.base + rva + unit_type)) * COST_STEP_VALUE for rva in (UNIT_GOLD_COST_RVA_2818, UNIT_LUMBER_COST_RVA_2818, UNIT_OIL_COST_RVA_2818))
                # Zero is legal for special map objects; accept all 0..255 entries.
                if all(0 <= v <= 2550 for v in vals):
                    return vals  # type: ignore[return-value]
            except Exception:
                pass
        return tuple(max(0, int(self._source128_rule_value(name, unit_type))) for name in ("Gold Cost", "Lumber Cost", "Oil Cost"))  # type: ignore[return-value]

    def _mission132_apply_cost(self, owner: int, costs: tuple[int, int, int], *, refund: bool = False, fraction: float = 1.0) -> bool:
        names = ("Gold", "Lumber", "Oil")
        scaled = tuple(max(0, int(round(v * max(0.0, float(fraction))))) for v in costs)
        before = tuple(self._read_resource(owner, name) for name in names)
        if not refund and any(have < cost for have, cost in zip(before, scaled)):
            return False
        ops = []
        for name, have, cost in zip(names, before, scaled):
            _, addr = self._resource_address(owner, name)
            after = min(0x7FFFFFFF, have + cost) if refund else max(0, have - cost)
            ops.append(("write_dword", addr, after))
        self._dispatch_ops(ops)
        return True

    def _mission132_target_unit(self) -> Any | None:
        address = int(self._mission132_target.get("unit_address", 0))
        if not address:
            return None
        return next((u for u in self.units() if int(u.address) == address), None)

    def _mission132_button(self, button_id: Any) -> dict[str, Any] | None:
        return self._mission132_custom_buttons.get(str(button_id or "Button").strip())

    def _mission132_point(self, args: dict[str, Any], *, key: str = "location") -> tuple[int, int]:
        """Resolve an authored point from location/X/Y or trigger variables."""
        xv = str(args.get("x_variable", "")).strip()
        yv = str(args.get("y_variable", "")).strip()
        if xv and yv:
            return int(self.variables.get(xv, 0)), int(self.variables.get(yv, 0))
        return self._campaign_point(args, key=key)

    def _mission132_prerequisites_met(self, args: dict[str, Any], player: int) -> bool:
        owner = int(args.get("player", player))
        required = str(args.get("required_units", "")).strip()
        if required:
            for token in required.replace(";", ",").split(","):
                token = token.strip()
                if not token:
                    continue
                if "x" in token.lower():
                    left, right = token.lower().split("x", 1)
                    unit_type, count = int(left, 0), max(1, int(right, 0))
                else:
                    unit_type, count = int(token, 0), 1
                have = sum(1 for u in self.units() if int(u.owner) == owner and int(u.unit_type) == unit_type and not (int(u.sflags) & SF_HIDDEN))
                if have < count:
                    return False
        return True

    # ---------------------------------------------------------------- conditions
    def massive_value(self, kind: str, args: dict[str, Any], player: int) -> Any:
        if kind == "Target Selection Active":
            return "Yes" if self._mission132_target.get("active") else "No"
        if kind == "Target Tile Selected":
            return 1 if self._mission132_target.get("selected") else 0
        if kind == "Target Unit Selected":
            return 1 if self._mission132_target.get("selected") and int(self._mission132_target.get("unit_address", 0)) else 0
        if kind == "Target X":
            return int(self._mission132_target.get("x", -1))
        if kind == "Target Y":
            return int(self._mission132_target.get("y", -1))
        if kind == "Target Unit Type":
            return int(self._mission132_target.get("unit_type", -1))
        if kind == "Target Unit Owner":
            return int(self._mission132_target.get("unit_owner", -1))
        if kind == "Target Is Building":
            return "Yes" if int(self._mission132_target.get("unit_type", -1)) >= 58 else "No"
        if kind == "Target Too Far For Spell":
            actor = self._campaign_actor(args.get("actor", "Actor"), required=False)
            if actor is None or not self._mission132_target.get("selected"):
                return "No"
            distance = max(abs(int(actor.x)-int(self._mission132_target["x"])), abs(int(actor.y)-int(self._mission132_target["y"])))
            return "Yes" if distance > max(0, int(args.get("range", 8))) else "No"
        if kind == "Placement Valid":
            candidate = self._mission132_placement.get("candidate")
            if candidate is None:
                return "No"
            return "Yes" if self._mission132_placement_valid(int(candidate[0]), int(candidate[1]), int(self._mission132_placement.get("building_type", 58))) else "No"
        if kind == "Player Placed Building":
            return 1 if bool(self._mission132_placement.get("placed")) else 0
        if kind in {"Left Clicked Map", "Right Clicked Map", "Mouse Moved Over Tile", "Minimap Clicked", "Minimap Dragged", "Construction Progress Changed", "Animation Started", "Animation Finished", "Attack Connected", "Projectile Impacted Unit", "Projectile Impacted Terrain", "Projectile Missed", "Projectile Native Expired"}:
            return self._mission_event_count(kind, args, player)
        if kind in {"Key Down", "Key Up"}:
            vk = self._mission131_vk(args.get("key", "Space"))
            current = self._mission131_key_state(vk)
            key = ("mission132", vk)
            previous = bool(getattr(self, "_mission132_key_prev", {}).get(key, False)) if hasattr(self, "_mission132_key_prev") else False
            if not hasattr(self, "_mission132_key_prev"):
                self._mission132_key_prev = {}
            self._mission132_key_prev[key] = current
            return 1 if (current and not previous if kind == "Key Down" else previous and not current) else 0
        if kind == "Player Issued Command":
            return self._mission_event_count("Player Issued Order (Inferred)", args, player)
        if kind == "Button Clicked":
            bid = str(args.get("button_id", "Button")).strip()
            button = self._mission132_button(bid)
            if not button or not button.get("enabled", True):
                return 0
            hotkey = str(button.get("hotkey", args.get("hotkey", ""))).strip()
            if not hotkey:
                return 0
            vk = self._mission131_vk(hotkey)
            current = self._mission131_key_state(vk)
            prev = bool(self._mission132_button_key_prev.get(bid, False))
            self._mission132_button_key_prev[bid] = current
            if current and not prev:
                self._mission132_button_click_serial[bid] = int(self._mission132_button_click_serial.get(bid, 0)) + 1
                self._mission132_command_serial += 1
                return 1
            return 0
        if kind == "Command Available":
            button = self._mission132_button(args.get("button_id", "Button"))
            return "Yes" if button and button.get("enabled", True) else "No"
        if kind == "Can Train Unit":
            owner, unit_type = int(args.get("player", player)), int(args.get("unit", args.get("new_unit", 0)))
            affordable = bool(super().massive_value("Source Player Can Afford Unit", {"player": owner, "new_unit": unit_type}, owner))
            return "Yes" if 0 <= unit_type < 58 and affordable and self._mission132_prerequisites_met(args, owner) else "No"
        if kind == "Can Build Structure":
            owner, unit_type = int(args.get("player", player)), int(args.get("building", args.get("new_building", 58)))
            affordable = bool(super().massive_value("Source Player Can Afford Unit", {"player": owner, "new_unit": unit_type}, owner))
            return "Yes" if 58 <= unit_type <= 104 and affordable and self._mission132_prerequisites_met(args, owner) else "No"
        if kind == "Can Research Spell":
            owner = int(args.get("player", player)); spell = str(args.get("spell", "Blizzard"))
            bit = int(SPELL_BITS.get(spell, -1))
            if bit < 0:
                return "No"
            try:
                tables = self._resolve_progression_tables(); researched = int(self.pm.read_uint(int(tables["spells"]) + owner*4))
                return "Yes" if not (researched & (1 << bit)) and self._mission132_prerequisites_met(args, owner) else "No"
            except Exception:
                return "No"
        if kind == "Can Research Upgrade":
            owner = int(args.get("player", player)); row = int(args.get("upgrade_id", UPGRADE_ROWS.get(str(args.get("upgrade", "Melee Attack")), 0)))
            try:
                _spells, tech = self._mission_sample_progression(); level = int(tech[row*16+owner]) if tech is not None and row*16+owner < len(tech) else 0
            except Exception:
                level = 0
            affordable = bool(super().massive_value("Source Player Can Afford Upgrade", {"player": owner, "upgrade": str(args.get("upgrade", "Melee Attack")), "upgrade_id": row}, owner))
            return "Yes" if level < max(1, int(args.get("max_level", 2))) and affordable and self._mission132_prerequisites_met(args, owner) else "No"
        if kind == "Prerequisites Met":
            return "Yes" if self._mission132_prerequisites_met(args, player) else "No"
        if kind == "Auto Build Waiting":
            state = self._mission132_auto_build.get(str(args.get("actor", "Building")), {})
            return "Yes" if bool(state.get("waiting") or state.get("paused")) else "No"
        if kind == "Production Put On Hold":
            actor = self._campaign_actor(args.get("actor", "Building"), required=False)
            if actor is None:
                return "No"
            key = self._source_unit_key(actor)
            return "Yes" if key in getattr(self, "_source128_paused_production", {}) else "No"
        if kind == "Can Attack Target" or kind == "Can Hit Target":
            actor = self._campaign_actor(args.get("actor", "Actor"), required=False)
            target = self._campaign_actor(args.get("target_actor", "Target"), required=False)
            if actor is None or target is None or int(actor.unit_type) >= 58:
                return "No"
            if self._players_allied(int(actor.owner), int(target.owner)):
                return "No"
            distance = max(abs(int(actor.x)-int(target.x)), abs(int(actor.y)-int(target.y)))
            attack_range = max(1, int(self._source128_rule_value("Attack Range", int(actor.unit_type))))
            if kind == "Can Attack Target":
                return "Yes"
            return "Yes" if distance <= attack_range else "No"
        if kind == "All Possible Building Upgrades Complete":
            owner = int(args.get("player", player))
            _spells, tech = self._mission_sample_progression()
            if tech is None:
                return "No"
            rows = self._mission132_parse_int_list(args.get("upgrade_rows", "")) or sorted({int(v) for v in UPGRADE_ROWS.values()})
            max_level = max(1, int(args.get("max_level", 2)))
            return "Yes" if all((row*16+owner) < len(tech) and int(tech[row*16+owner]) >= max_level for row in rows) else "No"
        if kind == "Campaign Map Visible":
            return "Yes" if self._mission132_campaign_map.get("visible") else "No"
        if kind == "Camera Zoom State":
            return float(self._mission132_zoom_state)
        return super().massive_value(kind, args, player)

    # -------------------------------------------------------------------- actions
    def massive_action(self, kind: str, args: dict[str, Any], player: int) -> bool:
        # reference module-shaped local targeting surface.
        if kind == "Configure Local Input Mapping":
            for key in self._mission132_input_map:
                if key in args:
                    self._mission132_input_map[key] = float(args[key])
            self.log("LOCAL INPUT MAPPING v1.32: " + ", ".join(f"{k}={v}" for k,v in self._mission132_input_map.items()))
            return True
        if kind == "Begin Target Selection":
            self._mission132_target.update({"active": True, "selected": False, "x": -1, "y": -1, "unit_address": 0, "unit_type": -1, "unit_owner": -1, "prompt": str(args.get("prompt", "Select a target")), "kind": str(args.get("target_kind", "Any"))})
            if bool(args.get("show_prompt", True)):
                self._game_message({"text": str(args.get("prompt", "Select a target")), "color": str(args.get("color", "White — native highlight")), "recipients": str(args.get("recipients", "All active players")), "seconds": max(1, int(args.get("seconds", 5))), "also_log": False}, player)
            return True
        if kind == "Cancel Target Selection":
            self._mission132_target["active"] = False; self._mission132_target["selected"] = False
            return True
        if kind == "Wait For Target":
            state = self._cached_action_value("mission132_wait_target", lambda: {"started": time.monotonic()})
            if self._mission132_target.get("selected"):
                if bool(args.get("close_mode", True)):
                    self._mission132_target["active"] = False
                return True
            timeout = max(0.0, float(args.get("timeout", 0.0)))
            if timeout and time.monotonic() - float(state["started"]) >= timeout:
                if str(args.get("on_timeout", "Continue")) == "Error":
                    raise RuntimeError("Wait For Target timed out")
                return True
            raise ActionDeferred("Waiting for local target selection", retry_after=0.05)
        if kind == "Store Selected Target":
            if not self._mission132_target.get("selected"):
                raise RuntimeError("No target has been selected")
            xv = str(args.get("x_variable", "TargetX")).strip(); yv = str(args.get("y_variable", "TargetY")).strip()
            if xv: self.variables[xv] = int(self._mission132_target["x"])
            if yv: self.variables[yv] = int(self._mission132_target["y"])
            ref = str(args.get("unit_reference", "")).strip()
            target = self._mission132_target_unit()
            if ref and target is not None:
                self._save_reference(ref, target)
            return True
        if kind == "Show Targeting Prompt":
            self._game_message({"text": str(args.get("text", "Select a target")), "color": str(args.get("color", "White — native highlight")), "recipients": str(args.get("recipients", "All active players")), "seconds": max(1, int(args.get("seconds", 5))), "also_log": bool(args.get("also_log", False))}, player)
            return True

        # reference module-shaped building-placement surface.
        if kind == "Begin Building Placement":
            self._mission132_placement.update({"active": True, "building_type": int(args.get("building", args.get("new_building", 58))), "owner": int(args.get("player", player)), "valid": False, "candidate": None, "placed": False, "complete": bool(args.get("complete", False))})
            self._mission132_target.update({"active": True, "selected": False, "prompt": str(args.get("prompt", "Choose a building location")), "kind": "Building placement"})
            if bool(args.get("show_prompt", True)):
                self._game_message({"text": str(args.get("prompt", "Choose a building location")), "color": "White — native highlight", "recipients": "All active players", "seconds": 5, "also_log": False}, player)
            return True
        if kind == "Cancel Placement":
            self._mission132_placement.update({"active": False, "valid": False, "candidate": None})
            if self._mission132_target.get("kind") == "Building placement": self._mission132_target["active"] = False
            return True
        if kind == "Wait For Placement":
            state = self._cached_action_value("mission132_wait_placement", lambda: {"started": time.monotonic(), "attempted": False})
            candidate = self._mission132_placement.get("candidate")
            if candidate is not None and self._mission132_placement.get("valid") and not state["attempted"]:
                state["attempted"] = True
                owner = int(self._mission132_placement.get("owner", player)); btype = int(self._mission132_placement.get("building_type", 58))
                before = {int(u.address) for u in self.units()}
                super().massive_action("Source Place Building Foundation", {"player": owner, "new_building": btype, "count": 1, "location": "Anywhere", "x": int(candidate[0]), "y": int(candidate[1])}, owner)
                created = [u for u in self.units() if int(u.address) not in before and int(u.owner) == owner and int(u.unit_type) == btype]
                if created:
                    if self._mission132_placement.get("complete"):
                        try:
                            self.action("Complete Buildings", {"player": owner, "unit": btype, "location": "Anywhere", "x": int(candidate[0]), "y": int(candidate[1])}, owner)
                        except Exception:
                            pass
                    self._mission132_placement.update({"placed": True, "placed_serial": int(self._mission132_placement.get("placed_serial", 0)) + 1, "active": False})
                    self._mission132_target["active"] = False
                    return True
                state["attempted"] = False
                self._mission132_placement["valid"] = False
            timeout = max(0.0, float(args.get("timeout", 0.0)))
            if timeout and time.monotonic() - float(state["started"]) >= timeout:
                if str(args.get("on_timeout", "Continue")) == "Error": raise RuntimeError("Wait For Placement timed out")
                return True
            raise ActionDeferred("Waiting for building placement click", retry_after=0.05)

        # Trigger-owned custom command buttons. Exact Remastered statbtn C++ card
        # mutation is still a separate ABI research item; these buttons use local
        # hotkeys and can launch target mode safely today.
        if kind in {"Create Command Button", "Replace Button"}:
            bid = str(args.get("button_id", "Button")).strip() or "Button"
            current = dict(self._mission132_custom_buttons.get(bid, {})) if kind == "Replace Button" else {}
            current.update({
                "id": bid, "label": str(args.get("label", bid)), "icon": str(args.get("icon", current.get("icon", ""))),
                "tooltip": str(args.get("tooltip", current.get("tooltip", ""))), "hotkey": str(args.get("hotkey", current.get("hotkey", ""))),
                "enabled": bool(args.get("enabled", current.get("enabled", True))), "target_mode": bool(args.get("target_mode", current.get("target_mode", False))),
                "prompt": str(args.get("prompt", current.get("prompt", "Select a target"))),
            })
            self._mission132_custom_buttons[bid] = current
            return True
        if kind == "Remove Button":
            self._mission132_custom_buttons.pop(str(args.get("button_id", "Button")), None); return True
        if kind in {"Enable Button", "Disable Button", "Set Button Icon", "Set Tooltip", "Set Hotkey"}:
            bid = str(args.get("button_id", "Button")); button = self._mission132_custom_buttons.setdefault(bid, {"id": bid, "label": bid, "enabled": True})
            if kind == "Enable Button": button["enabled"] = True
            elif kind == "Disable Button": button["enabled"] = False
            elif kind == "Set Button Icon": button["icon"] = str(args.get("icon", ""))
            elif kind == "Set Tooltip": button["tooltip"] = str(args.get("tooltip", ""))
            elif kind == "Set Hotkey": button["hotkey"] = str(args.get("hotkey", ""))
            return True
        if kind == "Button Starts Target Mode":
            bid = str(args.get("button_id", "Button")); button = self._mission132_button(bid)
            prompt = str(args.get("prompt", button.get("prompt", "Select a target") if button else "Select a target"))
            return self.massive_action("Begin Target Selection", {"prompt": prompt, "target_kind": str(args.get("target_kind", "Any")), "show_prompt": True}, player)
        if kind == "Show Custom Command Card":
            enabled = [b for b in self._mission132_custom_buttons.values() if b.get("enabled", True)]
            lines = [str(args.get("title", "CUSTOM COMMANDS"))]
            for b in enabled:
                hk = str(b.get("hotkey", "")); lines.append(f"[{hk}] {b.get('label', b.get('id'))}" if hk else str(b.get("label", b.get("id"))))
            self._game_message({"text": "\n".join(lines), "color": str(args.get("color", "White — native highlight")), "recipients": str(args.get("recipients", "All active players")), "seconds": max(1, int(args.get("seconds", 8))), "also_log": False}, player)
            return True

        # legacy bldg auto-build/auto-upgrade equivalents using verified production.
        if kind in {"Enable Auto Production", "Set Auto Build List", "Enable Auto Upgrade", "Pause Auto Build"}:
            actor = str(args.get("actor", "Building")); state = self._mission132_auto_build.setdefault(actor, {"enabled": False, "paused": False, "items": [], "index": 0, "order": BUILD_UNIT, "loop": True, "waiting": False})
            if kind == "Set Auto Build List":
                state["items"] = self._mission132_parse_int_list(args.get("items", args.get("unit_list", ""))); state["index"] = 0
            elif kind == "Enable Auto Production":
                if args.get("items") or args.get("unit_list"): state["items"] = self._mission132_parse_int_list(args.get("items", args.get("unit_list", "")))
                state.update({"enabled": bool(args.get("enabled", True)), "paused": False, "order": BUILD_UNIT, "loop": bool(args.get("loop", True))})
            elif kind == "Enable Auto Upgrade":
                if args.get("items") or args.get("upgrades"): state["items"] = self._mission132_parse_int_list(args.get("items", args.get("upgrades", "")))
                state.update({"enabled": bool(args.get("enabled", True)), "paused": False, "order": BUILD_TECH, "loop": bool(args.get("loop", False))})
            else:
                state["paused"] = bool(args.get("paused", True))
            return True

        # Atomic source-shaped purchases/refunds.
        if kind in {"Pay Unit Cost", "Refund Unit Cost", "Try Purchase"}:
            owner = int(args.get("player", player)); unit_type = int(args.get("unit", args.get("new_unit", 0))); costs = self._mission132_unit_cost(unit_type)
            refund = kind == "Refund Unit Cost"
            ok = self._mission132_apply_cost(owner, costs, refund=refund, fraction=float(args.get("fraction", 1.0)))
            if not ok:
                if kind == "Try Purchase":
                    var = str(args.get("result_variable", "PurchaseOK")).strip()
                    if var: self.variables[var] = 0
                    return True
                raise RuntimeError(f"P{owner+1} cannot afford unit {unit_type}: costs Gold/Lumber/Oil={costs}")
            if kind == "Try Purchase":
                var = str(args.get("result_variable", "PurchaseOK")).strip()
                if var: self.variables[var] = 1
            return True
        if kind == "Pay Upgrade Cost":
            owner = int(args.get("player", player)); gold = max(0, int(args.get("gold", 0))); lumber = max(0, int(args.get("lumber", 0))); oil = max(0, int(args.get("oil", 0)))
            if gold == lumber == oil == 0:
                row = int(args.get("upgrade_id", UPGRADE_ROWS.get(str(args.get("upgrade", "Melee Attack")), 0)))
                gold = max(0, int(self._source128_upgrade_rules.get(("Cost", row), 0)))
            if not self._mission132_apply_cost(owner, (gold, lumber, oil), refund=False):
                raise RuntimeError(f"P{owner+1} cannot afford upgrade cost Gold/Lumber/Oil={(gold,lumber,oil)}")
            return True

        # Animation sequencing from reference module::unit_force_seq semantics, safely using
        # the same verified animation fields already exposed by Scene Actor Play Animation.
        if kind in {"Loop Animation", "Stop Animation At Frame", "Play Death Sequence Only", "Play Attack Sequence Only", "Play Cast Sequence Only", "Unit Fidget/Idle Animation"}:
            actor_name = str(args.get("actor", "Actor")); actor = self._campaign_actor(actor_name)
            # legacy reference module sequence enum: DEAD=0, DIE=1, STOP=2, MOVE=3,
            # ATTACK=4, BUILD=5, ENTER_SHORE=6. Spell actions map to USEQ_ATTACK
            # in reference module, so authored cast-only animation uses sequence 4.
            seq_defaults = {"Play Death Sequence Only": 1, "Play Attack Sequence Only": 4, "Play Cast Sequence Only": 4, "Unit Fidget/Idle Animation": 2}
            animation = int(args.get("animation", seq_defaults.get(kind, 0))) & 0xFF
            frame = int(args.get("frame", 0)) & 0xFF
            timer = max(1, int(args.get("timer", 1))) & 0xFF
            self._dispatch_ops([("write_byte", actor.address+0x08, animation), ("write_byte", actor.address+0x09, frame), ("write_byte", actor.address+0x07, timer)])
            if kind == "Loop Animation":
                self._mission132_animation_loops[actor_name] = {"animation": animation, "timer": timer, "hold_frame": None}
            elif kind == "Stop Animation At Frame":
                self._mission132_animation_loops[actor_name] = {"animation": animation, "timer": timer, "hold_frame": frame}
            return True
        if kind == "Scene Wait For Animation":
            actor = self._campaign_actor(args.get("actor", "Actor")); wanted = int(args.get("animation", -1)); timeout = max(0.0, float(args.get("timeout", 0.0)))
            state = self._cached_action_value("mission132_wait_animation", lambda: {"started": time.monotonic(), "seen": False})
            current = int(self.pm.read_uchar(actor.address + 0x08)); timer = int(self.pm.read_uchar(actor.address + 0x07))
            if wanted < 0 or current == wanted: state["seen"] = True
            if state["seen"] and timer == 0: return True
            if timeout and time.monotonic()-float(state["started"]) >= timeout:
                if str(args.get("on_timeout", "Continue")) == "Error": raise RuntimeError("Scene Wait For Animation timed out")
                return True
            raise ActionDeferred("Waiting for scene animation", retry_after=0.05)
        if kind == "Stop Animation Loop":
            self._mission132_animation_loops.pop(str(args.get("actor", "Actor")), None); return True

        # Combat helpers from reference module/reference module semantics.
        if kind in {"Deal Native Area Damage", "Native Splash Attack", "Damage Units Around Point"}:
            if kind == "Native Splash Attack":
                attacker = self._campaign_actor(args.get("actor", "Actor")); x, y = int(attacker.target_x), int(attacker.target_y)
            else:
                attacker = self._campaign_actor(args.get("actor", "Actor"), required=False)
                x, y = self._mission132_point(args)
            radius = max(0, int(args.get("radius", 2))); explicit = max(0, int(args.get("damage", 0))); hit = 0
            for target in list(self.units()):
                if int(target.sflags) & SF_HIDDEN or max(abs(int(target.x)-x), abs(int(target.y)-y)) > radius:
                    continue
                if attacker is not None and int(target.owner) == int(attacker.owner) and not bool(args.get("friendly_fire", False)):
                    continue
                amount = explicit
                if amount <= 0 and attacker is not None:
                    amount = max(1, int(self._source128_native_damage(attacker, target, True)))
                if amount > 0:
                    self._call_damage_unit(attacker or target, target, amount); hit += 1
            self.log(f"AREA DAMAGE v1.32: {kind} hit {hit} unit(s) around ({x},{y}) radius {radius}")
            return True

        # Local sound/music authoring. Warcraft-native music remains unverified;
        # aliases reuse the existing fail-closed/state-backed scene music layer.
        if kind == "Play Music":
            return super().massive_action("Scene Set Music (Experimental)", {"track": args.get("track", ""), "volume": args.get("volume", 100), "fallback_to_state_only": True}, player)
        if kind == "Crossfade Music":
            self._mission_music_state["track"] = str(args.get("track", self._mission_music_state.get("track", "")))
            return super().massive_action("Scene Fade Music (Experimental)", {"to_volume": args.get("to_volume", 100), "seconds": args.get("seconds", 1.0), "fallback_to_state_only": True}, player)
        if kind == "Set Music Volume":
            self._mission_music_state["volume"] = max(0, min(100, int(args.get("volume", 100)))); return True
        if kind == "Set SFX Volume":
            # Remastered's global SFX stream ABI is not yet verified. Keep a
            # deterministic authored value and do not poke a guessed global.
            self.variables["LocalSFXVolume"] = max(0, min(100, int(args.get("volume", 100)))); return True
        if kind == "Loop Sound":
            self._mission132_sound_looping = True; self._mission132_sound_file = str(args.get("file", args.get("sound", ""))); self._mission132_sound_started = time.monotonic()
            actor = str(args.get("actor", "")).strip()
            if actor:
                super().massive_action("Scene Actor Voice", {"actor": actor, "event": args.get("event", "Selection"), "estimated_seconds": args.get("estimated_seconds", 1.5)}, player)
            return True
        if kind == "Stop Sound":
            self._mission132_sound_looping = False; self._mission132_sound_file = ""; self._mission_audio_until = min(self._mission_audio_until, time.monotonic()); return True
        if kind == "Wait Until Sound Finished":
            if self._mission132_sound_looping:
                raise ActionDeferred("Looping sound still active", retry_after=0.10)
            return super().massive_action("Scene Wait For Audio", {"seconds": args.get("seconds", 0.0)}, player)

        # Mission stats/result authoring from reference module semantics.
        if kind == "Set Mission Rank":
            self._mission132_result_state["rank"] = str(args.get("rank", "Commander")); return True
        if kind == "Set Bonus Score":
            self._mission132_result_state["bonus"] = int(args.get("score", args.get("amount", 0))); return True
        if kind == "Set Mission Time":
            self._mission132_result_state["mission_time"] = max(0.0, float(args.get("seconds", 0.0))); return True
        if kind in {"Show Mission Results", "Show Victory Statistics"}:
            elapsed = float(self._mission132_result_state.get("mission_time", 0.0)) or float(getattr(self, "elapsed_seconds", 0.0) or 0.0)
            rank = str(self._mission132_result_state.get("rank", "")) or str(args.get("rank", "Commander")); bonus = int(self._mission132_result_state.get("bonus", 0))
            text = str(args.get("title", "MISSION RESULTS")) + f"\nRank: {rank}\nBonus: {bonus}\nTime: {int(elapsed//60)}:{int(elapsed%60):02d}"
            self._game_message({"text": text, "color": str(args.get("color", "Yellow / gold — native normal")), "recipients": str(args.get("recipients", "All active players")), "seconds": max(2, int(args.get("seconds", 10))), "also_log": True}, player)
            if bool(args.get("victory", False)):
                self.action("Victory", {}, player)
            return True

        # Camera zoom source lead: Remastered native gamemap_shrink/expand ABI is
        # still unbound, so keep exact authored zoom state and fail closed on request.
        if kind in {"Scene Camera Zoom In", "Scene Camera Zoom Out"}:
            step = max(0.01, float(args.get("step", 0.10)))
            self._mission132_zoom_state = max(0.25, min(4.0, self._mission132_zoom_state + (step if kind.endswith("In") else -step)))
            if not bool(args.get("fallback_to_state_only", True)):
                raise RuntimeError(f"{kind}: Remastered gamemap_shrink/expand ABI is not verified; failed closed")
            self.log(f"CAMERA ZOOM v1.32: authored zoom={self._mission132_zoom_state:.2f}; native renderer zoom remains experimental")
            return True

        # Campaign-map interlude authoring using safe in-game presentation/minimap markers.
        if kind == "Show Campaign Map":
            self._mission132_campaign_map.update({"visible": True, "title": str(args.get("title", "CAMPAIGN MAP"))})
            self._game_message({"text": str(args.get("title", "CAMPAIGN MAP")), "color": str(args.get("color", "White — native highlight")), "recipients": str(args.get("recipients", "All active players")), "seconds": max(1, int(args.get("seconds", 5))), "also_log": False}, player)
            return True
        if kind == "Add Campaign Dot":
            x, y = self._mission132_point(args); label = str(args.get("label", "Objective")); self._mission132_campaign_map.setdefault("dots", []).append({"x": x, "y": y, "label": label})
            super().massive_action("Source Show Minimap Marker", {"location": "Anywhere", "x": x, "y": y, "duration": float(args.get("duration", 0.0))}, player)
            return True
        if kind == "Draw Campaign Route":
            points: list[tuple[int,int]] = []
            for name in str(args.get("locations", "")).replace(";", ",").split(","):
                name = name.strip()
                if not name: continue
                loc = self._find_location(name); points.append(((int(loc.left)+int(loc.right))//2, (int(loc.top)+int(loc.bottom))//2))
            self._mission132_campaign_map.setdefault("routes", []).append(points)
            for x,y in points: super().massive_action("Source Show Minimap Marker", {"location":"Anywhere","x":x,"y":y,"duration":float(args.get("duration",0.0))}, player)
            return True
        if kind == "Pulse Campaign Location":
            x, y = self._mission132_point(args); pulses = max(1, int(args.get("pulses", 3))); state = self._cached_action_value("mission132_campaign_pulse", lambda: {"next": time.monotonic(), "done": 0})
            now = time.monotonic()
            if state["done"] < pulses and now >= state["next"]:
                super().massive_action("Source Show Minimap Marker", {"location":"Anywhere","x":x,"y":y,"duration":float(args.get("interval",0.5))}, player)
                state["done"] += 1; state["next"] = now + max(0.1, float(args.get("interval",0.5)))
            if state["done"] < pulses: raise ActionDeferred("Pulsing campaign location", retry_after=0.05)
            return True
        if kind == "Hide Campaign Map":
            self._mission132_campaign_map["visible"] = False; super().massive_action("Source Clear Minimap Markers", {}, player); return True

        # Small source-shaped helpers.
        if kind == "Clear Current Game Message":
            self._game_message({"text": " ", "color": "White — native highlight", "recipients": str(args.get("recipients", "All active players")), "seconds": 1, "also_log": False}, player); return True
        if kind == "Cursor Set":
            self._mission132_cursor_state.update({"cursor": str(args.get("cursor", "Target")), "visible": True}); return True
        if kind == "Cursor Hide":
            self._mission132_cursor_state["visible"] = False; return True
        if kind == "Cursor Restore":
            self._mission132_cursor_state = {"visible": True, "cursor": "Default"}; return True
        if kind == "Show Native Cost/Mana Prompt":
            unit_type = int(args.get("unit", args.get("new_unit", 0))); gold,lumber,oil = self._mission132_unit_cost(unit_type); mana = int(args.get("mana", 0)); text = str(args.get("prefix", "Cost")) + f": {gold} gold / {lumber} lumber / {oil} oil" + (f" / {mana} mana" if mana else "")
            self._game_message({"text": text, "color": str(args.get("color", "White — native highlight")), "recipients": str(args.get("recipients", "All active players")), "seconds": max(1, int(args.get("seconds", 4))), "also_log": False}, player); return True

        # 1.35 promotes the native Scenario Objectives path from experimental:
        # CampaignFeatureMixin now validates the Remastered objective screen hook,
        # stages game-allocator-owned std::strings, and opens Warcraft's real screen.
        if kind in {"Show Native Objectives", "Open Scenario Objectives"}:
            return super().massive_action(kind, args, player)

        # Friendly aliases for the remaining fail-closed modern front-end actions.
        native_alias = {
            "Show Native Objectives": "Show Native Objectives HUD (Experimental)",
            "Open Scenario Objectives": "Open Native Scenario Objectives (Experimental)",
            "Show Native Briefing": "Show Native Mission Briefing (Experimental)",
            "Native Portrait Transmission": "Native Portrait Transmission (Experimental)",
            "Show Native Interlude": "Native Campaign Interlude (Experimental)",
            "Play Native FMV": "Play Cinematic Movie (Experimental)",
            "Save Native Campaign State": "Native Save Extension (Experimental)",
            "Scene Native Fade In": "Scene Fade In (Experimental)",
            "Scene Native Fade Out": "Scene Fade Out (Experimental)",
        }
        if kind in native_alias:
            return super().massive_action(native_alias[kind], args, player)

        return super().massive_action(kind, args, player)
