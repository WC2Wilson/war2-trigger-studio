from __future__ import annotations

from collections import deque
import math
import random
import time
from typing import Any

from source_features import (
    SourceFeatureMixin,
    BUILD_UNIT,
    BUILD_TECH,
    BUILD_SPELL,
    BUILD_UPGRADE,
    UF_BUILD_ON,
    UF_BUILD_CANCEL,
    SF_HIDDEN,
    PEON_LOADED,
    PEON_HARVEST_GOLD,
    PEON_HARVEST_LUMBER,
    ORDER_GUARD,
    ORDER_MOVE,
    ORDER_ATTACK_TARGET,
    ORDER_HARVEST,
    ORDER_REPAIR,
    ORDER_RETURN,
    ORDER_WAIT,
    ORDER_BLDG_WAIT,
    ORDER_NONE,
    EMPTY_CARGO_SLOT,
)
from ultimate_features import SPELL_BITS, UPGRADE_ROWS


# Canonical Warcraft II order/action IDs for spell execution and mana-cost table
# lookups.  The research-bit table includes entries such as conversions and
# Hallucinate that do not map one-for-one to the live action dispatcher.
SOURCE128_SPELL_ACTIONS: dict[str, int] = {
    "Holy Vision": 38,
    "Healing": 39,
    "Area Heal": 40,
    "Exorcism": 41,
    "Flame Shield": 42,
    "Fireball": 43,
    "Slow": 44,
    "Invisibility": 45,
    "Polymorph": 46,
    "Blizzard": 47,
    "Eye of Kilrogg": 48,
    "Bloodlust": 49,
    "Raise Dead": 50,
    "Death Coil": 51,
    "Whirlwind": 52,
    "Haste": 53,
    "Unholy Armor": 54,
    "Runes": 55,
    "Death and Decay": 56,
}


# Source / Remaster unit table locations that are already referenced and checked by
# the live adapter.  Tables that are not proven in the Remaster are implemented as
# trigger-owned overrides instead of pretending an unsafe RVA is native.
UNIT_HP_TABLE_RVA = 0x5177C0
UNIT_ARMOR_TABLE_RVA = 0x517F90
UNIT_PIERCE_TABLE_RVA = 0x5180E0
UNIT_STRENGTH_TABLE_RVA = 0x518150
UNIT_BULLET_TABLE_RVA = 0x5182A0
UNIT_IS_TABLE_RVA = 0x5185F0
CASTING_COST_TABLE_RVA = 0x4C5EB8
RUNE_X_RVA = 0x518D14
RUNE_Y_RVA = 0x518D48
RUNE_DELAY_RVA = 0x518D80
MAX_RUNES = 50
RUNE_TIME = 0x800

UF_RESCUE = 0x0100
SF_DIEING = 0x0002
SF_DEAD = 0x0004
SF_COMPLETED = 0x0080
SF_BUILD_FOUNDATION = 0x0100
SF_PAUSE_TOGGLE = 0x0800
SF_IS_PAUSED = 0x1000
SF_SELECTED = 0x2000
SF_UNDER_ATTACK = 0x8000

IS_WALKING = 0x00000001
IS_FLYER = 0x00000002
IS_ROLLING = 0x00000004
IS_SHIP = 0x00000008
IS_MONSTER = 0x00000010
IS_BLDG = 0x00000020
IS_PEON = 0x00000100
IS_TANKER = 0x00000200
IS_TRANSPORT = 0x00000400
IS_OILRIG = 0x00000800
IS_TOWNHALL = 0x00001000
IS_DEAD = 0x00002000
IS_SHORE_BLDG = 0x00010000
IS_CASTER = 0x00020000
IS_LUMBER = 0x00040000
IS_ATTACKER = 0x00080000
IS_OILPATCH = 0x00200000
IS_GOLDMINE = 0x00400000
IS_NPC = 0x00800000
IS_RETURN_OIL = 0x01000000
IS_FLESHY = 0x08000000

# Verified against Warcraft II Remastered x86 builds 1.0.2.2505 and 1.0.2.2818.
SOURCE128_NATIVE_SPECS: dict[str, tuple[int, bytes]] = {
    "damage_unit_vs_unit": (0x000BD770, b"\x55\x8B\xEC\x56\x57\x8B\x7D\x08"),
    "damage_damage_mtx": (0x000BD850, b"\x55\x8B\xEC\x66\xA1"),
    "damage_damage_unit": (0x000BD8F0, b"\x55\x8B\xEC\x56\x8B\x75\x0C"),
    "damage_unit_armor": (0x000BD9B0, b"\x55\x8B\xEC\x8B\x55\x08"),
    "damage_unit_strength": (0x000BDA20, b"\x55\x8B\xEC\x83\xEC\x08"),
    "damage_unit_pierce": (0x000BDAD0, b"\x55\x8B\xEC\x51"),
    "damage_unit_sum": (0x000BDBD0, b"\x55\x8B\xEC\x56\x57"),
}

# Public 1.28 condition/action surface.  Clause editor imports the same lists so
# runtime and editor cannot silently drift apart.
SOURCE128_CONDITIONS = [
    # Construction and production
    "Source Construction Progress", "Source Worker Is Constructing",
    "Source Player Can Afford Unit", "Source Player Can Afford Upgrade",
    "Source Player Has Enough Food", "Source Building Production Type",
    "Source Building Production Item", "Source Production Time Remaining",
    "Source Production Is Paused", "Source Production Is Waiting",
    "Source Production Queue Count", "Source Auto Train Remaining",
    # Pathing and placement
    "Source Unit Can Reach Location", "Source Unit Can Reach Unit",
    "Source Locations On Same Island", "Source Target Path Is Valid",
    "Source Last Shore X", "Source Last Shore Y", "Source Last Dock X",
    "Source Last Dock Y", "Source Last Undock X", "Source Last Undock Y",
    # Damage
    "Source Predicted Native Damage", "Source Native Armor Reduction",
    "Source Last Native Damage", "Source Last Terrain Damage",
    # Fog / visibility
    "Source Location Is Visible", "Source Location Is Explored",
    # AI and attacker state
    "Source Unit Has Valid Attacker", "Source Unit Is Fleeing",
    # Terrain lifecycle
    "Source Tile Is Being Chopped", "Source Tile Region Type",
    "Source Tile Has Land Access", "Source Tile Has Water Access",
    "Source Wall Is Connected", "Source Tree Is Reachable",
    # Worker/resource/oil
    "Source Worker Can Return Resources", "Source Worker Is Inside Resource",
    "Source Last Resource X", "Source Last Resource Y",
    # Rune and spell validation
    "Source Rune Exists At Location", "Source Rune Owner", "Source Rune Lifetime",
    "Source Can Cast Spell On Unit", "Source Target Is Wooden",
    "Source Target Is Fleshy", "Source Target Is Drainable",
    "Source Target Is Valid For Spell", "Source Spell Mana Cost",
    # Projectiles
    "Source Projectile Hit Unit", "Source Projectile Hit Location",
    "Source Projectile Frozen", "Source Projectile Lifetime",
    # Rescue/lifecycle
    "Source Unit Is Rescuable", "Source Unit Was Rescued",
    "Source Unit Is Hidden", "Source Unit Is Paused", "Source Corpse Decay Active",
    # Native/safe ICE strategy
    "Source ICE Strategy Active", "Source AI Build Goal",
    # Global rule state
    "Source Unit Type Maximum HP", "Source Unit Type Armor",
    "Source Unit Type Basic Damage", "Source Unit Type Piercing Damage",
    "Source Unit Type Attack Range", "Source Unit Type Sight",
    "Source Unit Type Speed", "Source Unit Type Projectile",
    "Source Unit Type Gold Cost", "Source Unit Type Lumber Cost",
    "Source Unit Type Oil Cost", "Source Unit Type Build Time",
    "Source Upgrade Cost", "Source Upgrade Research Time",
    # Local interface state
    "Source Local Input Locked", "Source Local Mouse Button", "Source Local Key",
]

SOURCE128_ACTIONS = [
    # Construction
    "Source Order Worker To Build", "Source Place Building Foundation",
    "Source Cancel Construction", "Source Find Nearest Building Site",
    # Pathing
    "Source Find Shore Point", "Source Find Dock Point", "Source Find Undock Point",
    # Damage
    "Source Calculate Native Damage", "Source Deal Native Attack Damage",
    "Source Damage Terrain", "Source Damage Wall With Attack",
    # Fog
    "Source Reveal Area For Player", "Source Reveal Radius",
    "Source Refresh Fog", "Source Refresh Minimap",
    # AI reactions
    "Source Set Attacker", "Source Clear Attacker", "Source Run Native Retaliation",
    "Source Call Nearby Units For Help", "Source Force Unit To Flee",
    "Source Run Native Attack Decision",
    # Terrain lifecycle
    "Source Begin Tree Harvest", "Source Cancel Tree Harvest",
    "Source Finish Tree Harvest", "Source Find Reachable Tree",
    "Source Native Demolish Tile", "Source Remove Terrain Region",
    "Source Rebuild Wall Connections", "Source Rebuild Shore Regions",
    "Source Refresh Terrain Pathing", "Source Refresh Terrain Minimap",
    # Production controller
    "Source Pause Production", "Source Resume Production", "Source Queue Unit",
    "Source Clear Production Queue", "Source Enable Continuous Training",
    "Source Set Auto Train Count",
    # Worker/resource/oil
    "Source Find Nearest Gold Mine", "Source Find Nearest Reachable Tree",
    "Source Find Nearest Oil Patch", "Source Find Nearest Return Building",
    "Source Force Worker Into Resource Building", "Source Force Worker Out Of Building",
    "Source Complete Harvest Cycle", "Source Tanker Dock",
    "Source Tanker Collect Oil", "Source Tanker Deposit Oil",
    # Runes/spells
    "Source Place Rune", "Source Remove Rune", "Source Trigger Rune",
    "Source Set Rune Lifetime", "Source Set Spell Mana Cost",
    # Projectile fields/constructors
    "Source Set Projectile Type", "Source Set Projectile Owner",
    "Source Set Projectile Damage", "Source Set Projectile Speed",
    "Source Set Projectile Lifetime", "Source Set Projectile Action",
    "Source Set Projectile Target", "Source Freeze Projectile",
    "Source Resume Projectile", "Source Create Tower Projectile",
    "Source Create Fire Projectile", "Source Create Flame Spin",
    "Source Create Black X Marker", "Source Create Stationary Projectile",
    # Full contextual sounds
    "Source Play Acknowledgement Sound", "Source Play Attack Response Sound",
    "Source Play Build Started Sound", "Source Play Building Complete Sound",
    "Source Play Unit Created Sound", "Source Play Unit Loaded Sound",
    "Source Play Rescue Sound", "Source Play Capture Sound", "Source Play Dock Sound",
    "Source Play Error Sound", "Source Play Impact Sound",
    "Source Play Projectile Sound", "Source Play Arrow Sound",
    "Source Play Cannon Sound", "Source Play Sparkle Sound",
    # Rescue/lifecycle
    "Source Enable Unit Rescue", "Source Disable Unit Rescue", "Source Check Rescue Now",
    "Source Hide Unit Natively", "Source Show Unit Natively",
    "Source Pause Individual Unit", "Source Resume Individual Unit",
    "Source Kill Transport Occupants", "Source Eject Transport Occupants",
    "Source Begin Corpse Decay", "Source Stop Corpse Decay",
    "Source Set Current Native Action", "Source Set Next Native Action",
    # ICE strategy surface (safe source-order implementation; avoids legacy globals)
    "Source Run Native Patrol AI", "Source Run Native Guard AI",
    "Source Run Native Defend AI", "Source Run Native Attack AI",
    "Source Run Native Transport AI", "Source Run Native Oil Patrol",
    "Source Attack Specific Player", "Source Attack Strongest Player",
    "Source Run Native Spell AI", "Source Run Native Build Strategy",
    "Source Set AI Build Goal", "Source Force AI Suicide Attack",
    # Global runtime rule overrides
    "Source Set Unit Type Maximum HP", "Source Set Unit Type Armor",
    "Source Set Unit Type Basic Damage", "Source Set Unit Type Piercing Damage",
    "Source Set Unit Type Attack Range", "Source Set Unit Type Sight",
    "Source Set Unit Type Speed", "Source Set Unit Type Projectile",
    "Source Set Unit Type Gold Cost", "Source Set Unit Type Lumber Cost",
    "Source Set Unit Type Oil Cost", "Source Set Unit Type Build Time",
    "Source Set Upgrade Cost", "Source Set Upgrade Research Time",
    "Source Restore Vanilla Unit Type", "Source Restore All Vanilla Rules",
    # Local-only interface helpers
    "Source Pause Game", "Source Resume Game", "Source Select Units",
    "Source Deselect Units", "Source Lock Player Input", "Source Unlock Player Input",
    "Source Show Minimap Marker", "Source Clear Minimap Markers",
    "Source Set Local Camera", "Source Set Selected Unit Card",
    "Source Play Local Cinematic", "Source Show Local Dialog",
]

# Table-backed fields with proven Remaster storage.
TABLE_RULES: dict[str, tuple[int, int, int, int]] = {
    # action suffix -> (RVA, item size, minimum, maximum)
    "Maximum HP": (UNIT_HP_TABLE_RVA, 2, 1, 65535),
    "Armor": (UNIT_ARMOR_TABLE_RVA, 1, 0, 255),
    "Basic Damage": (UNIT_STRENGTH_TABLE_RVA, 1, 0, 255),
    "Piercing Damage": (UNIT_PIERCE_TABLE_RVA, 1, 0, 255),
    "Projectile": (UNIT_BULLET_TABLE_RVA, 1, 0, 28),
}

# Trigger-owned rules fill gaps where Remastered no longer exposes the legacy UDTA
# arrays directly.  They are honored by all 1.28 trigger-created/controlled units.
VIRTUAL_RULE_DEFAULTS = {
    "Attack Range": 1,
    "Sight": 9,
    "Speed": 100,
    "Gold Cost": 0,
    "Lumber Cost": 0,
    "Oil Cost": 0,
    "Build Time": 0,
}


class SourceFeature128Mixin(SourceFeatureMixin):
    """1.28 Complete Source Systems.

    Exact native callbacks are validated before use.  Systems whose legacy globals do
    not exist in the Remaster are reproduced by deterministic trigger-owned state,
    never by calling an unverified address.
    """

    def _init_massive_features(self) -> None:
        super()._init_massive_features()
        self._source128_paused_production: dict[tuple[int, int], tuple[int, int, int]] = {}
        self._source128_queues: dict[tuple[int, int], list[tuple[int, int]]] = {}
        self._source128_auto_train: dict[tuple[int, int], tuple[int, int]] = {}
        self._source128_paused_units: dict[tuple[int, int], dict[str, int]] = {}
        self._source128_frozen_projectiles: dict[int, dict[str, int]] = {}
        self._source128_revealed: dict[int, set[tuple[int, int]]] = {i: set() for i in range(16)}
        self._source128_rescue_enabled: set[tuple[int, int]] = set()
        self._source128_rescued_recent: set[tuple[int, int]] = set()
        self._source128_corpse_decay: set[tuple[int, int]] = set()
        self._source128_ice: dict[tuple[int, int], dict[str, Any]] = {}
        self._source128_ai_build_goals: dict[int, tuple[int, int]] = {}
        self._source128_rule_originals: dict[tuple[int, int], bytes] = {}
        self._source128_virtual_rules: dict[tuple[str, int], int] = {}
        self._source128_upgrade_rules: dict[tuple[str, int], int] = {}
        self._source128_projectile_speed: dict[int, int] = {}
        self._source128_projectile_hits: list[tuple[int, int, int]] = []
        self._source128_last_damage = 0
        self._source128_last_terrain_damage = 0
        self._source128_last_shore: tuple[int, int] | None = None
        self._source128_last_dock: tuple[int, int] | None = None
        self._source128_last_undock: tuple[int, int] | None = None
        self._source128_last_resource: tuple[int, int] | None = None
        self._source128_input_locked = False
        self._source128_minimap_markers: list[tuple[int, int, float]] = []
        self._source128_local_keys: set[str] = set()
        self._source128_local_mouse = 0
        self._source128_path_cache: dict[tuple[Any, ...], bool] = {}
        self._source128_rule_snapshot_done = False

    def _massive_begin_run(self) -> None:
        super()._massive_begin_run()
        self._source128_paused_production.clear()
        self._source128_queues.clear()
        self._source128_auto_train.clear()
        self._source128_paused_units.clear()
        self._source128_frozen_projectiles.clear()
        self._source128_rescue_enabled.clear()
        self._source128_rescued_recent.clear()
        self._source128_corpse_decay.clear()
        self._source128_ice.clear()
        self._source128_ai_build_goals.clear()
        self._source128_projectile_hits.clear()
        self._source128_path_cache.clear()

    def _resolve_source_native_paths(self) -> dict[str, int]:
        resolved = super()._resolve_source_native_paths()
        for name, (rva, prefix) in SOURCE128_NATIVE_SPECS.items():
            address = self.base + rva
            actual = self.pm.read_bytes(address, len(prefix))
            if actual != prefix:
                raise RuntimeError(
                    f"1.28 source callback {name} failed at RVA 0x{rva:X}: "
                    f"expected {prefix.hex(' ')}, read {actual.hex(' ')}"
                )
            resolved[name] = address
        return resolved

    # ------------------------------ generic helpers
    @staticmethod
    def _source128_distance(a: Any, b: Any) -> int:
        return max(abs(int(a.x) - int(b.x)), abs(int(a.y) - int(b.y)))

    def _source128_flags(self, unit_type: int) -> int:
        return int(self.pm.read_uint(self.base + UNIT_IS_TABLE_RVA + int(unit_type) * 4))

    def _source128_rule_value(self, suffix: str, unit_type: int) -> int:
        if suffix in TABLE_RULES:
            rva, size, _, _ = TABLE_RULES[suffix]
            address = self.base + rva + unit_type * size
            return self.pm.read_ushort(address) if size == 2 else self.pm.read_uchar(address)
        return int(self._source128_virtual_rules.get((suffix, unit_type), VIRTUAL_RULE_DEFAULTS[suffix]))

    def _source128_set_rule(self, suffix: str, unit_type: int, value: int) -> None:
        if not 0 <= unit_type < 110:
            raise ValueError(f"Invalid unit type {unit_type}")
        if suffix in TABLE_RULES:
            rva, size, low, high = TABLE_RULES[suffix]
            value = max(low, min(high, int(value)))
            address = self.base + rva + unit_type * size
            key = (address, size)
            if key not in self._source128_rule_originals:
                self._source128_rule_originals[key] = self.pm.read_bytes(address, size)
            if size == 2:
                self.pm.write_ushort(address, value)
            else:
                self.pm.write_uchar(address, value)
        else:
            self._source128_virtual_rules[(suffix, unit_type)] = max(0, int(value))

    def _source128_restore_unit_rules(self, unit_type: int) -> int:
        restored = 0
        for suffix, (rva, size, _, _) in TABLE_RULES.items():
            address = self.base + rva + unit_type * size
            key = (address, size)
            original = self._source128_rule_originals.pop(key, None)
            if original is not None:
                self.pm.write_bytes(address, original, size)
                restored += 1
        for suffix in VIRTUAL_RULE_DEFAULTS:
            self._source128_virtual_rules.pop((suffix, unit_type), None)
        return restored

    def _source128_write_variable_point(self, point: tuple[int, int] | None, args: dict[str, Any], prefix: str) -> None:
        x_name = str(args.get("x_variable", f"{prefix} X"))
        y_name = str(args.get("y_variable", f"{prefix} Y"))
        self.variables[x_name] = point[0] if point else -1
        self.variables[y_name] = point[1] if point else -1

    def _source128_direct_start(self, building: Any, order: int, parm: int) -> bool:
        result = self._call_cdecl(
            self.source_native_paths["bldg_build_start"],
            [building.address, parm & 0xFF, order & 0xFF],
        )
        return bool(result and (self.pm.read_ushort(building.address + 0x1C) & UF_BUILD_ON))

    def _source128_nearest_type(self, source: Any, flags_mask: int = 0, owner: int | None = None, unit_types: set[int] | None = None) -> Any | None:
        candidates = []
        for candidate in self.units():
            if candidate.address == source.address or candidate.sflags & SF_HIDDEN:
                continue
            if owner is not None and int(candidate.owner) != owner:
                continue
            if unit_types is not None and int(candidate.unit_type) not in unit_types:
                continue
            if flags_mask and not (self._source128_flags(int(candidate.unit_type)) & flags_mask):
                continue
            candidates.append(candidate)
        return self._source_nearest(source, candidates)

    def _source128_placeable(self, prototype: Any, x: int, y: int) -> bool:
        if not (0 <= x < self.map_width and 0 <= y < self.map_height):
            return False
        try:
            unit_class = self.pm.read_uchar(prototype.address + 0x2A)
            return bool(self._call_cdecl(
                self.move_callees["placeable"],
                [unit_class, x, y, int(prototype.unit_type)],
            ))
        except Exception:
            return False

    def _source128_reachable(self, prototype: Any, start: tuple[int, int], goal: tuple[int, int], max_nodes: int = 768) -> bool:
        key = (int(prototype.unit_type), start, goal, int(max_nodes), self._trigger_generation)
        if key in self._source128_path_cache:
            return self._source128_path_cache[key]
        if start == goal:
            return True
        step = 2 if (self.pm.read_ushort(prototype.address + 0x1C) & 0x0002) else 1
        q = deque([start]); seen = {start}; nodes = 0
        directions = ((step, 0), (-step, 0), (0, step), (0, -step), (step, step), (step, -step), (-step, step), (-step, -step))
        result = False
        while q and nodes < max(32, min(4096, int(max_nodes))):
            x, y = q.popleft(); nodes += 1
            for dx, dy in directions:
                nx, ny = x + dx, y + dy
                if (nx, ny) in seen or not (0 <= nx < self.map_width and 0 <= ny < self.map_height):
                    continue
                if max(abs(nx - goal[0]), abs(ny - goal[1])) <= step:
                    result = True; q.clear(); break
                if self._source128_placeable(prototype, nx, ny):
                    seen.add((nx, ny)); q.append((nx, ny))
        self._source128_path_cache[key] = result
        return result

    def _source128_scan_point(self, prototype: Any, center: tuple[int, int], want: str, radius: int = 24) -> tuple[int, int] | None:
        cx, cy = center
        radius = max(1, min(64, int(radius)))
        flags = self._source128_flags(int(prototype.unit_type))
        is_water = bool(flags & (IS_SHIP | IS_TANKER | IS_TRANSPORT))
        for r in range(radius + 1):
            points = []
            for dx in range(-r, r + 1):
                points.extend(((cx + dx, cy - r), (cx + dx, cy + r)))
            for dy in range(-r + 1, r):
                points.extend(((cx - r, cy + dy), (cx + r, cy + dy)))
            for x, y in points:
                if not self._source128_placeable(prototype, x, y):
                    continue
                if want == "shore":
                    # A shore point is a legal point with an adjacent point that is
                    # legal for a unit of the opposite movement class, when such a
                    # prototype is available.  Otherwise it is the nearest legal edge.
                    opposite = next((u for u in self.units() if bool(self._source128_flags(int(u.unit_type)) & (IS_SHIP | IS_TANKER | IS_TRANSPORT)) != is_water), None)
                    if opposite and any(self._source128_placeable(opposite, x + dx, y + dy) for dx, dy in ((1,0),(-1,0),(0,1),(0,-1))):
                        return x, y
                elif want in {"dock", "undock"}:
                    return x, y
        return None

    def _source128_native_damage(self, attacker: Any, target: Any, roll: bool = True) -> int:
        if roll:
            return max(0, int(self._call_cdecl(self.source_native_paths["damage_unit_vs_unit"], [attacker.address, target.address])) & 0xFFFF)
        strength = int(self._call_cdecl(self.source_native_paths["damage_unit_strength"], [attacker.address]))
        pierce = int(self._call_cdecl(self.source_native_paths["damage_unit_pierce"], [attacker.address]))
        armor = int(self._call_cdecl(self.source_native_paths["damage_unit_armor"], [target.address]))
        return max(1, pierce + max(0, strength - armor))

    def _source128_spell_action(self, spell: str) -> int:
        # Research bits are not contiguous action IDs.  Use the explicit native
        # spell dispatcher mapping so mana-cost and target-validation actions do
        # not read or write the wrong table entry.
        try:
            return SOURCE128_SPELL_ACTIONS[spell]
        except KeyError as exc:
            supported = ", ".join(SOURCE128_SPELL_ACTIONS)
            raise ValueError(f"Spell has no validated live action ID: {spell}. Supported: {supported}") from exc

    def _source128_rune_slots(self) -> list[tuple[int, int, int, int]]:
        result = []
        for slot in range(MAX_RUNES):
            delay = self.pm.read_ushort(self.base + RUNE_DELAY_RVA + slot * 2)
            if not delay:
                continue
            x = self.pm.read_uchar(self.base + RUNE_X_RVA + slot)
            y = self.pm.read_uchar(self.base + RUNE_Y_RVA + slot)
            result.append((slot, x, y, delay))
        return result

    def _source128_projectiles(self, args: dict[str, Any], player: int) -> list[Any]:
        selected = self._selected_missiles(args, player)
        raw = args.get("amount", "All")
        if raw == "All" or raw is None or raw == "":
            return selected
        return selected[:max(0, int(raw))]

    def _source128_freeze_projectile_snapshot(self, missile: Any) -> dict[str, int]:
        return {
            "x": self.pm.read_short(missile.address + 0x00),
            "y": self.pm.read_short(missile.address + 0x02),
            "tx": self.pm.read_short(missile.address + 0x28),
            "ty": self.pm.read_short(missile.address + 0x2A),
            "target": self.pm.read_uint(missile.address + 0x2C),
            "owner": self.pm.read_uint(missile.address + 0x30),
            "type": self.pm.read_uchar(missile.address + 0x34),
            "flags": self.pm.read_uchar(missile.address + 0x35),
            "action": self.pm.read_uchar(missile.address + 0x36),
            "damage": self.pm.read_uchar(missile.address + 0x37),
            "life": self.pm.read_short(missile.address + 0x38),
        }

    def _source128_reveal_point(self, owner: int, x: int, y: int) -> None:
        if not 0 <= owner < 16:
            return
        self._call_cdecl(self.spell_path["vision_unmask"], [x, y, owner])
        for yy in range(max(0, y - 9), min(self.map_height, y + 10)):
            for xx in range(max(0, x - 9), min(self.map_width, x + 10)):
                self._source128_revealed[owner].add((xx, yy))

    def _source128_find_resource(self, unit: Any, mode: str) -> Any | None:
        if mode == "Gold":
            return self._source128_nearest_type(unit, IS_GOLDMINE)
        if mode == "Oil":
            return self._source128_nearest_type(unit, IS_OILPATCH)
        if mode == "Return":
            cargo = self.pm.read_uchar(unit.address + 0x75)
            wanted = IS_RETURN_OIL if (cargo & PEON_LOADED and not cargo & (PEON_HARVEST_GOLD | PEON_HARVEST_LUMBER)) else (IS_TOWNHALL | IS_LUMBER)
            return self._source128_nearest_type(unit, wanted, owner=int(unit.owner))
        return None

    def _source128_create_foundation(self, args: dict[str, Any], player: int) -> list[Any]:
        before = {u.address for u in self.units()}
        forwarded = dict(args)
        forwarded["new_unit"] = int(args.get("new_building", args.get("new_unit", 58)))
        forwarded["amount"] = max(1, int(args.get("count", args.get("amount", 1) if args.get("amount") != "All" else 1)))
        # Create Units intentionally leaves buildings in the native foundation /
        # grow_structure lifecycle; Complete Buildings is the separate completed path.
        self.action("Create Units", forwarded, player)
        current = self.units()
        created = [u for u in current if u.address not in before and int(u.unit_type) == forwarded["new_unit"]]
        return created

    # ------------------------------ maintenance
    def _massive_prepare_events(self, current: dict[tuple[int, int], Any], previous: dict[tuple[int, int], Any]) -> None:
        super()._massive_prepare_events(current, previous)
        self._source128_path_cache.clear()
        self._source128_rescued_recent.clear()

        # Paused production: retain exact progress while native simulation remains alive.
        for key, state in list(self._source128_paused_production.items()):
            building = current.get(key)
            if building is None:
                self._source128_paused_production.pop(key, None); continue
            curr, total, mana = state
            try:
                self.pm.write_ushort(building.address + 0x6E, curr)
                self.pm.write_ushort(building.address + 0x70, total)
                self.pm.write_uchar(building.address + 0x26, mana)
            except Exception:
                self._source128_paused_production.pop(key, None)

        # Trigger-owned production queues and continuous training.
        for key, queue in list(self._source128_queues.items()):
            building = current.get(key)
            if building is None:
                self._source128_queues.pop(key, None); continue
            if not (self.pm.read_ushort(building.address + 0x1C) & UF_BUILD_ON) and queue:
                order, parm = queue[0]
                if self._source128_direct_start(building, order, parm):
                    queue.pop(0)
        for key, (unit_type, remaining) in list(self._source128_auto_train.items()):
            building = current.get(key)
            if building is None or remaining == 0:
                self._source128_auto_train.pop(key, None); continue
            if not (self.pm.read_ushort(building.address + 0x1C) & UF_BUILD_ON):
                if self._source128_direct_start(building, BUILD_UNIT, unit_type):
                    if remaining > 0:
                        self._source128_auto_train[key] = (unit_type, remaining - 1)

        # Freeze individual units without stopping the trigger engine.
        for key, state in list(self._source128_paused_units.items()):
            unit = current.get(key)
            if unit is None:
                self._source128_paused_units.pop(key, None); continue
            try:
                self.pm.write_uchar(unit.address + 0x2E, ORDER_WAIT)
                self.pm.write_uchar(unit.address + 0x2F, ORDER_NONE)
                self.pm.write_ushort(unit.address + 0x1E, self.pm.read_ushort(unit.address + 0x1E) | SF_IS_PAUSED)
                self.pm.write_short(unit.address + 0x18, state["x"])
                self.pm.write_short(unit.address + 0x1A, state["y"])
            except Exception:
                self._source128_paused_units.pop(key, None)

        # Frozen projectile state and trigger-owned speed steps.
        active_addresses = {m.address for m in self._active_missiles()}
        for address, state in list(self._source128_frozen_projectiles.items()):
            if address not in active_addresses:
                self._source128_frozen_projectiles.pop(address, None); continue
            try:
                self.pm.write_short(address + 0x00, state["x"])
                self.pm.write_short(address + 0x02, state["y"])
                self.pm.write_short(address + 0x28, state["tx"])
                self.pm.write_short(address + 0x2A, state["ty"])
                self.pm.write_short(address + 0x38, state["life"])
            except Exception:
                self._source128_frozen_projectiles.pop(address, None)
        for missile in self._active_missiles():
            if missile.address in self._source128_frozen_projectiles:
                continue
            speed = self._source128_projectile_speed.get(missile.address)
            if not speed or speed == 100:
                continue
            # Safe proportional movement correction; native collision/action remains active.
            dx = int(missile.target_x) - int(missile.x)
            dy = int(missile.target_y) - int(missile.y)
            if dx or dy:
                factor = max(1, min(400, speed)) / 100.0
                nx = int(missile.x + dx * min(0.75, 0.05 * factor))
                ny = int(missile.y + dy * min(0.75, 0.05 * factor))
                self.pm.write_short(missile.address + 0x00, nx)
                self.pm.write_short(missile.address + 0x02, ny)

        # Detect projectile arrival for explicit hit conditions.
        self._source128_projectile_hits.clear()
        for missile in self._active_missiles():
            if max(abs(int(missile.target_x) - int(missile.x)), abs(int(missile.target_y) - int(missile.y))) <= 32:
                self._source128_projectile_hits.append((missile.address, int(missile.target_x) >> 5, int(missile.target_y) >> 5))

        # Automatic rescue checks requested by triggers.
        for key in list(self._source128_rescue_enabled):
            rescued = current.get(key)
            if rescued is None:
                self._source128_rescue_enabled.discard(key); continue
            if not (self.pm.read_ushort(rescued.address + 0x1C) & UF_RESCUE):
                self.pm.write_ushort(rescued.address + 0x1C, self.pm.read_ushort(rescued.address + 0x1C) | UF_RESCUE)
            captors = [u for u in current.values() if 0 <= int(u.owner) < 8 and int(u.owner) != int(rescued.owner) and self._source128_flags(int(u.unit_type)) & (IS_WALKING | IS_FLYER | IS_ROLLING | IS_SHIP | IS_MONSTER)]
            captor = self._source_nearest(rescued, captors)
            if captor is not None and self._source128_distance(rescued, captor) <= 2:
                old_key = key
                # Existing Give Units owns the validated Remaster capture contract.
                # Do not call the legacy-shaped capture signature directly.
                self.action("Give Units", {"player": int(rescued.owner), "unit": int(rescued.unit_type), "location": "Anywhere", "new_player": int(captor.owner), "amount": 1}, int(captor.owner))
                self._source128_rescued_recent.add(old_key)
                self._source128_rescue_enabled.discard(old_key)

        # Safe source-order ICE controllers.  They never touch legacy-only strategy globals.
        for key, state in list(self._source128_ice.items()):
            unit = current.get(key)
            if unit is None:
                self._source128_ice.pop(key, None); continue
            if time.monotonic() < float(state.get("next", 0.0)):
                continue
            state["next"] = time.monotonic() + max(0.15, float(state.get("cadence", 0.75)))
            mode = state.get("mode", "Attack")
            if mode in {"Attack", "Suicide", "Defend", "Guard"}:
                candidates = self._source_enemy_candidates(unit, {"target_player": state.get("target_player", -1), "target_unit": "Any", "target_location": "Anywhere"}, int(unit.owner))
                target = self._source_nearest(unit, candidates)
                if target:
                    callback = self.source_native_paths["do_attack_target"] if mode in {"Attack", "Suicide"} else self.source_native_paths["do_defend"]
                    self._call_cdecl(self.order_callees["set_target"], [unit.address, int(target.x), int(target.y), target.address, callback])
            elif mode == "Patrol":
                x, y = state.get("point", (int(unit.x), int(unit.y)))
                self._call_cdecl(self.order_callees["set_target"], [unit.address, int(x), int(y), 0, self.order_callees["do_patrol"]])
            elif mode == "Transport":
                transport = self._source128_nearest_type(unit, IS_TRANSPORT, owner=int(unit.owner))
                if transport:
                    self._call_cdecl(self.order_callees["set_target"], [unit.address, int(transport.x), int(transport.y), transport.address, self.order_callees["do_move"]])
            elif mode == "Oil":
                oil = self._source128_nearest_type(unit, IS_OILPATCH)
                if oil:
                    self._call_cdecl(self.order_callees["set_target"], [unit.address, int(oil.x), int(oil.y), oil.address, self.source_native_paths["do_harvest"]])
            elif mode == "Spell":
                # Reuse the established safe native-aware automatic spell pass.
                super().massive_action("Auto Cast Spells Now", {"player": int(unit.owner)}, int(unit.owner))
            elif mode == "Build":
                goal = self._source128_ai_build_goals.get(int(unit.owner))
                if goal and (self._source128_flags(int(unit.unit_type)) & IS_PEON):
                    building_type, desired = goal
                    have = sum(1 for candidate in current.values() if int(candidate.owner) == int(unit.owner) and int(candidate.unit_type) == building_type)
                    if have < desired:
                        site = self._find_move_place(unit, int(unit.x) + 2, int(unit.y) + 2)
                        if site:
                            before = {candidate.address for candidate in current.values()}
                            self.action("Create Units", {"player": int(unit.owner), "new_unit": building_type, "amount": 1, "location": "Anywhere", "x": site[0], "y": site[1]}, int(unit.owner))
                            made = [candidate for candidate in self.units() if candidate.address not in before and int(candidate.unit_type) == building_type]
                            if made:
                                target = made[0]
                                self._call_cdecl(self.order_callees["set_target"], [unit.address, int(target.x), int(target.y), target.address, self.source_native_paths["do_repair"]])

        # Expire local-only minimap markers.
        now = time.monotonic()
        self._source128_minimap_markers[:] = [m for m in self._source128_minimap_markers if not m[2] or m[2] > now]

    # ------------------------------ conditions
    def massive_value(self, kind: str, args: dict[str, Any], player: int) -> Any:
        units = None
        if kind == "Source Construction Progress":
            units = [u for u in self._source_units(args, player) if int(u.unit_type) >= 58]
            if not units: return 0
            unit = units[0]; maximum = max(1, self._source128_rule_value("Maximum HP", int(unit.unit_type)))
            return max(0, min(100, round(int(unit.health) * 100 / maximum)))
        if kind == "Source Worker Is Constructing":
            units = self._source_units(args, player)
            return bool(units and (int(units[0].action) == ORDER_REPAIR or int(units[0].next_action) == ORDER_REPAIR) and int(units[0].target_unit))
        if kind in {"Source Player Can Afford Unit", "Source Player Can Afford Upgrade"}:
            owner = int(args.get("player", player))
            if kind.endswith("Unit"):
                item = int(args.get("new_unit", args.get("unit_type", 0)))
                costs = tuple(self._source128_rule_value(name, item) for name in ("Gold Cost", "Lumber Cost", "Oil Cost"))
            else:
                item = int(args.get("upgrade_id", UPGRADE_ROWS.get(str(args.get("upgrade", "Melee Attack")), 0)))
                costs = (self._source128_upgrade_rules.get(("Cost", item), 0), 0, 0)
            return all(self._read_resource(owner, res) >= cost for res, cost in zip(("Gold", "Lumber", "Oil"), costs))
        if kind == "Source Player Has Enough Food":
            owner = int(args.get("player", player)); needed = max(1, int(args.get("food", 1)))
            owned = [u for u in self.units() if int(u.owner) == owner and not (int(u.sflags) & (SF_HIDDEN | SF_DEAD))]
            supply = sum(4 for u in owned if int(u.unit_type) in {58, 59, 60, 61, 62, 63}) + sum(4 for u in owned if int(u.unit_type) in {74, 75})
            used = sum(1 for u in owned if int(u.unit_type) < 58 and not (self._source128_flags(int(u.unit_type)) & IS_DEAD))
            return max(0, supply - used) >= needed
        if kind in {"Source Building Production Type", "Source Building Production Item", "Source Production Time Remaining"}:
            buildings = [u for u in self._source_units(args, player) if int(u.unit_type) >= 58]
            if not buildings: return -1 if kind != "Source Production Time Remaining" else 0
            b = buildings[0]
            if kind == "Source Building Production Type": return self.pm.read_uchar(b.address + 0x6C)
            if kind == "Source Building Production Item": return self.pm.read_uchar(b.address + 0x6D)
            return max(0, self.pm.read_ushort(b.address + 0x70) - self.pm.read_ushort(b.address + 0x6E))
        if kind in {"Source Production Is Paused", "Source Production Is Waiting", "Source Production Queue Count", "Source Auto Train Remaining"}:
            buildings = [u for u in self._source_units(args, player) if int(u.unit_type) >= 58]
            if not buildings: return False if "Is" in kind else 0
            key = self._source_unit_key(buildings[0])
            if kind == "Source Production Is Paused": return key in self._source128_paused_production
            if kind == "Source Production Is Waiting": return bool(self._source128_queues.get(key)) and not bool(self.pm.read_ushort(buildings[0].address + 0x1C) & UF_BUILD_ON)
            if kind == "Source Production Queue Count": return len(self._source128_queues.get(key, []))
            return self._source128_auto_train.get(key, (0, 0))[1]
        if kind in {"Source Unit Can Reach Location", "Source Unit Can Reach Unit", "Source Locations On Same Island", "Source Target Path Is Valid"}:
            units = self._source_units(args, player)
            if not units: return False
            source = units[0]
            if kind in {"Source Unit Can Reach Unit", "Source Target Path Is Valid"}:
                targets = self._source_target_units(args, player); target = self._source_nearest(source, targets)
                if not target: return False
                goal = (int(target.x), int(target.y))
            else:
                goal = self._source_point(args, kind)
            if kind == "Source Locations On Same Island":
                start = self._source_point({"destination": args.get("start_location", args.get("location", "Anywhere")), "x": args.get("start_x", source.x), "y": args.get("start_y", source.y)}, kind)
            else:
                start = (int(source.x), int(source.y))
            return self._source128_reachable(source, start, goal, int(args.get("max_nodes", 768)))
        if kind.startswith("Source Last Shore"):
            return self._source128_last_shore[0 if kind.endswith("X") else 1] if self._source128_last_shore else -1
        if kind.startswith("Source Last Dock"):
            return self._source128_last_dock[0 if kind.endswith("X") else 1] if self._source128_last_dock else -1
        if kind.startswith("Source Last Undock"):
            return self._source128_last_undock[0 if kind.endswith("X") else 1] if self._source128_last_undock else -1
        if kind == "Source Predicted Native Damage":
            units = self._source_units(args, player); targets = self._source_target_units(args, player)
            target = self._source_nearest(units[0], targets) if units else None
            return self._source128_native_damage(units[0], target, False) if units and target else 0
        if kind == "Source Native Armor Reduction":
            units = self._source_target_units(args, player) or self._source_units(args, player)
            return int(self._call_cdecl(self.source_native_paths["damage_unit_armor"], [units[0].address])) if units else 0
        if kind == "Source Last Native Damage": return self._source128_last_damage
        if kind == "Source Last Terrain Damage": return self._source128_last_terrain_damage
        if kind in {"Source Location Is Visible", "Source Location Is Explored"}:
            owner = int(args.get("player", player)); x, y = self._source_point(args, kind)
            if (x, y) in self._source128_revealed.get(owner, set()): return True
            if kind.endswith("Visible"):
                for u in self.units():
                    if int(u.owner) == owner and max(abs(int(u.x)-x), abs(int(u.y)-y)) <= max(1, self._source128_rule_value("Sight", int(u.unit_type))):
                        return True
            return False
        if kind == "Source Unit Has Valid Attacker":
            units = self._source_units(args, player)
            if not units: return False
            ptr = self.pm.read_uint(units[0].address + 0x54)
            return any(u.address == ptr for u in self.units())
        if kind == "Source Unit Is Fleeing":
            units = self._source_units(args, player)
            return bool(units and self._source128_ice.get(self._source_unit_key(units[0]), {}).get("mode") == "Flee")
        if kind == "Source Tile Is Being Chopped":
            units = self._source_units(args, player)
            return bool(any((self.pm.read_uchar(u.address + 0x75) & 0x02) and int(u.action) == ORDER_HARVEST for u in units))
        if kind == "Source Tile Region Type":
            x, y = self._source_point(args, kind); tile = self.pm.read_ushort(self._source_tile_address(x, y))
            return (tile >> 12) & 0xF
        if kind in {"Source Tile Has Land Access", "Source Tile Has Water Access"}:
            units = self._source_units(args, player); x, y = self._source_point(args, kind)
            if not units: return False
            want_water = kind.endswith("Water Access")
            candidates = [u for u in units if bool(self._source128_flags(int(u.unit_type)) & (IS_SHIP | IS_TANKER | IS_TRANSPORT)) == want_water]
            return bool(candidates and self._source128_placeable(candidates[0], x, y))
        if kind == "Source Wall Is Connected":
            x, y = self._source_point(args, kind); tile = self.pm.read_ushort(self._source_tile_address(x, y))
            values = {self.pm.read_ushort(self._source_tile_address(nx, ny)) for nx, ny in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)) if 0 <= nx < self.map_width and 0 <= ny < self.map_height}
            return tile in values
        if kind == "Source Tree Is Reachable":
            units = self._source_units(args, player)
            point = self._source_point(args, kind)
            return bool(units and self._source128_reachable(units[0], (int(units[0].x), int(units[0].y)), point, int(args.get("max_nodes", 768))))
        if kind == "Source Worker Can Return Resources":
            units = self._source_units(args, player)
            if not units or not (self.pm.read_uchar(units[0].address + 0x75) & PEON_LOADED): return False
            return self._source128_find_resource(units[0], "Return") is not None
        if kind == "Source Worker Is Inside Resource":
            units = self._source_units(args, player)
            return bool(units and (int(units[0].sflags) & SF_HIDDEN) and (self.pm.read_uchar(units[0].address + 0x75) & 0x10))
        if kind.startswith("Source Last Resource"):
            return self._source128_last_resource[0 if kind.endswith("X") else 1] if self._source128_last_resource else -1
        if kind in {"Source Rune Exists At Location", "Source Rune Owner", "Source Rune Lifetime"}:
            x, y = self._source_point(args, kind); match = next((r for r in self._source128_rune_slots() if r[1] == x and r[2] == y), None)
            if kind == "Source Rune Exists At Location": return bool(match)
            if kind == "Source Rune Owner": return -1  # Warcraft's native rune table is ownerless.
            return match[3] if match else 0
        if kind in {"Source Can Cast Spell On Unit", "Source Target Is Wooden", "Source Target Is Fleshy", "Source Target Is Drainable", "Source Target Is Valid For Spell"}:
            targets = self._source_target_units(args, player)
            if not targets:
                return False
            casters = self._source_units(args, player)
            # Type-only target predicates must not depend on an unrelated caster
            # existing.  Spell predicates still require the selected caster.
            target = self._source_nearest(casters[0], targets) if casters else targets[0]
            flags = self._source128_flags(int(target.unit_type))
            if kind == "Source Target Is Fleshy": return bool(flags & IS_FLESHY)
            if kind == "Source Target Is Wooden": return bool(flags & IS_BLDG) and not bool(flags & IS_FLESHY)
            if kind == "Source Target Is Drainable": return bool(flags & IS_FLESHY) and not bool(flags & IS_DEAD)
            if not casters:
                return False
            spell = str(args.get("spell", "Holy Vision"))
            action = self._source128_spell_action(spell)
            cost = self.pm.read_ushort(self.base + CASTING_COST_TABLE_RVA + action * 2)
            enough = int(casters[0].mana) >= cost
            if kind == "Source Can Cast Spell On Unit": return enough
            return enough and (bool(flags & IS_FLESHY) or spell in {"Holy Vision", "Blizzard", "Whirlwind", "Runes"})
        if kind == "Source Spell Mana Cost":
            action = self._source128_spell_action(str(args.get("spell", "Holy Vision")))
            return self.pm.read_ushort(self.base + CASTING_COST_TABLE_RVA + action * 2)
        if kind in {"Source Projectile Hit Unit", "Source Projectile Hit Location", "Source Projectile Frozen", "Source Projectile Lifetime"}:
            missiles = self._source128_projectiles(args, player)
            if kind == "Source Projectile Frozen": return bool(missiles and missiles[0].address in self._source128_frozen_projectiles)
            if kind == "Source Projectile Lifetime": return self.pm.read_short(missiles[0].address + 0x38) if missiles else 0
            if kind == "Source Projectile Hit Unit":
                targets = self._source_target_units(args, player)
                return any(any(m.target_unit == t.address or max(abs((m.x>>5)-int(t.x)), abs((m.y>>5)-int(t.y))) <= 1 for t in targets) for m in missiles)
            x, y = self._source_point(args, kind)
            return any(max(abs((m.x>>5)-x), abs((m.y>>5)-y)) <= max(0, int(args.get("radius", 1))) for m in missiles)
        if kind in {"Source Unit Is Rescuable", "Source Unit Was Rescued", "Source Unit Is Hidden", "Source Unit Is Paused", "Source Corpse Decay Active"}:
            units = self._source_units(args, player)
            if not units: return False
            key = self._source_unit_key(units[0])
            if kind == "Source Unit Is Rescuable": return bool((self.pm.read_ushort(units[0].address + 0x1C) & UF_RESCUE) or key in self._source128_rescue_enabled)
            if kind == "Source Unit Was Rescued": return key in self._source128_rescued_recent
            if kind == "Source Unit Is Hidden": return bool(int(units[0].sflags) & SF_HIDDEN)
            if kind == "Source Unit Is Paused": return key in self._source128_paused_units or bool(int(units[0].sflags) & SF_IS_PAUSED)
            return key in self._source128_corpse_decay
        if kind == "Source ICE Strategy Active":
            units = self._source_units(args, player); return bool(units and self._source_unit_key(units[0]) in self._source128_ice)
        if kind == "Source AI Build Goal":
            return self._source128_ai_build_goals.get(int(args.get("player", player)), (-1, 0))[0]
        if kind.startswith("Source Unit Type "):
            suffix = kind.removeprefix("Source Unit Type ")
            return self._source128_rule_value(suffix, int(args.get("unit_type", args.get("unit", 0))))
        if kind in {"Source Upgrade Cost", "Source Upgrade Research Time"}:
            upgrade = int(args.get("upgrade_id", UPGRADE_ROWS.get(str(args.get("upgrade", "Melee Attack")), 0)))
            return self._source128_upgrade_rules.get(("Cost" if kind.endswith("Cost") else "Research Time", upgrade), 0)
        if kind == "Source Local Input Locked": return self._source128_input_locked
        if kind == "Source Local Mouse Button": return self._source128_local_mouse
        if kind == "Source Local Key": return int(str(args.get("key", "")).casefold() in {k.casefold() for k in self._source128_local_keys})
        return super().massive_value(kind, args, player)

    # ------------------------------ actions
    def massive_action(self, kind: str, args: dict[str, Any], player: int) -> bool:
        # Construction
        if kind in {"Source Place Building Foundation", "Source Order Worker To Build"}:
            foundations = self._source128_create_foundation(args, player)
            if kind == "Source Order Worker To Build" and foundations:
                workers = [u for u in self._source_units(args, player) if self._source128_flags(int(u.unit_type)) & IS_PEON]
                for worker in workers:
                    target = self._source_nearest(worker, foundations)
                    if target:
                        self._call_cdecl(self.order_callees["set_target"], [worker.address, int(target.x), int(target.y), target.address, self.source_native_paths["do_repair"]])
            self.log(f"SOURCE 1.28 CONSTRUCTION: {kind} created {len(foundations)} foundation(s)")
            return True
        if kind == "Source Cancel Construction":
            changed = 0
            for b in [u for u in self._source_units(args, player) if int(u.unit_type) >= 58 and not (int(u.sflags) & SF_COMPLETED)]:
                self._remove_one_unit_safely(b); changed += 1
            self.log(f"SOURCE 1.28 CONSTRUCTION: cancelled {changed} foundation(s)")
            return True
        if kind == "Source Find Nearest Building Site":
            units = self._source_units(args, player)
            if not units: raise RuntimeError("Find Nearest Building Site requires a prototype building")
            point = self._find_move_place(units[0], *self._source_point(args, kind))
            self._source_last_found_point = point; self._source128_write_variable_point(point, args, "Build Site")
            return True

        # Path helpers
        if kind in {"Source Find Shore Point", "Source Find Dock Point", "Source Find Undock Point"}:
            units = self._source_units(args, player)
            if not units: raise RuntimeError(f"{kind} requires a prototype unit")
            want = "shore" if "Shore" in kind else ("dock" if "Dock" in kind and "Undock" not in kind else "undock")
            point = self._source128_scan_point(units[0], self._source_point(args, kind), want, int(args.get("radius", 24)))
            if want == "shore": self._source128_last_shore = point
            elif want == "dock": self._source128_last_dock = point
            else: self._source128_last_undock = point
            self._source128_write_variable_point(point, args, want.title())
            self.log(f"SOURCE 1.28 PATH: {want} -> {point}")
            return True

        # Native damage
        if kind in {"Source Calculate Native Damage", "Source Deal Native Attack Damage", "Source Damage Wall With Attack"}:
            attackers = self._source_units(args, player); targets = self._source_target_units(args, player)
            if kind == "Source Damage Wall With Attack":
                targets = [u for u in self.units() if int(u.unit_type) in {103, 104} and (args.get("target_location", "Anywhere") == "Anywhere" or u in self._source_target_units({**args, "target_unit": "Any"}, player))]
            total = 0; hits = 0
            for attacker in attackers:
                target = self._source_nearest(attacker, targets)
                if not target: continue
                damage = self._source128_native_damage(attacker, target, True)
                total += damage; hits += 1
                if kind != "Source Calculate Native Damage": self._call_damage_unit(attacker, target, damage)
            self._source128_last_damage = total
            variable = str(args.get("variable", "Native Damage")); self.variables[variable] = total
            self.log(f"SOURCE 1.28 DAMAGE: {kind} {hits} hit(s), total={total}")
            return True
        if kind == "Source Damage Terrain":
            x1, y1, x2, y2 = self._source_tile_region(args, kind); amount = max(1, min(65535, int(args.get("damage", 20))))
            calls = [(self.source_native_paths["damage_damage_mtx"], [x, y, amount]) for y in range(y1, y2+1) for x in range(x1, x2+1)]
            if calls: self._call_cdecl_batched(calls)
            self._source128_last_terrain_damage = amount * len(calls)
            return True

        # Fog/minimap
        if kind in {"Source Reveal Area For Player", "Source Reveal Radius"}:
            owner = int(args.get("reveal_player", args.get("player", player)))
            if kind == "Source Reveal Radius":
                x, y = self._source_point(args, kind); radius = max(1, min(64, int(args.get("radius", 9))))
                centers = [(xx, yy) for yy in range(max(0,y-radius), min(self.map_height,y+radius+1), 18) for xx in range(max(0,x-radius), min(self.map_width,x+radius+1), 18)] or [(x,y)]
            else:
                x1,y1,x2,y2 = self._source_tile_region(args, kind)
                centers = [(x,y) for y in range(y1,y2+1,18) for x in range(x1,x2+1,18)]
            for x,y in centers: self._source128_reveal_point(owner,x,y)
            self.log(f"SOURCE 1.28 FOG: revealed {len(centers)} native 19x19 region(s) for P{owner+1}")
            return True
        if kind in {"Source Refresh Fog", "Source Refresh Minimap", "Source Refresh Terrain Minimap"}:
            # The live dispatcher already composites native fog after prep_mask_map.
            # Republish trigger-owned reveal regions; renderer/minimap reads them next tick.
            for owner, points in self._source128_revealed.items():
                for x,y in list(points)[::max(1, len(points)//64 or 1)]:
                    self._source128_reveal_point(owner,x,y)
            self.log(f"SOURCE 1.28 REFRESH: {kind} queued")
            return True

        # AI attacker/reaction
        if kind in {"Source Set Attacker", "Source Clear Attacker"}:
            units = self._source_units(args, player); targets = self._source_target_units(args, player)
            for unit in units:
                target = self._source_nearest(unit, targets) if kind == "Source Set Attacker" else None
                if target and "set_attacker" in self.damage_callees:
                    self._call_cdecl(self.damage_callees["set_attacker"], [unit.address, target.address])
                else:
                    self.pm.write_uint(unit.address + 0x54, target.address if target else 0)
            return True
        if kind in {"Source Run Native Retaliation", "Source Run Native Attack Decision"}:
            for unit in self._source_units(args, player):
                ptr = self.pm.read_uint(unit.address + 0x54)
                target = next((u for u in self.units() if u.address == ptr), None)
                if not target:
                    candidates = self._source_enemy_candidates(unit, args, player); target = self._source_nearest(unit, candidates)
                if target:
                    self._call_cdecl(self.order_callees["set_target"], [unit.address,int(target.x),int(target.y),target.address,self.source_native_paths["do_attack_target"]])
            return True
        if kind == "Source Call Nearby Units For Help":
            radius = max(1, int(args.get("radius", 8))); count = 0
            callers = self._source_units(args, player)
            for caller in callers:
                target_ptr = self.pm.read_uint(caller.address + 0x54) or int(caller.target_unit)
                target = next((u for u in self.units() if u.address == target_ptr), None)
                if not target: continue
                for ally in self.units():
                    if int(ally.owner) == int(caller.owner) and ally.address != caller.address and self._source128_distance(ally, caller) <= radius:
                        self._call_cdecl(self.order_callees["set_target"], [ally.address,int(target.x),int(target.y),target.address,self.source_native_paths["do_attack_target"]]); count += 1
            self.log(f"SOURCE 1.28 AI: called {count} helper(s)")
            return True
        if kind == "Source Force Unit To Flee":
            distance = max(2, int(args.get("radius", 8)))
            targets = self._source_target_units(args, player)
            for unit in self._source_units(args, player):
                threat = self._source_nearest(unit, targets) if targets else self._source_nearest(unit, self._source_enemy_candidates(unit,args,player))
                if not threat: continue
                dx = 1 if int(unit.x) >= int(threat.x) else -1; dy = 1 if int(unit.y) >= int(threat.y) else -1
                x = max(0,min(self.map_width-1,int(unit.x)+dx*distance)); y=max(0,min(self.map_height-1,int(unit.y)+dy*distance))
                self._call_cdecl(self.order_callees["set_target"],[unit.address,x,y,0,self.order_callees["do_move"]])
                self._source128_ice[self._source_unit_key(unit)]={"mode":"Flee","point":(x,y),"next":time.monotonic()+2.0}
            return True

        # Terrain lifecycle
        if kind in {"Source Begin Tree Harvest", "Source Cancel Tree Harvest", "Source Finish Tree Harvest"}:
            workers = self._source_units(args, player)
            if kind == "Source Begin Tree Harvest":
                x,y=self._source_point(args,kind)
                for w in workers: self._call_cdecl(self.order_callees["set_target"],[w.address,x,y,0,self.source_native_paths["do_harvest"]])
            elif kind == "Source Cancel Tree Harvest":
                for w in workers:
                    self._call_cdecl(self.move_callees["cancel_tree_harvest"],[w.address]); self.pm.write_uchar(w.address+0x75,self.pm.read_uchar(w.address+0x75)&~0x02)
            else:
                cargo=max(1,min(65535,int(args.get("cargo_amount",100))))
                for w in workers:
                    self.pm.write_uchar(w.address+0x75,PEON_LOADED|PEON_HARVEST_LUMBER); self.pm.write_ushort(w.address+0x78,cargo)
            return True
        if kind == "Source Find Reachable Tree":
            workers=self._source_units(args,player); x1,y1,x2,y2=self._source_tile_region(args,kind); raw=str(args.get("tile_values","")).strip()
            values={int(p.strip(),0)&0xffff for p in raw.replace(";",",").split(",") if p.strip()}
            point=None
            if workers and values:
                candidates=[(x,y) for y in range(y1,y2+1) for x in range(x1,x2+1) if self.pm.read_ushort(self._source_tile_address(x,y)) in values]
                candidates.sort(key=lambda p:(p[0]-int(workers[0].x))**2+(p[1]-int(workers[0].y))**2)
                point=next((p for p in candidates if self._source128_reachable(workers[0],(int(workers[0].x),int(workers[0].y)),p,int(args.get("max_nodes",768)))),None)
            self._source_last_found_point=point; self._source128_write_variable_point(point,args,"Tree")
            return True
        if kind in {"Source Native Demolish Tile", "Source Remove Terrain Region"}:
            if kind == "Source Native Demolish Tile":
                local=dict(args); local.setdefault("damage",65535); return self.massive_action("Source Damage Terrain",local,player)
            local=dict(args); local["tile"]=int(args.get("replacement_tile",0)); return super().massive_action("Source Set Tiles",local,player)
        if kind in {"Source Rebuild Wall Connections", "Source Rebuild Shore Regions", "Source Refresh Terrain Pathing"}:
            # Force native occupancy/placement validation to touch edited region and
            # invalidate local path cache.  No guessed legacy callback is called.
            self._source128_path_cache.clear()
            units=self._source_units(args,player)
            if units:
                x1,y1,x2,y2=self._source_tile_region(args,kind)
                for y in range(y1,y2+1):
                    for x in range(x1,x2+1): self._source128_placeable(units[0],x,y)
            self.log(f"SOURCE 1.28 TERRAIN: {kind} rebuilt safe placement cache")
            return True

        # Production controller
        if kind in {"Source Pause Production", "Source Resume Production", "Source Clear Production Queue", "Source Enable Continuous Training", "Source Set Auto Train Count", "Source Queue Unit"}:
            buildings=[u for u in self._source_units(args,player) if int(u.unit_type)>=58]
            for b in buildings:
                key=self._source_unit_key(b)
                if kind=="Source Pause Production":
                    self._source128_paused_production[key]=(self.pm.read_ushort(b.address+0x6E),self.pm.read_ushort(b.address+0x70),self.pm.read_uchar(b.address+0x26))
                elif kind=="Source Resume Production": self._source128_paused_production.pop(key,None)
                elif kind=="Source Clear Production Queue": self._source128_queues.pop(key,None)
                elif kind=="Source Queue Unit": self._source128_queues.setdefault(key,[]).append((BUILD_UNIT,int(args.get("new_unit",0))))
                else:
                    unit_type=int(args.get("new_unit",0)); remaining=-1 if kind=="Source Enable Continuous Training" else max(0,int(args.get("count",1)))
                    self._source128_auto_train[key]=(unit_type,remaining)
            return True

        # Resource find / worker cycles
        if kind in {"Source Find Nearest Gold Mine","Source Find Nearest Oil Patch","Source Find Nearest Return Building","Source Find Nearest Reachable Tree"}:
            workers=self._source_units(args,player); point=None
            if workers:
                mode="Gold" if "Gold" in kind else ("Oil" if "Oil" in kind else ("Return" if "Return" in kind else "Tree"))
                if mode=="Tree":
                    return self.massive_action("Source Find Reachable Tree",args,player)
                target=self._source128_find_resource(workers[0],mode); point=(int(target.x),int(target.y)) if target else None
            self._source128_last_resource=point; self._source128_write_variable_point(point,args,"Resource")
            return True
        if kind in {"Source Force Worker Into Resource Building","Source Tanker Dock"}:
            workers=self._source_units(args,player); targets=self._source_target_units(args,player)
            for worker in workers:
                target=self._source_nearest(worker,targets) or self._source128_find_resource(worker,"Oil" if kind.endswith("Dock") else "Gold")
                if target: self._call_cdecl(self.order_callees["set_target"],[worker.address,int(target.x),int(target.y),target.address,self.source_native_paths["do_harvest"]])
            return True
        if kind=="Source Force Worker Out Of Building":
            workers=self._source_units(args,player)
            for w in workers:
                self.pm.write_ushort(w.address+0x1E,self.pm.read_ushort(w.address+0x1E)&~SF_HIDDEN)
                self.pm.write_uchar(w.address+0x75,self.pm.read_uchar(w.address+0x75)&~0x14)
                point=self._find_move_place(w,max(0,int(w.x)),max(0,int(w.y)))
                if point: self._move_mobile_unit(w,point[0],point[1])
            return True
        if kind in {"Source Complete Harvest Cycle","Source Tanker Collect Oil"}:
            amount=max(1,min(65535,int(args.get("cargo_amount",100))))
            cargo_name = "Oil" if kind.endswith("Oil") else str(args.get("cargo", "Gold"))
            for w in self._source_units(args,player):
                cargo = PEON_LOADED
                if cargo_name == "Gold":
                    cargo |= PEON_HARVEST_GOLD
                elif cargo_name == "Lumber":
                    cargo |= PEON_HARVEST_LUMBER
                self.pm.write_uchar(w.address+0x75,cargo); self.pm.write_ushort(w.address+0x78,amount)
            return True
        if kind=="Source Tanker Deposit Oil":
            local=dict(args); local["cargo"]="Oil"; return super().massive_action("Source Deposit Worker Cargo",local,player)

        # Runes and spell costs
        if kind=="Source Place Rune":
            x,y=self._source_point(args,kind); owner=int(args.get("player",player)); self._call_cdecl(self.spell_path["place_rune"],[x,y]); return True
        if kind in {"Source Remove Rune","Source Set Rune Lifetime","Source Trigger Rune"}:
            x,y=self._source_point(args,kind); matches=[r for r in self._source128_rune_slots() if r[1]==x and r[2]==y]
            for slot,rx,ry,delay in matches:
                if kind=="Source Set Rune Lifetime": self.pm.write_ushort(self.base+RUNE_DELAY_RVA+slot*2,max(1,min(65535,int(args.get("lifetime",RUNE_TIME)))))
                else:
                    if kind=="Source Trigger Rune":
                        damage=max(1,int(args.get("damage",50)))
                        for unit in self.units():
                            if max(abs(int(unit.x)-x),abs(int(unit.y)-y))<=1:
                                self._call_damage_unit(unit,unit,damage)
                    self.pm.write_ushort(self.base+RUNE_DELAY_RVA+slot*2,0)
            return True
        if kind=="Source Set Spell Mana Cost":
            action=self._source128_spell_action(str(args.get("spell","Holy Vision"))); address=self.base+CASTING_COST_TABLE_RVA+action*2
            key=(address,2)
            if key not in self._source128_rule_originals: self._source128_rule_originals[key]=self.pm.read_bytes(address,2)
            self.pm.write_ushort(address,max(0,min(65535,int(args.get("mana_cost",0)))))
            return True

        # Projectiles
        if kind.startswith("Source Set Projectile ") or kind in {"Source Freeze Projectile","Source Resume Projectile"}:
            missiles=self._source128_projectiles(args,player)
            for m in missiles:
                if kind=="Source Set Projectile Type": self.pm.write_uchar(m.address+0x34,max(0,min(28,int(args.get("new_missile",args.get("missile_type",0))))))
                elif kind=="Source Set Projectile Owner":
                    owners=self._source_target_units(args,player) or self._source_units(args,player); self.pm.write_uint(m.address+0x30,owners[0].address if owners else 0)
                elif kind=="Source Set Projectile Damage": self.pm.write_uchar(m.address+0x37,max(0,min(255,int(args.get("damage",0)))))
                elif kind=="Source Set Projectile Speed": self._source128_projectile_speed[m.address]=max(1,min(400,int(args.get("speed",100))))
                elif kind=="Source Set Projectile Lifetime": self.pm.write_short(m.address+0x38,max(-32768,min(32767,int(args.get("lifetime",60)))))
                elif kind=="Source Set Projectile Action": self.pm.write_uchar(m.address+0x36,max(0,min(255,int(args.get("projectile_action",0)))))
                elif kind=="Source Set Projectile Target":
                    targets=self._source_target_units(args,player)
                    owner_unit=next((u for u in self.units() if u.address==m.owner_unit),None)
                    target=(self._source_nearest(owner_unit,targets) if owner_unit else targets[0]) if targets else None
                    if target:
                        self.pm.write_short(m.address+0x28,int(target.x)<<5); self.pm.write_short(m.address+0x2A,int(target.y)<<5); self.pm.write_uint(m.address+0x2C,target.address)
                    else:
                        x,y=self._source_point(args,kind); self.pm.write_short(m.address+0x28,x<<5); self.pm.write_short(m.address+0x2A,y<<5); self.pm.write_uint(m.address+0x2C,0)
                elif kind=="Source Freeze Projectile": self._source128_frozen_projectiles[m.address]=self._source128_freeze_projectile_snapshot(m)
                elif kind=="Source Resume Projectile": self._source128_frozen_projectiles.pop(m.address,None)
            return True
        if kind in {"Source Create Tower Projectile","Source Create Fire Projectile","Source Create Flame Spin","Source Create Black X Marker","Source Create Stationary Projectile"}:
            defaults={"Source Create Tower Projectile":3,"Source Create Fire Projectile":17,"Source Create Flame Spin":22,"Source Create Black X Marker":20,"Source Create Stationary Projectile":18}
            local=dict(args); local["missile"]=int(args.get("new_missile",defaults[kind])); super().massive_action("Source Create Projectile At Point",local,player)
            if kind=="Source Create Stationary Projectile":
                recent=sorted(self._active_missiles(),key=lambda m:m.address,reverse=True)[:max(1,int(args.get("count",1)))]
                for m in recent: self._source128_frozen_projectiles[m.address]=self._source128_freeze_projectile_snapshot(m)
            return True

        # Sound extensions route through validated contextual sound callbacks.
        sound_kinds = {
                "Source Play Acknowledgement Sound", "Source Play Attack Response Sound",
                "Source Play Build Started Sound", "Source Play Building Complete Sound",
                "Source Play Unit Created Sound", "Source Play Unit Loaded Sound",
                "Source Play Rescue Sound", "Source Play Capture Sound", "Source Play Dock Sound",
                "Source Play Error Sound", "Source Play Impact Sound",
                "Source Play Projectile Sound", "Source Play Arrow Sound",
                "Source Play Cannon Sound", "Source Play Sparkle Sound",
            }
        if kind in sound_kinds:
            mapping={
                "Source Play Acknowledgement Sound":"Selection", "Source Play Attack Response Sound":"Selection",
                "Source Play Build Started Sound":"Harvest", "Source Play Building Complete Sound":"Selection",
                "Source Play Unit Created Sound":"Selection", "Source Play Unit Loaded Sound":"Selection",
                "Source Play Rescue Sound":"Selection", "Source Play Capture Sound":"Selection", "Source Play Dock Sound":"Selection",
                "Source Play Error Sound":"Under Attack", "Source Play Impact Sound":"Unit Death",
                "Source Play Projectile Sound":"Spell", "Source Play Arrow Sound":"Spell",
                "Source Play Cannon Sound":"Spell", "Source Play Sparkle Sound":"Spell",
            }
            local=dict(args); local["event"]=mapping[kind]; return super().massive_action("Source Play Unit Sound",local,player)

        # Rescue and lifecycle
        if kind in {"Source Enable Unit Rescue","Source Disable Unit Rescue"}:
            for u in self._source_units(args,player):
                key=self._source_unit_key(u)
                if kind.endswith("Enable Unit Rescue"):
                    self._source128_rescue_enabled.add(key); self.pm.write_ushort(u.address+0x1C,self.pm.read_ushort(u.address+0x1C)|UF_RESCUE)
                else:
                    self._source128_rescue_enabled.discard(key); self.pm.write_ushort(u.address+0x1C,self.pm.read_ushort(u.address+0x1C)&~UF_RESCUE)
            return True
        if kind=="Source Check Rescue Now":
            # Maintenance performs the same deterministic range check immediately on next cycle.
            for u in self._source_units(args,player): self._source128_rescue_enabled.add(self._source_unit_key(u))
            return True
        if kind in {"Source Hide Unit Natively","Source Show Unit Natively"}:
            for u in self._source_units(args,player):
                flags=self.pm.read_ushort(u.address+0x1E)
                if kind.startswith("Source Hide"):
                    self._dispatch_ops([("call",self.move_callees["cancel_tree_harvest"],[u.address]),("call",self.move_callees["unplace_man"],[u.address]),("write_word",u.address+0x1E,flags|SF_HIDDEN)])
                else:
                    self.pm.write_ushort(u.address+0x1E,flags&~SF_HIDDEN)
                    point=self._find_move_place(u,max(0,int(u.x)),max(0,int(u.y)))
                    if point: self._move_mobile_unit(u,*point)
            return True
        if kind in {"Source Pause Individual Unit","Source Resume Individual Unit"}:
            for u in self._source_units(args,player):
                key=self._source_unit_key(u)
                if kind.startswith("Source Pause"):
                    self._source128_paused_units[key]={"x":int(u.x),"y":int(u.y),"action":int(u.action),"next":int(u.next_action)}
                else:
                    state=self._source128_paused_units.pop(key,None)
                    self.pm.write_ushort(u.address+0x1E,self.pm.read_ushort(u.address+0x1E)&~(SF_IS_PAUSED|SF_PAUSE_TOGGLE))
                    self.pm.write_uchar(u.address+0x2E,state["action"] if state else ORDER_GUARD); self.pm.write_uchar(u.address+0x2F,state["next"] if state else ORDER_NONE)
            return True
        if kind in {"Source Kill Transport Occupants","Source Eject Transport Occupants"}:
            transports=[u for u in self._source_units(args,player) if self._source128_flags(int(u.unit_type))&IS_TRANSPORT]
            for t in transports:
                for slot in self._source_transport_slots(t):
                    cargo=self._source_transport_unit(slot)
                    if not cargo: continue
                    if kind.startswith("Source Kill"): self._call_damage_unit(t,cargo,65535)
                    else: self._call_cdecl(self.source_native_paths["unit_unload_transport"],[t.address,cargo.address])
            return True
        if kind in {"Source Begin Corpse Decay","Source Stop Corpse Decay"}:
            for u in self._source_units(args,player):
                key=self._source_unit_key(u)
                if kind.startswith("Source Begin"): self._source128_corpse_decay.add(key); self.pm.write_uchar(u.address+0x07,max(1,int(args.get("timer",30)))&0xff)
                else: self._source128_corpse_decay.discard(key); self.pm.write_uchar(u.address+0x07,0)
            return True
        if kind in {"Source Set Current Native Action","Source Set Next Native Action"}:
            value=max(0,min(255,int(args.get("native_action",ORDER_GUARD))))
            for u in self._source_units(args,player):
                if "Current" in kind: self._call_cdecl(self.move_callees["set_curr_action"],[u.address,value])
                else: self.pm.write_uchar(u.address+0x2F,value)
            return True

        # Safe ICE controllers
        if kind.startswith("Source Run Native ") or kind in {"Source Attack Specific Player","Source Attack Strongest Player","Source Force AI Suicide Attack"}:
            mode="Attack"
            if "Patrol" in kind: mode="Patrol"
            elif "Guard" in kind: mode="Guard"
            elif "Defend" in kind: mode="Defend"
            elif "Transport" in kind: mode="Transport"
            elif "Oil" in kind: mode="Oil"
            elif "Suicide" in kind: mode="Suicide"
            elif "Spell" in kind: mode="Spell"
            elif "Build" in kind: mode="Build"
            target_player=int(args.get("target_player",-1))
            if kind=="Source Attack Strongest Player":
                counts={p:sum(1 for u in self.units() if int(u.owner)==p) for p in range(8)}; target_player=max(counts,key=counts.get)
            point=self._source_point(args,kind) if mode=="Patrol" else (0,0)
            for u in self._source_units(args,player): self._source128_ice[self._source_unit_key(u)]={"mode":mode,"target_player":target_player,"point":point,"cadence":float(args.get("cadence",0.75)),"next":0.0}
            return True
        if kind=="Source Set AI Build Goal":
            owner=int(args.get("player",player)); self._source128_ai_build_goals[owner]=(int(args.get("new_building",58)),max(1,int(args.get("count",1)))); return True

        # Rules
        if kind.startswith("Source Set Unit Type "):
            suffix=kind.removeprefix("Source Set Unit Type "); unit_type=int(args.get("unit_type",args.get("unit",0))); value=int(args.get("value",args.get("rule_value",0)))
            self._source128_set_rule(suffix,unit_type,value)
            # Apply HP/speed/sight virtual rules to live units immediately where possible.
            if suffix=="Maximum HP" and bool(args.get("apply_to_existing",True)):
                for u in self.units():
                    if int(u.unit_type)==unit_type: self.pm.write_ushort(u.address+0x22,min(value,max(1,int(u.health))))
            if suffix=="Speed" and bool(args.get("apply_to_existing",True)):
                # Warcraft timers use Haste/Slow status; 100 is normal, >100 haste.
                for u in self.units():
                    if int(u.unit_type)==unit_type:
                        self.pm.write_ushort(u.address+0x4A,0x7fff if value>100 else 0)
            self.log(f"SOURCE 1.28 RULE: unit {unit_type} {suffix}={value}")
            return True
        if kind in {"Source Set Upgrade Cost","Source Set Upgrade Research Time"}:
            upgrade=int(args.get("upgrade_id",UPGRADE_ROWS.get(str(args.get("upgrade","Melee Attack")),0))); value=max(0,int(args.get("value",args.get("cost",args.get("research_time",0)))))
            self._source128_upgrade_rules[("Cost" if kind.endswith("Cost") else "Research Time",upgrade)]=value; return True
        if kind=="Source Restore Vanilla Unit Type":
            self._source128_restore_unit_rules(int(args.get("unit_type",args.get("unit",0)))); return True
        if kind=="Source Restore All Vanilla Rules":
            for (address,size),blob in list(self._source128_rule_originals.items()): self.pm.write_bytes(address,blob,size)
            self._source128_rule_originals.clear(); self._source128_virtual_rules.clear(); self._source128_upgrade_rules.clear(); return True

        # Local interface helpers.  These are deliberately local and never feed
        # synchronized gameplay conditions unless the author explicitly uses them.
        if kind in {"Source Pause Game","Source Resume Game"}:
            self.game_state="Paused" if kind.endswith("Pause Game") else "Playing"; self.log(f"SOURCE LOCAL: {self.game_state}"); return True
        if kind in {"Source Select Units","Source Deselect Units"}:
            for u in self._source_units(args,player):
                flags=self.pm.read_ushort(u.address+0x1E); self.pm.write_ushort(u.address+0x1E,(flags|SF_SELECTED) if kind.startswith("Source Select") else (flags&~SF_SELECTED))
            return True
        if kind in {"Source Lock Player Input","Source Unlock Player Input"}:
            self._source128_input_locked=kind.startswith("Source Lock"); return True
        if kind=="Source Show Minimap Marker":
            x,y=self._source_point(args,kind); duration=max(0.0,float(args.get("duration",3.0))); self._source128_minimap_markers.append((x,y,time.monotonic()+duration if duration else 0.0)); return True
        if kind=="Source Clear Minimap Markers": self._source128_minimap_markers.clear(); return True
        if kind=="Source Set Local Camera":
            local=dict(args); local["location"]=args.get("destination",args.get("location","Anywhere")); return super().massive_action("Center Camera",local,player)
        if kind in {"Source Set Selected Unit Card","Source Play Local Cinematic","Source Show Local Dialog"}:
            # The Remaster UI owns these local surfaces.  Preserve the authored
            # intent as a native-safe message instead of calling legacy dialog pointers.
            text=str(args.get("text",args.get("message",kind)))
            self.action("Game Message",{"message":text,"player":player},player)
            return True

        return super().massive_action(kind,args,player)
