from __future__ import annotations

from dataclasses import dataclass, field
import json
import math
import random
import struct
import time
from typing import Any

from massive_features import (
    MASSIVE_UNHANDLED,
    MassiveFeatureMixin,
    ORDER_ACTIONS,
    STATUS_OFFSETS,
    UNIT_HP_TABLE_RVA,
)


# Warcraft II source spell bit order. These are the bits stored in glSpells and
# glSpellsAllowed for each player. The gaps in the original source enum are
# intentionally preserved by the explicit indices below.
SPELL_BITS: dict[str, int] = {
    "Holy Vision": 0,
    "Healing": 1,
    "Area Heal": 2,
    "Exorcism": 3,
    "Flame Shield": 4,
    "Fireball": 5,
    "Slow": 6,
    "Invisibility": 7,
    "Polymorph": 8,
    "Blizzard": 9,
    "Eye of Kilrogg": 10,
    "Bloodlust": 11,
    "Hallucinate": 12,
    "Raise Dead": 13,
    "Death Coil": 14,
    "Whirlwind": 15,
    "Haste": 16,
    "Unholy Armor": 17,
    "Runes": 18,
    "Death and Decay": 19,
    "Paladin / Ogre-Mage Conversion": 20,
}
SPELL_MASK = sum(1 << bit for bit in SPELL_BITS.values())

# Source sgbTechTbl row order. Each row contains one byte per player.
UPGRADE_ROWS: dict[str, int] = {
    "Ranged Attack": 0,
    "Melee Attack": 1,
    "Armor": 2,
    "Ship Attack": 3,
    "Ship Armor": 4,
    "Ship Speed": 5,
    "Siege Damage": 6,
    "Ranger / Berserker": 7,
    "Longbow / Light Axes": 8,
    "Scouting": 9,
    "Marksmanship / Regeneration": 10,
}

SAPPER_TYPES = {14, 15}
MOBILE_MAX = 57
DEAD_FLAG_MASK = 0x0007
HIDDEN_FLAG = 0x0008

# Native-verified unit movement-class table used by Warcraft II Remastered 1.0.2.2818.
# TD 1.28.6 temporarily converts naval/mobile-inert roster entries to flyers so every
# mobile unit slot can participate in a land-path tower-defense wave.
UNIT_IS_TABLE_RVA = 0x5185F0
# gbUnitClassTbl: native-verified class byte used by unit_create/mtx_unit_placeable.
# 1.0.2.2818 unit_create loads [unitType + module+0x518310] before placement.
UNIT_CLASS_TABLE_RVA = 0x518310
CLASS_LAND = 0
CLASS_AIR = 1
CLASS_WATER = 2
CLASS_WATER_CANDOCK = 3
IS_WALKING = 0x00000001
IS_FLYER = 0x00000002
IS_ROLLING = 0x00000004
IS_SHIP = 0x00000008
IS_MONSTER = 0x00000010
IS_TANKER = 0x00000200
IS_TRANSPORT = 0x00000400
TD_WATER_FLAGS = IS_SHIP | IS_TANKER | IS_TRANSPORT
TD_MOBILE_FLAGS = IS_WALKING | IS_FLYER | IS_ROLLING | IS_SHIP | IS_MONSTER

# Canonical Warcraft II mobile unit IDs 0-57. The five reserved/unused slots are
# intentionally excluded from the Native HP Ladder campaign. This corrects the
# older shifted 1.28.6 display list after Deathwing.
TD_UNUSED_MOBILE_TYPES = frozenset({34, 36, 37, 48, 54})
TD_MOBILE_NAMES = (
    "Footman", "Grunt", "Peasant", "Peon", "Ballista", "Catapult", "Knight", "Ogre",
    "Archer", "Axethrower", "Mage", "Death Knight", "Paladin", "Ogre-Mage", "Dwarves", "Goblin Sappers",
    "Attack Peasant", "Attack Peon", "Ranger", "Berserker", "Alleria", "Teron Gorefiend", "Kurdan and Sky'ree", "Dentarg",
    "Khadgar", "Grom Hellscream", "Human Tanker", "Orc Tanker", "Human Transport", "Orc Transport",
    "Elven Destroyer", "Troll Destroyer", "Battleship", "Juggernaught", "Unused A100", "Deathwing",
    "Unused H Minelayer", "Unused O Minelayer", "Gnomish Submarine", "Giant Turtle",
    "Gnomish Flying Machine", "Goblin Zeppelin", "Gryphon Rider", "Dragon", "Turalyon", "Eye of Kilrogg",
    "Danath", "Korgath Bladefist", "Unused 0x30", "Cho'gall", "Lothar", "Gul'dan",
    "Uther Lightbringer", "Zul'jin", "Unused 0x36", "Skeleton", "Daemon", "Critter",
)


@dataclass
class TimedEffect:
    kind: str
    expires_at: float
    amount: float = 0.0
    interval: float = 1.0
    next_tick: float = 0.0
    source_ref: str = ""
    radius: int = 0
    chance: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class WaveDirectorState:
    name: str
    owner: int
    unit_pool: list[int]
    spawn_location: str
    spawn_x: int
    spawn_y: int
    destination: str
    destination_x: int
    destination_y: int
    base_count: int
    growth: int
    intermission: float
    max_waves: int
    boss_every: int
    boss_unit: int
    formation: str
    spacing: int
    group_prefix: str
    wave: int = 0
    active: bool = True
    waiting_until: float = 0.0
    current_group: str = ""
    completed: bool = False


@dataclass
class TDStreamUnitProgress:
    stage: int = 0
    lane: int = 0
    target_x: int = 0
    target_y: int = 0
    last_x: int = -1
    last_y: int = -1
    last_progress_at: float = 0.0
    last_order_at: float = 0.0
    spawn_rescues: int = 0
    hard_rescues: int = 0


@dataclass
class TDStreamWaveState:
    name: str
    owner: int
    unit_roster: list[int]
    total: int
    batch_size: int
    interval: float
    spawn_location: str
    spawn_x: int
    spawn_y: int
    route: list[str]
    max_hp: int
    mana: int
    group: str
    max_spawn_queue: int
    stall_reissue: float
    spawn_rescue_after: float
    lane_count: int = 3
    naval_as_flying: bool = True
    next_spawn_at: float = 0.0
    spawned: int = 0
    last_spawn_at: float = 0.0
    spawn_finished_at: float = 0.0
    active: bool = True
    completed: bool = False
    progress: dict[tuple[int, int], TDStreamUnitProgress] = field(default_factory=dict)
    overridden_types: set[int] = field(default_factory=set)


@dataclass
class TDNativeHPLadderState:
    name: str
    owner: int
    plan: list[dict[str, int]]
    batch_size: int
    interval: float
    first_wave_delay: float
    intermission: float
    spawn_location: str
    spawn_x: int
    spawn_y: int
    route: list[str]
    lane_count: int
    naval_as_flying: bool
    mana: int
    max_spawn_queue: int
    stall_reissue: float
    spawn_rescue_after: float
    builder_player: int = 5
    builder_unit: int = 11
    builder_refill_mana: int = 255
    next_wave_index: int = 0
    active_stream: str = ""
    waiting_until: float = 0.0
    active: bool = True
    completed: bool = False


@dataclass
class BossControllerState:
    name: str
    reference: str
    phases: list[dict[str, Any]]
    current_phase: int = 0
    active: bool = True


class UltimateFeatureMixin(MassiveFeatureMixin):
    """1.25 systems layered above the proven 1.24.7 runtime.

    This mixin deliberately leaves WT30 vision, the simulation dispatcher,
    attack-route acquisition, even-aligned placement, and atomic auto-spells in
    the base adapter. New systems use exact allocation tokens and existing native
    primitives so stale unit records are never retained as raw pointers.
    """

    def _init_massive_features(self) -> None:
        super()._init_massive_features()
        self.unit_references: dict[str, tuple[int, int]] = {}
        self.player_spell_grants: dict[int, set[str]] = {}
        self.player_upgrade_levels: dict[int, dict[str, int]] = {}
        self.player_tech_flags: dict[int, set[str]] = {}
        self._progression_tables: dict[str, int] | None = None
        self._progression_resolution_error: str = ""
        self.custom_effects: dict[tuple[int, int], dict[str, TimedEffect]] = {}
        self.combat_traits: dict[tuple[int, int], dict[str, float]] = {}
        self.tactical_ai: dict[str, dict[str, Any]] = {}
        self.wave_directors: dict[str, WaveDirectorState] = {}
        self.td_stream_waves: dict[str, TDStreamWaveState] = {}
        self.td_native_hp_ladders: dict[str, TDNativeHPLadderState] = {}
        self._td_stream_type_overrides: dict[int, dict[str, Any]] = {}
        self.boss_controllers: dict[str, BossControllerState] = {}
        self.hero_state: dict[tuple[int, int], dict[str, Any]] = {}
        self.inventory: dict[tuple[int, int], dict[str, int]] = {}
        self.quests: dict[str, str] = {}
        self.periodic_income: dict[str, dict[str, Any]] = {}
        self._previous_missiles: dict[int, Any] = {}
        self.projectile_created: list[Any] = []
        self.projectile_expired: list[Any] = []
        self._iteration_context: dict[str, Any] = {}
        self._ultimate_next_maintenance = 0.0
        self._ultimate_rng = random.Random(time.time_ns() ^ 0x1250)

    def _massive_begin_run(self) -> None:
        # A trigger restart must never leave a previous wave's global HP/movement
        # table overrides behind. Restore first, then reset runtime state.
        if getattr(self, "pm", None):
            self._td_stream_restore_all_type_overrides()
        super()._massive_begin_run()
        self.unit_references.clear()
        self.player_spell_grants.clear()
        self.player_upgrade_levels.clear()
        self.player_tech_flags.clear()
        self.custom_effects.clear()
        self.combat_traits.clear()
        self.tactical_ai.clear()
        self.wave_directors.clear()
        self.td_stream_waves.clear()
        self.td_native_hp_ladders.clear()
        self.boss_controllers.clear()
        self.hero_state.clear()
        self.inventory.clear()
        self.quests.clear()
        self.periodic_income.clear()
        self._previous_missiles = {m.address: m for m in self._active_missiles()} if getattr(self, "pm", None) else {}
        self.projectile_created = []
        self.projectile_expired = []
        self._iteration_context.clear()
        self._ultimate_next_maintenance = 0.0

    # ---------------------------------------------------------------- refs
    def _resolve_unit_reference(self, name: Any) -> Any | None:
        key = str(name or "Unit Reference 1").strip()
        marker = self.unit_references.get(key)
        if marker is None:
            return None
        current = getattr(self, "_snapshot", {})
        unit = current.get(marker)
        if unit is None:
            # Refresh directly because reference actions can run after a native
            # create/replace action but before the next normal event snapshot.
            unit = next((candidate for candidate in self.units() if self._unit_key_massive(candidate) == marker), None)
        if unit is None or int(unit.sflags) & DEAD_FLAG_MASK:
            self.unit_references.pop(key, None)
            return None
        return unit

    def _save_reference(self, name: Any, unit: Any | None) -> None:
        key = str(name or "Unit Reference 1").strip()
        if not key:
            raise ValueError("Unit reference name cannot be blank")
        if unit is None:
            self.unit_references.pop(key, None)
            return
        self.unit_references[key] = self._unit_key_massive(unit)

    @staticmethod
    def _distance_sq(a: Any, b: Any) -> int:
        return (int(a.x) - int(b.x)) ** 2 + (int(a.y) - int(b.y)) ** 2

    def _pick_reference_unit(self, args: dict[str, Any], player: int) -> Any | None:
        source = str(args.get("source", "Matching units"))
        if source == "Event unit":
            return self._event_unit()
        if source == "Last created unit":
            units = list(getattr(self, "created_units", []))
            return units[-1] if units else None
        if source == "Unit group":
            units = self._group_units(args.get("group", "Unit Group 1"))
        else:
            units = self._selected_units(args, player)
        if not units:
            return None
        selection = str(args.get("selection", "First matching"))
        if selection == "Random":
            return self._ultimate_rng.choice(units)
        if selection == "Most wounded":
            return min(units, key=lambda u: (int(u.health) / max(1, self._max_hp(u)), int(u.address)))
        if selection == "Highest health":
            return max(units, key=lambda u: (int(u.health), -int(u.address)))
        if selection in {"Nearest to reference", "Farthest from reference"}:
            anchor = self._resolve_unit_reference(args.get("anchor_reference", "Anchor"))
            if anchor is None:
                return units[0]
            reverse = selection.startswith("Farthest")
            return sorted(units, key=lambda u: (self._distance_sq(anchor, u), int(u.address)), reverse=reverse)[0]
        return units[0]

    # ------------------------------------------------------- progression tables
    @staticmethod
    def _dwords(blob: bytes) -> list[int]:
        return list(struct.unpack("<" + "I" * (len(blob) // 4), blob))

    def _resolve_progression_tables(self) -> dict[str, int]:
        if self._progression_tables is not None:
            return self._progression_tables
        if self._progression_resolution_error:
            raise RuntimeError(self._progression_resolution_error)
        if not getattr(self, "pm", None):
            raise RuntimeError("Progression tables require a live attachment")

        image = self.pm.read_bytes(self.base, self.image_size)
        code = image[: min(len(image), 0x510000)]

        # 1.0.2.2818 native-verified progression globals.  Live testing showed the
        # old state-content scanner was too strict on custom maps: it rejected the
        # real arrays when only one active player had nonzero allowed bits.  Resolve
        # the arrays from the exact cheat-all-spells code shape instead.  The source
        # cheat routine writes glSpells[i]=glSpellsAllowed[i]=0xffffffff and
        # glSpellsInProcess[i]=0 for each non-computer slot.
        result = None
        if int(getattr(self, "build_timestamp", 0)) == 0x699E13E7:
            direct_rvas = (0x519250, 0x519290, 0x5192D0)
            probe_rva = 0x0B3E19
            probe = self.pm.read_bytes(self.base + probe_rva, 0x21)
            expected_ops = (
                b"\xC7\x04\x85", b"\xFF\xFF\xFF\xFF",
                b"\xC7\x04\x85", b"\xFF\xFF\xFF\xFF",
                b"\xC7\x04\x85", b"\x00\x00\x00\x00",
            )
            valid_shape = (
                len(probe) >= 0x21
                and probe[0:3] == expected_ops[0]
                and probe[7:11] == expected_ops[1]
                and probe[11:14] == expected_ops[2]
                and probe[18:22] == expected_ops[3]
                and probe[22:25] == expected_ops[4]
                and probe[29:33] == expected_ops[5]
            )
            if valid_shape:
                refs = (
                    struct.unpack_from("<I", probe, 3)[0],
                    struct.unpack_from("<I", probe, 14)[0],
                    struct.unpack_from("<I", probe, 25)[0],
                )
                expected_refs = tuple(self.base + rva for rva in direct_rvas)
                if refs == expected_refs:
                    result = {
                        "spells": refs[0],
                        "spells_allowed": refs[1],
                        "spells_in_process": refs[2],
                        # The source globals remain contiguous 0x40-byte player arrays.
                        "tech_allowed": self.base + 0x519310,
                        "tech_in_process": self.base + 0x519350,
                    }
                    self.log(
                        "PROGRESSION TABLES: native-verified direct cheat-xref validation "
                        "validation accepted glSpells/glSpellsAllowed/glSpellsInProcess"
                    )

        # Fallback for other supported builds: retain the conservative content/xref scan.
        if result is None:
            start = 0x500000
            stop = min(len(image) - 0x140, 0x620000)
            candidates: list[tuple[int, int, tuple[list[int], ...]]] = []
            for offset in range(start, stop, 4):
                chunk = image[offset:offset + 0x140]
                arrays = tuple(self._dwords(chunk[index:index + 0x40]) for index in range(0, 0x140, 0x40))
                spells, allowed, spell_in, tech_allowed, tech_in = arrays
                if any(value & ~SPELL_MASK for value in spells + allowed + spell_in):
                    continue
                if any(value & ~0xFFFFFFFF for value in tech_allowed + tech_in):
                    continue
                if sum(value != 0 for value in allowed[:8]) < 1:
                    continue
                if sum(value == 0 for value in spell_in) < 8 or sum(value == 0 for value in tech_in) < 8:
                    continue
                if any(spells[i] & ~allowed[i] for i in range(8)):
                    continue
                addresses = [self.base + offset + index * 0x40 for index in range(5)]
                xrefs = [code.count(struct.pack("<I", address)) for address in addresses]
                score = xrefs[0] * 3 + xrefs[1] * 2 + xrefs[2] * 3 + xrefs[3] + xrefs[4] * 2
                if xrefs[0] >= 1 and xrefs[1] >= 1:
                    candidates.append((score, offset, arrays))
            if not candidates:
                self._progression_resolution_error = "Native-verified spell/technology array resolver found no validated candidate"
                raise RuntimeError(self._progression_resolution_error)
            candidates.sort(reverse=True)
            if len(candidates) > 1 and candidates[0][0] <= candidates[1][0] + 2:
                self._progression_resolution_error = (
                    "Native-verified spell/technology array scan was ambiguous: "
                    + ", ".join(f"RVA 0x{offset:X} score {score}" for score, offset, _ in candidates[:4])
                )
                raise RuntimeError(self._progression_resolution_error)
            _score, offset, _arrays = candidates[0]
            result = {
                "spells": self.base + offset,
                "spells_allowed": self.base + offset + 0x40,
                "spells_in_process": self.base + offset + 0x80,
                "tech_allowed": self.base + offset + 0xC0,
                "tech_in_process": self.base + offset + 0x100,
            }

        # Resolve sgbTechTbl from the source-matched tech completion function.
        tech_in_bytes = struct.pack("<I", result["tech_in_process"])
        windows: list[bytes] = []
        position = 0
        while True:
            hit = code.find(tech_in_bytes, position)
            if hit < 0:
                break
            windows.append(code[max(0, hit - 0x180): min(len(code), hit + 0x280)])
            position = hit + 1
        tech_candidates: dict[int, int] = {}
        for window in windows:
            for pos in range(0, max(0, len(window) - 4)):
                address = struct.unpack_from("<I", window, pos)[0]
                rva = address - self.base
                if not 0x500000 <= rva <= self.image_size - 176:
                    continue
                if address in result.values():
                    continue
                table = image[rva:rva + 176]
                if len(table) != 176 or any(value > 4 for value in table):
                    continue
                # The unused P9-P16 half of each row is normally zero in an
                # eight-player match, making the real row-major table distinctive.
                zero_tail = sum(1 for row in range(11) for value in table[row * 16 + 8:row * 16 + 16] if value == 0)
                if zero_tail < 72:
                    continue
                refs = code.count(struct.pack("<I", address))
                tech_candidates[address] = refs * 10 + zero_tail
        if tech_candidates:
            ranked = sorted(((score, address) for address, score in tech_candidates.items()), reverse=True)
            if len(ranked) == 1 or ranked[0][0] > ranked[1][0] + 5:
                result["tech_levels"] = ranked[0][1]

        self._progression_tables = result
        self.log(
            "PROGRESSION TABLES: "
            + ", ".join(f"{name}=RVA 0x{address - self.base:X}" for name, address in result.items())
        )
        return result

    def _spell_mask_value(self, name: Any) -> tuple[str, int]:
        text = str(name or "Healing").strip()
        canonical = next((label for label in SPELL_BITS if label.casefold() == text.casefold()), None)
        if canonical is None:
            raise ValueError(f"Unknown spell research: {text}")
        return canonical, 1 << SPELL_BITS[canonical]

    def _upgrade_row_value(self, name: Any) -> tuple[str, int]:
        text = str(name or "Melee Attack").strip()
        canonical = next((label for label in UPGRADE_ROWS if label.casefold() == text.casefold()), None)
        if canonical is None:
            raise ValueError(f"Unknown upgrade category: {text}")
        return canonical, UPGRADE_ROWS[canonical]

    # --------------------------------------------------------------- effects
    def _effect_bucket(self, unit: Any) -> dict[str, TimedEffect]:
        return self.custom_effects.setdefault(self._unit_key_massive(unit), {})

    def _effect_active(self, unit: Any, kind: str) -> bool:
        effect = self.custom_effects.get(self._unit_key_massive(unit), {}).get(kind)
        return bool(effect and effect.expires_at > time.monotonic())

    def _apply_custom_effect(self, unit: Any, effect: TimedEffect) -> None:
        effect.next_tick = time.monotonic() + max(0.05, effect.interval)
        self._effect_bucket(unit)[effect.kind] = effect

    def _infer_attacker(self, victim: Any, world: list[Any]) -> Any | None:
        candidates = [
            unit for unit in world
            if int(getattr(unit, "target_unit", 0)) == int(victim.address)
            and int(getattr(unit, "owner", -1)) != int(victim.owner)
            and not (int(unit.sflags) & (DEAD_FLAG_MASK | HIDDEN_FLAG))
        ]
        return min(candidates, key=lambda u: (self._distance_sq(u, victim), int(u.address))) if candidates else None

    def _maintain_custom_effects(self, world: list[Any], now: float) -> None:
        current = {self._unit_key_massive(unit): unit for unit in world}
        for key, effects in list(self.custom_effects.items()):
            unit = current.get(key)
            if unit is None:
                self.custom_effects.pop(key, None)
                self.combat_traits.pop(key, None)
                continue
            for name, effect in list(effects.items()):
                if effect.expires_at <= now:
                    effects.pop(name, None)
                    continue
                if name in {"Stun", "Root", "Fear"}:
                    # A target-less Move to the current tile is a stable native
                    # parking order and avoids raw unit target pointers.
                    if int(unit.target_unit) or (int(unit.target_x), int(unit.target_y)) != (int(unit.x), int(unit.y)):
                        self._call_cdecl(
                            self.order_callees["set_target"],
                            [unit.address, int(unit.x), int(unit.y), 0, self.order_callees["do_move"]],
                        )
                if name == "Taunt":
                    source = self._resolve_unit_reference(effect.source_ref)
                    if source is not None:
                        self._call_cdecl(
                            self.order_callees["set_target"],
                            [unit.address, int(source.x), int(source.y), source.address, self.order_callees["do_attack"]],
                        )
                if name in {"Damage Over Time", "Healing Over Time"} and now >= effect.next_tick:
                    amount = max(1, int(effect.amount))
                    if name == "Damage Over Time":
                        source = self._resolve_unit_reference(effect.source_ref) or unit
                        self._call_damage_unit(source, unit, amount)
                    else:
                        hp = min(self._max_hp(unit), int(unit.health) + amount)
                        self._dispatch_ops([("write_word", unit.address + 0x22, hp)])
                    effect.next_tick = now + max(0.05, effect.interval)
            if not effects:
                self.custom_effects.pop(key, None)

        # Post-hit traits use the already prepared damage events. They are
        # deliberately bounded to one response per victim per engine cycle.
        for key, damage in list(getattr(self, "_unit_damage_events", {}).items()):
            victim = current.get(key)
            if victim is None or damage <= 0:
                continue
            bucket = self.custom_effects.get(key, {})
            shield = bucket.get("Shield")
            if shield and shield.amount > 0:
                absorbed = min(int(shield.amount), int(damage))
                restored = min(self._max_hp(victim), int(victim.health) + absorbed)
                self._dispatch_ops([("write_word", victim.address + 0x22, restored)])
                shield.amount -= absorbed
                if shield.amount <= 0:
                    bucket.pop("Shield", None)
            attacker = self._infer_attacker(victim, world)
            if attacker is None:
                continue
            attacker_traits = self.combat_traits.get(self._unit_key_massive(attacker), {})
            victim_traits = self.combat_traits.get(key, {})
            evasion = float(victim_traits.get("Evasion", 0.0))
            if evasion > 0 and self._ultimate_rng.random() < evasion / 100.0:
                restored = min(self._max_hp(victim), int(victim.health) + int(damage))
                self._dispatch_ops([("write_word", victim.address + 0x22, restored)])
                continue
            reflect = float(victim_traits.get("Reflect", 0.0))
            if reflect > 0:
                self._call_damage_unit(victim, attacker, max(1, round(int(damage) * reflect / 100.0)))
            lifesteal = float(attacker_traits.get("Lifesteal", 0.0))
            if lifesteal > 0:
                healed = min(self._max_hp(attacker), int(attacker.health) + max(1, round(int(damage) * lifesteal / 100.0)))
                self._dispatch_ops([("write_word", attacker.address + 0x22, healed)])
            crit = float(attacker_traits.get("Critical Chance", 0.0))
            crit_mult = max(1.0, float(attacker_traits.get("Critical Multiplier", 2.0)))
            if crit > 0 and self._ultimate_rng.random() < crit / 100.0:
                self._call_damage_unit(attacker, victim, max(1, round(int(damage) * (crit_mult - 1.0))))
            cleave = float(attacker_traits.get("Cleave", 0.0))
            if cleave > 0:
                for target in world:
                    if target.address == victim.address or int(target.owner) == int(attacker.owner):
                        continue
                    if self._distance_sq(target, victim) <= 4:
                        self._call_damage_unit(attacker, target, max(1, round(int(damage) * cleave / 100.0)))

    # -------------------------------------------------------------- AI/waves
    def _maintain_tactical_ai(self, world: list[Any], now: float) -> None:
        for name, config in list(self.tactical_ai.items()):
            units = self._group_units(config.get("group", ""))
            if not units:
                continue
            profile = str(config.get("profile", "Aggressive"))
            destination = str(config.get("destination", "Anywhere"))
            if destination == "Anywhere":
                dx, dy = int(config.get("x", 0)), int(config.get("y", 0))
            else:
                loc = self._find_location(destination)
                dx, dy = (loc.left + loc.right) // 2, (loc.top + loc.bottom) // 2
            orders: list[tuple[int, int, int, int, int]] = []
            for unit in units:
                hp_percent = int(unit.health) * 100 / max(1, self._max_hp(unit))
                if profile == "Retreat when wounded" and hp_percent <= float(config.get("retreat_health", 30)):
                    retreat = str(config.get("retreat_location", destination))
                    if retreat != "Anywhere":
                        loc = self._find_location(retreat)
                        tx, ty = (loc.left + loc.right) // 2, (loc.top + loc.bottom) // 2
                    else:
                        tx, ty = int(config.get("retreat_x", unit.x)), int(config.get("retreat_y", unit.y))
                    orders.append((unit.address, tx, ty, 0, self.order_callees["do_move"]))
                elif profile == "Hold formation":
                    if self._distance_sq(unit, type("P", (), {"x": dx, "y": dy})()) > int(config.get("radius", 5)) ** 2:
                        orders.append((unit.address, dx, dy, 0, self.order_callees["do_move"]))
                else:
                    orders.append((unit.address, dx, dy, 0, self.order_callees["do_attack"]))
            if orders:
                self._call_cdecl_batched([(self.order_callees["set_target"], list(order)) for order in orders[:64]])

    def _td_stream_restore_all_type_overrides(self) -> None:
        overrides = getattr(self, "_td_stream_type_overrides", {})
        if not overrides or not getattr(self, "pm", None):
            return
        for unit_type, entry in list(overrides.items()):
            try:
                old_hp = int(entry["hp"])
                old_flags = int(entry["flags"])
                old_class = int(entry.get("class", CLASS_LAND))
                self.pm.write_ushort(self.base + UNIT_HP_TABLE_RVA + unit_type * 2, old_hp)
                self.pm.write_uint(self.base + UNIT_IS_TABLE_RVA + unit_type * 4, old_flags)
                self.pm.write_uchar(self.base + UNIT_CLASS_TABLE_RVA + unit_type, old_class)
                for unit in self.units():
                    if int(unit.unit_type) == unit_type and int(unit.health) > old_hp:
                        self.pm.write_ushort(unit.address + 0x22, old_hp)
            except Exception as exc:
                self.log(f"TD STREAM restore warning for unit {unit_type}: {exc}")
        overrides.clear()

    def _td_stream_prepare_type(self, state: TDStreamWaveState, unit_type: int) -> None:
        unit_type = int(unit_type)
        entry = self._td_stream_type_overrides.get(unit_type)
        if entry is None:
            hp_addr = self.base + UNIT_HP_TABLE_RVA + unit_type * 2
            flags_addr = self.base + UNIT_IS_TABLE_RVA + unit_type * 4
            class_addr = self.base + UNIT_CLASS_TABLE_RVA + unit_type
            original_hp = max(1, int(self.pm.read_ushort(hp_addr)))
            original_flags = int(self.pm.read_uint(flags_addr))
            original_class = int(self.pm.read_uchar(class_addr))
            if original_class not in (CLASS_LAND, CLASS_AIR, CLASS_WATER, CLASS_WATER_CANDOCK):
                raise RuntimeError(
                    f"TD stream unit {unit_type} has invalid native class {original_class} at RVA 0x{UNIT_CLASS_TABLE_RVA + unit_type:X}"
                )
            entry = {
                "hp": original_hp,
                "flags": original_flags,
                "class": original_class,
                "users": set(),
                "max_hp": state.max_hp,
            }
            self._td_stream_type_overrides[unit_type] = entry
            self.pm.write_ushort(hp_addr, state.max_hp)
            new_flags = original_flags
            # Naval classes cannot follow a land road. Turn those *unit types* into
            # flyers for the TD run. Also rescue otherwise mobile-inert unused slots
            # so the promised 0-57 roster cannot strand at spawn.
            if state.naval_as_flying and ((original_flags & TD_WATER_FLAGS) or original_class in (CLASS_WATER, CLASS_WATER_CANDOCK) or not (original_flags & TD_MOBILE_FLAGS)):
                # unit_create chooses placement rules from gbUnitClassTbl BEFORE the
                # Unit record exists. Patching only gUnitIsTbl (1.28.6-1.28.8) made
                # naval units look like flyers later, but creation still rejected
                # land because gbUnitClassTbl remained WATER/CANDOCK. Patch both
                # source tables before calling unit_create.
                new_flags = (original_flags & ~TD_WATER_FLAGS) | IS_FLYER
                self.pm.write_uint(flags_addr, new_flags)
                self.pm.write_uchar(class_addr, CLASS_AIR)
                kind = "naval" if ((original_flags & TD_WATER_FLAGS) or original_class in (CLASS_WATER, CLASS_WATER_CANDOCK)) else "mobile-inert"
                self.log(
                    f"TD STREAM AIR OVERRIDE v1.28.11: unit {unit_type} {kind}; "
                    f"class {original_class}->{CLASS_AIR}, capability flags 0x{original_flags:08X}->0x{new_flags:08X}"
                )
            # Keep any pre-existing same-type unit's health bar valid while this
            # global native max-HP table entry is overridden.
            for unit in self.units():
                if int(unit.unit_type) == unit_type:
                    self.pm.write_ushort(unit.address + 0x22, state.max_hp)
            self.log(f"TD STREAM HP TABLE: unit {unit_type} max HP {original_hp}->{state.max_hp}")
        else:
            # Concurrent streams may share a type only when they agree on max HP.
            if int(entry.get("max_hp", state.max_hp)) != state.max_hp:
                raise RuntimeError(
                    f"TD stream unit {unit_type} already has max HP {entry.get('max_hp')} from another active stream"
                )
        entry["users"].add(state.name)
        state.overridden_types.add(unit_type)

    def _td_stream_release_types(self, state: TDStreamWaveState) -> None:
        for unit_type in list(state.overridden_types):
            entry = self._td_stream_type_overrides.get(unit_type)
            if not entry:
                continue
            entry["users"].discard(state.name)
            if entry["users"]:
                continue
            old_hp = int(entry["hp"])
            old_flags = int(entry["flags"])
            old_class = int(entry.get("class", CLASS_LAND))
            self.pm.write_ushort(self.base + UNIT_HP_TABLE_RVA + unit_type * 2, old_hp)
            self.pm.write_uint(self.base + UNIT_IS_TABLE_RVA + unit_type * 4, old_flags)
            self.pm.write_uchar(self.base + UNIT_CLASS_TABLE_RVA + unit_type, old_class)
            for unit in self.units():
                if int(unit.unit_type) == unit_type and int(unit.health) > old_hp:
                    self.pm.write_ushort(unit.address + 0x22, old_hp)
            self._td_stream_type_overrides.pop(unit_type, None)
        state.overridden_types.clear()

    def _td_stream_route_point(self, state: TDStreamWaveState, stage: int, lane: int = 0) -> tuple[int, int]:
        """Return a stable lane point centered on the authored road.

        v1.28.5 randomized each unit over a five-tile cross-section. 1.28.6 uses
        fixed symmetric lanes (-1/0/+1 by default), so the horde is visually
        centered on the mud road and each creep keeps its lane through every turn.
        """
        loc = self._find_location(state.route[stage])
        cx = (int(loc.left) + int(loc.right)) // 2
        cy = (int(loc.top) + int(loc.bottom)) // 2
        half = max(0, state.lane_count // 2)
        lane = max(-half, min(half, int(lane)))
        if stage == 0:
            tx, ty = cx + lane, cy
        else:
            prev = self._find_location(state.route[stage - 1])
            px = (int(prev.left) + int(prev.right)) // 2
            py = (int(prev.top) + int(prev.bottom)) // 2
            if abs(cx - px) >= abs(cy - py):
                tx, ty = cx, cy + lane
            else:
                tx, ty = cx + lane, cy
        tx = max(int(loc.left), min(int(loc.right), tx))
        ty = max(int(loc.top), min(int(loc.bottom), ty))
        return tx, ty

    def _td_stream_unit_matches_state(self, unit: Any, state: TDStreamWaveState) -> bool:
        """Generation-safe guard for Warcraft's recycled unit slots.

        The engine reuses the same 152-byte unit record (and the token exposed by
        Trigger Studio is slot identity, not a creation generation).  A dead P7
        creep can therefore be replaced by a P6 building at the same address.
        Never let such a recycled record inherit a stream Move/path command.
        """
        return (
            int(getattr(unit, "owner", -1)) == int(state.owner)
            and 0 <= int(getattr(unit, "unit_type", -1)) <= MOBILE_MAX
            and int(getattr(unit, "unit_type", -1)) in state.unit_roster
        )

    def _td_stream_issue_moves(self, pairs: list[tuple[Any, int, int]], now: float, state: TDStreamWaveState) -> int:
        if not pairs:
            return 0

        valid: list[tuple[Any, int, int, tuple[int, int], TDStreamUnitProgress]] = []
        for unit, tx, ty in pairs[:128]:
            key = self._unit_key_massive(unit)
            prog = state.progress.get(key)

            # Re-read the 152-byte record immediately before dispatch. This closes
            # the remaining snapshot race: a world snapshot may have represented a
            # creep, but the slot can be freed/reused before the native path call.
            fresh = unit
            try:
                data = self.pm.read_bytes(int(unit.address), 152)
                if not self._record_is_allocated(data):
                    fresh = None
                else:
                    fresh = self._decode_unit(int(unit.address), data)
            except Exception:
                fresh = None

            if prog is None or fresh is None or not self._td_stream_unit_matches_state(fresh, state):
                # Defense in depth: native unit_set_target/path_init_target is a
                # mobile-unit operation. On a building the shared TUnit union at
                # +0x7C is TBldg, not TTarget, so issuing it can corrupt bldgFire.
                self.unit_groups.setdefault(state.group, set()).discard(key)
                state.progress.pop(key, None)
                if prog is not None:
                    observed = fresh if fresh is not None else unit
                    owner = int(getattr(observed, "owner", -1))
                    utype = int(getattr(observed, "unit_type", -1))
                    name = TD_MOBILE_NAMES[utype] if 0 <= utype < len(TD_MOBILE_NAMES) else f"unit {utype}"
                    self.log(
                        f"TD STREAM SLOT RECYCLE BLOCKED v1.28.11: {state.name} stale key "
                        f"0x{int(unit.address):08X} now P{owner + 1} {name}; mobile Move suppressed"
                    )
                continue
            valid.append((fresh, int(tx), int(ty), key, prog))

        if not valid:
            return 0
        self._call_cdecl_batched([
            (self.order_callees["set_target"], [unit.address, tx, ty, 0, self.order_callees["do_move"]])
            for unit, tx, ty, _key, _prog in valid
        ])
        for unit, tx, ty, key, prog in valid:
            prog.target_x, prog.target_y = tx, ty
            prog.last_order_at = now
            self._issued_orders.pop(key, None)
        return len(valid)

    def _td_stream_create_at_entrance(
        self, state: TDStreamWaveState, unit_type: int, sx: int, sy: int,
        left: int, right: int, top: int, bottom: int,
    ):
        """Create a creep only inside the authored entrance rectangle.

        The generic Create Units helper intentionally searches a large radius for
        any legal tile. That is useful for normal triggers but wrong for TD streams:
        a congested entrance could make a creep appear off the mud lane. This helper
        limits recovery candidates to two tiles and clips them to the spawn location.
        """
        source_even = self._source_even_aligned_type(unit_type)
        tried: set[tuple[int, int]] = set()
        for px, py in self._placement_candidates(int(sx), int(sy), radius=2):
            if source_even:
                px = self._normalize_even_tile(px)
                py = self._normalize_even_tile(py)
            candidate = (int(px), int(py))
            if candidate in tried:
                continue
            tried.add(candidate)
            if not (left <= px <= right and top <= py <= bottom):
                continue
            if not (0 <= px < self.map_width and 0 <= py < self.map_height):
                continue
            address = self._call_cdecl(self.unit_create_address, [int(px) << 5, int(py) << 5, int(unit_type), int(state.owner)])
            if not address:
                continue
            allocation_end = self.unit_pool + self.max_units * 152
            if not (self.unit_pool <= address < allocation_end) or (address - self.unit_pool) % 152:
                raise RuntimeError(f"TD stream unit_create returned invalid record pointer 0x{address:08X}")
            data = self.pm.read_bytes(address, 152)
            if not self._record_is_allocated(data):
                raise RuntimeError(f"TD stream unit_create returned inactive record 0x{address:08X}")
            unit = self._decode_unit(address, data)
            if int(unit.owner) != state.owner or int(unit.unit_type) != int(unit_type):
                raise RuntimeError("TD stream unit_create returned the wrong owner/type")
            if not (left <= int(unit.x) <= right and top <= int(unit.y) <= bottom):
                raise RuntimeError(
                    f"TD stream unit escaped authored entrance: requested ({px},{py}), got ({unit.x},{unit.y})"
                )
            return unit
        return None

    def _td_stream_spawn_batch(self, state: TDStreamWaveState, now: float, amount: int) -> int:
        """Create one deterministic centered TD batch.

        v1.28.11 gives effective air units a larger *staging* rectangle around the
        authored entrance. The route itself is unchanged. Large/even-aligned air
        units such as Deathwing no longer compete for only a handful of physical
        centers while a 420-unit stream is arriving. Ground waves keep the compact
        three-lane entrance used by v2.2.
        """
        if amount <= 0:
            return 0
        if state.spawn_location == "Anywhere":
            left = right = max(0, min(self.map_width - 1, int(state.spawn_x)))
            top = bottom = max(0, min(self.map_height - 1, int(state.spawn_y)))
        else:
            loc = self._find_location(state.spawn_location)
            left, right = int(loc.left), int(loc.right)
            top, bottom = int(loc.top), int(loc.bottom)
        cx, cy = (left + right) // 2, (top + bottom) // 2
        created: list[Any] = []
        lane_half = state.lane_count // 2

        for index in range(amount):
            sequence = state.spawned + index
            unit_type = state.unit_roster[sequence % len(state.unit_roster)]
            lane = (sequence % state.lane_count) - lane_half
            effective_class = int(self.pm.read_uchar(self.base + UNIT_CLASS_TABLE_RVA + int(unit_type)))
            is_air = effective_class == CLASS_AIR

            if is_air:
                # The authored Enemy Spawn is only 5x5. Even-aligned flyers collapse
                # that to roughly six useful centers. Expand staging only; WP1 and
                # all later lane points remain centered on the authored mud route.
                spawn_left = max(0, left - 3)
                spawn_right = min(self.map_width - 1, right + 3)
                spawn_top = max(0, top - 2)
                spawn_bottom = min(self.map_height - 1, bottom + 5)

                source_even = self._source_even_aligned_type(unit_type)
                xs = list(range(spawn_left, spawn_right + 1))
                ys = list(range(spawn_top, spawn_bottom + 1))
                if source_even:
                    xs = [v for v in xs if (v & 1) == 0]
                    ys = [v for v in ys if (v & 1) == 0]
                if not xs:
                    xs = [max(spawn_left, min(spawn_right, self._normalize_even_tile(cx)))]
                if not ys:
                    ys = [max(spawn_top, min(spawn_bottom, self._normalize_even_tile(cy)))]
                xs.sort(key=lambda v: (abs(v - cx), v))
                ys.sort(key=lambda v: (abs(v - cy), v))
                staging = [(px, py) for py in ys for px in xs]
                sx, sy = staging[sequence % len(staging)]
            else:
                spawn_left, spawn_right, spawn_top, spawn_bottom = left, right, top, bottom
                row = (sequence // max(1, state.lane_count)) & 1
                sx = max(left, min(right, cx + lane))
                sy = max(top, min(bottom, cy - row))

            unit = self._td_stream_create_at_entrance(
                state, unit_type, sx, sy, spawn_left, spawn_right, spawn_top, spawn_bottom
            )
            if unit is None:
                kind = "expanded air staging" if is_air else "centered entrance"
                self.log(f"TD STREAM SPAWN RETRY: {state.name} unit {unit_type} had no legal {kind} tile")
                break
            if state.mana:
                self.pm.write_uchar(unit.address + 0x26, max(0, min(255, state.mana)))
            native_max = max(1, int(self._max_hp(unit)))
            if native_max != state.max_hp:
                raise RuntimeError(
                    f"TD stream max-HP table mismatch for unit {unit_type}: {native_max} != {state.max_hp}"
                )
            if int(unit.health) != native_max:
                self.pm.write_ushort(unit.address + 0x22, native_max)
            key = self._unit_key_massive(unit)
            tx, ty = self._td_stream_route_point(state, 0, lane)
            state.progress[key] = TDStreamUnitProgress(
                stage=0, lane=lane, target_x=tx, target_y=ty,
                last_x=int(unit.x), last_y=int(unit.y),
                last_progress_at=now, last_order_at=0.0,
            )
            self.unit_groups.setdefault(state.group, set()).add(key)
            created.append(unit)

        ordered = self._td_stream_issue_moves(
            [(unit, *self._td_stream_route_point(state, 0, state.progress[self._unit_key_massive(unit)].lane)) for unit in created],
            now, state,
        )
        state.spawned += len(created)
        if created:
            state.last_spawn_at = now
            if state.spawned >= state.total and state.spawn_finished_at <= 0.0:
                state.spawn_finished_at = now
        self.counters[f"{state.name} Spawned"] = state.spawned
        if created:
            air_note = "; expanded air staging" if any(
                int(self.pm.read_uchar(self.base + UNIT_CLASS_TABLE_RVA + int(u.unit_type))) == CLASS_AIR
                for u in created
            ) else ""
            self.log(
                f"TD STREAM: {state.name} batch {len(created)}; spawned {state.spawned}/{state.total}; "
                f"absolute max HP {state.max_hp}/{state.max_hp}; centered {state.lane_count}-lane; "
                f"ordered {ordered}{air_note}"
            )
        return len(created)

    def _maintain_td_stream_waves(self, world: list[Any], now: float) -> None:
        """Maintain streamed TD waves without entrance-cap starvation.

        1.28.7 counted stage-zero creeps against a ten-unit queue cap. Towers near
        the entrance could therefore reduce a nominal batch of four to 1-2 units
        and eventually stall a wave indefinitely. 1.28.11 treats max_spawn_queue <=
        0 as an unlimited stream and, even when a cap is requested, never lets that
        policy change completion accounting. Wave completion is exact-group based,
        not "every mobile unit owned by P7", so unrelated strays cannot freeze the
        native-HP ladder.
        """
        live_by_key = {self._unit_key_massive(unit): unit for unit in world}
        for state in list(self.td_stream_waves.values()):
            if not state.active or state.completed:
                continue
            group_keys = self.unit_groups.setdefault(state.group, set())

            # Purge dead *and recycled* keys from the exact stream group. Warcraft
            # recycles a unit-array slot and the exposed token is slot identity, not
            # a generation counter. A freshly created P6 tower can therefore occupy
            # the exact key previously used by a dead P7 creep. v1.28.11 validates
            # owner + mobile type before that record can receive any path command.
            live_units: list[Any] = []
            for key in list(group_keys):
                unit = live_by_key.get(key)
                if unit is None:
                    group_keys.discard(key)
                    state.progress.pop(key, None)
                    continue
                if not self._td_stream_unit_matches_state(unit, state):
                    group_keys.discard(key)
                    state.progress.pop(key, None)
                    owner = int(getattr(unit, "owner", -1))
                    utype = int(getattr(unit, "unit_type", -1))
                    label = TD_MOBILE_NAMES[utype] if 0 <= utype < len(TD_MOBILE_NAMES) else f"unit {utype}"
                    self.log(
                        f"TD STREAM SLOT RECYCLE BLOCKED v1.28.11: {state.name} stale key "
                        f"0x{int(unit.address):08X} now P{owner + 1} {label}; detached from wave"
                    )
                    continue
                live_units.append(unit)
            live_keys = {self._unit_key_massive(unit) for unit in live_units}
            for key in list(state.progress):
                if key not in live_keys:
                    state.progress.pop(key, None)

            move_pairs: list[tuple[Any, int, int]] = []
            stage_zero = 0
            for unit in live_units:
                key = self._unit_key_massive(unit)
                prog = state.progress.get(key)
                if prog is None:
                    tx, ty = self._td_stream_route_point(state, 0, 0)
                    prog = TDStreamUnitProgress(
                        stage=0, lane=0, target_x=tx, target_y=ty,
                        last_x=int(unit.x), last_y=int(unit.y),
                        last_progress_at=now, last_order_at=0.0,
                    )
                    state.progress[key] = prog
                if prog.stage == 0:
                    stage_zero += 1
                if prog.stage >= len(state.route):
                    continue

                if (int(unit.x), int(unit.y)) != (prog.last_x, prog.last_y):
                    prog.last_x, prog.last_y = int(unit.x), int(unit.y)
                    prog.last_progress_at = now

                loc = self._find_location(state.route[prog.stage])
                inside = int(loc.left) <= int(unit.x) <= int(loc.right) and int(loc.top) <= int(unit.y) <= int(loc.bottom)
                close = (int(unit.x) - prog.target_x) ** 2 + (int(unit.y) - prog.target_y) ** 2 <= 4
                if inside or close:
                    prog.stage += 1
                    prog.spawn_rescues = 0
                    prog.hard_rescues = 0
                    if prog.stage >= len(state.route):
                        continue
                    prog.target_x, prog.target_y = self._td_stream_route_point(state, prog.stage, prog.lane)
                    prog.last_progress_at = now
                    move_pairs.append((unit, prog.target_x, prog.target_y))
                    continue

                stalled_for = now - prog.last_progress_at
                target_unit = int(getattr(unit, "target_unit", 0))
                current_tx = int(self.pm.read_short(unit.address + 0x84))
                current_ty = int(self.pm.read_short(unit.address + 0x86))
                wrong_target = target_unit != 0 or (current_tx, current_ty) != (prog.target_x, prog.target_y)
                unit_class = int(self.pm.read_uchar(unit.address + 0x2A))
                is_air = unit_class == CLASS_AIR

                if wrong_target or stalled_for >= state.stall_reissue:
                    # First-line rescue works at *every* route stage. The mud road is
                    # intentionally non-buildable in this TD, so a creep that has not
                    # changed tile for long enough is collision-stalled rather than
                    # legitimately blocked by player construction.
                    rescue_due = stalled_for >= state.spawn_rescue_after
                    if rescue_due and not is_air and prog.spawn_rescues < 3:
                        dx = 0 if prog.target_x == int(unit.x) else (1 if prog.target_x > int(unit.x) else -1)
                        dy = 0 if prog.target_y == int(unit.y) else (1 if prog.target_y > int(unit.y) else -1)
                        candidates = [
                            (int(unit.x) + dx, int(unit.y) + dy),
                            (int(unit.x) + dx, int(unit.y)),
                            (int(unit.x), int(unit.y) + dy),
                        ]
                        before_d = (int(unit.x) - prog.target_x) ** 2 + (int(unit.y) - prog.target_y) ** 2
                        for nx, ny in candidates:
                            if not (0 <= nx < self.map_width and 0 <= ny < self.map_height):
                                continue
                            place = self._find_move_place(unit, nx, ny)
                            if place is None or place == (int(unit.x), int(unit.y)):
                                continue
                            after_d = (place[0] - prog.target_x) ** 2 + (place[1] - prog.target_y) ** 2
                            if after_d >= before_d:
                                continue
                            try:
                                unit = self._move_mobile_unit(unit, *place)
                                prog.last_x, prog.last_y = int(unit.x), int(unit.y)
                                prog.last_progress_at = now
                                prog.spawn_rescues += 1
                                self.log(
                                    f"TD STREAM RESCUE: {state.name} P{state.owner + 1} slot "
                                    f"{(unit.address-self.unit_pool)//152} stage {prog.stage + 1} -> {place}"
                                )
                                break
                            except Exception as exc:
                                self.log(f"TD STREAM RESCUE WARNING: {state.name}: {exc}")

                    # Never physically unplace/teleport CLASS_AIR units. Flyers do
                    # not need collision nudges, and the unplace_man/place_man path is
                    # a land-unit mechanism. A stalled flyer gets a native Move
                    # reissue; after a sustained stall it is forward-retargeted one
                    # waypoint without mutating its coordinates.
                    stalled_for = now - prog.last_progress_at
                    if is_air:
                        if rescue_due:
                            prog.spawn_rescues += 1
                            if prog.spawn_rescues == 1:
                                self.log(
                                    f"TD STREAM AIR REISSUE v1.28.11: {state.name} P{state.owner + 1} "
                                    f"slot {(unit.address-self.unit_pool)//152} stage {prog.stage + 1}; "
                                    "physical rescue disabled"
                                )
                        if stalled_for >= max(4.5, state.spawn_rescue_after * 3.0) and prog.hard_rescues < 2:
                            if prog.stage + 1 < len(state.route):
                                prog.stage += 1
                                prog.target_x, prog.target_y = self._td_stream_route_point(state, prog.stage, prog.lane)
                                prog.last_progress_at = now
                                prog.hard_rescues += 1
                                self.log(
                                    f"TD STREAM AIR FORWARD RETARGET v1.28.11: {state.name} P{state.owner + 1} "
                                    f"slot {(unit.address-self.unit_pool)//152} -> waypoint {prog.stage + 1}"
                                )
                    elif stalled_for >= max(3.5, state.spawn_rescue_after * 2.0) and prog.spawn_rescues >= 3 and prog.hard_rescues < 2:
                        place = self._find_move_place(unit, prog.target_x, prog.target_y)
                        if place is not None and place != (int(unit.x), int(unit.y)):
                            try:
                                unit = self._move_mobile_unit(unit, *place)
                                prog.last_x, prog.last_y = int(unit.x), int(unit.y)
                                prog.last_progress_at = now
                                prog.hard_rescues += 1
                                self.log(
                                    f"TD STREAM HARD RESCUE: {state.name} P{state.owner + 1} slot "
                                    f"{(unit.address-self.unit_pool)//152} -> waypoint {prog.stage + 1} {place}"
                                )
                            except Exception as exc:
                                self.log(f"TD STREAM HARD RESCUE WARNING: {state.name}: {exc}")
                    move_pairs.append((unit, prog.target_x, prog.target_y))

            if move_pairs:
                self._td_stream_issue_moves(move_pairs, now, state)

            spawned_this_cycle = 0
            if state.spawned < state.total and now >= state.next_spawn_at:
                if state.max_spawn_queue > 0:
                    room = max(0, state.max_spawn_queue - stage_zero)
                    amount = min(state.batch_size, state.total - state.spawned, room)
                else:
                    # Unlimited stream: fixed authored batch size regardless of how
                    # many earlier creeps are still in the entrance section.
                    amount = min(state.batch_size, state.total - state.spawned)
                if amount > 0:
                    spawned_this_cycle = self._td_stream_spawn_batch(state, now, amount)
                    if spawned_this_cycle > 0:
                        # Advance from the previous deadline rather than `now`, so a
                        # slow Python/UI cycle cannot permanently stretch the wave.
                        state.next_spawn_at = max(state.next_spawn_at + state.interval, now)
                    else:
                        state.next_spawn_at = now + min(max(state.interval, 0.10), 0.35)

            # Exact group completion. Do not wait for every mobile unit owned by
            # the Empty creep player; only units created into this stream matter.
            if state.spawned >= state.total and not live_units and spawned_this_cycle == 0:
                state.completed = True
                state.active = False
                self._td_stream_release_types(state)
                self.counters[f"{state.name} Complete"] = 1
                self.counters[f"{state.name} Active"] = 0
                self.log(f"TD STREAM COMPLETE: {state.name}; {state.spawned} creep(s) released and exact group cleared")

    def _td_ladder_stop(self, state: TDNativeHPLadderState, *, restore: bool = True) -> None:
        state.active = False
        self.counters[f"{state.name} Active"] = 0
        if state.active_stream:
            stream = self.td_stream_waves.get(state.active_stream)
            if stream is not None and not stream.completed:
                stream.active = False
                self.counters[f"{stream.name} Active"] = 0
                if restore:
                    self._td_stream_release_types(stream)
        state.active_stream = ""

    def _maintain_td_native_hp_ladders(self, now: float) -> None:
        """Run one native-verified mobile unit type per wave, weakest native HP first.

        The complete order is computed once from Warcraft's live native max-HP
        table before any TD type override is installed. This avoids guessed unit
        statistics and guarantees the 53 real mobile slots are ordered by the
        game build actually attached to Trigger Studio.
        """
        for state in list(self.td_native_hp_ladders.values()):
            if not state.active or state.completed:
                continue

            if state.active_stream:
                stream = self.td_stream_waves.get(state.active_stream)
                if stream is None:
                    self.log(f"TD LADDER WARNING: {state.name} lost stream {state.active_stream}; retrying next wave")
                    state.active_stream = ""
                    state.waiting_until = now + state.intermission
                elif stream.completed:
                    cleared = state.next_wave_index
                    self.log(f"TD LADDER CLEAR: {state.name} wave {cleared}/{len(state.plan)} complete")
                    state.active_stream = ""
                    state.waiting_until = now + state.intermission
                else:
                    continue

            if state.next_wave_index >= len(state.plan):
                state.completed = True
                state.active = False
                self.counters[f"{state.name} Complete"] = 1
                self.counters[f"{state.name} Active"] = 0
                self.counters[f"{state.name} Current Wave"] = len(state.plan)
                self.log(f"TD LADDER COMPLETE: {state.name}; all {len(state.plan)} native-HP-sorted unit waves cleared")
                return

            if now < state.waiting_until:
                continue

            item = state.plan[state.next_wave_index]
            wave_number = state.next_wave_index + 1
            unit_type = int(item["unit_type"])
            base_hp = int(item["base_hp"])
            max_hp = int(item["max_hp"])
            total = int(item["total"])
            stream_name = f"{state.name} Wave {wave_number:02d}"

            if 0 <= state.builder_player <= 7 and 0 <= state.builder_unit <= MOBILE_MAX and state.builder_refill_mana > 0:
                try:
                    self.action(
                        "Set Mana",
                        {
                            "player": state.builder_player,
                            "unit": state.builder_unit,
                            "location": "Anywhere",
                            "amount": state.builder_refill_mana,
                        },
                        state.builder_player,
                    )
                except Exception as exc:
                    self.log(f"TD LADDER builder refill warning: {exc}")

            duration = math.ceil(total / max(1, state.batch_size)) * state.interval
            unit_name = TD_MOBILE_NAMES[unit_type] if 0 <= unit_type < len(TD_MOBILE_NAMES) else f"Unit {unit_type}"
            message = f"WAVE {wave_number}/{len(state.plan)} {unit_name}: {total} units, {max_hp} HP"
            # Native PM_STRING is 78 bytes; trim defensively without losing the useful stats.
            if len(message.encode("utf-8")) > 76:
                message = f"WAVE {wave_number}/{len(state.plan)} U{unit_type}: {total} units, {max_hp} HP"
            try:
                self.action(
                    "Game Message",
                    {
                        "text": message,
                        "color": "Yellow / gold — native normal",
                        "recipients": "All active players",
                        "seconds": 4,
                        "also_log": True,
                    },
                    state.builder_player if 0 <= state.builder_player <= 7 else state.owner,
                )
            except Exception as exc:
                self.log(f"TD LADDER message warning: {exc}")

            args = {
                "name": stream_name,
                "player": state.owner,
                "unit": unit_type,
                "unit_roster_json": json.dumps([unit_type]),
                "total": total,
                "batch_size": state.batch_size,
                "interval": state.interval,
                "spawn_location": state.spawn_location,
                "spawn_x": state.spawn_x,
                "spawn_y": state.spawn_y,
                "route_json": json.dumps(state.route),
                "max_hp": max_hp,
                "lane_count": state.lane_count,
                "naval_as_flying": state.naval_as_flying,
                "mana": state.mana,
                "group": stream_name,
                "max_spawn_queue": state.max_spawn_queue,
                "stall_reissue": state.stall_reissue,
                "spawn_rescue_after": state.spawn_rescue_after,
            }
            try:
                self.massive_action("Start TD Stream Wave", args, state.owner)
            except Exception as exc:
                self.log(f"TD LADDER START ERROR: {stream_name}: {exc}")
                state.waiting_until = now + max(1.0, state.intermission)
                continue

            state.active_stream = stream_name
            state.next_wave_index += 1
            self.counters[f"{state.name} Current Wave"] = wave_number
            self.counters["Wave"] = wave_number
            self.log(
                f"TD LADDER WAVE {wave_number:02d}/{len(state.plan)}: unit {unit_type} {unit_name}; "
                f"native base HP {base_hp}; TD max HP {max_hp}; {total} units; "
                f"nominal fixed-batch spawn duration {duration:.1f}s"
            )

    def _maintain_wave_directors(self, now: float) -> None:
        for state in list(self.wave_directors.values()):
            if not state.active or state.completed:
                continue
            if state.current_group and self._group_units(state.current_group):
                continue
            if state.wave >= state.max_waves > 0:
                state.completed = True
                state.active = False
                continue
            if now < state.waiting_until:
                continue
            state.wave += 1
            count = max(1, min(64, state.base_count + (state.wave - 1) * state.growth))
            unit_type = self._ultimate_rng.choice(state.unit_pool)
            group = f"{state.group_prefix} {state.wave}"
            create_args = {
                "player": state.owner,
                "unit": unit_type,
                "amount_expression": str(count),
                "spawn_location": state.spawn_location,
                "spawn_x": state.spawn_x,
                "spawn_y": state.spawn_y,
                "formation": state.formation,
                "spacing": state.spacing,
                "health_percent": 100,
                "mana": 255,
                "facing": -1,
                "group": group,
                "order": "Attack",
                "destination": state.destination,
                "destination_x": state.destination_x,
                "destination_y": state.destination_y,
            }
            MassiveFeatureMixin.massive_action(self, "Create Wave", create_args, state.owner)
            if state.boss_every > 0 and state.wave % state.boss_every == 0 and state.boss_unit >= 0:
                boss_args = dict(create_args)
                boss_args.update({"unit": state.boss_unit, "amount_expression": "1", "group": f"{group} Boss"})
                MassiveFeatureMixin.massive_action(self, "Create Wave", boss_args, state.owner)
                self.unit_groups[group].update(self.unit_groups.get(f"{group} Boss", set()))
            state.current_group = group
            state.waiting_until = now + state.intermission
            self.counters[f"{state.name} Wave"] = state.wave
            self.log(f"WAVE DIRECTOR: {state.name} spawned wave {state.wave} with {len(self._group_units(group))} unit(s)")

    def _maintain_boss_controllers(self, now: float) -> None:
        for state in list(self.boss_controllers.values()):
            if not state.active:
                continue
            boss = self._resolve_unit_reference(state.reference)
            if boss is None:
                state.active = False
                continue
            hp_percent = int(boss.health) * 100 / max(1, self._max_hp(boss))
            while state.current_phase < len(state.phases):
                phase = state.phases[state.current_phase]
                threshold = float(phase.get("health_at_or_below", 100))
                if hp_percent > threshold:
                    break
                state.current_phase += 1
                self.counters[f"{state.name} Phase"] = state.current_phase
                message = str(phase.get("message", "")).strip()
                if message:
                    self.action("Game Message", {"text": message, "color": "Red — native selected / warning", "recipients": "All active players", "seconds": 4, "also_log": True}, int(boss.owner))
                spawn_unit = int(phase.get("spawn_unit", -1))
                spawn_count = int(phase.get("spawn_count", 0))
                if 0 <= spawn_unit <= MOBILE_MAX and spawn_count > 0:
                    args = {
                        "player": int(phase.get("spawn_player", boss.owner)),
                        "unit": spawn_unit,
                        "amount_expression": str(min(64, spawn_count)),
                        "spawn_location": "Anywhere",
                        "spawn_x": int(boss.x),
                        "spawn_y": int(boss.y),
                        "formation": str(phase.get("formation", "Grid")),
                        "spacing": int(phase.get("spacing", 1)),
                        "group": f"{state.name} Phase {state.current_phase} Adds",
                        "order": "Attack",
                        "destination": str(phase.get("destination", "Anywhere")),
                        "destination_x": int(phase.get("destination_x", boss.x)),
                        "destination_y": int(phase.get("destination_y", boss.y)),
                        "mana": 255,
                        "health_percent": 100,
                        "facing": -1,
                    }
                    MassiveFeatureMixin.massive_action(self, "Create Wave", args, int(boss.owner))
                if bool(phase.get("invulnerable", False)):
                    self._write_status(boss, "Unholy Armor", int(phase.get("invulnerable_ticks", 250)))

    def _maintain_periodic_income(self, now: float) -> None:
        for name, config in list(self.periodic_income.items()):
            if now < float(config.get("next", 0.0)):
                continue
            owner = int(config["player"])
            resource = str(config["resource"])
            amount = int(config["amount"])
            self.action("Add Resources", {"player": owner, "resource": resource, "amount": amount}, owner)
            config["next"] = now + max(0.25, float(config["interval"]))

    # ---------------------------------------------------------- cycle hooks
    def _massive_prepare_pre(self, world: list[Any]) -> bool:
        result = super()._massive_prepare_pre(world)
        if result is False:
            return False
        now = time.monotonic()
        # Keep maintenance bounded. The normal trigger engine may cycle faster
        # than Warcraft needs for these high-level systems.
        if now < self._ultimate_next_maintenance:
            return True
        self._ultimate_next_maintenance = now + 0.20
        self._maintain_custom_effects(world, now)
        self._maintain_tactical_ai(world, now)
        self._maintain_td_stream_waves(world, now)
        self._maintain_td_native_hp_ladders(now)
        self._maintain_wave_directors(now)
        self._maintain_boss_controllers(now)
        self._maintain_periodic_income(now)
        return True

    def _massive_prepare_events(self, current: dict[tuple[int, int], Any], previous: dict[tuple[int, int], Any]) -> None:
        super()._massive_prepare_events(current, previous)
        missiles = {m.address: m for m in self._active_missiles()}
        self.projectile_created = [missiles[address] for address in missiles.keys() - self._previous_missiles.keys()]
        self.projectile_expired = [self._previous_missiles[address] for address in self._previous_missiles.keys() - missiles.keys()]
        if self.projectile_created:
            self._available_events.add("Projectile Created")
        if self.projectile_expired:
            self._available_events.add("Projectile Expired")
        self._previous_missiles = missiles

        # Grant XP from credited kills to referenced/group heroes belonging to
        # the killer. XP is a trigger-level RPG layer and never changes Warcraft's
        # native score or kill tables.
        for owner in range(8):
            kills = int(self._kill_delta(owner, "All")) if hasattr(self, "_kill_delta") else 0
            if kills <= 0:
                continue
            for key, state in list(self.hero_state.items()):
                unit = current.get(key)
                if unit is None or int(unit.owner) != owner:
                    continue
                state["xp"] = int(state.get("xp", 0)) + kills * int(state.get("xp_per_kill", 10))
                needed = max(1, int(state.get("next_level_xp", 100)))
                while int(state["xp"]) >= needed:
                    state["xp"] -= needed
                    state["level"] = int(state.get("level", 1)) + 1
                    needed = round(needed * float(state.get("growth", 1.25)))
                    state["next_level_xp"] = needed
                    hp = min(65535, self._max_hp(unit) + int(state.get("hp_per_level", 10)))
                    self._dispatch_ops([("write_word", unit.address + 0x22, hp)])
                    self.log(f"HERO LEVEL: P{owner + 1} unit 0x{unit.address:08X} reached level {state['level']}")

    # ------------------------------------------------------------- conditions
    def massive_value(self, kind: str, args: dict[str, Any], player: int) -> Any:
        if kind.startswith("Unit Reference"):
            unit = self._resolve_unit_reference(args.get("reference", "Unit Reference 1"))
            if kind == "Unit Reference Exists":
                return 1 if unit is not None else 0
            if unit is None:
                return 0
            if kind == "Unit Reference Alive":
                return 1
            if kind == "Unit Reference Health":
                return int(unit.health)
            if kind == "Unit Reference Health Percent":
                return round(int(unit.health) * 100 / max(1, self._max_hp(unit)))
            if kind == "Unit Reference Mana":
                return int(unit.mana)
            if kind == "Unit Reference Owner":
                return int(unit.owner) + 1
            if kind == "Unit Reference Type":
                return int(unit.unit_type)
            if kind == "Unit Reference Order":
                wanted = str(args.get("order", "Attack"))
                return 1 if int(unit.action) in ORDER_ACTIONS.get(wanted, set()) or int(unit.next_action) in ORDER_ACTIONS.get(wanted, set()) else 0
            if kind == "Unit Reference In Location":
                location = self._find_location(str(args.get("location", "Location 1")))
                return 1 if self._inside(unit, location) else 0
        if kind == "Upgrade Level":
            owner = int(args.get("player", player))
            name, row = self._upgrade_row_value(args.get("upgrade", "Melee Attack"))
            try:
                tables = self._resolve_progression_tables()
                if "tech_levels" in tables:
                    return int(self.pm.read_uchar(tables["tech_levels"] + row * 16 + owner))
            except Exception:
                pass
            return int(self.player_upgrade_levels.get(owner, {}).get(name, 0))
        if kind in {"Spell Researched", "Spell Allowed"}:
            owner = int(args.get("player", player))
            name, mask = self._spell_mask_value(args.get("spell", "Healing"))
            try:
                tables = self._resolve_progression_tables()
                table = tables["spells"] if kind == "Spell Researched" else tables["spells_allowed"]
                return 1 if self.pm.read_uint(table + owner * 4) & mask else 0
            except Exception:
                return 1 if name in self.player_spell_grants.get(owner, set()) else 0
        if kind == "Custom Effect Active":
            units = self._selected_units(args, player)
            effect = str(args.get("effect", "Stun"))
            return sum(1 for unit in units if self._effect_active(unit, effect))
        if kind == "Shield Amount":
            units = self._selected_units(args, player)
            if not units:
                return 0
            effect = self.custom_effects.get(self._unit_key_massive(units[0]), {}).get("Shield")
            return max(0, int(effect.amount)) if effect else 0
        if kind in {"Projectile Created", "Projectile Expired"}:
            source = self.projectile_created if kind == "Projectile Created" else self.projectile_expired
            missile = args.get("missile", "Any")
            matches = [m for m in source if missile == "Any" or int(m.missile_type) == int(missile)]
            if matches:
                m = matches[0]
                self._event_context = {
                    "event_type": kind,
                    "x": int(m.x), "y": int(m.y), "missile_type": int(m.missile_type),
                    "damage": int(m.damage), "amount": len(matches),
                }
            return len(matches)
        if kind == "Wave Director State":
            state = self.wave_directors.get(str(args.get("name", "Wave Director 1")))
            wanted = str(args.get("state", "Active"))
            actual = "Missing" if state is None else "Complete" if state.completed else "Active" if state.active else "Stopped"
            return actual
        if kind == "Wave Number":
            state = self.wave_directors.get(str(args.get("name", "Wave Director 1")))
            return int(state.wave if state else 0)
        if kind == "Boss Phase":
            state = self.boss_controllers.get(str(args.get("name", "Boss 1")))
            return int(state.current_phase if state else 0)
        if kind == "Tactical AI Enabled":
            return 1 if str(args.get("name", "Squad AI 1")) in self.tactical_ai else 0
        if kind == "Hero Level":
            unit = self._resolve_unit_reference(args.get("reference", "Hero"))
            if unit is None:
                return 0
            return int(self.hero_state.get(self._unit_key_massive(unit), {}).get("level", 1))
        if kind == "Hero Experience":
            unit = self._resolve_unit_reference(args.get("reference", "Hero"))
            if unit is None:
                return 0
            return int(self.hero_state.get(self._unit_key_massive(unit), {}).get("xp", 0))
        if kind == "Inventory Item Count":
            unit = self._resolve_unit_reference(args.get("reference", "Hero"))
            if unit is None:
                return 0
            return int(self.inventory.get(self._unit_key_massive(unit), {}).get(str(args.get("item", "Item")), 0))
        if kind == "Quest State":
            return self.quests.get(str(args.get("quest", "Quest 1")), "Missing")
        if kind == "Force Member":
            force = str(args.get("force", "Force 1"))
            owner = int(args.get("player", player))
            scenario = getattr(self, "scenario", None)
            return 1 if scenario and owner in scenario.forces.get(force, []) else 0
        if kind == "Active Player Count":
            return sum(1 for owner in range(8) if any(int(unit.owner) == owner for unit in self.units()))
        if kind == "Sapper Count":
            owner = int(args.get("player", player))
            location = str(args.get("location", "Anywhere"))
            selected = self._selected_units({"player": owner, "unit": "Any", "location": location}, player)
            return sum(1 for unit in selected if int(unit.unit_type) in SAPPER_TYPES)
        result = super().massive_value(kind, args, player)
        return result

    # ---------------------------------------------------------------- actions
    def massive_action(self, kind: str, args: dict[str, Any], player: int) -> bool:
        # Persistent references and trigger iteration.
        if kind == "Save Unit Reference":
            unit = self._pick_reference_unit(args, player)
            self._save_reference(args.get("reference", "Unit Reference 1"), unit)
            self.log(f"UNIT REFERENCE: {args.get('reference', 'Unit Reference 1')} -> {hex(unit.address) if unit else 'none'}")
            return True
        if kind == "Save Event Unit Reference":
            unit = self._event_unit()
            self._save_reference(args.get("reference", "Event Unit"), unit)
            return True
        if kind == "Save Last Created Unit Reference":
            unit = list(getattr(self, "created_units", []))[-1] if getattr(self, "created_units", []) else None
            self._save_reference(args.get("reference", "Last Created Unit"), unit)
            return True
        if kind == "Clear Unit Reference":
            self.unit_references.pop(str(args.get("reference", "Unit Reference 1")), None)
            return True
        if kind in {"Order Unit Reference", "Teleport Unit Reference", "Give Unit Reference", "Set Unit Reference Health", "Set Unit Reference Mana", "Apply Effect To Unit Reference", "Kill Unit Reference"}:
            unit = self._resolve_unit_reference(args.get("reference", "Unit Reference 1"))
            if unit is None:
                raise RuntimeError("The named unit reference is missing or dead")
            if kind == "Order Unit Reference":
                order = str(args.get("order", "Attack"))
                destination = str(args.get("destination", "Anywhere"))
                if destination == "Anywhere":
                    x, y = int(args.get("x", unit.x)), int(args.get("y", unit.y))
                else:
                    loc = self._find_location(destination)
                    x, y = (loc.left + loc.right) // 2, (loc.top + loc.bottom) // 2
                callback = {"Move": "do_move", "Attack": "do_attack", "Patrol": "do_patrol"}.get(order)
                if callback is None:
                    raise ValueError(f"Unsupported reference order: {order}")
                self._call_cdecl(self.order_callees["set_target"], [unit.address, x, y, 0, self.order_callees[callback]])
                if order == "Attack":
                    self._attack_routes[self._unit_key_massive(unit)] = (x, y)
            elif kind == "Teleport Unit Reference":
                destination = str(args.get("destination", "Anywhere"))
                if destination == "Anywhere":
                    x, y = int(args.get("x", unit.x)), int(args.get("y", unit.y))
                else:
                    loc = self._find_location(destination)
                    x, y = (loc.left + loc.right) // 2, (loc.top + loc.bottom) // 2
                moved = self._move_mobile_unit(unit, x, y)
                self._save_reference(args.get("reference"), moved)
            elif kind == "Give Unit Reference":
                new_owner = int(args.get("new_owner", player))
                self._call_cdecl(self.capture_unit_address, [unit.address, new_owner, 0])
                refreshed = next((u for u in self.units() if u.address == unit.address), None)
                self._save_reference(args.get("reference"), refreshed)
            elif kind == "Set Unit Reference Health":
                value = max(1, min(self._max_hp(unit), int(args.get("amount", 100))))
                self._dispatch_ops([("write_word", unit.address + 0x22, value)])
            elif kind == "Set Unit Reference Mana":
                value = max(0, min(255, int(args.get("amount", 255))))
                self._dispatch_ops([("write_bytes", unit.address + 0x26, bytes([value]))])
            elif kind == "Apply Effect To Unit Reference":
                effect = str(args.get("effect", "Bloodlust"))
                if effect in STATUS_OFFSETS:
                    self._write_status(unit, effect, int(args.get("ticks", 0)))
                else:
                    seconds = max(0.1, float(args.get("seconds", 5)))
                    self._apply_custom_effect(unit, TimedEffect(effect, time.monotonic() + seconds, amount=float(args.get("amount", 0)), interval=float(args.get("interval", 1)), source_ref=str(args.get("source_reference", ""))))
            else:
                self._call_cdecl(self.damage_callees["unit_kill"], [unit.address])
            return True

        if kind == "Run Trigger For Each Unit In Group":
            engine = getattr(self, "engine", None)
            if engine is None:
                raise RuntimeError("Trigger iteration requires an active TriggerEngine")
            target_name = str(args.get("trigger", "")).strip()
            target_index = engine.find_trigger_index(target_name)
            if target_index is None:
                raise ValueError(f"Unknown trigger: {target_name}")
            units = self._group_units(args.get("group", "Unit Group 1"))
            reference = str(args.get("reference", "Loop Unit"))
            original = self.unit_references.get(reference)
            try:
                for unit in units[: max(1, min(1600, int(args.get("maximum", 1600))))]:
                    self._save_reference(reference, unit)
                    self._set_event_context("Unit Group Iteration", unit, 1)
                    engine._execute_actions(target_index, player, 0, time.monotonic(), called=True)
            finally:
                if original is None:
                    self.unit_references.pop(reference, None)
                else:
                    self.unit_references[reference] = original
            self.log(f"FOR EACH UNIT: called {target_name} for {min(len(units), int(args.get('maximum', 1600)))} unit(s)")
            return True
        if kind == "Run Trigger For Each Player":
            engine = getattr(self, "engine", None)
            if engine is None:
                raise RuntimeError("Player iteration requires an active TriggerEngine")
            target_name = str(args.get("trigger", "")).strip()
            target_index = engine.find_trigger_index(target_name)
            if target_index is None:
                raise ValueError(f"Unknown trigger: {target_name}")
            force = str(args.get("force", "All Players"))
            if force == "All Players":
                players = list(range(8))
            else:
                players = list(getattr(self.scenario, "forces", {}).get(force, []))
            for owner in players:
                engine._execute_actions(target_index, int(owner), 0, time.monotonic(), called=True)
            return True

        # Native spell research and upgrade levels.
        if kind in {"Give Spell", "Remove Spell", "Give All Spells", "Remove All Spells", "Set Spell Allowed"}:
            owner = int(args.get("player", player))
            if not 0 <= owner <= 15:
                raise ValueError("Spell research player must be P1-P16")
            tables = self._resolve_progression_tables()
            spells_address = tables["spells"] + owner * 4
            allowed_address = tables["spells_allowed"] + owner * 4
            before = self.pm.read_uint(spells_address)
            allowed_before = self.pm.read_uint(allowed_address)
            if kind in {"Give Spell", "Remove Spell", "Set Spell Allowed"}:
                name, mask = self._spell_mask_value(args.get("spell", "Healing"))
            else:
                name, mask = "All spells", SPELL_MASK
            if kind == "Give Spell":
                after = before | mask
                allowed_after = allowed_before | mask
                self.player_spell_grants.setdefault(owner, set()).add(name)
            elif kind == "Remove Spell":
                after = before & ~mask
                allowed_after = allowed_before
                self.player_spell_grants.setdefault(owner, set()).discard(name)
            elif kind == "Give All Spells":
                after = before | SPELL_MASK
                allowed_after = allowed_before | SPELL_MASK
                self.player_spell_grants[owner] = set(SPELL_BITS)
            elif kind == "Remove All Spells":
                after = before & ~SPELL_MASK
                allowed_after = allowed_before
                self.player_spell_grants[owner] = set()
            else:
                allowed_after = (allowed_before | mask) if bool(args.get("allowed", True)) else (allowed_before & ~mask)
                after = before & allowed_after
            self._dispatch_ops([
                ("write_dword", spells_address, after),
                ("write_dword", allowed_address, allowed_after),
            ])
            self.log(f"SPELL RESEARCH: P{owner + 1} {kind} {name}; researched=0x{after:08X}, allowed=0x{allowed_after:08X}")
            return True

        if kind in {"Set Upgrade Level", "Add Upgrade Level", "Give All Upgrades", "Clear All Upgrades"}:
            owner = int(args.get("player", player))
            tables = self._resolve_progression_tables()
            if "tech_levels" not in tables:
                raise RuntimeError("The native sgbTechTbl upgrade-level table could not be uniquely resolved")
            operations: list[tuple] = []
            if kind in {"Give All Upgrades", "Clear All Upgrades"}:
                level = 2 if kind == "Give All Upgrades" else 0
                for name, row in UPGRADE_ROWS.items():
                    operations.append(("write_bytes", tables["tech_levels"] + row * 16 + owner, bytes([level])))
                    self.player_upgrade_levels.setdefault(owner, {})[name] = level
            else:
                name, row = self._upgrade_row_value(args.get("upgrade", "Melee Attack"))
                address = tables["tech_levels"] + row * 16 + owner
                before = int(self.pm.read_uchar(address))
                if kind == "Set Upgrade Level":
                    level = int(args.get("level", 1))
                else:
                    level = before + int(args.get("amount", 1))
                level = max(0, min(2, level))
                operations.append(("write_bytes", address, bytes([level])))
                self.player_upgrade_levels.setdefault(owner, {})[name] = level
            self._dispatch_ops(operations)
            self.log(f"UPGRADES: P{owner + 1} {kind} applied to {len(operations)} native tech cell(s)")
            return True

        if kind == "Enable Advanced Unit Classes":
            owner = int(args.get("player", player))
            # Grant the source conversion bit and the two automatic baseline
            # spells, then convert existing Knights/Ogres through the validated
            # replace path so HP and ownership remain coherent.
            self.massive_action("Give Spell", {"player": owner, "spell": "Paladin / Ogre-Mage Conversion"}, player)
            self.massive_action("Give Spell", {"player": owner, "spell": "Holy Vision"}, player)
            self.massive_action("Give Spell", {"player": owner, "spell": "Eye of Kilrogg"}, player)
            for old, new in ((6, 12), (7, 13)):
                MassiveFeatureMixin.massive_action(self, "Replace Units", {"player": owner, "unit": old, "location": "Anywhere", "amount": "All", "new_unit": new, "preserve_health_percent": True}, owner)
            return True

        # Sappers / demolition.
        if kind in {"Order Sappers Demolish", "Create Sapper Assault", "Arm Sappers"}:
            do_demolish = self.base + 0x319D70
            body = self.pm.read_bytes(do_demolish, 0x48)
            if b"\x55\x8B\xEC" not in body[:8] or b"\x6A" not in body:
                raise RuntimeError("Native-verified do_unit_demolish signature validation failed")
            if kind == "Create Sapper Assault":
                owner = int(args.get("player", player))
                unit_type = int(args.get("unit", 14))
                if unit_type not in SAPPER_TYPES:
                    raise ValueError("Create Sapper Assault requires Dwarves or Goblins")
                wave_args = {
                    "player": owner, "unit": unit_type,
                    "amount_expression": str(max(1, min(32, int(args.get("amount", 6))))),
                    "spawn_location": str(args.get("spawn_location", "Anywhere")),
                    "spawn_x": int(args.get("spawn_x", 0)), "spawn_y": int(args.get("spawn_y", 0)),
                    "formation": str(args.get("formation", "Grid")), "spacing": int(args.get("spacing", 1)),
                    "health_percent": 100, "mana": 0, "facing": -1,
                    "group": str(args.get("group", "Sapper Assault")), "order": "None",
                    "destination": "Anywhere", "destination_x": 0, "destination_y": 0,
                }
                MassiveFeatureMixin.massive_action(self, "Create Wave", wave_args, owner)
                targets = self._group_units(wave_args["group"])
            else:
                targets = [unit for unit in self._selected_units(args, player) if int(unit.unit_type) in SAPPER_TYPES]
            if kind == "Arm Sappers":
                # The source intentionally makes sappers explode if given
                # Invisibility or Unholy Armor. Arm uses a harmless runtime tag,
                # not those dangerous native timers.
                for unit in targets:
                    self._apply_custom_effect(unit, TimedEffect("Armed Sapper", time.monotonic() + max(1.0, float(args.get("seconds", 60)))))
                return True
            destination = str(args.get("destination", "Anywhere"))
            if destination == "Anywhere":
                x, y = int(args.get("x", 0)), int(args.get("y", 0))
            else:
                loc = self._find_location(destination)
                x, y = (loc.left + loc.right) // 2, (loc.top + loc.bottom) // 2
            target_unit = self._resolve_unit_reference(args.get("target_reference", "")) if str(args.get("target_reference", "")).strip() else None
            self._call_cdecl_batched([
                (self.order_callees["set_target"], [unit.address, x, y, target_unit.address if target_unit else 0, do_demolish])
                for unit in targets
            ])
            self.log(f"SAPPER DEMOLISH: ordered {len(targets)} sapper(s) toward ({x},{y})")
            return True

        # Advanced combat effects and traits.
        if kind in {"Apply Stun", "Apply Root", "Apply Silence", "Apply Fear", "Apply Taunt", "Apply Damage Over Time", "Apply Healing Over Time", "Add Shield", "Clear Custom Effects"}:
            units = self._selected_units(args, player)
            seconds = max(0.1, float(args.get("seconds", 5)))
            now = time.monotonic()
            mapping = {
                "Apply Stun": "Stun", "Apply Root": "Root", "Apply Silence": "Silence",
                "Apply Fear": "Fear", "Apply Taunt": "Taunt",
                "Apply Damage Over Time": "Damage Over Time", "Apply Healing Over Time": "Healing Over Time",
                "Add Shield": "Shield",
            }
            if kind == "Clear Custom Effects":
                effect = str(args.get("effect", "All"))
                for unit in units:
                    key = self._unit_key_massive(unit)
                    if effect == "All":
                        self.custom_effects.pop(key, None)
                    else:
                        self.custom_effects.get(key, {}).pop(effect, None)
                return True
            effect_name = mapping[kind]
            for unit in units:
                effect = TimedEffect(
                    effect_name, now + seconds,
                    amount=float(args.get("amount", 40)),
                    interval=max(0.1, float(args.get("interval", 1.0))),
                    source_ref=str(args.get("source_reference", "")),
                )
                self._apply_custom_effect(unit, effect)
            self.log(f"CUSTOM EFFECT: {effect_name} applied to {len(units)} unit(s) for {seconds:.1f}s")
            return True
        if kind in {"Set Lifesteal", "Set Critical Strike", "Set Evasion", "Set Reflect Damage", "Set Cleave"}:
            units = self._selected_units(args, player)
            for unit in units:
                traits = self.combat_traits.setdefault(self._unit_key_massive(unit), {})
                if kind == "Set Lifesteal":
                    traits["Lifesteal"] = max(0.0, min(100.0, float(args.get("percent", 20))))
                elif kind == "Set Critical Strike":
                    traits["Critical Chance"] = max(0.0, min(100.0, float(args.get("chance", 20))))
                    traits["Critical Multiplier"] = max(1.0, min(10.0, float(args.get("multiplier", 2.0))))
                elif kind == "Set Evasion":
                    traits["Evasion"] = max(0.0, min(100.0, float(args.get("percent", 20))))
                elif kind == "Set Reflect Damage":
                    traits["Reflect"] = max(0.0, min(500.0, float(args.get("percent", 25))))
                else:
                    traits["Cleave"] = max(0.0, min(500.0, float(args.get("percent", 35))))
            return True
        if kind in {"Knockback Units", "Pull Units"}:
            units = self._selected_units(args, player)
            anchor = self._resolve_unit_reference(args.get("anchor_reference", "Anchor"))
            if anchor is None:
                ax, ay = self._resolve_point(args, "anchor_location")
            else:
                ax, ay = int(anchor.x), int(anchor.y)
            distance = max(1, min(16, int(args.get("distance", 3))))
            for unit in units:
                dx, dy = int(unit.x) - ax, int(unit.y) - ay
                length = max(1.0, math.hypot(dx, dy))
                sign = -1 if kind == "Pull Units" else 1
                tx = round(int(unit.x) + sign * distance * dx / length)
                ty = round(int(unit.y) + sign * distance * dy / length)
                try:
                    self._move_mobile_unit(unit, tx, ty)
                except Exception:
                    continue
            return True

        # Projectile controls.
        if kind in {"Redirect Projectiles", "Destroy Projectiles", "Duplicate Projectiles"}:
            missiles = self._selected_missiles(args, player)
            if kind == "Destroy Projectiles":
                for missile in missiles:
                    self._dispatch_ops([("write_bytes", missile.address + 0x35, bytes([int(missile.flags) | 0x01]))])
                return True
            destination = str(args.get("destination", "Anywhere"))
            if destination == "Anywhere":
                x, y = int(args.get("x", 0)), int(args.get("y", 0))
            else:
                loc = self._find_location(destination)
                x, y = (loc.left + loc.right) // 2, (loc.top + loc.bottom) // 2
            if kind == "Redirect Projectiles":
                for missile in missiles:
                    self._dispatch_ops([
                        ("write_word", missile.address + 0x28, x),
                        ("write_word", missile.address + 0x2A, y),
                        ("write_dword", missile.address + 0x2C, 0),
                    ])
                return True
            # Duplicate through the validated Create Missile action using each
            # projectile's living owner and target when available.
            world = self.units()
            for missile in missiles[:16]:
                attacker = next((u for u in world if u.address == missile.owner_unit), None)
                target = next((u for u in world if u.address == missile.target_unit), None)
                if attacker and target:
                    for _ in range(max(1, min(8, int(args.get("copies", 1))))):
                        self._create_missile(attacker, target)
            return True

        # Tactical AI, wave director, and boss phases.
        if kind == "Enable Tactical AI":
            name = str(args.get("name", "Squad AI 1"))
            self.tactical_ai[name] = dict(args)
            return True
        if kind == "Disable Tactical AI":
            self.tactical_ai.pop(str(args.get("name", "Squad AI 1")), None)
            return True
        if kind == "Start TD Native HP Ladder":
            name = str(args.get("name", "TD Native HP Ladder")).strip() or "TD Native HP Ladder"
            owner = int(args.get("player", player))
            if not 0 <= owner <= 7:
                raise ValueError("TD Native HP Ladder supports P1-P8 wave owners")

            raw_unused = args.get("unused_unit_ids_json", "[34,36,37,48,54]")
            unused_values = json.loads(raw_unused) if isinstance(raw_unused, str) else list(raw_unused)
            unused = {int(value) for value in unused_values}
            if any(not 0 <= value <= MOBILE_MAX for value in unused):
                raise ValueError("TD Native HP Ladder unused IDs must be mobile unit IDs 0-57")
            # Always exclude the five source/art-reserved slots even if a sidecar
            # accidentally omits them. Additional IDs may be excluded explicitly.
            unused |= set(TD_UNUSED_MOBILE_TYPES)
            unit_types = [unit_type for unit_type in range(MOBILE_MAX + 1) if unit_type not in unused]
            if not unit_types:
                raise ValueError("TD Native HP Ladder has no usable mobile unit IDs")

            raw_route = args.get("route_json", "[]")
            route = json.loads(raw_route) if isinstance(raw_route, str) else list(raw_route)
            if not isinstance(route, list) or not route:
                raise ValueError("TD Native HP Ladder route_json must be a non-empty JSON list")
            route = [str(item).strip() for item in route if str(item).strip()]
            for location_name in route:
                self._find_location(location_name)

            native_hp: dict[int, int] = {}
            for unit_type in unit_types:
                hp = int(self.pm.read_ushort(self.base + UNIT_HP_TABLE_RVA + unit_type * 2))
                if hp <= 0:
                    # A real mobile type with a zero value is still kept, but use 1
                    # for deterministic ordering/scaling and make it obvious in log.
                    self.log(f"TD LADDER HP WARNING: unit {unit_type} native max HP read {hp}; treating as 1")
                    hp = 1
                native_hp[unit_type] = hp
            ordered = sorted(unit_types, key=lambda unit_type: (native_hp[unit_type], unit_type))

            total_start = max(1, min(10000, int(args.get("total_start", 160))))
            total_growth = max(0, min(500, int(args.get("total_growth", 5))))
            hp_scale_start = max(100.0, min(5000.0, float(args.get("hp_scale_start_percent", 150.0))))
            hp_scale_growth = max(0.0, min(500.0, float(args.get("hp_scale_growth_percent", 10.0))))
            hp_floor_start = max(1, min(65535, int(args.get("hp_floor_start", 80))))
            hp_floor_growth = max(0, min(5000, int(args.get("hp_floor_growth", 15))))
            plan: list[dict[str, int]] = []
            previous_max = 0
            for index, unit_type in enumerate(ordered):
                base_hp = native_hp[unit_type]
                scale = hp_scale_start + index * hp_scale_growth
                scaled = int(math.ceil(base_hp * scale / 100.0))
                floor_hp = hp_floor_start + index * hp_floor_growth
                max_hp = max(base_hp, scaled, floor_hp, previous_max)
                max_hp = max(1, min(65535, max_hp))
                previous_max = max_hp
                total = max(1, min(10000, total_start + index * total_growth))
                plan.append({"unit_type": unit_type, "base_hp": base_hp, "max_hp": max_hp, "total": total})

            lane_count = max(1, min(5, int(args.get("lane_count", 3))))
            if lane_count % 2 == 0:
                lane_count -= 1
            state = TDNativeHPLadderState(
                name=name,
                owner=owner,
                plan=plan,
                batch_size=max(1, min(32, int(args.get("batch_size", 4)))),
                interval=max(0.20, min(30.0, float(args.get("interval", 0.30)))),
                first_wave_delay=max(0.0, min(600.0, float(args.get("first_wave_delay", 15.0)))),
                intermission=max(0.0, min(600.0, float(args.get("intermission", 5.0)))),
                spawn_location=str(args.get("spawn_location", "Enemy Spawn")),
                spawn_x=int(args.get("spawn_x", 0)),
                spawn_y=int(args.get("spawn_y", 0)),
                route=route,
                lane_count=lane_count,
                naval_as_flying=bool(args.get("naval_as_flying", True)),
                mana=max(0, min(255, int(args.get("mana", 255)))),
                max_spawn_queue=max(0, min(64, int(args.get("max_spawn_queue", 0)))),
                stall_reissue=max(0.5, min(10.0, float(args.get("stall_reissue", 0.9)))),
                spawn_rescue_after=max(1.0, min(20.0, float(args.get("spawn_rescue_after", 1.75)))),
                builder_player=int(args.get("builder_player", 5)),
                builder_unit=int(args.get("builder_unit", 11)),
                builder_refill_mana=max(0, min(255, int(args.get("builder_refill_mana", 255)))),
                waiting_until=time.monotonic() + max(0.0, min(600.0, float(args.get("first_wave_delay", 15.0)))),
            )
            old = self.td_native_hp_ladders.get(name)
            if old is not None and old.active:
                self._td_ladder_stop(old)
            self.td_native_hp_ladders[name] = state
            self.counters[f"{name} Total Waves"] = len(plan)
            self.counters[f"{name} Current Wave"] = 0
            self.counters[f"{name} Complete"] = 0
            self.counters[f"{name} Active"] = 1
            self.counters["Wave"] = 0
            self.log(
                f"TD NATIVE HP LADDER START: {name}; {len(plan)} real mobile unit waves; "
                f"excluded IDs {sorted(unused)}; sorted by live native max HP then unit ID"
            )
            for index, item in enumerate(plan, 1):
                unit_type = item["unit_type"]
                unit_name = TD_MOBILE_NAMES[unit_type]
                duration = math.ceil(item["total"] / state.batch_size) * state.interval
                self.log(
                    f"TD LADDER PLAN {index:02d}/{len(plan)}: U{unit_type:02d} {unit_name}; "
                    f"native {item['base_hp']} HP -> TD {item['max_hp']} HP; "
                    f"{item['total']} units; nominal spawn {duration:.1f}s"
                )
            return True
        if kind == "Stop TD Native HP Ladder":
            name = str(args.get("name", "TD Native HP Ladder")).strip() or "TD Native HP Ladder"
            state = self.td_native_hp_ladders.get(name)
            if state is not None:
                self._td_ladder_stop(state)
                self.log(f"TD NATIVE HP LADDER STOPPED: {name}")
            return True
        if kind == "Start TD Stream Wave":
            name = str(args.get("name", "TD Wave 1")).strip()
            owner = int(args.get("player", player))
            unit_type = int(args.get("unit", 1))
            raw_roster = args.get("unit_roster_json", "")
            if raw_roster not in (None, "", []):
                roster = json.loads(raw_roster) if isinstance(raw_roster, str) else list(raw_roster)
            else:
                roster = [unit_type]
            roster = [int(value) for value in roster]
            if not 0 <= owner <= 7:
                raise ValueError("TD stream waves support P1-P8 owners")
            if not roster or any(not 0 <= value <= MOBILE_MAX for value in roster):
                raise ValueError("TD stream wave roster must contain mobile unit IDs 0-57")
            raw_route = args.get("route_json", "[]")
            route = json.loads(raw_route) if isinstance(raw_route, str) else list(raw_route)
            if not isinstance(route, list) or not route:
                raise ValueError("TD stream wave route_json must be a non-empty JSON list")
            route = [str(item).strip() for item in route if str(item).strip()]
            if not route:
                raise ValueError("TD stream wave route cannot be empty")
            for location_name in route:
                self._find_location(location_name)
            lane_count = int(args.get("lane_count", 3))
            lane_count = max(1, min(5, lane_count))
            if lane_count % 2 == 0:
                lane_count -= 1
            state = TDStreamWaveState(
                name=name,
                owner=owner,
                unit_roster=roster,
                total=max(1, min(10000, int(args.get("total", 200)))),
                batch_size=max(1, min(32, int(args.get("batch_size", 3)))),
                interval=max(0.20, min(30.0, float(args.get("interval", 0.35)))),
                spawn_location=str(args.get("spawn_location", "Anywhere")),
                spawn_x=int(args.get("spawn_x", 0)),
                spawn_y=int(args.get("spawn_y", 0)),
                route=route,
                max_hp=max(1, min(65535, int(args.get("max_hp", 100)))),
                mana=max(0, min(255, int(args.get("mana", 0)))),
                group=str(args.get("group", name)).strip() or name,
                max_spawn_queue=max(0, min(64, int(args.get("max_spawn_queue", 0)))),
                stall_reissue=max(0.5, min(10.0, float(args.get("stall_reissue", 1.0)))),
                spawn_rescue_after=max(1.0, min(20.0, float(args.get("spawn_rescue_after", 2.0)))),
                lane_count=lane_count,
                naval_as_flying=bool(args.get("naval_as_flying", True)),
                next_spawn_at=time.monotonic(),
            )
            for roster_type in sorted(set(state.unit_roster)):
                self._td_stream_prepare_type(state, roster_type)
            self.td_stream_waves[name] = state
            self.unit_groups[state.group] = set()
            self.counters[f"{name} Spawned"] = 0
            self.counters[f"{name} Target"] = state.total
            self.counters[f"{name} Complete"] = 0
            self.counters[f"{name} Active"] = 1
            self.log(
                f"TD STREAM START: {name}; P{owner + 1} roster {state.unit_roster}; total {state.total}; "
                f"batch {state.batch_size}/{state.interval:.2f}s; absolute max HP {state.max_hp}; "
                f"centered lanes {state.lane_count}; naval-as-flying={state.naval_as_flying}; "
                f"spawn queue {'unlimited' if state.max_spawn_queue <= 0 else state.max_spawn_queue}; route {' -> '.join(state.route)}"
            )
            return True
        if kind == "Stop TD Stream Wave":
            name = str(args.get("name", "TD Wave 1")).strip()
            state = self.td_stream_waves.get(name)
            if state:
                state.active = False
                self.counters[f"{name} Active"] = 0
            return True
        if kind == "Start Wave Director":
            name = str(args.get("name", "Wave Director 1"))
            raw_pool = args.get("unit_pool", "0")
            if isinstance(raw_pool, str):
                unit_pool = [int(part.strip(), 0) for part in raw_pool.replace(";", ",").split(",") if part.strip()]
            else:
                unit_pool = [int(value) for value in raw_pool]
            if not unit_pool or any(not 0 <= value <= MOBILE_MAX for value in unit_pool):
                raise ValueError("Wave Director unit pool must contain mobile unit IDs 0-57")
            state = WaveDirectorState(
                name=name, owner=int(args.get("player", player)), unit_pool=unit_pool,
                spawn_location=str(args.get("spawn_location", "Anywhere")),
                spawn_x=int(args.get("spawn_x", 0)), spawn_y=int(args.get("spawn_y", 0)),
                destination=str(args.get("destination", "Anywhere")),
                destination_x=int(args.get("destination_x", 0)), destination_y=int(args.get("destination_y", 0)),
                base_count=max(1, int(args.get("base_count", 6))), growth=max(0, int(args.get("growth", 2))),
                intermission=max(0.25, float(args.get("intermission", 5))), max_waves=max(0, int(args.get("max_waves", 10))),
                boss_every=max(0, int(args.get("boss_every", 5))), boss_unit=int(args.get("boss_unit", -1)),
                formation=str(args.get("formation", "Grid")), spacing=max(1, int(args.get("spacing", 1))),
                group_prefix=str(args.get("group_prefix", name)), waiting_until=time.monotonic() + max(0.0, float(args.get("start_delay", 0))),
            )
            self.wave_directors[name] = state
            return True
        if kind == "Stop Wave Director":
            state = self.wave_directors.get(str(args.get("name", "Wave Director 1")))
            if state:
                state.active = False
            return True
        if kind == "Advance Wave Director":
            state = self.wave_directors.get(str(args.get("name", "Wave Director 1")))
            if not state:
                raise ValueError("Unknown Wave Director")
            if state.current_group:
                self.unit_groups.pop(state.current_group, None)
            state.waiting_until = 0.0
            return True
        if kind == "Start Boss Controller":
            name = str(args.get("name", "Boss 1"))
            phases_raw = args.get("phases_json", "[]")
            phases = json.loads(phases_raw) if isinstance(phases_raw, str) else list(phases_raw)
            if not isinstance(phases, list):
                raise ValueError("Boss phases JSON must be a list")
            phases = sorted((dict(phase) for phase in phases), key=lambda p: float(p.get("health_at_or_below", 100)), reverse=True)
            self.boss_controllers[name] = BossControllerState(name, str(args.get("reference", "Boss")), phases)
            return True
        if kind == "Stop Boss Controller":
            state = self.boss_controllers.get(str(args.get("name", "Boss 1")))
            if state:
                state.active = False
            return True

        # Economy and production.
        if kind in {"Transfer Resources", "Steal Resources", "Tax Player"}:
            source = int(args.get("source_player", player))
            destination = int(args.get("destination_player", player))
            resource = str(args.get("resource", "Gold"))
            amount = max(0, int(args.get("amount", 0)))
            available = self._read_resource(source, resource)
            moved = min(available, amount)
            self.action("Subtract Resources", {"player": source, "resource": resource, "amount": moved}, player)
            self.action("Add Resources", {"player": destination, "resource": resource, "amount": moved}, player)
            return True
        if kind == "Start Periodic Income":
            name = str(args.get("name", "Income 1"))
            self.periodic_income[name] = {
                "player": int(args.get("player", player)), "resource": str(args.get("resource", "Gold")),
                "amount": max(0, int(args.get("amount", 100))), "interval": max(0.25, float(args.get("interval", 5))),
                "next": time.monotonic() + max(0.0, float(args.get("start_delay", 0))),
            }
            return True
        if kind == "Stop Periodic Income":
            self.periodic_income.pop(str(args.get("name", "Income 1")), None)
            return True
        if kind == "Refill Resource Node":
            units = self._selected_units(args, player)
            amount = max(0, min(65535, int(args.get("amount", 50000))))
            changed = 0
            for unit in units:
                if int(unit.unit_type) not in {92, 93}:
                    continue
                # Gold Mine/Oil Patch resource quantity is the source build's
                # building union word at +0x84, already validated for fresh
                # construction progress. This action is intentionally limited to
                # these two map-resource object types.
                self._dispatch_ops([("write_word", unit.address + 0x84, amount)])
                changed += 1
            self.log(f"RESOURCE NODE: refilled {changed} mine/oil object(s) to {amount}")
            return True
        if kind == "Train Units Instantly At Buildings":
            buildings = self._selected_units(args, player)
            unit_type = int(args.get("new_unit", 0))
            amount_each = max(1, min(16, int(args.get("amount_each", 1))))
            group = str(args.get("group", "Instant Production"))
            created: list[Any] = []
            for building in buildings[:64]:
                for _ in range(amount_each):
                    unit = self._create_unit(int(args.get("new_owner", building.owner)), unit_type, int(building.x) + 1, int(building.y) + 1)
                    if unit:
                        created.append(unit)
            if group:
                self.unit_groups[group] = {self._unit_key_massive(unit) for unit in created}
            self.log(f"INSTANT PRODUCTION: created {len(created)} unit(s) at {len(buildings)} building(s)")
            return True

        # RPG, inventory, quests, and transmissions.
        if kind == "Register Hero":
            unit = self._resolve_unit_reference(args.get("reference", "Hero"))
            if unit is None:
                raise RuntimeError("Register Hero requires a live unit reference")
            self.hero_state[self._unit_key_massive(unit)] = {
                "level": max(1, int(args.get("level", 1))), "xp": max(0, int(args.get("xp", 0))),
                "next_level_xp": max(1, int(args.get("next_level_xp", 100))),
                "growth": max(1.0, float(args.get("xp_growth", 1.25))),
                "xp_per_kill": max(0, int(args.get("xp_per_kill", 10))),
                "hp_per_level": max(0, int(args.get("hp_per_level", 10))),
            }
            return True
        if kind in {"Add Hero Experience", "Set Hero Level"}:
            unit = self._resolve_unit_reference(args.get("reference", "Hero"))
            if unit is None:
                raise RuntimeError("Hero action requires a live unit reference")
            state = self.hero_state.setdefault(self._unit_key_massive(unit), {"level": 1, "xp": 0, "next_level_xp": 100, "growth": 1.25, "xp_per_kill": 10, "hp_per_level": 10})
            if kind == "Add Hero Experience":
                state["xp"] = int(state.get("xp", 0)) + max(0, int(args.get("amount", 0)))
            else:
                state["level"] = max(1, int(args.get("level", 1)))
            return True
        if kind in {"Give Inventory Item", "Remove Inventory Item", "Clear Inventory"}:
            unit = self._resolve_unit_reference(args.get("reference", "Hero"))
            if unit is None:
                raise RuntimeError("Inventory action requires a live unit reference")
            bag = self.inventory.setdefault(self._unit_key_massive(unit), {})
            if kind == "Clear Inventory":
                bag.clear()
            else:
                item = str(args.get("item", "Item"))
                amount = max(0, int(args.get("amount", 1)))
                bag[item] = max(0, int(bag.get(item, 0)) + (amount if kind == "Give Inventory Item" else -amount))
                if bag[item] == 0:
                    bag.pop(item, None)
            return True
        if kind in {"Set Quest", "Complete Quest", "Fail Quest", "Clear Quest"}:
            name = str(args.get("quest", "Quest 1"))
            if kind == "Clear Quest":
                self.quests.pop(name, None)
            else:
                self.quests[name] = {"Set Quest": "Active", "Complete Quest": "Completed", "Fail Quest": "Failed"}[kind]
            return True
        if kind == "Transmission":
            speaker = str(args.get("speaker", "Narrator"))
            text = str(args.get("text", ""))
            message = f"{speaker}: {text}" if speaker else text
            self.action("Game Message", {"text": message, "color": args.get("color", "White — native highlight"), "recipients": args.get("recipients", "All active players"), "seconds": int(args.get("seconds", 5)), "also_log": True}, player)
            reference = str(args.get("reference", "")).strip()
            unit = self._resolve_unit_reference(reference) if reference else None
            if unit is not None and bool(args.get("center_camera", False)):
                MassiveFeatureMixin.massive_action(self, "Center Camera", {"location": "Anywhere", "x": unit.x, "y": unit.y}, player)
            return True

        # Diagnostics.
        if kind == "Watch Expression":
            expression = str(args.get("expression", "0"))
            value = self._evaluate_expression(expression, player)
            self.log(f"WATCH: {expression} = {value}")
            return True
        if kind == "Dump Unit References":
            entries = []
            for name in sorted(self.unit_references):
                unit = self._resolve_unit_reference(name)
                entries.append(f"{name}={'dead' if unit is None else f'P{unit.owner+1} type {unit.unit_type} ({unit.x},{unit.y}) HP {unit.health}'}")
            self.log("UNIT REFERENCES: " + ("; ".join(entries) if entries else "none"))
            return True
        if kind == "Dump Unit Group":
            name = str(args.get("group", "Unit Group 1"))
            units = self._group_units(name)
            self.log(f"UNIT GROUP DUMP: {name} has {len(units)} live unit(s): " + ", ".join(f"P{u.owner+1}/T{u.unit_type}@{u.x},{u.y}" for u in units[:64]))
            return True

        return super().massive_action(kind, args, player)
