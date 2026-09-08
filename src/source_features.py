from __future__ import annotations

from typing import Any

from advanced_features import AdvancedFeatureMixin
from ultimate_features import SPELL_BITS, UPGRADE_ROWS


# Warcraft II source order values.
ORDER_GUARD = 2
ORDER_MOVE = 3
ORDER_PATROL = 5
ORDER_FOLLOW = 6
ORDER_ATTACK_TARGET = 9
ORDER_ATTACK_AREA = 10
ORDER_ATTACK_WALL = 11
ORDER_STAND = 13
ORDER_STAND_ATTACK = 14
ORDER_ATTACK_GROUND = 17
ORDER_DEMOLISH = 19
ORDER_HARVEST = 23
ORDER_RETURN = 24
ORDER_REPAIR = 27
ORDER_UNLOAD_ALL = 29
ORDER_WAIT = 32
ORDER_BLDG_WAIT = 33
ORDER_BLDG_BUILD = 37
ORDER_NONE = 60

UF_BUILD_ON = 0x0010
UF_BUILD_CANCEL = 0x0020
SF_HIDDEN = 0x0008
PEON_HARVEST_GOLD = 0x80
PEON_HARVEST_LUMBER = 0x40
PEON_LOADED = 0x20
MAX_TRANSPORT_CARGO = 6
EMPTY_CARGO_SLOT = 0xFFFF
MTXM_DATA_OFFSET = 0xB4

BUILD_UNIT = 0
BUILD_TECH = 1
BUILD_SPELL = 2
BUILD_UPGRADE = 3

SOURCE_NATIVE_SPECS: dict[str, tuple[int, bytes]] = {
    "do_guard": (0x000D8580, b"\x55\x8B\xEC\x51\x53\x56\x8B\x75\x08"),
    "do_follow": (0x000D8560, b"\x55\x8B\xEC\x6A\x06\xFF\x75\x08"),
    "do_attack_area": (0x000D82E0, b"\x55\x8B\xEC\x6A\x0A\xFF\x75\x08"),
    "do_attack_ground": (0x000D8300, b"\x55\x8B\xEC\x56\x8B\x75\x08\x56"),
    "do_attack_ground_only": (0x000D8370, b"\x55\x8B\xEC\x6A\x11\xFF\x75\x08"),
    "do_attack_target": (0x000D8390, b"\x55\x8B\xEC\x8B\x4D\x08\xBA\x02"),
    "do_attack_wall": (0x000D83C0, b"\x55\x8B\xEC\x56\x8B\x75\x08\x6A\x0C"),
    "do_defend": (0x000D84B0, b"\x55\x8B\xEC\x6A\x0C\xFF\x75\x08"),
    "do_defend_ground": (0x000D84D0, b"\x55\x8B\xEC\x6A\x0F\xFF\x75\x08"),
    "do_defend_stopped": (0x000D84F0, b"\x55\x8B\xEC\x6A\x10\xFF\x75\x08"),
    "do_demolish": (0x000D8510, b"\x55\x8B\xEC\x56\x8B\x75\x08\x83\xBE\x88"),
    "do_harvest": (0x000D85E0, b"\x55\x8B\xEC\x56\x8B\x75\x08\x0F\xB6\x4E\x27"),
    "do_patrol_move": (0x000D88F0, b"\x55\x8B\xEC\x56\x8B\x75\x08\x0F\xB6\x46\x27"),
    "do_repair": (0x000D8920, b"\x55\x8B\xEC\x8B\x4D\x08\x8B\x81\x88"),
    "do_return": (0x000D8960, b"\x55\x8B\xEC\x51\x56\x8B\x75\x08\xC6\x45\xFC"),
    "do_stand_attack": (0x000D89C0, b"\x55\x8B\xEC\x6A\x0E\xFF\x75\x08"),
    "do_stand_ground": (0x000D89E0, b"\x55\x8B\xEC\x6A\x0D\xFF\x75\x08"),
    "do_unload_all": (0x000D8A00, b"\x55\x8B\xEC\x56\x8B\x75\x08\x6A\x02"),
    "unit_load_transport": (0x000EE600, b"\x55\x8B\xEC\x56\x8B\x75\x08\x57\x8B\xBE\x88"),
    "unit_unload_transport": (0x000EE820, b"\x55\x8B\xEC\x83\xEC\x0C\x53\x8B\x5D\x08"),
    "bldg_build_start": (0x000ACE10, b"\x55\x8B\xEC\x81\xEC\xCC\x00\x00\x00"),
    "bldg_dispatch_build": (0x000AD250, b"\x55\x8B\xEC\x53\x56\x8B\x75\x08\x57"),
    "gamesnd_explode": (0x000C7B70, b"\x55\x8B\xEC\x66\x8B\x45\x08\x66\x89\x45\x08"),
    "gamesnd_harvest": (0x000C7BA0, b"\x55\x8B\xEC\xE8\x08\x86\x02\x00\xC1\xF8\x08"),
    "gamesnd_kill_bldg": (0x000C7BD0, b"\x55\x8B\xEC\xE8\xD8\x85\x02\x00\xC1\xF8\x08"),
    "gamesnd_kill_man": (0x000C7C00, b"\x55\x8B\xEC\x8B\x55\x08\x8A\x4A\x27"),
    "gamesnd_select": (0x000C7FE0, b"\x55\x8B\xEC\x56\x8B\x75\x08\x85\xF6"),
    "gamesnd_spell": (0x000C82B0, b"\x55\x8B\xEC\x8B\x45\x08\x6A\x01\x6A\x01"),
    "gamesnd_under_attack": (0x000C8370, b"\x55\x8B\xEC\x83\xEC\x08\x80\x3D"),
}

SOURCE_ORDER_ACTIONS: dict[str, tuple[str, set[int], str]] = {
    "Source Guard": ("do_guard", {ORDER_GUARD, ORDER_WAIT}, "self"),
    "Source Follow": ("do_follow", {ORDER_FOLLOW}, "unit"),
    "Source Attack Target": ("do_attack_target", {ORDER_ATTACK_TARGET, ORDER_GUARD}, "unit"),
    "Source Attack Area": ("do_attack_area", {ORDER_ATTACK_AREA}, "point"),
    "Source Attack Ground": ("do_attack_ground", {ORDER_ATTACK_GROUND, 18}, "point"),
    "Source Attack Wall": ("do_attack_wall", {ORDER_ATTACK_WALL, ORDER_GUARD}, "point"),
    "Source Defend": ("do_defend", {12}, "self"),
    "Source Defend Ground": ("do_defend_ground", {15}, "self"),
    "Source Defend Stopped": ("do_defend_stopped", {16}, "self"),
    "Source Stand Attack": ("do_stand_attack", {ORDER_STAND_ATTACK}, "self"),
    "Source Stand Ground": ("do_stand_ground", {ORDER_STAND}, "self"),
    "Source Patrol Move": ("do_patrol_move", {4, ORDER_MOVE}, "point"),
    "Source Demolish": ("do_demolish", {20, 21}, "optional_unit"),
    "Source Harvest": ("do_harvest", {ORDER_HARVEST}, "optional_unit"),
    "Source Repair": ("do_repair", {ORDER_REPAIR, ORDER_MOVE}, "unit"),
    "Source Return Resources": ("do_return", {ORDER_RETURN, ORDER_GUARD}, "self"),
    "Source Unload All": ("do_unload_all", {ORDER_UNLOAD_ALL, ORDER_MOVE, ORDER_WAIT}, "point"),
}

PRODUCTION_STATE_NAMES = {
    BUILD_UNIT: "Training Unit",
    BUILD_TECH: "Researching Technology",
    BUILD_SPELL: "Researching Spell",
    BUILD_UPGRADE: "Upgrading Building",
}


class SourceFeatureMixin(AdvancedFeatureMixin):
    """1.27 source-code systems layered over the validated live runtime."""

    def _init_massive_features(self) -> None:
        super()._init_massive_features()
        self.source_native_paths: dict[str, int] = {}
        self._source_frozen_animations: dict[tuple[int, int], tuple[int, int, int]] = {}
        self._source_last_found_point: tuple[int, int] | None = None

    def _massive_begin_run(self) -> None:
        super()._massive_begin_run()
        self._source_frozen_animations.clear()
        self._source_last_found_point = None

    def _resolve_source_native_paths(self) -> dict[str, int]:
        resolved: dict[str, int] = {}
        for name, (rva, prefix) in SOURCE_NATIVE_SPECS.items():
            address = self.base + rva
            actual = self.pm.read_bytes(address, len(prefix))
            if actual != prefix:
                raise RuntimeError(
                    f"Source native path {name} failed validation at RVA 0x{rva:X}: "
                    f"expected {prefix.hex(' ')}, read {actual.hex(' ')}"
                )
            resolved[name] = address
        return resolved

    def _massive_prepare_events(self, current: dict[tuple[int, int], Any], previous: dict[tuple[int, int], Any]) -> None:
        super()._massive_prepare_events(current, previous)
        stale: list[tuple[int, int]] = []
        for key, (action, frame, facing) in self._source_frozen_animations.items():
            unit = current.get(key)
            if unit is None:
                stale.append(key)
                continue
            # Freeze only sequence fields; leave orders, HP, targeting, and flags alone.
            try:
                self.pm.write_uchar(unit.address + 0x07, 0)
                self.pm.write_uchar(unit.address + 0x08, action & 0xFF)
                self.pm.write_uchar(unit.address + 0x09, frame & 0xFF)
                self.pm.write_uchar(unit.address + 0x0A, facing & 7)
                self.pm.write_uchar(unit.address + 0x06, self.pm.read_uchar(unit.address + 0x06) | 0x20)
            except Exception:
                stale.append(key)
        for key in stale:
            self._source_frozen_animations.pop(key, None)

    # ------------------------------------------------------------------ helpers
    def _source_amount(self, args: dict[str, Any], count: int) -> int:
        raw = args.get("amount", "All")
        if raw == "All" or raw is None or raw == "":
            return count
        return max(0, min(count, int(raw)))

    def _source_units(self, args: dict[str, Any], player: int) -> list[Any]:
        units = self._selected_units(args, player)
        # Condition schemas use "amount" as the comparison value, while source
        # action schemas use it as the maximum selection count. Never let an
        # expected condition value of zero hide the unit being inspected.
        if "comparison" in args:
            return units
        return units[: self._source_amount(args, len(units))]

    def _source_target_args(self, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "player": int(args.get("target_player", 1)),
            "unit": args.get("target_unit", "Any"),
            "location": args.get("target_location", "Anywhere"),
        }

    def _source_target_units(self, args: dict[str, Any], player: int) -> list[Any]:
        return self._selected_units(self._source_target_args(args), player)

    @staticmethod
    def _source_nearest(unit: Any, candidates: list[Any]) -> Any | None:
        candidates = [candidate for candidate in candidates if candidate.address != unit.address]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda candidate: (
                (int(candidate.x) - int(unit.x)) ** 2 + (int(candidate.y) - int(unit.y)) ** 2,
                int(candidate.address),
            ),
        )

    def _source_point(self, args: dict[str, Any], label: str) -> tuple[int, int]:
        local = dict(args)
        if "destination" not in local:
            local["destination"] = local.get("target_location", local.get("location", "Anywhere"))
        if "x" not in local and "target_x" in local:
            local["x"] = local["target_x"]
        if "y" not in local and "target_y" in local:
            local["y"] = local["target_y"]
        return self._tile_destination(local, label)

    def _source_unit_key(self, unit: Any) -> tuple[int, int]:
        return self._unit_key_massive(unit) if hasattr(self, "_unit_key_massive") else self._unit_key(unit)

    def _source_refresh_unit(self, unit: Any) -> Any | None:
        try:
            data = self.pm.read_bytes(unit.address, 152)
        except Exception:
            return None
        if not self._record_is_allocated(data):
            return None
        return self._decode_unit(unit.address, data)

    def _source_order(self, kind: str, args: dict[str, Any], player: int) -> int:
        callback_name, expected, mode = SOURCE_ORDER_ACTIONS[kind]
        units = [u for u in self._source_units(args, player) if int(u.unit_type) < 58 and not (int(u.sflags) & SF_HIDDEN)]
        wants_optional_target = mode == "optional_unit" and bool(args.get("use_target_unit", False))
        targets = self._source_target_units(args, player) if mode == "unit" or wants_optional_target else []
        point = self._source_point(args, kind) if mode in {"point", "optional_unit"} else None
        calls: list[tuple[int, list[int]]] = []
        assignments: list[tuple[Any, Any | None, int, int]] = []
        for unit in units:
            target = self._source_nearest(unit, targets) if targets else None
            if mode == "unit" and target is None:
                continue
            if target is not None:
                x, y, pointer = int(target.x), int(target.y), int(target.address)
            elif point is not None:
                x, y, pointer = int(point[0]), int(point[1]), 0
            else:
                x, y, pointer = int(unit.x), int(unit.y), 0
            if not (0 <= x < self.map_width and 0 <= y < self.map_height):
                continue
            calls.append((self.order_callees["set_target"], [unit.address, x, y, pointer, self.source_native_paths[callback_name]]))
            assignments.append((unit, target, x, y))
        if calls:
            self._call_cdecl_batched(calls)
        accepted = 0
        for unit, target, x, y in assignments:
            current = self._source_refresh_unit(unit)
            if current is None:
                continue
            if int(current.action) in expected or int(current.next_action) in expected:
                accepted += 1
                self._issued_orders[self._unit_key(current)] = (kind, x, y, int(target.address) if target else 0)
        self.log(f"SOURCE ORDER: {kind} accepted by {accepted}/{len(assignments)} unit(s)")
        return accepted

    def _source_transport_slots(self, transport: Any) -> list[int]:
        return [self.pm.read_ushort(transport.address + 0x70 + slot * 2) for slot in range(MAX_TRANSPORT_CARGO)]

    def _source_transport_unit(self, slot_value: int) -> Any | None:
        if slot_value == EMPTY_CARGO_SLOT or not 0 <= slot_value < self.max_units:
            return None
        address = self.unit_pool + slot_value * 152
        try:
            data = self.pm.read_bytes(address, 152)
        except Exception:
            return None
        if not self._record_is_allocated(data):
            return None
        return self._decode_unit(address, data)

    def _source_find_transport_for(self, unit: Any) -> Any | None:
        slot = (int(unit.address) - int(self.unit_pool)) // 152
        for transport in self.units():
            if int(transport.unit_type) not in {28, 29}:
                continue
            if slot in self._source_transport_slots(transport):
                return transport
        return None

    def _source_production_state(self, building: Any) -> str:
        flags = self.pm.read_ushort(building.address + 0x1C)
        if not flags & UF_BUILD_ON:
            return "Idle"
        order = self.pm.read_uchar(building.address + 0x6C)
        return PRODUCTION_STATE_NAMES.get(order, f"Unknown {order}")

    def _source_start_production(self, args: dict[str, Any], player: int, order: int, parm: int) -> int:
        buildings = [u for u in self._source_units(args, player) if int(u.unit_type) >= 58]
        started = 0
        rejected: list[str] = []
        for building in buildings:
            result = self._call_cdecl(self.source_native_paths["bldg_build_start"], [building.address, parm & 0xFF, order & 0xFF])
            flags = self.pm.read_ushort(building.address + 0x1C)
            if result and flags & UF_BUILD_ON:
                started += 1
            else:
                rejected.append(f"slot {(building.address-self.unit_pool)//152}")
        self.log(
            f"SOURCE PRODUCTION: started {started}/{len(buildings)} operation(s), order={order}, parm={parm}"
            + (f"; rejected {', '.join(rejected[:8])}" if rejected else "")
        )
        return started

    def _source_tile_address(self, x: int, y: int) -> int:
        if not (0 <= x < self.map_width and 0 <= y < self.map_height):
            raise ValueError(f"Tile ({x},{y}) is outside the live map")
        map_object = self._read_ptr(self.base + 0x560DF4)
        if not map_object or not self._is_private_writable(map_object):
            raise RuntimeError(f"MTXM map object pointer is invalid: 0x{map_object:08X}")
        return map_object + MTXM_DATA_OFFSET + (y * self.map_width + x) * 2

    def _source_tile_region(self, args: dict[str, Any], label: str) -> tuple[int, int, int, int]:
        location_name = str(args.get("location", "Anywhere"))
        if location_name != "Anywhere":
            if not self.scenario:
                raise RuntimeError(f"{label} requires an active scenario")
            location = next((loc for loc in self.scenario.locations if loc.name == location_name), None)
            if location is None:
                raise ValueError(f"Unknown location: {location_name}")
            return int(location.left), int(location.top), int(location.right), int(location.bottom)
        x = int(args.get("x", 0)); y = int(args.get("y", 0))
        width = max(1, int(args.get("width", 1))); height = max(1, int(args.get("height", 1)))
        return x, y, min(self.map_width - 1, x + width - 1), min(self.map_height - 1, y + height - 1)

    def _source_enemy_candidates(self, unit: Any, args: dict[str, Any], player: int) -> list[Any]:
        candidates = self._source_target_units(args, player)
        if args.get("target_unit", "Any") == "Any" and args.get("target_location", "Anywhere") == "Anywhere":
            candidates = self.units()
        if not 0 <= int(unit.owner) < 8:
            return []
        row = self._read_diplomacy_state(int(unit.owner))[0]
        result = []
        for candidate in candidates:
            if candidate.address == unit.address or candidate.sflags & SF_HIDDEN:
                continue
            if not 0 <= int(candidate.owner) < 8:
                continue
            if self._relation_is_enemy(int(unit.owner), int(candidate.owner), row[int(candidate.owner)]):
                result.append(candidate)
        return result

    # ---------------------------------------------------------------- conditions
    def massive_value(self, kind: str, args: dict[str, Any], player: int) -> Any:
        if kind == "Source Production State":
            units = [unit for unit in self._source_units(args, player) if int(unit.unit_type) >= 58]
            return self._source_production_state(units[0]) if units else "Missing"
        if kind == "Source Production Progress":
            units = [unit for unit in self._source_units(args, player) if int(unit.unit_type) >= 58]
            if not units:
                return 0
            current = self.pm.read_ushort(units[0].address + 0x6E)
            total = self.pm.read_ushort(units[0].address + 0x70)
            return 0 if total <= 0 else min(100, round(current * 100 / total))
        if kind == "Source Transport Cargo Count":
            units = [unit for unit in self._source_units(args, player) if int(unit.unit_type) in {28, 29}]
            return sum(1 for value in self._source_transport_slots(units[0]) if value != EMPTY_CARGO_SLOT) if units else 0
        if kind == "Source Transport Has Space":
            units = [unit for unit in self._source_units(args, player) if int(unit.unit_type) in {28, 29}]
            return bool(units and any(value == EMPTY_CARGO_SLOT for value in self._source_transport_slots(units[0])))
        if kind == "Source Unit Is Loaded":
            units = self._source_units(args, player)
            return bool(units and self._source_find_transport_for(units[0]) is not None)
        if kind == "Source Worker Cargo Type":
            units = self._source_units(args, player)
            if not units:
                return "None"
            flags = self.pm.read_uchar(units[0].address + 0x75)
            if not flags & PEON_LOADED:
                return "None"
            if flags & PEON_HARVEST_GOLD:
                return "Gold"
            if flags & PEON_HARVEST_LUMBER:
                return "Lumber"
            return "Oil"
        if kind == "Source Worker Cargo Amount":
            units = self._source_units(args, player)
            return self.pm.read_ushort(units[0].address + 0x78) if units else 0
        if kind == "Source Resource Node Remaining":
            units = self._source_units(args, player)
            return self.pm.read_ushort(units[0].address + 0x8A) if units else 0
        if kind == "Source Tile Value":
            x, y = self._source_point(args, kind)
            return self.pm.read_ushort(self._source_tile_address(x, y))
        if kind in {"Source Tile Is Tree", "Source Tile Is Rock", "Source Tile Is Wall", "Source Tile Is Demolishable"}:
            # Exact graphic IDs vary by tileset. The condition accepts optional ID lists;
            # defaults remain conservative and can be authored from the live Tile Value.
            x, y = self._source_point(args, kind)
            tile = self.pm.read_ushort(self._source_tile_address(x, y))
            raw = str(args.get("tile_values", "")).strip()
            values = {int(part.strip(), 0) & 0xFFFF for part in raw.replace(";", ",").split(",") if part.strip()}
            return tile in values if values else False
        if kind in {"Source Location Walkable", "Source Location Buildable"}:
            units = self._source_units(args, player)
            if not units:
                return False
            x, y = self._source_point(args, kind)
            unit = units[0]
            unit_class = self.pm.read_uchar(unit.address + 0x2A)
            result = self._call_cdecl(self.move_callees["placeable"], [unit_class, x, y, int(unit.unit_type)])
            return bool(result)
        if kind == "Source Unit Has Target":
            units = self._source_units(args, player)
            return bool(units and int(units[0].target_unit))
        if kind == "Source Unit Can Attack Target":
            units = self._source_units(args, player); targets = self._source_target_units(args, player)
            if not units or not targets:
                return False
            source = units[0]; target = self._source_nearest(source, targets)
            if target is None or int(source.unit_type) >= 58:
                return False
            if 0 <= int(source.owner) < 8 and 0 <= int(target.owner) < 8:
                row = self._read_diplomacy_state(int(source.owner))[0]
                return self._relation_is_enemy(int(source.owner), int(target.owner), row[int(target.owner)])
            return True
        if kind == "Source Target In Range":
            units = self._source_units(args, player); targets = self._source_target_units(args, player)
            if not units or not targets:
                return False
            target = self._source_nearest(units[0], targets)
            if target is None:
                return 0
            distance = max(abs(int(target.x)-int(units[0].x)), abs(int(target.y)-int(units[0].y)))
            return distance
        if kind == "Source Animation Action":
            units = self._source_units(args, player)
            return self.pm.read_uchar(units[0].address + 0x08) if units else 0
        if kind == "Source Animation Frozen":
            units = self._source_units(args, player)
            return bool(units and self._source_unit_key(units[0]) in self._source_frozen_animations)
        if kind == "Source Last Found X":
            return self._source_last_found_point[0] if self._source_last_found_point else -1
        if kind == "Source Last Found Y":
            return self._source_last_found_point[1] if self._source_last_found_point else -1
        return super().massive_value(kind, args, player)

    # ------------------------------------------------------------------ actions
    def massive_action(self, kind: str, args: dict[str, Any], player: int) -> bool:
        if kind in SOURCE_ORDER_ACTIONS:
            self._source_order(kind, args, player)
            return True

        if kind == "Source Board Transport":
            passengers = [u for u in self._source_units(args, player) if int(u.unit_type) < 58 and not (int(u.sflags) & SF_HIDDEN)]
            transports = [
                unit for unit in self._source_target_units(args, player)
                if int(unit.unit_type) in {28, 29} and not (int(unit.sflags) & SF_HIDDEN)
            ]
            ordered = 0
            for passenger in passengers:
                transport = self._source_nearest(passenger, transports)
                if transport is None or not any(value == EMPTY_CARGO_SLOT for value in self._source_transport_slots(transport)):
                    continue
                self._call_cdecl(
                    self.order_callees["set_target"],
                    [passenger.address, int(transport.x), int(transport.y), transport.address, self.order_callees["do_move"]],
                )
                ordered += 1
            self.log(f"SOURCE TRANSPORT: ordered {ordered} passenger(s) to board")
            return True

        if kind == "Source Unload Transport Unit":
            transports = [unit for unit in self._source_units(args, player) if int(unit.unit_type) in {28, 29}]
            unloaded = 0
            for transport in transports:
                for slot_value in self._source_transport_slots(transport):
                    cargo = self._source_transport_unit(slot_value)
                    if cargo is None:
                        continue
                    if args.get("cargo_unit", "Any") != "Any" and int(args.get("cargo_unit")) != int(cargo.unit_type):
                        continue
                    result = self._call_cdecl(self.source_native_paths["unit_unload_transport"], [transport.address, cargo.address])
                    if result:
                        unloaded += 1
                        break
            self.log(f"SOURCE TRANSPORT: unloaded {unloaded} cargo unit(s)")
            return True

        if kind == "Source Train Unit":
            self._source_start_production(args, player, BUILD_UNIT, int(args.get("new_unit", 0)))
            return True
        if kind == "Source Research Technology":
            upgrade = str(args.get("upgrade", "Melee Attack"))
            if upgrade not in UPGRADE_ROWS:
                raise ValueError(f"Unknown source technology: {upgrade}")
            self._source_start_production(args, player, BUILD_TECH, UPGRADE_ROWS[upgrade])
            return True
        if kind == "Source Research Spell":
            spell = str(args.get("spell", "Holy Vision"))
            if spell not in SPELL_BITS:
                raise ValueError(f"Unknown source spell: {spell}")
            self._source_start_production(args, player, BUILD_SPELL, SPELL_BITS[spell])
            return True
        if kind == "Source Upgrade Building":
            self._source_start_production(args, player, BUILD_UPGRADE, int(args.get("new_building", 58)))
            return True
        if kind in {"Source Cancel Production", "Source Complete Production", "Source Set Production Progress"}:
            buildings = [u for u in self._source_units(args, player) if int(u.unit_type) >= 58]
            changed = 0
            for building in buildings:
                flags = self.pm.read_ushort(building.address + 0x1C)
                if not flags & UF_BUILD_ON:
                    continue
                total = self.pm.read_ushort(building.address + 0x70)
                if kind == "Source Cancel Production":
                    self._dispatch_ops([
                        ("or_word", building.address + 0x1C, UF_BUILD_CANCEL),
                        ("call", self.source_native_paths["bldg_dispatch_build"], [building.address]),
                    ])
                elif kind == "Source Complete Production":
                    self._dispatch_ops([
                        ("write_word", building.address + 0x6E, total),
                        ("call", self.source_native_paths["bldg_dispatch_build"], [building.address]),
                    ])
                else:
                    percent = max(0, min(100, int(args.get("percent", 50))))
                    current = round(total * percent / 100) if total else 0
                    mana = round(255 * percent / 100) if total else 0
                    self._dispatch_ops([
                        ("write_word", building.address + 0x6E, current),
                        ("write_byte", building.address + 0x26, mana),
                    ])
                changed += 1
            self.log(f"SOURCE PRODUCTION: {kind} changed {changed} building(s)")
            return True

        if kind == "Source Give Worker Cargo":
            cargo = str(args.get("cargo", "Gold"))
            amount = max(0, min(65535, int(args.get("cargo_amount", 100))))
            changed = 0
            for unit in self._source_units(args, player):
                flags = self.pm.read_uchar(unit.address + 0x75)
                flags &= ~(PEON_HARVEST_GOLD | PEON_HARVEST_LUMBER | PEON_LOADED)
                if amount:
                    flags |= PEON_LOADED
                    if cargo == "Gold": flags |= PEON_HARVEST_GOLD
                    elif cargo == "Lumber": flags |= PEON_HARVEST_LUMBER
                self._dispatch_ops([
                    ("write_byte", unit.address + 0x75, flags),
                    ("write_word", unit.address + 0x78, amount),
                    ("or_byte", unit.address + 0x06, 0x20),
                ])
                changed += 1
            self.log(f"SOURCE WORKER CARGO: gave {cargo} x{amount} to {changed} unit(s)")
            return True
        if kind == "Source Clear Worker Cargo":
            changed = 0
            for unit in self._source_units(args, player):
                flags = self.pm.read_uchar(unit.address + 0x75) & ~(PEON_HARVEST_GOLD | PEON_HARVEST_LUMBER | PEON_LOADED)
                self._dispatch_ops([("write_byte", unit.address + 0x75, flags), ("write_word", unit.address + 0x78, 0)])
                changed += 1
            self.log(f"SOURCE WORKER CARGO: cleared {changed} unit(s)")
            return True
        if kind == "Source Deposit Worker Cargo":
            deposited = {"Gold": 0, "Lumber": 0, "Oil": 0}
            for unit in self._source_units(args, player):
                flags = self.pm.read_uchar(unit.address + 0x75)
                if not flags & PEON_LOADED:
                    continue
                amount = self.pm.read_ushort(unit.address + 0x78)
                resource = "Gold" if flags & PEON_HARVEST_GOLD else "Lumber" if flags & PEON_HARVEST_LUMBER else "Oil"
                _name, address = self._resource_address(int(unit.owner), resource)
                before = self._read_resource(int(unit.owner), resource)
                after = min(0x7FFFFFFF, before + amount)
                cleared = flags & ~(PEON_HARVEST_GOLD | PEON_HARVEST_LUMBER | PEON_LOADED)
                self._dispatch_ops([
                    ("write_dword", address, after),
                    ("write_byte", unit.address + 0x75, cleared),
                    ("write_word", unit.address + 0x78, 0),
                ])
                deposited[resource] += amount
            self.log("SOURCE WORKER CARGO: deposited " + ", ".join(f"{key}={value}" for key, value in deposited.items()))
            return True
        if kind == "Source Refill Resource Node":
            amount = max(0, min(65535, int(args.get("resource_amount", 50000))))
            units = self._source_units(args, player)
            for unit in units:
                self._dispatch_ops([("write_word", unit.address + 0x8A, amount)])
            self.log(f"SOURCE RESOURCE NODE: set {len(units)} node(s) to {amount}")
            return True

        if kind in {"Source Set Tiles", "Source Remove Trees", "Source Remove Rocks", "Source Place Walls", "Source Destroy Walls"}:
            left, top, right, bottom = self._source_tile_region(args, kind)
            if kind == "Source Set Tiles":
                tile = int(args.get("tile", 0)) & 0xFFFF
            elif kind in {"Source Remove Trees", "Source Remove Rocks", "Source Destroy Walls"}:
                tile = int(args.get("replacement_tile", 0)) & 0xFFFF
            else:
                tile = int(args.get("wall_tile", 0)) & 0xFFFF
            filter_values: set[int] | None = None
            if kind in {"Source Remove Trees", "Source Remove Rocks", "Source Destroy Walls"}:
                raw = str(args.get("tile_values", "")).strip()
                filter_values = {
                    int(part.strip(), 0) & 0xFFFF
                    for part in raw.replace(";", ",").split(",")
                    if part.strip()
                }
                if not filter_values:
                    raise ValueError(f"{kind} requires one or more source tile IDs in Tile values")
            operations = []
            for y in range(top, bottom + 1):
                for x in range(left, right + 1):
                    address = self._source_tile_address(x, y)
                    if filter_values is not None and self.pm.read_ushort(address) not in filter_values:
                        continue
                    operations.append(("write_word", address, tile))
            for start in range(0, len(operations), 128):
                self._dispatch_ops(operations[start:start+128])
            self.log(f"SOURCE TERRAIN: {kind} wrote MTXM {tile} to {len(operations)} matching tile(s); live renderer/pathing refresh may require camera movement or a native region rebuild")
            return True
        if kind in {"Source Damage Walls", "Source Kill Walls"}:
            amount = max(1, int(args.get("damage", 20)))
            selected: list[Any] = []
            for wall_type in (103, 104):
                wall_args = dict(args); wall_args["unit"] = wall_type
                selected.extend(self._selected_units(wall_args, player))
            if kind == "Source Kill Walls":
                for wall in selected:
                    self._remove_one_unit_safely(wall)
            else:
                attackers = [
                    unit for unit in self._selected_units(
                        {"player": int(args.get("attacker_player", player)), "unit": args.get("attacker_unit", "Any"), "location": args.get("attacker_location", "Anywhere")},
                        player,
                    )
                    if unit.address not in {wall.address for wall in selected}
                ]
                if selected and not attackers:
                    raise RuntimeError("Source Damage Walls requires a live attacker for native damage credit")
                attacker = attackers[0] if attackers else None
                for wall in selected:
                    self._call_damage_unit(attacker, wall, amount)
            self.log(f"SOURCE WALLS: {kind} affected {len(selected)} wall object(s)")
            return True

        if kind in {"Source Find Walkable Point", "Source Find Buildable Point"}:
            units = self._source_units(args, player)
            if not units:
                raise RuntimeError(f"{kind} requires at least one matching prototype unit/building")
            x, y = self._source_point(args, kind)
            point = self._find_move_place(units[0], x, y)
            self._source_last_found_point = point
            x_var = str(args.get("x_variable", "Found X")); y_var = str(args.get("y_variable", "Found Y"))
            self.variables[x_var] = point[0] if point else -1
            self.variables[y_var] = point[1] if point else -1
            self.log(f"SOURCE PLACEMENT: {kind} requested ({x},{y}) -> {point}")
            return True

        if kind in {"Source Acquire Best Target", "Source Reevaluate Target"}:
            ordered = 0
            radius = max(0, int(args.get("radius", 0)))
            for unit in self._source_units(args, player):
                candidates = self._source_enemy_candidates(unit, args, player)
                if radius:
                    candidates = [c for c in candidates if max(abs(int(c.x)-int(unit.x)), abs(int(c.y)-int(unit.y))) <= radius]
                target = self._source_nearest(unit, candidates)
                if target is None:
                    continue
                self._call_cdecl(
                    self.order_callees["set_target"],
                    [unit.address, int(target.x), int(target.y), target.address, self.source_native_paths["do_attack_target"]],
                )
                ordered += 1
            self.log(f"SOURCE AI TARGETING: acquired {ordered} target(s)")
            return True
        if kind == "Source Clear Target":
            units = self._source_units(args, player)
            calls = [(self.order_callees["set_target"], [u.address, int(u.x), int(u.y), 0, self.source_native_paths["do_guard"]]) for u in units]
            if calls: self._call_cdecl_batched(calls)
            self.log(f"SOURCE AI TARGETING: cleared {len(units)} target(s)")
            return True

        if kind == "Source Convert Unit Type":
            forwarded = dict(args)
            forwarded["new_unit"] = int(args.get("new_unit", 0))
            forwarded["preserve_health_percent"] = bool(args.get("preserve_health_percent", True))
            super().massive_action("Replace Units", forwarded, player)
            return True
        if kind == "Source Play Animation":
            action = max(0, min(255, int(args.get("animation", 0))))
            frame = max(0, min(255, int(args.get("frame", 0))))
            facing = int(args.get("facing", 0)) & 7
            timer = max(0, min(255, int(args.get("timer", 1))))
            units = self._source_units(args, player)
            for unit in units:
                self._dispatch_ops([
                    ("write_byte", unit.address + 0x07, timer),
                    ("write_byte", unit.address + 0x08, action),
                    ("write_byte", unit.address + 0x09, frame),
                    ("write_byte", unit.address + 0x0A, facing),
                    ("or_byte", unit.address + 0x06, 0x20),
                ])
            self.log(f"SOURCE ANIMATION: action={action}, frame={frame}, facing={facing} on {len(units)} unit(s)")
            return True
        if kind == "Source Freeze Animation":
            units = self._source_units(args, player)
            for unit in units:
                action = int(args.get("animation", self.pm.read_uchar(unit.address + 0x08)))
                frame = int(args.get("frame", self.pm.read_uchar(unit.address + 0x09)))
                facing = int(args.get("facing", self.pm.read_uchar(unit.address + 0x0A)))
                self._source_frozen_animations[self._source_unit_key(unit)] = (action & 0xFF, frame & 0xFF, facing & 7)
            self.log(f"SOURCE ANIMATION: froze {len(units)} unit(s)")
            return True
        if kind == "Source Resume Animation":
            units = self._source_units(args, player)
            for unit in units:
                self._source_frozen_animations.pop(self._source_unit_key(unit), None)
                self.pm.write_uchar(unit.address + 0x07, max(1, int(args.get("timer", 1))) & 0xFF)
            self.log(f"SOURCE ANIMATION: resumed {len(units)} unit(s)")
            return True

        if kind == "Source Play Unit Sound":
            event = str(args.get("event", "Selection"))
            units = self._source_units(args, player)
            calls: list[tuple[int, list[int]]] = []
            for unit in units:
                if event == "Selection":
                    calls.append((self.source_native_paths["gamesnd_select"], [unit.address]))
                elif event == "Under Attack":
                    calls.append((self.source_native_paths["gamesnd_under_attack"], [unit.address]))
                elif event == "Harvest":
                    calls.append((self.source_native_paths["gamesnd_harvest"], [unit.address]))
                elif event == "Unit Death":
                    calls.append((self.source_native_paths["gamesnd_kill_man"], [unit.address]))
                elif event == "Building Destruction":
                    calls.append((self.source_native_paths["gamesnd_kill_bldg"], [unit.address]))
                else:
                    sound_id = self._spell_sound_id(args.get("sound", "Thunder"))
                    calls.append((self.source_native_paths["gamesnd_spell"], [unit.address, sound_id]))
            if calls: self._call_cdecl_batched(calls)
            self.log(f"SOURCE SOUND: {event} on {len(units)} unit(s)")
            return True

        if kind == "Source Play Explosion Sound At Point":
            x, y = self._source_point(args, kind)
            count = max(1, min(32, int(args.get("count", 1))))
            self._call_cdecl_batched([(self.source_native_paths["gamesnd_explode"], [x, y]) for _ in range(count)])
            self.log(f"SOURCE SOUND: explosion at ({x},{y}) x{count}")
            return True

        if kind == "Source Create Projectile At Point":
            x, y = self._source_point(args, kind)
            missile_type = max(0, min(28, int(args.get("missile", 0))))
            count = max(1, min(128, int(args.get("count", 1))))
            calls = [(self.bullet_path["bullet_create_xy"], [x << 5, y << 5, missile_type]) for _ in range(count)]
            self._call_cdecl_batched(calls)
            self.log(f"SOURCE PROJECTILE: created {count} type {missile_type} projectile(s) at ({x},{y})")
            return True
        if kind == "Source Create Projectile Between Units":
            attackers = self._source_units(args, player); targets = self._source_target_units(args, player)
            created = 0
            for attacker in attackers:
                target = self._source_nearest(attacker, targets)
                if target is None: continue
                self._create_missile(attacker, target); created += 1
            self.log(f"SOURCE PROJECTILE: created {created} native attacker projectile(s)")
            return True
        if kind == "Source Attach Projectile To Unit":
            units = self._source_units(args, player)
            missile_type = max(0, min(28, int(args.get("missile", 22))))
            calls = [(self.bullet_path["bullet_create_xy"], [int(u.x) << 5, int(u.y) << 5, missile_type]) for u in units]
            if calls: self._call_cdecl_batched(calls)
            self.log(f"SOURCE PROJECTILE: attached visual type {missile_type} to {len(units)} current unit position(s)")
            return True
        if kind == "Source Create Explosion Projectile":
            local = dict(args); local["missile"] = int(args.get("missile", 20)); local["count"] = int(args.get("count", 1))
            return self.massive_action("Source Create Projectile At Point", local, player)
        if kind in {"Source Blizzard Volley", "Source Fire Shield Effect", "Source Whirlwind", "Source Raise Dead Effect"}:
            spell = {
                "Source Blizzard Volley": "Blizzard",
                "Source Fire Shield Effect": "Flame Shield",
                "Source Whirlwind": "Whirlwind",
                "Source Raise Dead Effect": "Raise Dead",
            }[kind]
            forwarded = dict(args); forwarded["spell"] = spell
            # Cast Spell already owns the source-validated projectile/effect constructors.
            self.action("Cast Spell", forwarded, player)
            return True

        return super().massive_action(kind, args, player)
