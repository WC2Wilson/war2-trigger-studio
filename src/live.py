from __future__ import annotations

from dataclasses import dataclass
import math
import re
import struct
import sys
import threading
from pathlib import Path
import time
from typing import Any

from engine import ActionDeferred
from massive_features import MASSIVE_UNHANDLED
from card_engine import CardEngineMixin
from compatibility import KNOWN_BUILDS, parse_loaded_pe, scan_compatibility, export_report


SUPPORTED_SHA256 = "c0e96e9b19d532d3c52a2c079ff127a9f372d645dcd58fad4888cb23944060bc"
SUPPORTED_TIMESTAMPS = {
    0x6813B7ED: "installed 1.0.2.2505",
    0x681446FD: "uploaded 1.0.2.2505",
    0x699E13E7: "installed 1.0.2.2818",
}
DISPATCH_SYNC_WAIT = 0.35
DISPATCH_RETRY_DELAY = 0.05
DISPATCH_NOTICE_INTERVAL = 5.0
SIMULATION_DISPATCH_HOOK_RVA = 0x000EEA80
SIMULATION_DISPATCH_RETURN_RVA = 0x000EEA85
SIMULATION_DISPATCH_ORIGINAL = b"\x55\x8B\xEC\x51\x53"
DISPATCH_MEMORY_SIZE = 0x2000
DISPATCH_HOOK_OFFSET = 0x0000
DISPATCH_COMMAND_OFFSET = 0x0400
DISPATCH_COMMAND_CAPACITY = 0x1000
DISPATCH_STATE_OFFSET = 0x1800
DISPATCH_RESULT_OFFSET = 0x1804
DISPATCH_HEARTBEAT_OFFSET = 0x1808
DISPATCH_MAGIC_OFFSET = 0x180C
# Persistent shared-vision guard lives in otherwise-unused mailbox control bytes.
# The simulation trampoline writes all eight desired masks before every native tick,
# and the diplomacy-entry guard substitutes the desired source mask before Warcraft
# can rebuild gSharedVision from stale scenario/player state.
DISPATCH_VISION_MASKS_OFFSET = 0x1810
DISPATCH_VISION_ACTIVE_OFFSET = 0x1818
# Retained for mailbox-layout compatibility. WT30 keeps this byte equal to the
# native gbMultiPlayer value; shared vision no longer redirects visibility gates.
DISPATCH_VISION_MODE_OFFSET = 0x1819
DIPLOMACY_GUARD_CODE_OFFSET = 0x0200
DIPLOMACY_GUARD_HOOK_LENGTH = 7
DISPATCH_MAGIC = 0x30335457  # "WT30" -- post-reset local fog compositor generation
CHAT_PACKET_OFFSET = 0x1900
CHAT_PACKET_CAPACITY = 0x0100
CHAT_LOCAL_TEXT_OFFSET = 0x1A00
CHAT_LOCAL_TEXT_CAPACITY = 0x0100
# TD Raise Tower extension.  The dispatcher allocation has 0x1B00-0x1FFF free.
TD_BUILDER_DATA_OFFSET = 0x1B00
TD_BUILDER_CODE_OFFSET = 0x1C00
TD_BUILDER_TRAMPOLINE_OFFSET = 0x1D00
TD_BUILDER_ACTION_PATCH_LENGTH = 10
TD_BUILDER_MAGIC = 0x42544457  # "WDTB"
TD_BUILDER_PENDING_OFFSET = TD_BUILDER_DATA_OFFSET + 0x04
TD_BUILDER_CASTER_OFFSET = TD_BUILDER_DATA_OFFSET + 0x08
TD_BUILDER_X_OFFSET = TD_BUILDER_DATA_OFFSET + 0x0C
TD_BUILDER_Y_OFFSET = TD_BUILDER_DATA_OFFSET + 0x10
# Source gbRangedOrderTbl spell-range tail, SPELL_VISION through ORDER_NONE.
TD_RANGED_SPELL_SIGNATURE = bytes((0xFF, 6, 0, 10, 6, 10, 10, 6, 10, 12, 0xFF, 6, 6, 10, 12, 6, 6, 10, 12, 0xFF, 0, 0, 0xFF))
PACKET_SEND_STRING_RVA = 0x000F1540
NET_SEND_MSG_ALL_RVA = 0x00117B30
MAP_MSG_RVA = 0x000D3160
FONT_SET_COLOR_TABLE_RVA = 0x001859F0
FONT_SET_COLOR_TABLE_RVAS = {
    0x6813B7ED: 0x001859F0,
    0x681446FD: 0x001859F0,
    0x699E13E7: 0x00185B20,
}
MAP_MESSAGE_DRAW_RVA = 0x000D35E0
CHAT_FILTER_RVA = 0x00518BE9
PM_STRING = 0x23
MAX_NATIVE_MESSAGE_BYTES = 78
MILLISECONDS_PER_SECOND = 1000
NATIVE_CHAT_DISPLAY_DELAY = 7000
NET_MAX_NODES = 8
PM_SET_SPEED = 0x27
GAME_SPEED_LEVELS = ("Slowest", "Slower", "Slow", "Normal", "Fast", "Faster", "Fastest")
PLAYER_COLOR_NAMES = ("Red", "Blue", "Teal", "Violet", "Orange", "Black", "White", "Yellow")
PLAYER_REFERENCE_MODES = (
    "Live owner slots (P1-P8)",
    "Displayed colors / fixed order (P1=Red, P2=Blue, P3=Teal, P4=Violet, P5=Orange, P6=Black, P7=White, P8=Yellow)",
)

# Both native message forms enter through map_msg, exactly like PM_STRING in the
# original packet dispatcher. Player senders use the seven-line rolling chat
# queue; sender 8 uses the one-line game-information slot. Remaster stores the
# selected line color in a separate renderer-owned byte array; 1.24.5 writes the
# final slot's color byte after map_msg chooses the slot. Inline 0x01-0x06 tags
# remain supported for changes inside a line.
NATIVE_MESSAGE_COLORS = {
    "Native sender color — no override": None,
    "Yellow / gold — native normal": 0x02,
    "White — native highlight": 0x03,
    "Red — native selected / warning": 0x04,
    "Gray — native disabled": 0x05,
    "Game yellow — native game palette": 0x06,
}
NATIVE_MESSAGE_COLOR_TAGS = {
    "yellow": 0x02,
    "gold": 0x02,
    "normal": 0x02,
    "white": 0x03,
    "highlight": 0x03,
    "hilite": 0x03,
    "red": 0x04,
    "select": 0x04,
    "warning": 0x04,
    "gray": 0x05,
    "grey": 0x05,
    "disabled": 0x05,
    "game": 0x06,
    "game yellow": 0x06,
}
MAX_SPELL_TARGET_POINTS = 32
VISION_REGIONS_PER_BATCH = 32
DISPATCH_STATE_IDLE = 0
DISPATCH_STATE_QUEUED = 1
DISPATCH_STATE_EXECUTING = 2
DISPATCH_STATE_COMPLETE = 3
UNIT_SIZE = 152
UNIT_ARRAY_RVA = 0x51C704
MAX_UNITS_RVA = 0x51BFB8
BULLET_SIZE = 0x40
BULLET_ARRAY_RVA = 0x51C700
MAX_BULLETS_RVA = 0x51BFBC
UNIT_BULLET_TABLE_RVA = 0x5182A0
BT_NONE = 29
UNIT_MAP_RVA = 0x51AD6C
AIR_UNIT_MAP_RVA = 0x51AD70
RUNE_X_RVA = 0x518D14
RUNE_Y_RVA = 0x518D48
RUNE_DELAY_RVA = 0x518D80
MAX_RUNES = 50
RUNE_TIME = 0x0800
BT_RUNE = 11
BT_SPARKLE = 22
BT_FIREBALL = 2
BT_FLAME_SHIELD = 3
BT_FLAME_SPIN = 4
BT_BLIZZARD = 5
BT_EXORCISM = 8
UNIT_GLOBAL_RVAS = (0x534A68, 0x53484C, 0x534B8C)
MTXM_GLOBAL_RVA = 0x560DF4
MAP_DIMENSION_RVA = 0x518D10
LOCAL_PLAYER_RVA = 0x518CCD
LOCAL_HUMAN_PLAYER = -2
FIRST_NON_LOCAL_PLAYER = -3
VISION_MASK_TABLE_RVA = 0x4C4EC8
DEFAULT_VISION_DURATION = 0.0
MAX_VISION_DURATION = 600.0
ACTION_TYPE_RVA = 0x5348BC
UNIT_ACTION_FUNCTION_TABLE_RVA = 0x4C1498
UNIT_ACTION_USER_DISPATCH_TABLE_RVA = 0x4C13A0
UNIT_ACTION_DISPATCH_TABLE_RVA = 0x4C1590
SPELL_AREA_EFFECT_TABLE_RVA = 0x4C1804
CASTING_COST_TABLE_RVA = 0x4C5EB8
RESOURCE_RVAS = {
    "Gold": 0x519128,
    "Lumber": 0x5190E8,
    "Oil": 0x519168,
}
STAT_RVAS = {
    "Deaths Men": 0x519438,
    "Deaths Buildings": 0x519458,
    "Kills Men": 0x519478,
    "Kills Buildings": 0x519498,
    "Score": 0x5193A8,
}
UNIT_SCORE_RVA = 0x5184A0
GAME_MODE_RVA = 0x51C184
BUILDINGS_IN_PROGRESS_RVA = 0x519410
UNIT_HP_TABLE_RVA = 0x5177C0
UNIT_IS_TABLE_RVA = 0x5185F0
CHEAT_BITS_RVA = 0x51B270
GAME_RUN = 3
GAME_VICTORY = 6
GAME_LOSS = 7
MAX_RESOURCE_VALUE = 0x7FFFFFFF
DAMAGE_UNIT_RVA = 0x0BD8F0
DAMAGE_UNIT_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x0C\x0F\xB7\x4E\x1E\xF6\xC1\x07"
UNIT_CREATE_SIGNATURE = b"\x55\x8B\xEC\x83\xEC\x0C\x8A\x45\x14\x56\x50\x89\x45\xF8"
CAPTURE_UNIT_SIGNATURE = b"\x55\x8B\xEC\x53\x8B\x5D\x0C\x56\x8B\x75\x08\x0F\xB6\x46\x27\xF6\x04\x85"
UNIT_FREE_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x08\x56\xE8\xB3\x29\x00\x00\x56\xE8\xAD\xEC\xFF\xFF\x83\xC4\x08"
UNIT_UNMASK_SQUARE_SIGNATURE = b"\x55\x8B\xEC\x8B\x55\x08\x83\xEC\x08\x80\x3D"
UNIT_SET_CURR_ACTION_SIGNATURE = b"\x55\x8B\xEC\x83\x3D"
UNIT_SET_TARGET_SIGNATURE = b"\x55\x8B\xEC\x83\xEC\x08\x57\x8B\x7D\x08\x0F\xB6\x47\x2E"
DO_UNIT_MOVE_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x08\xB9\x0A\x00\x00\x00\x57\xBF\x28\x00\x00\x00"
DO_UNIT_ATTACK_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x08\x83\xBE\x88\x00\x00\x00\x00\x74"
DO_UNIT_PATROL_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x08\x8B\x46\x18\x57\x8D\x7E\x18\xC7\x86\x88\x00\x00\x00"
DIPLOMACY_UPDATE_RVA = 0x000D6740
ENEMY_TABLE_RVA = 0x00519578
SHARED_VISION_RVA = 0x00519678
ALLIED_VICTORY_RVA = 0x00518D13
OWNER_TYPE_TABLE_RVA = 0x00518CAC
C_PLAYER = 0
C_COMPUTER = 1
C_NEUTRAL = 2
C_NONE = 3
# Live 1.0.2.2505 behavior and clean-match self cells confirm the relation
# values used by unit selection, native retargeting, and the diplomacy updater:
# 0 is Enemy and 1 is Allied. Emitted diagonals are repaired to Allied (1).
RELATION_ENEMY = 0
RELATION_ALLIED = 1
VISION_REFRESH_RVA = 0x000F11C0
DIPLOMACY_UPDATE_SIGNATURE = b"\x55\x8B\xEC\x66\x8B\x4D\x0C\x56\x0F\xB6\x75\x08\x8A\xC1\x24\x03"
UNITDRAW_SET_SELECTION_COLORS_RVA = 0x000F0D10
# Actual Battle.net Edition gbMultiPlayer byte.  It is decoded again from
# unit_unmask_square at attach time; that routine skips the C_PLAYER-only fog
# guard when this byte is nonzero.  RVA 0x51C178 is an unrelated DWORD game
# option and must never be used as the multiplayer/vision switch.
MULTIPLAYER_MODE_RVA = 0x00522F5B
# Legacy builds replaced these branches directly. That made individual routines
# take hand-picked paths, but it did not reproduce the single consistent state
# produced by gbMultiPlayer=1 and could leave alternating visibility caches. 1.23.36
# restores any old branch patches and instead redirects the gate operand used by
# visibility code to DISPATCH_VISION_MODE_OFFSET. The real gbMultiPlayer byte stays
# zero, so Peon orders, Pause, saving, and local command routing remain offline.
SHARED_VISION_OFFLINE_PATCHES = (
    (0x000D3909, b"\x74\x08", b"\x90\x90"),
    (0x000D3975, b"\x74\x06", b"\x90\x90"),
    (0x000D3A21, b"\x74\x1F", b"\x90\x90"),
    (0x000F025D, b"\x74\x0C", b"\x90\x90"),
    (0x000F02D4, b"\x74\x7E", b"\x90\x90"),
    (0x000F11F1, b"\x74\x2A", b"\x90\x90"),
    (0x000EF364, b"\x75\x10", b"\xEB\x10"),
)
# Additional xrefs in these tightly scoped fog/unit-draw ranges are discovered and
# redirected as well. This avoids guessing that the seven historical branches are
# the only readers used by moving units and renderer visibility.
SHARED_VISION_GATE_SCAN_WINDOWS = (
    (0x000D3600, 0x000D3C00),
    (0x000EF300, 0x000EF3C0),
    (0x000F0000, 0x000F1300),
)
ACTION_DO_ATTACK_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x08\x56\x0F\xB6\x46\x27\x80\xB8"
PLACE_RUNE_SIGNATURE = b"\x55\x8B\xEC\x66\xA1"
DO_VISION_SIGNATURE = b"\x55\x8B\xEC\x51\x8B\x15"
DO_UNIT_SPELL_SIGNATURE = b"\x55\x8B\xEC\xF6\x05"
ACTION_VISION_SIGNATURE = b"\x55\x8B\xEC\x51\x53\x8B\x5D\x08\x0F\xB6\x43\x2E"
ACTION_BLIZZARD_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x08\x0F\xB6\x46\x2E\x8A\x4E\x26"
ACTION_FIREBALL_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x08\x6A\x02\x56\x0F\xB6\x46\x2E"
ACTION_SLOW_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x08\x8B\x86\x88\x00\x00\x00\x85\xC0\x74"
ACTION_FLAME_SHIELD_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x08\x8B\x86\x88\x00\x00\x00\x85\xC0\x74\x5D"
ACTION_INVIS_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x08\x8B\x86\x88\x00\x00\x00\x85\xC0\x74\x1D"
ACTION_POLYMORPH_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x08\x8B\x86\x88\x00\x00\x00\x85\xC0\x74\x1D"
ACTION_EYE_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x08\x6A\x02\x56\x0F\xB6\x46\x2E"
ACTION_HEAL_SIGNATURE = b"\x55\x8B\xEC\x51\x56\x8B\x75\x08\x8B\x86\x88\x00\x00\x00\x85\xC0"
ACTION_EXORCISM_SIGNATURE = b"\x55\x8B\xEC\x83\xEC\x18\x53\x56\x8B\x75\x08\x57\x6A\x02\x56"
ACTION_BLOODLUST_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x08\x8B\x86\x88\x00\x00\x00\x85\xC0\x74\x1D"
ACTION_DRAINLIFE_SIGNATURE = b"\x55\x8B\xEC\x81\xEC\xBC\x01\x00\x00\xA1"
ACTION_RAISEDEAD_SIGNATURE = b"\x55\x8B\xEC\x83\xEC\x10\x53\x56\x57\x8B\x7D\x08\x6A\x02\x57\xE8"
ACTION_WHIRLWIND_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x08\x6A\x02\x56\x0F\xB6\x46\x2E"
ACTION_ROT_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x08\x0F\xB6\x46\x2E\x8A\x4E\x26"
ACTION_RUNES_SIGNATURE = b"\x55\x8B\xEC\x83\xEC\x08\x53\x8B\x5D\x08\x0F\xB6\x43\x2E"
ACTION_HASTE_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x08\x8B\x86\x88\x00\x00\x00\x85\xC0\x74\x1D"
ACTION_ARMOR_SIGNATURE = b"\x55\x8B\xEC\x56\x8B\x75\x08\x8B\x86\x88\x00\x00\x00\x85\xC0\x74\x1D"
COUNT_MAN_SIGNATURE = b"\x55\x8B\xEC\x66\x83\x7D\x0C\x00\x7F\x0F\x8B\x45\x08\x0F\xB6\x40\x2C\x66\xFF\x04\x45"
COUNT_BUILDING_SIGNATURE = b"\x55\x8B\xEC\x8B\x55\x08\x66\x8B\x45\x0C\x0F\xB6\x4A\x2C\x66\x01\x04\x4D"
GAME_SET_MODE_SIGNATURE = b"\x55\x8B\xEC\x66\x8B\x0D"
GROW_STRUCTURE_SIGNATURE = b"\x55\x8B\xEC\x83\xEC\x08\x53\x8B\x5D\x08\xF6\x43\x1E\x07"
REMOVE_LAND_UNIT_TYPES = frozenset((*range(0, 26), 44, *range(46, 54), 55, 56, 57))
FIRST_BUILDING_TYPE = 58
LAST_BUILDING_TYPE = 104
# Normal land structures that Warcraft can safely create during a running match.
# Oil platforms require an existing oil patch; mines, oil patches, start markers,
# circles, portals, and runestones use scenario/special-case initialization.
CREATE_BUILDING_TYPES = frozenset((*range(58, 86), *range(88, 92), *range(96, 100), 103, 104))
SND_SPELL_HOLYVISION = 7
VISION_OFFSETS = ((0, 0), (0, -8), (0, 8), (6, 4), (6, -4), (-6, 4), (-6, -4))
SPELL_SOUND_NAMES = (
    "Bloodlust", "Death and Decay", "Death Coil", "Exorcism",
    "Flame Shield", "Haste", "Healing", "Holy Vision", "Blizzard",
    "Invisibility", "Eye of Kilrogg", "Polymorph", "Slow", "Thunder",
    "Touch of Darkness", "Unholy Armor", "Whirlwind",
)
SPELL_VISION = 38
SPELL_BLIZZARD = 47
SPELL_HEAL = 39
SPELL_EXORCISM = 41
SPELL_BLOODLUST = 49
SPELL_RAISEDEAD = 50
SPELL_DRAINLIFE = 51
SPELL_WHIRLWIND = 52
SPELL_HASTE = 53
SPELL_ARMOR = 54
SPELL_RUNES = 55
SPELL_ROT = 56
SPELL_FIREBALL = 43
SPELL_SLOW = 44
SPELL_FLAME_SHIELD = 42
SPELL_INVIS = 45
SPELL_POLYMORPH = 46
SPELL_EYE = 48
BLIZZARD_CASTER_TYPE = 10
VISION_CASTER_TYPE = 12
FIREBALL_CASTER_TYPE = 10
SLOW_CASTER_TYPE = 10
FLAME_SHIELD_CASTER_TYPE = 10
INVIS_CASTER_TYPE = 10
POLYMORPH_CASTER_TYPE = 10
POLYMORPH_SHEEP_TYPE = 57
EYE_CASTER_TYPE = 13
EYE_UNIT_TYPE = 45
UNIT_MTX_SIZE_TABLE_RVA = 0x517AD0
UF_EVEN_ALIGN = 0x0002
# Native-verified gbUnitClassTbl/gUnitFlagsTbl contract: every CLASS_AIR,
# CLASS_WATER, and CLASS_WATER_CANDOCK mobile unit carries UF_EVEN_ALIGN.
# Warcraft's traversal advances those units in two-matrix steps. Starting one
# on an odd tile makes line_to_target mathematically unable to reach its forced
# even target and it eventually walks beyond gfpSquareMap. Keep this list tied
# to the live 0-57 unit IDs used by this editor.
EVEN_ALIGNED_MOBILE_TYPES = frozenset({
    22,                         # Kurdran
    26, 27, 28, 29, 30, 31, 32, 33,  # tankers/transports/destroyers/battleships
    35,                         # Deathwing
    36, 37, 38, 39,             # submarines/turtles
    40, 41, 42, 43,             # flying machine/zeppelin/gryphon/dragon
    45,                         # Eye of Kilrogg
    56,                         # Demon
})
NEUTRAL_OWNER = 15
HEAL_CASTER_TYPE = 12
HEAL_MAX = 40
IS_FLYER = 0x00000002
IS_FLESHY = 0x08000000
IS_UNDEAD = 0x00008000
EXORCISM_CASTER_TYPE = 12
EXORCISM_RADIUS = 3
BLOODLUST_CASTER_TYPE = 13
BLOODLUST_TIME = 750
RAISEDEAD_CASTER_TYPE = 11
RAISEDEAD_RADIUS = 6
DEAD_GUY_TYPE = 105
SKELETON_TYPE = 55
DRAINLIFE_CASTER_TYPE = 11
DRAINLIFE_RADIUS = 2
DRAINLIFE_MAX = 50
WHIRLWIND_CASTER_TYPE = 11
BT_TYPHOON = 12
ROT_CASTER_TYPE = 11
BT_ROT = 6
ROT_TIMES = 10
RUNES_CASTER_TYPE = 13
HASTE_CASTER_TYPE = 11
HASTE_TIME = 1000
ARMOR_CASTER_TYPE = 11
ARMOR_TIME = 500

# Warcraft's hero casters use the same native spell action handlers as their
# normal class.  Earlier builds accepted only the base four unit IDs, causing
# valid selections such as Turalyon Healing to be rejected before Warcraft was
# called.
MAGE_CASTER_TYPES = frozenset((10, 24))              # Mage, Khadgar
DEATH_KNIGHT_CASTER_TYPES = frozenset((11, 21, 51))  # Death Knight, Teron, Gul'dan
PALADIN_CASTER_TYPES = frozenset((12, 44, 52))       # Paladin, Turalyon, Uther
OGRE_MAGE_CASTER_TYPES = frozenset((13, 23, 49))     # Ogre-Mage, Dentarg, Cho'gall

BLIZZARD_TIMES = 10
SLOW_TIME = -1000
FLAME_SHIELD_TIME = 500
INVIS_TIME = 2000

UNIT_NAMES = [
    'Footman', 'Grunt', 'Peasant', 'Peon',
    'Ballista', 'Catapult', 'Knight', 'Ogre',
    'Archer', 'Axethrower', 'Mage', 'Death Knight',
    'Paladin', 'Ogre-Mage', 'Dwarves', 'Goblin Sappers',
    'Attack Peasant', 'Attack Peon', 'Ranger', 'Berserker',
    'Alleria', 'Teron Gorefiend', "Kurdan and Sky'ree", 'Dentarg',
    'Khadgar', 'Grom Hellscream', 'Human Tanker', 'Orc Tanker',
    'Human Transport', 'Orc Transport', 'Elven Destroyer', 'Troll Destroyer',
    'Battleship', 'Juggernaught', 'Nothing (Unused A100)', 'Deathwing',
    'Nothing (Unused H Minelayer)', 'Nothing (Unused O Minelayer)', 'Gnomish Submarine', 'Giant Turtle',
    'Gnomish Flying Machine', 'Goblin Zeppelin', 'Gryphon Rider', 'Dragon',
    'Turalyon', 'Eye of Kilrogg', 'Danath', 'Korgath Bladefist',
    'Nothing (Unused 0x30)', "Cho'gall", 'Lothar', "Gul'dan",
    'Uther Lightbringer', "Zul'jin", 'Nothing (Unused 0x36)', 'Skeleton',
    'Daemon', 'Critter', 'Human Farm', 'Orc Farm',
    'Human Barracks', 'Orc Barracks', 'Church', 'Altar of Storms',
    'Scout Tower', 'Watch Tower', 'Stables', 'Ogre Mound',
    'Gnomish Inventor', 'Goblin Alchemist', 'Gryphon Aviary', 'Dragon Roost',
    'Human Shipyard', 'Orc Shipyard', 'Town Hall', 'Great Hall',
    'Elven Lumber Mill', 'Troll Lumber Mill', 'Human Foundry', 'Orc Foundry',
    'Mage Tower', 'Temple of the Damned', 'Human Blacksmith', 'Orc Blacksmith',
    'Human Refinery', 'Orc Refinery', 'Human Oil Platform', 'Orc Oil Platform',
    'Keep', 'Stronghold', 'Castle', 'Fortress',
    'Gold Mine', 'Oil Patch', 'Human Start', 'Orc Start',
    'Guard Tower', 'Orc Guard Tower', 'Cannon Tower', 'Orc Cannon Tower',
    'Circle of Power', 'Dark Portal', 'Runestone', 'Human Wall',
    'Orc Wall', 'Dead Body', 'Destroyed 1x1', 'Destroyed 2x2',
    'Destroyed 3x3', 'Destroyed 4x4',
]
MISSILE_NAMES = [
    "Lightning", "Hammer", "Fireball", "Fire Shield", "Flame Spin", "Blizzard",
    "Rot", "Human Battleship Shot", "Exorcism", "Heal", "Dark Attack", "Rune",
    "Typhoon", "Stone", "Bolt", "Arrow", "Axe", "Human Torpedo", "Orc Torpedo",
    "Light Fire", "Heavy Fire", "Catapult Impact", "Sparkle", "Fire Explosion",
    "Cannon", "Cannon Muzzle Fire", "Cannon Explosion", "Demon Fire", "Black X",
    "None",
]


@dataclass
class Unit:
    address: int
    x: int
    y: int
    action: int
    health: int
    unit_type: int
    owner: int
    color: int
    mana: int
    next_action: int
    target_x: int
    target_y: int
    target_unit: int
    sflags: int
    token: int
    warp: int
    armor: int
    rage: int
    fire: int
    invis: int


@dataclass
class Missile:
    address: int
    x: int
    y: int
    target_x: int
    target_y: int
    target_unit: int
    owner_unit: int
    missile_type: int
    flags: int
    action: int
    damage: int


@dataclass
class VisionEffect:
    owner: int
    regions: tuple[tuple[int, int], ...]
    expires: float



# Universal compatibility relocation map.  These are only applied after
# compatibility.py proves a coherent relocation using independent native-verified
# anchors.  The baseline values stay immutable so detach/reattach never stacks a
# delta on top of a previous session.
_BASELINE_DATA_RVAS = {
    "CHAT_FILTER_RVA": 0x00518BE9,
    "UNIT_ARRAY_RVA": 0x0051C704,
    "MAX_UNITS_RVA": 0x0051BFB8,
    "BULLET_ARRAY_RVA": 0x0051C700,
    "MAX_BULLETS_RVA": 0x0051BFBC,
    "UNIT_BULLET_TABLE_RVA": 0x005182A0,
    "UNIT_MAP_RVA": 0x0051AD6C,
    "AIR_UNIT_MAP_RVA": 0x0051AD70,
    "RUNE_X_RVA": 0x00518D14,
    "RUNE_Y_RVA": 0x00518D48,
    "RUNE_DELAY_RVA": 0x00518D80,
    "MTXM_GLOBAL_RVA": 0x00560DF4,
    "MAP_DIMENSION_RVA": 0x00518D10,
    "LOCAL_PLAYER_RVA": 0x00518CCD,
    "ACTION_TYPE_RVA": 0x005348BC,
    "UNIT_SCORE_RVA": 0x005184A0,
    "GAME_MODE_RVA": 0x0051C184,
    "BUILDINGS_IN_PROGRESS_RVA": 0x00519410,
    "UNIT_HP_TABLE_RVA": 0x005177C0,
    "UNIT_IS_TABLE_RVA": 0x005185F0,
    "CHEAT_BITS_RVA": 0x0051B270,
    "ENEMY_TABLE_RVA": 0x00519578,
    "SHARED_VISION_RVA": 0x00519678,
    "ALLIED_VICTORY_RVA": 0x00518D13,
    "OWNER_TYPE_TABLE_RVA": 0x00518CAC,
    "MULTIPLAYER_MODE_RVA": 0x00522F5B,
}
_BASELINE_RESOURCE_RVAS = {"Gold": 0x00519128, "Lumber": 0x005190E8, "Oil": 0x00519168}
_BASELINE_STAT_RVAS = {
    "Deaths Men": 0x00519438,
    "Deaths Buildings": 0x00519458,
    "Kills Men": 0x00519478,
    "Kills Buildings": 0x00519498,
    "Score": 0x005193A8,
}
_BASELINE_UNIT_GLOBAL_RVAS = (0x00534A68, 0x0053484C, 0x00534B8C)
_BASELINE_RDATA_RVAS = {
    "VISION_MASK_TABLE_RVA": 0x004C4EC8,
    "UNIT_ACTION_FUNCTION_TABLE_RVA": 0x004C1498,
    "UNIT_ACTION_USER_DISPATCH_TABLE_RVA": 0x004C13A0,
    "UNIT_ACTION_DISPATCH_TABLE_RVA": 0x004C1590,
    "SPELL_AREA_EFFECT_TABLE_RVA": 0x004C1804,
    "CASTING_COST_TABLE_RVA": 0x004C5EB8,
}
_BASELINE_CODE_RVAS = {
    "SIMULATION_DISPATCH_HOOK_RVA": 0x000EEA80,
    "SIMULATION_DISPATCH_RETURN_RVA": 0x000EEA85,
    "PACKET_SEND_STRING_RVA": 0x000F1540,
    "NET_SEND_MSG_ALL_RVA": 0x00117B30,
    "MAP_MSG_RVA": 0x000D3160,
    "MAP_MESSAGE_DRAW_RVA": 0x000D35E0,
    "DIPLOMACY_UPDATE_RVA": 0x000D6740,
    "VISION_REFRESH_RVA": 0x000F11C0,
    "UNITDRAW_SET_SELECTION_COLORS_RVA": 0x000F0D10,
}
_BASELINE_SHARED_VISION_OFFLINE_PATCHES = tuple(SHARED_VISION_OFFLINE_PATCHES)
_BASELINE_SHARED_VISION_GATE_SCAN_WINDOWS = tuple(SHARED_VISION_GATE_SCAN_WINDOWS)

@dataclass
class _InFlightDispatch:
    owner: tuple[int, ...] | None
    ordinal: int
    signature: tuple
    status_address: int
    result_address: int
    started_at: float
    call_count: int
    last_notice: float
    heartbeat_at_queue: int


class LiveAdapter(CardEngineMixin):
    """Read-first adapter for validated Warcraft II Remastered x86 builds.

    It validates the loaded PE before following any candidate global. Mutation is
    restricted to actions whose memory semantics have already been observed. Game
    Unsupported specialized allocator/pathing cases remain fail-closed.
    """

    @staticmethod
    def probe_process_state() -> dict[str, Any]:
        """Lightweight AUTO-mode probe that never installs hooks.

        The watcher uses only the native-verified game-mode and map-dimension globals
        from the currently supported Remastered layout. Full compatibility validation
        still happens in :meth:`attach`; a false/unknown probe therefore cannot make
        the runtime write to an unsupported build.
        """
        pm = None
        result: dict[str, Any] = {
            "present": False, "pid": None, "base": 0, "mode": None,
            "dimension": None, "running": False,
        }
        try:
            import pymem
            import pymem.process
            pm = pymem.Pymem("Warcraft II.exe")
            module = pymem.process.module_from_name(pm.process_handle, "Warcraft II.exe")
            if not module:
                return result
            base = int(module.lpBaseOfDll)
            mode = int(pm.read_ushort(base + GAME_MODE_RVA))
            dimension = int(pm.read_ushort(base + MAP_DIMENSION_RVA))
            pid = int(getattr(pm, "process_id", 0) or 0) or None
            result.update(
                present=True, pid=pid, base=base, mode=mode, dimension=dimension,
                running=(mode == GAME_RUN and dimension in (32, 64, 96, 128)),
            )
            return result
        except Exception as exc:
            # Process-not-found and process-transition races are normal for an
            # always-on watcher. Keep the detail for diagnostics without surfacing
            # a modal error every polling cycle.
            result["error"] = str(exc)
            return result
        finally:
            if pm is not None:
                try:
                    pm.close_process()
                except Exception:
                    pass

    def detect_map_names(self, expected: list[str] | tuple[str, ...] = ()) -> list[str]:
        """Return best-effort live ``.pud`` filename candidates.

        Warcraft keeps map strings in process memory while a scenario is active, but
        the exact modern string owner is not a source-stable ABI. We therefore use a
        read-only scan: first exact filenames supplied by open sidecars, then a
        conservative printable ``*.pud`` fallback. No game memory is modified.
        """
        if not self.pm:
            return []
        try:
            import pymem.pattern
        except Exception:
            return []

        found: list[str] = []
        seen: set[str] = set()

        def add(name: str) -> None:
            name = Path(str(name)).name.strip().strip('\x00')
            if not name or not name.casefold().endswith('.pud'):
                return
            key = name.casefold()
            if key not in seen:
                seen.add(key)
                found.append(name)

        def scan(pattern: bytes, multiple: bool = True):
            try:
                return pymem.pattern.pattern_scan_all(
                    self.pm.process_handle, pattern, return_multiple=multiple
                )
            except TypeError:
                try:
                    return pymem.pattern.pattern_scan_all(self.pm.process_handle, pattern, multiple)
                except Exception:
                    return [] if multiple else None
            except Exception:
                return [] if multiple else None

        # Exact candidate matching is fast. Scan every hit and rank heap/dynamic
        # occurrences above strings inside Warcraft's module image; among dynamic
        # hits, newer heap allocations commonly have the higher address. This is
        # still intentionally best-effort, but avoids choosing a static/stale menu
        # string merely because it appeared first in the address space.
        exact_hits: list[tuple[int, str]] = []
        for raw in expected:
            base_name = Path(str(raw).replace("\\", "/")).name
            if not base_name:
                continue
            if not base_name.casefold().endswith('.pud'):
                base_name += '.pud'
            for encoded in (base_name.encode('utf-8', 'ignore'), base_name.encode('utf-16le', 'ignore')):
                if not encoded:
                    continue
                hits = scan(re.escape(encoded), multiple=True)
                if isinstance(hits, int):
                    hits = [hits]
                for hit in hits or []:
                    address = int(hit)
                    dynamic_bonus = 1 if not (self.base <= address < self.base + max(1, self.image_size)) else 0
                    exact_hits.append(((dynamic_bonus << 63) | address, base_name))
        if exact_hits:
            for _, name in sorted(exact_hits, reverse=True):
                add(name)
            return found

        # Fallback: printable ASCII path/basename ending in .pud. The regex is
        # deliberately bounded so a corrupt page cannot turn into a giant string.
        pattern = rb"(?i)(?:[A-Z]:\\)?[ -~]{1,180}\.pud\x00"
        hits = scan(pattern, multiple=True)
        if isinstance(hits, int):
            hits = [hits]
        for address in sorted((int(item) for item in (hits or [])), reverse=True)[:64]:
            try:
                raw = self.pm.read_bytes(int(address), 192)
                text = raw.split(b'\x00', 1)[0].decode('utf-8', 'ignore').strip()
                # pattern_scan_all returns the start of the full printable match.
                match = re.search(r"(?i)([^\\/:*?\"<>|]+\.pud)$", text)
                if match:
                    add(match.group(1))
            except Exception:
                continue
        return found
    def __init__(self, scenario=None, logger=None):
        self.scenario = scenario
        self.log = logger or (lambda text: None)
        self.pm = None
        self.base = 0
        self.image_size = 0
        self.build_info = None
        self.compatibility_mode = "Unattached"
        self.compatibility_report_path = ""
        self.build_timestamp = 0
        self.unit_global = 0
        self.unit_pool = 0
        self.unit_globals: list[int] = []
        self.auto_scanned = False
        self.map_width = 128
        self.map_height = 128
        self.started = time.monotonic()
        self.switches: dict[str, str] = {}
        self.counters: dict[str, int] = {}
        self.game_state = "Playing"
        self._region_cache: dict[int, bool] = {}
        self._snapshot: dict[tuple[int, int], Unit] = {}
        self._previous_snapshot: dict[tuple[int, int], Unit] = {}
        self.created_units: list[Unit] = []
        self.died_units: list[Unit] = []
        self.removed_units: list[Unit] = []
        self._pending_removed_keys: set[tuple[int, int]] = set()
        self._active_visions: list[VisionEffect] = []
        self.damage_unit_address = 0
        self.damage_callees: dict[str, int] = {}
        self.unit_create_address = 0
        self.building_create_path: dict[str, int] = {}
        self.building_completion_path: dict[str, int] = {}
        self.capture_unit_address = 0
        self.unit_free_address = 0
        self.remove_callees: dict[str, int] = {}
        self.move_callees: dict[str, int] = {}
        self.order_callees: dict[str, int] = {}
        self.bullet_path: dict[str, int] = {}
        self.spell_path: dict[str, int] = {}
        self.message_path: dict[str, int] = {}
        self.diplomacy_path: dict[str, int] = {}
        self._kill_snapshot: dict[tuple[int, str], int] = {}
        self.kill_deltas: dict[tuple[int, str], int] = {}
        self._action_value_cache: dict[tuple[int, ...], dict[str, Any]] = {}
        self.bullet_pool = 0
        self.max_bullets = 0
        self.game_mode_path: dict[str, int] = {}
        self.dispatcher_memory = 0
        self.dispatcher_hook_address = 0
        self.dispatcher_command_address = 0
        self.dispatcher_status_address = 0
        self.dispatcher_result_address = 0
        self.dispatcher_heartbeat_address = 0
        self.dispatcher_magic_address = 0
        self.dispatcher_vision_masks_address = 0
        self.dispatcher_vision_active_address = 0
        self.dispatcher_vision_mode_address = 0
        self.diplomacy_guard_code_address = 0
        self.diplomacy_guard_hook_address = 0
        self.diplomacy_guard_original_bytes = b""
        self.dispatcher_chat_packet_address = 0
        self.dispatcher_chat_text_address = 0
        self.dispatcher_original_bytes = b""
        self.dispatcher_installed = False
        self._last_dispatch = 0.0
        self._dispatch_lock = threading.RLock()
        self._dispatch_inflight: _InFlightDispatch | None = None
        self._trigger_generation = 0
        self._action_context: tuple[int, ...] | None = None
        self._action_dispatch_cursor = 0
        self._dispatch_journal: dict[tuple[int, ...], list[tuple[tuple, int]]] = {}
        self._issued_orders: dict[tuple[int, int], tuple[Any, ...]] = {}
        # Generic destination-only Attack routes. Empty owner slots can walk a
        # target-less route but have no persistent controller to acquire enemies;
        # runtime maintenance supplies native target pointers only when an enemy
        # enters the encounter radius, then resumes the saved X/Y route.
        self._attack_routes: dict[tuple[int, int], tuple[int, int]] = {}
        self._shared_vision_patch_originals: dict[int, bytes] = {}
        self._shared_vision_gate_operand_originals: dict[int, bytes] = {}
        self._diplomacy_mode_original: int | None = None
        self._diplomacy_mode_forced = False
        self._shared_vision_sources: set[int] = set()
        # Authoritative masks requested by the trigger. Warcraft can rebuild the
        # live gSharedVision bytes during normal simulation, so runtime refreshes
        # must restore these desired bytes instead of treating a reset as a user
        # request to disable vision.
        self._shared_vision_masks: list[int] | None = None
        self._next_shared_vision_refresh = 0.0
        self._last_diplomacy_signature: tuple[Any, ...] | None = None
        self._relation_self_codes: list[int] = []
        # Optional TD-specific Raise Dead -> tower builder. It detours the validated
        # native action body and restores it on stop. Native spell pursuit/range stays intact.
        self._td_builder_enabled = False
        self._td_builder_owner = 0
        self._td_builder_caster_type = RAISEDEAD_CASTER_TYPE
        self._td_builder_tower_type = 97
        self._td_builder_mana_cost = 50
        self._td_builder_location_prefix = "Tower Pad "
        self._td_builder_dispatch_entry = 0
        self._td_builder_dispatch_original = 0
        self._td_builder_range_address = 0
        self._td_builder_range_original = 0
        self._td_builder_code_address = 0
        self._td_builder_action_entry = 0
        self._td_builder_action_original = b""
        self._td_builder_action_patch = b""
        self._td_builder_trampoline_address = 0
        # 1.28.11 tower foundations are completed incrementally through Warcraft's
        # native grow_structure routine instead of being force-finished in the
        # Raise Dead cast cycle. Keys are live TUnit addresses.
        self._td_pending_towers: dict[int, dict[str, int | float]] = {}
        # A grow_structure call can legitimately remain queued across trigger cycles.
        # Preserve the exact owner-less maintenance signature until it is consumed;
        # otherwise a cancelled/freed tower can make the next tower submit a different
        # signature and permanently wedge the shared simulation dispatcher.
        self._td_growth_retry_ops: list[tuple] | None = None
        self._td_growth_retry_address = 0
        self._init_massive_features()

    def _apply_universal_relocation(self, data_delta: int, code_delta: int) -> None:
        """Relocate baseline RVAs only after independent anchor validation.

        Most Remastered maintenance builds preserve the source data block and
        text layout.  When a build shifts those sections as a whole, universal
        mode can still operate by relocating the baseline addresses.  Tables in
        the older .rdata block are *not* guessed; their existing validators must
        still pass before the related feature is enabled.
        """
        g = globals()
        for name, baseline in _BASELINE_DATA_RVAS.items():
            g[name] = int(baseline + data_delta)
        g["RESOURCE_RVAS"] = {k: int(v + data_delta) for k, v in _BASELINE_RESOURCE_RVAS.items()}
        g["STAT_RVAS"] = {k: int(v + data_delta) for k, v in _BASELINE_STAT_RVAS.items()}
        g["UNIT_GLOBAL_RVAS"] = tuple(int(v + data_delta) for v in _BASELINE_UNIT_GLOBAL_RVAS)
        for name, baseline in _BASELINE_RDATA_RVAS.items():
            g[name] = int(baseline + code_delta)
        for name, baseline in _BASELINE_CODE_RVAS.items():
            g[name] = int(baseline + code_delta)
        g["SHARED_VISION_OFFLINE_PATCHES"] = tuple(
            (int(rva + code_delta), original, patched)
            for rva, original, patched in _BASELINE_SHARED_VISION_OFFLINE_PATCHES
        )
        g["SHARED_VISION_GATE_SCAN_WINDOWS"] = tuple(
            (int(start + code_delta), int(end + code_delta))
            for start, end in _BASELINE_SHARED_VISION_GATE_SCAN_WINDOWS
        )

        # Mixins imported these table constants at module scope.  Keep them in
        # lockstep with the validated data relocation rather than leaving one
        # subsystem on the old build's addresses.
        import source_features as sf
        import source_features_128 as sf128
        import ultimate_features as ult
        import mission_features_132 as mf132
        import massive_features as massive
        import campaign_features as camp
        for module, mapping in (
            (sf128, {
                "UNIT_HP_TABLE_RVA": 0x005177C0,
                "UNIT_ARMOR_TABLE_RVA": 0x00517F90,
                "UNIT_PIERCE_TABLE_RVA": 0x005180E0,
                "UNIT_STRENGTH_TABLE_RVA": 0x00518150,
                "UNIT_BULLET_TABLE_RVA": 0x005182A0,
                "UNIT_IS_TABLE_RVA": 0x005185F0,
                "RUNE_X_RVA": 0x00518D14,
                "RUNE_Y_RVA": 0x00518D48,
                "RUNE_DELAY_RVA": 0x00518D80,
            }),
            (ult, {
                "UNIT_IS_TABLE_RVA": 0x005185F0,
                "UNIT_CLASS_TABLE_RVA": 0x00518310,
            }),
            (mf132, {
                "UNIT_GOLD_COST_RVA_2818": 0x00517980,
                "UNIT_LUMBER_COST_RVA_2818": 0x005179F0,
                "UNIT_OIL_COST_RVA_2818": 0x00517A60,
            }),
            (massive, {"UNIT_HP_TABLE_RVA": 0x005177C0}),
        ):
            for name, baseline in mapping.items():
                setattr(module, name, int(baseline + data_delta))
        # Constants imported by value need their consumer module updated too.
        ult.UNIT_HP_TABLE_RVA = int(0x005177C0 + data_delta)
        sf128.CASTING_COST_TABLE_RVA = int(0x004C5EB8 + code_delta)
        camp.CampaignFeatureMixin.CAMERA_X_RVA = int(0x0051AD80 + data_delta)
        camp.CampaignFeatureMixin.CAMERA_Y_RVA = int(0x0051AD84 + data_delta)

        # Source-native callback dictionaries use fixed RVAs plus exact byte
        # prefixes. Relocate the candidate RVAs, but keep the byte check; if one
        # function moved independently the feature still fails closed.
        if not hasattr(sf, "_UNIVERSAL_BASELINE_SOURCE_NATIVE_SPECS"):
            sf._UNIVERSAL_BASELINE_SOURCE_NATIVE_SPECS = dict(sf.SOURCE_NATIVE_SPECS)
        sf.SOURCE_NATIVE_SPECS = {
            name: (int(rva + code_delta), prefix)
            for name, (rva, prefix) in sf._UNIVERSAL_BASELINE_SOURCE_NATIVE_SPECS.items()
        }
        if not hasattr(sf128, "_UNIVERSAL_BASELINE_SOURCE128_NATIVE_SPECS"):
            sf128._UNIVERSAL_BASELINE_SOURCE128_NATIVE_SPECS = dict(sf128.SOURCE128_NATIVE_SPECS)
        sf128.SOURCE128_NATIVE_SPECS = {
            name: (int(rva + code_delta), prefix)
            for name, (rva, prefix) in sf128._UNIVERSAL_BASELINE_SOURCE128_NATIVE_SPECS.items()
        }

    def attach(self) -> None:
        try:
            import pymem
            import pymem.process
        except ImportError as exc:
            exe = sys.executable or "python"
            raise RuntimeError(
                f"Pymem import failed in the Python interpreter running Trigger Studio: {exe}. "
                f"Install it into THIS interpreter with: \"{exe}\" -m pip install pymem. "
                f"Original import error: {exc}"
            ) from exc
        self.pm = pymem.Pymem("Warcraft II.exe")
        module = pymem.process.module_from_name(self.pm.process_handle, "Warcraft II.exe")
        if not module:
            raise RuntimeError("Warcraft II.exe module was not found")
        self.base = int(module.lpBaseOfDll)
        self._validate_loaded_pe()
        self._find_map_size()
        self._validate_resource_layout()
        initial_resources = self._validate_resource_tables()
        self.damage_unit_address = self._resolve_damage_unit()
        self.damage_callees = self._resolve_damage_callees()
        self._validate_statistics_layout()
        initial_statistics = self._read_player_statistics(0)
        self.game_mode_path = self._resolve_game_mode_path()
        initial_game_mode = self._read_game_mode()
        if initial_game_mode != GAME_RUN:
            raise RuntimeError(
                f"Warcraft game mode is {initial_game_mode}, expected running mode {GAME_RUN}; "
                "start or load a match before attaching"
            )
        self.unit_create_address = self._resolve_unit_create()
        self.building_create_path = self._validate_building_create_path()
        self.building_completion_path = self._resolve_building_completion_path()
        self.capture_unit_address = self._resolve_capture_unit()
        self.unit_free_address = self._resolve_unit_free()
        self.remove_callees = self._resolve_remove_callees()
        self.move_callees = self._resolve_move_callees()
        self.order_callees = self._resolve_order_callees()
        self.source_native_paths = self._resolve_source_native_paths()
        self.diplomacy_path = self._resolve_diplomacy_path()
        # The validated 1.0.2.2505/1.0.2.2818 builds store 1 (Allied) on every self-cell.
        # Keep the observed diagonal for diagnostics, but all emitted matrices use
        # the canonical Allied value so a stale 1.23.29 self=0 row is repaired.
        self._relation_self_codes = [
            int(self.pm.read_uchar(self.diplomacy_path["relations"] + player * 16 + player))
            for player in range(8)
        ]
        if any(not 0 <= value <= 3 for value in self._relation_self_codes):
            raise RuntimeError("Relation table contains a value outside the validated 2-bit range")
        local_player_at_attach = int(self.pm.read_uchar(self.base + LOCAL_PLAYER_RVA))
        if not 0 <= local_player_at_attach < 8:
            raise RuntimeError(f"Invalid local player slot {local_player_at_attach}")
        self._remove_legacy_shared_vision_patches()
        self.bullet_path = self._resolve_bullet_path()
        self.spell_path = self._resolve_spell_path()
        self.message_path = self._resolve_message_path()
        self.unit_global = self.base + UNIT_ARRAY_RVA
        self.unit_pool = self._read_ptr(self.unit_global)
        self.max_units = self.pm.read_uint(self.base + MAX_UNITS_RVA)
        if not 1 <= self.max_units <= 4096:
            raise RuntimeError(f"Invalid MAX_UNITS value at RVA 0x{MAX_UNITS_RVA:X}: {self.max_units}")
        if not self._is_private_writable(self.unit_pool):
            raise RuntimeError(f"gpUnits points outside writable private memory: 0x{self.unit_pool:08X}")
        # Prove the full allocation is readable before accepting it.
        self.pm.read_bytes(self.unit_pool, self.max_units * UNIT_SIZE)
        self.unit_globals = [self.unit_global]
        self.bullet_pool = self._read_ptr(self.base + BULLET_ARRAY_RVA)
        self.max_bullets = self.pm.read_uint(self.base + MAX_BULLETS_RVA)
        if not 1 <= self.max_bullets <= 1024:
            raise RuntimeError(
                f"Invalid MAX_BULLETS value at RVA 0x{MAX_BULLETS_RVA:X}: {self.max_bullets}"
            )
        if not self._is_private_writable(self.bullet_pool):
            raise RuntimeError(f"gpBullets points outside writable private memory: 0x{self.bullet_pool:08X}")
        self.pm.read_bytes(self.bullet_pool, self.max_bullets * BULLET_SIZE)
        self._install_simulation_dispatcher()
        # WT30 uses the unit_run-entry fog compositor and must not leave any
        # previous split-mode operand redirection active.
        self._restore_shared_vision_offline_patch()
        self.started = time.monotonic()
        self.log(f"Attached PID {self.pm.process_id}, module base 0x{self.base:08X}")
        self.log(f"Native-verified gpUnits: 0x{self.unit_global:08X} -> 0x{self.unit_pool:08X}")
        self.log(f"Native-verified MAX_UNITS: {self.max_units}; allocation size: 0x{self.max_units * UNIT_SIZE:X}")
        self.log(f"Native-verified gpBullets: RVA 0x{BULLET_ARRAY_RVA:X} -> 0x{self.bullet_pool:08X}")
        self.log(
            f"Native-verified MAX_BULLETS: {self.max_bullets}; "
            f"record size: 0x{BULLET_SIZE:X}; allocation size: 0x{self.max_bullets * BULLET_SIZE:X}"
        )
        self.log(f"Live map bounds: {self.map_width} x {self.map_height}")
        self.log(
            "Native-verified resources: "
            + ", ".join(f"{name} RVA 0x{rva:X}" for name, rva in RESOURCE_RVAS.items())
        )
        self.log(
            "Live P1 resources: "
            + ", ".join(f"{name} {initial_resources[name]}" for name in RESOURCE_RVAS)
        )
        self.log(
            "Native-verified combat statistics: "
            + ", ".join(f"{name} RVA 0x{rva:X}" for name, rva in STAT_RVAS.items())
        )
        self.log(
            "Live P1 statistics: "
            f"Kills {initial_statistics['Kills Men']} men / "
            f"{initial_statistics['Kills Buildings']} buildings; "
            f"Deaths {initial_statistics['Deaths Men']} men / "
            f"{initial_statistics['Deaths Buildings']} buildings; "
            f"Score {initial_statistics['Score']}"
        )
        self.log(
            f"Native-verified game mode: RVA 0x{GAME_MODE_RVA:X}, "
            f"current {initial_game_mode} (Running)"
        )
        self.log(
            f"Resolved game mode path: get RVA 0x{self.game_mode_path['get'] - self.base:X}, "
            f"set RVA 0x{self.game_mode_path['set'] - self.base:X}"
        )
        self.log(f"Resolved damage_damage_unit: 0x{self.damage_unit_address:08X} (RVA 0x{self.damage_unit_address - self.base:X})")
        self.log(f"Resolved unit_create: 0x{self.unit_create_address:08X} (RVA 0x{self.unit_create_address - self.base:X})")
        self.log(
            "Validated source building range 58-104: SF_BUILD_FOUNDATION, "
            f"gwBldgInProgress RVA 0x{BUILDINGS_IN_PROGRESS_RVA:X}, "
            f"mtx_place_bldg RVA 0x{self.building_create_path['place_bldg'] - self.base:X}"
        )
        self.log(
            f"Resolved instant building completion: grow_structure RVA "
            f"0x{self.building_completion_path['grow_structure'] - self.base:X}, "
            f"steps-cost RVA 0x{self.building_completion_path['steps_cost'] - self.base:X}"
        )
        self.log(f"Resolved capture_unit: 0x{self.capture_unit_address:08X} (RVA 0x{self.capture_unit_address - self.base:X})")
        self.log(f"Resolved unit_free: 0x{self.unit_free_address:08X} (RVA 0x{self.unit_free_address - self.base:X})")
        self.log(
            "Resolved movement path: "
            f"placeable RVA 0x{self.move_callees['placeable'] - self.base:X}, "
            f"place RVA 0x{self.move_callees['place_man'] - self.base:X}, "
            f"unmask RVA 0x{self.move_callees['unmask_square'] - self.base:X}, "
            f"guard RVA 0x{self.move_callees['set_curr_action'] - self.base:X}"
        )
        self.log(
            "Resolved orders: "
            f"unit_set_target RVA 0x{self.order_callees['set_target'] - self.base:X}, "
            f"do_unit_move RVA 0x{self.order_callees['do_move'] - self.base:X}, "
            f"do_unit_attack RVA 0x{self.order_callees['do_attack'] - self.base:X}, "
            f"do_unit_patrol RVA 0x{self.order_callees['do_patrol'] - self.base:X}"
        )
        self.log(
            f"Resolved {len(self.source_native_paths)} source-native callbacks: "
            "orders, transport unload, production, and contextual sound; source-structure systems enabled"
        )
        self.log(
            "Resolved diplomacy path: "
            f"update RVA 0x{self.diplomacy_path['update'] - self.base:X}, "
            f"relations RVA 0x{ENEMY_TABLE_RVA:X}, "
            f"shared vision RVA 0x{SHARED_VISION_RVA:X}, "
            f"allied victory RVA 0x{ALLIED_VICTORY_RVA:X}, "
            f"unit-mask refresh RVA 0x{self.diplomacy_path['vision_refresh'] - self.base:X}; "
            f"relation enum 0=Enemy/1=Allied; observed self cells "
            f"[{', '.join(f'P{i + 1}={value}' for i, value in enumerate(self._relation_self_codes))}]; "
            f"gbMultiPlayer byte RVA 0x{self.diplomacy_path['multiplayer_gate'] - self.base:X}="
            f"{self.pm.read_uchar(self.diplomacy_path['multiplayer_gate'])}"
        )
        self.log(
            f"Resolved projectile path: action_do_attack RVA "
            f"0x{self.bullet_path['action_do_attack'] - self.base:X}, "
            f"bullet_create RVA 0x{self.bullet_path['bullet_create'] - self.base:X}, "
            f"bullet_create_xy RVA 0x{self.bullet_path['bullet_create_xy'] - self.base:X}"
        )
        self.log(
            f"Resolved unitless spell paths: place_a_rune RVA "
            f"0x{self.spell_path['place_rune'] - self.base:X}; "
            f"Holy Vision unmask RVA 0x{self.spell_path['vision_unmask'] - self.base:X}, "
            f"camera RVA 0x{self.spell_path['vision_set_pos'] - self.base:X}, "
            f"sound RVA 0x{self.spell_path['vision_sound'] - self.base:X}"
        )
        self.log(
            f"Resolved caster spell path: do_unit_spell RVA "
            f"0x{self.spell_path['do_unit_spell'] - self.base:X}, "
            f"Holy Vision action RVA "
            f"0x{self.spell_path['action_vision'] - self.base:X}; "
            f"native mana cost {self.spell_path['vision_cost']}; "
            f"Fireball action RVA 0x{self.spell_path['action_fireball'] - self.base:X}, "
            f"bullet_create_fireball RVA "
            f"0x{self.spell_path['bullet_create_fireball'] - self.base:X}; "
            f"native mana cost {self.spell_path['fireball_cost']}; "
            f"Slow action RVA 0x{self.spell_path['action_slow'] - self.base:X}; "
            f"native mana cost {self.spell_path['slow_cost']}; "
            f"Flame Shield action RVA "
            f"0x{self.spell_path['action_flame_shield'] - self.base:X}; "
            f"native mana cost {self.spell_path['flame_shield_cost']}; "
            f"Invisibility action RVA "
            f"0x{self.spell_path['action_invis'] - self.base:X}; "
            f"native mana cost {self.spell_path['invis_cost']}; "
            f"Polymorph action RVA "
            f"0x{self.spell_path['action_polymorph'] - self.base:X}; "
            f"native mana cost {self.spell_path['polymorph_cost']}; "
            f"Eye of Kilrogg action RVA "
            f"0x{self.spell_path['action_eye'] - self.base:X}; "
            f"native mana cost {self.spell_path['eye_cost']}; "
            f"Bloodlust action RVA "
            f"0x{self.spell_path['action_bloodlust'] - self.base:X}; "
            f"native mana cost {self.spell_path['bloodlust_cost']}; "
            f"Heal action RVA "
            f"0x{self.spell_path['action_heal'] - self.base:X}; "
            f"native mana cost {self.spell_path['heal_cost']} per HP; "
            f"Exorcism action RVA "
            f"0x{self.spell_path['action_exorcism'] - self.base:X}; "
            f"native mana cost {self.spell_path['exorcism_cost']} per damage; "
            f"Raise Dead action RVA "
            f"0x{self.spell_path['action_raisedead'] - self.base:X}; "
            f"native mana cost {self.spell_path['raisedead_cost']} per corpse; "
            f"Death Coil action RVA "
            f"0x{self.spell_path['action_drainlife'] - self.base:X}; "
            f"native mana cost {self.spell_path['drainlife_cost']}; "
            f"Whirlwind action RVA "
            f"0x{self.spell_path['action_whirlwind'] - self.base:X}, "
            f"bullet_create_typhoon RVA "
            f"0x{self.spell_path['bullet_create_typhoon'] - self.base:X}; "
            f"native mana cost {self.spell_path['whirlwind_cost']}; "
            f"Death and Decay action RVA "
            f"0x{self.spell_path['action_rot'] - self.base:X}, "
            f"bullet_create_rot RVA "
            f"0x{self.spell_path['bullet_create_rot'] - self.base:X}; "
            f"native mana cost {self.spell_path['rot_cost']} per wave; "
            f"Runes action RVA "
            f"0x{self.spell_path['action_runes'] - self.base:X}; "
            f"native mana cost {self.spell_path['runes_cost']}; "
            f"Haste action RVA "
            f"0x{self.spell_path['action_haste'] - self.base:X}; "
            f"native mana cost {self.spell_path['haste_cost']}; "
            f"Unholy Armor action RVA "
            f"0x{self.spell_path['action_armor'] - self.base:X}; "
            f"native mana cost {self.spell_path['armor_cost']}; "
            f"Blizzard action RVA 0x{self.spell_path['action_blizzard'] - self.base:X}, "
            f"bullet_create_blizzard RVA "
            f"0x{self.spell_path['bullet_create_blizzard'] - self.base:X}; "
            f"native mana cost {self.spell_path['blizzard_cost']}"
        )
        self.log(
            "Resolved native game-message path: "
            f"packet_send_string RVA 0x{self.message_path['packet_send_string'] - self.base:X}, "
            f"net_send_msg_all RVA 0x{self.message_path['net_send_msg_all'] - self.base:X}, "
            f"map_msg RVA 0x{self.message_path['map_msg'] - self.base:X}; "
            "Player Chat and Game Message use public PM_STRING/map_msg with unaffected-slot restoration; "
            "native per-slot colors 02 yellow, 03 white, 04 red, 05 gray, 06 game-yellow; "
            f"PM_STRING 0x{PM_STRING:02X}, {MAX_NATIVE_MESSAGE_BYTES}-byte text limit"
        )
        self.log(
            "Resolved native game-speed packet path: PM_SET_SPEED 0x27 through "
            "validated net_send_msg_all; seven levels Slowest through Fastest"
        )
        self.log(
            f"Simulation-tick dispatcher installed: hook RVA 0x{SIMULATION_DISPATCH_HOOK_RVA:X}, "
            f"mailbox 0x{self.dispatcher_memory:08X}"
        )
        self.log(
            f"Post-reset shared vision installed: unit_run hook RVA 0x{SIMULATION_DISPATCH_HOOK_RVA:X}, "
            f"diplomacy hook RVA 0x{DIPLOMACY_UPDATE_RVA:X}; WT30 local fog compositor; "
            "gbMultiPlayer and worker commands remain native offline"
        )
        self.log("Dispatcher mode: native actions run on Warcraft's simulation thread; no Win32 safe-point queue")
        initial = self.units()
        self._snapshot = {self._unit_key(u): u for u in initial}
        self._kill_snapshot = self._capture_kill_snapshot()
        self.kill_deltas = {}
        self.log(f"Live event baseline captured: {len(initial)} unit(s)")

    def close(self) -> None:
        self._active_visions.clear()
        if self.pm:
            try:
                self._td_stream_restore_all_type_overrides()
            except Exception as exc:
                self.log(f"TD stream table cleanup deferred: {exc}")
            try:
                self._disable_td_tower_builder(log_result=False)
            except Exception as exc:
                self.log(f"TD tower-builder cleanup deferred: {exc}")
            try:
                restore_objectives = getattr(self, "_restore_native_objectives_hook", None)
                if restore_objectives:
                    restore_objectives()
            except Exception as exc:
                self.log(f"Native objectives cleanup deferred: {exc}")
            try:
                if self.dispatcher_vision_mode_address:
                    self.pm.write_uchar(self.dispatcher_vision_mode_address, 0)
                self._restore_shared_vision_offline_patch()
                self._restore_diplomacy_mode_byte()
            except Exception as exc:
                self.log(f"Diplomacy/shared-vision compatibility cleanup deferred: {exc}")
            try:
                self._uninstall_simulation_dispatcher()
            except Exception as exc:
                # If Warcraft is executing the mailbox at this exact instant, the
                # allocation must remain alive. The process will reclaim it on exit.
                self.log(f"Simulation dispatcher cleanup deferred: {exc}")
            try:
                self.pm.close_process()
            except Exception:
                pass
        self.pm = None

    def _validate_loaded_pe(self) -> None:
        """Accept any x86 Remastered build that proves the source-layout anchors.

        Older releases hard-rejected every unknown PE timestamp.  Universal mode
        instead fingerprints the loaded image, scans source-correlated unit_run,
        damage and victory_update anchors, and proves one coherent code/data
        relocation before native writes are allowed.  Unknown layouts fail closed.
        """
        info = parse_loaded_pe(self.pm, self.base)
        self.image_size = int(info.image_size)
        self.build_timestamp = int(info.timestamp)
        info = scan_compatibility(self.pm, self.base, info)
        self.build_info = info
        self.compatibility_mode = info.mode
        self._apply_universal_relocation(info.data_delta, info.code_delta)
        try:
            report_path = Path(__file__).resolve().parent.parent / "compatibility_last.json"
            export_report(info, str(report_path))
            self.compatibility_report_path = str(report_path)
        except Exception:
            self.compatibility_report_path = ""
        self.log(
            f"Build accepted: {info.label}; timestamp 0x{info.timestamp:08X}, "
            f"image 0x{info.image_size:X}; mode={info.mode}; "
            f"data delta {info.data_delta:+#x}; code delta {info.code_delta:+#x}"
        )
        for note in info.notes:
            self.log(f"COMPAT: {note}")

    def _read_ptr(self, address: int) -> int:
        return self.pm.read_uint(address)

    def _resolve_damage_unit(self) -> int:
        """Resolve the installed build by code signature, never by timestamp alone."""
        image = self.pm.read_bytes(self.base, self.image_size)
        hits: list[int] = []
        start = 0
        while True:
            offset = image.find(DAMAGE_UNIT_SIGNATURE, start)
            if offset < 0:
                break
            # Confirm the function contains the source-matched HP compare/subtract
            # tail nearby: movzx eax,[esi+22], compare, then mov [esi+22],ax.
            body = image[offset:offset + 0xC0]
            if b"\x0F\xB7\x46\x22" in body and b"\x66\x89\x46\x22" in body:
                hits.append(offset)
            start = offset + 1
        if len(hits) != 1:
            raise RuntimeError(f"Damage routine signature validation found {len(hits)} candidates; action disabled")
        return self.base + hits[0]

    def _resolve_damage_callees(self) -> dict[str, int]:
        """Decode the five rel32 calls made by the validated damage function."""
        body = self.pm.read_bytes(self.damage_unit_address, 0xAC)
        offsets = {
            "set_attacker": 0x61,
            "score_kill": 0x89,
            "unit_kill": 0x8F,
            "target_valid": 0x95,
            "under_attack": 0xA7,
        }
        result: dict[str, int] = {}
        for name, offset in offsets.items():
            if body[offset] != 0xE8:
                raise RuntimeError(f"Damage routine {name} call validation failed at +0x{offset:X}")
            displacement = struct.unpack_from("<i", body, offset + 1)[0]
            result[name] = self.damage_unit_address + offset + 5 + displacement
        return result

    def _validate_statistics_layout(self) -> None:
        """Anchor kills, deaths, and score to their source-matched update code."""
        score_kill = self.damage_callees["score_kill"]
        body = self.pm.read_bytes(score_kill, 0x3F)
        if (
            body[0x17:0x1B] != b"\x66\xFF\x04\x4D"
            or body[0x21:0x25] != b"\x66\xFF\x04\x4D"
            or body[0x29:0x2D] != b"\x0F\xB6\x40\x27"
            or body[0x2D:0x31] != b"\x0F\xB7\x04\x45"
            or body[0x35:0x38] != b"\x01\x04\x8D"
        ):
            raise RuntimeError("score_kill_unit statistics signature validation failed")
        score_operands = {
            "Kills Men": struct.unpack_from("<I", body, 0x1B)[0],
            "Kills Buildings": struct.unpack_from("<I", body, 0x25)[0],
            "Unit Score": struct.unpack_from("<I", body, 0x31)[0],
            "Score": struct.unpack_from("<I", body, 0x38)[0],
        }
        score_expected = {
            "Kills Men": self.base + STAT_RVAS["Kills Men"],
            "Kills Buildings": self.base + STAT_RVAS["Kills Buildings"],
            "Unit Score": self.base + UNIT_SCORE_RVA,
            "Score": self.base + STAT_RVAS["Score"],
        }
        if score_operands != score_expected:
            raise RuntimeError(
                "score_kill_unit table addresses disagree: "
                + ", ".join(f"{name}=0x{address:08X}" for name, address in score_operands.items())
            )

        count_man = self._resolve_unique_signature(
            COUNT_MAN_SIGNATURE, "count_man", 0x28, (b"\x66\x83\x7D\x0C\x00\x7F",)
        )
        man_body = self.pm.read_bytes(count_man, 0x28)
        dead_men = struct.unpack_from("<I", man_body, 0x15)[0]
        if dead_men != self.base + STAT_RVAS["Deaths Men"]:
            raise RuntimeError(f"count_man death table disagrees: 0x{dead_men:08X}")

        count_building = self._resolve_unique_signature(
            COUNT_BUILDING_SIGNATURE,
            "count_bldg",
            0x2C,
            (b"\x66\x85\xC0\x7F\x0C\x0F\xB6\x42\x2C\x66\xFF\x04\x45",),
        )
        building_body = self.pm.read_bytes(count_building, 0x2C)
        if building_body[0x1F:0x23] != b"\x66\xFF\x04\x45":
            raise RuntimeError("count_bldg death increment validation failed")
        dead_buildings = struct.unpack_from("<I", building_body, 0x23)[0]
        if dead_buildings != self.base + STAT_RVAS["Deaths Buildings"]:
            raise RuntimeError(f"count_bldg death table disagrees: 0x{dead_buildings:08X}")

    @staticmethod
    def _stat_category(value: Any) -> str:
        aliases = {
            "men": "Men", "man": "Men", "units": "Men", "unit": "Men", "mobile": "Men",
            "buildings": "Buildings", "building": "Buildings", "structures": "Buildings",
            "structure": "Buildings", "all": "All", "any": "All", "total": "All",
        }
        category = aliases.get(str(value).strip().casefold())
        if not category:
            raise ValueError(f"Unknown combat-stat category: {value}; use Men, Buildings, or All")
        return category

    def _stat_owner(self, value: Any) -> int:
        owner = int(value)
        if not 0 <= owner <= 15:
            raise ValueError(f"Invalid statistics player: {owner}")
        return owner

    def _read_stat_table(self, owner: int, name: str) -> int:
        address = self.base + STAT_RVAS[name]
        if name == "Score":
            return self.pm.read_uint(address + owner * 4)
        return self.pm.read_ushort(address + owner * 2)

    def _read_player_statistics(self, owner: int) -> dict[str, int]:
        owner = self._stat_owner(owner)
        return {name: self._read_stat_table(owner, name) for name in STAT_RVAS}

    def _read_combat_stat(self, owner: int, kind: str, category: Any) -> int:
        owner = self._stat_owner(owner)
        category = self._stat_category(category)
        if category == "All":
            return (
                self._read_stat_table(owner, f"{kind} Men")
                + self._read_stat_table(owner, f"{kind} Buildings")
            )
        return self._read_stat_table(owner, f"{kind} {category}")

    def _capture_kill_snapshot(self) -> dict[tuple[int, str], int]:
        return {
            (owner, category): self._read_stat_table(owner, f"Kills {category}")
            for owner in range(16)
            for category in ("Men", "Buildings")
        }

    @staticmethod
    def _counter_delta(current: int, previous: int) -> int:
        delta = (int(current) - int(previous)) & 0xFFFF
        # A normal UWORD wrap (65535 -> 0) produces a small delta. A huge
        # backwards jump means the match/stat table was reset, not 65k kills.
        return 0 if delta > 0x7FFF else delta

    def _kill_delta(self, owner: int, category: Any = "All") -> int:
        owner = self._stat_owner(owner)
        category = self._stat_category(category)
        if category == "All":
            return self.kill_deltas.get((owner, "Men"), 0) + self.kill_deltas.get((owner, "Buildings"), 0)
        return self.kill_deltas.get((owner, category), 0)

    def _resolve_game_mode_path(self) -> dict[str, int]:
        """Resolve Warcraft's native-verified game-mode getter and transition setter."""
        # score_victory immediately follows score_kill_unit in this validated
        # build. Its first call reads gwGameMode and compares it to GAME_VICTORY
        # before granting the 500-point victory bonus.
        score_victory = self.damage_callees["score_kill"] + 0x70
        score_body = self.pm.read_bytes(score_victory, 0x20)
        if (
            score_body[:8] != b"\x55\x8B\xEC\x56\x0F\xB6\x75\x08"
            or score_body[8] != 0xE8
            or score_body[0x0D:0x11] != b"\x66\x83\xF8\x06"
            or b"\xF4\x01\x00\x00" not in score_body
        ):
            raise RuntimeError("score_victory game-mode validation failed")
        displacement = struct.unpack_from("<i", score_body, 9)[0]
        get_mode = score_victory + 13 + displacement
        get_body = self.pm.read_bytes(get_mode, 7)
        if get_body[:2] != b"\x66\xA1" or get_body[6] != 0xC3:
            raise RuntimeError("game mode getter signature validation failed")
        getter_global = struct.unpack_from("<I", get_body, 2)[0]
        expected_global = self.base + GAME_MODE_RVA
        if getter_global != expected_global:
            raise RuntimeError(f"game mode getter global disagrees: 0x{getter_global:08X}")

        set_mode = self._resolve_unique_signature(
            GAME_SET_MODE_SIGNATURE,
            "game_set_mode",
            0x30,
            (
                b"\x8B\x45\x08\x66\x3B\xC8\x74\x1C",
                b"\x66\x83\xF9\x03",
                b"\x66\x89\x0D",
                b"\x66\xA3",
            ),
        )
        set_body = self.pm.read_bytes(set_mode, 0x30)
        setter_read_global = struct.unpack_from("<I", set_body, 6)[0]
        store_marker = set_body.find(b"\x66\xA3")
        if store_marker < 0:
            raise RuntimeError("game mode setter store validation failed")
        setter_write_global = struct.unpack_from("<I", set_body, store_marker + 2)[0]
        if setter_read_global != expected_global or setter_write_global != expected_global:
            raise RuntimeError(
                f"game mode setter globals disagree: read 0x{setter_read_global:08X}, "
                f"write 0x{setter_write_global:08X}"
            )
        return {"get": get_mode, "set": set_mode}

    def _read_game_mode(self) -> int:
        return self.pm.read_ushort(self.base + GAME_MODE_RVA)

    def _request_game_result(self, result: str) -> None:
        expected = GAME_VICTORY if result == "Victory" else GAME_LOSS
        before = self._read_game_mode()
        if before != GAME_RUN:
            raise RuntimeError(
                f"Cannot request {result}: Warcraft game mode is {before}, expected running mode {GAME_RUN}"
            )
        self._call_cdecl(self.game_mode_path["set"], [expected])

        # The validated setter can defer a mode change to the next simulation
        # boundary when Warcraft is inside its synchronized update section.
        # Allow that normal handoff to complete rather than writing the global.
        deadline = time.monotonic() + 1.0
        observed = before
        while time.monotonic() < deadline:
            observed = self._read_game_mode()
            if observed == expected:
                break
            time.sleep(0.01)
        if observed != expected:
            raise RuntimeError(
                f"Warcraft rejected {result}: game mode {before} -> {observed}, expected {expected}"
            )
        self.game_state = result
        self.log(f"GAME RESULT: {result} accepted through Warcraft game_set_mode ({before} -> {observed})")

    def _resolve_unit_create(self) -> int:
        image = self.pm.read_bytes(self.base, self.image_size)
        hits: list[int] = []
        start = 0
        while True:
            offset = image.find(UNIT_CREATE_SIGNATURE, start)
            if offset < 0:
                break
            body = image[offset:offset + 0x180]
            # Source-matched initialization writes owner/creator at +2C/+2D,
            # type at +27, tile coordinates at +18/+1A and HP at +22.
            required = (b"\x88\x46\x2C", b"\x88\x46\x2D", b"\x88\x4E\x27", b"\x66\x89\x56\x22")
            if all(pattern in body for pattern in required):
                hits.append(offset)
            start = offset + 1
        if len(hits) != 1:
            raise RuntimeError(f"unit_create signature validation found {len(hits)} candidates; action disabled")
        return self.base + hits[0]

    def _resolve_capture_unit(self) -> int:
        """Resolve source-matched capture_unit without relying on a fixed RVA."""
        image = self.pm.read_bytes(self.base, self.image_size)
        hits: list[int] = []
        start = 0
        while True:
            offset = image.find(CAPTURE_UNIT_SIGNATURE, start)
            if offset < 0:
                break
            body = image[offset:offset + 0x110]
            # capture_unit reads type/owner, updates capture and ownership tables,
            # honors playSound, sets a blinky timer, and starts color cycling.
            required = (
                b"\x0F\xB6\x46\x27",
                b"\x0F\xB6\x46\x2C",
                b"\x66\xFF\x04\x45",
                b"\x80\x7D\x10\x00",
                b"\x6A\x64",
            )
            if all(pattern in body for pattern in required):
                hits.append(offset)
            start = offset + 1
        if len(hits) != 1:
            raise RuntimeError(f"capture_unit signature validation found {len(hits)} candidates; action disabled")
        return self.base + hits[0]

    def _validate_building_create_path(self) -> dict[str, int]:
        """Prove unit_create retains the source building-foundation contract."""
        body = self.pm.read_bytes(self.unit_create_address, 0x3A0)
        if body[0x2B8:0x2BC] != b"\x66\x83\xFB\x3A":
            raise RuntimeError("unit_create FIRST_BLDG validation failed")
        if body[0x2C2:0x2C6] != b"\x66\x83\xFB\x68":
            raise RuntimeError("unit_create LAST_BLDG validation failed")
        if body[0x31A:0x323] != b"\xB8\x00\x01\x00\x00\x66\x09\x46\x1E":
            raise RuntimeError("unit_create SF_BUILD_FOUNDATION validation failed")
        counter_prefix = b"\x66\xFF\x04\x45"
        if body[0x312:0x316] != counter_prefix:
            raise RuntimeError("unit_create gwBldgInProgress update validation failed")
        counter_global = struct.unpack_from("<I", body, 0x316)[0]
        if counter_global != self.base + BUILDINGS_IN_PROGRESS_RVA:
            raise RuntimeError(
                f"unit_create gwBldgInProgress global disagrees: 0x{counter_global:08X}"
            )
        if body[0x38A:0x38E] != b"\x66\x09\x7E\x1E":
            raise RuntimeError("unit_create special-completed building validation failed")
        place_bldg = self._decode_rel32_call(
            self.unit_create_address, body, 0x395, "unit_create mtx_place_bldg"
        )
        return {"place_bldg": place_bldg}

    def _resolve_building_completion_path(self) -> dict[str, int]:
        """Resolve grow_structure and prove its native completion bookkeeping."""
        grow_structure = self._resolve_unique_signature(
            GROW_STRUCTURE_SIGNATURE,
            "grow_structure",
            0x37B,
            (
                b"\xB8\x80\x00\x00\x00\x66\x09\x43\x1E",
                b"\x66\x01\x0C\x45",
                b"\x88\x43\x25",
            ),
        )
        body = self.pm.read_bytes(grow_structure, 0x210)
        if body[0x14:0x16] != b"\xF6\x05" or body[0x1A:0x1B] != b"\x02":
            raise RuntimeError("grow_structure fast-build branch validation failed")
        cheat_global = struct.unpack_from("<I", body, 0x16)[0]
        if cheat_global != self.base + CHEAT_BITS_RVA:
            raise RuntimeError(f"grow_structure cheat global disagrees: 0x{cheat_global:08X}")
        steps_cost = self._decode_rel32_call(
            grow_structure, body, 0x52, "grow_structure unit_steps_cost"
        )
        if body[0xC2:0xC6] != b"\x0F\xB7\x14\x75":
            raise RuntimeError("grow_structure HP-table instruction validation failed")
        hp_global = struct.unpack_from("<I", body, 0xC6)[0]
        if hp_global != self.base + UNIT_HP_TABLE_RVA:
            raise RuntimeError(f"grow_structure HP table disagrees: 0x{hp_global:08X}")
        if body[0x1BF:0x1C3] != b"\x66\x01\x0C\x45":
            raise RuntimeError("grow_structure gwBldgInProgress decrement validation failed")
        counter_global = struct.unpack_from("<I", body, 0x1C3)[0]
        if counter_global != self.base + BUILDINGS_IN_PROGRESS_RVA:
            raise RuntimeError(f"grow_structure progress global disagrees: 0x{counter_global:08X}")
        return {"grow_structure": grow_structure, "steps_cost": steps_cost}

    def _resolve_unit_free(self) -> int:
        """Resolve the source-matched final unit record release routine."""
        image = self.pm.read_bytes(self.base, self.image_size)
        hits: list[int] = []
        start = 0
        while True:
            offset = image.find(UNIT_FREE_SIGNATURE, start)
            if offset < 0:
                break
            body = image[offset:offset + 0x30]
            if b"\xC7\x46\x14\x00\x00\x00\x00" in body and b"\xC6\x86\x8C\x00\x00\x00\x00" in body:
                hits.append(offset)
            start = offset + 1
        if len(hits) != 1:
            raise RuntimeError(f"unit_free signature validation found {len(hits)} candidates; action disabled")
        return self.base + hits[0]

    @staticmethod
    def _decode_rel32_call(function_address: int, body: bytes, offset: int, label: str) -> int:
        if offset + 5 > len(body) or body[offset] != 0xE8:
            raise RuntimeError(f"{label} call validation failed at +0x{offset:X}")
        displacement = struct.unpack_from("<i", body, offset + 1)[0]
        return function_address + offset + 5 + displacement

    def _resolve_remove_callees(self) -> dict[str, int]:
        """Decode unit_kill's source-matched cleanup calls used by silent removal."""
        unit_kill = self.damage_callees["unit_kill"]
        body = self.pm.read_bytes(unit_kill, 0x260)
        offsets = {
            "cancel_tree_harvest": 0x92,
            "unplace_man": 0x98,
            "deselect_unit": 0x1CD,
            "strategy_alert_kill": 0x1D3,
            "count_remove": 0x252,
        }
        result = {
            name: self._decode_rel32_call(unit_kill, body, offset, f"unit_kill {name}")
            for name, offset in offsets.items()
        }
        capture_body = self.pm.read_bytes(self.capture_unit_address, 0x70)
        capture_count_remove = self._decode_rel32_call(
            self.capture_unit_address, capture_body, 0x67, "capture_unit count_remove"
        )
        if result["count_remove"] != capture_count_remove:
            raise RuntimeError("Source-matched count_remove target disagrees between unit_kill and capture_unit")
        return result

    def _resolve_unique_signature(self, signature: bytes, label: str, body_size: int, required=()) -> int:
        """Resolve one source-matched routine and fail closed on ambiguity."""
        image = self.pm.read_bytes(self.base, self.image_size)
        hits: list[int] = []
        start = 0
        while True:
            offset = image.find(signature, start)
            if offset < 0:
                break
            body = image[offset:offset + body_size]
            if all(pattern in body for pattern in required):
                hits.append(offset)
            start = offset + 1
        if len(hits) != 1:
            raise RuntimeError(f"{label} signature validation found {len(hits)} candidates; action disabled")
        return self.base + hits[0]

    def _resolve_move_callees(self) -> dict[str, int]:
        """Resolve the native-verified map unplace/place movement contract."""
        create_body = self.pm.read_bytes(self.unit_create_address, 0x430)
        placeable = self._decode_rel32_call(
            self.unit_create_address, create_body, 0xD8, "unit_create mtx_unit_placeable"
        )
        place_man = self._decode_rel32_call(
            self.unit_create_address, create_body, 0x416, "unit_create mtx_place_man"
        )
        unmask_square = self._resolve_unique_signature(
            UNIT_UNMASK_SQUARE_SIGNATURE,
            "unit_unmask_square",
            0xC0,
            (b"\x8A\x4A\x2C", b"\x8A\x6A\x27", b"\x66\x03\x42\x18", b"\x66\x03\x42\x1A"),
        )
        set_curr_action = self._resolve_unique_signature(
            UNIT_SET_CURR_ACTION_SIGNATURE,
            "unit_set_curr_action",
            0xB2,
            (b"\xC6\x46\x2F\x3C", b"\x88\x5E\x2E", b"\x80\xFB\x02", b"\x66\x21\x46\x1E"),
        )
        action_body = self.pm.read_bytes(set_curr_action, 0x40)
        action_cancel = self._decode_rel32_call(
            set_curr_action, action_body, 0x2E, "unit_set_curr_action cancel_tree_harvest"
        )
        if action_cancel != self.remove_callees["cancel_tree_harvest"]:
            raise RuntimeError("Source-matched movement/action cleanup targets disagree")
        return {
            "placeable": placeable,
            "cancel_tree_harvest": self.remove_callees["cancel_tree_harvest"],
            "unplace_man": self.remove_callees["unplace_man"],
            "place_man": place_man,
            "unmask_square": unmask_square,
            "set_curr_action": set_curr_action,
        }

    def _resolve_order_callees(self) -> dict[str, int]:
        """Resolve Warcraft's real target assignment and order callbacks."""
        set_target = self._resolve_unique_signature(
            UNIT_SET_TARGET_SIGNATURE,
            "unit_set_target",
            0xE2,
            (
                b"\x89\x87\x88\x00\x00\x00",
                b"\x66\x89\x87\x84\x00\x00\x00",
                b"\x66\x89\x87\x86\x00\x00\x00",
                b"\xFF\x55\x18",
                b"\xC6\x47\x0B\x00",
                b"\x66\x09\x47\x1E",
            ),
        )
        do_move = self._resolve_unique_signature(
            DO_UNIT_MOVE_SIGNATURE,
            "do_unit_move",
            0x1B0,
            (
                b"\x8A\x56\x2C",
                b"\x0F\xB6\x46\x27",
                b"\x80\x7E\x2A\x00",
                b"\x8D\x9E\x88\x00\x00\x00",
                b"\x6A\x03\x56",
            ),
        )
        do_attack = self._resolve_unique_signature(
            DO_UNIT_ATTACK_SIGNATURE,
            "do_unit_attack",
            0x90,
            (
                b"\xC6\x45\x08\x09",
                b"\x0F\xB7\x86\x86\x00\x00\x00",
                b"\x0F\xB7\x86\x84\x00\x00\x00",
                b"\xC6\x45\x08\x0B",
                b"\xC6\x45\x08\x0A",
            ),
        )
        do_patrol = self._resolve_unique_signature(
            DO_UNIT_PATROL_SIGNATURE,
            "do_unit_patrol",
            0x90,
            (
                b"\xC7\x86\x88\x00\x00\x00\x00\x00\x00\x00",
                b"\xC7\x46\x70\x00\x00\x00\x00",
                b"\x89\x46\x6C",
                b"\x6A\x05\x56",
            ),
        )
        return {
            "set_target": set_target,
            "do_move": do_move,
            "do_attack": do_attack,
            "do_patrol": do_patrol,
        }

    def _find_existing_dispatcher_base(self) -> int:
        """Return a live WT30 mailbox allocation when our unit-run hook is present.

        Trigger Studio's executable hooks live in Warcraft, not in the Python GUI.
        If the GUI was closed without running cleanup, the game can therefore still
        contain a perfectly valid dispatcher and diplomacy guard.  Reattach must
        identify that exact pair before validating the native diplomacy body.
        """
        hook_address = self.base + SIMULATION_DISPATCH_HOOK_RVA
        try:
            current = self.pm.read_bytes(hook_address, 5)
            if current[:1] != b"\xE9":
                return 0
            target = hook_address + 5 + struct.unpack("<i", current[1:5])[0]
            if self.pm.read_uint(target + DISPATCH_MAGIC_OFFSET) != DISPATCH_MAGIC:
                return 0
            # Prove this is our layout, not a coincidental magic value.
            guard = target + DIPLOMACY_GUARD_CODE_OFFSET
            prefix = self.pm.read_bytes(guard, 10)
            if prefix[:5] != b"\x9C\x50\x51\x80\x3D":
                return 0
            active_operand = struct.unpack_from("<I", prefix, 5)[0]
            if active_operand != target + DISPATCH_VISION_ACTIVE_OFFSET:
                return 0
            return int(target)
        except Exception:
            return 0

    def _resolve_diplomacy_path(self) -> dict[str, int]:
        """Validate Remaster's extended relation/vision/allied-victory updater.

        Accept either an untouched supported-build entry or the exact WT30 guard left
        by an earlier Trigger Studio instance.  The latter is reconstructed to its
        native bytes for all native-verified operand/call validation below.
        """
        update = self.base + DIPLOMACY_UPDATE_RVA
        body = self.pm.read_bytes(update, 0xBD)
        if body[:len(DIPLOMACY_UPDATE_SIGNATURE)] != DIPLOMACY_UPDATE_SIGNATURE:
            dispatcher = self._find_existing_dispatcher_base()
            hook_len = DIPLOMACY_GUARD_HOOK_LENGTH
            if not dispatcher:
                raise RuntimeError(
                    "Diplomacy updater signature validation failed. Close other Warcraft tools "
                    "and fully restart Warcraft before attaching."
                )
            guard = dispatcher + DIPLOMACY_GUARD_CODE_OFFSET
            expected_patch = (
                b"\xE9" + self._relative32(update + 5, guard)
                + b"\x90" * (hook_len - 5)
            )
            if body[:hook_len] != expected_patch:
                raise RuntimeError(
                    "Diplomacy updater is modified, but it is not the matching WT30 vision guard. "
                    "Close other Warcraft tools and fully restart Warcraft before attaching."
                )
            guard_body = self.pm.read_bytes(guard, 0x100)
            original = DIPLOMACY_UPDATE_SIGNATURE[:hook_len]
            if original not in guard_body:
                raise RuntimeError(
                    "The existing WT30 diplomacy trampoline failed original-byte validation. "
                    "Fully restart Warcraft before attaching."
                )
            body = original + body[hook_len:]
            self.log(
                f"Recovered existing WT30 diplomacy guard and mailbox at 0x{dispatcher:08X}; "
                "safe reattach enabled"
            )
        operands = {
            "relations": struct.unpack_from("<I", body, 0x1B)[0],
            "shared_vision": struct.unpack_from("<I", body, 0x9A)[0],
            "allied_victory": struct.unpack_from("<I", body, 0xA1)[0],
        }
        expected = {
            "relations": self.base + ENEMY_TABLE_RVA,
            "shared_vision": self.base + SHARED_VISION_RVA,
            "allied_victory": self.base + ALLIED_VICTORY_RVA,
        }
        if operands != expected:
            raise RuntimeError(
                "Diplomacy updater globals disagree with the native-verified layout: "
                + ", ".join(f"{name}=0x{value:08X}" for name, value in operands.items())
            )
        rows = self.pm.read_bytes(expected["relations"], 8 * 16)
        if any(value > 3 for row in range(8) for value in rows[row * 16:row * 16 + 8]):
            raise RuntimeError("Diplomacy relation table contains values outside its 2-bit contract")
        self.pm.read_bytes(expected["shared_vision"], 8)
        self.pm.read_uchar(expected["allied_victory"])

        if body[0x8C] != 0xE8:
            raise RuntimeError("Diplomacy updater selection-color refresh call is missing")
        selection_colors = update + 0x91 + struct.unpack_from("<i", body, 0x8D)[0]
        expected_selection_colors = self.base + UNITDRAW_SET_SELECTION_COLORS_RVA
        if selection_colors != expected_selection_colors:
            raise RuntimeError(
                f"Diplomacy selection-color refresh disagrees: "
                f"0x{selection_colors:08X} != 0x{expected_selection_colors:08X}"
            )
        selection_code = self.pm.read_bytes(selection_colors, 0x18)
        if selection_code[:3] != b"\x0F\xB6\x15" or struct.unpack_from("<I", selection_code, 3)[0] != self.base + LOCAL_PLAYER_RVA:
            raise RuntimeError("unitdraw_set_selection_colors signature validation failed")

        owner_types = self.base + OWNER_TYPE_TABLE_RVA
        owner_values = self.pm.read_bytes(owner_types, 16)
        if any(value > 7 for value in owner_values):
            raise RuntimeError("Owner-type table contains values outside Warcraft's source contract")

        vision_refresh = self.base + VISION_REFRESH_RVA
        refresh = self.pm.read_bytes(vision_refresh, 0x30)
        if refresh[:8] != b"\x56\x8B\x35" + struct.pack("<I", self.base + UNIT_ARRAY_RVA) + b"\x57":
            raise RuntimeError("Shared-vision unit-mask refresh signature validation failed")
        if struct.pack("<I", self.base + SHARED_VISION_RVA) not in self.pm.read_bytes(vision_refresh, 0x70):
            raise RuntimeError("Shared-vision refresh does not reference the validated vision masks")

        # unit_unmask_square contains the authoritative BNE gate.  Its exact
        # code is: cmp byte ptr [gbMultiPlayer],0; when nonzero it bypasses the
        # source-era C_PLAYER-only check, allowing Computer units to contribute
        # their normal sight to the shared-vision planes.  Decode the absolute
        # operand instead of trusting a guessed data-table RVA.
        unmask_body = self.pm.read_bytes(self.move_callees["unmask_square"], 0x18)
        if unmask_body[:len(UNIT_UNMASK_SQUARE_SIGNATURE)] != UNIT_UNMASK_SQUARE_SIGNATURE:
            raise RuntimeError("unit_unmask_square multiplayer-gate signature changed")
        multiplayer_gate = struct.unpack_from("<I", unmask_body, 0x0B)[0]
        expected_gate = self.base + MULTIPLAYER_MODE_RVA
        if multiplayer_gate != expected_gate:
            raise RuntimeError(
                f"unit_unmask_square gbMultiPlayer operand disagrees: "
                f"0x{multiplayer_gate:08X} != 0x{expected_gate:08X}"
            )

        return {
            "update": update,
            **expected,
            "owner_types": owner_types,
            "vision_refresh": vision_refresh,
            "selection_colors": selection_colors,
            "multiplayer_gate": multiplayer_gate,
        }

    @staticmethod
    def _pack_relations(values: list[int]) -> int:
        if len(values) != 8 or any(not 0 <= int(value) <= 3 for value in values):
            raise ValueError("Diplomacy relation rows require eight 2-bit values")
        packed = 0
        for index, value in enumerate(values):
            packed |= (int(value) & 3) << (index * 2)
        return packed

    def _self_relation_code(self, player: int) -> int:
        player = int(player)
        if not 0 <= player < 8:
            raise ValueError("Self relation supports Player 1 through Player 8")
        # The diagonal must be Allied. Build 1.23.29 wrote 0 here, which is the
        # native Enemy value and allowed computer units to retarget their own side.
        return RELATION_ALLIED

    @staticmethod
    def _relation_is_allied(source: int, target: int, value: int) -> bool:
        # The diagonal is ownership/self, not a cross-player alliance enum.
        return int(source) == int(target) or int(value) == RELATION_ALLIED

    @staticmethod
    def _relation_is_enemy(source: int, target: int, value: int) -> bool:
        return int(source) != int(target) and int(value) == RELATION_ENEMY

    def _apply_relation_pairs(
        self,
        states: dict[int, dict[str, Any]],
        pairs: set[tuple[int, int]],
        relation: int,
    ) -> None:
        """Apply directed cross-player cells and keep every self-cell Allied."""
        relation = int(relation)
        if relation not in (RELATION_ENEMY, RELATION_ALLIED):
            raise ValueError("Alliance relations use 0=Enemy and 1=Allied")
        for source, target in sorted(pairs):
            if source == target:
                continue
            if source not in states:
                raise ValueError(f"Missing relation row for Player {source + 1}")
            states[source]["row"][target] = relation
        for source, state in states.items():
            state["row"][source] = self._self_relation_code(source)

    def _relation_masks(self, source: int, row: list[int]) -> tuple[int, int]:
        if len(row) < 8:
            raise ValueError("Relation row must contain Players 1-8")
        allied = 0
        enemy = 0
        for target, value in enumerate(row[:8]):
            if self._relation_is_allied(source, target, int(value)):
                allied |= 1 << target
            elif self._relation_is_enemy(source, target, int(value)):
                enemy |= 1 << target
        return allied & 0xFF, enemy & 0xFF

    def _read_diplomacy_state(self, player: int) -> tuple[list[int], int, bool]:
        if not 0 <= int(player) <= 7:
            raise ValueError("Diplomacy supports Player 1 through Player 8")
        player = int(player)
        row = list(self.pm.read_bytes(self.diplomacy_path["relations"] + player * 16, 8))
        vision = self.pm.read_uchar(self.diplomacy_path["shared_vision"] + player)
        victory_mask = self.pm.read_uchar(self.diplomacy_path["allied_victory"])
        return row, vision, bool(victory_mask & (1 << player))

    def _owner_type(self, player: int) -> int:
        if not 0 <= int(player) <= 15:
            raise ValueError("Owner type supports Player 1 through Player 16")
        return int(self.pm.read_uchar(self.diplomacy_path["owner_types"] + int(player)))

    @staticmethod
    def _owner_type_name(owner_type: int) -> str:
        return {
            C_PLAYER: "Human",
            C_COMPUTER: "Computer",
            C_NEUTRAL: "Neutral",
            C_NONE: "Empty",
        }.get(int(owner_type), f"Owner type {int(owner_type)}")

    def _diplomacy_call(self, player: int, relations: list[int], vision: int, allied_victory: bool) -> tuple[int, list[int]]:
        packed = self._pack_relations(relations)
        return (
            self.diplomacy_path["update"],
            [int(player), packed, int(vision) & 0xFF, 1 if allied_victory else 0],
        )

    @staticmethod
    def _apply_shared_vision_pairs(
        states: dict[int, dict[str, Any]],
        pairs: set[tuple[int, int]],
        enabled: bool,
    ) -> None:
        """Apply source->viewer pairs to Warcraft's source-indexed vision masks.

        Remaster stores one byte per vision *source*.  A bit in that byte names
        a player who is allowed to see the source player's fog and units.  The
        native unit-mask refresh proves this by loading gSharedVision[unitOwner]
        directly into Unit+0x29.  Earlier builds reversed these two dimensions.
        """
        for vision_source, vision_viewer in sorted(pairs):
            if vision_source not in states:
                raise ValueError(
                    f"Missing shared-vision source state for Player {vision_source + 1}"
                )
            if enabled:
                states[vision_source]["vision"] |= 1 << vision_viewer
            else:
                states[vision_source]["vision"] &= ~(1 << vision_viewer)
            # Every source always exposes its own vision to itself.
            states[vision_source]["vision"] |= 1 << vision_source

    def _remove_legacy_shared_vision_patches(self) -> int:
        """Restore any visibility-only compatibility patch already present."""
        restored = 0
        for rva, original, replacement in SHARED_VISION_OFFLINE_PATCHES:
            address = self.base + rva
            current = self.pm.read_bytes(address, len(original))
            if current == replacement:
                self._write_executable_bytes(address, original)
                restored += 1
            elif current != original:
                raise RuntimeError(
                    f"Shared-vision compatibility gate at RVA 0x{rva:X} changed: "
                    f"{current.hex(' ')}"
                )
        self._shared_vision_patch_originals.clear()
        if restored:
            self.log(f"Restored {restored} shared-vision compatibility patch(es)")
        return restored

    def _shared_vision_gate_operand_addresses(self) -> list[int]:
        """Locate visibility-only reads of ``gbMultiPlayer``.

        The seven historical patch RVAs identify conditional branches, not a
        guaranteed compiler layout for the instruction that produced the flags.
        Build 1.23.36 incorrectly required every branch to sit immediately after
        ``cmp byte ptr [gbMultiPlayer], 0``. The validated supported executables
        use equivalent layouts at those sites, so that validator rejected the
        correct build before any operand redirection occurred.

        Scan only the native-verified fog, unit-draw, visibility-cache, and unmask
        ranges. An address is accepted only when it is the absolute operand of a
        byte-reading x86 instruction. Historical branch bytes are validated
        separately, without assuming adjacency to the global-byte read.
        """
        gate_bytes = struct.pack("<I", int(self.diplomacy_path["multiplayer_gate"]))
        shadow_bytes = struct.pack("<I", int(self.dispatcher_vision_mode_address))
        found: set[int] = set()

        def is_absolute_byte_read(blob: bytes, index: int) -> bool:
            # ``index`` points to the four-byte absolute address operand.
            if index >= 2:
                opcode = blob[index - 2]
                modrm = blob[index - 1]
                absolute_modrm = (modrm & 0xC7) == 0x05
                # cmp byte ptr [absolute], imm8
                if opcode == 0x80 and modrm == 0x3D:
                    return True
                # test byte ptr [absolute], imm8
                if opcode == 0xF6 and modrm == 0x05:
                    return True
                # mov/cmp/test r8,[absolute] or [absolute],r8. These all read the
                # byte; writes such as opcode 0x88 are deliberately excluded.
                if opcode in {0x8A, 0x3A, 0x38, 0x84} and absolute_modrm:
                    return True
            # mov al, byte ptr [absolute]
            if index >= 1 and blob[index - 1] == 0xA0:
                return True
            # movzx reg32, byte ptr [absolute] -- accept every destination register,
            # not only the EAX ModRM emitted by one compiler layout.
            if (
                index >= 3
                and blob[index - 3:index - 1] == b"\x0F\xB6"
                and (blob[index - 1] & 0xC7) == 0x05
            ):
                return True
            return False

        for start_rva, end_rva in SHARED_VISION_GATE_SCAN_WINDOWS:
            blob = self.pm.read_bytes(self.base + start_rva, end_rva - start_rva)
            candidates: set[int] = set()
            for needle in (gate_bytes, shadow_bytes):
                cursor = 0
                while True:
                    index = blob.find(needle, cursor)
                    if index < 0:
                        break
                    candidates.add(index)
                    cursor = index + 1
            for index in sorted(candidates):
                if is_absolute_byte_read(blob, index):
                    found.add(self.base + start_rva + index)

        # Keep the proven historical branch locations as a build guard, but do not
        # invent a relationship between each branch and the preceding instruction.
        # _remove_legacy_shared_vision_patches() already restores the old NOP/JMP
        # replacements before this scan.
        changed_branches: list[int] = []
        for branch_rva, original_branch, _legacy_replacement in SHARED_VISION_OFFLINE_PATCHES:
            branch = self.pm.read_bytes(self.base + branch_rva, len(original_branch))
            if branch != original_branch:
                changed_branches.append(branch_rva)
        if changed_branches:
            joined = ", ".join(f"0x{rva:X}" for rva in changed_branches)
            raise RuntimeError(
                f"Historical shared-vision branch bytes changed at {joined}; "
                "fully restart Warcraft before attaching"
            )

        if not found:
            raise RuntimeError(
                "No validated gbMultiPlayer visibility operand was found in the "
                "native-verified fog/unit-draw ranges"
            )
        return sorted(found)

    def _ensure_shared_vision_offline_patch(self) -> bool:
        """Give visibility code a private multiplayer-mode byte.

        This exactly follows Warcraft's proven multiplayer visibility branches, but
        only inside fog, unit-draw, and unmask routines. The real gbMultiPlayer byte
        remains zero, preserving Peon commands and all normal offline behavior.
        """
        gate_bytes = struct.pack("<I", int(self.diplomacy_path["multiplayer_gate"]))
        shadow_bytes = struct.pack("<I", int(self.dispatcher_vision_mode_address))
        changed = False
        addresses = self._shared_vision_gate_operand_addresses()
        for address in addresses:
            current = self.pm.read_bytes(address, 4)
            if current == shadow_bytes:
                self._shared_vision_gate_operand_originals.setdefault(address, gate_bytes)
                continue
            if current != gate_bytes:
                raise RuntimeError(
                    f"Shared-vision gate operand at RVA 0x{address - self.base:X} changed: "
                    f"{current.hex(' ')}"
                )
            self._shared_vision_gate_operand_originals[address] = current
            self._write_executable_bytes(address, shadow_bytes)
            changed = True
        if changed:
            rvas = ", ".join(f"0x{address - self.base:X}" for address in addresses)
            self.log(
                f"SPLIT VISION MODE: redirected {len(addresses)} visibility gate operand(s) "
                f"to WT29 shadow byte [{rvas}]; gbMultiPlayer remains native for commands"
            )
        return changed

    def _set_diplomacy_mode_byte(self, enabled: bool) -> bool:
        """Hold Warcraft's BNE multiplayer/vision byte while shared vision is active.

        Computer-owned fog only remains stable while this byte stays nonzero.  This
        intentionally matches the proven 1.23.19 behavior.  Warcraft consequently
        treats the offline match like a network match for local Pause/speed-menu
        availability; Set Game Speed remains available as a trigger action.
        """
        address = int(self.diplomacy_path["multiplayer_gate"])
        current = int(self.pm.read_uchar(address))
        if enabled:
            if current:
                # In a real multiplayer match the byte belongs to Warcraft and must
                # not be restored by us. In an offline match, a pre-existing 1 is a
                # stale/continued Trigger Studio vision gate, whose natural value is 0.
                human_count = sum(
                    1 for owner in range(8)
                    if self._owner_type(owner) == C_PLAYER
                )
                if human_count <= 1 and not self._diplomacy_mode_forced:
                    self._diplomacy_mode_original = 0
                    self._diplomacy_mode_forced = True
                return False
            if self._diplomacy_mode_original is None:
                self._diplomacy_mode_original = current
            self.pm.write_uchar(address, 1)
            verified = int(self.pm.read_uchar(address))
            if verified != 1:
                raise RuntimeError("Could not enable Warcraft's Battle.net computer-vision byte")
            self._diplomacy_mode_forced = True
            self.log(
                f"BNE VISION SWITCH: gbMultiPlayer RVA 0x{MULTIPLAYER_MODE_RVA:X} "
                "0->1 and held while cross-player shared vision is active"
            )
            return True
        self._restore_diplomacy_mode_byte()
        return False

    def _restore_diplomacy_mode_byte(self) -> None:
        if not self._diplomacy_mode_forced:
            return
        address = int(self.diplomacy_path["multiplayer_gate"])
        original = 0 if self._diplomacy_mode_original is None else int(self._diplomacy_mode_original)
        self.pm.write_uchar(address, original)
        verified = int(self.pm.read_uchar(address))
        if verified != original:
            raise RuntimeError(
                f"Could not restore gbMultiPlayer at RVA 0x{MULTIPLAYER_MODE_RVA:X}: "
                f"expected {original}, got {verified}"
            )
        self.log(
            f"BNE VISION SWITCH: gbMultiPlayer restored to {original}; "
            "no cross-player shared vision remains"
        )
        self._diplomacy_mode_forced = False
        self._diplomacy_mode_original = None

    @staticmethod
    def _active_sources_from_vision_masks(masks: list[int]) -> set[int]:
        """Return sources whose requested mask grants sight cross-player."""
        return {
            source for source, mask in enumerate(masks[:8])
            if (int(mask) & 0xFF) & ~(1 << source)
        }

    def _capture_shared_vision_masks(self) -> list[int]:
        return [
            int(self.pm.read_uchar(self.diplomacy_path["shared_vision"] + source)) & 0xFF
            for source in range(8)
        ]

    def _remember_shared_vision_masks(self, masks: list[int]) -> set[int]:
        if len(masks) != 8:
            raise ValueError("Shared-vision mask set must contain exactly 8 rows")
        normalized = [((int(mask) & 0xFF) | (1 << source)) for source, mask in enumerate(masks)]
        self._shared_vision_masks = normalized
        active = self._active_sources_from_vision_masks(normalized)
        self._shared_vision_sources = set(active)
        if not active:
            self._next_shared_vision_refresh = 0.0
        return active

    def _program_shared_vision_guard(self, masks: list[int]) -> set[int]:
        """Publish one authoritative matrix while preserving native command mode.

        The real gbMultiPlayer byte and every visibility operand remain untouched.
        The WT30 unit_run-entry compositor consumes the shadow masks directly and
        repopulates the actual local fog planes before rendering.
        """
        if len(masks) != 8:
            raise ValueError("Shared-vision guard requires exactly 8 source masks")
        normalized = bytes(
            ((int(mask) & 0xFF) | (1 << source))
            for source, mask in enumerate(masks)
        )
        active = self._active_sources_from_vision_masks(list(normalized))
        enabled = 1 if active else 0
        native_mode = int(self.pm.read_uchar(self.diplomacy_path["multiplayer_gate"])) & 0xFF
        # WT30 never feeds a synthetic multiplayer mode into visibility code.
        # The post-reset compositor writes the actual local fog planes directly.
        vision_mode = native_mode
        self._dispatch_ops([
            ("write_bytes", self.dispatcher_vision_active_address, b"\x00"),
            ("write_bytes", self.dispatcher_vision_mode_address, b"\x00"),
            ("write_bytes", self.dispatcher_vision_masks_address, normalized),
            ("write_bytes", self.diplomacy_path["shared_vision"], normalized),
            ("write_bytes", self.dispatcher_vision_mode_address, bytes([vision_mode])),
            ("write_bytes", self.dispatcher_vision_active_address, bytes([enabled])),
        ])
        self._shared_vision_sources = set(active)
        return active

    def _restore_desired_shared_vision_masks(self) -> tuple[set[int], int]:
        """Repair guard state atomically; never chase a renderer-visible reset."""
        if self._shared_vision_masks is None:
            return self._shared_vision_active_sources(), 0
        expected = bytes(int(mask) & 0xFF for mask in self._shared_vision_masks)
        desired_active = 1 if self._active_sources_from_vision_masks(self._shared_vision_masks) else 0
        shadow = self.pm.read_bytes(self.dispatcher_vision_masks_address, 8)
        guard_active = int(self.pm.read_uchar(self.dispatcher_vision_active_address))
        live = self.pm.read_bytes(self.diplomacy_path["shared_vision"], 8)
        changed = sum(1 for before, after in zip(live, expected) if before != after)
        if shadow != expected or guard_active != desired_active or live != expected:
            active = self._program_shared_vision_guard(self._shared_vision_masks)
        else:
            active = self._active_sources_from_vision_masks(self._shared_vision_masks)
            self._shared_vision_sources = set(active)
        return active, changed

    def _shared_vision_active_sources(self) -> set[int]:
        """Return sources whose live mask grants sight to another player."""
        return self._active_sources_from_vision_masks(self._capture_shared_vision_masks())

    def _restore_offline_command_mode(self) -> bool:
        """Release a stale Trigger Studio gbMultiPlayer override in offline games.

        Build 1.23.32 held this byte at 1 to stabilize shared vision. That also
        routed an offline match through multiplayer command handling and could make
        the local peon ignore normal right-click work orders. Shared vision now uses
        the narrow visibility-only branches instead, so a one-human offline match
        must remain at its native value 0. Real multiplayer games are never changed.
        """
        address = int(self.diplomacy_path["multiplayer_gate"])
        current = int(self.pm.read_uchar(address))
        human_count = sum(
            1 for owner in range(8)
            if self._owner_type(owner) == C_PLAYER
        )
        if current != 1 or human_count > 1:
            return False
        self.pm.write_uchar(address, 0)
        verified = int(self.pm.read_uchar(address))
        if verified != 0:
            raise RuntimeError("Could not restore Warcraft's offline command mode")
        self._diplomacy_mode_forced = False
        self._diplomacy_mode_original = None
        self.log(
            f"OFFLINE COMMAND MODE: gbMultiPlayer RVA 0x{MULTIPLAYER_MODE_RVA:X} "
            "restored 1->0; local worker and unit commands remain native"
        )
        return True

    def _sync_diplomacy_compatibility(self) -> bool:
        """Keep command mode native and remove every legacy visibility redirect.

        WT30 updates the real local fog planes inside the unit_run-entry simulation
        hook. No private multiplayer mode is needed, so workers and local UI commands
        continue to use Warcraft's normal offline path.
        """
        masks = self._shared_vision_masks
        active = bool(
            self._active_sources_from_vision_masks(masks)
            if masks is not None else self._shared_vision_active_sources()
        )
        self._restore_offline_command_mode()
        # Remove any WT29 operand redirection before enabling the compositor.
        self._restore_shared_vision_offline_patch()
        native_mode = int(self.pm.read_uchar(self.diplomacy_path["multiplayer_gate"])) & 0xFF
        desired = native_mode
        if int(self.pm.read_uchar(self.dispatcher_vision_mode_address)) != desired:
            self.pm.write_uchar(self.dispatcher_vision_mode_address, desired)
        return active

    def _refresh_shared_vision_now(
        self,
        sources: set[int] | None = None,
        *,
        force_unmask: bool = True,
    ) -> int:
        """Publish unit visibility once after a shared-vision matrix changes.

        Warcraft's native refresh copies gSharedVision into existing Unit+0x29
        masks. The WT30 simulation compositor independently owns terrain fog after
        every prep_mask_map reset, so this action never toggles multiplayer mode or
        performs a repeating global fog rebuild.
        """
        if sources is None:
            sources = self._shared_vision_active_sources()
        sources = set(sources)
        if not sources:
            return 0
        self._restore_offline_command_mode()
        self._restore_shared_vision_offline_patch()
        native_mode = int(self.pm.read_uchar(self.diplomacy_path["multiplayer_gate"])) & 0xFF
        if int(self.pm.read_uchar(self.dispatcher_vision_mode_address)) != native_mode:
            self.pm.write_uchar(self.dispatcher_vision_mode_address, native_mode)

        source_units = [unit.address for unit in self.units() if int(unit.owner) in sources]
        # One unit-mask refresh publishes gSharedVision into Unit+0x29. Terrain
        # fog is handled continuously by the unit_run-entry compositor, not here.
        self._call_cdecl_batched([(self.diplomacy_path["vision_refresh"], [])])
        self._shared_vision_sources = sources
        self._next_shared_vision_refresh = 0.0
        return len(source_units)

    def _refresh_shared_vision_runtime(self) -> None:
        """Maintain the shadow matrix while the simulation hook owns local fog.

        No Python timer, global fog rebuild, or synthetic multiplayer mode runs here.
        The unit_run-entry trampoline repopulates Warcraft's local fog planes after
        every native mask reset and before rendering can observe an off-frame.
        """
        if self._shared_vision_masks is None:
            return
        active = self._active_sources_from_vision_masks(self._shared_vision_masks)
        desired_active = 1 if active else 0
        native_mode = int(self.pm.read_uchar(self.diplomacy_path["multiplayer_gate"])) & 0xFF
        desired_mode = native_mode
        expected = bytes(int(mask) & 0xFF for mask in self._shared_vision_masks)
        shadow = self.pm.read_bytes(self.dispatcher_vision_masks_address, 8)
        guard_active = int(self.pm.read_uchar(self.dispatcher_vision_active_address))
        mode = int(self.pm.read_uchar(self.dispatcher_vision_mode_address))
        if shadow != expected or guard_active != desired_active or mode != desired_mode:
            self._program_shared_vision_guard(self._shared_vision_masks)
        self._shared_vision_sources = set(active)
        self._sync_diplomacy_compatibility()

    def _restore_shared_vision_offline_patch(self) -> None:
        """Restore visibility gate operands to the real gbMultiPlayer byte."""
        if not self._shared_vision_gate_operand_originals:
            return
        shadow_bytes = struct.pack("<I", int(self.dispatcher_vision_mode_address))
        for address, original in sorted(self._shared_vision_gate_operand_originals.items()):
            current = self.pm.read_bytes(address, len(original))
            if current == shadow_bytes:
                self._write_executable_bytes(address, original)
            elif current != original:
                raise RuntimeError(
                    f"Shared-vision operand changed before cleanup at RVA "
                    f"0x{address - self.base:X}: {current.hex(' ')}"
                )
        restored = len(self._shared_vision_gate_operand_originals)
        self._shared_vision_gate_operand_originals.clear()
        if restored:
            self.log(f"Restored {restored} split shared-vision gate operand(s)")

    def _cancel_now_friendly_combat(self, allied_pairs: set[tuple[int, int]]) -> int:
        """Stop combat state that still points at newly allied players.

        Warcraft checks gEnemyTbl while choosing a *new* target, but an existing
        attack can retain pAttacker, manSavedTarget, or targetUnit pointers after
        diplomacy changes.  Attack-area orders can also retain their combat state
        without a direct target pointer.  Clear all three native-verified pointers
        and return affected units to Guard so the new matrix takes effect now.
        """
        if not allied_pairs:
            return 0

        units = self.units()
        active_owners = {unit.owner for unit in units if 0 <= unit.owner < 8}
        pool_end = self.unit_pool + self.max_units * UNIT_SIZE
        combat_actions = {8, 9, 10, 11, 12}

        def pointer_owner(address: int) -> int | None:
            if not (
                self.unit_pool <= address < pool_end
                and (address - self.unit_pool) % UNIT_SIZE == 0
            ):
                return None
            try:
                data = self.pm.read_bytes(address, UNIT_SIZE)
            except Exception:
                return None
            if not self._record_is_allocated(data):
                return None
            return int(data[0x2C])

        rows: dict[int, list[int]] = {}
        for source, _target in allied_pairs:
            if source not in rows:
                rows[source] = self._read_diplomacy_state(source)[0]

        to_stop: list[int] = []
        for unit in units:
            if unit.owner not in rows:
                continue
            if unit.action not in combat_actions and unit.next_action not in combat_actions:
                continue

            data = self.pm.read_bytes(unit.address, UNIT_SIZE)
            pointer_targets = {
                pointer_owner(int.from_bytes(data[offset:offset + 4], "little"))
                for offset in (0x50, 0x70, 0x88)
            }
            pointer_targets.discard(None)
            points_to_new_ally = any(
                (unit.owner, target_owner) in allied_pairs
                for target_owner in pointer_targets
            )

            # A target-less attack-area/patrol combat state must also be stopped
            # when this player has no remaining live enemies.  This is the common
            # all-to-all test case and prevents old retaliation state from killing
            # units after every matrix entry was changed to Allied.
            row = rows[unit.owner]
            has_live_enemy = any(
                other != unit.owner
                and other in active_owners
                and self._relation_is_enemy(unit.owner, other, row[other])
                for other in range(8)
            )
            targetless_without_enemies = not pointer_targets and not has_live_enemy

            if points_to_new_ally or targetless_without_enemies:
                to_stop.append(unit.address)

        for offset in range(0, len(to_stop), 32):
            operations: list[tuple] = []
            for address in to_stop[offset:offset + 32]:
                operations.extend([
                    ("write_dword", address + 0x50, 0),  # pAttacker
                    ("write_dword", address + 0x70, 0),  # manSavedTarget
                    ("write_dword", address + 0x88, 0),  # targetUnit
                    ("call", self.move_callees["set_curr_action"], [address, 2]),
                ])
            if operations:
                self._dispatch_ops(operations)
        return len(to_stop)

    def _rearm_new_enemy_combat(self, enemy_pairs: set[tuple[int, int]]) -> int:
        """Wake idle computer combat units after relations become hostile.

        Computer-vs-computer slots begin allied in Warcraft's normal offline setup.
        Changing gEnemyTbl alone does not recreate an attack order that was cleared
        while the units were friendly.  Re-enter Guard once for targetless combat
        units owned by rows that gained a live enemy; Warcraft then performs its
        normal enemy scan using the newly applied native relation row.
        """
        if not enemy_pairs:
            return 0
        source_owners = {
            source for source, _target in enemy_pairs
            if self._owner_type(source) == C_COMPUTER
        }
        if not source_owners:
            return 0

        combat_types = frozenset({
            0, 1, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15,
            16, 17, 18, 19, 20, 21, 22, 23, 24, 25,
            30, 31, 32, 33, 35, 36, 37, 38, 39, 42, 43,
            44, 46, 47, 49, 50, 51, 52, 53, 55, 56,
        })
        pool_end = self.unit_pool + self.max_units * UNIT_SIZE
        candidates: list[int] = []
        for unit in self.units():
            if unit.owner not in source_owners or unit.unit_type not in combat_types:
                continue
            if unit.action in {8, 9, 10, 11, 12} or unit.next_action in {8, 9, 10, 11, 12}:
                continue
            data = self.pm.read_bytes(unit.address, UNIT_SIZE)
            has_target = False
            for offset in (0x50, 0x70, 0x88):
                pointer = int.from_bytes(data[offset:offset + 4], "little")
                if self.unit_pool <= pointer < pool_end and (pointer - self.unit_pool) % UNIT_SIZE == 0:
                    has_target = True
                    break
            if not has_target:
                candidates.append(unit.address)

        for offset in range(0, len(candidates), 32):
            self._call_cdecl_batched([
                (self.move_callees["set_curr_action"], [address, 2])
                for address in candidates[offset:offset + 32]
            ])
        return len(candidates)

    def _resolve_bullet_path(self) -> dict[str, int]:
        """Resolve action_do_attack -> bullet_create and prove the bullet globals."""
        action_do_attack = self._resolve_unique_signature(
            ACTION_DO_ATTACK_SIGNATURE,
            "action_do_attack",
            0x60,
            (
                b"\x80\xB8",
                b"\x1D\x74\x0B\xE8",
                b"\x8B\x86\x88\x00\x00\x00",
                b"\x0F\xB7\x86\x84\x00\x00\x00",
                b"\x0F\xB7\x86\x86\x00\x00\x00",
            ),
        )
        action_body = self.pm.read_bytes(action_do_attack, 0x60)
        table_address = struct.unpack_from("<I", action_body, 0x0E)[0]
        if table_address != self.base + UNIT_BULLET_TABLE_RVA:
            raise RuntimeError(
                f"action_do_attack bullet table disagrees: 0x{table_address:08X}"
            )
        if action_body[0x12] != BT_NONE:
            raise RuntimeError(
                f"action_do_attack BT_NONE disagrees: {action_body[0x12]} expected {BT_NONE}"
            )
        bullet_create = self._decode_rel32_call(
            action_do_attack, action_body, 0x15, "action_do_attack bullet_create"
        )
        create_body = self.pm.read_bytes(bullet_create, 0x24A)
        if create_body[:14] != b"\x55\x8B\xEC\x53\x8B\x5D\x08\x3B\x9B\x88\x00\x00\x00\x75":
            raise RuntimeError("bullet_create entry signature validation failed")
        if create_body[0x1E] != 0xA1 or create_body[0x24:0x26] != b"\x8B\x35":
            raise RuntimeError("bullet_create allocator-global instructions were not found")
        max_address = struct.unpack_from("<I", create_body, 0x1F)[0]
        pool_address = struct.unpack_from("<I", create_body, 0x26)[0]
        create_table_address = struct.unpack_from("<I", create_body, 0x67)[0]
        expected = (
            self.base + MAX_BULLETS_RVA,
            self.base + BULLET_ARRAY_RVA,
            self.base + UNIT_BULLET_TABLE_RVA,
        )
        if (max_address, pool_address, create_table_address) != expected:
            raise RuntimeError(
                "bullet_create globals disagree: "
                f"max=0x{max_address:08X}, pool=0x{pool_address:08X}, "
                f"type-table=0x{create_table_address:08X}"
            )
        required = (
            b"\x83\xC6\x40",
            b"\x6A\x40\x6A\x00\x56",
            b"\x89\x5E\x30",
            b"\x66\xC7\x46\x35\x02\x00",
            b"\x89\x56\x2C",
            b"\x88\x46\x37",
            b"\x8B\xC6\x5E\x5B\x5D\xC3",
        )
        if not all(pattern in create_body for pattern in required):
            raise RuntimeError("bullet_create record-layout validation failed")
        bullet_create_xy = self._decode_rel32_call(
            bullet_create, create_body, 0x23C, "bullet_create bullet_create_xy"
        )
        xy_body = self.pm.read_bytes(bullet_create_xy, 0x69)
        if xy_body[:4] != b"\x55\x8B\xEC\xA1" or xy_body[0x08:0x0B] != b"\x56\x8B\x35":
            raise RuntimeError("bullet_create_xy entry signature validation failed")
        xy_max_address = struct.unpack_from("<I", xy_body, 0x04)[0]
        xy_pool_address = struct.unpack_from("<I", xy_body, 0x0B)[0]
        if (xy_max_address, xy_pool_address) != (
            self.base + MAX_BULLETS_RVA,
            self.base + BULLET_ARRAY_RVA,
        ):
            raise RuntimeError(
                f"bullet_create_xy globals disagree: max=0x{xy_max_address:08X}, "
                f"pool=0x{xy_pool_address:08X}"
            )
        xy_required = (
            b"\x83\xC6\x40",
            b"\x6A\x40\x6A\x00\x56",
            b"\x8A\x45\x10",
            b"\x88\x46\x34",
            b"\x66\x8B\x45\x08\x66\x89\x06",
            b"\x66\x8B\x45\x0C",
            b"\xC6\x46\x35\x02",
            b"\x8B\xC6\x5E\x5D\xC3",
        )
        if not all(pattern in xy_body for pattern in xy_required):
            raise RuntimeError("bullet_create_xy record-layout validation failed")
        return {
            "action_do_attack": action_do_attack,
            "bullet_create": bullet_create,
            "bullet_create_xy": bullet_create_xy,
        }

    def _resolve_spell_path(self) -> dict[str, int]:
        """Resolve native-verified entry points used by caster-free spell actions."""
        place_rune = self._resolve_unique_signature(
            PLACE_RUNE_SIGNATURE,
            "place_a_rune",
            0xB4,
            (
                b"\x83\xF8\x32\x7C",
                b"\xB9\x00\x08\x00\x00",
                b"\x6A\x0B\xC1\xE2\x05",
                b"\x66\x89\x0C\x45",
                b"\xB8\x01\x00\x00\x00",
            ),
        )
        body = self.pm.read_bytes(place_rune, 0xB4)
        operands = {
            "map_dimension": struct.unpack_from("<I", body, 0x05)[0],
            "unit_map": struct.unpack_from("<I", body, 0x1E)[0],
            "delay_read": struct.unpack_from("<I", body, 0x34)[0],
            "rune_x_read": struct.unpack_from("<I", body, 0x3E)[0],
            "rune_y_read": struct.unpack_from("<I", body, 0x49)[0],
            "rune_y_write": struct.unpack_from("<I", body, 0x7D)[0],
            "rune_x_write": struct.unpack_from("<I", body, 0x88)[0],
            "delay_write": struct.unpack_from("<I", body, 0x9E)[0],
        }
        expected = {
            "map_dimension": self.base + MAP_DIMENSION_RVA,
            "unit_map": self.base + UNIT_MAP_RVA,
            "delay_read": self.base + RUNE_DELAY_RVA,
            "rune_x_read": self.base + RUNE_X_RVA,
            "rune_y_read": self.base + RUNE_Y_RVA,
            "rune_y_write": self.base + RUNE_Y_RVA,
            "rune_x_write": self.base + RUNE_X_RVA,
            "delay_write": self.base + RUNE_DELAY_RVA,
        }
        if operands != expected:
            raise RuntimeError(
                "place_a_rune table addresses disagree: "
                + ", ".join(f"{name}=0x{address:08X}" for name, address in operands.items())
            )
        visual = self._decode_rel32_call(
            place_rune, body, 0xA4, "place_a_rune bullet_create_xy"
        )
        if visual != self.bullet_path["bullet_create_xy"]:
            raise RuntimeError("place_a_rune visual constructor disagrees with bullet_create_xy")
        delays = [
            self.pm.read_ushort(self.base + RUNE_DELAY_RVA + slot * 2)
            for slot in range(MAX_RUNES)
        ]
        if any(delay > RUNE_TIME for delay in delays):
            raise RuntimeError("Live rune table contains an invalid delay value")

        # do_vision itself requires a PTUnit only to read unitOwner. Decode its
        # real reveal, camera, visual, and sound callees so a trigger can supply
        # an explicit player and location without manufacturing a fake caster.
        do_vision = self._resolve_unique_signature(
            DO_VISION_SIGNATURE,
            "do_vision",
            0xB0,
            (
                b"\x0F\xB6\x40\x2C",
                b"\xA0" + struct.pack("<I", self.base + LOCAL_PLAYER_RVA),
                b"\xC1\xE6\x05\x6A\x16\xC1\xE7\x05",
                b"\x6A\x07",
            ),
        )
        vision_body = self.pm.read_bytes(do_vision, 0xB0)
        if vision_body[0x0A:0x0C] != b"\x66\xA1":
            raise RuntimeError("do_vision map-dimension instruction validation failed")
        dimension_global = struct.unpack_from("<I", vision_body, 0x0C)[0]
        if dimension_global != self.base + MAP_DIMENSION_RVA:
            raise RuntimeError(
                f"do_vision map-dimension global disagrees: 0x{dimension_global:08X}"
            )
        if vision_body[0x74] != 0xA0:
            raise RuntimeError("do_vision local-player instruction validation failed")
        local_player_global = struct.unpack_from("<I", vision_body, 0x75)[0]
        if local_player_global != self.base + LOCAL_PLAYER_RVA:
            raise RuntimeError(
                f"do_vision local-player global disagrees: 0x{local_player_global:08X}"
            )
        vision_unmask = self._decode_rel32_call(
            do_vision, vision_body, 0x66, "do_vision cell_unmask_19x19"
        )
        vision_set_pos = self._decode_rel32_call(
            do_vision, vision_body, 0x80, "do_vision cell_set_pos"
        )
        vision_visual = self._decode_rel32_call(
            do_vision, vision_body, 0x98, "do_vision bullet_create_xy"
        )
        vision_sound = self._decode_rel32_call(
            do_vision, vision_body, 0xA1, "do_vision gamesnd_spellxy"
        )
        if vision_visual != self.bullet_path["bullet_create_xy"]:
            raise RuntimeError("do_vision visual constructor disagrees with bullet_create_xy")

        unmask_body = self.pm.read_bytes(vision_unmask, 0x1D)
        if (
            unmask_body[:3] != b"\x55\x8B\xEC"
            or unmask_body[3] != 0x68
            or unmask_body[8:0x13]
            != b"\x6A\x13\xFF\x75\x10\xFF\x75\x0C\xFF\x75\x08"
            or unmask_body[0x13] != 0xE8
            or unmask_body[0x18:0x1D] != b"\x83\xC4\x14\x5D\xC3"
        ):
            raise RuntimeError("cell_unmask_19x19 source contract validation failed")
        mask_table = struct.unpack_from("<I", unmask_body, 4)[0]
        if mask_table != self.base + VISION_MASK_TABLE_RVA:
            raise RuntimeError(
                f"cell_unmask_19x19 mask table disagrees: 0x{mask_table:08X}"
            )
        camera_body = self.pm.read_bytes(vision_set_pos, 0x12)
        if (
            camera_body[:6] != b"\x55\x8B\xEC\x0F\xB7\x15"
            or struct.unpack_from("<I", camera_body, 6)[0]
            != self.base + MAP_DIMENSION_RVA
            or camera_body[0x0A:0x0E] != b"\x0F\xBF\x4D\x0C"
        ):
            raise RuntimeError("cell_set_pos source contract validation failed")
        sound_body = self.pm.read_bytes(vision_sound, 0x3B)
        sound_required = (
            b"\x83\xE2\x1F\x03\xC2\xC1\xF8\x05",
            b"\x6A\x01\x66\x89\x45\x0A\x8B\x45\x10\x6A\x01",
            b"\x83\xC0\x45\x50",
        )
        if sound_body[:6] != b"\x55\x8B\xEC\x8B\x45\x08" or not all(
            pattern in sound_body for pattern in sound_required
        ):
            raise RuntimeError("gamesnd_spellxy source contract validation failed")

        do_unit_spell = self._resolve_unique_signature(
            DO_UNIT_SPELL_SIGNATURE,
            "do_unit_spell",
            0x50,
            (
                b"\x08\x56\x8B\x75\x08\x74\x04\xC6\x46\x26\xFF",
                b"\x0F\xB6\x05" + struct.pack("<I", self.base + ACTION_TYPE_RVA),
                b"\x0F\xB7\x05" + struct.pack("<I", self.base + ACTION_TYPE_RVA),
                b"\x80\xB8" + struct.pack("<I", self.base + SPELL_AREA_EFFECT_TABLE_RVA) + b"\x00",
            ),
        )
        spell_order_body = self.pm.read_bytes(do_unit_spell, 0x50)
        next_action = self._decode_rel32_call(
            do_unit_spell, spell_order_body, 0x1D, "do_unit_spell unit_set_next_action"
        )
        if self.pm.read_ushort(self.base + ACTION_TYPE_RVA) != 0:
            raise RuntimeError("gwActionType is nonzero while attaching; caster spell orders disabled")
        for spell_action, spell_name in (
            (SPELL_VISION, "Holy Vision"),
            (SPELL_FIREBALL, "Fireball"),
            (SPELL_BLIZZARD, "Blizzard"),
            (SPELL_EYE, "Eye of Kilrogg"),
            (SPELL_EXORCISM, "Exorcism"),
            (SPELL_RAISEDEAD, "Raise Dead"),
            (SPELL_DRAINLIFE, "Death Coil"),
            (SPELL_WHIRLWIND, "Whirlwind"),
            (SPELL_RUNES, "Runes"),
            (SPELL_ROT, "Death and Decay"),
        ):
            action_function = self.pm.read_uint(
                self.base + UNIT_ACTION_FUNCTION_TABLE_RVA + spell_action * 4
            )
            if action_function != do_unit_spell:
                raise RuntimeError(
                    f"{spell_name} action-function table disagrees: 0x{action_function:08X}"
                )
            if self.pm.read_uchar(
                self.base + SPELL_AREA_EFFECT_TABLE_RVA + spell_action
            ) != 1:
                raise RuntimeError(
                    f"{spell_name} is not marked as a source area-effect spell"
                )
        for spell_action, spell_name in (
            (SPELL_FLAME_SHIELD, "Flame Shield"),
            (SPELL_SLOW, "Slow"),
            (SPELL_INVIS, "Invisibility"),
            (SPELL_POLYMORPH, "Polymorph"),
            (SPELL_BLOODLUST, "Bloodlust"),
            (SPELL_HEAL, "Heal"),
            (SPELL_HASTE, "Haste"),
            (SPELL_ARMOR, "Unholy Armor"),
        ):
            target_action_function = self.pm.read_uint(
                self.base + UNIT_ACTION_FUNCTION_TABLE_RVA + spell_action * 4
            )
            if target_action_function != do_unit_spell:
                raise RuntimeError(
                    f"{spell_name} action-function table disagrees: "
                    f"0x{target_action_function:08X}"
                )
            if self.pm.read_uchar(
                self.base + SPELL_AREA_EFFECT_TABLE_RVA + spell_action
            ) != 0:
                raise RuntimeError(
                    f"{spell_name} is incorrectly marked as an area-effect spell"
                )

        action_vision = self._resolve_unique_signature(
            ACTION_VISION_SIGNATURE,
            "action_vision",
            0xCA,
            (
                b"\x0F\xB7\x14\x45"
                + struct.pack("<I", self.base + CASTING_COST_TABLE_RVA),
                b"\x83\xC6\x06",
                b"\x83\xC6\xFA",
                b"\x83\x3D",
            ),
        )
        vision_action_body = self.pm.read_bytes(action_vision, 0xCA)
        for call_offset, branch_name in ((0x22, "insufficient-mana"), (0x39, "accepted")):
            if self._decode_rel32_call(
                action_vision,
                vision_action_body,
                call_offset,
                f"action_vision {branch_name} unit_set_next_action",
            ) != next_action:
                raise RuntimeError(f"action_vision {branch_name} guard path disagrees")
        for call_offset in (0x58, 0x63, 0x6E, 0x7E, 0x8B, 0x9E, 0xA8):
            if self._decode_rel32_call(
                action_vision,
                vision_action_body,
                call_offset,
                "action_vision do_vision",
            ) != do_vision:
                raise RuntimeError("Holy Vision reveal helpers disagree with do_vision")
        vision_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_VISION * 4
        )
        if vision_dispatch != action_vision:
            raise RuntimeError(
                f"Holy Vision action-dispatch table disagrees: 0x{vision_dispatch:08X}"
            )
        vision_cost = self.pm.read_ushort(
            self.base + CASTING_COST_TABLE_RVA + SPELL_VISION * 2
        )
        if vision_cost != 70:
            raise RuntimeError(f"Holy Vision native mana cost disagrees: {vision_cost}")

        action_eye = self._resolve_unique_signature(
            ACTION_EYE_SIGNATURE,
            "action_eye",
            0x74,
            (
                b"\x68"
                + struct.pack(
                    "<I",
                    self.base + UNIT_MTX_SIZE_TABLE_RVA + EYE_UNIT_TYPE * 4,
                ),
                b"\x0F\xB7\x46\x1A\x6A\x2D",
                b"\x68\x5A\x01\x00\x00",
            ),
        )
        eye_body = self.pm.read_bytes(action_eye, 0x74)
        for call_offset, branch_name in ((0x21, "insufficient-mana"), (0x31, "accepted")):
            if self._decode_rel32_call(
                action_eye,
                eye_body,
                call_offset,
                f"action_eye {branch_name} unit_set_next_action",
            ) != next_action:
                raise RuntimeError(f"action_eye {branch_name} guard path disagrees")
        eye_create_place = self._decode_rel32_call(
            action_eye, eye_body, 0x52, "action_eye unit_create_place"
        )
        eye_sound = self._decode_rel32_call(
            action_eye, eye_body, 0x69, "action_eye gamesnd_spell"
        )
        create_place_body = self.pm.read_bytes(eye_create_place, 0xD2)
        if (
            create_place_body[:10]
            != b"\x55\x8B\xEC\x83\xEC\x08\x66\x8B\x45\x08"
            or b"\xC1\xE0\x05\x0F\xB7\xF8" not in create_place_body
            or b"\xC1\xE0\x05\x0F\xB7\xD8" not in create_place_body
            or b"\xF6\x04\x85"
            + struct.pack("<I", self.base + UNIT_IS_TABLE_RVA)
            + b"\x10"
            not in create_place_body
        ):
            raise RuntimeError("unit_create_place source contract validation failed")
        eye_unit_create = self._decode_rel32_call(
            eye_create_place,
            create_place_body,
            0x8E,
            "unit_create_place unit_create",
        )
        eye_placement_visual = self._decode_rel32_call(
            eye_create_place,
            create_place_body,
            0xC1,
            "unit_create_place bullet_create_xy",
        )
        if eye_unit_create != self.unit_create_address:
            raise RuntimeError("Eye of Kilrogg allocator disagrees with Create Units")
        if eye_placement_visual != self.bullet_path["bullet_create_xy"]:
            raise RuntimeError("Eye placement visual disagrees with projectile path")
        eye_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_EYE * 4
        )
        if eye_dispatch != action_eye:
            raise RuntimeError(
                f"Eye of Kilrogg action-dispatch table disagrees: 0x{eye_dispatch:08X}"
            )
        eye_cost = self.pm.read_ushort(
            self.base + CASTING_COST_TABLE_RVA + SPELL_EYE * 2
        )
        if eye_cost != 70:
            raise RuntimeError(f"Eye of Kilrogg native mana cost disagrees: {eye_cost}")

        action_fireball = self._resolve_unique_signature(
            ACTION_FIREBALL_SIGNATURE,
            "action_fireball",
            0x50,
            (
                b"\x0F\xB7\x14\x45"
                + struct.pack("<I", self.base + CASTING_COST_TABLE_RVA),
                b"\x33\xC0\x56\x66\x89\x46\x44\xE8",
                b"\x83\xC4\x0C\x5E\x5D\xC3",
            ),
        )
        fireball_body = self.pm.read_bytes(action_fireball, 0x50)
        if self._decode_rel32_call(
            action_fireball,
            fireball_body,
            0x21,
            "action_fireball insufficient-mana unit_set_next_action",
        ) != next_action:
            raise RuntimeError("action_fireball insufficient-mana guard path disagrees")
        if self._decode_rel32_call(
            action_fireball,
            fireball_body,
            0x31,
            "action_fireball success unit_set_next_action",
        ) != next_action:
            raise RuntimeError("action_fireball success guard path disagrees")
        bullet_create_fireball = self._decode_rel32_call(
            action_fireball,
            fireball_body,
            0x3D,
            "action_fireball bullet_create_fireball",
        )
        fireball_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_FIREBALL * 4
        )
        if fireball_dispatch != action_fireball:
            raise RuntimeError(
                f"Fireball action-dispatch table disagrees: 0x{fireball_dispatch:08X}"
            )
        fireball_create_body = self.pm.read_bytes(bullet_create_fireball, 0x1A2)
        if (
            fireball_create_body[:13]
            != b"\x55\x8B\xEC\x57\x8B\x7D\x08\x3B\xBF\x88\x00\x00\x00"
            or fireball_create_body[0x1C] != 0xA1
            or struct.unpack_from("<I", fireball_create_body, 0x1D)[0]
            != self.base + MAX_BULLETS_RVA
            or fireball_create_body[0x22:0x24] != b"\x8B\x35"
            or struct.unpack_from("<I", fireball_create_body, 0x24)[0]
            != self.base + BULLET_ARRAY_RVA
        ):
            raise RuntimeError("bullet_create_fireball allocator validation failed")
        fireball_required = (
            b"\x89\x7E\x30",
            b"\x66\xC7\x46\x35\x02\x00",
            b"\xC6\x46\x34\x02",
            b"\xB0\x28\xEB\x09",
            b"\x88\x46\x37",
            b"\x8B\x97\x88\x00\x00\x00\x89\x56\x2C",
            b"\x66\x8B\x8F\x84\x00\x00\x00",
            b"\x66\x8B\x87\x86\x00\x00\x00",
        )
        if not all(pattern in fireball_create_body for pattern in fireball_required):
            raise RuntimeError("bullet_create_fireball record/target validation failed")
        fireball_cost = self.pm.read_ushort(
            self.base + CASTING_COST_TABLE_RVA + SPELL_FIREBALL * 2
        )
        if fireball_cost != 100:
            raise RuntimeError(f"Fireball native mana cost disagrees: {fireball_cost}")

        action_slow = self._resolve_unique_signature(
            ACTION_SLOW_SIGNATURE,
            "action_slow",
            0x90,
            (
                b"\x0F\xB7\x14\x45"
                + struct.pack("<I", self.base + CASTING_COST_TABLE_RVA),
                b"\xBA\x18\xFC\xFF\xFF",
                b"\x0F\xB7\x4F\x4A",
                b"\x66\x89\x57\x4A",
                b"\x66\x89\x57\x4A\xE8",
                b"\x6A\x0C\x57\xE8",
            ),
        )
        slow_body = self.pm.read_bytes(action_slow, 0x90)
        for call_offset, branch_name in ((0x31, "rejected"), (0x4F, "accepted")):
            if self._decode_rel32_call(
                action_slow,
                slow_body,
                call_offset,
                f"action_slow {branch_name} unit_set_next_action",
            ) != next_action:
                raise RuntimeError(f"action_slow {branch_name} guard path disagrees")
        slow_sparkle = self._decode_rel32_call(
            action_slow, slow_body, 0x79, "action_slow bullet_create_on"
        )
        slow_sound = self._decode_rel32_call(
            action_slow, slow_body, 0x81, "action_slow gamesnd_spell"
        )
        slow_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_SLOW * 4
        )
        if slow_dispatch != action_slow:
            raise RuntimeError(
                f"Slow action-dispatch table disagrees: 0x{slow_dispatch:08X}"
            )
        slow_cost = self.pm.read_ushort(
            self.base + CASTING_COST_TABLE_RVA + SPELL_SLOW * 2
        )
        if slow_cost != 50:
            raise RuntimeError(f"Slow native mana cost disagrees: {slow_cost}")

        action_flame_shield = self._resolve_unique_signature(
            ACTION_FLAME_SHIELD_SIGNATURE,
            "action_fireshield",
            0x80,
            (
                b"\x66\x39\x47\x4E",
                b"\xB8\xF4\x01\x00\x00",
                b"\x66\x89\x47\x4E",
                b"\x6A\x04\x57\xE8",
            ),
        )
        flame_body = self.pm.read_bytes(action_flame_shield, 0x80)
        for call_offset, branch_name in ((0x1B, "accepted"), (0x71, "target-gone")):
            if self._decode_rel32_call(
                action_flame_shield,
                flame_body,
                call_offset,
                f"action_fireshield {branch_name} unit_set_next_action",
            ) != next_action:
                raise RuntimeError(
                    f"action_fireshield {branch_name} guard path disagrees"
                )
        flame_pay_cost = self._decode_rel32_call(
            action_flame_shield,
            flame_body,
            0x44,
            "action_fireshield spell_pay_cost",
        )
        pay_body = self.pm.read_bytes(flame_pay_cost, 0x40)
        if (
            b"\x0F\xB7\x1C\x45"
            + struct.pack("<I", self.base + CASTING_COST_TABLE_RVA)
            not in pay_body
            or self._decode_rel32_call(
                flame_pay_cost,
                pay_body,
                0x21,
                "spell_pay_cost unit_set_next_action",
            ) != next_action
        ):
            raise RuntimeError("spell_pay_cost source contract validation failed")
        bullet_create_flame_shield = self._decode_rel32_call(
            action_flame_shield,
            flame_body,
            0x5A,
            "action_fireshield bullet_create_fireshield",
        )
        flame_sound = self._decode_rel32_call(
            action_flame_shield,
            flame_body,
            0x62,
            "action_fireshield gamesnd_spell",
        )
        flame_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_FLAME_SHIELD * 4
        )
        if flame_dispatch != action_flame_shield:
            raise RuntimeError(
                f"Flame Shield action-dispatch table disagrees: 0x{flame_dispatch:08X}"
            )
        flame_create_body = self.pm.read_bytes(bullet_create_flame_shield, 0x10C)
        if (
            flame_create_body[:4] != b"\x55\x8B\xEC\xA1"
            or struct.unpack_from("<I", flame_create_body, 4)[0]
            != self.base + MAX_BULLETS_RVA
            or flame_create_body[9:11] != b"\x8B\x35"
            or struct.unpack_from("<I", flame_create_body, 0x0B)[0]
            != self.base + BULLET_ARRAY_RVA
        ):
            raise RuntimeError("bullet_create_fireshield allocator validation failed")
        flame_required = (
            b"\x89\x7E\x30",
            b"\x66\xC7\x46\x34\x03\x02",
            b"\x88\x46\x0A\xC6\x46\x09\x00",
            b"\x66\x89\x46\x24",
            b"\x66\x89\x46\x26",
        )
        if not all(pattern in flame_create_body for pattern in flame_required):
            raise RuntimeError("bullet_create_fireshield record/path validation failed")
        flame_shield_cost = self.pm.read_ushort(
            self.base + CASTING_COST_TABLE_RVA + SPELL_FLAME_SHIELD * 2
        )
        if flame_shield_cost != 80:
            raise RuntimeError(
                f"Flame Shield native mana cost disagrees: {flame_shield_cost}"
            )

        action_invis = self._resolve_unique_signature(
            ACTION_INVIS_SIGNATURE,
            "action_invis",
            0x80,
            (
                b"\xB8\xD0\x07\x00\x00",
                b"\x66\x89\x47\x44",
                b"\x6A\x16\x57\x66\x89\x47\x44\xE8",
                b"\x6A\x09\x57\xE8",
            ),
        )
        invis_body = self.pm.read_bytes(action_invis, 0x80)
        for call_offset, branch_name in ((0x31, "rejected"), (0x4F, "accepted")):
            if self._decode_rel32_call(
                action_invis,
                invis_body,
                call_offset,
                f"action_invis {branch_name} unit_set_next_action",
            ) != next_action:
                raise RuntimeError(f"action_invis {branch_name} guard path disagrees")
        invis_sparkle = self._decode_rel32_call(
            action_invis, invis_body, 0x66, "action_invis bullet_create_on"
        )
        invis_sound = self._decode_rel32_call(
            action_invis, invis_body, 0x6E, "action_invis gamesnd_spell"
        )
        if invis_sparkle != slow_sparkle or invis_sound != slow_sound:
            raise RuntimeError("Invisibility Sparkle/sound helpers disagree with Slow")
        invis_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_INVIS * 4
        )
        if invis_dispatch != action_invis:
            raise RuntimeError(
                f"Invisibility action-dispatch table disagrees: 0x{invis_dispatch:08X}"
            )
        invis_cost = self.pm.read_ushort(
            self.base + CASTING_COST_TABLE_RVA + SPELL_INVIS * 2
        )
        if invis_cost != 200:
            raise RuntimeError(f"Invisibility native mana cost disagrees: {invis_cost}")

        action_polymorph = self._resolve_unique_signature(
            ACTION_POLYMORPH_SIGNATURE,
            "action_polymorph",
            0xB0,
            (
                b"\x66\x83\x4B\x1E\x08",
                b"\x80\x4B\x06\x20",
                b"\x6A\x0F\x6A\x39",
                b"\x6A\x16",
            ),
        )
        polymorph_body = self.pm.read_bytes(action_polymorph, 0xB0)
        for call_offset, branch_name in ((0x31, "rejected"), (0x50, "accepted")):
            if self._decode_rel32_call(
                action_polymorph,
                polymorph_body,
                call_offset,
                f"action_polymorph {branch_name} unit_set_next_action",
            ) != next_action:
                raise RuntimeError(
                    f"action_polymorph {branch_name} guard path disagrees"
                )
        polymorph_sound = self._decode_rel32_call(
            action_polymorph,
            polymorph_body,
            0x5E,
            "action_polymorph gamesnd_spell",
        )
        polymorph_unit_kill = self._decode_rel32_call(
            action_polymorph,
            polymorph_body,
            0x75,
            "action_polymorph unit_kill",
        )
        polymorph_unit_create = self._decode_rel32_call(
            action_polymorph,
            polymorph_body,
            0x86,
            "action_polymorph unit_create",
        )
        polymorph_visual = self._decode_rel32_call(
            action_polymorph,
            polymorph_body,
            0x95,
            "action_polymorph bullet_create_xy",
        )
        if polymorph_sound != slow_sound:
            raise RuntimeError("Polymorph spell-sound helper disagrees with Slow")
        if polymorph_unit_kill != self.damage_callees["unit_kill"]:
            raise RuntimeError("Polymorph unit_kill helper disagrees with Damage Units")
        if polymorph_unit_create != self.unit_create_address:
            raise RuntimeError("Polymorph unit_create helper disagrees with Create Units")
        if polymorph_visual != self.bullet_path["bullet_create_xy"]:
            raise RuntimeError("Polymorph Sparkle helper disagrees with projectile path")
        polymorph_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_POLYMORPH * 4
        )
        if polymorph_dispatch != action_polymorph:
            raise RuntimeError(
                f"Polymorph action-dispatch table disagrees: 0x{polymorph_dispatch:08X}"
            )
        polymorph_cost = self.pm.read_ushort(
            self.base + CASTING_COST_TABLE_RVA + SPELL_POLYMORPH * 2
        )
        if polymorph_cost != 200:
            raise RuntimeError(f"Polymorph native mana cost disagrees: {polymorph_cost}")

        dispatch_spell_fleshy = self.pm.read_uint(
            self.base + UNIT_ACTION_USER_DISPATCH_TABLE_RVA + SPELL_HEAL * 4
        )
        fleshy_body = self.pm.read_bytes(dispatch_spell_fleshy, 0x68)
        if (
            fleshy_body[:16]
            != b"\x55\x8B\xEC\x56\x8B\x75\x08\x8B\x86\x88\x00\x00\x00\x85\xC0\x74"
            or b"\xF7\x04\x85"
            + struct.pack("<I", self.base + UNIT_IS_TABLE_RVA)
            + struct.pack("<I", IS_FLESHY)
            not in fleshy_body
        ):
            raise RuntimeError("dispatch_spell_fleshy source contract validation failed")

        bloodlust_user_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_USER_DISPATCH_TABLE_RVA + SPELL_BLOODLUST * 4
        )
        if bloodlust_user_dispatch != dispatch_spell_fleshy:
            raise RuntimeError(
                "Bloodlust user-target dispatcher disagrees with the validated "
                "fleshy-target path"
            )
        action_bloodlust = self._resolve_unique_signature(
            ACTION_BLOODLUST_SIGNATURE,
            "action_bloodlust",
            0x7A,
            (
                b"\xB8\xEE\x02\x00\x00",
                b"\x66\x89\x47\x48",
                b"\x6A\x16\x57\x66\x89\x47\x48\xE8",
                b"\x6A\x00\x57\xE8",
            ),
        )
        bloodlust_body = self.pm.read_bytes(action_bloodlust, 0x7A)
        for call_offset, branch_name in ((0x31, "rejected"), (0x4F, "accepted")):
            if self._decode_rel32_call(
                action_bloodlust,
                bloodlust_body,
                call_offset,
                f"action_bloodlust {branch_name} unit_set_next_action",
            ) != next_action:
                raise RuntimeError(
                    f"action_bloodlust {branch_name} guard path disagrees"
                )
        bloodlust_sparkle = self._decode_rel32_call(
            action_bloodlust,
            bloodlust_body,
            0x66,
            "action_bloodlust bullet_create_on",
        )
        bloodlust_sound = self._decode_rel32_call(
            action_bloodlust,
            bloodlust_body,
            0x6E,
            "action_bloodlust gamesnd_spell",
        )
        if bloodlust_sparkle != slow_sparkle or bloodlust_sound != slow_sound:
            raise RuntimeError("Bloodlust Sparkle/sound helpers disagree with Slow")
        bloodlust_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_BLOODLUST * 4
        )
        if bloodlust_dispatch != action_bloodlust:
            raise RuntimeError(
                f"Bloodlust action-dispatch table disagrees: 0x{bloodlust_dispatch:08X}"
            )
        bloodlust_cost = self.pm.read_ushort(
            self.base + CASTING_COST_TABLE_RVA + SPELL_BLOODLUST * 2
        )
        if bloodlust_cost != 60:
            raise RuntimeError(
                f"Bloodlust Remastered mana cost disagrees: {bloodlust_cost}"
            )

        action_heal = self._resolve_unique_signature(
            ACTION_HEAL_SIGNATURE,
            "action_heal",
            0xCC,
            (
                b"\xB8\x28\x00\x00\x00",
                b"\x66\x89\x47\x22",
                b"\x6A\x09\x57\x28\x4E\x26\xE8",
                b"\x6A\x06\x57\xE8",
            ),
        )
        heal_body = self.pm.read_bytes(action_heal, 0xCC)
        for call_offset, branch_name in ((0x25, "accepted"), (0xBF, "target-gone")):
            if self._decode_rel32_call(
                action_heal,
                heal_body,
                call_offset,
                f"action_heal {branch_name} unit_set_next_action",
            ) != next_action:
                raise RuntimeError(f"action_heal {branch_name} guard path disagrees")
        heal_hp_max = self._decode_rel32_call(
            action_heal, heal_body, 0x3B, "action_heal unit_hp_tbl"
        )
        hp_body = self.pm.read_bytes(heal_hp_max, 0x20)
        if (
            hp_body[:10] != b"\x55\x8B\xEC\x8B\x45\x08\x0F\xB6\x40\x27"
            or hp_body[0x0A:0x0E] != b"\x0F\xB7\x14\x45"
            or struct.unpack_from("<I", hp_body, 0x0E)[0]
            != self.base + UNIT_HP_TABLE_RVA
        ):
            raise RuntimeError("action_heal unit_hp_tbl source contract validation failed")
        heal_cost_address = self.base + CASTING_COST_TABLE_RVA + SPELL_HEAL * 2
        if (
            heal_body[0x57:0x5A] != b"\x0F\xB7\x0D"
            or struct.unpack_from("<I", heal_body, 0x5A)[0] != heal_cost_address
            or heal_body[0x95:0x98] != b"\x0F\xB6\x05"
            or struct.unpack_from("<I", heal_body, 0x98)[0] != heal_cost_address
        ):
            raise RuntimeError("action_heal casting-cost operands disagree")
        heal_visual = self._decode_rel32_call(
            action_heal, heal_body, 0xA5, "action_heal bullet_create_on"
        )
        heal_sound = self._decode_rel32_call(
            action_heal, heal_body, 0xAD, "action_heal gamesnd_spell"
        )
        if heal_visual != slow_sparkle or heal_sound != slow_sound:
            raise RuntimeError("Heal visual/sound helpers disagree with validated spell paths")
        heal_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_HEAL * 4
        )
        if heal_dispatch != action_heal:
            raise RuntimeError(
                f"Heal action-dispatch table disagrees: 0x{heal_dispatch:08X}"
            )
        heal_cost = self.pm.read_ushort(heal_cost_address)
        if heal_cost != 5:
            raise RuntimeError(f"Heal native per-HP mana cost disagrees: {heal_cost}")

        action_exorcism = self._resolve_unique_signature(
            ACTION_EXORCISM_SIGNATURE,
            "action_exorcism",
            0x180,
            (
                b"\x66\x3B\x0D"
                + struct.pack(
                    "<I", self.base + CASTING_COST_TABLE_RVA + SPELL_EXORCISM * 2
                ),
                b"\xA1" + struct.pack("<I", self.base + UNIT_MAP_RVA),
                b"\x83\xFF\xFD",
            ),
        )
        exorcism_body = self.pm.read_bytes(action_exorcism, 0x180)
        if self._decode_rel32_call(
            action_exorcism,
            exorcism_body,
            0x23,
            "action_exorcism unit_set_next_action",
        ) != next_action:
            raise RuntimeError("action_exorcism guard path disagrees")
        exorcism_hit = self._decode_rel32_call(
            action_exorcism, exorcism_body, 0xA0, "action_exorcism exorcism helper"
        )
        for call_offset in (0xC6, 0x110, 0x13B):
            if self._decode_rel32_call(
                action_exorcism,
                exorcism_body,
                call_offset,
                "action_exorcism repeated exorcism helper",
            ) != exorcism_hit:
                raise RuntimeError("action_exorcism scan helpers disagree")
        exorcism_hit_body = self.pm.read_bytes(exorcism_hit, 0xA2)
        undead_pattern = (
            b"\xF7\x04\x85"
            + struct.pack("<I", self.base + UNIT_IS_TABLE_RVA)
            + struct.pack("<I", IS_UNDEAD)
        )
        exorcism_cost_address = (
            self.base + CASTING_COST_TABLE_RVA + SPELL_EXORCISM * 2
        )
        if (
            exorcism_hit_body[:15]
            != b"\x55\x8B\xEC\x56\x8B\x75\x0C\x85\xF6\x0F\x84\x90\x00\x00\x00"
            or undead_pattern not in exorcism_hit_body
            or b"\x0F\xB7\x0D" + struct.pack("<I", exorcism_cost_address)
            not in exorcism_hit_body
            or b"\x0F\xB6\x05" + struct.pack("<I", exorcism_cost_address)
            not in exorcism_hit_body
        ):
            raise RuntimeError("exorcism helper source contract validation failed")
        exorcism_visual = self._decode_rel32_call(
            exorcism_hit, exorcism_hit_body, 0x64, "exorcism bullet_create_on"
        )
        exorcism_sound = self._decode_rel32_call(
            exorcism_hit, exorcism_hit_body, 0x6C, "exorcism gamesnd_spell"
        )
        exorcism_damage = self._decode_rel32_call(
            exorcism_hit, exorcism_hit_body, 0x85, "exorcism damage_damage_unit"
        )
        if exorcism_visual != slow_sparkle or exorcism_sound != slow_sound:
            raise RuntimeError("Exorcism visual/sound helpers disagree with validated spell paths")
        if exorcism_damage != self.damage_unit_address:
            raise RuntimeError("Exorcism damage helper disagrees with Damage Units")
        exorcism_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_EXORCISM * 4
        )
        if exorcism_dispatch != action_exorcism:
            raise RuntimeError(
                f"Exorcism action-dispatch table disagrees: 0x{exorcism_dispatch:08X}"
            )
        exorcism_cost = self.pm.read_ushort(exorcism_cost_address)
        if exorcism_cost != 4:
            raise RuntimeError(
                f"Exorcism native per-damage mana cost disagrees: {exorcism_cost}"
            )

        raisedead_cost_address = (
            self.base + CASTING_COST_TABLE_RVA + SPELL_RAISEDEAD * 2
        )
        action_raisedead = self._resolve_unique_signature(
            ACTION_RAISEDEAD_SIGNATURE,
            "action_raisedead",
            0x109,
            (
                b"\x8B\x1D" + struct.pack("<I", self.base + MAX_UNITS_RVA),
                b"\x8B\x35" + struct.pack("<I", self.base + UNIT_ARRAY_RVA),
                b"\x66\x3B\x05" + struct.pack("<I", raisedead_cost_address),
                b"\x80\x7E\x09\x69",
                b"\x8A\x06\x24\x0F\x3C\x02",
                b"\x83\xF9\x24",
                b"\x6A\x37",
                b"\x66\x83\x0E\x08",
                b"\x81\xC6\x98\x00\x00\x00",
            ),
        )
        raisedead_body = self.pm.read_bytes(action_raisedead, 0x109)
        if self._decode_rel32_call(
            action_raisedead,
            raisedead_body,
            0x0F,
            "action_raisedead unit_set_next_action",
        ) != next_action:
            raise RuntimeError("action_raisedead guard path disagrees")
        raisedead_create = self._decode_rel32_call(
            action_raisedead, raisedead_body, 0xB2, "action_raisedead unit_create"
        )
        raisedead_sparkle = self._decode_rel32_call(
            action_raisedead,
            raisedead_body,
            0xC1,
            "action_raisedead bullet_create_on",
        )
        raisedead_sound = self._decode_rel32_call(
            action_raisedead, raisedead_body, 0xE0, "action_raisedead sound"
        )
        if raisedead_create != self.unit_create_address:
            raise RuntimeError("Raise Dead allocator disagrees with Create Units")
        if raisedead_sparkle != slow_sparkle:
            raise RuntimeError("Raise Dead Sparkle helper disagrees with Slow")
        raisedead_sound_body = self.pm.read_bytes(raisedead_sound, 0xD8)
        if (
            raisedead_sound_body[:10]
            != b"\x55\x8B\xEC\x57\x8B\x7D\x08\x66\x85\xFF"
            or b"\x81\xC7\xFF\xFF\x00\x00" not in raisedead_sound_body
            or b"\x66\x8B\x15" + struct.pack("<I", self.base + MAP_DIMENSION_RVA)
            not in raisedead_sound_body
        ):
            raise RuntimeError("Raise Dead positional sound source contract failed")
        raisedead_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_RAISEDEAD * 4
        )
        if raisedead_dispatch != action_raisedead:
            raise RuntimeError(
                f"Raise Dead action-dispatch table disagrees: 0x{raisedead_dispatch:08X}"
            )
        raisedead_cost = self.pm.read_ushort(raisedead_cost_address)
        if raisedead_cost != 50:
            raise RuntimeError(
                f"Raise Dead native per-corpse mana cost disagrees: {raisedead_cost}"
            )

        runes_cost_address = (
            self.base + CASTING_COST_TABLE_RVA + SPELL_RUNES * 2
        )
        action_runes = self._resolve_unique_signature(
            ACTION_RUNES_SIGNATURE,
            "action_runes",
            0xE6,
            (
                b"\x0F\xB7\x0D" + struct.pack("<I", runes_cost_address),
                b"\xB8\xCD\xCC\xCC\xCC\xF7\xE1\xB0\x05\x2A\xC3",
                b"\x68\x5D\x01\x00\x00",
            ),
        )
        runes_body = self.pm.read_bytes(action_runes, 0xE6)
        for call_offset, branch_name in ((0x24, "insufficient-mana"), (0x3B, "accepted")):
            if self._decode_rel32_call(
                action_runes,
                runes_body,
                call_offset,
                f"action_runes {branch_name} unit_set_next_action",
            ) != next_action:
                raise RuntimeError(f"action_runes {branch_name} guard path disagrees")
        for call_offset in (0x62, 0x6E, 0x7A, 0x86, 0x92):
            if self._decode_rel32_call(
                action_runes,
                runes_body,
                call_offset,
                "action_runes place_a_rune",
            ) != place_rune:
                raise RuntimeError("Runes placement helpers disagree with place_a_rune")
        if (
            runes_body[0x97:0x9A] != b"\x0F\xB7\x0D"
            or struct.unpack_from("<I", runes_body, 0x9A)[0]
            != runes_cost_address
        ):
            raise RuntimeError("Runes failed-placement refund cost operand disagrees")
        runes_sound = self._decode_rel32_call(
            action_runes,
            runes_body,
            0xD7,
            "action_runes positional sound",
        )
        if runes_sound != raisedead_sound:
            raise RuntimeError(
                "Runes positional sound helper disagrees with Raise Dead"
            )
        runes_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_RUNES * 4
        )
        if runes_dispatch != action_runes:
            raise RuntimeError(
                f"Runes action-dispatch table disagrees: 0x{runes_dispatch:08X}"
            )
        runes_cost = self.pm.read_ushort(runes_cost_address)
        if runes_cost != 200:
            raise RuntimeError(f"Runes native mana cost disagrees: {runes_cost}")

        action_drainlife = self._resolve_unique_signature(
            ACTION_DRAINLIFE_SIGNATURE,
            "action_drainlife",
            0x422,
            (
                b"\xA1" + struct.pack("<I", self.base + UNIT_MAP_RVA),
                b"\x8B\x0D" + struct.pack("<I", self.base + AIR_UNIT_MAP_RVA),
                b"\xF7\x04\x85"
                + struct.pack("<I", self.base + UNIT_IS_TABLE_RVA)
                + struct.pack("<I", IS_FLESHY),
                b"\x83\xF8\x32",
                b"\xBB\x32\x00\x00\x00",
            ),
        )
        drainlife_body = self.pm.read_bytes(action_drainlife, 0x422)
        for call_offset, branch_name in ((0x40, "rejected"), (0x5D, "accepted")):
            if self._decode_rel32_call(
                action_drainlife,
                drainlife_body,
                call_offset,
                f"action_drainlife {branch_name} unit_set_next_action",
            ) != next_action:
                raise RuntimeError(
                    f"action_drainlife {branch_name} guard path disagrees"
                )
        drainlife_bullet = self._decode_rel32_call(
            action_drainlife,
            drainlife_body,
            0x3A5,
            "action_drainlife bullet_create",
        )
        drainlife_sound = self._decode_rel32_call(
            action_drainlife,
            drainlife_body,
            0x3B4,
            "action_drainlife gamesnd_spell",
        )
        drainlife_hp_max = self._decode_rel32_call(
            action_drainlife,
            drainlife_body,
            0x3D7,
            "action_drainlife unit_hp_tbl",
        )
        if self._decode_rel32_call(
            action_drainlife,
            drainlife_body,
            0x3EF,
            "action_drainlife repeated unit_hp_tbl",
        ) != drainlife_hp_max:
            raise RuntimeError("action_drainlife maximum-HP helpers disagree")
        if drainlife_bullet != self.bullet_path["bullet_create"]:
            raise RuntimeError("Death Coil projectile helper disagrees with bullet_create")
        if drainlife_sound != slow_sound:
            raise RuntimeError("Death Coil sound helper disagrees with validated spell path")
        if drainlife_hp_max != heal_hp_max:
            raise RuntimeError("Death Coil maximum-HP helper disagrees with Healing")
        drainlife_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_DRAINLIFE * 4
        )
        if drainlife_dispatch != action_drainlife:
            raise RuntimeError(
                f"Death Coil action-dispatch table disagrees: 0x{drainlife_dispatch:08X}"
            )
        drainlife_cost = self.pm.read_ushort(
            self.base + CASTING_COST_TABLE_RVA + SPELL_DRAINLIFE * 2
        )
        if drainlife_cost != 100:
            raise RuntimeError(f"Death Coil native mana cost disagrees: {drainlife_cost}")

        action_whirlwind = self._resolve_unique_signature(
            ACTION_WHIRLWIND_SIGNATURE,
            "action_whirlwind",
            0x50,
            (
                b"\x0F\xB7\x14\x45"
                + struct.pack("<I", self.base + CASTING_COST_TABLE_RVA),
                b"\x33\xC0\x56\x66\x89\x46\x44\xE8",
                b"\x6A\x10\x56\xE8",
            ),
        )
        whirlwind_body = self.pm.read_bytes(action_whirlwind, 0x50)
        for call_offset, branch_name in ((0x21, "insufficient-mana"), (0x31, "accepted")):
            if self._decode_rel32_call(
                action_whirlwind,
                whirlwind_body,
                call_offset,
                f"action_whirlwind {branch_name} unit_set_next_action",
            ) != next_action:
                raise RuntimeError(
                    f"action_whirlwind {branch_name} guard path disagrees"
                )
        bullet_create_typhoon = self._decode_rel32_call(
            action_whirlwind,
            whirlwind_body,
            0x3D,
            "action_whirlwind bullet_create_typhoon",
        )
        whirlwind_sound = self._decode_rel32_call(
            action_whirlwind,
            whirlwind_body,
            0x45,
            "action_whirlwind gamesnd_spell",
        )
        if whirlwind_sound != slow_sound:
            raise RuntimeError("Whirlwind sound helper disagrees with validated spell path")
        typhoon_body = self.pm.read_bytes(bullet_create_typhoon, 0x160)
        typhoon_required = (
            b"\x89\x7E\x30",
            b"\x66\xC7\x46\x35\x02\x00",
            b"\xC6\x46\x34\x0C",
            b"\xC6\x46\x37\x04",
            b"\x89\x56\x2C",
        )
        if (
            typhoon_body[:13]
            != b"\x55\x8B\xEC\x57\x8B\x7D\x08\x3B\xBF\x88\x00\x00\x00"
            or b"\xA1" + struct.pack("<I", self.base + MAX_BULLETS_RVA)
            not in typhoon_body
            or b"\x8B\x35" + struct.pack("<I", self.base + BULLET_ARRAY_RVA)
            not in typhoon_body
            or not all(pattern in typhoon_body for pattern in typhoon_required)
        ):
            raise RuntimeError("bullet_create_typhoon source/record contract validation failed")
        whirlwind_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_WHIRLWIND * 4
        )
        if whirlwind_dispatch != action_whirlwind:
            raise RuntimeError(
                f"Whirlwind action-dispatch table disagrees: 0x{whirlwind_dispatch:08X}"
            )
        whirlwind_cost = self.pm.read_ushort(
            self.base + CASTING_COST_TABLE_RVA + SPELL_WHIRLWIND * 2
        )
        if whirlwind_cost != 100:
            raise RuntimeError(
                f"Whirlwind native mana cost disagrees: {whirlwind_cost}"
            )

        action_rot = self._resolve_unique_signature(
            ACTION_ROT_SIGNATURE,
            "action_rot",
            0x70,
            (
                b"\x0F\xB7\x14\x45"
                + struct.pack("<I", self.base + CASTING_COST_TABLE_RVA),
                b"\x6A\x01\x56\x88\x4E\x26\xE8",
                b"\x83\xC4\x30\x33\xC0\x66\x89\x46\x44",
            ),
        )
        rot_body = self.pm.read_bytes(action_rot, 0x70)
        if self._decode_rel32_call(
            action_rot,
            rot_body,
            0x21,
            "action_rot insufficient-mana unit_set_next_action",
        ) != next_action:
            raise RuntimeError("action_rot insufficient-mana guard path disagrees")
        rot_sound = self._decode_rel32_call(
            action_rot, rot_body, 0x34, "action_rot gamesnd_spell"
        )
        if rot_sound != slow_sound:
            raise RuntimeError(
                "Death and Decay sound helper disagrees with validated spell path"
            )
        bullet_create_rot = self._decode_rel32_call(
            action_rot, rot_body, 0x3C, "action_rot bullet_create_rot"
        )
        for call_offset in (0x44, 0x4C, 0x54, 0x5C):
            if self._decode_rel32_call(
                action_rot,
                rot_body,
                call_offset,
                "action_rot repeated bullet_create_rot",
            ) != bullet_create_rot:
                raise RuntimeError("Death and Decay constructors disagree")
        rot_create_body = self.pm.read_bytes(bullet_create_rot, 0xB7)
        rot_required = (
            b"\x89\x4E\x30",
            b"\x66\xC7\x46\x34\x06\x02",
            b"\xC6\x46\x37\x0A",
            b"\x66\x89\x46\x38",
            b"\xC7\x46\x2C\x00\x00\x00\x00",
        )
        if (
            rot_create_body[:4] != b"\x55\x8B\xEC\xA1"
            or struct.unpack_from("<I", rot_create_body, 4)[0]
            != self.base + MAX_BULLETS_RVA
            or rot_create_body[8:10] != b"\x56\x8B"
            or b"\x8B\x35" + struct.pack("<I", self.base + BULLET_ARRAY_RVA)
            not in rot_create_body
            or not all(pattern in rot_create_body for pattern in rot_required)
        ):
            raise RuntimeError("bullet_create_rot source/record contract validation failed")
        rot_set_target = self._decode_rel32_call(
            bullet_create_rot,
            rot_create_body,
            0x5E,
            "bullet_create_rot bullet_set_target",
        )
        rot_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_ROT * 4
        )
        if rot_dispatch != action_rot:
            raise RuntimeError(
                f"Death and Decay action-dispatch table disagrees: 0x{rot_dispatch:08X}"
            )
        rot_cost = self.pm.read_ushort(
            self.base + CASTING_COST_TABLE_RVA + SPELL_ROT * 2
        )
        if rot_cost != 30:
            raise RuntimeError(
                f"Death and Decay Remastered mana cost disagrees: {rot_cost}"
            )

        action_haste = self._resolve_unique_signature(
            ACTION_HASTE_SIGNATURE,
            "action_haste",
            0x90,
            (
                b"\xBA\xE8\x03\x00\x00",
                b"\x8D\x81\xE8\x03\x00\x00",
                b"\x66\x89\x57\x4A",
                b"\x6A\x16\x57\x8D",
                b"\x6A\x05\x57\xE8",
            ),
        )
        haste_body = self.pm.read_bytes(action_haste, 0x90)
        for call_offset, branch_name in ((0x31, "rejected"), (0x4F, "accepted")):
            if self._decode_rel32_call(
                action_haste,
                haste_body,
                call_offset,
                f"action_haste {branch_name} unit_set_next_action",
            ) != next_action:
                raise RuntimeError(f"action_haste {branch_name} guard path disagrees")
        haste_sparkle = self._decode_rel32_call(
            action_haste, haste_body, 0x79, "action_haste bullet_create_on"
        )
        haste_sound = self._decode_rel32_call(
            action_haste, haste_body, 0x81, "action_haste gamesnd_spell"
        )
        if haste_sparkle != slow_sparkle or haste_sound != slow_sound:
            raise RuntimeError("Haste Sparkle/sound helpers disagree with Slow")
        haste_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_HASTE * 4
        )
        if haste_dispatch != action_haste:
            raise RuntimeError(
                f"Haste action-dispatch table disagrees: 0x{haste_dispatch:08X}"
            )
        haste_cost = self.pm.read_ushort(
            self.base + CASTING_COST_TABLE_RVA + SPELL_HASTE * 2
        )
        if haste_cost != 50:
            raise RuntimeError(f"Haste native mana cost disagrees: {haste_cost}")

        action_armor = self._resolve_unique_signature(
            ACTION_ARMOR_SIGNATURE,
            "action_armor",
            0x90,
            (
                b"\xB8\xF4\x01\x00\x00",
                b"\x66\x89\x47\x46",
                b"\x0F\xB7\x47\x22\x83\xF8\x02",
                b"\x66\xD1\xE8\x66\x89\x47\x22",
                b"\x6A\x16\x57\xE8",
                b"\x6A\x0F\x57\xE8",
            ),
        )
        armor_body = self.pm.read_bytes(action_armor, 0x90)
        for call_offset, branch_name in ((0x31, "rejected"), (0x4F, "accepted")):
            if self._decode_rel32_call(
                action_armor,
                armor_body,
                call_offset,
                f"action_armor {branch_name} unit_set_next_action",
            ) != next_action:
                raise RuntimeError(f"action_armor {branch_name} guard path disagrees")
        armor_sparkle = self._decode_rel32_call(
            action_armor, armor_body, 0x79, "action_armor bullet_create_on"
        )
        armor_sound = self._decode_rel32_call(
            action_armor, armor_body, 0x81, "action_armor gamesnd_spell"
        )
        if armor_sparkle != slow_sparkle or armor_sound != slow_sound:
            raise RuntimeError("Unholy Armor Sparkle/sound helpers disagree with Slow")
        armor_dispatch = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_ARMOR * 4
        )
        if armor_dispatch != action_armor:
            raise RuntimeError(
                f"Unholy Armor action-dispatch table disagrees: 0x{armor_dispatch:08X}"
            )
        armor_cost = self.pm.read_ushort(
            self.base + CASTING_COST_TABLE_RVA + SPELL_ARMOR * 2
        )
        if armor_cost != 100:
            raise RuntimeError(
                f"Unholy Armor native mana cost disagrees: {armor_cost}"
            )

        action_blizzard = self._resolve_unique_signature(
            ACTION_BLIZZARD_SIGNATURE,
            "action_blizzard",
            0x70,
            (
                b"\x2A\xCA\x6A\x08\x56\x88\x4E\x26",
                b"\x6A\x0A\x56\xE8",
                b"\x83\xC4\x30\x33\xC0\x66\x89\x46\x44",
            ),
        )
        blizzard_body = self.pm.read_bytes(action_blizzard, 0x70)
        if blizzard_body[0x0E:0x12] != b"\x0F\xB7\x14\x45":
            raise RuntimeError("action_blizzard casting-cost instruction validation failed")
        cost_table = struct.unpack_from("<I", blizzard_body, 0x12)[0]
        if cost_table != self.base + CASTING_COST_TABLE_RVA:
            raise RuntimeError(
                f"action_blizzard casting-cost table disagrees: 0x{cost_table:08X}"
            )
        bullet_create_blizzard = self._decode_rel32_call(
            action_blizzard, blizzard_body, 0x3C, "action_blizzard bullet_create_blizzard"
        )
        for call_offset in (0x44, 0x4C, 0x54, 0x5C):
            target = self._decode_rel32_call(
                action_blizzard,
                blizzard_body,
                call_offset,
                "action_blizzard repeated bullet_create_blizzard",
            )
            if target != bullet_create_blizzard:
                raise RuntimeError("action_blizzard shard constructors disagree")
        dispatch_function = self.pm.read_uint(
            self.base + UNIT_ACTION_DISPATCH_TABLE_RVA + SPELL_BLIZZARD * 4
        )
        if dispatch_function != action_blizzard:
            raise RuntimeError(
                f"Blizzard action-dispatch table disagrees: 0x{dispatch_function:08X}"
            )

        blizzard_create_body = self.pm.read_bytes(bullet_create_blizzard, 0xD3)
        if (
            blizzard_create_body[:5] != b"\x55\x8B\xEC\x51\xA1"
            or struct.unpack_from("<I", blizzard_create_body, 5)[0]
            != self.base + MAX_BULLETS_RVA
            or blizzard_create_body[9:11] != b"\x8B\x0D"
            or struct.unpack_from("<I", blizzard_create_body, 0x0B)[0]
            != self.base + BULLET_ARRAY_RVA
            or b"\x0F\xBF\xB8\x84\x00\x00\x00" not in blizzard_create_body
            or b"\x0F\xB7\x98\x86\x00\x00\x00" not in blizzard_create_body
        ):
            raise RuntimeError("bullet_create_blizzard allocator/target validation failed")
        blizzard_shards = self._decode_rel32_call(
            bullet_create_blizzard,
            blizzard_create_body,
            0x84,
            "bullet_create_blizzard blizzard_shards",
        )
        shard_body = self.pm.read_bytes(blizzard_shards, 0x70)
        shard_required = (
            b"\x89\x47\x30",
            b"\x66\x89\x47\x38",
            b"\xC6\x47\x34\x05",
            b"\xC6\x47\x37\x0A",
            b"\x66\x89\x4F\x2A",
        )
        if not all(pattern in shard_body for pattern in shard_required):
            raise RuntimeError("blizzard_shards record contract validation failed")
        blizzard_cost = self.pm.read_ushort(
            self.base + CASTING_COST_TABLE_RVA + SPELL_BLIZZARD * 2
        )
        if blizzard_cost != 25:
            raise RuntimeError(f"Blizzard native mana cost disagrees: {blizzard_cost}")
        return {
            "place_rune": place_rune,
            "do_vision": do_vision,
            "vision_unmask": vision_unmask,
            "vision_set_pos": vision_set_pos,
            "vision_sound": vision_sound,
            "do_unit_spell": do_unit_spell,
            "unit_set_next_action": next_action,
            "action_type_global": self.base + ACTION_TYPE_RVA,
            "action_vision": action_vision,
            "vision_cost": vision_cost,
            "action_eye": action_eye,
            "eye_create_place": eye_create_place,
            "eye_unit_create": eye_unit_create,
            "eye_placement_visual": eye_placement_visual,
            "eye_sound": eye_sound,
            "eye_cost": eye_cost,
            "action_fireball": action_fireball,
            "bullet_create_fireball": bullet_create_fireball,
            "fireball_cost": fireball_cost,
            "action_slow": action_slow,
            "slow_sparkle": slow_sparkle,
            "slow_sound": slow_sound,
            "slow_cost": slow_cost,
            "action_flame_shield": action_flame_shield,
            "flame_pay_cost": flame_pay_cost,
            "bullet_create_flame_shield": bullet_create_flame_shield,
            "flame_sound": flame_sound,
            "flame_shield_cost": flame_shield_cost,
            "action_invis": action_invis,
            "invis_sparkle": invis_sparkle,
            "invis_sound": invis_sound,
            "invis_cost": invis_cost,
            "action_polymorph": action_polymorph,
            "polymorph_sound": polymorph_sound,
            "polymorph_unit_kill": polymorph_unit_kill,
            "polymorph_unit_create": polymorph_unit_create,
            "polymorph_visual": polymorph_visual,
            "polymorph_cost": polymorph_cost,
            "dispatch_spell_fleshy": dispatch_spell_fleshy,
            "action_bloodlust": action_bloodlust,
            "bloodlust_sparkle": bloodlust_sparkle,
            "bloodlust_sound": bloodlust_sound,
            "bloodlust_cost": bloodlust_cost,
            "action_heal": action_heal,
            "heal_hp_max": heal_hp_max,
            "heal_visual": heal_visual,
            "heal_sound": heal_sound,
            "heal_cost": heal_cost,
            "action_exorcism": action_exorcism,
            "exorcism_hit": exorcism_hit,
            "exorcism_visual": exorcism_visual,
            "exorcism_sound": exorcism_sound,
            "exorcism_damage": exorcism_damage,
            "exorcism_cost": exorcism_cost,
            "action_raisedead": action_raisedead,
            "raisedead_create": raisedead_create,
            "raisedead_sparkle": raisedead_sparkle,
            "raisedead_sound": raisedead_sound,
            "raisedead_cost": raisedead_cost,
            "action_runes": action_runes,
            "runes_sound": runes_sound,
            "runes_cost": runes_cost,
            "action_drainlife": action_drainlife,
            "drainlife_bullet": drainlife_bullet,
            "drainlife_sound": drainlife_sound,
            "drainlife_hp_max": drainlife_hp_max,
            "drainlife_cost": drainlife_cost,
            "action_whirlwind": action_whirlwind,
            "bullet_create_typhoon": bullet_create_typhoon,
            "whirlwind_sound": whirlwind_sound,
            "whirlwind_cost": whirlwind_cost,
            "action_rot": action_rot,
            "bullet_create_rot": bullet_create_rot,
            "rot_set_target": rot_set_target,
            "rot_sound": rot_sound,
            "rot_cost": rot_cost,
            "action_haste": action_haste,
            "haste_sparkle": haste_sparkle,
            "haste_sound": haste_sound,
            "haste_cost": haste_cost,
            "action_armor": action_armor,
            "armor_sparkle": armor_sparkle,
            "armor_sound": armor_sound,
            "armor_cost": armor_cost,
            "action_blizzard": action_blizzard,
            "bullet_create_blizzard": bullet_create_blizzard,
            "blizzard_shards": blizzard_shards,
            "blizzard_cost": blizzard_cost,
        }

    @staticmethod
    def _game_speed_index(value: Any) -> int:
        if isinstance(value, int):
            index = int(value)
        else:
            text = str(value).strip()
            if text.isdigit():
                index = int(text)
            else:
                aliases = {name.casefold(): index for index, name in enumerate(GAME_SPEED_LEVELS)}
                try:
                    index = aliases[text.casefold()]
                except KeyError as exc:
                    raise ValueError(
                        f"Unknown game speed {value!r}; use Slowest through Fastest or 0 through 6"
                    ) from exc
        if not 0 <= index < len(GAME_SPEED_LEVELS):
            raise ValueError("Game speed index must be 0 through 6")
        return index

    def _resolve_message_path(self) -> dict[str, int]:
        """Validate Remaster's source-matched PM_STRING and map-message path."""
        packet_send_string = self.base + PACKET_SEND_STRING_RVA
        code = self.pm.read_bytes(packet_send_string, 0xC0)
        if code[:9] != b"\x55\x8B\xEC\x81\xEC\x0C\x01\x00\x00":
            raise RuntimeError("packet_send_string prologue validation failed")
        if code[0x13:0x15] != b"\x8A\x0D":
            raise RuntimeError("packet_send_string message-filter operand is missing")
        filter_address = struct.unpack_from("<I", code, 0x15)[0]
        if filter_address != self.base + CHAT_FILTER_RVA:
            raise RuntimeError(
                f"packet_send_string gbMsgFilter disagrees: 0x{filter_address:08X}"
            )
        if code[0x3B] != 0xA0:
            raise RuntimeError("packet_send_string local-player operand is missing")
        local_player_address = struct.unpack_from("<I", code, 0x3C)[0]
        if local_player_address != self.base + LOCAL_PLAYER_RVA:
            raise RuntimeError(
                f"packet_send_string gbLocalPlayer disagrees: 0x{local_player_address:08X}"
            )
        if code[0x69:0x70] != b"\xC6\x85\xFA\xFE\xFF\xFF" + bytes([PM_STRING]):
            raise RuntimeError("packet_send_string PM_STRING packet-type validation failed")

        def call_target(offset: int, name: str) -> int:
            if code[offset] != 0xE8:
                raise RuntimeError(f"packet_send_string {name} call is missing")
            displacement = struct.unpack_from("<i", code, offset + 1)[0]
            return packet_send_string + offset + 5 + displacement

        net_send_msg_all = call_target(0x7A, "net_send_msg_all")
        map_msg = call_target(0xAC, "map_msg")
        if net_send_msg_all != self.base + NET_SEND_MSG_ALL_RVA:
            raise RuntimeError(
                f"packet_send_string net_send_msg_all disagrees: 0x{net_send_msg_all:08X}"
            )
        if map_msg != self.base + MAP_MSG_RVA:
            raise RuntimeError(
                f"packet_send_string map_msg disagrees: 0x{map_msg:08X}"
            )
        if self.pm.read_bytes(net_send_msg_all, 4) != b"\x55\x8B\xEC\xA0":
            raise RuntimeError("net_send_msg_all prologue validation failed")
        if self.pm.read_bytes(map_msg, 6) != b"\x55\x8B\xEC\x6A\xFF\x68":
            raise RuntimeError("map_msg prologue validation failed")

        # Do not call map_msg's internal rolling-slot helper.  It is a private
        # implementation detail with hidden context/ABI requirements.  The public
        # map_msg entry point is the exact source path used by incoming PM_STRING.

        # Sender 8 writes the system slot at +0x62 and its base color at +0x6F.
        # Player senders rotate through the seven immediately preceding slots.
        map_code = self.pm.read_bytes(map_msg, 0xC0)
        if map_code[0x62:0x64] != b"\xFF\x35":
            raise RuntimeError("map_msg system-slot pointer operand is missing")
        system_slot_pointer_global = struct.unpack_from("<I", map_code, 0x64)[0]
        if map_code[0x6F:0x71] != b"\xC6\x05" or map_code[0x75] != 0x04:
            raise RuntimeError("map_msg system-color slot validation failed")
        system_color = struct.unpack_from("<I", map_code, 0x71)[0]
        if map_code[0xB6:0xB9] != b"\x8D\x0C\xC5":
            raise RuntimeError("map_msg player-name table operand is missing")
        player_names = struct.unpack_from("<I", map_code, 0xB9)[0]
        slot_globals = [
            system_slot_pointer_global - offset * 4
            for offset in range(7, -1, -1)
        ]
        for index, address in enumerate(slot_globals):
            pointer = self.pm.read_uint(address)
            if not pointer or not self._is_private_writable(pointer):
                label = "system" if index == 7 else f"player {index}"
                raise RuntimeError(
                    f"map_msg {label} slot buffer is not writable: "
                    f"global 0x{address:08X} -> 0x{pointer:08X}"
                )
        if not self.pm.read_bytes(player_names, 1):
            raise RuntimeError("map_msg player-name table is unreadable")

        draw = self.base + MAP_MESSAGE_DRAW_RVA
        draw_code = self.pm.read_bytes(draw, 0x90)
        if b"\x0F\xB6\x86" not in draw_code or struct.pack("<I", system_color - 12) not in draw_code:
            # Unknown builds may move this renderer independently.  Find the exact
            # source-shaped draw function rather than accepting a stale RVA.
            draw = self._resolve_unique_signature(
                b"\x55\x8B\xEC\x51\x53\x56\x57\xFF\x35",
                "map_message_draw",
                0x90,
                (b"\x0F\xB6\x86", struct.pack("<I", system_color - 12)),
            )
            draw_code = self.pm.read_bytes(draw, 0x90)

        font_set_color_rva = FONT_SET_COLOR_TABLE_RVAS.get(
            self.build_timestamp, FONT_SET_COLOR_TABLE_RVA + int(getattr(self.build_info, "code_delta", 0) if self.build_info else 0)
        )
        font_set_color = self.base + font_set_color_rva
        font_code = self.pm.read_bytes(font_set_color, 0x90)
        if font_code[:10] != b"\x55\x8B\xEC\x0F\xB6\x45\x08\x83\xF8\x01":
            font_set_color = self._resolve_unique_signature(
                b"\x55\x8B\xEC\x0F\xB6\x45\x08\x83\xF8\x01",
                "font_set_color_table",
                0x90,
                (b"\x83\xF8\x02", b"\x83\xF9\x03", b"\x83\xFA\x05", b"\x83\xF8\x04", b"\x83\xF9\x06"),
            )
            font_code = self.pm.read_bytes(font_set_color, 0x90)
        for compare in (
            b"\x83\xF8\x02",  # normal / yellow
            b"\x83\xF9\x03",  # highlight / white
            b"\x83\xFA\x05",  # disabled / gray
            b"\x83\xF8\x04",  # selected / red
            b"\x83\xF9\x06",  # game palette / yellow
        ):
            if compare not in font_code:
                raise RuntimeError("native font color control mapping is incomplete")
        return {
            "packet_send_string": packet_send_string,
            "net_send_msg_all": net_send_msg_all,
            "map_msg": map_msg,
            "font_set_color": font_set_color,
            "system_color": system_color,
            "color_table": system_color - 7,
            "system_slot_pointer_global": system_slot_pointer_global,
            "player_names": player_names,
            "message_filter": self.base + CHAT_FILTER_RVA,
            "local_player": self.base + LOCAL_PLAYER_RVA,
        }

    def _find_map_size(self) -> None:
        # Warcraft II PUD maps are square. The remaster retains their matrix
        # dimension in the native-verified gwMapMtxWdt global used by collision,
        # placement, fog, and pathfinding code. Do not infer it from heap blobs.
        dimension = self.pm.read_ushort(self.base + MAP_DIMENSION_RVA)
        if dimension not in (32, 64, 96, 128):
            raise RuntimeError(
                f"Invalid live map matrix dimension {dimension} at RVA 0x{MAP_DIMENSION_RVA:X}; "
                "start or load a match before attaching"
            )
        self.map_width = self.map_height = dimension

    @staticmethod
    def _resource_name(value: Any) -> str:
        aliases = {"gold": "Gold", "stone": "Gold", "lumber": "Lumber", "wood": "Lumber", "oil": "Oil"}
        name = aliases.get(str(value).strip().casefold())
        if not name:
            raise ValueError(f"Unknown Warcraft resource: {value}")
        return name

    def _resource_address(self, owner: int, resource: Any) -> tuple[str, int]:
        if not 0 <= owner <= 15:
            raise ValueError(f"Invalid resource player: {owner}")
        name = self._resource_name(resource)
        return name, self.base + RESOURCE_RVAS[name] + owner * 4

    def _read_resource(self, owner: int, resource: Any) -> int:
        name, address = self._resource_address(owner, resource)
        value = self.pm.read_uint(address)
        if value > MAX_RESOURCE_VALUE:
            raise RuntimeError(f"Invalid negative {name} value for P{owner + 1}: 0x{value:08X}")
        return value

    def _validate_resource_tables(self) -> dict[str, int]:
        player_one: dict[str, int] = {}
        for name in RESOURCE_RVAS:
            values = [self._read_resource(owner, name) for owner in range(16)]
            player_one[name] = values[0]
        return player_one

    def _validate_resource_layout(self) -> None:
        """Cross-check the three tables against new_game_init's source pattern."""
        image = self.pm.read_bytes(self.base, self.image_size)
        matches: list[tuple[int, tuple[int, int, int]]] = []
        start = 0
        while True:
            offset = image.find(b"\xC7\x86", start)
            if offset < 0:
                break
            body = image[offset:offset + 33]
            if (
                len(body) == 33
                and body[6:10] == b"\xE8\x03\x00\x00"
                and body[10:12] == b"\xC7\x86"
                and body[16:20] == b"\xE8\x03\x00\x00"
                and body[20:23] == b"\x8D\x52\xFE"
                and body[23:25] == b"\xC7\x86"
                and body[29:33] == b"\xE8\x03\x00\x00"
            ):
                addresses = (
                    struct.unpack_from("<I", body, 2)[0],
                    struct.unpack_from("<I", body, 12)[0],
                    struct.unpack_from("<I", body, 25)[0],
                )
                matches.append((offset, addresses))
            start = offset + 1
        if len(matches) != 1:
            raise RuntimeError(f"Resource initialization validation found {len(matches)} candidates")
        _offset, addresses = matches[0]
        expected = (
            self.base + RESOURCE_RVAS["Oil"] + 0x40,
            self.base + RESOURCE_RVAS["Gold"] + 0x40,
            self.base + RESOURCE_RVAS["Lumber"] + 0x40,
        )
        if addresses != expected:
            raise RuntimeError(
                "Resource table addresses disagree with new_game_init: "
                + ", ".join(f"0x{address:08X}" for address in addresses)
            )
        # The initialization loop proves the three adjacent arrays but not their
        # labels. The return-harvest routine shifts manFlags by 7 for GOLD and 6
        # for LUMBER, then adds to the corresponding live table. Decode both
        # relocated operands so equal starting values cannot conceal a swap.
        harvest_prefix = b"\xC1\xEF\x06\xC1\xEB\x07\x83\xE7\x01"
        harvest_hits: list[int] = []
        start = 0
        while True:
            offset = image.find(harvest_prefix, start)
            if offset < 0:
                break
            body = image[offset:offset + 0xB3]
            if (
                len(body) == 0xB3
                and body[0x7A:0x7D] == b"\x01\x0C\x85"
                and body[0xAC:0xAF] == b"\x01\x0C\x85"
            ):
                harvest_hits.append(offset)
            start = offset + 1
        if len(harvest_hits) != 1:
            raise RuntimeError(f"Resource harvest validation found {len(harvest_hits)} candidates")
        body = image[harvest_hits[0]:harvest_hits[0] + 0xB3]
        gold_address = struct.unpack_from("<I", body, 0x7D)[0]
        lumber_address = struct.unpack_from("<I", body, 0xAF)[0]
        if gold_address != self.base + RESOURCE_RVAS["Gold"]:
            raise RuntimeError(f"Gold table disagrees with harvest code: 0x{gold_address:08X}")
        if lumber_address != self.base + RESOURCE_RVAS["Lumber"]:
            raise RuntimeError(f"Lumber table disagrees with harvest code: 0x{lumber_address:08X}")

    @staticmethod
    def _decode_unit(address: int, data: bytes) -> Unit:
        # +0/+2 are TSeq pixel coordinates. unitMtx tile coordinates follow the
        # 24-byte sequence at +0x18/+0x1A.
        return Unit(address, int.from_bytes(data[0x18:0x1A], "little", signed=True),
                    int.from_bytes(data[0x1A:0x1C], "little", signed=True),
                    data[0x2E], int.from_bytes(data[0x22:0x24], "little"),
                    data[0x27], data[0x2C], data[0x2D], data[0x26], data[0x2F],
                    int.from_bytes(data[0x84:0x86], "little", signed=True),
                    int.from_bytes(data[0x86:0x88], "little", signed=True),
                    int.from_bytes(data[0x88:0x8C], "little"),
                    int.from_bytes(data[0x1E:0x20], "little"),
                    int.from_bytes(data[0x10:0x14], "little"),
                    int.from_bytes(data[0x4A:0x4C], "little", signed=True),
                    int.from_bytes(data[0x46:0x48], "little"),
                    int.from_bytes(data[0x48:0x4A], "little"),
                    int.from_bytes(data[0x4E:0x50], "little"),
                    int.from_bytes(data[0x44:0x46], "little"))

    def _unit_is_active(self, unit: Unit) -> bool:
        return (
            0 <= unit.x < self.map_width and 0 <= unit.y < self.map_height
            and 0 <= unit.unit_type < len(UNIT_NAMES)
            and 0 <= unit.owner <= 15
        )

    @staticmethod
    def _record_is_allocated(data: bytes) -> bool:
        # Exact remaster/source condition. The word at +0x1E is sFlags:
        # bit 0 FREE, bit 1 DIEING, bit 2 DEAD. Engine array loops skip a record
        # when (sFlags & 7) != 0.
        return len(data) >= 0x20 and not (struct.unpack_from("<H", data, 0x1E)[0] & 0x0007)

    def _pool_score(self, pool: int, sample=128) -> tuple[int, int]:
        if pool < 0x10000 or pool > 0x7FFF0000: return (-1, 0)
        plausible = active = readable = 0
        for i in range(sample):
            address = pool + i * UNIT_SIZE
            try:
                data = self.pm.read_bytes(address, UNIT_SIZE)
            except Exception as exc:
                # A pool can end at a page/region boundary. Do not reject records
                # already validated just because a later slot is unreadable.
                if readable == 0:
                    self.log(f"Cannot read first unit record at 0x{address:08X}: {exc}")
                break
            readable += 1
            u = self._decode_unit(address, data)
            if u.unit_type < len(UNIT_NAMES) and u.owner <= 15: plausible += 1
            if self._unit_is_active(u):
                active += 1
        if not readable: return (-1, 0)
        return plausible + active * 8 + min(readable, 32), active

    def _find_unit_pool(self) -> tuple[int, int]:
        ranked = []
        for rva in UNIT_GLOBAL_RVAS:
            address = self.base + rva
            try: pool = self._read_ptr(address)
            except Exception: continue
            score, active = self._pool_score(pool)
            self.log(f"Unit candidate RVA 0x{rva:X}: pool 0x{pool:08X}, score {score}, active {active}")
            # These globals are allocator cursors. A cursor may legitimately point
            # at the next free slot, so its own record can be inactive even while
            # nearby records contain the match's units.
            if score >= 32:
                ranked.append((score, address, pool))
                self.unit_globals.append(address)
        if not ranked: raise RuntimeError("No readable unit cursor found. Start or load a match, then attach again.")
        _, address, pool = max(ranked)
        return address, pool

    def _writable_module_pointers(self) -> list[tuple[int, int]]:
        head = self.pm.read_bytes(self.base, 0x1000)
        pe = struct.unpack_from("<I", head, 0x3C)[0]
        section_count = struct.unpack_from("<H", head, pe + 6)[0]
        optional_size = struct.unpack_from("<H", head, pe + 20)[0]
        table = pe + 24 + optional_size
        found: list[tuple[int, int]] = []
        for i in range(section_count):
            off = table + i * 40
            virtual_size, rva, raw_size = struct.unpack_from("<III", head, off + 8)
            characteristics = struct.unpack_from("<I", head, off + 36)[0]
            if not characteristics & 0x80000000: continue
            size = max(virtual_size, raw_size)
            try: blob = self.pm.read_bytes(self.base + rva, size)
            except Exception: continue
            for pos in range(0, len(blob) - 3, 4):
                value = struct.unpack_from("<I", blob, pos)[0]
                if 0x10000 <= value <= 0x7FFF0000 and value % 4 == 0 and self._is_private_writable(value):
                    found.append((self.base + rva + pos, value))
        return found

    def _is_private_writable(self, address: int) -> bool:
        """Require committed writable MEM_PRIVATE storage, not image/string data."""
        page = address & ~0xFFF
        if page in self._region_cache: return self._region_cache[page]
        try:
            import ctypes
            from ctypes import wintypes

            class MBI(ctypes.Structure):
                _fields_ = [
                    ("BaseAddress", ctypes.c_void_p),
                    ("AllocationBase", ctypes.c_void_p),
                    ("AllocationProtect", wintypes.DWORD),
                    ("PartitionId", wintypes.WORD),
                    ("RegionSize", ctypes.c_size_t),
                    ("State", wintypes.DWORD),
                    ("Protect", wintypes.DWORD),
                    ("Type", wintypes.DWORD),
                ]

            mbi = MBI()
            size = ctypes.windll.kernel32.VirtualQueryEx(
                wintypes.HANDLE(self.pm.process_handle), ctypes.c_void_p(address),
                ctypes.byref(mbi), ctypes.sizeof(mbi))
            writable = {0x04, 0x08, 0x40, 0x80}
            ok = bool(size) and mbi.State == 0x1000 and mbi.Type == 0x20000 and (mbi.Protect & 0xFF) in writable
        except Exception:
            ok = False
        self._region_cache[page] = ok
        return ok

    def _looks_active(self, data: bytes) -> bool:
        if len(data) < 46: return False
        return self._unit_is_active(self._decode_unit(0, data))

    def _window_metrics(self, pointer: int, backward=32, forward=96) -> tuple[int, int, int]:
        count = longest = run = transitions = 0
        previous = False
        for slot in range(-backward, forward):
            try: data = self.pm.read_bytes(pointer + slot * UNIT_SIZE, 48)
            except Exception:
                active = False
            else:
                active = self._looks_active(data)
            if active:
                count += 1; run += 1; longest = max(longest, run)
            else: run = 0
            if active != previous: transitions += 1
            previous = active
        return count, longest, transitions

    def _auto_find_unit_global(self) -> tuple[int, int, int]:
        candidates = self._writable_module_pointers()
        self.log(f"Writable module pointer candidates: {len(candidates)}")
        shortlist: list[tuple[int, int]] = []
        seen: set[int] = set()
        for glob, pointer in candidates:
            if pointer in seen: continue
            seen.add(pointer)
            try: data = self.pm.read_bytes(pointer, 48)
            except Exception: continue
            if self._looks_active(data): shortlist.append((glob, pointer))
        self.log(f"Direct active-unit pointer candidates: {len(shortlist)}")
        if not shortlist:
            raise RuntimeError("Automatic unit scan found no active unit records")
        ranked = []
        for glob, pointer in shortlist[:512]:
            active, longest, transitions = self._window_metrics(pointer)
            # Unit arrays produce contiguous runs. Accidental matches in unrelated
            # structures tend to be scattered and have many state transitions.
            score = longest * 1000 + active * 10 - transitions
            ranked.append((score, longest, active, glob, pointer))
        score, longest, active, glob, pointer = max(ranked)
        self.log(f"Strongest unit-array candidate: run {longest}, active {active}, score {score}")
        if active < 1: raise RuntimeError("Automatic unit candidates failed surrounding-array validation")
        return glob, pointer, active

    def _cursor_values(self) -> list[int]:
        values = []
        for glob in self.unit_globals:
            try:
                value = self._read_ptr(glob)
                if 0x10000 <= value <= 0x7FFF0000: values.append(value)
            except Exception: pass
        return values

    def units(self, limit=1600) -> list[Unit]:
        if not self.pm: raise RuntimeError("Not attached")
        pool = self._read_ptr(self.unit_global)
        if pool != self.unit_pool:
            if not self._is_private_writable(pool): raise RuntimeError(f"gpUnits changed to invalid pointer 0x{pool:08X}")
            self.unit_pool = pool; self.log(f"gpUnits allocation changed to 0x{pool:08X}")
        count = min(self.max_units, limit)
        blob = self.pm.read_bytes(pool, count * UNIT_SIZE)
        result: list[Unit] = []
        for slot in range(count):
            start = slot * UNIT_SIZE
            data = blob[start:start + UNIT_SIZE]
            if not self._record_is_allocated(data): continue
            unit = self._decode_unit(pool + start, data)
            if self._unit_is_active(unit): result.append(unit)
        return result

    def corpses(self, limit=1600) -> list[Unit]:
        """Return Raise Dead-eligible native corpse records from the raw pool."""
        if not self.pm:
            raise RuntimeError("Not attached")
        pool = self._read_ptr(self.unit_global)
        if pool != self.unit_pool:
            if not self._is_private_writable(pool):
                raise RuntimeError(f"gpUnits changed to invalid pointer 0x{pool:08X}")
            self.unit_pool = pool
            self.log(f"gpUnits allocation changed to 0x{pool:08X}")
        count = min(self.max_units, limit)
        blob = self.pm.read_bytes(pool, count * UNIT_SIZE)
        result: list[Unit] = []
        for slot in range(count):
            start = slot * UNIT_SIZE
            data = blob[start:start + UNIT_SIZE]
            sflags = struct.unpack_from("<H", data, 0x1E)[0]
            # Exact action_raisedead test: type DEAD_GUY and low nibble == DIEING.
            if data[0x27] != DEAD_GUY_TYPE or (sflags & 0x000F) != 0x0002:
                continue
            corpse = self._decode_unit(pool + start, data)
            if 0 <= corpse.x < self.map_width and 0 <= corpse.y < self.map_height:
                result.append(corpse)
        return result

    @staticmethod
    def _decode_missile(address: int, data: bytes) -> Missile:
        return Missile(
            address=address,
            x=int.from_bytes(data[0x00:0x02], "little", signed=True),
            y=int.from_bytes(data[0x02:0x04], "little", signed=True),
            target_x=int.from_bytes(data[0x28:0x2A], "little", signed=True),
            target_y=int.from_bytes(data[0x2A:0x2C], "little", signed=True),
            target_unit=int.from_bytes(data[0x2C:0x30], "little"),
            owner_unit=int.from_bytes(data[0x30:0x34], "little"),
            missile_type=data[0x34],
            flags=data[0x35],
            action=data[0x36],
            damage=data[0x37],
        )

    def _current_bullet_pool(self) -> int:
        pool = self._read_ptr(self.base + BULLET_ARRAY_RVA)
        if pool != self.bullet_pool:
            if not self._is_private_writable(pool):
                raise RuntimeError(f"gpBullets changed to invalid pointer 0x{pool:08X}")
            self.pm.read_bytes(pool, self.max_bullets * BULLET_SIZE)
            self.bullet_pool = pool
            self.log(f"gpBullets allocation changed to 0x{pool:08X}")
        return pool

    def _active_missiles(self) -> list[Missile]:
        pool = self._current_bullet_pool()
        blob = self.pm.read_bytes(pool, self.max_bullets * BULLET_SIZE)
        result: list[Missile] = []
        for slot in range(self.max_bullets):
            start = slot * BULLET_SIZE
            data = blob[start:start + BULLET_SIZE]
            if data[0x35] & 0x01:
                continue
            missile = self._decode_missile(pool + start, data)
            if 0 <= missile.missile_type < BT_NONE:
                result.append(missile)
        return result

    def _create_missile(self, attacker: Unit, target: Unit) -> Missile:
        expected_type = self.pm.read_uchar(
            self.base + UNIT_BULLET_TABLE_RVA + attacker.unit_type
        )
        if expected_type == BT_NONE:
            raise RuntimeError(
                f"{UNIT_NAMES[attacker.unit_type]} has no Warcraft missile type"
            )
        if not 0 <= expected_type < BT_NONE:
            raise RuntimeError(
                f"Invalid missile type {expected_type} for {UNIT_NAMES[attacker.unit_type]}"
            )
        old_target = self._read_ptr(attacker.address + 0x88)
        # bullet_create reads the attacker's target pointer, then copies it into
        # the new bullet. Assign the requested target, create one bullet, and
        # restore the unit's prior target before the simulation mailbox returns.
        address = self._dispatch_ops([
            ("write_dword", attacker.address + 0x88, target.address),
            ("call", self.bullet_path["bullet_create"], [attacker.address]),
            ("write_dword", attacker.address + 0x88, old_target),
        ])
        if not address:
            raise RuntimeError("Warcraft bullet_create returned no free projectile slot")
        pool = self._current_bullet_pool()
        allocation_end = pool + self.max_bullets * BULLET_SIZE
        if not (pool <= address < allocation_end) or (address - pool) % BULLET_SIZE:
            raise RuntimeError(f"bullet_create returned invalid record pointer 0x{address:08X}")
        data = self.pm.read_bytes(address, BULLET_SIZE)
        missile = self._decode_missile(address, data)
        failures: list[str] = []
        if missile.flags & 0x01:
            failures.append(f"free flags 0x{missile.flags:02X}")
        if missile.owner_unit != attacker.address:
            failures.append(
                f"owner 0x{missile.owner_unit:08X}/0x{attacker.address:08X}"
            )
        if missile.target_unit != target.address:
            failures.append(
                f"target 0x{missile.target_unit:08X}/0x{target.address:08X}"
            )
        if missile.missile_type != expected_type:
            failures.append(f"type {missile.missile_type}/{expected_type}")
        if missile.damage <= 0:
            failures.append(f"damage {missile.damage}")
        if failures:
            raise RuntimeError("Warcraft missile validation failed: " + ", ".join(failures))
        return missile

    def _spell_destination(self, args: dict[str, Any], action_name: str) -> tuple[int, int]:
        location_name = args.get("location", args.get("destination", "Anywhere")) or "Anywhere"
        if location_name != "Anywhere":
            if not self.scenario:
                raise RuntimeError(f"{action_name} location requires an active scenario")
            location = next(
                (item for item in self.scenario.locations if item.name == location_name),
                None,
            )
            if not location:
                raise ValueError(f"Unknown spell location: {location_name}")
            return (
                (location.left + location.right) // 2,
                (location.top + location.bottom) // 2,
            )
        if "x" not in args or "y" not in args:
            raise ValueError(
                f"{action_name} needs tile coordinates x and y, a named location, "
                "or Map target source = Matching unit(s)"
            )
        return int(args["x"]), int(args["y"])

    @staticmethod
    def _spell_target_uses_units(args: dict[str, Any]) -> bool:
        source = str(args.get("map_target_source", "")).strip().casefold()
        if source in {"matching unit(s)", "matching units", "unit", "units"}:
            return True
        # Backward-compatible convenience: choosing an exact target unit/location
        # with no literal point implicitly means to use matching unit positions.
        if "x" in args or "y" in args:
            return False
        target_unit = args.get("target_unit", "Any")
        target_location = args.get("target_location", "Anywhere") or "Anywhere"
        return target_unit not in (None, "", "Any") or target_location != "Anywhere"

    def _spell_destinations(
        self, args: dict[str, Any], action_name: str, executing_player: int
    ) -> list[tuple[int, int]]:
        if not self._spell_target_uses_units(args):
            points = [self._spell_destination(args, action_name)]
        else:
            owner = int(args.get("target_player", executing_player))
            target_args = {
                "player": owner,
                "unit": args.get("target_unit", "Any"),
                "location": args.get("target_location", "Anywhere") or "Anywhere",
            }
            matches = self._selected_units(target_args, executing_player)
            if not matches:
                unit_value = target_args["unit"]
                unit_name = (
                    "Any unit" if unit_value == "Any"
                    else UNIT_NAMES[int(unit_value)]
                )
                raise RuntimeError(
                    f"{action_name} found no live P{owner + 1} {unit_name} target "
                    f"at {target_args['location']}"
                )
            amount = args.get("target_amount", "All")
            if amount != "All":
                count = int(amount)
                if not 1 <= count <= MAX_SPELL_TARGET_POINTS:
                    raise ValueError(
                        f"Maximum target points must be 1 through {MAX_SPELL_TARGET_POINTS}, or All"
                    )
                matches = matches[:count]
            points = []
            seen: set[tuple[int, int]] = set()
            for unit in matches:
                point = (unit.x, unit.y)
                if point not in seen:
                    seen.add(point)
                    points.append(point)
            if len(points) > MAX_SPELL_TARGET_POINTS:
                raise RuntimeError(
                    f"{action_name} matched {len(points)} unique unit tiles; narrow the "
                    f"location or set Maximum target points to {MAX_SPELL_TARGET_POINTS} or less"
                )
        for x, y in points:
            if not (0 <= x < self.map_width and 0 <= y < self.map_height):
                raise ValueError(f"{action_name} destination ({x},{y}) is outside the live map")
        return points

    def _single_spell_destination(
        self, args: dict[str, Any], action_name: str, executing_player: int
    ) -> tuple[int, int]:
        points = self._spell_destinations(args, action_name, executing_player)
        if len(points) != 1:
            raise ValueError(
                f"{action_name} matched {len(points)} target points, but a native caster "
                "has only one live order target. Set Maximum target points to 1, or use "
                "caster-free Runes/Holy Vision for multi-point effects."
            )
        return points[0]

    @staticmethod
    def _spell_casts_with_unit(args: dict[str, Any], spell_key: str) -> bool:
        mode = str(args.get("cast_mode", "Automatic")).strip().casefold()
        if mode == "use caster units":
            return True
        if mode == "caster-free effect":
            return False
        if spell_key.startswith("caster ") or bool(args.get("with_caster", False)):
            return True
        caster_unit = args.get("caster_unit", "Any")
        return caster_unit not in (None, "", "Any")

    def _message_template_player(self, value: str, executing_player: int) -> int:
        text = str(value or "Current").strip().casefold()
        if text in {"", "current", "executing", "executing player", "self"}:
            return executing_player
        if text in {"all", "all players", "any"}:
            return -1
        match = re.fullmatch(r"(?:p|player\s*)?(\d{1,2})", text)
        if not match:
            raise ValueError(f"Unknown message-variable player: {value}")
        player = int(match.group(1)) - 1
        if not 0 <= player <= 15:
            raise ValueError("Message-variable players must be Player 1 through Player 16")
        return player

    @staticmethod
    def _message_template_unit(value: str) -> int | str:
        text = str(value or "Any").strip()
        if not text or text.casefold() == "any":
            return "Any"
        numeric = re.fullmatch(r"(?:unit|building)?\s*(\d{1,3})", text, re.IGNORECASE)
        if numeric:
            unit_type = int(numeric.group(1))
            if 0 <= unit_type < len(UNIT_NAMES):
                return unit_type
            raise ValueError(f"Unit type {unit_type} is outside the Warcraft table")
        key = text.casefold()
        matches = [index for index, name in enumerate(UNIT_NAMES) if name.casefold() == key]
        if not matches:
            raise ValueError(f"Unknown message-variable unit/building: {value}")
        return matches[0]

    def _message_template_selector(
        self, parts: list[str], executing_player: int
    ) -> dict[str, Any]:
        player = self._message_template_player(parts[0] if parts else "Current", executing_player)
        unit_type = self._message_template_unit(parts[1] if len(parts) > 1 else "Any")
        location = str(parts[2]).strip() if len(parts) > 2 else "Anywhere"
        if not location:
            location = "Anywhere"
        if location != "Anywhere" and self.scenario:
            if not any(item.name == location for item in self.scenario.locations):
                raise ValueError(f"Unknown message-variable location: {location}")
        return {"player": player, "unit": unit_type, "location": location}

    def _message_template_count(
        self, function: str, parts: list[str], executing_player: int
    ) -> int:
        selector = self._message_template_selector(parts, executing_player)
        if function == "count":
            source = self.units()
            return len(self._selected_from(source, selector, executing_player))
        if function == "completed":
            source = self._selected_from(self.units(), selector, executing_player)
            return sum(
                1 for unit in source
                if FIRST_BUILDING_TYPE <= unit.unit_type <= LAST_BUILDING_TYPE
                and bool(unit.sflags & 0x0080)
            )
        if function == "created":
            source = self.created_units
        elif function == "died":
            source = self.died_units
        elif function == "removed":
            source = self.removed_units
        elif function == "corpses":
            source = self.corpses()
        else:
            raise ValueError(f"Unknown count function: {function}")
        return len(self._selected_from(source, selector, executing_player))

    def _message_context_value(self, name: str, executing_player: int) -> str:
        key = name.strip().casefold().replace(" ", "_")
        if key in {"elapsed", "time", "elapsed_seconds"}:
            return str(int(time.monotonic() - self.started))
        if key == "player":
            return f"Player {executing_player + 1}"
        if key in {"player_number", "player_no"}:
            return str(executing_player + 1)
        if key in {"run", "run_number"}:
            if self._action_context and len(self._action_context) >= 5:
                return str(int(self._action_context[3]) + 1)
            return "1"
        if key in {"trigger", "trigger_number"}:
            if self._action_context and len(self._action_context) >= 5:
                return str(int(self._action_context[1]) + 1)
            return "1"
        if key in {"action", "action_number"}:
            if self._action_context and len(self._action_context) >= 5:
                return str(int(self._action_context[4]) + 1)
            return "1"
        if key in {"gold", "lumber", "oil"}:
            return str(self._read_resource(executing_player, key.title()))
        if key == "kills":
            return str(self._read_combat_stat(executing_player, "Kills", "All"))
        if key in {"killdelta", "new_kills", "kills_this_cycle"}:
            return str(self._kill_delta(executing_player, "All"))
        if key == "deaths":
            return str(self._read_combat_stat(executing_player, "Deaths", "All"))
        if key == "score":
            return str(self._read_stat_table(executing_player, "Score"))
        if key in {"event_type", "event"}:
            return str(self._event_context.get("event_type", "None"))
        if key == "event_player":
            owner = int(self._event_context.get("player", -1))
            return f"Player {owner + 1}" if owner >= 0 else "None"
        if key in {"event_player_number", "event_player_no"}:
            return str(int(self._event_context.get("player", -1)) + 1)
        if key == "event_unit":
            unit_type = int(self._event_context.get("unit_type", -1))
            return UNIT_NAMES[unit_type] if 0 <= unit_type < len(UNIT_NAMES) else "None"
        if key in {"event_x", "event_y", "event_health", "event_mana", "event_damage", "event_amount"}:
            field = {"event_damage": "amount", "event_amount": "amount"}.get(key, key.removeprefix("event_"))
            return str(self._event_context.get(field, 0))
        raise ValueError(f"Unknown Game Message variable: {{{name}}}")

    def _message_function_value(
        self, function: str, argument_text: str, executing_player: int
    ) -> str:
        name = function.strip().casefold().replace(" ", "_")
        if "|" in argument_text:
            parts = [part.strip() for part in argument_text.split("|")]
        elif argument_text.strip():
            parts = [part.strip() for part in argument_text.split(",")]
        else:
            parts = []

        if name in {"count", "completed", "created", "died", "removed", "corpses"}:
            return str(self._message_template_count(name, parts, executing_player))
        if name in {"gold", "lumber", "oil"}:
            player = self._message_template_player(parts[0] if parts else "Current", executing_player)
            if player < 0:
                raise ValueError(f"{{{function}(...)}} requires one player, not All")
            return str(self._read_resource(player, name.title()))
        if name in {"kills", "deaths"}:
            player = self._message_template_player(parts[0] if parts else "Current", executing_player)
            if player < 0:
                raise ValueError(f"{{{function}(...)}} requires one player, not All")
            category = parts[1].title() if len(parts) > 1 else "All"
            if category not in {"Men", "Buildings", "All"}:
                raise ValueError(f"Unknown {function} category: {category}")
            return str(self._read_combat_stat(player, name.title(), category))
        if name in {"killdelta", "new_kills", "kills_this_cycle"}:
            player = self._message_template_player(parts[0] if parts else "Current", executing_player)
            if player < 0:
                raise ValueError(f"{{{function}(...)}} requires one player, not All")
            category = parts[1].title() if len(parts) > 1 else "All"
            if category not in {"Men", "Buildings", "All"}:
                raise ValueError(f"Unknown {function} category: {category}")
            return str(self._kill_delta(player, category))
        if name == "score":
            player = self._message_template_player(parts[0] if parts else "Current", executing_player)
            if player < 0:
                raise ValueError("{score(...)} requires one player, not All")
            return str(self._read_stat_table(player, "Score"))
        if name == "switch":
            switch_name = argument_text.strip()
            if not switch_name:
                raise ValueError("{switch(...)} requires a switch name")
            return str(self.switches.get(switch_name, "Cleared"))
        if name == "counter":
            counter_name = argument_text.strip()
            if not counter_name:
                raise ValueError("{counter(...)} requires a counter name")
            return str(int(self.counters.get(counter_name, 0)))
        if name in {"variable", "var"}:
            variable_name = argument_text.strip()
            if not variable_name:
                raise ValueError("{variable(...)} requires a variable name")
            return str(self.variables.get(variable_name, 0))
        if name in {"timer", "countdown"}:
            timer_name = argument_text.strip()
            if not timer_name:
                raise ValueError("{timer(...)} requires a timer name")
            return str(int(math.ceil(self._timer(timer_name).value())))
        if name == "objective":
            objective_name = argument_text.strip()
            if not objective_name:
                raise ValueError("{objective(...)} requires an objective name")
            return str(self.objectives.get(objective_name, objective_name))
        if name in {"group", "unit_group"}:
            group_name = argument_text.strip()
            if not group_name:
                raise ValueError("{group(...)} requires a unit-group name")
            return str(len(self._group_units(group_name)))
        if name in {"expr", "expression"}:
            return str(self._evaluate_expression(argument_text, executing_player))
        if name == "event":
            field = argument_text.strip() or "event_type"
            return str(self._event_context.get(field, 0))
        raise ValueError(f"Unknown Game Message variable function: {function}")

    def _expand_message_template(self, template: str, executing_player: int) -> str:
        open_sentinel = "\uf000"
        close_sentinel = "\uf001"
        working = template.replace("{{", open_sentinel).replace("}}", close_sentinel)
        pattern = re.compile(r"\{([^{}]+)\}")
        replacements = 0

        def replace(match: re.Match[str]) -> str:
            nonlocal replacements
            replacements += 1
            if replacements > 64:
                raise ValueError("Game Message supports at most 64 variable expressions")
            expression = match.group(1).strip()
            function_match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_ ]*)\((.*)\)", expression)
            if function_match:
                return self._message_function_value(
                    function_match.group(1), function_match.group(2), executing_player
                )
            return self._message_context_value(expression, executing_player)

        expanded = pattern.sub(replace, working)
        if "{" in expanded or "}" in expanded:
            raise ValueError(
                "Malformed Game Message variable. Use {elapsed} or "
                "{count(Current|Footman|Anywhere)}; double braces print literal braces."
            )
        expanded = expanded.replace(open_sentinel, "{").replace(close_sentinel, "}")
        if len(expanded) > 4096:
            raise ValueError("Expanded Game Message is unreasonably long")
        return expanded

    @staticmethod
    def _message_start_color(color_name: str) -> int | None:
        if color_name in NATIVE_MESSAGE_COLORS:
            return NATIVE_MESSAGE_COLORS[color_name]
        # Backward compatibility for old projects. Player-number color choices
        # were sender identities; leave the native sender color unchanged.
        if color_name in {"Neutral / default", "Native default — no color code"} or re.fullmatch(
            r"Player \d+ color", color_name
        ):
            return None
        raise ValueError(f"Unknown Player Chat color: {color_name}")

    @staticmethod
    def _apply_message_color_tags(text: str) -> str:
        """Convert chat-only [color] tags into Warcraft font-control bytes."""
        pattern = re.compile(r"\[([A-Za-z ]+)\]", re.IGNORECASE)

        def replace(match: re.Match[str]) -> str:
            key = " ".join(match.group(1).strip().casefold().split())
            if key in {"previous", "restore"}:
                return chr(0x01)
            code = NATIVE_MESSAGE_COLOR_TAGS.get(key)
            return chr(code) if code is not None else match.group(0)

        return pattern.sub(replace, text)

    @staticmethod
    def _strip_message_color_tags(text: str) -> str:
        """Remove recognized tags for the printable PM_STRING network copy."""
        pattern = re.compile(r"\[([A-Za-z ]+)\]", re.IGNORECASE)

        def replace(match: re.Match[str]) -> str:
            key = " ".join(match.group(1).strip().casefold().split())
            if key in NATIVE_MESSAGE_COLOR_TAGS or key in {"previous", "restore"}:
                return ""
            return match.group(0)

        stripped = pattern.sub(replace, text)
        # Users may paste the original source-era control characters directly
        # (01-06), as old Cheat Engine tables allowed. Keep them for the local
        # raw-slot rewrite but never pass them through Remaster's text converter,
        # which turns them into visible question marks.
        return "".join(character for character in stripped if not 1 <= ord(character) <= 6)

    @staticmethod
    def _message_log_text(text: str) -> str:
        return "".join(character for character in text if ord(character) not in range(1, 7))

    def _native_message_recipients(
        self,
        args: dict[str, Any],
        local_player: int,
        *,
        default: str,
        label: str,
    ) -> tuple[str, bool, int]:
        recipients = str(args.get("recipients", default)).strip()
        local_show = False
        remote_mask = 0

        # net_send_msg_all addresses network-player nodes, not Warcraft owner
        # slots.  In an offline game the other active slots are Computers and
        # must not be placed in the network filter.  Earlier builds used 0xFF,
        # so a Player Chat action could enter the network sender before its local
        # map_msg insertion and never reach the visible chat branch.
        remote_human_mask = 0
        for owner in range(8):
            if owner == local_player:
                continue
            if self._owner_type(owner) == C_PLAYER:
                remote_human_mask |= 1 << owner

        if recipients == "Local player only":
            local_show = True
        elif recipients == "All active players":
            local_show = True
            remote_mask = remote_human_mask
        elif recipients.startswith("Player "):
            try:
                recipient = int(recipients.split()[1]) - 1
            except (ValueError, IndexError) as exc:
                raise ValueError(f"Unknown {label} recipients: {recipients}") from exc
            if not 0 <= recipient <= 7:
                raise ValueError(f"Native {label.lower()} supports Player 1 through Player 8")
            if recipient == local_player:
                local_show = True
            elif self._owner_type(recipient) == C_PLAYER:
                remote_mask = 1 << recipient
        else:
            raise ValueError(f"Unknown {label} recipients: {recipients}")
        return recipients, local_show, remote_mask

    @staticmethod
    def _native_game_speed_packet(speed_index: int) -> bytearray:
        """Build NET_MSG + one-byte PKT_SET_SPEED exactly as upacket_set_speed."""
        speed_index = LiveAdapter._game_speed_index(speed_index)
        packet = bytearray(9)
        packet[0] = len(packet)
        packet[6] = PM_SET_SPEED
        packet[8] = speed_index
        return packet

    @staticmethod
    def _native_message_packet(
        encoded: bytes, remote_mask: int, sender: int
    ) -> bytearray:
        # NET_MSG header (8) + PKT_STRING filter/sender (2) + text + NUL (1).
        packet = bytearray(len(encoded) + 11)
        packet[0] = len(packet)
        packet[6] = PM_STRING
        packet[8] = remote_mask
        packet[9] = sender
        packet[10:10 + len(encoded)] = encoded
        packet[10 + len(encoded)] = 0
        if len(packet) > CHAT_PACKET_CAPACITY:
            raise RuntimeError("Native message packet exceeds reserved dispatcher storage")
        return packet

    def _message_slot_pointer(self, global_key: str) -> int:
        global_address = int(self.message_path[global_key])
        pointer = int(self.pm.read_uint(global_address))
        if not pointer or not self._is_private_writable(pointer):
            raise RuntimeError(
                f"Native message slot became unavailable: 0x{global_address:08X} -> 0x{pointer:08X}"
            )
        return pointer

    def _native_message_slot_globals(self) -> list[int]:
        """Return Player Chat slots 0-6 followed by the system slot 7."""
        system_global = int(self.message_path["system_slot_pointer_global"])
        return [system_global - (7 - index) * 4 for index in range(8)]

    def _snapshot_native_message_slots(self) -> list[tuple[int, bytes]]:
        """Capture all eight 100-byte native slots by their pointer globals."""
        snapshots: list[tuple[int, bytes]] = []
        for global_address in self._native_message_slot_globals():
            pointer = int(self.pm.read_uint(global_address))
            if not pointer or not self._is_private_writable(pointer):
                raise RuntimeError(
                    f"Native message slot became unavailable: "
                    f"0x{global_address:08X} -> 0x{pointer:08X}"
                )
            snapshots.append((global_address, self.pm.read_bytes(pointer, 100)))
        return snapshots

    def _snapshot_native_message_colors(self) -> bytes:
        """Capture renderer-owned colors for player slots 0-6 and system slot 7."""
        return bytes(self.pm.read_bytes(int(self.message_path["color_table"]), 8))

    def _restore_message_color_operations(
        self, colors: bytes, indices: set[int]
    ) -> list[tuple]:
        table = int(self.message_path["color_table"])
        raw = bytes(colors).ljust(8, b"\x04")[:8]
        return [
            ("write_bytes", table + index, raw[index:index + 1])
            for index in sorted(indices)
        ]

    @staticmethod
    def _slot_has_text(raw: bytes) -> bool:
        return bool(bytes(raw).split(b"\0", 1)[0])

    @staticmethod
    def _slot_with_start_color(raw: bytes, start_color: int | None) -> bytes:
        """Prefix the final rendered slot, including Warcraft's player name."""
        original = bytes(raw)
        content = original.split(b"\0", 1)[0]
        if not content or start_color is None:
            return original[:100].ljust(100, b"\0")
        color = int(start_color) & 0xFF
        if not 1 <= color <= 6:
            raise ValueError(f"Invalid native message color control: 0x{color:02X}")
        if content[0] != color:
            content = bytes([color]) + content
        return (content[:99] + b"\0").ljust(100, b"\0")

    @staticmethod
    def _restore_slot_operations(
        snapshots: list[tuple[int, bytes]],
        indices: set[int],
    ) -> list[tuple]:
        return [
            ("write_bytes_indirect", snapshots[index][0], snapshots[index][1])
            for index in sorted(indices)
        ]

    def _native_player_name(self, player: int) -> str:
        if not 0 <= int(player) <= 7:
            return f"Player {int(player) + 1}"
        raw = self.pm.read_bytes(self.message_path["player_names"] + int(player) * 56, 56)
        name = raw.split(b"\0", 1)[0].decode("cp1252", "replace").strip()
        return name or f"Player {int(player) + 1}"

    @staticmethod
    def _raw_slot_text(text: str, *, label: str) -> bytes:
        raw = text.encode("cp1252", "replace")
        # Remaster retains the source-era 100-byte slot contract. Keep one byte
        # for NUL; trimming is preferable to corrupting the adjacent slot.
        if len(raw) > 99:
            raw = raw[:99]
        if not raw:
            raise ValueError(f"Expanded {label} cannot be empty")
        return raw + b"\0"

    @staticmethod
    def _colored_local_message(text: str, start_color: int | None, *, label: str) -> bytes:
        raw = text.encode("cp1252", "replace")
        if start_color is not None:
            raw = bytes([int(start_color) & 0xFF]) + raw
        if len(raw) > 99:
            raw = raw[:99]
        if not raw or raw == b"\0":
            raise ValueError(f"Expanded {label} cannot be empty")
        return raw + b"\0"

    def _verify_native_message_slot(self, global_key: str, expected: bytes, label: str) -> None:
        """Verify the raw control and text reached a native HUD slot.

        The rolling chat inserter can word-wrap a long line into several slots,
        so comparing all 100 bytes against the original string is too strict.
        Verify the leading control byte when present and a short printable prefix;
        this catches sanitization to '?' without rejecting native word wrapping.
        """
        pointer = self._message_slot_pointer(global_key)
        actual = self.pm.read_bytes(pointer, 100).split(b"\0", 1)[0]
        wanted = bytes(expected).split(b"\0", 1)[0]
        if wanted and 1 <= wanted[0] <= 6 and (not actual or actual[0] != wanted[0]):
            raise RuntimeError(
                f"{label} raw color verification failed at 0x{pointer:08X}: "
                f"expected control 0x{wanted[0]:02X}, read "
                + (f"0x{actual[0]:02X}" if actual else "an empty slot")
            )
        wanted_printable = bytes(value for value in wanted if not 1 <= value <= 6)
        actual_printable = bytes(value for value in actual if not 1 <= value <= 6)
        prefix = wanted_printable[: min(12, len(wanted_printable))]
        if prefix and prefix not in actual_printable:
            raise RuntimeError(
                f"{label} slot text verification failed at 0x{pointer:08X}: "
                f"expected prefix {prefix!r}, read {actual_printable[:24]!r}"
            )

    def _verify_native_player_chat(self, expected: bytes, label: str) -> None:
        """Find the just-inserted payload in Warcraft's seven rolling chat slots."""
        wanted = bytes(expected).split(b"\0", 1)[0]
        base_global = int(self.message_path["system_slot_pointer_global"])
        observed: list[bytes] = []
        for index in range(7):
            global_address = base_global - (7 - index) * 4
            pointer = int(self.pm.read_uint(global_address))
            if not pointer or not self._is_private_writable(pointer):
                continue
            actual = self.pm.read_bytes(pointer, 100).split(b"\0", 1)[0]
            observed.append(actual)
            if wanted and wanted in actual:
                return
        printable = bytes(value for value in wanted if not 1 <= value <= 6)
        for actual in observed:
            actual_printable = bytes(value for value in actual if not 1 <= value <= 6)
            if printable and printable[: min(12, len(printable))] in actual_printable:
                return
        raise RuntimeError(
            f"{label} was not found in Warcraft's seven native player-chat slots"
        )

    def _game_message(self, args: dict[str, Any], executing_player: int) -> None:
        template = str(args.get("text", "")).replace("\x00", " ")
        if not template.strip():
            raise ValueError("Game Message template cannot be empty")

        expanded = self._expand_message_template(template, executing_player)
        color_name = str(
            args.get("color", "Yellow / gold — native normal")
        ).strip()
        start_color = self._message_start_color(color_name)
        colored_text = self._apply_message_color_tags(expanded)
        # map_msg stores text and color separately. Do not prefix the text with
        # a control byte; write the exact sgbMsgColorTbl slot after map_msg picks it.
        local_raw = self._colored_local_message(
            colored_text, None, label="Game Message"
        )
        encoded = local_raw[:-1]
        if len(encoded) > MAX_NATIVE_MESSAGE_BYTES:
            raise ValueError(
                f"Expanded Game Message uses {len(encoded)} native bytes; Warcraft's "
                f"PM_STRING limit is {MAX_NATIVE_MESSAGE_BYTES}."
            )

        local_player = int(self.pm.read_uchar(self.message_path["local_player"]))
        if not 0 <= local_player <= 7:
            raise RuntimeError(f"Invalid native local-player index: {local_player}")
        recipients, local_show, remote_mask = self._native_message_recipients(
            args,
            local_player,
            default="Local player only",
            label="Game Message",
        )
        seconds = int(args.get("seconds", 4))
        if not 1 <= seconds <= 60:
            raise ValueError("Game Message display seconds must be 1 through 60")

        packet = self._native_message_packet(encoded, remote_mask, NET_MAX_NODES)
        operations: list[tuple] = []
        before_slots: list[tuple[int, bytes]] | None = None
        before_colors: bytes | None = None
        if local_show:
            before_slots = self._snapshot_native_message_slots()
            before_colors = self._snapshot_native_message_colors()
            operations.extend([
                ("write_bytes", self.dispatcher_chat_text_address, local_raw),
                (
                    "call",
                    self.message_path["map_msg"],
                    [
                        self.dispatcher_chat_text_address,
                        NET_MAX_NODES,
                        seconds * MILLISECONDS_PER_SECOND,
                    ],
                ),
            ])
            if start_color is not None:
                operations.append((
                    "write_bytes",
                    self.message_path["system_color"],
                    bytes([int(start_color) & 0xFF]),
                ))
            # Source map_msg clears the first byte of all eight slots before it
            # inserts either message type. Restore the seven rolling Player Chat
            # slots after the system insertion so game information no longer
            # erases visible chat.
            operations.extend(
                self._restore_slot_operations(before_slots, set(range(7)))
            )
            operations.extend(
                self._restore_message_color_operations(before_colors, set(range(7)))
            )
        if remote_mask:
            operations.extend([
                ("write_bytes", self.dispatcher_chat_packet_address, bytes(packet)),
                (
                    "call",
                    self.message_path["net_send_msg_all"],
                    [self.dispatcher_chat_packet_address],
                ),
            ])
        self._dispatch_ops(operations)
        if local_show:
            self._verify_native_message_slot(
                "system_slot_pointer_global", local_raw, "Game Message"
            )
            if start_color is not None:
                actual_color = int(self.pm.read_uchar(self.message_path["system_color"]))
                if actual_color != int(start_color):
                    raise RuntimeError(
                        f"Game Message color verification failed: expected "
                        f"0x{int(start_color):02X}, read 0x{actual_color:02X}"
                    )
        if bool(args.get("also_log", True)):
            self.log(
                f"GAME MESSAGE [{recipients}, {color_name}, {seconds}s]: "
                f"{self._message_log_text(colored_text)}"
            )

    @staticmethod
    def _player_chat_sender(
        sender_name: str, executing_player: int, local_player: int
    ) -> int:
        sender_name = sender_name.strip()
        if sender_name == "Current trigger player":
            sender = int(executing_player)
        elif sender_name == "Local player":
            sender = int(local_player)
        elif sender_name.startswith("Player "):
            try:
                sender = int(sender_name.split()[1]) - 1
            except (ValueError, IndexError) as exc:
                raise ValueError(f"Unknown Player Chat sender: {sender_name}") from exc
        else:
            raise ValueError(f"Unknown Player Chat sender: {sender_name}")
        if not 0 <= sender <= 7:
            raise ValueError(
                "Native Player Chat sender must resolve to Player 1 through Player 8"
            )
        return sender

    def _player_chat(self, args: dict[str, Any], executing_player: int) -> None:
        template = str(args.get("text", "")).replace("\x00", " ")
        if not template.strip():
            raise ValueError("Player Chat template cannot be empty")

        expanded = self._expand_message_template(template, executing_player)
        color_name = str(
            args.get("color", "Native sender color — no override")
        ).strip()
        start_color = self._message_start_color(color_name)
        colored_text = self._apply_message_color_tags(expanded)
        # Player-chat text and color live in separate native arrays. The final
        # rotating slot is discovered after map_msg returns, then its color byte
        # is written directly.
        local_raw = self._colored_local_message(
            colored_text, None, label="Player Chat"
        )
        encoded = local_raw[:-1]
        if not encoded:
            raise ValueError("Expanded Player Chat cannot be empty")
        if len(encoded) > MAX_NATIVE_MESSAGE_BYTES:
            raise ValueError(
                f"Expanded Player Chat uses {len(encoded)} native bytes; Warcraft's "
                f"PM_STRING limit is {MAX_NATIVE_MESSAGE_BYTES}."
            )

        local_player = int(self.pm.read_uchar(self.message_path["local_player"]))
        if not 0 <= local_player <= 7:
            raise RuntimeError(f"Invalid native local-player index: {local_player}")
        sender_name = str(args.get("sender", "Current trigger player"))
        sender = self._player_chat_sender(sender_name, executing_player, local_player)
        recipients, local_show, remote_mask = self._native_message_recipients(
            args,
            local_player,
            default="All active players",
            label="Player Chat",
        )

        packet = self._native_message_packet(encoded, remote_mask, sender)
        before_slots: list[tuple[int, bytes]] | None = None
        before_colors: bytes | None = None
        if local_show:
            before_slots = self._snapshot_native_message_slots()
            before_colors = self._snapshot_native_message_colors()
            # Public map_msg is the real PM_STRING receiver path. It formats the
            # player name and advances Warcraft's native chat index, but its
            # source also clears every message slot first. Run it once, inspect
            # which rolling slot(s) it selected, then restore only the slots it
            # did not replace.
            self._dispatch_ops([
                ("write_bytes", self.dispatcher_chat_text_address, local_raw),
                (
                    "call",
                    self.message_path["map_msg"],
                    [
                        self.dispatcher_chat_text_address,
                        sender,
                        NATIVE_CHAT_DISPLAY_DELAY,
                    ],
                ),
            ])

            after_slots = self._snapshot_native_message_slots()
            new_indices = {
                index for index in range(7)
                if self._slot_has_text(after_slots[index][1])
            }
            if not new_indices:
                raise RuntimeError(
                    "Player Chat reached map_msg, but no rolling chat slot was populated"
                )

            restore_indices = set(range(8)) - new_indices
            restore_operations = self._restore_slot_operations(
                before_slots, restore_indices
            )
            restore_operations.extend(
                self._restore_message_color_operations(before_colors, restore_indices)
            )
            if start_color is not None:
                color_table = int(self.message_path["color_table"])
                for index in sorted(new_indices):
                    restore_operations.append((
                        "write_bytes", color_table + index,
                        bytes([int(start_color) & 0xFF]),
                    ))
            if remote_mask:
                restore_operations.extend([
                    ("write_bytes", self.dispatcher_chat_packet_address, bytes(packet)),
                    (
                        "call",
                        self.message_path["net_send_msg_all"],
                        [self.dispatcher_chat_packet_address],
                    ),
                ])
            self._dispatch_ops(restore_operations)
        elif remote_mask:
            self._dispatch_ops([
                ("write_bytes", self.dispatcher_chat_packet_address, bytes(packet)),
                (
                    "call",
                    self.message_path["net_send_msg_all"],
                    [self.dispatcher_chat_packet_address],
                ),
            ])

        if local_show:
            self._verify_native_player_chat(local_raw, "Player Chat")
            if start_color is not None:
                color_table = int(self.message_path["color_table"])
                for index in sorted(new_indices):
                    actual_color = int(self.pm.read_uchar(color_table + index))
                    if actual_color != int(start_color):
                        raise RuntimeError(
                            f"Player Chat color verification failed for slot {index}: "
                            f"expected 0x{int(start_color):02X}, read 0x{actual_color:02X}"
                        )
        if bool(args.get("also_log", True)):
            self.log(
                f"PLAYER CHAT [as Player {sender + 1}, {recipients}, {color_name}]: "
                f"{self._message_log_text(colored_text)}"
            )


    @staticmethod
    def _spell_sound_id(value: Any) -> int:
        if isinstance(value, int):
            sound_id = value
        else:
            text = str(value).strip()
            try:
                sound_id = int(text, 0)
            except ValueError:
                key = "".join(character for character in text.casefold() if character.isalnum())
                names = {
                    "".join(character for character in name.casefold() if character.isalnum()): index
                    for index, name in enumerate(SPELL_SOUND_NAMES)
                }
                names.update({
                    "decay": 1,
                    "dnd": 1,
                    "deathcoil": 2,
                    "flameshield": 4,
                    "fireshield": 4,
                    "heal": 6,
                    "icestorm": 8,
                    "invisible": 9,
                    "invis": 9,
                    "eye": 10,
                    "morph": 11,
                    "raisedead": 13,
                    "runes": 14,
                    "rune": 14,
                    "armor": 15,
                    "armour": 15,
                })
                if key not in names:
                    raise ValueError(f"Unknown Warcraft spell sound: {value}")
                sound_id = names[key]
        if 69 <= sound_id <= 85:
            sound_id -= 69
        if not 0 <= sound_id < len(SPELL_SOUND_NAMES):
            raise ValueError(
                "Spell sound ID must be relative 0-16 or native Warcraft ID 69-85"
            )
        return sound_id

    def _live_rune(self, x: int, y: int) -> tuple[int, int] | None:
        for slot in range(MAX_RUNES):
            delay = self.pm.read_ushort(self.base + RUNE_DELAY_RVA + slot * 2)
            if not delay:
                continue
            rune_x = self.pm.read_uchar(self.base + RUNE_X_RVA + slot)
            rune_y = self.pm.read_uchar(self.base + RUNE_Y_RVA + slot)
            if (rune_x, rune_y) == (x, y):
                return slot, delay
        return None

    def _active_runes(self, args: dict[str, Any] | None = None) -> list[tuple[int, int, int, int]]:
        result: list[tuple[int, int, int, int]] = []
        for slot in range(MAX_RUNES):
            delay = self.pm.read_ushort(self.base + RUNE_DELAY_RVA + slot * 2)
            if not delay:
                continue
            x = self.pm.read_uchar(self.base + RUNE_X_RVA + slot)
            y = self.pm.read_uchar(self.base + RUNE_Y_RVA + slot)
            if 0 <= x < self.map_width and 0 <= y < self.map_height:
                result.append((slot, x, y, delay))
        location_name = (args or {}).get("location")
        if location_name and location_name != "Anywhere" and self.scenario:
            location = next(
                (item for item in self.scenario.locations if item.name == location_name),
                None,
            )
            if not location:
                raise ValueError(f"Unknown location: {location_name}")
            result = [
                rune for rune in result
                if location.left <= rune[1] <= location.right
                and location.top <= rune[2] <= location.bottom
            ]
        return result

    def _cast_rune_without_unit(self, x: int, y: int) -> tuple[int, int, Missile]:
        if not (0 <= x < self.map_width and 0 <= y < self.map_height):
            raise ValueError(f"Rune destination ({x},{y}) is outside the live map")
        if self._live_rune(x, y):
            raise RuntimeError(f"A Warcraft Rune is already active at ({x},{y})")
        accepted = self._call_cdecl(self.spell_path["place_rune"], [x, y])
        if accepted != 1:
            raise RuntimeError(
                f"Warcraft rejected Rune placement at ({x},{y}); "
                "the tile may be occupied or all 50 rune slots may be in use"
            )
        live = self._live_rune(x, y)
        if not live:
            raise RuntimeError("place_a_rune returned success but no live rune-table entry was found")
        slot, delay = live
        if not 0 < delay <= RUNE_TIME:
            raise RuntimeError(f"Rune slot {slot} has invalid live delay {delay}")
        pixel_x, pixel_y = (x << 5) + 16, (y << 5) + 16
        visual = next(
            (
                missile for missile in self._active_missiles()
                if missile.missile_type == BT_RUNE
                and (missile.x, missile.y) == (pixel_x, pixel_y)
            ),
            None,
        )
        if not visual:
            raise RuntimeError(
                f"Rune slot {slot} is active but Warcraft created no Rune visual at ({x},{y})"
            )
        return slot, delay, visual

    def _cast_runes_many_without_unit(
        self, points: list[tuple[int, int]]
    ) -> tuple[list[int], list[int]]:
        """Place several caster-free Runes in one simulation command."""
        if not points:
            return [], []
        active = self._active_runes()
        if len(active) + len(points) > MAX_RUNES:
            raise RuntimeError(
                f"Caster-free Runes needs {len(points)} free rune slots, but only "
                f"{MAX_RUNES - len(active)} remain"
            )
        occupied = [point for point in points if self._live_rune(*point)]
        if occupied:
            raise RuntimeError(
                "A Warcraft Rune is already active at: "
                + ", ".join(f"({x},{y})" for x, y in occupied)
            )
        free_bullets = self.max_bullets - len(self._active_missiles())
        if free_bullets < len(points):
            raise RuntimeError(
                f"Caster-free Runes needs {len(points)} projectile slots, but only "
                f"{free_bullets} are currently free"
            )
        self._dispatch_ops([
            ("call", self.spell_path["place_rune"], [x, y])
            for x, y in points
        ])
        slots: list[int] = []
        missing: list[tuple[int, int]] = []
        for x, y in points:
            live = self._live_rune(x, y)
            if not live:
                missing.append((x, y))
                continue
            slot, delay = live
            if not 0 < delay <= RUNE_TIME:
                raise RuntimeError(f"Rune slot {slot} has invalid live delay {delay}")
            slots.append(slot)
        if missing:
            raise RuntimeError(
                "Warcraft rejected caster-free Rune placement at: "
                + ", ".join(f"({x},{y})" for x, y in missing)
                + "; tiles may be occupied or the native rune table became full"
            )
        visuals = self._active_missiles()
        visual_slots: list[int] = []
        missing_visuals: list[tuple[int, int]] = []
        for x, y in points:
            pixel = ((x << 5) + 16, (y << 5) + 16)
            visual = next(
                (
                    missile for missile in visuals
                    if missile.missile_type == BT_RUNE
                    and (missile.x, missile.y) == pixel
                ),
                None,
            )
            if visual is None:
                missing_visuals.append((x, y))
            else:
                visual_slots.append((visual.address - self.bullet_pool) // BULLET_SIZE)
        if missing_visuals:
            raise RuntimeError(
                "Warcraft created Rune entries but no native visual at: "
                + ", ".join(f"({x},{y})" for x, y in missing_visuals)
            )
        return slots, visual_slots

    def _cast_holy_vision_without_unit(
        self, owner: int, x: int, y: int, duration: float = DEFAULT_VISION_DURATION
    ) -> tuple[list[tuple[int, int]], list[Missile], bool]:
        """Recreate action_vision's seven reveals without requiring a PTUnit."""
        if not 0 <= owner < 8:
            raise ValueError("Holy Vision fog ownership requires a player from 0 through 7")
        if not (0 <= x < self.map_width and 0 <= y < self.map_height):
            raise ValueError(f"Holy Vision destination ({x},{y}) is outside the live map")
        if not 0 <= duration <= MAX_VISION_DURATION:
            raise ValueError(
                f"Holy Vision duration must be from 0 through {MAX_VISION_DURATION:g} seconds"
            )
        regions = [
            (x + dx, y + dy)
            for dx, dy in VISION_OFFSETS
            if 0 <= x + dx < self.map_width and 0 <= y + dy < self.map_height
        ]
        if not regions:
            raise RuntimeError("Holy Vision has no valid reveal regions on the live map")

        operations: list[tuple] = []
        for region_x, region_y in regions:
            pixel_x = (region_x << 5) + 8
            pixel_y = (region_y << 5) + 8
            operations.extend((
                ("call", self.spell_path["vision_unmask"], [region_x, region_y, owner]),
                ("call", self.bullet_path["bullet_create_xy"], [pixel_x, pixel_y, BT_SPARKLE]),
                ("call", self.spell_path["vision_sound"], [pixel_x, pixel_y, SND_SPELL_HOLYVISION]),
            ))
        local_player = self.pm.read_uchar(self.base + LOCAL_PLAYER_RVA)
        centered = local_player == owner
        if centered:
            # The source recenters once for every subregion. The caster-free
            # action preserves all seven effects, then leaves the camera on the
            # requested center instead of the final diagonal offset.
            operations.append(("call", self.spell_path["vision_set_pos"], [x, y]))
        self._dispatch_ops(operations)

        expected_pixels = {((rx << 5) + 8, (ry << 5) + 8) for rx, ry in regions}
        visuals = [
            missile for missile in self._active_missiles()
            if missile.missile_type == BT_SPARKLE
            and (missile.x, missile.y) in expected_pixels
        ]
        visual_positions = {(missile.x, missile.y) for missile in visuals}
        missing = expected_pixels - visual_positions
        if missing:
            missing_tiles = sorted(((px - 8) >> 5, (py - 8) >> 5) for px, py in missing)
            raise RuntimeError(
                "Holy Vision reveal calls returned but Warcraft created no Sparkle at: "
                + ", ".join(f"({tx},{ty})" for tx, ty in missing_tiles)
            )
        if duration:
            self._active_visions.append(VisionEffect(
                owner=owner,
                regions=tuple(regions),
                expires=time.monotonic() + duration,
            ))
        return regions, visuals, centered

    def _cast_holy_vision_many_without_unit(
        self, owner: int, points: list[tuple[int, int]], duration: float
    ) -> tuple[int, int, bool]:
        """Apply source-faithful caster-free Holy Vision to several unit points.

        Points are batched so the stable mailbox stays well below its code limit.
        Dispatcher result replay makes completed batches idempotent when the trigger
        action parks between simulation updates. Overlapping reveal regions are
        deduplicated, avoiding redundant Sparkles and sounds.
        """
        if not 0 <= owner < 8:
            raise ValueError("Holy Vision fog ownership requires Player 1 through Player 8")
        if not 0 <= duration <= MAX_VISION_DURATION:
            raise ValueError(
                f"Holy Vision duration must be from 0 through {MAX_VISION_DURATION:g} seconds"
            )
        all_regions: list[tuple[int, int]] = []
        seen_regions: set[tuple[int, int]] = set()
        for x, y in points:
            for dx, dy in VISION_OFFSETS:
                region = (x + dx, y + dy)
                if (
                    0 <= region[0] < self.map_width
                    and 0 <= region[1] < self.map_height
                    and region not in seen_regions
                ):
                    seen_regions.add(region)
                    all_regions.append(region)
        if not all_regions:
            raise RuntimeError("Holy Vision has no valid reveal regions on the live map")
        free_bullets = self.max_bullets - len(self._active_missiles())
        if free_bullets < len(all_regions):
            raise RuntimeError(
                f"Multi-point Holy Vision needs {len(all_regions)} Sparkle slots, but "
                f"only {free_bullets} projectile slots are currently free. Use fewer "
                "target points or wait for existing projectiles to clear."
            )

        # Batch the globally deduplicated reveal regions. Thirty-two regions encode
        # 96 native calls and stay comfortably below the mailbox's 0x1000 code area.
        # Using all_regions here is important: two target units can share one of the
        # seven Holy Vision subregions even when they fall in different batches.
        for batch_start in range(0, len(all_regions), VISION_REGIONS_PER_BATCH):
            batch_regions = all_regions[
                batch_start:batch_start + VISION_REGIONS_PER_BATCH
            ]
            operations: list[tuple] = []
            for region_x, region_y in batch_regions:
                pixel_x = (region_x << 5) + 8
                pixel_y = (region_y << 5) + 8
                operations.extend((
                    ("call", self.spell_path["vision_unmask"], [region_x, region_y, owner]),
                    ("call", self.bullet_path["bullet_create_xy"], [pixel_x, pixel_y, BT_SPARKLE]),
                    ("call", self.spell_path["vision_sound"], [pixel_x, pixel_y, SND_SPELL_HOLYVISION]),
                ))
            self._dispatch_ops(operations)

        local_player = self.pm.read_uchar(self.base + LOCAL_PLAYER_RVA)
        centered = local_player == owner
        if centered:
            final_x, final_y = points[-1]
            self._dispatch_ops([
                ("call", self.spell_path["vision_set_pos"], [final_x, final_y])
            ])
        if duration:
            self._active_visions.append(VisionEffect(
                owner=owner,
                regions=tuple(all_regions),
                expires=time.monotonic() + duration,
            ))
        return len(all_regions), len(all_regions), centered

    @staticmethod
    def _holy_vision_duration(value: Any) -> float:
        if value is None:
            return DEFAULT_VISION_DURATION
        if isinstance(value, str) and value.strip().casefold() in {
            "vanilla", "native", "normal", "pulse", "one pulse"
        }:
            return 0.0
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "Holy Vision duration must be Vanilla or a number of seconds"
            ) from exc

    def _refresh_holy_visions(self) -> None:
        """Keep timed reveal areas visible without replaying cast feedback."""
        now = time.monotonic()
        remaining: list[VisionEffect] = []
        for effect in self._active_visions:
            if now >= effect.expires:
                self.log(
                    f"VISION EXPIRED: P{effect.owner + 1} timed Holy Vision returned to normal fog"
                )
                continue
            self._dispatch_ops([
                ("call", self.spell_path["vision_unmask"], [x, y, effect.owner])
                for x, y in effect.regions
            ])
            remaining.append(effect)
        self._active_visions = remaining

    @staticmethod
    def _spell_action_busy(unit: Unit) -> bool:
        return (
            SPELL_VISION <= int(unit.action) <= SPELL_ROT
            or SPELL_VISION <= int(unit.next_action) <= SPELL_ROT
        )

    def _auto_spell_manages_caster(self, unit: Unit) -> bool:
        """Return whether the unit belongs to an enabled automatic caster owner."""
        return (
            int(unit.owner) in getattr(self, "auto_spellcasting", {})
            and int(unit.unit_type) in (
                MAGE_CASTER_TYPES | PALADIN_CASTER_TYPES
                | OGRE_MAGE_CASTER_TYPES | DEATH_KNIGHT_CASTER_TYPES
            )
        )

    @staticmethod
    def _auto_spell_caster_parked(unit: Unit) -> bool:
        """Require a clean target-less guard state before publishing a spell.

        The two observed Remaster crashes both entered a unit-target spell while
        Attack Location remained queued as action 10.  Parking first prevents the
        attack path from clearing Unit+0x88 inside action_heal/action_fireshield.
        """
        action = int(unit.action)
        next_action = int(unit.next_action)
        if int(unit.target_unit) != 0:
            return False
        movement_or_attack = set(range(3, 13)) | set(range(15, 22))
        if action in movement_or_attack or next_action in movement_or_attack:
            return False
        if SPELL_VISION <= action <= SPELL_ROT:
            return False
        if SPELL_VISION <= next_action <= SPELL_ROT:
            return False
        return action in {2, 13, 14, 32, 33} and next_action in {2, 13, 14, 32, 33, 60}

    def _spell_ready_casters(
        self,
        casters: list[Unit],
        args: dict[str, Any],
        spell_name: str,
    ) -> tuple[list[Unit], list[str]]:
        """Limit casters and keep repeated triggers from overwriting live casts."""
        amount_arg = args.get("amount", 1)
        if amount_arg != "All":
            casters = casters[:max(0, min(64, int(amount_arg)))]
        if bool(args.get("interrupt_casters", False)):
            return list(casters), []
        ready: list[Unit] = []
        skipped: list[str] = []
        for caster in casters:
            if self._spell_action_busy(caster):
                skipped.append(
                    f"slot {(caster.address-self.unit_pool)//UNIT_SIZE} already casting "
                    f"action {caster.action}/{caster.next_action}"
                )
            else:
                ready.append(caster)
        if skipped:
            self.log(
                f"{spell_name.upper()} SAFE TARGETING: skipped {len(skipped)} busy caster(s); "
                "enable Interrupt current caster orders only when intentional"
            )
        return ready, skipped

    def _unit_type_flags(self, unit_type: int) -> int:
        if not 0 <= int(unit_type) < len(UNIT_NAMES):
            return 0
        return int(self.pm.read_uint(self.base + UNIT_IS_TABLE_RVA + int(unit_type) * 4))

    def _unit_is_flyer_type(self, unit_type: int) -> bool:
        return bool(self._unit_type_flags(unit_type) & IS_FLYER)

    def _spell_unit_hp_max(self, unit: Unit) -> int:
        value = int(self.pm.read_ushort(self.base + UNIT_HP_TABLE_RVA + unit.unit_type * 2))
        return max(1, value)

    def _spell_health_allowed(
        self,
        unit: Unit,
        args: dict[str, Any],
        default_condition: str = "Any health",
    ) -> bool:
        condition = str(args.get("target_health", "Spell default") or "Spell default")
        if condition.casefold() == "spell default":
            condition = default_condition
        hp_max = self._spell_unit_hp_max(unit)
        value = int(args.get("target_health_value", 50) or 50)
        key = condition.casefold()
        if key in {"any", "any health"}:
            return True
        if key in {"wounded", "wounded only"}:
            return unit.health < hp_max
        if key in {"at or below %", "at or below percent", "below %"}:
            return unit.health * 100 <= hp_max * max(0, min(100, value))
        if key in {"at or above %", "at or above percent", "above %"}:
            return unit.health * 100 >= hp_max * max(0, min(100, value))
        if key in {"at or below hp", "below hp"}:
            return unit.health <= max(0, value)
        if key in {"at or above hp", "above hp"}:
            return unit.health >= max(0, value)
        raise ValueError(f"Unknown spell target health condition: {condition}")

    def _spell_target_sort_key(
        self,
        caster: Unit,
        target: Unit,
        args: dict[str, Any],
    ) -> tuple[Any, ...]:
        mode = str(args.get("target_selection", "Nearest valid") or "Nearest valid").casefold()
        distance = (target.x - caster.x) ** 2 + (target.y - caster.y) ** 2
        hp_max = self._spell_unit_hp_max(target)
        missing = max(0, hp_max - target.health)
        ratio_num = target.health * 100000
        if mode in {"most wounded", "largest missing hp"}:
            return (-missing, distance, target.address)
        if mode in {"lowest health %", "lowest health percent"}:
            return (ratio_num // hp_max, distance, target.address)
        if mode in {"highest health %", "highest health percent"}:
            return (-(ratio_num // hp_max), distance, target.address)
        if mode in {"lowest current hp", "lowest hp"}:
            return (target.health, distance, target.address)
        if mode in {"highest current hp", "highest hp"}:
            return (-target.health, distance, target.address)
        if mode in {"nearest then most wounded", "nearest / most wounded"}:
            return (distance, -missing, target.address)
        return (distance, target.address)

    def _spell_assign_unique_targets(
        self,
        casters: list[Unit],
        targets: list[Unit],
        args: dict[str, Any],
        *,
        default_health: str = "Any health",
        exclude_self: bool = False,
    ) -> tuple[list[tuple[Unit, Unit]], list[str]]:
        """Assign at most one distinct target per caster.

        Native spell orders keep a raw PTUnit pointer in each caster.  Giving
        several casters the same changing/dying target is the unsafe pattern that
        caused multi-target Bloodlust/Polymorph crashes.  Reservations are made
        before any native order is queued, so a target cannot be reused in the
        same trigger action even if its effect has not started yet.
        """
        health_filtered = [
            target for target in targets
            if self._spell_health_allowed(target, args, default_health)
        ]
        target_amount = args.get("target_amount", "All")
        limit = len(casters) if target_amount == "All" else max(0, min(64, int(target_amount)))
        allow_self = bool(args.get("allow_self_target", True))
        available = list(health_filtered)
        assignments: list[tuple[Unit, Unit]] = []
        skipped: list[str] = []
        for caster in casters:
            if len(assignments) >= limit:
                break
            eligible = [
                target for target in available
                if not ((exclude_self or not allow_self) and target.address == caster.address)
            ]
            if not eligible:
                skipped.append(
                    f"caster slot {(caster.address-self.unit_pool)//UNIT_SIZE}: no remaining valid target"
                )
                continue
            target = min(
                eligible,
                key=lambda candidate: self._spell_target_sort_key(caster, candidate, args),
            )
            assignments.append((caster, target))
            available = [candidate for candidate in available if candidate.address != target.address]
        return assignments, skipped

    def _spell_queue_unit_target(
        self,
        caster: Unit,
        target: Unit,
        spell_id: int,
        spell_name: str,
    ) -> tuple[Unit, Unit, int] | None:
        action_global = int(self.spell_path["action_type_global"])
        before_action_type = self.pm.read_ushort(action_global)
        if before_action_type != 0:
            self.log(
                f"{spell_name.upper()} SKIPPED: gwActionType busy with "
                f"action {before_action_type}"
            )
            return None
        self._dispatch_ops([
            ("write_word", action_global, spell_id),
            (
                "call",
                self.order_callees["set_target"],
                [caster.address, 0, 0, target.address, self.spell_path["do_unit_spell"]],
            ),
            ("write_word", action_global, 0),
        ])
        if self.pm.read_ushort(action_global) != 0:
            raise RuntimeError(f"{spell_name} order failed to restore gwActionType")
        caster_data = self.pm.read_bytes(caster.address, UNIT_SIZE)
        target_data = self.pm.read_bytes(target.address, UNIT_SIZE)
        if not self._record_is_allocated(caster_data) or not self._record_is_allocated(target_data):
            self.log(
                f"{spell_name.upper()} SKIPPED: caster or target became inactive while queueing"
            )
            return None
        current = self._decode_unit(caster.address, caster_data)
        current_target = self._decode_unit(target.address, target_data)
        target_pointer = int.from_bytes(caster_data[0x88:0x8C], "little")
        return current, current_target, target_pointer

    # ------------------------------------------------------------------
    # Automatic native spellcasting
    # ------------------------------------------------------------------
    @staticmethod
    def _auto_spell_distance_sq(left: Unit, right: Unit) -> int:
        return (int(left.x) - int(right.x)) ** 2 + (int(left.y) - int(right.y)) ** 2

    def _auto_spell_cluster(
        self,
        caster: Unit,
        enemies: list[Unit],
        cast_range: int,
        radius: int = 3,
    ) -> tuple[Unit | None, int]:
        in_range = [
            enemy for enemy in enemies
            if self._auto_spell_distance_sq(caster, enemy) <= cast_range * cast_range
        ]
        if not in_range:
            return None, 0
        best: tuple[int, int, int, Unit] | None = None
        radius_sq = radius * radius
        for center in in_range:
            count = sum(
                1 for other in in_range
                if (int(center.x) - int(other.x)) ** 2
                + (int(center.y) - int(other.y)) ** 2 <= radius_sq
            )
            distance = self._auto_spell_distance_sq(caster, center)
            candidate = (-count, distance, int(center.address), center)
            if best is None or candidate[:3] < best[:3]:
                best = candidate
        assert best is not None
        return best[3], -best[0]

    def _auto_spell_plan_for_caster(
        self,
        caster: Unit,
        allies: list[Unit],
        enemies: list[Unit],
        config: dict[str, Any],
        reserved_targets: set[int],
    ) -> dict[str, Any] | None:
        caster_type = int(caster.unit_type)
        if caster_type in MAGE_CASTER_TYPES:
            caster_class = "Mage"
        elif caster_type in PALADIN_CASTER_TYPES:
            caster_class = "Paladin"
        elif caster_type in OGRE_MAGE_CASTER_TYPES:
            caster_class = "Ogre-Mage"
        elif caster_type in DEATH_KNIGHT_CASTER_TYPES:
            caster_class = "Death Knight"
        else:
            return None

        cast_range = int(config.get("range", 16))
        range_sq = cast_range * cast_range
        reserve = int(config.get("mana_reserve", 0))
        effective_mana = 255 if bool(config.get("keep_mana_full", False)) else int(caster.mana)
        utility = bool(config.get("utility_spells", False))
        profile = str(config.get("profile", "Balanced combat"))

        nearby_enemies = [
            unit for unit in enemies
            if self._auto_spell_distance_sq(caster, unit) <= range_sq
            and int(unit.address) not in reserved_targets
        ]
        nearby_allies = [
            unit for unit in allies
            if self._auto_spell_distance_sq(caster, unit) <= range_sq
            and not (int(unit.sflags) & 0x0008)
        ]
        nearest_enemy = min(
            nearby_enemies,
            key=lambda unit: (self._auto_spell_distance_sq(caster, unit), int(unit.address)),
            default=None,
        )
        cluster_center, cluster_count = self._auto_spell_cluster(
            caster, nearby_enemies, cast_range
        )

        def enough(cost_key: str) -> tuple[bool, int]:
            cost = int(self.spell_path[cost_key])
            return effective_mana >= cost + reserve, cost

        def unit_plan(name: str, spell_id: int, cost: int, target: Unit, score: int) -> dict[str, Any]:
            return {
                "name": name, "spell_id": spell_id, "cost": cost,
                "caster": caster, "target": target, "x": 0, "y": 0,
                "score": score, "class": caster_class,
            }

        def area_plan(name: str, spell_id: int, cost: int, x: int, y: int, score: int) -> dict[str, Any]:
            return {
                "name": name, "spell_id": spell_id, "cost": cost,
                "caster": caster, "target": None, "x": int(x), "y": int(y),
                "score": score, "class": caster_class,
            }

        options: list[dict[str, Any]] = []

        if caster_class == "Mage":
            ok, cost = enough("flame_shield_cost")
            if ok:
                frontline = [
                    ally for ally in nearby_allies
                    if int(ally.unit_type) < FIRST_BUILDING_TYPE
                    and self._unit_is_fleshy_type(int(ally.unit_type))
                    and int(ally.fire) == 0
                    and any(self._auto_spell_distance_sq(ally, enemy) <= 16 for enemy in nearby_enemies)
                    and int(ally.address) not in reserved_targets
                ]
                if frontline:
                    target = min(frontline, key=lambda unit: (-self._spell_unit_hp_max(unit), self._auto_spell_distance_sq(caster, unit)))
                    options.append(unit_plan("Flame Shield", SPELL_FLAME_SHIELD, cost, target, 112))
            ok, cost = enough("polymorph_cost")
            if ok:
                candidates = [
                    enemy for enemy in nearby_enemies
                    if int(enemy.unit_type) < FIRST_BUILDING_TYPE
                    and self._unit_is_fleshy_type(int(enemy.unit_type))
                    and int(enemy.unit_type) != 57
                ]
                if candidates:
                    target = max(candidates, key=lambda unit: (self._spell_unit_hp_max(unit), -self._auto_spell_distance_sq(caster, unit)))
                    options.append(unit_plan("Polymorph", SPELL_POLYMORPH, cost, target, 108))
            ok, cost = enough("blizzard_cost")
            if ok and cluster_center is not None and cluster_count >= 3:
                options.append(area_plan("Blizzard", SPELL_BLIZZARD, cost, cluster_center.x, cluster_center.y, 100 + cluster_count))
            ok, cost = enough("slow_cost")
            if ok:
                candidates = [enemy for enemy in nearby_enemies if int(enemy.warp) >= 0]
                if candidates:
                    target = min(candidates, key=lambda unit: (self._auto_spell_distance_sq(caster, unit), int(unit.address)))
                    options.append(unit_plan("Slow", SPELL_SLOW, cost, target, 92))
            ok, cost = enough("fireball_cost")
            if ok and nearest_enemy is not None:
                options.append(area_plan("Fireball", SPELL_FIREBALL, cost, nearest_enemy.x, nearest_enemy.y, 84))
            ok, cost = enough("invis_cost")
            if utility and ok:
                candidates = [
                    ally for ally in nearby_allies
                    if int(ally.invis) == 0 and int(ally.address) != int(caster.address)
                    and int(ally.address) not in reserved_targets
                ]
                if candidates:
                    target = min(candidates, key=lambda unit: (int(unit.health) * 100 // self._spell_unit_hp_max(unit), self._auto_spell_distance_sq(caster, unit)))
                    options.append(unit_plan("Invisibility", SPELL_INVIS, cost, target, 68))

        elif caster_class == "Paladin":
            ok, cost = enough("heal_cost")
            if ok:
                wounded = [
                    ally for ally in nearby_allies
                    if int(ally.unit_type) < FIRST_BUILDING_TYPE
                    and self._unit_is_fleshy_type(int(ally.unit_type))
                    and int(ally.health) < self._spell_unit_hp_max(ally)
                    and int(ally.address) not in reserved_targets
                ]
                if wounded:
                    target = max(
                        wounded,
                        key=lambda unit: (
                            self._spell_unit_hp_max(unit) - int(unit.health),
                            -self._auto_spell_distance_sq(caster, unit),
                        ),
                    )
                    missing = self._spell_unit_hp_max(target) - int(target.health)
                    if missing >= 4:
                        options.append(unit_plan("Healing", SPELL_HEAL, cost, target, 130 + min(40, missing)))
            ok, cost = enough("exorcism_cost")
            undead = [enemy for enemy in nearby_enemies if self._unit_is_undead_type(int(enemy.unit_type))]
            undead_center, undead_count = self._auto_spell_cluster(caster, undead, cast_range)
            if ok and undead_center is not None:
                options.append(area_plan("Exorcism", SPELL_EXORCISM, cost, undead_center.x, undead_center.y, 105 + undead_count))
            ok, cost = enough("vision_cost")
            if utility and ok and cluster_center is not None:
                options.append(area_plan("Holy Vision", SPELL_VISION, cost, cluster_center.x, cluster_center.y, 55))

        elif caster_class == "Ogre-Mage":
            ok, cost = enough("bloodlust_cost")
            if ok:
                candidates = [
                    ally for ally in nearby_allies
                    if int(ally.unit_type) < FIRST_BUILDING_TYPE
                    and self._unit_is_fleshy_type(int(ally.unit_type))
                    and int(ally.rage) == 0
                    and int(ally.address) not in reserved_targets
                ]
                if candidates:
                    target = max(candidates, key=lambda unit: (self._spell_unit_hp_max(unit), -self._auto_spell_distance_sq(caster, unit)))
                    options.append(unit_plan("Bloodlust", SPELL_BLOODLUST, cost, target, 125))
            ok, cost = enough("runes_cost")
            if ok and cluster_center is not None and cluster_count >= 2:
                options.append(area_plan("Runes", SPELL_RUNES, cost, cluster_center.x, cluster_center.y, 96 + cluster_count))
            ok, cost = enough("eye_cost")
            existing_eye = any(
                int(ally.owner) == int(caster.owner)
                and int(ally.unit_type) == 45
                and not (int(ally.sflags) & 0x0008)
                for ally in allies
            )
            if utility and ok and nearest_enemy is not None and not existing_eye:
                center = cluster_center or nearest_enemy
                options.append(area_plan("Eye of Kilrogg", SPELL_EYE, cost, center.x, center.y, 50))

        else:  # Death Knight
            ok, cost = enough("armor_cost")
            if ok:
                wounded = [
                    ally for ally in nearby_allies
                    if int(ally.unit_type) < FIRST_BUILDING_TYPE
                    and self._unit_is_fleshy_type(int(ally.unit_type))
                    and int(ally.armor) == 0
                    and int(ally.health) * 100 <= self._spell_unit_hp_max(ally) * 45
                    and int(ally.address) not in reserved_targets
                ]
                if wounded:
                    target = min(wounded, key=lambda unit: (int(unit.health) * 100 // self._spell_unit_hp_max(unit), self._auto_spell_distance_sq(caster, unit)))
                    options.append(unit_plan("Unholy Armor", SPELL_ARMOR, cost, target, 128))
            ok, cost = enough("raisedead_cost")
            if ok:
                corpses = [
                    corpse for corpse in self.corpses()
                    if (int(corpse.x) - int(caster.x)) ** 2 + (int(corpse.y) - int(caster.y)) ** 2 <= range_sq
                ]
                if corpses:
                    corpse = min(corpses, key=lambda unit: ((int(unit.x)-int(caster.x))**2 + (int(unit.y)-int(caster.y))**2, int(unit.address)))
                    options.append(area_plan("Raise Dead", SPELL_RAISEDEAD, cost, corpse.x, corpse.y, 116))
            ok, cost = enough("rot_cost")
            if ok and cluster_center is not None and cluster_count >= 3:
                options.append(area_plan("Death and Decay", SPELL_ROT, cost, cluster_center.x, cluster_center.y, 110 + cluster_count))
            ok, cost = enough("whirlwind_cost")
            if ok and cluster_center is not None and cluster_count >= 3:
                options.append(area_plan("Whirlwind", SPELL_WHIRLWIND, cost, cluster_center.x, cluster_center.y, 98 + cluster_count))
            ok, cost = enough("drainlife_cost")
            if ok:
                candidates = [enemy for enemy in nearby_enemies if self._unit_is_fleshy_type(int(enemy.unit_type))]
                if candidates:
                    target = min(candidates, key=lambda unit: (self._auto_spell_distance_sq(caster, unit), int(unit.health)))
                    options.append(area_plan("Death Coil", SPELL_DRAINLIFE, cost, target.x, target.y, 90))
            ok, cost = enough("haste_cost")
            if ok:
                candidates = [
                    ally for ally in nearby_allies
                    if int(ally.unit_type) < FIRST_BUILDING_TYPE
                    and self._unit_is_fleshy_type(int(ally.unit_type))
                    and int(ally.warp) <= 0
                    and int(ally.address) not in reserved_targets
                ]
                if candidates:
                    target = max(candidates, key=lambda unit: (self._spell_unit_hp_max(unit), -self._auto_spell_distance_sq(caster, unit)))
                    options.append(unit_plan("Haste", SPELL_HASTE, cost, target, 82))

        if not options:
            return None

        if profile == "Offensive":
            offensive = {
                "Blizzard", "Fireball", "Polymorph", "Slow", "Runes",
                "Exorcism", "Death and Decay", "Whirlwind", "Death Coil",
            }
            for option in options:
                if option["name"] in offensive:
                    option["score"] += 35
        elif profile == "Support":
            support = {
                "Healing", "Flame Shield", "Invisibility", "Bloodlust",
                "Haste", "Unholy Armor", "Holy Vision", "Eye of Kilrogg",
            }
            for option in options:
                if option["name"] in support:
                    option["score"] += 45
                else:
                    option["score"] -= 25
        elif profile == "Full spellbook rotation":
            key = self._unit_key(caster)
            options.sort(key=lambda option: (int(option["spell_id"]), -int(option["score"])))
            start = int(self._auto_spell_rotation.get(key, 0)) % len(options)
            choice = options[start]
            choice["rotation_next"] = start + 1
            return choice

        return max(options, key=lambda option: (int(option["score"]), -int(option["spell_id"])))

    def _consume_auto_spell_maintenance_dispatch(self) -> bool:
        """Consume an owner-less auto-cast mailbox command before triggers run.

        Automatic spellcasting executes from prepare_cycle rather than from a
        visible trigger action.  Its dispatcher owner is therefore None.  The
        normal trigger retry journal intentionally cannot consume that result,
        so maintenance owns this tiny completion path and blocks the rest of the
        engine cycle while the command is queued or executing.
        """
        pending = getattr(self, "_dispatch_inflight", None)
        if pending is not None:
            if pending.owner is not None:
                # A real trigger action owns the mailbox.  Leave it untouched so
                # the engine can resume that exact action below.
                return True
            state = int(self.pm.read_uint(pending.status_address))
            if state in (DISPATCH_STATE_QUEUED, DISPATCH_STATE_EXECUTING):
                return False
            if state == DISPATCH_STATE_COMPLETE:
                elapsed = time.monotonic() - pending.started_at
                self.pm.write_uint(pending.status_address, DISPATCH_STATE_IDLE)
                self._dispatch_inflight = None
                self._last_dispatch = time.monotonic()
                if elapsed >= 2.0:
                    self.log(
                        f"AUTO SPELL DISPATCH RECOVERED: simulation command completed "
                        f"after {elapsed:.1f}s"
                    )
                action_global = int(self.spell_path.get("action_type_global", 0))
                if action_global and int(self.pm.read_ushort(action_global)) != 0:
                    raise RuntimeError(
                        "Automatic spell command completed without restoring gwActionType"
                    )
                return True
            if state == DISPATCH_STATE_IDLE:
                # The game was restarted or the command was cancelled before it
                # entered the hook.  Drop the stale Python owner safely.
                self._dispatch_inflight = None
                return True
            raise RuntimeError(f"Unknown automatic spell dispatcher state: {state}")

        # Recover only owner-less leftovers from an older adapter.  A queued
        # command that has not started can be cancelled; an executing command
        # must finish before any trigger action is allowed to use the mailbox.
        state = int(self.pm.read_uint(self.dispatcher_status_address))
        if state == DISPATCH_STATE_COMPLETE:
            self.pm.write_uint(self.dispatcher_status_address, DISPATCH_STATE_IDLE)
            return True
        if state == DISPATCH_STATE_QUEUED:
            self.pm.write_uint(self.dispatcher_status_address, DISPATCH_STATE_IDLE)
            return True
        if state == DISPATCH_STATE_EXECUTING:
            return False
        if state != DISPATCH_STATE_IDLE:
            raise RuntimeError(f"Unknown simulation dispatcher state: {state}")
        return True

    def _auto_spell_revalidate_plan(
        self, plan: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Re-read caster/target records immediately before publishing a cast.

        Unit slots are recycled.  Address-only validation is insufficient during a
        large battle, so both allocation state and the native-verified unit token must
        still match the planning snapshot.  Invalid plans are dropped without
        touching gwActionType or Unit+0x88.
        """
        caster: Unit = plan["caster"]
        try:
            caster_data = self.pm.read_bytes(int(caster.address), UNIT_SIZE)
        except Exception:
            return None
        if not self._record_is_allocated(caster_data):
            return None
        current_caster = self._decode_unit(int(caster.address), caster_data)
        if (
            self._unit_key(current_caster) != self._unit_key(caster)
            or int(current_caster.owner) != int(caster.owner)
            or int(current_caster.unit_type) != int(caster.unit_type)
            or int(current_caster.sflags) & 0x0008
            or self._spell_action_busy(current_caster)
            or not self._auto_spell_caster_parked(current_caster)
        ):
            return None

        current_target: Unit | None = None
        target = plan.get("target")
        if target is not None:
            try:
                target_data = self.pm.read_bytes(int(target.address), UNIT_SIZE)
            except Exception:
                return None
            if not self._record_is_allocated(target_data):
                return None
            current_target = self._decode_unit(int(target.address), target_data)
            if (
                self._unit_key(current_target) != self._unit_key(target)
                or int(current_target.owner) != int(target.owner)
                or int(current_target.unit_type) != int(target.unit_type)
                or int(current_target.sflags) & 0x0008
            ):
                return None

        validated = dict(plan)
        validated["caster"] = current_caster
        validated["target"] = current_target
        return validated

    def _finalize_auto_spell_plans(
        self,
        plans: list[dict[str, Any]],
        cooldown_updates: list[tuple[tuple[int, int], float]],
        now: float,
    ) -> None:
        for key, due_at in cooldown_updates:
            self._auto_spell_cooldowns[key] = due_at
        guards = getattr(self, "_auto_spell_route_guards", None)
        parking = getattr(self, "_auto_spell_parking", None)
        parking_started = getattr(self, "_auto_spell_parking_started", None)
        if guards is not None:
            for plan in plans:
                key = self._unit_key(plan["caster"])
                guards.add(key)
                if parking is not None:
                    parking.discard(key)
                if parking_started is not None:
                    parking_started.pop(key, None)
        for plan in plans:
            if "rotation_next" in plan:
                self._auto_spell_rotation[self._unit_key(plan["caster"])] = int(
                    plan["rotation_next"]
                )
            config = plan["config"]
            if not bool(config.get("log_casts", True)):
                continue
            caster: Unit = plan["caster"]
            target = plan.get("target")
            target_text = (
                f"P{target.owner + 1} {UNIT_NAMES[target.unit_type]} "
                f"at ({target.x},{target.y})"
                if target is not None
                else f"({plan['x']},{plan['y']})"
            )
            delivery = (
                "source-equivalent atomic effect"
                if plan["name"] in {"Healing", "Flame Shield"}
                else "native spell order"
            )
            self.log(
                f"AUTO SPELL: P{caster.owner + 1} {UNIT_NAMES[caster.unit_type]} "
                f"slot {(caster.address-self.unit_pool)//UNIT_SIZE} queued "
                f"{plan['name']} -> {target_text}; mana {caster.mana}, "
                f"profile {config.get('profile', 'Balanced combat')}; {delivery}"
            )
        self._auto_spell_next_cycle = now + 0.20

    def _run_auto_spellcasting_cycle(
        self,
        world: list[Unit],
        *,
        force: bool = False,
        owner_filter: Any = "All",
    ) -> bool:
        """Choose and queue smart spells without removing casters from combat.

        Only casters that already have a useful spell plan enter the parking
        stage.  They are protected for that one cast, then the saved Attack
        Location route resumes after Warcraft leaves the spell action.  Casters
        with no valid spell remain under normal combat/route control.

        Returns False only when an owner-less maintenance command is still using
        Warcraft's simulation mailbox. TriggerEngine then skips the rest of that
        cycle so ordinary actions cannot race the auto-caster.
        """
        if not getattr(self, "auto_spellcasting", None):
            return True

        maintenance = self._action_context is None
        if maintenance:
            if not self._consume_auto_spell_maintenance_dispatch():
                return False
            # A real trigger action owns the mailbox. Leave it untouched so the
            # action can resume with its original dispatcher signature.
            if self._dispatch_inflight is not None:
                return True

        # Auto Cast Spells Now is a real trigger action and can be parked by the
        # dispatcher. Reuse the exact operations/plans on retry rather than
        # replanning after units have already entered native spell orders.
        action_key = self._action_context
        if not maintenance and action_key in self._auto_spell_action_cache:
            operations, plans, cooldown_updates, planned_at = self._auto_spell_action_cache[action_key]
            self._dispatch_ops(operations)
            self._auto_spell_action_cache.pop(action_key, None)
            action_global = int(self.spell_path["action_type_global"])
            if int(self.pm.read_ushort(action_global)) != 0:
                raise RuntimeError("Auto Spellcasting failed to restore gwActionType")
            self._finalize_auto_spell_plans(plans, cooldown_updates, planned_at)
            return True

        now = time.monotonic()
        if maintenance and not force and now < float(
            getattr(self, "_auto_spell_next_cycle", 0.0)
        ):
            return True

        action_global = int(self.spell_path["action_type_global"])
        if int(self.pm.read_ushort(action_global)) != 0:
            return True

        if str(owner_filter).strip().casefold() in {"all", "all players", ""}:
            owners = sorted(self.auto_spellcasting)
        else:
            owners = [int(owner_filter)]

        active = [
            unit for unit in world
            if 0 <= int(unit.owner) < 8
            and not (int(unit.sflags) & (0x0007 | 0x0008))
        ]
        current_by_key = {self._unit_key(unit): unit for unit in active}
        by_owner: dict[int, list[Unit]] = {owner: [] for owner in range(8)}
        for unit in active:
            by_owner[int(unit.owner)].append(unit)

        spell_guards = getattr(self, "_auto_spell_route_guards", set())
        parking_state = getattr(self, "_auto_spell_parking", set())
        parking_started = getattr(self, "_auto_spell_parking_started", {})

        # Drop stale pending records immediately. Address-only state is unsafe
        # because Warcraft recycles unit slots; the allocation token is part of
        # every key.
        for key in list(parking_state):
            unit = current_by_key.get(key)
            if unit is None or int(unit.owner) not in self.auto_spellcasting:
                parking_state.discard(key)
                parking_started.pop(key, None)
                spell_guards.discard(key)

        owner_context: dict[int, tuple[dict[str, Any], list[Unit], list[Unit], list[Unit]]] = {}
        for owner in owners:
            config = self.auto_spellcasting.get(owner)
            if config is None:
                continue
            relation_row = self._read_diplomacy_state(owner)[0]
            allies: list[Unit] = []
            enemies: list[Unit] = []
            for target_owner, units in by_owner.items():
                relation = int(relation_row[target_owner])
                if self._relation_is_allied(owner, target_owner, relation):
                    allies.extend(units)
                elif self._relation_is_enemy(owner, target_owner, relation):
                    enemies.extend(units)

            group_name = str(config.get("group", "")).strip()
            if group_name:
                group_keys = {self._unit_key(unit) for unit in self._group_units(group_name)}
            else:
                group_keys = set()
            casters = [
                unit for unit in by_owner.get(owner, [])
                if int(unit.unit_type) in (
                    MAGE_CASTER_TYPES | PALADIN_CASTER_TYPES
                    | OGRE_MAGE_CASTER_TYPES | DEATH_KNIGHT_CASTER_TYPES
                )
                and (not group_name or self._unit_key(unit) in group_keys)
                and not self._spell_action_busy(unit)
                and not (hasattr(self, "_effect_active") and self._effect_active(unit, "Silence"))
            ]
            casters.sort(key=lambda unit: (int(unit.address), int(unit.unit_type)))
            owner_context[owner] = (config, allies, enemies, casters)

        # Phase 1: finish only the casters that were selected on an earlier
        # cycle. No new caster is stopped while one-cast parking is pending.
        pending_keys = {
            key for key in parking_state
            if key in current_by_key and int(current_by_key[key].owner) in owners
        }
        plans: list[dict[str, Any]] = []
        cooldown_updates: list[tuple[tuple[int, int], float]] = []
        reserved_targets: set[int] = set()
        total_cap = 12
        waiting_for_park = False

        if pending_keys:
            for owner in owners:
                context = owner_context.get(owner)
                if context is None:
                    continue
                config, allies, enemies, casters = context
                owner_cap = int(config.get("max_casts", 2))
                owner_count = 0
                for caster in casters:
                    key = self._unit_key(caster)
                    if key not in pending_keys:
                        continue
                    if len(plans) >= total_cap or owner_count >= owner_cap:
                        waiting_for_park = True
                        continue
                    if not self._auto_spell_caster_parked(caster):
                        started = float(parking_started.get(key, now))
                        if now - started >= 0.85:
                            parking_state.discard(key)
                            parking_started.pop(key, None)
                            spell_guards.discard(key)
                            self.log(
                                f"AUTO SPELL PARK CANCELLED: P{caster.owner + 1} "
                                f"{UNIT_NAMES[caster.unit_type]} slot "
                                f"{(caster.address-self.unit_pool)//UNIT_SIZE} could not "
                                "settle safely; combat route released"
                            )
                        else:
                            waiting_for_park = True
                        continue

                    plan = self._auto_spell_plan_for_caster(
                        caster, allies, enemies, config, reserved_targets
                    )
                    if plan is None:
                        parking_state.discard(key)
                        parking_started.pop(key, None)
                        spell_guards.discard(key)
                        continue
                    target = plan.get("target")
                    if target is not None:
                        reserved_targets.add(int(target.address))
                    plan["config"] = config
                    plans.append(plan)
                    owner_count += 1
                    cooldown_updates.append((
                        key, now + float(config.get("cooldown", 2.5))
                    ))

            # If none of the pending casters can cast yet, do not park anyone
            # else. Existing combatants continue fighting and pending casters
            # either settle or are released by the timeout above.
            if not plans and (waiting_for_park or pending_keys & parking_state):
                self._auto_spell_next_cycle = now + 0.05
                return True

        # Phase 2: when no prior caster is waiting, select only casters that
        # actually have a valid spell. These are the only units interrupted.
        if not plans and not parking_state:
            new_parking: dict[tuple[int, int], Unit] = {}
            reserved_targets.clear()
            for owner in owners:
                context = owner_context.get(owner)
                if context is None:
                    continue
                config, allies, enemies, casters = context
                owner_cap = int(config.get("max_casts", 2))
                owner_count = 0
                for caster in casters:
                    if len(new_parking) >= total_cap or owner_count >= owner_cap:
                        break
                    key = self._unit_key(caster)
                    if key in spell_guards or key in parking_state:
                        continue
                    if not force and now < float(self._auto_spell_cooldowns.get(key, 0.0)):
                        continue
                    plan = self._auto_spell_plan_for_caster(
                        caster, allies, enemies, config, reserved_targets
                    )
                    if plan is None:
                        continue
                    target = plan.get("target")
                    if target is not None:
                        reserved_targets.add(int(target.address))
                    new_parking[key] = caster
                    parking_state.add(key)
                    parking_started[key] = now
                    spell_guards.add(key)
                    owner_count += 1

            if new_parking:
                operations = [
                    (
                        "call",
                        self.order_callees["set_target"],
                        [
                            int(caster.address), int(caster.x), int(caster.y), 0,
                            self.order_callees["do_move"],
                        ],
                    )
                    for _key, caster in sorted(
                        new_parking.items(), key=lambda item: item[1].address
                    )
                ]
                try:
                    self._dispatch_ops(operations)
                except ActionDeferred:
                    if maintenance:
                        return False
                    raise
                except Exception:
                    for key in new_parking:
                        parking_state.discard(key)
                        parking_started.pop(key, None)
                        spell_guards.discard(key)
                    raise
                self._auto_spell_next_cycle = now + 0.05
                self.log(
                    f"AUTO SPELL PARK: paused {len(new_parking)} selected caster(s) "
                    "for one cast; all other casters remain in combat"
                )
                return True

            self._auto_spell_next_cycle = now + 0.20
            return True

        if not plans:
            self._auto_spell_next_cycle = now + 0.10
            return True

        validated_plans: list[dict[str, Any]] = []
        for plan in plans:
            validated = self._auto_spell_revalidate_plan(plan)
            if validated is None:
                caster = plan["caster"]
                key = self._unit_key(caster)
                parking_state.discard(key)
                parking_started.pop(key, None)
                spell_guards.discard(key)
                self.log(
                    f"AUTO SPELL SKIPPED: P{caster.owner + 1} "
                    f"{UNIT_NAMES[caster.unit_type]} slot "
                    f"{(caster.address-self.unit_pool)//UNIT_SIZE} changed, "
                    "retargeted, or left its safe park before native dispatch; "
                    "combat route released"
                )
                continue
            validated_plans.append(validated)
        plans = validated_plans
        valid_caster_keys = {self._unit_key(plan["caster"]) for plan in plans}
        cooldown_updates = [
            item for item in cooldown_updates if item[0] in valid_caster_keys
        ]
        if not plans:
            self._auto_spell_next_cycle = now + 0.10
            return True

        # Publication keeps the one-cast route guard until Warcraft leaves the
        # spell action. Attack-route maintenance then consumes the guard for one
        # clean cycle and reissues the original destination on the next cycle.
        for plan in plans:
            spell_guards.add(self._unit_key(plan["caster"]))

        operations: list[tuple] = []
        for plan in plans:
            caster: Unit = plan["caster"]
            config = plan["config"]
            target = plan.get("target")
            keep_full = bool(config.get("keep_mana_full", False))
            if plan["name"] == "Healing" and target is not None:
                operations.append((
                    "safe_auto_heal",
                    int(caster.address), int(caster.token), int(caster.unit_type), int(caster.owner),
                    int(target.address), int(target.token), int(target.unit_type), int(target.owner),
                    int(self._spell_unit_hp_max(target)), int(plan["cost"]), keep_full,
                    int(self.spell_path["heal_visual"]), int(self.spell_path["slow_sound"]),
                ))
                continue
            if plan["name"] == "Flame Shield" and target is not None:
                operations.append((
                    "safe_auto_flame_shield",
                    int(caster.address), int(caster.token), int(caster.unit_type), int(caster.owner),
                    int(target.address), int(target.token), int(target.unit_type), int(target.owner),
                    int(plan["cost"]), keep_full,
                    int(self.spell_path["bullet_create_flame_shield"]),
                    int(self.spell_path["flame_sound"]),
                ))
                continue
            if keep_full:
                operations.append(("write_bytes", caster.address + 0x26, b"\xFF"))
            operations.append(("write_word", action_global, int(plan["spell_id"])))
            operations.append((
                "call",
                self.order_callees["set_target"],
                [
                    caster.address,
                    int(plan["x"]),
                    int(plan["y"]),
                    int(target.address) if target is not None else 0,
                    self.spell_path["do_unit_spell"],
                ],
            ))
            operations.append(("write_word", action_global, 0))

        if not maintenance:
            self._auto_spell_action_cache[action_key] = (
                operations, plans, cooldown_updates, now
            )
            try:
                self._dispatch_ops(operations)
            except ActionDeferred:
                raise
            else:
                self._auto_spell_action_cache.pop(action_key, None)
        else:
            signature = self._dispatch_signature(operations)
            try:
                self._dispatch_ops(operations)
            except ActionDeferred:
                pending = self._dispatch_inflight
                if (
                    pending is not None
                    and pending.owner is None
                    and pending.signature == signature
                ):
                    # Publication succeeded. Reserve casters immediately so a
                    # maintenance retry cannot queue the same spell twice.
                    self._finalize_auto_spell_plans(plans, cooldown_updates, now)
                return False

        if int(self.pm.read_ushort(action_global)) != 0:
            raise RuntimeError("Auto Spellcasting failed to restore gwActionType")
        self._finalize_auto_spell_plans(plans, cooldown_updates, now)
        return True

    def _spell_log_skips(self, spell_name: str, details: list[str]) -> None:
        if details:
            preview = "; ".join(details[:6])
            if len(details) > 6:
                preview += f"; +{len(details) - 6} more"
            self.log(f"{spell_name.upper()} SKIPPED: {preview}")

    def _order_vision(
        self, args: dict[str, Any], executing_player: int, x: int, y: int
    ) -> int:
        """Queue Warcraft's real Paladin SPELL_VISION order."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", VISION_CASTER_TYPE))
        if not 0 <= caster_owner < 8:
            raise ValueError("Holy Vision fog ownership requires a player from 0 through 7")
        if caster_type not in PALADIN_CASTER_TYPES:
            raise RuntimeError(
                "Caster Holy Vision requires a Paladin-class caster "
                "(Paladin, Turalyon, or Uther)"
            )
        caster_args = {
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }
        casters = self._selected_units(caster_args, executing_player)
        casters, busy_skips = self._spell_ready_casters(casters, args, "Holy Vision")
        if not casters:
            self.log("HOLY VISION SKIPPED: no ready Paladin caster matched the trigger")
            self._spell_log_skips("Holy Vision", busy_skips)
            return 0
        native_cost = int(self.spell_path["vision_cost"])
        ordered = 0
        rejected: list[str] = []
        for caster in casters:
            if caster.mana < native_cost:
                rejected.append(
                    f"Paladin slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"mana {caster.mana}/{native_cost}"
                )
                continue
            action_global = int(self.spell_path["action_type_global"])
            before_action_type = self.pm.read_ushort(action_global)
            if before_action_type != 0:
                rejected.append("Holy Vision selector busy with action " + str(before_action_type))
                continue
            self._dispatch_ops([
                ("write_word", action_global, SPELL_VISION),
                (
                    "call",
                    self.order_callees["set_target"],
                    [caster.address, x, y, 0, self.spell_path["do_unit_spell"]],
                ),
                ("write_word", action_global, 0),
            ])
            if self.pm.read_ushort(action_global) != 0:
                raise RuntimeError(
                    "Caster Holy Vision order failed to restore gwActionType"
                )
            data = self.pm.read_bytes(caster.address, UNIT_SIZE)
            if not self._record_is_allocated(data):
                rejected.append(
                    f"Paladin slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    "became inactive"
                )
                continue
            current = self._decode_unit(caster.address, data)
            target_x = int.from_bytes(data[0x84:0x86], "little", signed=True)
            target_y = int.from_bytes(data[0x86:0x88], "little", signed=True)
            target_unit = int.from_bytes(data[0x88:0x8C], "little")
            accepted = (
                target_unit == 0
                and (target_x, target_y) == (x, y)
                and (
                    current.action == SPELL_VISION
                    or current.next_action == SPELL_VISION
                )
            )
            if not accepted:
                rejected.append(
                    f"Paladin slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"target ({target_x},{target_y}) ptr 0x{target_unit:08X} "
                    f"action {current.action}/{current.next_action} mana {current.mana}"
                )
                continue
            self.log(
                f"HOLY VISION ORDERED: P{caster.owner + 1} Paladin slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} -> ({x},{y}); "
                f"action {current.action}/{current.next_action}; mana "
                f"{caster.mana}->{current.mana}; seven-reveal native cast queued"
            )
            ordered += 1
        self._spell_log_skips("Holy Vision", rejected)
        return ordered

    def _order_blizzard(
        self, args: dict[str, Any], executing_player: int, x: int, y: int
    ) -> int:
        """Queue Warcraft's real SPELL_BLIZZARD order on live Mage units."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", BLIZZARD_CASTER_TYPE))
        if caster_type not in MAGE_CASTER_TYPES:
            raise RuntimeError(
                "Blizzard requires Mage or Khadgar"
            )
        caster_args = {
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }
        casters = self._selected_units(caster_args, executing_player)
        casters, busy_skips = self._spell_ready_casters(casters, args, "Blizzard")
        if not casters:
            self.log("BLIZZARD SKIPPED: no ready Mage caster matched the trigger")
            self._spell_log_skips("Blizzard", busy_skips)
            return 0
        native_cost = int(self.spell_path["blizzard_cost"])
        ordered = 0
        rejected: list[str] = []
        for caster in casters:
            if caster.mana < native_cost:
                rejected.append(
                    f"Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"mana {caster.mana}/{native_cost}"
                )
                continue
            action_global = int(self.spell_path["action_type_global"])
            before_action_type = self.pm.read_ushort(action_global)
            if before_action_type != 0:
                rejected.append("Blizzard selector busy with action " + str(before_action_type))
                continue
            self._dispatch_ops([
                ("write_word", action_global, SPELL_BLIZZARD),
                (
                    "call",
                    self.order_callees["set_target"],
                    [caster.address, x, y, 0, self.spell_path["do_unit_spell"]],
                ),
                ("write_word", action_global, 0),
            ])
            if self.pm.read_ushort(action_global) != 0:
                raise RuntimeError("Blizzard order failed to restore gwActionType")
            data = self.pm.read_bytes(caster.address, UNIT_SIZE)
            if not self._record_is_allocated(data):
                rejected.append(
                    f"Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} became inactive"
                )
                continue
            current = self._decode_unit(caster.address, data)
            target_x = int.from_bytes(data[0x84:0x86], "little", signed=True)
            target_y = int.from_bytes(data[0x86:0x88], "little", signed=True)
            target_unit = int.from_bytes(data[0x88:0x8C], "little")
            active_storm = any(
                missile.missile_type == BT_BLIZZARD
                and missile.owner_unit == caster.address
                for missile in self._active_missiles()
            )
            accepted = (
                target_unit == 0
                and (target_x, target_y) == (x, y)
                and (
                    current.action == SPELL_BLIZZARD
                    or current.next_action == SPELL_BLIZZARD
                    or active_storm
                )
            )
            if not accepted:
                rejected.append(
                    f"Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"target ({target_x},{target_y}) ptr 0x{target_unit:08X} "
                    f"action {current.action}/{current.next_action} mana {current.mana}"
                )
                continue
            state = "storm active" if active_storm else "spell queued"
            self.log(
                f"BLIZZARD ORDERED: P{caster.owner + 1} Mage slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} -> ({x},{y}); "
                f"action {current.action}/{current.next_action}; mana "
                f"{caster.mana}->{current.mana}; {state}"
            )
            ordered += 1
        self._spell_log_skips("Blizzard", rejected)
        return ordered

    def _order_fireball(
        self, args: dict[str, Any], executing_player: int, x: int, y: int
    ) -> int:
        """Queue Warcraft's real SPELL_FIREBALL order on live Mage units."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", FIREBALL_CASTER_TYPE))
        if caster_type not in MAGE_CASTER_TYPES:
            raise RuntimeError(
                "Fireball requires Mage or Khadgar"
            )
        caster_args = {
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }
        casters = self._selected_units(caster_args, executing_player)
        casters, busy_skips = self._spell_ready_casters(casters, args, "Fireball")
        if not casters:
            self.log("FIREBALL SKIPPED: no ready Mage caster matched the trigger")
            self._spell_log_skips("Fireball", busy_skips)
            return 0
        native_cost = int(self.spell_path["fireball_cost"])
        ordered = 0
        rejected: list[str] = []
        for caster in casters:
            if caster.mana < native_cost:
                rejected.append(
                    f"Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"mana {caster.mana}/{native_cost}"
                )
                continue
            action_global = int(self.spell_path["action_type_global"])
            before_action_type = self.pm.read_ushort(action_global)
            if before_action_type != 0:
                rejected.append("Fireball selector busy with action " + str(before_action_type))
                continue
            self._dispatch_ops([
                ("write_word", action_global, SPELL_FIREBALL),
                (
                    "call",
                    self.order_callees["set_target"],
                    [caster.address, x, y, 0, self.spell_path["do_unit_spell"]],
                ),
                ("write_word", action_global, 0),
            ])
            if self.pm.read_ushort(action_global) != 0:
                raise RuntimeError("Fireball order failed to restore gwActionType")
            data = self.pm.read_bytes(caster.address, UNIT_SIZE)
            if not self._record_is_allocated(data):
                rejected.append(
                    f"Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} became inactive"
                )
                continue
            current = self._decode_unit(caster.address, data)
            target_x = int.from_bytes(data[0x84:0x86], "little", signed=True)
            target_y = int.from_bytes(data[0x86:0x88], "little", signed=True)
            target_unit = int.from_bytes(data[0x88:0x8C], "little")
            active_fireball = any(
                missile.missile_type == BT_FIREBALL
                and missile.owner_unit == caster.address
                for missile in self._active_missiles()
            )
            accepted = (
                target_unit == 0
                and (target_x, target_y) == (x, y)
                and (
                    current.action == SPELL_FIREBALL
                    or current.next_action == SPELL_FIREBALL
                    or active_fireball
                )
            )
            if not accepted:
                rejected.append(
                    f"Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"target ({target_x},{target_y}) ptr 0x{target_unit:08X} "
                    f"action {current.action}/{current.next_action} mana {current.mana}"
                )
                continue
            state = "projectile active" if active_fireball else "spell queued"
            self.log(
                f"FIREBALL ORDERED: P{caster.owner + 1} Mage slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} -> ({x},{y}); "
                f"action {current.action}/{current.next_action}; mana "
                f"{caster.mana}->{current.mana}; {state}"
            )
            ordered += 1
        self._spell_log_skips("Fireball", rejected)
        return ordered

    def _order_slow(self, args: dict[str, Any], executing_player: int) -> int:
        """Queue safe, unique native Slow orders on live Mages."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", SLOW_CASTER_TYPE))
        if caster_type not in MAGE_CASTER_TYPES:
            raise RuntimeError(
                "Slow requires Mage or Khadgar"
            )
        if "target_player" not in args:
            raise ValueError("Cast Spell: Slow requires target_player")
        target_owner = int(args["target_player"])
        target_type = args.get("target_unit", "Any")
        casters = self._selected_units({
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }, executing_player)
        casters, _ = self._spell_ready_casters(casters, args, "Slow")
        refresh = bool(args.get("refresh_effects", False))
        targets = [
            target for target in self._selected_units({
                "player": target_owner,
                "unit": target_type,
                "location": args.get("target_location", "Anywhere"),
            }, executing_player)
            if target.unit_type < FIRST_BUILDING_TYPE
            and (refresh or target.warp >= 0)
        ]
        if not casters:
            self.log("SLOW SKIPPED: no ready Mage caster matched the trigger")
            return 0
        assignments, skipped = self._spell_assign_unique_targets(
            casters, targets, args, default_health="Any health", exclude_self=False
        )
        if not assignments:
            self.log(
                "SLOW SKIPPED: no valid mobile target remained after health, location, "
                "effect-state, and unique-target filters"
            )
            self._spell_log_skips("Slow", skipped)
            return 0
        native_cost = int(self.spell_path["slow_cost"])
        ordered = 0
        rejected = list(skipped)
        for caster, target in assignments:
            if caster.mana < native_cost:
                rejected.append(
                    f"Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} mana "
                    f"{caster.mana}/{native_cost}"
                )
                continue
            result = self._spell_queue_unit_target(caster, target, SPELL_SLOW, "Slow")
            if result is None:
                continue
            current, current_target, target_pointer = result
            accepted = current_target.warp < 0 or (
                target_pointer == target.address
                and (current.action == SPELL_SLOW or current.next_action == SPELL_SLOW)
            )
            if not accepted:
                rejected.append(
                    f"Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} native order "
                    f"not retained for target slot {(target.address-self.unit_pool)//UNIT_SIZE}"
                )
                continue
            self.log(
                f"SLOW ORDERED: P{caster.owner + 1} Mage slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} -> P{target.owner + 1} "
                f"{UNIT_NAMES[target.unit_type]} slot "
                f"{(target.address-self.unit_pool)//UNIT_SIZE}; warp "
                f"{target.warp}->{current_target.warp}; action "
                f"{current.action}/{current.next_action}"
            )
            ordered += 1
        self._spell_log_skips("Slow", rejected)
        return ordered

    def _order_flame_shield(self, args: dict[str, Any], executing_player: int) -> int:
        """Queue safe, unique native Flame Shield orders and reject flyers."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", FLAME_SHIELD_CASTER_TYPE))
        if caster_type not in MAGE_CASTER_TYPES:
            raise RuntimeError(
                "Flame Shield requires Mage or Khadgar"
            )
        if "target_player" not in args:
            raise ValueError("Cast Spell: Flame Shield requires target_player")
        target_owner = int(args["target_player"])
        target_type = args.get("target_unit", "Any")
        casters = self._selected_units({
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }, executing_player)
        casters, _ = self._spell_ready_casters(casters, args, "Flame Shield")
        refresh = bool(args.get("refresh_effects", False))
        targets = [
            target for target in self._selected_units({
                "player": target_owner,
                "unit": target_type,
                "location": args.get("target_location", "Anywhere"),
            }, executing_player)
            if target.unit_type < FIRST_BUILDING_TYPE
            and not self._unit_is_flyer_type(target.unit_type)
            and (refresh or target.fire == 0)
        ]
        if not casters:
            self.log("FLAME SHIELD SKIPPED: no ready Mage caster matched the trigger")
            return 0
        assignments, skipped = self._spell_assign_unique_targets(casters, targets, args)
        if not assignments:
            self.log(
                "FLAME SHIELD SKIPPED: no valid non-flying, unshielded target remained"
            )
            self._spell_log_skips("Flame Shield", skipped)
            return 0
        native_cost = int(self.spell_path["flame_shield_cost"])
        ordered = 0
        rejected = list(skipped)
        for caster, target in assignments:
            if caster.mana < native_cost:
                rejected.append(
                    f"Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} mana "
                    f"{caster.mana}/{native_cost}"
                )
                continue
            result = self._spell_queue_unit_target(
                caster, target, SPELL_FLAME_SHIELD, "Flame Shield"
            )
            if result is None:
                continue
            current, current_target, target_pointer = result
            accepted = current_target.fire > 0 or (
                target_pointer == target.address
                and (current.action == SPELL_FLAME_SHIELD
                     or current.next_action == SPELL_FLAME_SHIELD)
            )
            if not accepted:
                rejected.append(
                    f"Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} native order "
                    f"not retained for target slot {(target.address-self.unit_pool)//UNIT_SIZE}"
                )
                continue
            self.log(
                f"FLAME SHIELD ORDERED: P{caster.owner + 1} Mage slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} -> P{target.owner + 1} "
                f"{UNIT_NAMES[target.unit_type]} slot "
                f"{(target.address-self.unit_pool)//UNIT_SIZE}; fire "
                f"{target.fire}->{current_target.fire}; action "
                f"{current.action}/{current.next_action}"
            )
            ordered += 1
        self._spell_log_skips("Flame Shield", rejected)
        return ordered

    def _order_invisibility(self, args: dict[str, Any], executing_player: int) -> int:
        """Queue safe, unique native Invisibility orders."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", INVIS_CASTER_TYPE))
        if caster_type not in MAGE_CASTER_TYPES:
            raise RuntimeError(
                "Invisibility requires Mage or Khadgar"
            )
        if "target_player" not in args:
            raise ValueError("Cast Spell: Invisibility requires target_player")
        target_owner = int(args["target_player"])
        target_type = args.get("target_unit", "Any")
        casters = self._selected_units({
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }, executing_player)
        casters, _ = self._spell_ready_casters(casters, args, "Invisibility")
        refresh = bool(args.get("refresh_effects", False))
        targets = [
            target for target in self._selected_units({
                "player": target_owner,
                "unit": target_type,
                "location": args.get("target_location", "Anywhere"),
            }, executing_player)
            if target.unit_type < FIRST_BUILDING_TYPE
            and (refresh or target.invis == 0)
        ]
        if not casters:
            self.log("INVISIBILITY SKIPPED: no ready Mage caster matched the trigger")
            return 0
        assignments, skipped = self._spell_assign_unique_targets(casters, targets, args)
        if not assignments:
            self.log("INVISIBILITY SKIPPED: no valid visible mobile target remained")
            self._spell_log_skips("Invisibility", skipped)
            return 0
        native_cost = int(self.spell_path["invis_cost"])
        ordered = 0
        rejected = list(skipped)
        for caster, target in assignments:
            if caster.mana < native_cost:
                rejected.append(
                    f"Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} mana "
                    f"{caster.mana}/{native_cost}"
                )
                continue
            result = self._spell_queue_unit_target(
                caster, target, SPELL_INVIS, "Invisibility"
            )
            if result is None:
                continue
            current, current_target, target_pointer = result
            accepted = current_target.invis > 0 or (
                target_pointer == target.address
                and (current.action == SPELL_INVIS or current.next_action == SPELL_INVIS)
            )
            if not accepted:
                rejected.append(
                    f"Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} native order "
                    f"not retained for target slot {(target.address-self.unit_pool)//UNIT_SIZE}"
                )
                continue
            self.log(
                f"INVISIBILITY ORDERED: P{caster.owner + 1} Mage slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} -> P{target.owner + 1} "
                f"{UNIT_NAMES[target.unit_type]} slot "
                f"{(target.address-self.unit_pool)//UNIT_SIZE}; invis "
                f"{target.invis}->{current_target.invis}; action "
                f"{current.action}/{current.next_action}"
            )
            ordered += 1
        self._spell_log_skips("Invisibility", rejected)
        return ordered

    def _order_polymorph(self, args: dict[str, Any], executing_player: int) -> int:
        """Queue one unique fleshy target per Mage, preventing stale PTUnit reuse."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", POLYMORPH_CASTER_TYPE))
        if caster_type not in MAGE_CASTER_TYPES:
            raise RuntimeError(
                "Polymorph requires Mage or Khadgar"
            )
        if "target_player" not in args:
            raise ValueError("Cast Spell: Polymorph requires target_player")
        target_owner = int(args["target_player"])
        target_type = args.get("target_unit", "Any")
        casters = self._selected_units({
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }, executing_player)
        casters, _ = self._spell_ready_casters(casters, args, "Polymorph")
        targets = [
            target for target in self._selected_units({
                "player": target_owner,
                "unit": target_type,
                "location": args.get("target_location", "Anywhere"),
            }, executing_player)
            if target.unit_type < FIRST_BUILDING_TYPE
            and self._unit_is_fleshy_type(target.unit_type)
        ]
        if not casters:
            self.log("POLYMORPH SKIPPED: no ready Mage caster matched the trigger")
            return 0
        assignments, skipped = self._spell_assign_unique_targets(
            casters, targets, args, exclude_self=True
        )
        if not assignments:
            self.log(
                "POLYMORPH SKIPPED: no valid fleshy mobile target remained; "
                "a Mage is never allowed to Polymorph itself"
            )
            self._spell_log_skips("Polymorph", skipped)
            return 0
        native_cost = int(self.spell_path["polymorph_cost"])
        ordered = 0
        rejected = list(skipped)
        for caster, target in assignments:
            if caster.mana < native_cost:
                rejected.append(
                    f"Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} mana "
                    f"{caster.mana}/{native_cost}"
                )
                continue
            action_global = int(self.spell_path["action_type_global"])
            if self.pm.read_ushort(action_global) != 0:
                rejected.append("gwActionType busy")
                continue
            self._dispatch_ops([
                ("write_word", action_global, SPELL_POLYMORPH),
                ("call", self.order_callees["set_target"], [
                    caster.address, 0, 0, target.address, self.spell_path["do_unit_spell"]
                ]),
                ("write_word", action_global, 0),
            ])
            if self.pm.read_ushort(action_global) != 0:
                raise RuntimeError("Polymorph order failed to restore gwActionType")
            caster_data = self.pm.read_bytes(caster.address, UNIT_SIZE)
            target_data = self.pm.read_bytes(target.address, UNIT_SIZE)
            if not self._record_is_allocated(caster_data):
                rejected.append("Mage became inactive while queueing Polymorph")
                continue
            current = self._decode_unit(caster.address, caster_data)
            target_pointer = int.from_bytes(caster_data[0x88:0x8C], "little")
            target_flags = int.from_bytes(target_data[0x1E:0x20], "little")
            transformed = bool(target_flags & 0x000E)
            accepted = transformed or (
                target_pointer == target.address
                and (current.action == SPELL_POLYMORPH
                     or current.next_action == SPELL_POLYMORPH)
            )
            if not accepted:
                rejected.append(
                    f"Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} native order "
                    f"not retained for target slot {(target.address-self.unit_pool)//UNIT_SIZE}"
                )
                continue
            self.log(
                f"POLYMORPH ORDERED: P{caster.owner + 1} Mage slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} -> P{target.owner + 1} "
                f"{UNIT_NAMES[target.unit_type]} slot "
                f"{(target.address-self.unit_pool)//UNIT_SIZE}; "
                f"{'transformed' if transformed else 'unique native spell queued'}"
            )
            ordered += 1
        self._spell_log_skips("Polymorph", rejected)
        return ordered

    def _order_eye(self, args: dict[str, Any], executing_player: int) -> int:
        """Queue Warcraft's real caster-centered SPELL_EYE order."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", EYE_CASTER_TYPE))
        if caster_type not in OGRE_MAGE_CASTER_TYPES:
            raise RuntimeError(
                "Eye of Kilrogg requires Ogre-Mage, Dentarg, or Cho'gall"
            )
        caster_args = {
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }
        casters = self._selected_units(caster_args, executing_player)
        casters, busy_skips = self._spell_ready_casters(casters, args, "Eye of Kilrogg")
        if not casters:
            self.log("EYE OF KILROGG SKIPPED: no ready Ogre-Mage caster matched the trigger")
            self._spell_log_skips("Eye of Kilrogg", busy_skips)
            return 0
        native_cost = int(self.spell_path["eye_cost"])
        ordered = 0
        rejected: list[str] = []
        for caster in casters:
            if caster.mana < native_cost:
                rejected.append(
                    f"Ogre-Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"mana {caster.mana}/{native_cost}"
                )
                continue
            before_eye_keys = {
                self._unit_key(unit) for unit in self.units()
                if unit.owner == caster_owner and unit.unit_type == EYE_UNIT_TYPE
            }
            x, y = caster.x, caster.y
            action_global = int(self.spell_path["action_type_global"])
            before_action_type = self.pm.read_ushort(action_global)
            if before_action_type != 0:
                rejected.append("Eye of Kilrogg selector busy with action " + str(before_action_type))
                continue
            self._dispatch_ops([
                ("write_word", action_global, SPELL_EYE),
                (
                    "call",
                    self.order_callees["set_target"],
                    [caster.address, x, y, 0, self.spell_path["do_unit_spell"]],
                ),
                ("write_word", action_global, 0),
            ])
            if self.pm.read_ushort(action_global) != 0:
                raise RuntimeError("Eye of Kilrogg order failed to restore gwActionType")
            caster_data = self.pm.read_bytes(caster.address, UNIT_SIZE)
            if not self._record_is_allocated(caster_data):
                rejected.append(
                    f"Ogre-Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} became inactive"
                )
                continue
            current = self._decode_unit(caster.address, caster_data)
            target_x = int.from_bytes(caster_data[0x84:0x86], "little", signed=True)
            target_y = int.from_bytes(caster_data[0x86:0x88], "little", signed=True)
            target_pointer = int.from_bytes(caster_data[0x88:0x8C], "little")
            new_eyes = [
                unit for unit in self.units()
                if unit.owner == caster_owner
                and unit.unit_type == EYE_UNIT_TYPE
                and self._unit_key(unit) not in before_eye_keys
            ]
            accepted = bool(new_eyes) or (
                target_pointer == 0
                and (target_x, target_y) == (x, y)
                and (current.action == SPELL_EYE or current.next_action == SPELL_EYE)
            )
            if not accepted:
                rejected.append(
                    f"Ogre-Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"target ({target_x},{target_y}) ptr 0x{target_pointer:08X} action "
                    f"{current.action}/{current.next_action} mana {current.mana}; "
                    f"new Eyes {len(new_eyes)}"
                )
                continue
            state = f"created {len(new_eyes)} Eye(s)" if new_eyes else "spell queued"
            self.log(
                f"EYE OF KILROGG ORDERED: P{caster.owner + 1} Ogre-Mage slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} at ({x},{y}); action "
                f"{current.action}/{current.next_action}; mana {caster.mana}->{current.mana}; "
                f"{state}"
            )
            ordered += 1
        self._spell_log_skips("Eye of Kilrogg", rejected)
        return ordered

    def _unit_is_fleshy_type(self, unit_type: int) -> bool:
        if not 0 <= unit_type < len(UNIT_NAMES):
            return False
        flags = self.pm.read_uint(self.base + UNIT_IS_TABLE_RVA + unit_type * 4)
        return bool(flags & IS_FLESHY)

    def _order_runes(
        self, args: dict[str, Any], executing_player: int, x: int, y: int
    ) -> int:
        """Queue Warcraft's real Ogre-Mage SPELL_RUNES order."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", RUNES_CASTER_TYPE))
        if caster_type not in OGRE_MAGE_CASTER_TYPES:
            raise RuntimeError(
                "Caster Runes requires Ogre-Mage, Dentarg, or Cho'gall"
            )
        caster_args = {
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }
        casters = self._selected_units(caster_args, executing_player)
        casters, busy_skips = self._spell_ready_casters(casters, args, "Runes")
        if not casters:
            self.log("RUNES SKIPPED: no ready Ogre-Mage caster matched the trigger")
            self._spell_log_skips("Runes", busy_skips)
            return 0
        native_cost = int(self.spell_path["runes_cost"])
        expected_positions = {
            (x, y), (x, y - 1), (x + 1, y), (x, y + 1), (x - 1, y)
        }
        ordered = 0
        rejected: list[str] = []
        for caster in casters:
            if caster.mana < native_cost:
                rejected.append(
                    f"Ogre-Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"mana {caster.mana}/{native_cost}"
                )
                continue
            before_runes = {
                (slot, rx, ry) for slot, rx, ry, _ in self._active_runes()
            }
            action_global = int(self.spell_path["action_type_global"])
            before_action_type = self.pm.read_ushort(action_global)
            if before_action_type != 0:
                rejected.append("Runes selector busy with action " + str(before_action_type))
                continue
            self._dispatch_ops([
                ("write_word", action_global, SPELL_RUNES),
                (
                    "call",
                    self.order_callees["set_target"],
                    [caster.address, x, y, 0, self.spell_path["do_unit_spell"]],
                ),
                ("write_word", action_global, 0),
            ])
            if self.pm.read_ushort(action_global) != 0:
                raise RuntimeError("Caster Runes order failed to restore gwActionType")
            data = self.pm.read_bytes(caster.address, UNIT_SIZE)
            if not self._record_is_allocated(data):
                rejected.append(
                    f"Ogre-Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    "became inactive"
                )
                continue
            current = self._decode_unit(caster.address, data)
            target_x = int.from_bytes(data[0x84:0x86], "little", signed=True)
            target_y = int.from_bytes(data[0x86:0x88], "little", signed=True)
            target_unit = int.from_bytes(data[0x88:0x8C], "little")
            new_runes = [
                rune for rune in self._active_runes()
                if (rune[0], rune[1], rune[2]) not in before_runes
                and (rune[1], rune[2]) in expected_positions
            ]
            accepted = (
                target_unit == 0
                and (target_x, target_y) == (x, y)
                and (
                    current.action == SPELL_RUNES
                    or current.next_action == SPELL_RUNES
                    or bool(new_runes)
                )
            )
            if not accepted:
                rejected.append(
                    f"Ogre-Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"target ({target_x},{target_y}) ptr 0x{target_unit:08X} "
                    f"action {current.action}/{current.next_action} mana {current.mana}"
                )
                continue
            state = (
                f"{len(new_runes)} Rune(s) active"
                if new_runes else "five-position pattern queued"
            )
            self.log(
                f"RUNES ORDERED: P{caster.owner + 1} Ogre-Mage slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} -> ({x},{y}); "
                f"action {current.action}/{current.next_action}; mana "
                f"{caster.mana}->{current.mana}; {state}"
            )
            ordered += 1
        self._spell_log_skips("Runes", rejected)
        return ordered

    def _order_bloodlust(self, args: dict[str, Any], executing_player: int) -> int:
        """Queue one unique, valid Bloodlust target per ready Ogre-Mage."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", BLOODLUST_CASTER_TYPE))
        if caster_type not in OGRE_MAGE_CASTER_TYPES:
            raise RuntimeError(
                "Bloodlust requires Ogre-Mage, Dentarg, or Cho'gall"
            )
        if "target_player" not in args:
            raise ValueError("Cast Spell: Bloodlust requires target_player")
        target_owner = int(args["target_player"])
        target_type = args.get("target_unit", "Any")
        casters = self._selected_units({
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }, executing_player)
        casters, _ = self._spell_ready_casters(casters, args, "Bloodlust")
        refresh = bool(args.get("refresh_effects", False))
        targets = [
            target for target in self._selected_units({
                "player": target_owner,
                "unit": target_type,
                "location": args.get("target_location", "Anywhere"),
            }, executing_player)
            if target.unit_type < FIRST_BUILDING_TYPE
            and self._unit_is_fleshy_type(target.unit_type)
            and (refresh or target.rage == 0)
        ]
        if not casters:
            self.log("BLOODLUST SKIPPED: no ready Ogre-Mage caster matched the trigger")
            return 0
        assignments, skipped = self._spell_assign_unique_targets(casters, targets, args)
        if not assignments:
            self.log(
                "BLOODLUST SKIPPED: no unbuffed fleshy target remained after the "
                "trigger filters; no unsafe duplicate order was issued"
            )
            self._spell_log_skips("Bloodlust", skipped)
            return 0
        native_cost = int(self.spell_path["bloodlust_cost"])
        ordered = 0
        rejected = list(skipped)
        for caster, target in assignments:
            if caster.mana < native_cost:
                rejected.append(
                    f"Ogre-Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} mana "
                    f"{caster.mana}/{native_cost}"
                )
                continue
            result = self._spell_queue_unit_target(
                caster, target, SPELL_BLOODLUST, "Bloodlust"
            )
            if result is None:
                continue
            current, current_target, target_pointer = result
            accepted = current_target.rage > 0 or (
                target_pointer == target.address
                and (current.action == SPELL_BLOODLUST
                     or current.next_action == SPELL_BLOODLUST)
            )
            if not accepted:
                rejected.append(
                    f"Ogre-Mage slot {(caster.address-self.unit_pool)//UNIT_SIZE} native order "
                    f"not retained for target slot {(target.address-self.unit_pool)//UNIT_SIZE}"
                )
                continue
            self.log(
                f"BLOODLUST ORDERED: P{caster.owner + 1} Ogre-Mage slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} -> P{target.owner + 1} "
                f"{UNIT_NAMES[target.unit_type]} slot "
                f"{(target.address-self.unit_pool)//UNIT_SIZE}; rage "
                f"{target.rage}->{current_target.rage}; action "
                f"{current.action}/{current.next_action}"
            )
            ordered += 1
        self._spell_log_skips("Bloodlust", rejected)
        return ordered

    def _order_heal(self, args: dict[str, Any], executing_player: int) -> int:
        """Queue Healing only on distinct wounded fleshy targets."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", HEAL_CASTER_TYPE))
        if caster_type not in PALADIN_CASTER_TYPES:
            raise RuntimeError(
                "Healing requires Paladin, Turalyon, or Uther"
            )
        if "target_player" not in args:
            raise ValueError("Cast Spell: Healing requires target_player")
        target_owner = int(args["target_player"])
        target_type = args.get("target_unit", "Any")
        casters = self._selected_units({
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }, executing_player)
        casters, _ = self._spell_ready_casters(casters, args, "Healing")
        matched_targets = self._selected_units({
            "player": target_owner,
            "unit": target_type,
            "location": args.get("target_location", "Anywhere"),
        }, executing_player)
        targets = []
        full_health = 0
        non_fleshy = 0
        for target in matched_targets:
            hp_max = self._spell_unit_hp_max(target)
            if target.unit_type >= FIRST_BUILDING_TYPE or not self._unit_is_fleshy_type(target.unit_type):
                non_fleshy += 1
                continue
            if target.health >= hp_max:
                full_health += 1
                continue
            targets.append(target)
        if not casters:
            self.log("HEALING SKIPPED: no ready Paladin caster matched the trigger")
            return 0
        assignments, skipped = self._spell_assign_unique_targets(
            casters, targets, args, default_health="Wounded only"
        )
        if not assignments:
            self.log(
                "HEALING SKIPPED: no eligible wounded target; "
                f"matched={len(matched_targets)}, wounded={len(targets)}, "
                f"full-health={full_health}, non-fleshy/building={non_fleshy}. "
                "Healing intentionally never casts on a full-health unit."
            )
            self._spell_log_skips("Healing", skipped)
            return 0
        native_cost = int(self.spell_path["heal_cost"])
        ordered = 0
        rejected = list(skipped)
        for caster, target in assignments:
            hp_max = self._spell_unit_hp_max(target)
            if caster.mana < native_cost:
                rejected.append(
                    f"Paladin slot {(caster.address-self.unit_pool)//UNIT_SIZE} mana "
                    f"{caster.mana}/{native_cost} minimum"
                )
                continue
            expected_heal = min(
                hp_max - target.health,
                HEAL_MAX,
                caster.mana // native_cost,
            )
            if expected_heal <= 0:
                rejected.append(
                    f"target slot {(target.address-self.unit_pool)//UNIT_SIZE} needs no heal"
                )
                continue
            result = self._spell_queue_unit_target(caster, target, SPELL_HEAL, "Healing")
            if result is None:
                continue
            current, current_target, target_pointer = result
            healed = current_target.health > target.health
            accepted = healed or (
                target_pointer == target.address
                and (current.action == SPELL_HEAL or current.next_action == SPELL_HEAL)
            )
            if not accepted:
                rejected.append(
                    f"Paladin slot {(caster.address-self.unit_pool)//UNIT_SIZE} native order "
                    f"not retained for target slot {(target.address-self.unit_pool)//UNIT_SIZE}"
                )
                continue
            self.log(
                f"HEALING ORDERED: P{caster.owner + 1} Paladin slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} -> P{target.owner + 1} "
                f"{UNIT_NAMES[target.unit_type]} slot "
                f"{(target.address-self.unit_pool)//UNIT_SIZE}; HP "
                f"{target.health}->{current_target.health}/{hp_max}; native heal up to "
                f"{expected_heal}; action {current.action}/{current.next_action}"
            )
            ordered += 1
        self._spell_log_skips("Healing", rejected)
        return ordered

    def _unit_is_undead_type(self, unit_type: int) -> bool:
        if not 0 <= unit_type < len(UNIT_NAMES):
            return False
        flags = self.pm.read_uint(self.base + UNIT_IS_TABLE_RVA + unit_type * 4)
        return bool(flags & IS_UNDEAD)

    def _order_exorcism(
        self, args: dict[str, Any], executing_player: int, x: int, y: int
    ) -> int:
        """Queue Warcraft's real area-effect SPELL_EXORCISM order."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", EXORCISM_CASTER_TYPE))
        if caster_type not in PALADIN_CASTER_TYPES:
            raise RuntimeError(
                "Exorcism requires Paladin, Turalyon, or Uther"
            )
        caster_args = {
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }
        casters = self._selected_units(caster_args, executing_player)
        casters, busy_skips = self._spell_ready_casters(casters, args, "Exorcism")
        if not casters:
            self.log("EXORCISM SKIPPED: no ready Paladin caster matched the trigger")
            self._spell_log_skips("Exorcism", busy_skips)
            return 0
        target_owner_arg = args.get("target_player")
        target_owner = int(target_owner_arg) if target_owner_arg is not None else None
        undead_targets = [
            unit for unit in self.units()
            if self._unit_is_undead_type(unit.unit_type)
            and (target_owner is None or unit.owner == target_owner)
            and abs(unit.x - x) <= EXORCISM_RADIUS
            and abs(unit.y - y) <= EXORCISM_RADIUS
        ]
        if not undead_targets:
            owner_text = "" if target_owner is None else f" P{target_owner + 1}"
            self.log(
                f"EXORCISM SKIPPED: no{owner_text} undead target within "
                f"{EXORCISM_RADIUS} tiles of ({x},{y})"
            )
            return 0
        native_cost = int(self.spell_path["exorcism_cost"])
        ordered = 0
        rejected: list[str] = []
        for caster in casters:
            if caster.mana < native_cost:
                rejected.append(
                    f"Paladin slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"mana {caster.mana}/{native_cost} minimum"
                )
                continue
            action_global = int(self.spell_path["action_type_global"])
            before_action_type = self.pm.read_ushort(action_global)
            if before_action_type != 0:
                rejected.append("Exorcism selector busy with action " + str(before_action_type))
                continue
            self._dispatch_ops([
                ("write_word", action_global, SPELL_EXORCISM),
                (
                    "call",
                    self.order_callees["set_target"],
                    [caster.address, x, y, 0, self.spell_path["do_unit_spell"]],
                ),
                ("write_word", action_global, 0),
            ])
            if self.pm.read_ushort(action_global) != 0:
                raise RuntimeError("Exorcism order failed to restore gwActionType")
            data = self.pm.read_bytes(caster.address, UNIT_SIZE)
            if not self._record_is_allocated(data):
                rejected.append(
                    f"Paladin slot {(caster.address-self.unit_pool)//UNIT_SIZE} became inactive"
                )
                continue
            current = self._decode_unit(caster.address, data)
            target_x = int.from_bytes(data[0x84:0x86], "little", signed=True)
            target_y = int.from_bytes(data[0x86:0x88], "little", signed=True)
            target_unit = int.from_bytes(data[0x88:0x8C], "little")
            target_damaged = any(
                (
                    not self._record_is_allocated(
                        self.pm.read_bytes(target.address, UNIT_SIZE)
                    )
                    or self.pm.read_ushort(target.address + 0x22) < target.health
                )
                for target in undead_targets
            )
            active_visual = any(
                missile.missile_type == BT_EXORCISM
                for missile in self._active_missiles()
            )
            accepted = (
                target_unit == 0
                and (target_x, target_y) == (x, y)
                and (
                    current.action == SPELL_EXORCISM
                    or current.next_action == SPELL_EXORCISM
                    or target_damaged
                    or active_visual
                )
            )
            if not accepted:
                rejected.append(
                    f"Paladin slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"target ({target_x},{target_y}) ptr 0x{target_unit:08X} "
                    f"action {current.action}/{current.next_action} mana {current.mana}"
                )
                continue
            state = "damage active" if target_damaged else (
                "visual active" if active_visual else "spell queued"
            )
            self.log(
                f"EXORCISM ORDERED: P{caster.owner + 1} Paladin slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} -> ({x},{y}); "
                f"action {current.action}/{current.next_action}; mana "
                f"{caster.mana}->{current.mana}; {len(undead_targets)} undead target(s); "
                f"up to {caster.mana // native_cost} damage; {state}"
            )
            for target in undead_targets:
                self._snapshot[self._unit_key(target)] = target
            ordered += 1
        self._spell_log_skips("Exorcism", rejected)
        return ordered

    def _order_raisedead(
        self, args: dict[str, Any], executing_player: int, x: int, y: int
    ) -> int:
        """Queue Warcraft's real area-effect SPELL_RAISEDEAD order."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", RAISEDEAD_CASTER_TYPE))
        if caster_type not in DEATH_KNIGHT_CASTER_TYPES:
            raise RuntimeError(
                "Raise Dead requires Death Knight, Teron Gorefiend, or Gul'dan"
            )
        caster_args = {
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }
        casters = self._selected_units(caster_args, executing_player)
        casters, busy_skips = self._spell_ready_casters(casters, args, "Raise Dead")
        if not casters:
            self.log("RAISE DEAD SKIPPED: no ready Death Knight caster matched the trigger")
            self._spell_log_skips("Raise Dead", busy_skips)
            return 0
        target_owner_arg = args.get("target_player")
        target_owner = int(target_owner_arg) if target_owner_arg is not None else None
        eligible_corpses = [
            corpse for corpse in self.corpses()
            if (target_owner is None or corpse.owner == target_owner)
            and (corpse.x - x) ** 2 + (corpse.y - y) ** 2 <= RAISEDEAD_RADIUS ** 2
        ]
        if not eligible_corpses:
            owner_text = "" if target_owner is None else f" P{target_owner + 1}"
            self.log(
                f"RAISE DEAD SKIPPED: no eligible{owner_text} corpse within "
                f"{RAISEDEAD_RADIUS} tiles of ({x},{y})"
            )
            return 0
        native_cost = int(self.spell_path["raisedead_cost"])
        ordered = 0
        rejected: list[str] = []
        for caster in casters:
            if caster.mana < native_cost:
                rejected.append(
                    f"Death Knight slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"mana {caster.mana}/{native_cost} minimum"
                )
                continue
            before_skeleton_keys = {
                self._unit_key(unit) for unit in self.units()
                if unit.owner == caster_owner and unit.unit_type == SKELETON_TYPE
            }
            corpse_addresses = {corpse.address for corpse in eligible_corpses}
            maximum_raised = min(len(eligible_corpses), caster.mana // native_cost)
            action_global = int(self.spell_path["action_type_global"])
            before_action_type = self.pm.read_ushort(action_global)
            if before_action_type != 0:
                rejected.append("Raise Dead selector busy with action " + str(before_action_type))
                continue
            self._dispatch_ops([
                ("write_word", action_global, SPELL_RAISEDEAD),
                (
                    "call",
                    self.order_callees["set_target"],
                    [caster.address, x, y, 0, self.spell_path["do_unit_spell"]],
                ),
                ("write_word", action_global, 0),
            ])
            if self.pm.read_ushort(action_global) != 0:
                raise RuntimeError("Raise Dead order failed to restore gwActionType")
            caster_data = self.pm.read_bytes(caster.address, UNIT_SIZE)
            if not self._record_is_allocated(caster_data):
                rejected.append(
                    f"Death Knight slot {(caster.address-self.unit_pool)//UNIT_SIZE} became inactive"
                )
                continue
            current = self._decode_unit(caster.address, caster_data)
            target_x = int.from_bytes(caster_data[0x84:0x86], "little", signed=True)
            target_y = int.from_bytes(caster_data[0x86:0x88], "little", signed=True)
            target_pointer = int.from_bytes(caster_data[0x88:0x8C], "little")
            after_units = self.units()
            new_skeletons = [
                unit for unit in after_units
                if unit.owner == caster_owner
                and unit.unit_type == SKELETON_TYPE
                and self._unit_key(unit) not in before_skeleton_keys
            ]
            remaining_corpses = {corpse.address for corpse in self.corpses()}
            consumed_count = sum(
                1 for address in corpse_addresses if address not in remaining_corpses
            )
            accepted = (
                target_pointer == 0
                and (target_x, target_y) == (x, y)
                and (
                    current.action == SPELL_RAISEDEAD
                    or current.next_action == SPELL_RAISEDEAD
                    or bool(new_skeletons)
                    or consumed_count > 0
                )
            )
            if not accepted:
                rejected.append(
                    f"Death Knight slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"target ({target_x},{target_y}) ptr 0x{target_pointer:08X} action "
                    f"{current.action}/{current.next_action} mana {current.mana}; "
                    f"Skeletons +{len(new_skeletons)}, corpses consumed {consumed_count}"
                )
                continue
            state = (
                f"raised {len(new_skeletons)} Skeleton(s), consumed {consumed_count} corpse(s)"
                if new_skeletons or consumed_count
                else "spell queued"
            )
            self.log(
                f"RAISE DEAD ORDERED: P{caster.owner + 1} Death Knight slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} -> ({x},{y}); action "
                f"{current.action}/{current.next_action}; mana {caster.mana}->{current.mana}; "
                f"{len(eligible_corpses)} eligible corpse(s), up to {maximum_raised} "
                f"native Skeleton(s); {state}"
            )
            ordered += 1
        self._spell_log_skips("Raise Dead", rejected)
        return ordered

    def _order_drainlife(
        self, args: dict[str, Any], executing_player: int, x: int, y: int
    ) -> int:
        """Queue Warcraft's real area-effect SPELL_DRAINLIFE (Death Coil)."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", DRAINLIFE_CASTER_TYPE))
        if caster_type not in DEATH_KNIGHT_CASTER_TYPES:
            raise RuntimeError(
                "Death Coil requires Death Knight, Teron Gorefiend, or Gul'dan"
            )
        caster_args = {
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }
        casters = self._selected_units(caster_args, executing_player)
        casters, busy_skips = self._spell_ready_casters(casters, args, "Death Coil")
        if not casters:
            self.log("DEATH COIL SKIPPED: no ready Death Knight caster matched the trigger")
            self._spell_log_skips("Death Coil", busy_skips)
            return 0
        target_owner_arg = args.get("target_player")
        target_owner = int(target_owner_arg) if target_owner_arg is not None else None
        drain_targets = [
            unit for unit in self.units()
            if unit.owner != caster_owner
            and (target_owner is None or unit.owner == target_owner)
            and self._unit_is_fleshy_type(unit.unit_type)
            and abs(unit.x - x) <= DRAINLIFE_RADIUS
            and abs(unit.y - y) <= DRAINLIFE_RADIUS
        ]
        if not drain_targets:
            owner_text = "" if target_owner is None else f" P{target_owner + 1}"
            self.log(
                f"DEATH COIL SKIPPED: no enemy{owner_text} fleshy target "
                f"within {DRAINLIFE_RADIUS} tiles of ({x},{y})"
            )
            return 0
        native_cost = int(self.spell_path["drainlife_cost"])
        ordered = 0
        rejected: list[str] = []
        for caster in casters:
            if caster.mana < native_cost:
                rejected.append(
                    f"Death Knight slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"mana {caster.mana}/{native_cost}"
                )
                continue
            reserved_life = min(
                DRAINLIFE_MAX,
                sum(target.health for target in sorted(
                    drain_targets, key=lambda unit: (unit.health, unit.address)
                )),
            )
            action_global = int(self.spell_path["action_type_global"])
            before_action_type = self.pm.read_ushort(action_global)
            if before_action_type != 0:
                rejected.append("Death Coil selector busy with action " + str(before_action_type))
                continue
            self._dispatch_ops([
                ("write_word", action_global, SPELL_DRAINLIFE),
                (
                    "call",
                    self.order_callees["set_target"],
                    [caster.address, x, y, 0, self.spell_path["do_unit_spell"]],
                ),
                ("write_word", action_global, 0),
            ])
            if self.pm.read_ushort(action_global) != 0:
                raise RuntimeError("Death Coil order failed to restore gwActionType")
            data = self.pm.read_bytes(caster.address, UNIT_SIZE)
            if not self._record_is_allocated(data):
                rejected.append(
                    f"Death Knight slot {(caster.address-self.unit_pool)//UNIT_SIZE} became inactive"
                )
                continue
            current = self._decode_unit(caster.address, data)
            target_x = int.from_bytes(data[0x84:0x86], "little", signed=True)
            target_y = int.from_bytes(data[0x86:0x88], "little", signed=True)
            current_target = int.from_bytes(data[0x88:0x8C], "little")
            target_damaged = any(
                (
                    not self._record_is_allocated(
                        self.pm.read_bytes(target.address, UNIT_SIZE)
                    )
                    or self.pm.read_ushort(target.address + 0x22) < target.health
                )
                for target in drain_targets
            )
            active_coil = any(
                missile.owner_unit == caster.address and missile.damage > 0
                for missile in self._active_missiles()
            )
            caster_healed = current.health > caster.health
            accepted = (
                (target_x, target_y) == (x, y)
                and (
                    current.action == SPELL_DRAINLIFE
                    or current.next_action == SPELL_DRAINLIFE
                    or target_damaged
                    or active_coil
                    or caster_healed
                )
            )
            if not accepted:
                rejected.append(
                    f"Death Knight slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"target ({target_x},{target_y}) ptr 0x{current_target:08X} "
                    f"action {current.action}/{current.next_action} mana {current.mana} "
                    f"HP {caster.health}->{current.health}"
                )
                continue
            state = "life drained" if caster_healed or target_damaged else (
                "projectile active" if active_coil else "spell queued"
            )
            self.log(
                f"DEATH COIL ORDERED: P{caster.owner + 1} Death Knight slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} -> ({x},{y}); "
                f"action {current.action}/{current.next_action}; mana "
                f"{caster.mana}->{current.mana}; HP {caster.health}->{current.health}; "
                f"{len(drain_targets)} eligible target(s), up to {reserved_life} life; {state}"
            )
            for target in drain_targets:
                self._snapshot[self._unit_key(target)] = target
            ordered += 1
        self._spell_log_skips("Death Coil", rejected)
        return ordered

    def _order_whirlwind(
        self, args: dict[str, Any], executing_player: int, x: int, y: int
    ) -> int:
        """Queue Warcraft's real area-effect SPELL_WHIRLWIND order."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", WHIRLWIND_CASTER_TYPE))
        if caster_type not in DEATH_KNIGHT_CASTER_TYPES:
            raise RuntimeError(
                "Whirlwind requires Death Knight, Teron Gorefiend, or Gul'dan"
            )
        caster_args = {
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }
        casters = self._selected_units(caster_args, executing_player)
        casters, busy_skips = self._spell_ready_casters(casters, args, "Whirlwind")
        if not casters:
            self.log("WHIRLWIND SKIPPED: no ready Death Knight caster matched the trigger")
            self._spell_log_skips("Whirlwind", busy_skips)
            return 0
        native_cost = int(self.spell_path["whirlwind_cost"])
        ordered = 0
        rejected: list[str] = []
        for caster in casters:
            if caster.mana < native_cost:
                rejected.append(
                    f"Death Knight slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"mana {caster.mana}/{native_cost}"
                )
                continue
            before_typhoons = {
                missile.address for missile in self._active_missiles()
                if missile.missile_type == BT_TYPHOON
                and missile.owner_unit == caster.address
            }
            action_global = int(self.spell_path["action_type_global"])
            before_action_type = self.pm.read_ushort(action_global)
            if before_action_type != 0:
                rejected.append("Whirlwind selector busy with action " + str(before_action_type))
                continue
            self._dispatch_ops([
                ("write_word", action_global, SPELL_WHIRLWIND),
                (
                    "call",
                    self.order_callees["set_target"],
                    [caster.address, x, y, 0, self.spell_path["do_unit_spell"]],
                ),
                ("write_word", action_global, 0),
            ])
            if self.pm.read_ushort(action_global) != 0:
                raise RuntimeError("Whirlwind order failed to restore gwActionType")
            data = self.pm.read_bytes(caster.address, UNIT_SIZE)
            if not self._record_is_allocated(data):
                rejected.append(
                    f"Death Knight slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    "became inactive"
                )
                continue
            current = self._decode_unit(caster.address, data)
            target_x = int.from_bytes(data[0x84:0x86], "little", signed=True)
            target_y = int.from_bytes(data[0x86:0x88], "little", signed=True)
            target_unit = int.from_bytes(data[0x88:0x8C], "little")
            new_typhoons = [
                missile for missile in self._active_missiles()
                if missile.missile_type == BT_TYPHOON
                and missile.owner_unit == caster.address
                and missile.address not in before_typhoons
            ]
            accepted = (
                target_unit == 0
                and (target_x, target_y) == (x, y)
                and (
                    current.action == SPELL_WHIRLWIND
                    or current.next_action == SPELL_WHIRLWIND
                    or bool(new_typhoons)
                )
            )
            if not accepted:
                rejected.append(
                    f"Death Knight slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"target ({target_x},{target_y}) ptr 0x{target_unit:08X} "
                    f"action {current.action}/{current.next_action} mana {current.mana}"
                )
                continue
            state = "Typhoon projectile active" if new_typhoons else "spell queued"
            self.log(
                f"WHIRLWIND ORDERED: P{caster.owner + 1} Death Knight slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} -> ({x},{y}); "
                f"action {current.action}/{current.next_action}; mana "
                f"{caster.mana}->{current.mana}; {state}"
            )
            ordered += 1
        self._spell_log_skips("Whirlwind", rejected)
        return ordered

    def _order_rot(
        self, args: dict[str, Any], executing_player: int, x: int, y: int
    ) -> int:
        """Queue Warcraft's persistent SPELL_ROT (Death and Decay) order."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", ROT_CASTER_TYPE))
        if caster_type not in DEATH_KNIGHT_CASTER_TYPES:
            raise RuntimeError(
                "Death and Decay requires Death Knight, Teron Gorefiend, or Gul'dan"
            )
        caster_args = {
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }
        casters = self._selected_units(caster_args, executing_player)
        casters, busy_skips = self._spell_ready_casters(casters, args, "Death and Decay")
        if not casters:
            self.log("DEATH AND DECAY SKIPPED: no ready Death Knight caster matched the trigger")
            self._spell_log_skips("Death and Decay", busy_skips)
            return 0
        native_cost = int(self.spell_path["rot_cost"])
        ordered = 0
        rejected: list[str] = []
        for caster in casters:
            if caster.mana < native_cost:
                rejected.append(
                    f"Death Knight slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"mana {caster.mana}/{native_cost}"
                )
                continue
            before_rot = {
                missile.address for missile in self._active_missiles()
                if missile.missile_type == BT_ROT
                and missile.owner_unit == caster.address
            }
            action_global = int(self.spell_path["action_type_global"])
            before_action_type = self.pm.read_ushort(action_global)
            if before_action_type != 0:
                rejected.append("Death and Decay selector busy with action " + str(before_action_type))
                continue
            self._dispatch_ops([
                ("write_word", action_global, SPELL_ROT),
                (
                    "call",
                    self.order_callees["set_target"],
                    [caster.address, x, y, 0, self.spell_path["do_unit_spell"]],
                ),
                ("write_word", action_global, 0),
            ])
            if self.pm.read_ushort(action_global) != 0:
                raise RuntimeError(
                    "Death and Decay order failed to restore gwActionType"
                )
            data = self.pm.read_bytes(caster.address, UNIT_SIZE)
            if not self._record_is_allocated(data):
                rejected.append(
                    f"Death Knight slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    "became inactive"
                )
                continue
            current = self._decode_unit(caster.address, data)
            target_x = int.from_bytes(data[0x84:0x86], "little", signed=True)
            target_y = int.from_bytes(data[0x86:0x88], "little", signed=True)
            target_unit = int.from_bytes(data[0x88:0x8C], "little")
            new_rot = [
                missile for missile in self._active_missiles()
                if missile.missile_type == BT_ROT
                and missile.owner_unit == caster.address
                and missile.address not in before_rot
            ]
            accepted = (
                target_unit == 0
                and (target_x, target_y) == (x, y)
                and (
                    current.action == SPELL_ROT
                    or current.next_action == SPELL_ROT
                    or bool(new_rot)
                )
            )
            if not accepted:
                rejected.append(
                    f"Death Knight slot {(caster.address-self.unit_pool)//UNIT_SIZE} "
                    f"target ({target_x},{target_y}) ptr 0x{target_unit:08X} "
                    f"action {current.action}/{current.next_action} mana {current.mana}"
                )
                continue
            state = (
                f"{len(new_rot)} Rot projectile(s) active"
                if new_rot else "persistent spell queued"
            )
            self.log(
                f"DEATH AND DECAY ORDERED: P{caster.owner + 1} Death Knight slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} -> ({x},{y}); "
                f"action {current.action}/{current.next_action}; mana "
                f"{caster.mana}->{current.mana}; {native_cost} per wave; {state}"
            )
            ordered += 1
        self._spell_log_skips("Death and Decay", rejected)
        return ordered

    def _order_haste(self, args: dict[str, Any], executing_player: int) -> int:
        """Queue safe, unique Haste orders and prefer non-hasted targets."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", HASTE_CASTER_TYPE))
        if caster_type not in DEATH_KNIGHT_CASTER_TYPES:
            raise RuntimeError(
                "Haste requires Death Knight, Teron Gorefiend, or Gul'dan"
            )
        if "target_player" not in args:
            raise ValueError("Cast Spell: Haste requires target_player")
        target_owner = int(args["target_player"])
        target_type = args.get("target_unit", "Any")
        casters = self._selected_units({
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }, executing_player)
        casters, _ = self._spell_ready_casters(casters, args, "Haste")
        refresh = bool(args.get("refresh_effects", False))
        targets = [
            target for target in self._selected_units({
                "player": target_owner,
                "unit": target_type,
                "location": args.get("target_location", "Anywhere"),
            }, executing_player)
            if target.unit_type < FIRST_BUILDING_TYPE
            and (refresh or target.warp <= 0)
        ]
        if not casters:
            self.log("HASTE SKIPPED: no ready Death Knight caster matched the trigger")
            return 0
        assignments, skipped = self._spell_assign_unique_targets(casters, targets, args)
        if not assignments:
            self.log("HASTE SKIPPED: no non-hasted mobile target remained")
            self._spell_log_skips("Haste", skipped)
            return 0
        native_cost = int(self.spell_path["haste_cost"])
        ordered = 0
        rejected = list(skipped)
        for caster, target in assignments:
            if caster.mana < native_cost:
                rejected.append(
                    f"Death Knight slot {(caster.address-self.unit_pool)//UNIT_SIZE} mana "
                    f"{caster.mana}/{native_cost}"
                )
                continue
            result = self._spell_queue_unit_target(caster, target, SPELL_HASTE, "Haste")
            if result is None:
                continue
            current, current_target, target_pointer = result
            changed = current_target.warp != target.warp
            accepted = changed or (
                target_pointer == target.address
                and (current.action == SPELL_HASTE or current.next_action == SPELL_HASTE)
            )
            if not accepted:
                rejected.append(
                    f"Death Knight slot {(caster.address-self.unit_pool)//UNIT_SIZE} native order "
                    f"not retained for target slot {(target.address-self.unit_pool)//UNIT_SIZE}"
                )
                continue
            self.log(
                f"HASTE ORDERED: P{caster.owner + 1} Death Knight slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} -> P{target.owner + 1} "
                f"{UNIT_NAMES[target.unit_type]} slot "
                f"{(target.address-self.unit_pool)//UNIT_SIZE}; warp "
                f"{target.warp}->{current_target.warp}; action "
                f"{current.action}/{current.next_action}"
            )
            ordered += 1
        self._spell_log_skips("Haste", rejected)
        return ordered

    def _order_armor(self, args: dict[str, Any], executing_player: int) -> int:
        """Queue safe, unique Unholy Armor orders."""
        caster_owner = int(args.get("caster_player", args.get("player", executing_player)))
        caster_type = int(args.get("caster_unit", ARMOR_CASTER_TYPE))
        if caster_type not in DEATH_KNIGHT_CASTER_TYPES:
            raise RuntimeError(
                "Unholy Armor requires Death Knight, Teron Gorefiend, or Gul'dan"
            )
        if "target_player" not in args:
            raise ValueError("Cast Spell: Unholy Armor requires target_player")
        target_owner = int(args["target_player"])
        target_type = args.get("target_unit", "Any")
        casters = self._selected_units({
            "player": caster_owner,
            "unit": caster_type,
            "location": args.get("caster_location", "Anywhere"),
        }, executing_player)
        casters, _ = self._spell_ready_casters(casters, args, "Unholy Armor")
        refresh = bool(args.get("refresh_effects", False))
        targets = [
            target for target in self._selected_units({
                "player": target_owner,
                "unit": target_type,
                "location": args.get("target_location", "Anywhere"),
            }, executing_player)
            if target.unit_type < FIRST_BUILDING_TYPE
            and (refresh or target.armor == 0)
        ]
        if not casters:
            self.log("UNHOLY ARMOR SKIPPED: no ready Death Knight caster matched the trigger")
            return 0
        assignments, skipped = self._spell_assign_unique_targets(casters, targets, args)
        if not assignments:
            self.log("UNHOLY ARMOR SKIPPED: no unarmored mobile target remained")
            self._spell_log_skips("Unholy Armor", skipped)
            return 0
        native_cost = int(self.spell_path["armor_cost"])
        ordered = 0
        rejected = list(skipped)
        for caster, target in assignments:
            if caster.mana < native_cost:
                rejected.append(
                    f"Death Knight slot {(caster.address-self.unit_pool)//UNIT_SIZE} mana "
                    f"{caster.mana}/{native_cost}"
                )
                continue
            result = self._spell_queue_unit_target(
                caster, target, SPELL_ARMOR, "Unholy Armor"
            )
            if result is None:
                continue
            current, current_target, target_pointer = result
            changed = (
                current_target.armor != target.armor
                or current_target.health != target.health
            )
            accepted = changed or (
                target_pointer == target.address
                and (current.action == SPELL_ARMOR or current.next_action == SPELL_ARMOR)
            )
            if not accepted:
                rejected.append(
                    f"Death Knight slot {(caster.address-self.unit_pool)//UNIT_SIZE} native order "
                    f"not retained for target slot {(target.address-self.unit_pool)//UNIT_SIZE}"
                )
                continue
            self.log(
                f"UNHOLY ARMOR ORDERED: P{caster.owner + 1} Death Knight slot "
                f"{(caster.address-self.unit_pool)//UNIT_SIZE} -> P{target.owner + 1} "
                f"{UNIT_NAMES[target.unit_type]} slot "
                f"{(target.address-self.unit_pool)//UNIT_SIZE}; armor "
                f"{target.armor}->{current_target.armor}; HP "
                f"{target.health}->{current_target.health}; action "
                f"{current.action}/{current.next_action}"
            )
            ordered += 1
        self._spell_log_skips("Unholy Armor", rejected)
        return ordered

    def _local_human_player(self) -> int:
        if not self.pm or not self.base:
            raise RuntimeError("Warcraft is not attached; local human player is unavailable")
        owner = int(self.pm.read_uchar(self.base + LOCAL_PLAYER_RVA))
        if not 0 <= owner < 8:
            raise RuntimeError(f"Warcraft reported invalid local human slot {owner}")
        return owner

    def _first_non_local_player(self) -> int:
        local = self._local_human_player()
        # Blank-map/campaign authoring is single-player. Prefer an Empty or Computer
        # slot so the trigger-created opposition can never steal control from the
        # local human. Fall back to the first different P1-P8 slot.
        computers: list[int] = []
        empty_slots: list[int] = []
        fallback: list[int] = []
        for owner in range(8):
            if owner == local:
                continue
            fallback.append(owner)
            try:
                owner_name = str(self._owner_type_name(self._owner_type(owner))).casefold()
            except Exception:
                owner_name = ""
            if owner_name == "computer":
                computers.append(owner)
            elif owner_name == "empty":
                empty_slots.append(owner)
        # Prefer an actual Computer slot so a trigger-created opponent can use
        # Warcraft's normal AI/order machinery when the PUD provides one. A truly
        # blank scenario may only expose Empty slots, which remain valid enemies.
        if computers:
            return computers[0]
        if empty_slots:
            return empty_slots[0]
        if fallback:
            return fallback[0]
        raise RuntimeError("No non-local P1-P8 owner slot is available")

    def _resolve_player_value(self, value: Any, executing_player: int, *, allow_any: bool = False) -> int:
        if value is None:
            value = executing_player
        if isinstance(value, str):
            folded = value.strip().casefold()
            if folded in {"local human", "local player", "current local player"}:
                return self._local_human_player()
            if folded in {"first non-local slot", "first non local slot", "non-local", "non local"}:
                return self._first_non_local_player()
        owner = int(value)
        if owner == LOCAL_HUMAN_PLAYER:
            return self._local_human_player()
        if owner == FIRST_NON_LOCAL_PLAYER:
            return self._first_non_local_player()
        if owner < 0:
            if allow_any:
                return -1
            raise ValueError(f"Invalid player selector {owner}")
        if not 0 <= owner <= 15:
            raise ValueError(f"Invalid player selector {owner}")
        return owner

    def _selected_units(self, args: dict[str, Any], executing_player: int) -> list[Unit]:
        return self._selected_from(self.units(), args, executing_player)

    def _selected_from(self, source: list[Unit], args: dict[str, Any], executing_player: int) -> list[Unit]:
        owner = self._resolve_player_value(args.get("player", executing_player), executing_player, allow_any=True)
        unit_type = args.get("unit", "Any")
        found = [u for u in source if (owner < 0 or u.owner == owner) and (unit_type == "Any" or u.unit_type == int(unit_type))]
        location_name = args.get("location")
        if location_name and location_name != "Anywhere" and self.scenario:
            loc = next((x for x in self.scenario.locations if x.name == location_name), None)
            if not loc: raise ValueError(f"Unknown location: {location_name}")
            found = [u for u in found if loc.left <= u.x <= loc.right and loc.top <= u.y <= loc.bottom]
        return found

    def _selected_missiles(
        self, args: dict[str, Any], executing_player: int
    ) -> list[Missile]:
        missile_value = args.get("missile", args.get("missile_type", "Any"))
        missile_type: int | None
        if isinstance(missile_value, str) and missile_value.strip().casefold() == "any":
            missile_type = None
        else:
            try:
                missile_type = int(missile_value)
            except (TypeError, ValueError):
                name = str(missile_value).strip().casefold()
                missile_type = next(
                    (index for index, label in enumerate(MISSILE_NAMES)
                     if label.casefold() == name),
                    -1,
                )
            if not 0 <= missile_type < BT_NONE:
                raise ValueError(f"Unknown Warcraft missile type: {missile_value}")
        owner = self._resolve_player_value(args.get("player", executing_player), executing_player, allow_any=True)
        owner_unit = args.get("owner_unit", args.get("caster_unit", "Any"))
        owner_addresses = {
            unit.address for unit in self.units()
            if (owner < 0 or unit.owner == owner)
            and (owner_unit == "Any" or unit.unit_type == int(owner_unit))
        }
        found = [
            missile for missile in self._active_missiles()
            if (missile_type is None or missile.missile_type == missile_type)
            and missile.owner_unit in owner_addresses
        ]
        location_name = args.get("location")
        if location_name and location_name != "Anywhere" and self.scenario:
            location = next(
                (item for item in self.scenario.locations if item.name == location_name),
                None,
            )
            if not location:
                raise ValueError(f"Unknown location: {location_name}")
            found = [
                missile for missile in found
                if location.left <= (missile.x >> 5) <= location.right
                and location.top <= (missile.y >> 5) <= location.bottom
            ]
        return found

    def _unit_key(self, unit: Unit) -> tuple[int, int]:
        return ((unit.address - self.unit_pool) // UNIT_SIZE, unit.token)

    def set_action_context(self, context: tuple[int, int, int, int] | None) -> None:
        """Identify the trigger action that owns the next dispatcher callback."""
        self._action_context = None if context is None else (self._trigger_generation, *context)
        self._action_dispatch_cursor = 0

    def finish_action_context(
        self,
        context: tuple[int, int, int, int],
        *,
        keep_for_retry: bool,
    ) -> None:
        owner = (self._trigger_generation, *context)
        if not keep_for_retry:
            self._dispatch_journal.pop(owner, None)
            self._action_value_cache.pop(owner, None)
        self._action_context = None
        self._action_dispatch_cursor = 0

    def _cached_action_value(self, name: str, factory):
        owner = self._action_context
        if owner is None:
            return factory()
        values = self._action_value_cache.setdefault(owner, {})
        if name not in values:
            values[name] = factory()
        return values[name]

    @classmethod
    def _freeze_dispatch_value(cls, value: Any):
        if isinstance(value, (list, tuple)):
            return tuple(cls._freeze_dispatch_value(item) for item in value)
        if isinstance(value, dict):
            return tuple(sorted((key, cls._freeze_dispatch_value(item)) for key, item in value.items()))
        return value

    @classmethod
    def _dispatch_signature(cls, operations: list[tuple]) -> tuple:
        return tuple(cls._freeze_dispatch_value(operation) for operation in operations)

    def _replay_cached_dispatch(self, signature: tuple) -> tuple[bool, int]:
        owner = self._action_context
        if owner is None:
            return False, 0
        journal = self._dispatch_journal.get(owner, [])
        ordinal = self._action_dispatch_cursor
        if ordinal >= len(journal):
            return False, 0
        cached_signature, result = journal[ordinal]
        if cached_signature != signature:
            raise RuntimeError(
                "Dispatcher retry changed call order inside a parked trigger action; "
                "refusing to replay an unrelated native result"
            )
        self._action_dispatch_cursor += 1
        return True, result

    def _record_dispatch_result(
        self,
        owner: tuple[int, ...] | None,
        ordinal: int,
        signature: tuple,
        result: int,
    ) -> None:
        if owner is None:
            return
        journal = self._dispatch_journal.setdefault(owner, [])
        if ordinal < len(journal):
            cached_signature, cached_result = journal[ordinal]
            if cached_signature != signature or cached_result != result:
                raise RuntimeError("Dispatcher result journal changed during action retry")
        elif ordinal == len(journal):
            journal.append((signature, result))
        else:
            raise RuntimeError("Dispatcher result journal has a missing callback entry")
        if owner == self._action_context and self._action_dispatch_cursor == ordinal:
            self._action_dispatch_cursor += 1

    def _configure_dispatcher_layout(self, base_address: int) -> None:
        self.dispatcher_memory = int(base_address)
        self.dispatcher_command_address = self.dispatcher_memory + DISPATCH_COMMAND_OFFSET
        self.dispatcher_status_address = self.dispatcher_memory + DISPATCH_STATE_OFFSET
        self.dispatcher_result_address = self.dispatcher_memory + DISPATCH_RESULT_OFFSET
        self.dispatcher_heartbeat_address = self.dispatcher_memory + DISPATCH_HEARTBEAT_OFFSET
        self.dispatcher_magic_address = self.dispatcher_memory + DISPATCH_MAGIC_OFFSET
        self.dispatcher_vision_masks_address = self.dispatcher_memory + DISPATCH_VISION_MASKS_OFFSET
        self.dispatcher_vision_active_address = self.dispatcher_memory + DISPATCH_VISION_ACTIVE_OFFSET
        self.dispatcher_vision_mode_address = self.dispatcher_memory + DISPATCH_VISION_MODE_OFFSET
        self.diplomacy_guard_code_address = self.dispatcher_memory + DIPLOMACY_GUARD_CODE_OFFSET
        self.diplomacy_guard_hook_address = self.base + DIPLOMACY_UPDATE_RVA
        self.dispatcher_chat_packet_address = self.dispatcher_memory + CHAT_PACKET_OFFSET
        self.dispatcher_chat_text_address = self.dispatcher_memory + CHAT_LOCAL_TEXT_OFFSET
        self.dispatcher_hook_address = self.base + SIMULATION_DISPATCH_HOOK_RVA

    @staticmethod
    def _relative32(source_next: int, destination: int) -> bytes:
        displacement = int(destination) - int(source_next)
        if not -0x80000000 <= displacement <= 0x7FFFFFFF:
            raise RuntimeError("x86 dispatcher branch is outside rel32 range")
        return struct.pack("<i", displacement)

    def _build_simulation_hook(self) -> bytes:
        """Build the simulation mailbox plus the post-reset local fog compositor.

        Source ``game_unit_loop`` calls ``prep_mask_map`` immediately before
        ``unit_run`` and calls ``unitdraw_prep`` afterward. RVA 0xEEA80 is the
        validated Remaster ``unit_run`` entry, so this trampoline executes in the
        only safe no-flash window: after Warcraft clears the fog planes and before
        either units or terrain are rendered.

        When shared vision is active, every allocated unit whose source mask grants
        sight to the local player is passed through Warcraft's native
        ``unit_unmask_square`` as the local owner for the duration of that one call.
        The real owner byte is restored immediately. This updates the actual local,
        gray, and all-player fog maps with Warcraft's normal sight-radius tables;
        it does not toggle gbMultiPlayer, rebuild the whole fog cache, or alter unit
        ownership outside the native unmask call.
        """
        code = bytearray(b"\x9C\x60")  # pushfd; pushad
        fixups: list[tuple[int, str]] = []
        labels: dict[str, int] = {}

        def near_jump(opcode: bytes, label: str) -> None:
            code.extend(opcode)
            fixups.append((len(code), label))
            code.extend(b"\x00\x00\x00\x00")

        def mark(label: str) -> None:
            labels[label] = len(code)

        # Publish the complete trigger-owned gSharedVision matrix first. This
        # preserves unit-mask semantics and protects against diplomacy rebuilds.
        code += b"\x80\x3D" + struct.pack("<I", self.dispatcher_vision_active_address) + b"\x00"
        near_jump(b"\x0F\x84", "after_vision")
        code += b"\xA1" + struct.pack("<I", self.dispatcher_vision_masks_address)
        code += b"\xA3" + struct.pack("<I", self.diplomacy_path["shared_vision"])
        code += b"\xA1" + struct.pack("<I", self.dispatcher_vision_masks_address + 4)
        code += b"\xA3" + struct.pack("<I", self.diplomacy_path["shared_vision"] + 4)

        # local player must be P1-P8.
        code += b"\x0F\xB6\x1D" + struct.pack("<I", self.base + LOCAL_PLAYER_RVA)  # movzx ebx,byte [local]
        code += b"\x83\xFB\x07"  # cmp ebx,7
        near_jump(b"\x0F\x87", "after_vision")  # ja

        # Always follow the live gpUnits allocation instead of caching its pointer.
        code += b"\x8B\x35" + struct.pack("<I", self.base + UNIT_ARRAY_RVA)  # mov esi,[gpUnits]
        code += b"\x85\xF6"  # test esi,esi
        near_jump(b"\x0F\x84", "after_vision")
        code += b"\xBF" + struct.pack("<I", int(self.max_units))  # mov edi,max_units

        mark("unit_loop")
        # Exact source allocation condition: skip FREE/DIEING/DEAD records.
        code += b"\x66\xF7\x46\x1E\x07\x00"  # test word [esi+1Eh],7
        near_jump(b"\x0F\x85", "next_unit")
        code += b"\x0F\xB6\x46\x2C"  # movzx eax,byte [esi+owner]
        code += b"\x83\xF8\x07"          # cmp eax,7
        near_jump(b"\x0F\x87", "next_unit")
        # ECX = gSharedVision[source owner]; test viewer bit for local player EBX.
        code += b"\x0F\xB6\x88" + struct.pack("<I", self.dispatcher_vision_masks_address)
        code += b"\x0F\xA3\xD9"  # bt ecx,ebx
        near_jump(b"\x0F\x83", "next_unit")  # jnc

        # Save owner, impersonate the local human only during native fog unmask,
        # then restore the source owner before Warcraft's unit loop continues.
        code += b"\x50"                    # push eax (saved owner)
        code += b"\x88\x5E\x2C"        # mov [esi+2Ch],bl
        code += b"\x56"                    # push esi
        call_offset = len(code)
        code += b"\xE8" + self._relative32(
            self.dispatcher_memory + call_offset + 5,
            self.move_callees["unmask_square"],
        )
        code += b"\x83\xC4\x04"        # add esp,4
        code += b"\x58"                    # pop eax
        code += b"\x88\x46\x2C"        # mov [esi+2Ch],al

        mark("next_unit")
        code += b"\x81\xC6" + struct.pack("<I", UNIT_SIZE)  # add esi,152
        code += b"\x4F"  # dec edi
        near_jump(b"\x0F\x85", "unit_loop")
        mark("after_vision")

        # Original one-command simulation mailbox behavior remains unchanged.
        code += b"\xFF\x05" + struct.pack("<I", self.dispatcher_heartbeat_address)
        code += b"\x83\x3D" + struct.pack("<I", self.dispatcher_status_address) + b"\x01"
        near_jump(b"\x0F\x85", "after_command")
        code += (
            b"\xC7\x05" + struct.pack("<I", self.dispatcher_status_address)
            + struct.pack("<I", DISPATCH_STATE_EXECUTING)
        )
        code += b"\xB8" + struct.pack("<I", self.dispatcher_command_address) + b"\xFF\xD0"
        code += b"\xA3" + struct.pack("<I", self.dispatcher_result_address)
        code += (
            b"\xC7\x05" + struct.pack("<I", self.dispatcher_status_address)
            + struct.pack("<I", DISPATCH_STATE_COMPLETE)
        )
        mark("after_command")

        for displacement_offset, label in fixups:
            if label not in labels:
                raise RuntimeError(f"Missing simulation-hook label: {label}")
            source_next = displacement_offset + 4
            code[displacement_offset:displacement_offset + 4] = struct.pack(
                "<i", labels[label] - source_next
            )

        code += b"\x61\x9D"  # popad; popfd
        code += SIMULATION_DISPATCH_ORIGINAL
        jmp_offset = len(code)
        code += b"\xE9" + self._relative32(
            self.dispatcher_memory + jmp_offset + 5,
            self.base + SIMULATION_DISPATCH_RETURN_RVA,
        )
        if len(code) >= DIPLOMACY_GUARD_CODE_OFFSET:
            raise RuntimeError("Simulation dispatcher hook overlaps diplomacy guard code")
        return bytes(code)

    def _build_diplomacy_vision_guard(self) -> bytes:
        """Preserve trigger-owned vision at the source of native diplomacy rebuilds.

        Warcraft's updater receives ``(player, relations, vision, victory)``. When
        shared vision is active, substitute the desired source mask in the caller's
        stack before replaying the exact overwritten prologue. This prevents the
        transient off-state instead of repairing it after the renderer has seen it.
        """
        code = bytearray(b"\x9C\x50\x51")  # pushfd; push eax; push ecx
        code += b"\x80\x3D" + struct.pack("<I", self.dispatcher_vision_active_address) + b"\x00"
        inactive_jump = len(code)
        code += b"\x0F\x84\x00\x00\x00\x00"
        # Original entry ESP + 4 (player) is current ESP + 16 after three pushes.
        code += b"\x0F\xB6\x44\x24\x10"  # movzx eax,byte ptr [esp+10h]
        code += b"\x83\xF8\x07"               # cmp eax,7
        invalid_jump = len(code)
        code += b"\x0F\x87\x00\x00\x00\x00"
        code += b"\x8A\x88" + struct.pack("<I", self.dispatcher_vision_masks_address)
        # Original vision byte argument at entry ESP+0Ch is now current ESP+18h.
        code += b"\x88\x4C\x24\x18"
        restore = len(code)
        code[inactive_jump + 2:inactive_jump + 6] = struct.pack(
            "<i", restore - (inactive_jump + 6)
        )
        code[invalid_jump + 2:invalid_jump + 6] = struct.pack(
            "<i", restore - (invalid_jump + 6)
        )
        code += b"\x59\x58\x9D"  # pop ecx; pop eax; popfd
        original = DIPLOMACY_UPDATE_SIGNATURE[:DIPLOMACY_GUARD_HOOK_LENGTH]
        code += original
        jmp_offset = len(code)
        code += b"\xE9" + self._relative32(
            self.diplomacy_guard_code_address + jmp_offset + 5,
            self.diplomacy_guard_hook_address + DIPLOMACY_GUARD_HOOK_LENGTH,
        )
        if len(code) >= DISPATCH_COMMAND_OFFSET - DIPLOMACY_GUARD_CODE_OFFSET:
            raise RuntimeError("Diplomacy guard code overlaps dispatcher command slot")
        return bytes(code)

    def _install_diplomacy_vision_guard(self) -> None:
        original = DIPLOMACY_UPDATE_SIGNATURE[:DIPLOMACY_GUARD_HOOK_LENGTH]
        current = self.pm.read_bytes(self.diplomacy_guard_hook_address, DIPLOMACY_GUARD_HOOK_LENGTH)
        expected_patch = (
            b"\xE9"
            + self._relative32(self.diplomacy_guard_hook_address + 5, self.diplomacy_guard_code_address)
            + b"\x90" * (DIPLOMACY_GUARD_HOOK_LENGTH - 5)
        )
        if current == expected_patch:
            self.diplomacy_guard_original_bytes = original
            return
        if current != original:
            raise RuntimeError(
                "Diplomacy updater entry is already modified. Fully restart Warcraft "
                "before attaching Trigger Studio 1.28.0."
            )
        guard_code = self._build_diplomacy_vision_guard()
        self.pm.write_bytes(self.diplomacy_guard_code_address, guard_code, len(guard_code))
        self._flush_dispatch_code(self.diplomacy_guard_code_address, len(guard_code))
        self._write_executable_bytes(self.diplomacy_guard_hook_address, expected_patch)
        self.diplomacy_guard_original_bytes = original

    def _restore_diplomacy_vision_guard(self) -> None:
        if not self.diplomacy_guard_hook_address:
            return
        current = self.pm.read_bytes(self.diplomacy_guard_hook_address, DIPLOMACY_GUARD_HOOK_LENGTH)
        if current[:1] == b"\xE9":
            target = self.diplomacy_guard_hook_address + 5 + struct.unpack("<i", current[1:5])[0]
            if target == self.diplomacy_guard_code_address:
                self._write_executable_bytes(
                    self.diplomacy_guard_hook_address,
                    self.diplomacy_guard_original_bytes
                    or DIPLOMACY_UPDATE_SIGNATURE[:DIPLOMACY_GUARD_HOOK_LENGTH],
                )

    def _write_executable_bytes(self, address: int, data: bytes) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = wintypes.HANDLE(self.pm.process_handle)
        old_protect = wintypes.DWORD()
        kernel32.VirtualProtectEx.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
            wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
        ]
        kernel32.VirtualProtectEx.restype = wintypes.BOOL
        kernel32.FlushInstructionCache.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
        ]
        kernel32.FlushInstructionCache.restype = wintypes.BOOL
        if not kernel32.VirtualProtectEx(
            handle, ctypes.c_void_p(address), len(data), 0x40, ctypes.byref(old_protect)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            self.pm.write_bytes(address, data, len(data))
            if self.pm.read_bytes(address, len(data)) != data:
                raise RuntimeError(f"Executable write verification failed at 0x{address:08X}")
            if not kernel32.FlushInstructionCache(handle, ctypes.c_void_p(address), len(data)):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            restored = wintypes.DWORD()
            kernel32.VirtualProtectEx(
                handle, ctypes.c_void_p(address), len(data), old_protect.value,
                ctypes.byref(restored),
            )

    def _flush_dispatch_code(self, address: int, size: int) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.FlushInstructionCache.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
        ]
        kernel32.FlushInstructionCache.restype = wintypes.BOOL
        if not kernel32.FlushInstructionCache(
            wintypes.HANDLE(self.pm.process_handle), ctypes.c_void_p(address), size
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    def _install_simulation_dispatcher(self) -> None:
        """Install or reuse the proven module+0xEEA80 simulation mailbox hook."""
        import ctypes
        from ctypes import wintypes

        hook_address = self.base + SIMULATION_DISPATCH_HOOK_RVA
        current = self.pm.read_bytes(hook_address, len(SIMULATION_DISPATCH_ORIGINAL))

        # A previous studio instance may have closed unexpectedly. Reuse its
        # persistent mailbox when the jump target carries our exact version magic.
        if current[:1] == b"\xE9":
            target = hook_address + 5 + struct.unpack("<i", current[1:5])[0]
            try:
                magic = self.pm.read_uint(target + DISPATCH_MAGIC_OFFSET)
            except Exception:
                magic = 0
            if magic == DISPATCH_MAGIC:
                self._configure_dispatcher_layout(target)
                self.dispatcher_original_bytes = SIMULATION_DISPATCH_ORIGINAL
                self.dispatcher_installed = True
                state = self.pm.read_uint(self.dispatcher_status_address)
                if state != DISPATCH_STATE_EXECUTING:
                    self.pm.write_uint(self.dispatcher_status_address, DISPATCH_STATE_IDLE)
                    self.pm.write_uint(self.dispatcher_result_address, 0)
                self._install_diplomacy_vision_guard()
                self.pm.write_uchar(self.dispatcher_vision_active_address, 0)
                self.pm.write_uchar(
                    self.dispatcher_vision_mode_address,
                    int(self.pm.read_uchar(self.diplomacy_path["multiplayer_gate"])) & 0xFF,
                )
                self.log("Reused the stable simulation dispatcher mailbox and diplomacy vision guard")
                return

        if current != SIMULATION_DISPATCH_ORIGINAL:
            raise RuntimeError(
                "Simulation hook bytes at RVA 0xEEA80 are not original. Close other Warcraft "
                "tools and fully restart Warcraft before attaching."
            )

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = wintypes.HANDLE(self.pm.process_handle)
        kernel32.VirtualAllocEx.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
            wintypes.DWORD, wintypes.DWORD,
        ]
        kernel32.VirtualAllocEx.restype = ctypes.c_void_p
        allocation = kernel32.VirtualAllocEx(
            handle, None, DISPATCH_MEMORY_SIZE, 0x3000, 0x40
        )
        allocation_value = int(allocation or 0)
        if not allocation_value:
            raise ctypes.WinError(ctypes.get_last_error())

        self._configure_dispatcher_layout(allocation_value)
        self.dispatcher_original_bytes = current
        try:
            self.pm.write_bytes(
                self.dispatcher_memory, b"\xCC" * DISPATCH_MEMORY_SIZE,
                DISPATCH_MEMORY_SIZE,
            )
            self.pm.write_uint(self.dispatcher_status_address, DISPATCH_STATE_IDLE)
            self.pm.write_uint(self.dispatcher_result_address, 0)
            self.pm.write_uint(self.dispatcher_heartbeat_address, 0)
            self.pm.write_uint(self.dispatcher_magic_address, DISPATCH_MAGIC)
            self.pm.write_bytes(
                self.dispatcher_vision_masks_address,
                bytes(1 << source for source in range(8)),
                8,
            )
            self.pm.write_uchar(self.dispatcher_vision_active_address, 0)
            self.pm.write_uchar(
                self.dispatcher_vision_mode_address,
                int(self.pm.read_uchar(self.diplomacy_path["multiplayer_gate"])) & 0xFF,
            )
            hook_code = self._build_simulation_hook()
            self.pm.write_bytes(self.dispatcher_memory, hook_code, len(hook_code))
            self._flush_dispatch_code(self.dispatcher_memory, len(hook_code))
            patch = b"\xE9" + self._relative32(hook_address + 5, self.dispatcher_memory)
            self._write_executable_bytes(hook_address, patch)
            self._install_diplomacy_vision_guard()
            self.dispatcher_installed = True
        except Exception:
            try:
                self._restore_diplomacy_vision_guard()
            except Exception:
                pass
            current_hook = self.pm.read_bytes(hook_address, 5)
            if current_hook[:1] == b"\xE9":
                target = hook_address + 5 + struct.unpack("<i", current_hook[1:5])[0]
                if target == self.dispatcher_memory:
                    self._write_executable_bytes(hook_address, current)
            kernel32.VirtualFreeEx.argtypes = [
                wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD,
            ]
            kernel32.VirtualFreeEx(handle, ctypes.c_void_p(self.dispatcher_memory), 0, 0x8000)
            self.dispatcher_memory = 0
            raise

    def _uninstall_simulation_dispatcher(self) -> None:
        if not self.dispatcher_installed or not self.dispatcher_memory:
            return
        import ctypes
        from ctypes import wintypes

        state = self.pm.read_uint(self.dispatcher_status_address)
        if state == DISPATCH_STATE_QUEUED:
            self.pm.write_uint(self.dispatcher_status_address, DISPATCH_STATE_IDLE)
            state = DISPATCH_STATE_IDLE
        if state == DISPATCH_STATE_EXECUTING:
            deadline = time.monotonic() + 0.75
            while time.monotonic() < deadline:
                time.sleep(0.005)
                state = self.pm.read_uint(self.dispatcher_status_address)
                if state != DISPATCH_STATE_EXECUTING:
                    break
        if state == DISPATCH_STATE_EXECUTING:
            raise RuntimeError("a simulation-thread native command is still executing")
        # COMPLETE is published immediately after the command returns, a few
        # instructions before the trampoline jumps back into Warcraft. Give that
        # tiny epilogue time to retire before freeing its executable allocation.
        if state == DISPATCH_STATE_COMPLETE:
            time.sleep(0.02)

        # Disable the shadow table before removing either executable guard, then
        # restore the native diplomacy updater while its trampoline is still valid.
        self.pm.write_uchar(self.dispatcher_vision_active_address, 0)
        self.pm.write_uchar(self.dispatcher_vision_mode_address, 0)
        self._restore_diplomacy_vision_guard()

        current = self.pm.read_bytes(self.dispatcher_hook_address, 5)
        if current[:1] == b"\xE9":
            target = self.dispatcher_hook_address + 5 + struct.unpack("<i", current[1:5])[0]
            if target == self.dispatcher_memory:
                self._write_executable_bytes(
                    self.dispatcher_hook_address,
                    self.dispatcher_original_bytes or SIMULATION_DISPATCH_ORIGINAL,
                )

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.VirtualFreeEx.argtypes = [
            wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD,
        ]
        kernel32.VirtualFreeEx.restype = wintypes.BOOL
        kernel32.VirtualFreeEx(
            wintypes.HANDLE(self.pm.process_handle),
            ctypes.c_void_p(self.dispatcher_memory), 0, 0x8000,
        )
        self.dispatcher_installed = False
        self.dispatcher_memory = 0
        self._dispatch_inflight = None

    def _encode_dispatch_program(self, operations: list[tuple]) -> bytes:
        """Encode one atomic mailbox command that returns its final EAX."""
        code = bytearray(b"\x31\xC0")  # deterministic zero result for write-only programs

        def emit_end_jump(opcode: bytes, fixups: list[int]) -> None:
            code.extend(opcode)
            fixups.append(len(code))
            code.extend(b"\x00\x00\x00\x00")

        def patch_end_jumps(fixups: list[int]) -> None:
            end = len(code)
            for offset in fixups:
                code[offset:offset + 4] = struct.pack("<i", end - (offset + 4))

        def emit_unit_identity_guard(
            address: int, token: int, unit_type: int, owner: int, fixups: list[int]
        ) -> None:
            code.extend(b"\x81\x3D" + struct.pack("<I", address + 0x10) + struct.pack("<I", token & 0xFFFFFFFF))
            emit_end_jump(b"\x0F\x85", fixups)  # jne
            code.extend(b"\x80\x3D" + struct.pack("<I", address + 0x27) + bytes([unit_type & 0xFF]))
            emit_end_jump(b"\x0F\x85", fixups)
            code.extend(b"\x80\x3D" + struct.pack("<I", address + 0x2C) + bytes([owner & 0xFF]))
            emit_end_jump(b"\x0F\x85", fixups)
            code.extend(b"\x66\xF7\x05" + struct.pack("<I", address + 0x1E) + b"\x0F\x00")
            emit_end_jump(b"\x0F\x85", fixups)
            code.extend(b"\x66\x83\x3D" + struct.pack("<I", address + 0x22) + b"\x00")
            emit_end_jump(b"\x0F\x84", fixups)  # je

        for operation in operations:
            kind = operation[0]
            if kind == "call":
                _kind, address, args = operation
                if len(args) * 4 > 0x7F:
                    raise ValueError("Dispatcher call has too many cdecl arguments")
                code += b"".join(
                    b"\x68" + struct.pack("<I", value & 0xFFFFFFFF)
                    for value in reversed(args)
                )
                code += b"\xB8" + struct.pack("<I", address) + b"\xFF\xD0"
                if args:
                    code += b"\x83\xC4" + bytes([len(args) * 4])
            elif kind == "call_loop":
                _kind, address, args, count = operation
                if not 1 <= int(count) <= 4096:
                    raise ValueError(f"Dispatcher loop count is out of range: {count}")
                if len(args) * 4 > 0x7F:
                    raise ValueError("Dispatcher loop call has too many cdecl arguments")
                code += b"\xBF" + struct.pack("<I", int(count))
                loop_start = len(code)
                code += b"".join(
                    b"\x68" + struct.pack("<I", value & 0xFFFFFFFF)
                    for value in reversed(args)
                )
                code += b"\xB8" + struct.pack("<I", address) + b"\xFF\xD0"
                if args:
                    code += b"\x83\xC4" + bytes([len(args) * 4])
                code += b"\x4F\x0F\x85"
                code += struct.pack("<i", loop_start - (len(code) + 4))
            elif kind == "call_until_word_flag":
                _kind, address, args, count, flag_address, mask = operation
                if not 1 <= int(count) <= 4096:
                    raise ValueError(f"Dispatcher guarded-loop count is out of range: {count}")
                if len(args) * 4 > 0x7F:
                    raise ValueError("Dispatcher guarded-loop call has too many cdecl arguments")
                code += b"\xBF" + struct.pack("<I", int(count))
                loop_start = len(code)
                code += b"".join(
                    b"\x68" + struct.pack("<I", value & 0xFFFFFFFF)
                    for value in reversed(args)
                )
                code += b"\xB8" + struct.pack("<I", address) + b"\xFF\xD0"
                if args:
                    code += b"\x83\xC4" + bytes([len(args) * 4])
                code += (
                    b"\x66\xF7\x05" + struct.pack("<I", flag_address)
                    + struct.pack("<H", mask & 0xFFFF)
                    + b"\x0F\x85\x07\x00\x00\x00"
                )
                code += b"\x4F\x0F\x85"
                code += struct.pack("<i", loop_start - (len(code) + 4))
            elif kind == "safe_auto_heal":
                (
                    _kind, caster, caster_token, caster_type, caster_owner,
                    target, target_token, target_type, target_owner, hp_max,
                    mana_cost, keep_full, visual_address, sound_address,
                ) = operation
                if not 1 <= int(mana_cost) <= 127:
                    raise ValueError(f"Unsafe automatic Heal mana cost: {mana_cost}")
                fixups: list[int] = []
                emit_unit_identity_guard(caster, caster_token, caster_type, caster_owner, fixups)
                emit_unit_identity_guard(target, target_token, target_type, target_owner, fixups)
                # EAX=current HP, EBX=lost HP, EDI=min(40,lost,mana/cost).
                code += b"\x0F\xB7\x05" + struct.pack("<I", target + 0x22)
                code += b"\x3D" + struct.pack("<I", int(hp_max))
                emit_end_jump(b"\x0F\x83", fixups)  # jae full health
                code += b"\xBB" + struct.pack("<I", int(hp_max)) + b"\x2B\xD8"
                code += b"\xBF\x28\x00\x00\x00\x3B\xDF\x0F\x42\xFB"
                if keep_full:
                    code += b"\xC6\x05" + struct.pack("<I", caster + 0x26) + b"\xFF"
                else:
                    code += b"\x0F\xB6\x0D" + struct.pack("<I", caster + 0x26)
                    code += b"\x8B\xC1\x33\xD2\xBB" + struct.pack("<I", int(mana_cost))
                    code += b"\xF7\xF3\x3B\xC7\x0F\x42\xF8"
                code += b"\x85\xFF"
                emit_end_jump(b"\x0F\x84", fixups)
                code += b"\x0F\xB7\x05" + struct.pack("<I", target + 0x22)
                code += b"\x03\xC7\x66\xA3" + struct.pack("<I", target + 0x22)
                if not keep_full:
                    code += b"\x6B\xC7" + bytes([int(mana_cost) & 0xFF])
                    code += b"\x28\x05" + struct.pack("<I", caster + 0x26)
                code += b"\x66\xC7\x05" + struct.pack("<I", caster + 0x44) + b"\x00\x00"
                # Native Heal visual and sound, but without action_heal's raw target pointer.
                code += b"\x6A\x09\x68" + struct.pack("<I", target)
                code += b"\xB8" + struct.pack("<I", visual_address) + b"\xFF\xD0\x83\xC4\x08"
                code += b"\x6A\x06\x68" + struct.pack("<I", target)
                code += b"\xB8" + struct.pack("<I", sound_address) + b"\xFF\xD0\x83\xC4\x08"
                patch_end_jumps(fixups)
            elif kind == "safe_auto_flame_shield":
                (
                    _kind, caster, caster_token, caster_type, caster_owner,
                    target, target_token, target_type, target_owner, mana_cost,
                    keep_full, bullet_address, sound_address,
                ) = operation
                if not 1 <= int(mana_cost) <= 255:
                    raise ValueError(f"Unsafe automatic Flame Shield mana cost: {mana_cost}")
                fixups: list[int] = []
                emit_unit_identity_guard(caster, caster_token, caster_type, caster_owner, fixups)
                emit_unit_identity_guard(target, target_token, target_type, target_owner, fixups)
                code += b"\x66\x83\x3D" + struct.pack("<I", target + 0x4E) + b"\x00"
                emit_end_jump(b"\x0F\x85", fixups)
                if keep_full:
                    code += b"\xC6\x05" + struct.pack("<I", caster + 0x26) + b"\xFF"
                else:
                    code += b"\x80\x3D" + struct.pack("<I", caster + 0x26) + bytes([int(mana_cost) & 0xFF])
                    emit_end_jump(b"\x0F\x82", fixups)  # jb insufficient mana
                    code += b"\x80\x2D" + struct.pack("<I", caster + 0x26) + bytes([int(mana_cost) & 0xFF])
                code += b"\x66\xC7\x05" + struct.pack("<I", caster + 0x44) + b"\x00\x00"
                code += b"\x66\xC7\x05" + struct.pack("<I", target + 0x4E) + b"\xF4\x01"
                # bullet_create_fireshield needs caster->target for the duration of
                # the call. Save and restore the route target atomically.
                code += b"\xFF\x35" + struct.pack("<I", caster + 0x88)
                code += b"\xFF\x35" + struct.pack("<I", caster + 0x84)
                code += b"\xA1" + struct.pack("<I", target + 0x18)
                code += b"\xA3" + struct.pack("<I", caster + 0x84)
                code += b"\xC7\x05" + struct.pack("<I", caster + 0x88) + struct.pack("<I", target)
                code += b"\x68" + struct.pack("<I", caster)
                code += b"\xB8" + struct.pack("<I", bullet_address) + b"\xFF\xD0\x83\xC4\x04"
                code += b"\x58\xA3" + struct.pack("<I", caster + 0x84)
                code += b"\x58\xA3" + struct.pack("<I", caster + 0x88)
                code += b"\x6A\x04\x68" + struct.pack("<I", target)
                code += b"\xB8" + struct.pack("<I", sound_address) + b"\xFF\xD0\x83\xC4\x08"
                patch_end_jumps(fixups)
            elif kind == "write_bytes":
                _kind, address, value = operation
                raw = bytes(value)
                if len(raw) > CHAT_PACKET_CAPACITY:
                    raise ValueError(
                        f"Dispatcher byte write is too large: {len(raw)} > {CHAT_PACKET_CAPACITY}"
                    )
                offset = 0
                while offset + 4 <= len(raw):
                    code += (
                        b"\xC7\x05" + struct.pack("<I", address + offset)
                        + raw[offset:offset + 4]
                    )
                    offset += 4
                while offset < len(raw):
                    code += (
                        b"\xC6\x05" + struct.pack("<I", address + offset)
                        + raw[offset:offset + 1]
                    )
                    offset += 1
            elif kind == "write_bytes_indirect":
                _kind, pointer_global, value = operation
                raw = bytes(value)
                if len(raw) > CHAT_PACKET_CAPACITY:
                    raise ValueError(
                        f"Dispatcher indirect byte write is too large: "
                        f"{len(raw)} > {CHAT_PACKET_CAPACITY}"
                    )
                # map_msg may rotate/free/reallocate its destination slot. Load
                # the final pointer only after map_msg returns, exactly where the
                # renderer will later read it. A null pointer simply skips the
                # rewrite instead of crashing Warcraft.
                code += b"\x8B\x3D" + struct.pack("<I", pointer_global)  # mov edi,[abs]
                code += b"\x85\xFF\x0F\x84"                         # test edi,edi; je skip
                skip_displacement_offset = len(code)
                code += b"\x00\x00\x00\x00"
                rewrite_start = len(code)
                offset = 0
                while offset + 4 <= len(raw):
                    if offset == 0:
                        code += b"\xC7\x07" + raw[offset:offset + 4]
                    elif offset <= 0x7F:
                        code += b"\xC7\x47" + bytes([offset]) + raw[offset:offset + 4]
                    else:
                        code += b"\xC7\x87" + struct.pack("<I", offset) + raw[offset:offset + 4]
                    offset += 4
                while offset < len(raw):
                    if offset == 0:
                        code += b"\xC6\x07" + raw[offset:offset + 1]
                    elif offset <= 0x7F:
                        code += b"\xC6\x47" + bytes([offset]) + raw[offset:offset + 1]
                    else:
                        code += b"\xC6\x87" + struct.pack("<I", offset) + raw[offset:offset + 1]
                    offset += 1
                rewrite_end = len(code)
                struct.pack_into(
                    "<i", code, skip_displacement_offset,
                    rewrite_end - (skip_displacement_offset + 4),
                )
            elif kind == "write_byte":
                _kind, address, value = operation
                code += b"\xC6\x05" + struct.pack("<I", address) + bytes([value & 0xFF])
            elif kind == "write_word":
                _kind, address, value = operation
                code += b"\x66\xC7\x05" + struct.pack("<I", address) + struct.pack("<H", value & 0xFFFF)
            elif kind == "or_word":
                _kind, address, value = operation
                code += b"\x66\x81\x0D" + struct.pack("<I", address) + struct.pack("<H", value & 0xFFFF)
            elif kind == "write_dword":
                _kind, address, value = operation
                code += b"\xC7\x05" + struct.pack("<I", address) + struct.pack("<I", value & 0xFFFFFFFF)
            elif kind == "or_byte":
                _kind, address, value = operation
                code += b"\x80\x0D" + struct.pack("<I", address) + bytes([value & 0xFF])
            else:
                raise ValueError(f"Unsupported dispatcher operation: {kind}")
        code += b"\xC3"
        if len(code) > DISPATCH_COMMAND_CAPACITY:
            raise RuntimeError(
                f"Atomic dispatcher program is too large ({len(code)} > {DISPATCH_COMMAND_CAPACITY})"
            )
        return bytes(code)

    def _defer_inflight_dispatch(self, pending: _InFlightDispatch) -> None:
        now = time.monotonic()
        age = now - pending.started_at
        if age >= 2.0 and (
            pending.last_notice <= 0.0 or now - pending.last_notice >= DISPATCH_NOTICE_INTERVAL
        ):
            state = self.pm.read_uint(pending.status_address)
            heartbeat = self.pm.read_uint(self.dispatcher_heartbeat_address)
            ticks = (heartbeat - pending.heartbeat_at_queue) & 0xFFFFFFFF
            phase = "queued for the next active simulation update"
            if state == DISPATCH_STATE_EXECUTING:
                phase = "executing inside Warcraft's simulation update"
            self.log(
                f"SIMULATION DISPATCH WAIT: native command has been {phase} for {age:.1f}s "
                f"({pending.call_count} call(s), heartbeat +{ticks}). The trigger action remains parked."
            )
            pending.last_notice = now
        raise ActionDeferred(
            "Warcraft simulation-thread command is pending; action parked for automatic retry",
            retry_after=DISPATCH_RETRY_DELAY,
        )

    def _consume_inflight_dispatch(self, signature: tuple) -> int | None:
        pending = self._dispatch_inflight
        if pending is None:
            return None
        if self.pm.read_uint(pending.status_address) != DISPATCH_STATE_COMPLETE:
            self._defer_inflight_dispatch(pending)

        if pending.owner is not None and pending.owner[0] != self._trigger_generation:
            elapsed = time.monotonic() - pending.started_at
            self._dispatch_journal.pop(pending.owner, None)
            self.pm.write_uint(pending.status_address, DISPATCH_STATE_IDLE)
            self._dispatch_inflight = None
            self._last_dispatch = time.monotonic()
            self.log(
                f"SIMULATION DISPATCH RECOVERED: command from the previous trigger run "
                f"completed after {elapsed:.1f}s; stale return value discarded"
            )
            return None

        if pending.owner != self._action_context:
            raise ActionDeferred(
                "Completed simulation command is waiting for its original trigger action",
                retry_after=DISPATCH_RETRY_DELAY,
            )
        if pending.signature != signature:
            raise RuntimeError(
                "Dispatcher retry did not match the parked simulation command; "
                "refusing to consume an unrelated result"
            )

        result = self.pm.read_uint(pending.result_address)
        self._record_dispatch_result(
            pending.owner, pending.ordinal, pending.signature, result
        )
        elapsed = time.monotonic() - pending.started_at
        self.pm.write_uint(pending.status_address, DISPATCH_STATE_IDLE)
        self._dispatch_inflight = None
        self._last_dispatch = time.monotonic()
        if elapsed >= 2.0:
            self.log(
                f"SIMULATION DISPATCH RECOVERED: parked command completed after {elapsed:.1f}s; "
                "resuming the trigger action"
            )
        return result

    def _call_damage_unit(self, attacker: Unit, target: Unit, damage: int) -> None:
        """Invoke damage_damage_unit on Warcraft's simulation thread."""
        self._call_cdecl(self.damage_unit_address, [attacker.address, target.address, damage])

    def _call_cdecl(self, address: int, args: list[int]) -> int:
        return self._call_cdecl_sequence([(address, args)])

    def _call_cdecl_sequence(self, calls: list[tuple[int, list[int]]]) -> int:
        """Run one or more cdecl calls atomically on Warcraft's simulation thread."""
        return self._dispatch_ops([("call", address, args) for address, args in calls])

    def _call_cdecl_batched(self, calls: list[tuple[int, list[int]]]) -> None:
        """Run ordered callbacks in bounded simulation-thread mailbox commands."""
        for start in range(0, len(calls), 32):
            self._call_cdecl_sequence(calls[start:start + 32])

    def _dispatch_ops(self, operations: list[tuple]) -> int:
        """Serialize one atomic command through the simulation-tick mailbox."""
        with self._dispatch_lock:
            return self._dispatch_ops_locked(operations)

    def _dispatch_ops_locked(self, operations: list[tuple]) -> int:
        if not operations:
            return 0
        signature = self._dispatch_signature(operations)
        replayed, replayed_result = self._replay_cached_dispatch(signature)
        if replayed:
            return replayed_result
        recovered = self._consume_inflight_dispatch(signature)
        if recovered is not None:
            return recovered
        if not self.dispatcher_installed or not self.dispatcher_memory:
            raise RuntimeError("Simulation dispatcher is not installed")

        state = self.pm.read_uint(self.dispatcher_status_address)
        if state == DISPATCH_STATE_COMPLETE:
            # Orphaned completion from a prior adapter instance; its side effect is
            # already finished and no owner remains in this object.
            self.pm.write_uint(self.dispatcher_status_address, DISPATCH_STATE_IDLE)
            state = DISPATCH_STATE_IDLE
        if state == DISPATCH_STATE_QUEUED:
            # There is no matching in-memory owner, so cancel before the hook starts it.
            self.pm.write_uint(self.dispatcher_status_address, DISPATCH_STATE_IDLE)
            state = DISPATCH_STATE_IDLE
        if state == DISPATCH_STATE_EXECUTING:
            raise ActionDeferred(
                "A simulation-thread command from an earlier adapter instance is still executing",
                retry_after=DISPATCH_RETRY_DELAY,
            )
        if state != DISPATCH_STATE_IDLE:
            raise RuntimeError(f"Unknown simulation dispatcher state: {state}")

        code = self._encode_dispatch_program(operations)
        self.pm.write_bytes(self.dispatcher_command_address, code, len(code))
        self._flush_dispatch_code(self.dispatcher_command_address, len(code))
        self.pm.write_uint(self.dispatcher_result_address, 0)
        heartbeat = self.pm.read_uint(self.dispatcher_heartbeat_address)
        call_count = sum(
            1 for operation in operations
            if operation and str(operation[0]).startswith("call")
        )
        pending = _InFlightDispatch(
            owner=self._action_context,
            ordinal=self._action_dispatch_cursor,
            signature=signature,
            status_address=self.dispatcher_status_address,
            result_address=self.dispatcher_result_address,
            started_at=time.monotonic(),
            call_count=call_count,
            last_notice=0.0,
            heartbeat_at_queue=heartbeat,
        )
        self._dispatch_inflight = pending
        try:
            # Publish state last. The hook cannot observe a partially-written command.
            self.pm.write_uint(self.dispatcher_status_address, DISPATCH_STATE_QUEUED)
        except Exception:
            self._dispatch_inflight = None
            raise

        deadline = time.monotonic() + DISPATCH_SYNC_WAIT
        while time.monotonic() < deadline:
            if self.pm.read_uint(self.dispatcher_status_address) == DISPATCH_STATE_COMPLETE:
                recovered = self._consume_inflight_dispatch(signature)
                if recovered is not None:
                    return recovered
            time.sleep(0.001)
        self._defer_inflight_dispatch(pending)

    def _source_damage_fallback(self, attacker: Unit, target: Unit, damage: int, before: int) -> int:
        """Execute DAMAGE.C's branch operations when its wrapper call is suppressed."""
        flags = self.pm.read_ushort(target.address + 0x1E)
        guard = self.pm.read_ushort(target.address + 0x46)
        if flags & 0x000F:
            raise RuntimeError(f"Damage target is dead/dying/hidden (sFlags=0x{flags:04X})")
        if guard:
            return before
        if damage >= before:
            self._call_cdecl(self.damage_callees["score_kill"], [attacker.owner, target.address])
            self._call_cdecl(self.damage_callees["unit_kill"], [target.address])
            self._call_cdecl(self.damage_callees["target_valid"], [attacker.address])
            return self.pm.read_ushort(target.address + 0x22)
        after = before - damage
        self.pm.write_ushort(target.address + 0x22, after)
        self._call_cdecl(self.damage_callees["under_attack"], [target.address])
        return self.pm.read_ushort(target.address + 0x22)

    @staticmethod
    def _placement_candidates(x: int, y: int, radius: int = 10):
        yield x, y
        for distance in range(1, radius + 1):
            for dx in range(-distance, distance + 1):
                yield x + dx, y - distance
                yield x + dx, y + distance
            for dy in range(-distance + 1, distance):
                yield x - distance, y + dy
                yield x + distance, y + dy

    @staticmethod
    def _source_even_aligned_type(unit_type: int) -> bool:
        return int(unit_type) in EVEN_ALIGNED_MOBILE_TYPES

    @staticmethod
    def _normalize_even_tile(value: int) -> int:
        # Source UF_EVEN_ALIGN traversal uses two-matrix steps. Align downward
        # just like traverse_init's target normalization (`coord &= 0xFFFE`).
        return int(value) & ~1

    def _create_unit(self, owner: int, unit_type: int, x: int, y: int) -> Unit | None:
        source_even = self._source_even_aligned_type(unit_type)
        tried: set[tuple[int, int]] = set()
        for px, py in self._placement_candidates(x, y):
            if source_even:
                px = self._normalize_even_tile(px)
                py = self._normalize_even_tile(py)
            candidate = (int(px), int(py))
            if candidate in tried:
                continue
            tried.add(candidate)
            if not (0 <= px < self.map_width and 0 <= py < self.map_height):
                continue
            address = self._call_cdecl(self.unit_create_address, [px << 5, py << 5, unit_type, owner])
            if not address:
                continue
            allocation_end = self.unit_pool + self.max_units * UNIT_SIZE
            if not (self.unit_pool <= address < allocation_end) or (address - self.unit_pool) % UNIT_SIZE:
                raise RuntimeError(f"unit_create returned invalid record pointer 0x{address:08X}")
            data = self.pm.read_bytes(address, UNIT_SIZE)
            if not self._record_is_allocated(data):
                raise RuntimeError(f"unit_create returned inactive record 0x{address:08X}")
            unit = self._decode_unit(address, data)
            if unit.owner != owner or unit.unit_type != unit_type:
                raise RuntimeError(
                    f"unit_create record mismatch at 0x{address:08X}: owner {unit.owner}, type {unit.unit_type}"
                )

            # Fail-safe against any future/unknown unit type whose live class
            # table says UF_EVEN_ALIGN even if it is absent from the source ID
            # set above. unit_create leaves such a unit safely guarding, so we
            # can atomically unplace/re-place it before publishing an order.
            live_flags = self.pm.read_ushort(unit.address + 0x1C)
            if live_flags & UF_EVEN_ALIGN and ((unit.x | unit.y) & 1):
                destination = self._find_move_place(unit, unit.x, unit.y)
                if destination is None:
                    raise RuntimeError(
                        f"Created UF_EVEN_ALIGN {UNIT_NAMES[unit.unit_type]} on unsafe odd tile "
                        f"({unit.x},{unit.y}) and found no even recovery tile"
                    )
                before = (unit.x, unit.y)
                unit = self._move_mobile_unit(unit, *destination)
                self.log(
                    f"EVEN ALIGNMENT REPAIRED: P{owner + 1} {UNIT_NAMES[unit_type]} "
                    f"{before}->{destination} before any path order"
                )
            if (self.pm.read_ushort(unit.address + 0x1C) & UF_EVEN_ALIGN) and ((unit.x | unit.y) & 1):
                raise RuntimeError(
                    f"UF_EVEN_ALIGN verification failed for {UNIT_NAMES[unit.unit_type]} "
                    f"at ({unit.x},{unit.y})"
                )
            return unit
        return None

    def _complete_building(self, unit: Unit) -> Unit:
        """Accelerate a fresh foundation through Warcraft's grow_structure path."""
        if unit.unit_type not in CREATE_BUILDING_TYPES:
            raise RuntimeError(f"Instant completion is not enabled for {UNIT_NAMES[unit.unit_type]}")
        if unit.sflags & 0x0080 or not (unit.sflags & 0x0100):
            raise RuntimeError(
                f"Instant completion requires a fresh foundation (sFlags=0x{unit.sflags:04X})"
            )
        steps = self._call_cdecl(self.building_completion_path["steps_cost"], [unit.address]) & 0xFFFF
        if not 1 <= steps <= 255:
            raise RuntimeError(f"Invalid Warcraft construction step cost for {UNIT_NAMES[unit.unit_type]}: {steps}")
        progress_address = self.base + BUILDINGS_IN_PROGRESS_RVA + unit.owner * 2
        progress_before = self.pm.read_ushort(progress_address)
        if progress_before < 1:
            raise RuntimeError(
                f"Warcraft has no active building count for P{unit.owner + 1} {UNIT_NAMES[unit.unit_type]}"
            )
        cheat_address = self.base + CHEAT_BITS_RVA
        cheat_before = self.pm.read_uint(cheat_address)
        # Reset only this new foundation's private construction counter, enable
        # Warcraft's own fast-build branch atomically, and run every native growth
        # step through completion. The global cheat word is restored before the
        # interrupted game instruction resumes.
        self._dispatch_ops([
            ("write_word", unit.address + 0x84, 0),
            ("write_dword", cheat_address, cheat_before | 0x00000002),
            (
                "call_until_word_flag",
                self.building_completion_path["grow_structure"],
                [unit.address],
                steps + 3,
                unit.address + 0x1E,
                0x0080,
            ),
            ("write_dword", cheat_address, cheat_before),
        ])
        data = self.pm.read_bytes(unit.address, UNIT_SIZE)
        if not self._record_is_allocated(data):
            raise RuntimeError("grow_structure returned an inactive building record")
        completed = self._decode_unit(unit.address, data)
        hp_max = self.pm.read_ushort(self.base + UNIT_HP_TABLE_RVA + unit.unit_type * 2)
        progress_after = self.pm.read_ushort(progress_address)
        failures: list[str] = []
        if not (completed.sflags & 0x0080) or completed.sflags & 0x0100:
            failures.append(f"sFlags 0x{completed.sflags:04X}")
        if completed.health != hp_max:
            failures.append(f"HP {completed.health}/{hp_max}")
        if progress_after != progress_before - 1:
            failures.append(f"gwBldgInProgress {progress_before}->{progress_after}")
        if self.pm.read_uint(cheat_address) != cheat_before:
            failures.append("cheat word was not restored")
        if failures:
            raise RuntimeError("Warcraft instant building completion failed: " + ", ".join(failures))
        return completed

    def _tile_destination(self, args: dict[str, Any], action_name: str) -> tuple[int, int]:
        location_name = args.get("destination", args.get("to_location", "Anywhere"))
        if location_name != "Anywhere":
            if not self.scenario:
                raise RuntimeError(f"{action_name} destination requires an active scenario")
            location = next((item for item in self.scenario.locations if item.name == location_name), None)
            if not location:
                raise ValueError(f"Unknown destination location: {location_name}")
            return ((location.left + location.right) // 2, (location.top + location.bottom) // 2)
        if "x" not in args or "y" not in args:
            raise ValueError(f"{action_name} to Anywhere requires destination tile coordinates x and y")
        return int(args["x"]), int(args["y"])

    def _find_move_place(self, unit: Unit, x: int, y: int) -> tuple[int, int] | None:
        unit_class = self.pm.read_uchar(unit.address + 0x2A)
        unit_flags = self.pm.read_ushort(unit.address + 0x1C)
        even_aligned = bool(unit_flags & UF_EVEN_ALIGN)
        tried: set[tuple[int, int]] = set()
        for px, py in self._placement_candidates(x, y):
            if even_aligned:
                px = self._normalize_even_tile(px)
                py = self._normalize_even_tile(py)
            candidate = (int(px), int(py))
            if candidate in tried:
                continue
            tried.add(candidate)
            if not (0 <= px < self.map_width and 0 <= py < self.map_height):
                continue
            placeable = self._call_cdecl(
                self.move_callees["placeable"], [unit_class, px, py, unit.unit_type]
            )
            if placeable:
                return px, py
        return None

    def _move_mobile_unit(self, unit: Unit, x: int, y: int) -> Unit:
        """Teleport a mobile unit through the engine's atomic matrix update path."""
        if int(unit.unit_type) >= FIRST_BUILDING_TYPE:
            raise RuntimeError(
                f"Refusing mobile-unit matrix move for building type {int(unit.unit_type)} "
                f"at 0x{int(unit.address):08X}"
            )
        unit_flags = self.pm.read_ushort(unit.address + 0x1C)
        if unit_flags & UF_EVEN_ALIGN:
            x = self._normalize_even_tile(x)
            y = self._normalize_even_tile(y)
        if not (0 <= x < self.map_width and 0 <= y < self.map_height):
            raise RuntimeError(f"Move destination ({x},{y}) is outside the live map")
        packed_tile = (x & 0xFFFF) | ((y & 0xFFFF) << 16)
        operations = [
            ("call", self.move_callees["cancel_tree_harvest"], [unit.address]),
            ("call", self.move_callees["unplace_man"], [unit.address]),
            ("write_word", unit.address + 0x00, x << 5),
            ("write_word", unit.address + 0x02, y << 5),
            ("write_dword", unit.address + 0x18, packed_tile),
            ("or_byte", unit.address + 0x06, 0x20),
            ("call", self.move_callees["place_man"], [unit.address]),
            ("call", self.move_callees["unmask_square"], [unit.address]),
            ("call", self.move_callees["set_curr_action"], [unit.address, 2]),
        ]
        self._dispatch_ops(operations)
        data = self.pm.read_bytes(unit.address, UNIT_SIZE)
        if not self._record_is_allocated(data):
            raise RuntimeError(f"Moved unit slot {(unit.address-self.unit_pool)//UNIT_SIZE} became inactive")
        moved = self._decode_unit(unit.address, data)
        pixel_x = int.from_bytes(data[0:2], "little", signed=True)
        pixel_y = int.from_bytes(data[2:4], "little", signed=True)
        if (moved.x, moved.y) != (x, y) or (pixel_x, pixel_y) != (x << 5, y << 5):
            raise RuntimeError(
                f"Move verification failed for slot {(unit.address-self.unit_pool)//UNIT_SIZE}: "
                f"tile ({moved.x},{moved.y}), pixel ({pixel_x},{pixel_y})"
            )
        if moved.action != 2 or moved.next_action != 60:
            raise RuntimeError(
                f"Move order reset failed for slot {(unit.address-self.unit_pool)//UNIT_SIZE}: "
                f"action {moved.action}/{moved.next_action}"
            )
        return moved

    def _maintain_attack_routes(self, units: list[Unit]) -> None:
        """Maintain destination-only attack-move for Empty wave owners.

        Empty player slots have no strategy controller, which is exactly what
        prevents the unwanted return-to-spawn behavior. They can still follow a
        target-less ``do_unit_attack`` route, but they need help acquiring a live
        enemy record. This maintenance runs each trigger-engine cycle, chooses only
        enemies allowed by the current diplomacy row, and uses Warcraft's native
        targeted Attack callback. After combat clears, the original destination is
        reissued. No owner type, alliance, shared-vision, or home coordinate changes.
        """
        if not self._attack_routes:
            return
        current = {self._unit_key(unit): unit for unit in units}
        world = [
            unit for unit in units
            if 0 <= int(unit.owner) < 8 and not (unit.sflags & 0x0008)
        ]
        relation_rows: dict[int, list[int]] = {}
        target_orders: list[tuple[Unit, Unit, tuple[int, int]]] = []
        resume_orders: list[tuple[Unit, tuple[int, int]]] = []
        encounter_radius_sq = 8 * 8
        spell_guards = getattr(self, "_auto_spell_route_guards", set())
        parking_state = getattr(self, "_auto_spell_parking", set())

        for key, destination in list(self._attack_routes.items()):
            unit = current.get(key)
            if unit is None:
                self._attack_routes.pop(key, None)
                spell_guards.discard(key)
                continue
            if not (0 <= int(unit.owner) < 8):
                self._attack_routes.pop(key, None)
                spell_guards.discard(key)
                continue

            # A caster selected for one spell is protected only while its
            # one-cast parking stage is active. All other auto-casters remain
            # normal attack-route units and continue fighting.
            if key in parking_state:
                spell_guards.add(key)
                continue

            # Native unit-target spells retain a raw target pointer at Unit+0x88.
            # Never replace a caster's order while that spell is pending/running.
            # The explicit guard also covers the same cycle in which auto-casting
            # published the order but an older Python snapshot still showed Attack.
            if self._spell_action_busy(unit):
                spell_guards.add(key)
                continue
            if key in spell_guards:
                spell_guards.discard(key)
                # Give Warcraft one clean simulation cycle after the spell leaves
                # its action state before resuming the saved attack destination.
                self.log(
                    f"AUTO SPELL ROUTE RELEASE: P{unit.owner + 1} "
                    f"{UNIT_NAMES[unit.unit_type]} slot "
                    f"{(unit.address-self.unit_pool)//UNIT_SIZE} finished its cast; "
                    f"saved destination {destination} resumes next cycle"
                )
                continue

            # Real Human/Computer owners already have Warcraft's own acquisition.
            # The route keeper exists only for units belonging to Empty slots.
            if self._owner_type(int(unit.owner)) != C_NONE:
                continue

            row = relation_rows.get(int(unit.owner))
            if row is None:
                row = self._read_diplomacy_state(int(unit.owner))[0]
                relation_rows[int(unit.owner)] = row

            live_target = next(
                (candidate for candidate in world if candidate.address == int(unit.target_unit)),
                None,
            )
            if live_target is not None and self._relation_is_enemy(
                int(unit.owner), int(live_target.owner), row[int(live_target.owner)]
            ) and (
                unit.action in {8, 9, 10, 11, 12}
                or unit.next_action in {8, 9, 10, 11, 12}
            ):
                continue

            candidates: list[tuple[int, int, Unit]] = []
            for candidate in world:
                if candidate.address == unit.address:
                    continue
                if not self._relation_is_enemy(
                    int(unit.owner), int(candidate.owner), row[int(candidate.owner)]
                ):
                    continue
                dx = int(candidate.x) - int(unit.x)
                dy = int(candidate.y) - int(unit.y)
                distance_sq = dx * dx + dy * dy
                if distance_sq <= encounter_radius_sq:
                    candidates.append((distance_sq, candidate.address, candidate))
            if candidates:
                _distance, _address, target = min(candidates, key=lambda item: (item[0], item[1]))
                target_orders.append((unit, target, destination))
                continue

            dest_x, dest_y = destination
            at_destination = (
                abs(int(unit.x) - int(dest_x)) <= 1
                and abs(int(unit.y) - int(dest_y)) <= 1
            )
            route_active = (
                int(unit.target_unit) == 0
                and (int(unit.target_x), int(unit.target_y)) == (int(dest_x), int(dest_y))
                and (
                    unit.action in {10, 11}
                    or unit.next_action in {10, 11}
                    or (unit.action == 2 and unit.next_action == 60)
                )
            )
            if at_destination or route_active:
                continue
            resume_orders.append((unit, destination))

        if target_orders:
            self._call_cdecl_batched([
                (
                    self.order_callees["set_target"],
                    [
                        unit.address,
                        int(target.x),
                        int(target.y),
                        target.address,
                        self.order_callees["do_attack"],
                    ],
                )
                for unit, target, _destination in target_orders
            ])
            for unit, target, destination in target_orders:
                self.log(
                    f"ATTACK ROUTE ENCOUNTER: P{unit.owner + 1} {UNIT_NAMES[unit.unit_type]} "
                    f"slot {(unit.address-self.unit_pool)//UNIT_SIZE} acquired enemy "
                    f"P{target.owner + 1} {UNIT_NAMES[target.unit_type]} at "
                    f"({target.x},{target.y}); destination remains {destination}"
                )

        if resume_orders:
            self._call_cdecl_batched([
                (
                    self.order_callees["set_target"],
                    [
                        unit.address,
                        int(destination[0]),
                        int(destination[1]),
                        0,
                        self.order_callees["do_attack"],
                    ],
                )
                for unit, destination in resume_orders
            ])
            for unit, destination in resume_orders:
                self.log(
                    f"ATTACK ROUTE RESUMED: P{unit.owner + 1} {UNIT_NAMES[unit.unit_type]} "
                    f"slot {(unit.address-self.unit_pool)//UNIT_SIZE} toward {destination}"
                )

    # ------------------------------------------------------------------
    # TD Raise Dead -> tower builder extension
    # ------------------------------------------------------------------
    def _resolve_td_ranged_order_entry(self) -> int:
        """Resolve gbRangedOrderTbl[SPELL_RAISEDEAD] from the source byte tail."""
        image = self.pm.read_bytes(self.base, self.image_size)
        hits: list[int] = []
        start = 0
        while True:
            offset = image.find(TD_RANGED_SPELL_SIGNATURE, start)
            if offset < 0:
                break
            hits.append(offset)
            start = offset + 1
        if len(hits) != 1:
            raise RuntimeError(
                f"TD tower builder could not uniquely resolve gbRangedOrderTbl: {len(hits)} candidate(s)"
            )
        address = self.base + hits[0] + (SPELL_RAISEDEAD - SPELL_VISION)
        observed = self.pm.read_uchar(address)
        if observed != RAISEDEAD_RADIUS:
            raise RuntimeError(
                f"Raise Dead range-table validation failed: expected {RAISEDEAD_RADIUS}, read {observed}"
            )
        return address

    def _build_td_raise_tower_stub(self, trampoline_address: int) -> bytes:
        """Intercept P6 Death Knight Raise Dead at do_unit_spell target submission.

        v1.28.3 had an x86 encoding bug: 0F B7 46 84/86 uses a signed
        8-bit displacement, so it read Unit-0x7C/-0x7A instead of Unit+0x84/+0x86.
        That is why every live click logged the bogus (0,160). v1.28.4 encodes the
        offsets with disp32 and also hooks do_unit_spell, immediately after
        unit_set_target has written the freshly clicked tile, while gwActionType
        still identifies Raise Dead. Matching TD casts publish that exact tile and are
        converted straight back to Guard; all other spells/casters trampoline into
        Blizzard's untouched do_unit_spell implementation.
        """
        code = bytearray()
        labels: dict[str, int] = {}
        fixups: list[tuple[int, str]] = []

        def emit(data: bytes):
            code.extend(data)

        def label(name: str):
            labels[name] = len(code)

        def jcc(second_opcode: int, target: str):
            emit(bytes((0x0F, second_opcode)))
            fixups.append((len(code), target))
            emit(b"\x00\x00\x00\x00")

        pending = self.dispatcher_memory + TD_BUILDER_PENDING_OFFSET
        caster_out = self.dispatcher_memory + TD_BUILDER_CASTER_OFFSET
        x_out = self.dispatcher_memory + TD_BUILDER_X_OFFSET
        y_out = self.dispatcher_memory + TD_BUILDER_Y_OFFSET
        next_action = int(self.spell_path["unit_set_next_action"])
        action_type = int(self.spell_path["action_type_global"])

        # do_unit_spell(pUnit) is entered directly from unit_set_target after the
        # clicked ground tile has been stored at Unit+0x84/+0x86.
        emit(b"\x8B\x44\x24\x04")  # mov eax,[esp+4] ; pUnit
        emit(b"\x80\x78\x2C" + bytes((self._td_builder_owner & 0xFF,)))
        jcc(0x85, "native")
        emit(b"\x80\x78\x27" + bytes((self._td_builder_caster_type & 0xFF,)))
        jcc(0x85, "native")
        emit(b"\x0F\xB7\x0D" + __import__('struct').pack("<I", action_type))
        emit(b"\x83\xF9" + bytes((SPELL_RAISEDEAD & 0xFF,)))
        jcc(0x85, "native")

        # Matching TD cast: use our own cdecl frame.
        emit(b"\x55\x8B\xEC\x56")
        emit(b"\x8B\x75\x08")

        # If mana is insufficient, or the prior click has not yet been consumed,
        # cancel this spell cleanly rather than falling into native corpse logic.
        emit(b"\x80\x7E\x26" + bytes((self._td_builder_mana_cost & 0xFF,)))
        jcc(0x82, "td_done")
        emit(b"\x83\x3D" + __import__('struct').pack("<I", pending) + b"\x00")
        jcc(0x85, "td_done")

        # Publish the exact target tile just written by unit_set_target.
        emit(b"\x89\x35" + __import__('struct').pack("<I", caster_out))
        emit(b"\x0F\xB7\x86\x84\x00\x00\x00")  # movzx eax,word ptr [esi+0x84]
        emit(b"\xA3" + __import__('struct').pack("<I", x_out))
        emit(b"\x0F\xB7\x86\x86\x00\x00\x00")  # movzx eax,word ptr [esi+0x86]
        emit(b"\xA3" + __import__('struct').pack("<I", y_out))
        emit(b"\xC7\x05" + __import__('struct').pack("<I", pending) + b"\x01\x00\x00\x00")

        # Do not queue SPELL_RAISEDEAD. The next simulation cycle creates the
        # tower and charges mana only after native building-placement validation.
        emit(b"\x6A\x02\x56\xB8" + __import__('struct').pack("<I", next_action) + b"\xFF\xD0\x83\xC4\x08")
        emit(b"\x66\xC7\x46\x44\x00\x00")

        label("td_done")
        emit(b"\x5E\x8B\xE5\x5D\xC3")

        label("native")
        emit(b"\xB8" + __import__('struct').pack("<I", int(trampoline_address)) + b"\xFF\xE0")

        for displacement_at, target in fixups:
            if target not in labels:
                raise RuntimeError(f"Internal TD builder stub label missing: {target}")
            displacement = labels[target] - (displacement_at + 4)
            __import__('struct').pack_into("<i", code, displacement_at, displacement)
        if len(code) > (TD_BUILDER_TRAMPOLINE_OFFSET - TD_BUILDER_CODE_OFFSET):
            raise RuntimeError(f"TD builder stub is too large: {len(code)} bytes")
        return bytes(code)

    @staticmethod
    def _td_rel32_jump(source: int, target: int, total_length: int = 5) -> bytes:
        if total_length < 5:
            raise ValueError("x86 rel32 jump requires at least five bytes")
        displacement = int(target) - (int(source) + 5)
        if not -0x80000000 <= displacement <= 0x7FFFFFFF:
            raise RuntimeError("TD builder detour is outside rel32 range")
        return b"\xE9" + __import__('struct').pack("<i", displacement) + (b"\x90" * (total_length - 5))

    def _enable_td_tower_builder(self, args: dict[str, Any], executing_player: int) -> None:
        if not self.dispatcher_installed or not self.dispatcher_memory:
            raise RuntimeError("TD tower builder requires the simulation dispatcher")
        if self._td_builder_enabled:
            self._disable_td_tower_builder(log_result=False)

        owner = int(args.get("player", executing_player))
        caster_type = int(args.get("caster_unit", RAISEDEAD_CASTER_TYPE))
        tower_type = int(args.get("tower_unit", 97))
        mana_cost = int(args.get("mana_cost", 50))
        prefix = str(args.get("location_prefix", "Tower Pad "))
        if not 0 <= owner <= 7:
            raise ValueError("TD tower builder owner must be P1-P8")
        if caster_type not in DEATH_KNIGHT_CASTER_TYPES:
            raise ValueError("TD tower builder caster must be a Death Knight-class unit")
        if tower_type not in CREATE_BUILDING_TYPES:
            raise ValueError("TD tower builder tower must be a validated standard land building")
        if not 0 <= mana_cost <= 255:
            raise ValueError("TD tower builder mana cost must be 0-255")
        if not self.scenario:
            raise RuntimeError("TD tower builder requires an active scenario")
        pads = [loc for loc in self.scenario.locations if prefix and loc.name.startswith(prefix)]
        if prefix and not pads:
            raise ValueError(f"TD tower builder found no locations beginning with {prefix!r}")

        self._td_builder_owner = owner
        self._td_builder_caster_type = caster_type
        self._td_builder_tower_type = tower_type
        self._td_builder_mana_cost = mana_cost
        self._td_builder_location_prefix = prefix

        # Hook do_unit_spell, not action_raisedead. At this point Warcraft's
        # unit_set_target has just stored the user's clicked tile in +0x84/+0x86,
        # and gwActionType still identifies Raise Dead. This is the earliest stable
        # native-verified interception point for a manual UI cast.
        action_entry = int(self.spell_path["do_unit_spell"])
        original_prefix = self.pm.read_bytes(action_entry, TD_BUILDER_ACTION_PATCH_LENGTH)
        expected_prefix = (
            b"\x55\x8B\xEC\xF6\x05"
            + __import__('struct').pack("<I", self.base + CHEAT_BITS_RVA)
            + b"\x08"
        )
        if original_prefix != expected_prefix:
            raise RuntimeError(
                "do_unit_spell entry has already been modified; restart Warcraft before enabling TD tower building"
            )

        code_address = self.dispatcher_memory + TD_BUILDER_CODE_OFFSET
        trampoline_address = self.dispatcher_memory + TD_BUILDER_TRAMPOLINE_OFFSET

        # Trampoline: exact whole-instruction native prefix, then jump back.
        trampoline = bytearray(original_prefix)
        trampoline += self._td_rel32_jump(
            trampoline_address + len(original_prefix),
            action_entry + len(original_prefix),
            5,
        )
        stub = self._build_td_raise_tower_stub(trampoline_address)
        action_patch = self._td_rel32_jump(action_entry, code_address, TD_BUILDER_ACTION_PATCH_LENGTH)

        self.pm.write_uint(self.dispatcher_memory + TD_BUILDER_DATA_OFFSET, TD_BUILDER_MAGIC)
        self.pm.write_uint(self.dispatcher_memory + TD_BUILDER_PENDING_OFFSET, 0)
        self.pm.write_uint(self.dispatcher_memory + TD_BUILDER_CASTER_OFFSET, 0)
        self.pm.write_uint(self.dispatcher_memory + TD_BUILDER_X_OFFSET, 0)
        self.pm.write_uint(self.dispatcher_memory + TD_BUILDER_Y_OFFSET, 0)
        self.pm.write_bytes(code_address, stub, len(stub))
        self.pm.write_bytes(trampoline_address, bytes(trampoline), len(trampoline))
        self._flush_dispatch_code(code_address, len(stub))
        self._flush_dispatch_code(trampoline_address, len(trampoline))

        dispatch_entry = 0
        dispatch_target = 0
        self._td_builder_dispatch_entry = dispatch_entry
        self._td_builder_dispatch_original = dispatch_target
        self._td_builder_range_address = 0
        self._td_builder_range_original = 0
        self._td_builder_code_address = code_address
        self._td_builder_action_entry = action_entry
        self._td_builder_action_original = bytes(original_prefix)
        self._td_builder_action_patch = bytes(action_patch)
        self._td_builder_trampoline_address = trampoline_address
        try:
            self._write_executable_bytes(action_entry, action_patch)
        except Exception:
            try:
                self._write_executable_bytes(action_entry, original_prefix)
            except Exception:
                pass
            raise
        self._td_builder_enabled = True
        self.log(
            f"TD TOWER BUILDER ENABLED v1.28.11: P{owner + 1} Death Knight Raise Dead target-stage detour -> "
            f"{UNIT_NAMES[tower_type]} native foundation, {mana_cost} mana, no corpse required; exact clicked tile only, incremental native construction"
        )

    def _disable_td_tower_builder(self, *, log_result: bool = True) -> None:
        if not self.pm:
            self._td_builder_enabled = False
            return
        if self._td_builder_action_entry and self._td_builder_action_original:
            current = self.pm.read_bytes(self._td_builder_action_entry, len(self._td_builder_action_patch))
            if current == self._td_builder_action_patch:
                self._write_executable_bytes(self._td_builder_action_entry, self._td_builder_action_original)
        if self._td_builder_range_address:
            current_range = self.pm.read_uchar(self._td_builder_range_address)
            if current_range == 0xFF:
                self._write_executable_bytes(
                    self._td_builder_range_address,
                    bytes((self._td_builder_range_original & 0xFF,)),
                )
        if self.dispatcher_memory:
            try:
                self.pm.write_uint(self.dispatcher_memory + TD_BUILDER_PENDING_OFFSET, 0)
            except Exception:
                pass
        was_enabled = self._td_builder_enabled
        self._td_builder_enabled = False
        self._td_builder_dispatch_entry = 0
        self._td_builder_dispatch_original = 0
        self._td_builder_range_address = 0
        self._td_builder_code_address = 0
        self._td_builder_action_entry = 0
        self._td_builder_action_original = b""
        self._td_builder_action_patch = b""
        self._td_builder_trampoline_address = 0
        if was_enabled and log_result:
            self.log("TD TOWER BUILDER DISABLED: native Raise Dead body/range restored")

    def _td_builder_pad_at(self, x: int, y: int):
        if not self.scenario or not self._td_builder_location_prefix:
            return None
        for location in self.scenario.locations:
            if not location.name.startswith(self._td_builder_location_prefix):
                continue
            if location.left <= x <= location.right and location.top <= y <= location.bottom:
                return location
        return None

    def _td_builder_resource_snapshot(self, owner: int) -> dict[str, int]:
        """Capture the builder owner's resources for cancellation-refund rollback.

        TD towers are paid for with mana only. Warcraft's native Cancel Construction
        command refunds 75% of the normal building gold/lumber cost, even though this
        custom foundation never charged those resources. The normal UI cancel button
        is suppressed in 1.28.11, but this snapshot is retained as defense-in-depth
        for direct packets, stale UI state, or any other path that kills an incomplete
        TD tower through unit_order_kill().
        """
        return {
            name.lower(): int(self.pm.read_uint(self.base + rva + int(owner) * 4))
            for name, rva in RESOURCE_RVAS.items()
        }

    def _td_rollback_unearned_cancel_refund(self, info: dict[str, int | float], *, reason: str) -> None:
        """Remove only resource increases above the foundation's creation snapshot."""
        owner = int(info.get("owner", self._td_builder_owner))
        restored: list[str] = []
        # unit_order_kill refunds only stone/gold and lumber for construction.
        # Oil is intentionally left alone.
        for name in ("Gold", "Lumber"):
            rva = RESOURCE_RVAS[name]
            key = f"resource_{name.lower()}"
            if key not in info:
                continue
            baseline = int(info[key])
            address = self.base + rva + owner * 4
            current = int(self.pm.read_uint(address))
            if current <= baseline:
                continue
            self.pm.write_uint(address, baseline)
            restored.append(f"{name} {current}->{baseline}")
        if restored:
            self.log(
                f"TD TOWER CANCEL REFUND BLOCKED v1.28.11: P{owner + 1} "
                f"{', '.join(restored)}; {reason}"
            )

    def _td_create_tower_foundation(self, owner: int, tower_type: int, x: int, y: int, pad=None) -> Unit | None:
        """Create a tower as an exact native building foundation.

        1.28.11 keeps Warcraft's real construction lifecycle, but immediately replaces
        CARD_CANCEL_BUILD with the tower's normal card. These TD towers are mana-only,
        so allowing the stock Cancel Construction command would mint 75% of the normal
        gold/lumber cost out of nothing.
        """
        x, y = int(x), int(y)
        if not (0 <= x < self.map_width and 0 <= y < self.map_height):
            return None
        if pad is not None and not (pad.left <= x <= pad.right and pad.top <= y <= pad.bottom):
            return None

        resource_snapshot = self._td_builder_resource_snapshot(owner)
        address = self._call_cdecl(
            self.unit_create_address, [x << 5, y << 5, int(tower_type), int(owner)]
        )
        if not address:
            return None
        allocation_end = self.unit_pool + self.max_units * UNIT_SIZE
        if not (self.unit_pool <= address < allocation_end) or (address - self.unit_pool) % UNIT_SIZE:
            raise RuntimeError(f"TD tower unit_create returned invalid record pointer 0x{address:08X}")
        data = self.pm.read_bytes(address, UNIT_SIZE)
        if not self._record_is_allocated(data):
            raise RuntimeError("TD tower unit_create returned an inactive record")
        unit = self._decode_unit(address, data)
        if unit.owner != owner or unit.unit_type != tower_type:
            raise RuntimeError("TD tower unit_create returned the wrong owner/type")
        if (int(unit.x), int(unit.y)) != (x, y):
            # Building creation is supposed to be exact. Refuse to publish/charge a
            # relocated result; clean the unexpected record through Warcraft's own
            # unit_free routine rather than pretending the click was accepted.
            self._call_cdecl(self.unit_free_address, [address])
            self.log(
                f"TD TOWER BUILDER: native foundation relocated ({x},{y})->({unit.x},{unit.y}); rejected"
            )
            return None
        if unit.sflags & 0x0080 or not (unit.sflags & 0x0100):
            raise RuntimeError(
                f"TD tower creation did not return a fresh foundation (sFlags=0x{unit.sflags:04X})"
            )
        steps = self._call_cdecl(self.building_completion_path["steps_cost"], [unit.address]) & 0xFFFF
        if not 1 <= steps <= 255:
            raise RuntimeError(f"Invalid Warcraft construction step cost for {UNIT_NAMES[unit.unit_type]}: {steps}")

        # unitCard is byte +0x25. unit_create normally assigns CARD_CANCEL_BUILD
        # while an ordinary worker-funded building is incomplete. TD foundations are
        # not worker-funded and never paid native gold/lumber, so expose the normal
        # tower card immediately and remove the stock refund-producing Cancel button.
        #
        # +0x84 is this fresh foundation's private construction amount field in the
        # TBldg union. Reset it exactly as the validated completion path does.
        self._dispatch_ops([
            ("write_byte", unit.address + 0x25, int(tower_type)),
            # TBldg begins at Unit+0x7C. Its first DWORD is bldgFire and must be
            # NULL for an incomplete foundation. Mobile TTarget shares this union,
            # so clearing it here also gives us a clean corruption sentinel.
            ("write_dword", unit.address + 0x7C, 0),
            ("write_word", unit.address + 0x84, 0),
        ])
        self._td_pending_towers[unit.address] = {
            "owner": int(owner),
            "type": int(tower_type),
            "x": x,
            "y": y,
            "steps": int(steps),
            "cycles": 0,
            "next_growth_at": time.monotonic() + 0.08,
            "resource_gold": int(resource_snapshot["gold"]),
            "resource_lumber": int(resource_snapshot["lumber"]),
            "resource_oil": int(resource_snapshot["oil"]),
        }
        return self._decode_unit(unit.address, self.pm.read_bytes(unit.address, UNIT_SIZE))

    def _td_resume_growth_dispatch(self) -> bool:
        """Consume a deferred tower-growth command with its exact original signature."""
        operations = self._td_growth_retry_ops
        if not operations:
            return True
        address = int(self._td_growth_retry_address)
        try:
            self._dispatch_ops(operations)
        except ActionDeferred:
            return False

        # The queued native grow call has now definitely executed once. Account for
        # that exact step before another tower is allowed to use the mailbox.
        info = self._td_pending_towers.get(address)
        if info is not None:
            info["cycles"] = int(info.get("cycles", 0)) + 1
            info["next_growth_at"] = time.monotonic() + 0.08
        self._td_growth_retry_ops = None
        self._td_growth_retry_address = 0
        return True

    def _maintain_td_pending_towers(self) -> bool:
        # A maintenance grow call may have been published on the previous cycle and
        # completed after the Python-side tower disappeared (for example because the
        # player cancelled it). Always consume that exact command first. v1.28.11
        # instead advanced to another tower, changed the dispatcher signature, and
        # could wedge every trigger action behind "retry did not match".
        if not self._td_resume_growth_dispatch():
            return False

        if not self._td_pending_towers:
            return True

        now = time.monotonic()
        cheat_address = self.base + CHEAT_BITS_RVA
        for address, info in list(self._td_pending_towers.items()):
            if now < float(info.get("next_growth_at", 0.0)):
                continue

            allocation_end = self.unit_pool + self.max_units * UNIT_SIZE
            if not (self.unit_pool <= address < allocation_end) or (address - self.unit_pool) % UNIT_SIZE:
                self._td_pending_towers.pop(address, None)
                continue

            data = self.pm.read_bytes(address, UNIT_SIZE)
            # sFlags is word +0x1E. Catch dying/dead/free before attempting another
            # grow_structure call. A stock Cancel Construction order enters this path
            # immediately after applying its native 75% resource refund.
            raw_sflags = struct.unpack_from("<H", data, 0x1E)[0]
            if raw_sflags & 0x0007:
                self._td_rollback_unearned_cancel_refund(
                    info,
                    reason=f"incomplete tower left construction state (sFlags 0x{raw_sflags:04X})",
                )
                self._td_pending_towers.pop(address, None)
                self.log(
                    f"TD TOWER CONSTRUCTION REMOVED v1.28.11: P{int(info['owner']) + 1} "
                    f"{UNIT_NAMES[int(info['type'])]} at ({int(info['x'])},{int(info['y'])}); "
                    "tracker detached safely"
                )
                continue

            if not self._record_is_allocated(data):
                self._td_rollback_unearned_cancel_refund(
                    info, reason="incomplete tower record was freed"
                )
                self._td_pending_towers.pop(address, None)
                continue

            unit = self._decode_unit(address, data)
            if unit.owner != int(info["owner"]) or unit.unit_type != int(info["type"]):
                # Slot reuse after a very fast cancellation/free must never inherit
                # construction maintenance intended for the previous object.
                self._td_rollback_unearned_cancel_refund(
                    info, reason="incomplete tower slot was reused"
                )
                self._td_pending_towers.pop(address, None)
                continue

            if (int(unit.x), int(unit.y)) != (int(info["x"]), int(info["y"])):
                self.log(
                    f"TD TOWER STATIC WARNING: {UNIT_NAMES[unit.unit_type]} moved from "
                    f"({info['x']},{info['y']}) to ({unit.x},{unit.y}); tracking stopped"
                )
                self._td_pending_towers.pop(address, None)
                continue

            # Keep the refund-producing cancel card suppressed throughout construction.
            # This also repairs a stale selection/UI cycle if Warcraft temporarily
            # regenerated CARD_CANCEL_BUILD after the initial foundation write.
            if self.pm.read_uchar(unit.address + 0x25) != int(info["type"]):
                self.pm.write_uchar(unit.address + 0x25, int(info["type"]))

            # For an unfinished TBldg, +0x7C is bldgFire and source initializes it
            # to NULL. If any mobile TTarget/path routine ever touched this recycled
            # slot, bTargetCounter/target fields alias this DWORD. Repair before the
            # next native building update and record the fact loudly.
            if not (unit.sflags & 0x0080):
                bldg_fire = int(self.pm.read_uint(unit.address + 0x7C))
                if bldg_fire != 0:
                    self.pm.write_uint(unit.address + 0x7C, 0)
                    self.log(
                        f"TD TOWER TARGET-UNION REPAIR v1.28.11: P{unit.owner + 1} "
                        f"{UNIT_NAMES[unit.unit_type]} at ({unit.x},{unit.y}) "
                        f"bldgFire 0x{bldg_fire:08X}->0"
                    )

            if unit.sflags & 0x0080:
                # SF_BUILD_FOUNDATION is *not* an all-construction flag. Warcraft's
                # update_frame() intentionally clears it around the halfway point
                # and switches from foundation graphics to the building group. The
                # real completion test is SF_COMPLETED.
                hp_max = self.pm.read_ushort(self.base + UNIT_HP_TABLE_RVA + unit.unit_type * 2)
                if int(unit.health) != int(hp_max):
                    self.pm.write_ushort(unit.address + 0x22, int(hp_max))
                self._td_pending_towers.pop(address, None)
                self.log(
                    f"TD TOWER COMPLETE v1.28.11: P{unit.owner + 1} {UNIT_NAMES[unit.unit_type]} "
                    f"static at ({unit.x},{unit.y}); HP {hp_max}/{hp_max}; sFlags 0x{unit.sflags:04X}"
                )
                continue

            if unit.unit_type not in CREATE_BUILDING_TYPES:
                self.log(
                    f"TD TOWER CONSTRUCTION ABORT: record at ({unit.x},{unit.y}) changed to non-building type {unit.unit_type}"
                )
                self._td_pending_towers.pop(address, None)
                continue

            cheat_before = self.pm.read_uint(cheat_address)
            operations = [
                ("write_dword", cheat_address, cheat_before | 0x00000002),
                ("call", self.building_completion_path["grow_structure"], [address]),
                ("write_dword", cheat_address, cheat_before),
            ]
            try:
                # Advance one native construction step at a time. If the mailbox
                # cannot finish within the synchronous wait, retain *these exact ops*
                # and consume them on the next prepare cycle before touching any
                # other tower.
                self._dispatch_ops(operations)
            except ActionDeferred:
                self._td_growth_retry_ops = operations
                self._td_growth_retry_address = int(address)
                return False
            finally:
                # Only repair the cheat bit if no command is currently executing.
                # When a deferred command is still queued/executing, its own final
                # dispatcher operation restores the exact captured value.
                if self._td_growth_retry_ops is None:
                    if self.pm.read_uint(cheat_address) != cheat_before:
                        self.pm.write_uint(cheat_address, cheat_before)

            info["cycles"] = int(info.get("cycles", 0)) + 1
            info["next_growth_at"] = now + 0.08
            if int(info["cycles"]) > int(info.get("steps", 255)) + 8:
                self.log(
                    f"TD TOWER CONSTRUCTION TIMEOUT: {UNIT_NAMES[unit.unit_type]} at ({unit.x},{unit.y}); "
                    f"native grow_structure did not complete"
                )
                self._td_pending_towers.pop(address, None)

        return True

    def _process_td_tower_builder_request(self) -> None:
        if not self._td_builder_enabled or not self.dispatcher_memory:
            return
        pending_address = self.dispatcher_memory + TD_BUILDER_PENDING_OFFSET
        if self.pm.read_uint(pending_address) != 1:
            return
        caster_address = self.pm.read_uint(self.dispatcher_memory + TD_BUILDER_CASTER_OFFSET)
        x = self.pm.read_uint(self.dispatcher_memory + TD_BUILDER_X_OFFSET) & 0xFFFF
        y = self.pm.read_uint(self.dispatcher_memory + TD_BUILDER_Y_OFFSET) & 0xFFFF
        # Consume first so a bad placement cannot wedge the native spell handler.
        self.pm.write_uint(pending_address, 0)

        allocation_end = self.unit_pool + self.max_units * UNIT_SIZE
        if not (self.unit_pool <= caster_address < allocation_end) or (caster_address - self.unit_pool) % UNIT_SIZE:
            self.log("TD TOWER BUILDER: ignored stale caster pointer")
            return
        data = self.pm.read_bytes(caster_address, UNIT_SIZE)
        if not self._record_is_allocated(data):
            self.log("TD TOWER BUILDER: caster no longer exists")
            return
        caster = self._decode_unit(caster_address, data)
        if caster.owner != self._td_builder_owner or caster.unit_type != self._td_builder_caster_type:
            self.log("TD TOWER BUILDER: ignored request from a non-builder caster")
            return
        mana = self.pm.read_uchar(caster.address + 0x26)
        if mana < self._td_builder_mana_cost:
            self.log(f"TD TOWER BUILDER: not enough mana ({mana}/{self._td_builder_mana_cost})")
            return
        pad = self._td_builder_pad_at(x, y)
        if self._td_builder_location_prefix and pad is None:
            self.log(f"TD TOWER BUILDER: ({x},{y}) is outside the configured build zone; no mana charged")
            return
        tower = self._td_create_tower_foundation(
            self._td_builder_owner, self._td_builder_tower_type, x, y, pad
        )
        if tower is None:
            scope = pad.name if pad is not None else f"at exact tile ({x},{y})"
            self.log(f"TD TOWER BUILDER: no legal native building footprint {scope}; no mana charged")
            return
        new_mana = max(0, mana - self._td_builder_mana_cost)
        self._dispatch_ops([("write_bytes", caster.address + 0x26, bytes((new_mana,)))])
        self.log(
            f"TD TOWER FOUNDATION: P{tower.owner + 1} {UNIT_NAMES[tower.unit_type]} "
            f"at exact ({tower.x},{tower.y}); mana {mana}->{new_mana}; native construction started"
        )

    def prepare_cycle(self) -> bool:
        # Warcraft tears down/replaces several match-owned allocations as soon as
        # the game leaves GAME_RUN. 1.36 kept scanning the old gpUnits allocation
        # after Victory/Defeat, which produced a 250 ms stream of ERROR_PARTIAL_COPY
        # failures. Stop all live-world maintenance before the first unit read once
        # the native game mode becomes terminal.
        try:
            mode = self._read_game_mode()
        except Exception:
            mode = GAME_RUN
        if mode != GAME_RUN:
            if mode == GAME_VICTORY:
                self.game_state = "Victory"
            elif mode == GAME_LOSS:
                self.game_state = "Defeat"
            if getattr(self, "_terminal_game_mode_logged", None) != mode:
                self.log(
                    f"TRIGGER ENGINE QUIESCED: Warcraft game mode {mode} left Running; "
                    "live unit scanning paused"
                )
                self._terminal_game_mode_logged = mode
            return False
        self._terminal_game_mode_logged = None

        self._refresh_holy_visions()
        self._refresh_shared_vision_runtime()
        # Tower-growth maintenance owns the simulation mailbox while an incremental
        # native grow_structure call is in flight. Do not let wave/trigger actions
        # submit a different command until the exact maintenance signature is
        # consumed.
        if self._maintain_td_pending_towers() is False:
            return False
        self._process_td_tower_builder_request()
        route_units = self.units()
        if self._massive_prepare_pre(route_units) is False:
            return False
        # Auto-spell maintenance can change current/next action and Unit+0x88 on
        # Warcraft's simulation thread.  Refresh the snapshot before attack-route
        # maintenance so it never acts on the pre-cast state.
        route_units = self.units()
        self._maintain_attack_routes(route_units)
        current_kills = self._capture_kill_snapshot()
        if self._kill_snapshot:
            self.kill_deltas = {
                key: self._counter_delta(value, self._kill_snapshot.get(key, value))
                for key, value in current_kills.items()
            }
        else:
            self.kill_deltas = {}
        self._kill_snapshot = current_kills
        for (owner, category), amount in self.kill_deltas.items():
            if amount:
                self.log(f"EVENT killed: P{owner + 1} credited +{amount} {category}")
        current_units = self.units()
        current = {self._unit_key(u): u for u in current_units}
        previous = self._snapshot
        self.created_units = [u for key, u in current.items() if key not in previous]
        missing = {key: unit for key, unit in previous.items() if key not in current}
        self.removed_units = [unit for key, unit in missing.items() if key in self._pending_removed_keys]
        self.died_units = [unit for key, unit in missing.items() if key not in self._pending_removed_keys]
        self._massive_prepare_events(current, previous)
        for unit in self.created_units:
            self.log(f"EVENT created: P{unit.owner + 1} {UNIT_NAMES[unit.unit_type]} at ({unit.x},{unit.y})")
        for unit in self.died_units:
            self.log(f"EVENT died: P{unit.owner + 1} {UNIT_NAMES[unit.unit_type]} at ({unit.x},{unit.y})")
        for unit in self.removed_units:
            self.log(f"EVENT removed: P{unit.owner + 1} {UNIT_NAMES[unit.unit_type]} at ({unit.x},{unit.y})")
        self._pending_removed_keys.clear()
        self._issued_orders = {key: value for key, value in self._issued_orders.items() if key in current}
        self._attack_routes = {key: value for key, value in self._attack_routes.items() if key in current}
        self._previous_snapshot = previous
        self._snapshot = current
        return True

    def begin_trigger_run(self) -> None:
        """Start elapsed-time conditions at Start Triggers, not at Attach."""
        # A previous scenario/run may have installed the TD Raise Dead shim.
        # Always restore native semantics before the new trigger's initializer.
        self._disable_td_tower_builder(log_result=False)
        # A stopped run may leave a command published but not yet entered (for
        # example while the match is paused). It has no native side effect yet,
        # so cancel it rather than making the new run wait behind stale work.
        if self._dispatch_inflight is not None and self.dispatcher_installed:
            try:
                state = self.pm.read_uint(self.dispatcher_status_address)
                if state in (DISPATCH_STATE_QUEUED, DISPATCH_STATE_COMPLETE):
                    self.pm.write_uint(self.dispatcher_status_address, DISPATCH_STATE_IDLE)
                    self._dispatch_inflight = None
            except Exception:
                pass
        self._trigger_generation += 1
        self._action_context = None
        self._action_dispatch_cursor = 0
        self._dispatch_journal.clear()
        self._action_value_cache.clear()
        self.started = time.monotonic()
        initial = self.units()
        self._snapshot = {self._unit_key(unit): unit for unit in initial}
        self._previous_snapshot = dict(self._snapshot)
        self.created_units = []
        self.died_units = []
        self.removed_units = []
        self._pending_removed_keys.clear()
        self._issued_orders.clear()
        self._attack_routes.clear()
        self._active_visions.clear()
        self._kill_snapshot = self._capture_kill_snapshot()
        self.kill_deltas = {}
        self._massive_begin_run()
        self.log(f"Trigger clock reset; event baseline contains {len(initial)} unit(s)")

    def _unit_entered_location_count(self, args: dict[str, Any], executing_player: int) -> int:
        """Count units that crossed from outside to inside since the last cycle."""
        location_name = str(args.get("location", "Anywhere"))
        if location_name == "Anywhere":
            raise ValueError("Unit Entered Location requires a named location")
        current = getattr(self, "_snapshot", {})
        keys = getattr(self, "_entered_location_events", {}).get(location_name, set())
        matches = [
            key for key in keys
            if key in current and self._selector_matches(current[key], args, executing_player)
        ]
        if matches:
            self._set_event_context("Unit Entered Location", current[matches[0]], len(matches))
            self._event_context["location"] = location_name
        return len(matches)

    def value(self, kind: str, args: dict[str, Any], player: int) -> Any:
        massive = self.massive_value(kind, args, player)
        if massive is not MASSIVE_UNHANDLED:
            return massive
        if kind == "Elapsed Time": return int(time.monotonic() - self.started)
        if kind == "Switch": return self.switches.get(args.get("name", "Switch 1"), "Cleared")
        if kind == "Counter": return int(self.counters.get(str(args.get("name", "Counter 1")), 0))
        if kind == "Unit Entered Location":
            return self._unit_entered_location_count(args, player)
        if kind == "Game State":
            if self.game_state != "Playing":
                return self.game_state
            mode = self._read_game_mode()
            if mode == GAME_VICTORY:
                self.game_state = "Victory"
            elif mode == GAME_LOSS:
                self.game_state = "Defeat"
            return self.game_state
        if kind == "Resources":
            owner = self._resolve_player_value(args.get("player", player), player)
            return self._read_resource(owner, args.get("resource", "Gold"))
        if kind in {"Kills", "Deaths"}:
            owner = self._resolve_player_value(args.get("player", player), player)
            return self._read_combat_stat(owner, kind, args.get("category", "All"))
        if kind == "Player Killed":
            owner = self._resolve_player_value(args.get("player", player), player)
            return self._kill_delta(owner, args.get("category", "All"))
        if kind == "Score":
            owner = self._stat_owner(args.get("player", player))
            return self._read_stat_table(owner, "Score")
        if kind in {"Command", "Bring"}: return len(self._selected_units(args, player))
        if kind == "Building Count":
            owner=self._resolve_player_value(args.get("player", player), player); requested=args.get("unit", "Any")
            return sum(1 for unit in self._selected_units({"player": owner, "unit": "Any", "location": args.get("location", "Anywhere")}, player) if FIRST_BUILDING_TYPE <= unit.unit_type <= LAST_BUILDING_TYPE and bool(unit.sflags & 0x0080) and (requested == "Any" or int(requested) == unit.unit_type))
        if kind == "Building Completed":
            return sum(
                1 for unit in self._selected_units(args, player)
                if FIRST_BUILDING_TYPE <= unit.unit_type <= LAST_BUILDING_TYPE
                and bool(unit.sflags & 0x0080)
            )
        if kind in {"Unit Created", "Unit Died", "Unit Removed"}:
            source = {"Unit Created": self.created_units, "Unit Died": self.died_units, "Unit Removed": self.removed_units}[kind]
            matches = self._selected_from(source, args, player)
            if matches:
                self._set_event_context(kind, matches[0], len(matches), matches[0])
            return len(matches)
        if kind == "Corpse Count": return len(self._selected_from(self.corpses(), args, player))
        if kind == "Missile Count": return len(self._selected_missiles(args, player))
        if kind == "Rune Count": return len(self._active_runes(args))
        if kind in {"Hit Points", "Mana"}:
            units = self._selected_units(args, player)
            if not units: return 0
            return getattr(units[0], "health" if kind == "Hit Points" else "mana")
        if kind == "Unit Property":
            units = self._selected_units(args, player)
            prop = args.get("property", "health")
            return getattr(units[0], prop) if units else 0
        raise RuntimeError(f"Live condition is not validated yet: {kind}")

    @staticmethod
    def _diplomacy_players(
        args: dict[str, Any], plural_key: str, singular_key: str, default: int
    ) -> list[int]:
        value = args.get(plural_key, args.get(singular_key, [default]))
        if isinstance(value, str):
            text = value.strip().casefold()
            if text in {"all", "all players", "players 1-8"}:
                values = list(range(8))
            else:
                values = []
                for part in re.split(r"[,; ]+", value.strip()):
                    if not part:
                        continue
                    match = re.fullmatch(r"(?:p|player)?(\d+)", part, re.IGNORECASE)
                    values.append(int(match.group(1)) - 1 if match else int(part, 0))
        elif isinstance(value, (list, tuple, set)):
            values = [int(item) for item in value]
        else:
            values = [int(value)]
        result = sorted(set(values))
        if not result:
            raise ValueError(f"{plural_key.replace('_', ' ').title()} requires at least one player")
        if any(not 0 <= item <= 7 for item in result):
            raise ValueError("Diplomacy supports Player 1 through Player 8")
        return result

    def _live_player_color_mapping(self) -> tuple[dict[int, int], dict[int, int], set[int]]:
        """Return owner-slot->display-color and inverse mappings from live units.

        Unit+0x2D is the color actually drawn by Warcraft.  Observed unit colors
        are authoritative. Missing/empty slots are completed as a permutation so
        fixed-color actions remain deterministic even before a player owns a unit.
        """
        votes: dict[int, dict[int, int]] = {owner: {} for owner in range(8)}
        for unit in self.units():
            if 0 <= unit.owner < 8 and 0 <= unit.color < 8:
                bucket = votes[unit.owner]
                bucket[unit.color] = bucket.get(unit.color, 0) + 1

        slot_to_color: dict[int, int] = {}
        observed: set[int] = set()
        used_colors: set[int] = set()
        ranked = []
        for owner, bucket in votes.items():
            if bucket:
                color, count = max(bucket.items(), key=lambda item: (item[1], -item[0]))
                ranked.append((count, owner, color))
        for _count, owner, color in sorted(ranked, reverse=True):
            if color in used_colors:
                continue
            slot_to_color[owner] = color
            observed.add(owner)
            used_colors.add(color)

        remaining_slots = [owner for owner in range(8) if owner not in slot_to_color]
        remaining_colors = [color for color in range(8) if color not in used_colors]
        # Prefer identity for missing slots, then fill the remaining permutation.
        for owner in list(remaining_slots):
            if owner in remaining_colors:
                slot_to_color[owner] = owner
                remaining_slots.remove(owner)
                remaining_colors.remove(owner)
        for owner, color in zip(remaining_slots, remaining_colors):
            slot_to_color[owner] = color

        color_to_slot = {color: owner for owner, color in slot_to_color.items()}
        if len(slot_to_color) != 8 or len(color_to_slot) != 8:
            raise RuntimeError("Could not reconstruct Warcraft's live eight-color player permutation")
        return slot_to_color, color_to_slot, observed

    def _resolve_diplomacy_reference(
        self, selected: list[int], reference_mode: str
    ) -> list[int]:
        mode = str(reference_mode or PLAYER_REFERENCE_MODES[0])
        if mode == PLAYER_REFERENCE_MODES[0]:
            return sorted(set(int(value) for value in selected))
        if mode != PLAYER_REFERENCE_MODES[1]:
            raise ValueError(f"Unknown diplomacy player-numbering mode: {mode}")
        _slot_to_color, color_to_slot, _observed = self._live_player_color_mapping()
        return sorted({color_to_slot[int(color)] for color in selected})

    @staticmethod
    def _player_set_label(players: list[int]) -> str:
        players = sorted(set(int(player) for player in players))
        if players == list(range(8)):
            return "Players 1-8"
        return ", ".join(f"P{player + 1}" for player in players)

    @staticmethod
    def _color_set_label(colors: list[int]) -> str:
        colors = sorted(set(int(color) for color in colors))
        if colors == list(range(8)):
            return "all displayed colors"
        return ", ".join(PLAYER_COLOR_NAMES[color] for color in colors)

    def _diplomacy_reference_label(
        self, raw_players: list[int], resolved_players: list[int], reference_mode: str
    ) -> str:
        if reference_mode == PLAYER_REFERENCE_MODES[1]:
            return (
                f"{self._color_set_label(raw_players)} -> "
                f"live {self._player_set_label(resolved_players)}"
            )
        return self._player_set_label(resolved_players)

    def action(self, kind: str, args: dict[str, Any], player: int) -> None:
        if kind == "Enable Death Knight Tower Builder":
            self._enable_td_tower_builder(args, player)
            return
        if kind == "Disable Death Knight Tower Builder":
            self._disable_td_tower_builder()
            return
        if self.massive_action(kind, args, player):
            return
        if kind == "Display Text": self.log(str(args.get("text", ""))); return
        if kind == "Game Message": self._game_message(args, player); return
        if kind == "Player Chat": self._player_chat(args, player); return
        if kind == "Set Switch": self.switches[args.get("name", "Switch 1")] = args.get("state", "Set"); return
        if kind in {"Set Counter", "Add Counter", "Subtract Counter"}:
            name = str(args.get("name", "Counter 1")).strip()
            if not name:
                raise ValueError(f"{kind} requires a counter name")
            amount = int(args.get("amount", 0))
            if amount < 0:
                raise ValueError(f"{kind} amount cannot be negative")
            before = int(self.counters.get(name, 0))
            if kind == "Set Counter":
                after = amount
            elif kind == "Add Counter":
                after = min(0x7FFFFFFF, before + amount)
            else:
                after = max(0, before - amount)
            self.counters[name] = after
            self.log(f"COUNTER: {name} {before} -> {after} ({kind})")
            return
        if kind in {"Victory", "Defeat"}:
            self._request_game_result(kind)
            return
        if kind in {"Set Resources", "Add Resources", "Subtract Resources"}:
            owner = int(args.get("player", player))
            resource, address = self._resource_address(owner, args.get("resource", "Gold"))
            amount = int(args.get("amount", 0))
            if not 0 <= amount <= MAX_RESOURCE_VALUE:
                raise ValueError(f"Invalid {kind} amount: {amount}")
            before = self._read_resource(owner, resource)
            if kind == "Set Resources":
                after = amount
            elif kind == "Add Resources":
                after = min(MAX_RESOURCE_VALUE, before + amount)
            else:
                after = max(0, before - amount)
            self._dispatch_ops([("write_dword", address, after)])
            verified = self._read_resource(owner, resource)
            if verified != after:
                raise RuntimeError(
                    f"{kind} verification failed for P{owner + 1} {resource}: expected {after}, read {verified}"
                )
            self.log(f"RESOURCES: P{owner + 1} {resource} {before} -> {verified} ({kind})")
            return
        if kind == "Award Kill Resources":
            def build_reward():
                killer = int(args.get("killer_player", player))
                category = self._stat_category(args.get("category", "All"))
                recipient = int(args.get("recipient_player", killer))
                resource, address = self._resource_address(recipient, args.get("resource", "Gold"))
                per_kill = int(args.get("amount_per_kill", 0))
                if per_kill < 0:
                    raise ValueError("Amount per kill cannot be negative")
                count = self._kill_delta(killer, category)
                before = self._read_resource(recipient, resource)
                reward = min(MAX_RESOURCE_VALUE, count * per_kill)
                after = min(MAX_RESOURCE_VALUE, before + reward)
                return killer, category, recipient, resource, address, per_kill, count, before, after
            killer, category, recipient, resource, address, per_kill, count, before, after = self._cached_action_value("kill_reward", build_reward)
            if count <= 0 or per_kill <= 0:
                self.log(f"KILL REWARD: no new P{killer + 1} {category} kills; no {resource} awarded")
                return
            self._dispatch_ops([("write_dword", address, after)])
            verified = self._read_resource(recipient, resource)
            if verified != after:
                raise RuntimeError(
                    f"Award Kill Resources verification failed for P{recipient + 1} {resource}: "
                    f"expected {after}, read {verified}"
                )
            self.log(
                f"KILL REWARD: P{killer + 1} +{count} {category} kill(s) -> "
                f"P{recipient + 1} {resource} {before}->{verified} "
                f"({per_kill} each, +{verified - before})"
            )
            return
        if kind == "Set Game Speed":
            speed_index = self._game_speed_index(args.get("speed", "Fastest"))
            packet = self._native_game_speed_packet(speed_index)
            self._dispatch_ops([
                ("write_bytes", self.dispatcher_chat_packet_address, bytes(packet)),
                (
                    "call",
                    self.message_path["net_send_msg_all"],
                    [self.dispatcher_chat_packet_address],
                ),
            ])
            self.log(
                f"GAME SPEED: requested {GAME_SPEED_LEVELS[speed_index]} "
                f"(native index {speed_index}) through PM_SET_SPEED"
            )
            return

        if kind == "Set Player Relations":
            reference_mode=str(args.get("player_reference_mode", PLAYER_REFERENCE_MODES[0]))
            matrix=args.get("matrix", {})
            raw_alliance=matrix.get("alliance", [[p] for p in range(8)])
            raw_vision=matrix.get("vision", [[p] for p in range(8)])
            raw_victory=set(int(x) for x in matrix.get("allied_victory", []))
            if reference_mode == PLAYER_REFERENCE_MODES[0]:
                mapping=list(range(8))
            elif reference_mode == PLAYER_REFERENCE_MODES[1]:
                _slot_to_color, color_to_slot, _observed = self._live_player_color_mapping()
                mapping=[color_to_slot[color] for color in range(8)]
            else:
                raise ValueError(f"Unknown diplomacy player-numbering mode: {reference_mode}")
            # displayed/reference index -> live owner slot
            alliance_rows=[[RELATION_ENEMY]*8 for _ in range(8)]
            vision_masks=[0]*8
            victory_mask=0
            for displayed_source in range(8):
                source=mapping[displayed_source]
                alliance_rows[source][source]=self._self_relation_code(source)
                for displayed_target in raw_alliance[displayed_source]:
                    target=mapping[int(displayed_target)]
                    if target != source:
                        alliance_rows[source][target]=RELATION_ALLIED
                for displayed_viewer in raw_vision[displayed_source]:
                    viewer=mapping[int(displayed_viewer)]
                    vision_masks[source] |= 1 << viewer
                vision_masks[source] |= 1 << source
                if displayed_source in raw_victory:
                    victory_mask |= 1 << source
            # Publish the complete vision matrix before any native diplomacy
            # call. The entry guard then preserves it through all eight updates.
            active_sources = self._remember_shared_vision_masks(vision_masks)
            self._program_shared_vision_guard(vision_masks)
            self._sync_diplomacy_compatibility()
            # Legacy combined action also goes through the native updater so its
            # Alliance rows cannot be overwritten and computer relations refresh.
            self._call_cdecl_batched([
                self._diplomacy_call(
                    source,
                    alliance_rows[source],
                    vision_masks[source],
                    bool(victory_mask & (1 << source)),
                )
                for source in range(8)
            ])
            refreshed = self._refresh_shared_vision_now(active_sources) if active_sources else 0
            for source in range(8):
                row,vision,victory=self._read_diplomacy_state(source)
                if list(row[:8]) != alliance_rows[source]: raise RuntimeError(f"Player relation verification failed for P{source+1} alliance row")
                if vision != vision_masks[source]: raise RuntimeError(f"Player relation verification failed for P{source+1} vision mask")
                if victory != bool(victory_mask & (1<<source)): raise RuntimeError(f"Player relation verification failed for P{source+1} allied victory")
            self.log("PLAYER RELATIONS: exact 8x8 alliance and vision matrices applied; self-cells fixed Allied; self vision locked on; allied-victory mask 0x%02X; refreshed %d unit(s)" % (victory_mask, refreshed))
            return
        if kind in {"Set Alliance", "Set Allied Victory", "Set Shared Vision"}:
            # 1.23.30 exact per-player matrix format. Older group-based actions
            # fall through to the compatibility implementation below.
            if "matrix" in args:
                reference_mode = str(args.get("player_reference_mode", PLAYER_REFERENCE_MODES[0]))
                raw_rows = args.get("matrix", [])
                if not isinstance(raw_rows, list) or len(raw_rows) != 8:
                    raise ValueError(f"{kind} matrix must contain all 8 player rows")

                normalized_rows: list[list[int]] = []
                for source in range(8):
                    raw_row = raw_rows[source]
                    if not isinstance(raw_row, (list, tuple, set)):
                        raise ValueError(f"{kind} Player {source + 1} row is invalid")
                    selected = {int(target) for target in raw_row if 0 <= int(target) <= 7}
                    selected.add(source)
                    normalized_rows.append(sorted(selected))

                if reference_mode == PLAYER_REFERENCE_MODES[0]:
                    mapping = list(range(8))
                elif reference_mode == PLAYER_REFERENCE_MODES[1]:
                    _slot_to_color, color_to_slot, _observed = self._live_player_color_mapping()
                    mapping = [color_to_slot[color] for color in range(8)]
                else:
                    raise ValueError(f"Unknown diplomacy player-numbering mode: {reference_mode}")

                numbering_label = (
                    "displayed colors translated to live slots"
                    if reference_mode == PLAYER_REFERENCE_MODES[1]
                    else "live owner slots"
                )

                if kind == "Set Alliance":
                    # Checked = Allied, unchecked = Enemy.  Do not write gEnemyTbl
                    # directly: Remaster's native diplomacy updater also performs
                    # the engine-side relation refresh needed by computer players.
                    live_rows = [[RELATION_ENEMY] * 8 for _ in range(8)]
                    for source in range(8):
                        live_rows[source][source] = self._self_relation_code(source)
                    for reference_source, selected_targets in enumerate(normalized_rows):
                        source = mapping[reference_source]
                        for reference_target in selected_targets:
                            target = mapping[reference_target]
                            if target != source:
                                live_rows[source][target] = RELATION_ALLIED

                    before_rows: list[list[int]] = []
                    calls: list[tuple[int, list[int]]] = []
                    changed_sources: list[int] = []
                    for source, desired in enumerate(live_rows):
                        current, vision, victory = self._read_diplomacy_state(source)
                        current = list(current[:8])
                        before_rows.append(current)
                        if current != desired:
                            changed_sources.append(source)
                        # Always run the native updater for all eight rows. The
                        # visible bytes can already match while Warcraft's computer
                        # target-acquisition cache still reflects the map's original
                        # diplomacy. Skipping these calls made attack-area waves pass
                        # through each other without acquiring an enemy.
                        calls.append(self._diplomacy_call(source, desired, vision, victory))
                    self._call_cdecl_batched(calls)
                    # The diplomacy-entry guard preserves trigger-owned vision
                    # through all eight native relation refreshes. No fog/cache
                    # rebuild is permitted here.
                    active_vision_sources, _restored_masks = self._restore_desired_shared_vision_masks()
                    self._sync_diplomacy_compatibility()
                    vision_refreshed = 0

                    newly_allied = {
                        (source, target)
                        for source in range(8) for target in range(8)
                        if source != target
                        and not self._relation_is_allied(source, target, before_rows[source][target])
                        and self._relation_is_allied(source, target, live_rows[source][target])
                    }
                    newly_enemy = {
                        (source, target)
                        for source in range(8) for target in range(8)
                        if source != target
                        and not self._relation_is_enemy(source, target, before_rows[source][target])
                        and self._relation_is_enemy(source, target, live_rows[source][target])
                    }

                    summaries: list[str] = []
                    for source, expected in enumerate(live_rows):
                        row, _vision, _victory = self._read_diplomacy_state(source)
                        if list(row[:8]) != expected:
                            raise RuntimeError(f"Set Alliance matrix verification failed for P{source + 1}")
                        expected_self = self._self_relation_code(source)
                        if int(row[source]) != expected_self:
                            raise RuntimeError(
                                f"Set Alliance matrix changed P{source + 1} self relation "
                                f"{expected_self}->{int(row[source])}"
                            )
                        allies, enemies = self._relation_masks(source, row)
                        summaries.append(f"P{source + 1}:allies=0x{allies:02X}/enemies=0x{enemies:02X}")

                    stopped = self._cancel_now_friendly_combat(newly_allied) if newly_allied else 0
                    # Re-arm from the full desired enemy matrix, not only byte
                    # transitions. The table may already contain Enemy while the
                    # native computer cache still came from the original scenario.
                    all_enemy_pairs = {
                        (source, target)
                        for source in range(8) for target in range(8)
                        if self._relation_is_enemy(source, target, live_rows[source][target])
                    }
                    rearmed = self._rearm_new_enemy_combat(all_enemy_pairs)
                    cross_allies = sum(
                        1 for source in range(8) for target in range(8)
                        if source != target and self._relation_is_allied(source, target, live_rows[source][target])
                    )
                    self.log(
                        f"ALLIANCE MATRIX: checked=Allied(value 1), unchecked=Enemy(value 0); self-cells repaired Allied(value 1); "
                        f"native updater refreshed all 8 row(s) by {numbering_label} "
                        f"({len(changed_sources)} byte row(s) changed); "
                        f"{cross_allies} allied cross-player directed cell(s), "
                        f"{56 - cross_allies} enemy cell(s); "
                        f"masks [{'; '.join(summaries)}]"
                        + (f"; stopped {stopped} now-friendly attack order(s)" if stopped else "")
                        + (f"; rearmed {rearmed} computer combat unit(s) for new enemies" if rearmed else "")
                        + (f"; refreshed shared vision on {vision_refreshed} source unit(s)" if vision_refreshed else "")
                    )
                    return

                if kind == "Set Shared Vision":
                    # Exact full source->viewer bit matrix. Alliance bytes are untouched.
                    masks = [1 << source for source in range(8)]
                    for reference_source, selected_viewers in enumerate(normalized_rows):
                        source = mapping[reference_source]
                        mask = 1 << source
                        for reference_viewer in selected_viewers:
                            mask |= 1 << mapping[reference_viewer]
                        masks[source] = mask & 0xFF

                    relations_before = self.pm.read_bytes(
                        self.diplomacy_path["relations"], 8 * 16
                    )
                    # Apply vision through Warcraft's native diplomacy updater for
                    # every source row. Direct gSharedVision writes are transient:
                    # the game reconstructs them from its player state, which was
                    # the remaining cause of the one-second vision flash. Preserve
                    # the exact current relation row and allied-victory bit.
                    vision_calls: list[tuple[int, list[int]]] = []
                    for source, mask in enumerate(masks):
                        row, _old_vision, victory = self._read_diplomacy_state(source)
                        vision_calls.append(
                            self._diplomacy_call(source, list(row[:8]), mask, victory)
                        )
                    active_sources = self._remember_shared_vision_masks(masks)
                    self._program_shared_vision_guard(masks)
                    if active_sources:
                        self._restore_offline_command_mode()
                        self._restore_shared_vision_offline_patch()
                    self._call_cdecl_batched(vision_calls)
                    relations_after = self.pm.read_bytes(
                        self.diplomacy_path["relations"], 8 * 16
                    )
                    if relations_after != relations_before:
                        self.pm.write_bytes(
                            self.diplomacy_path["relations"],
                            relations_before,
                            len(relations_before),
                        )
                        raise RuntimeError(
                            "Set Shared Vision matrix changed alliance bytes; original relations restored"
                        )

                    compatibility_active = self._sync_diplomacy_compatibility()
                    refreshed_units = (
                        self._refresh_shared_vision_now(active_sources)
                        if active_sources else 0
                    )
                    if not active_sources:
                        self._shared_vision_sources.clear()
                        self._next_shared_vision_refresh = 0.0

                    for source, expected in enumerate(masks):
                        actual = self.pm.read_uchar(self.diplomacy_path["shared_vision"] + source)
                        if actual != expected:
                            raise RuntimeError(
                                f"Set Shared Vision matrix verification failed for P{source + 1}: "
                                f"expected 0x{expected:02X}, read 0x{actual:02X}"
                            )
                    cross_vision = sum(
                        1 for source, mask in enumerate(masks) for viewer in range(8)
                        if source != viewer and bool(mask & (1 << viewer))
                    )
                    gate = self.pm.read_uchar(self.diplomacy_path["multiplayer_gate"])
                    self.log(
                        f"SHARED VISION MATRIX: exact 8x8 source->viewer grid applied by {numbering_label}; "
                        f"{cross_vision} cross-player directed cell(s); "
                        f"masks [{', '.join(f'P{source + 1}=0x{mask:02X}' for source, mask in enumerate(masks))}]; "
                        f"post-reset fog compositor={'active' if compatibility_active else 'not required'} "
                        f"(gbMultiPlayer={gate}); alliance matrix unchanged; "
                        "source-guarded matrix plus pre-render local fog compositor active"
                    )
                    return

                # Allied Victory is stored by Warcraft as one enable bit per player,
                # not an 8x8 native table. The row/column editor records intended
                # partners; a row gains its native bit when any cross-player partner
                # is checked. The current alliance matrix remains authoritative for
                # which surviving players can actually win together.
                victory_mask = 0
                intended_pairs: list[tuple[int, int]] = []
                for reference_source, selected_partners in enumerate(normalized_rows):
                    source = mapping[reference_source]
                    cross = [target for target in selected_partners if target != reference_source]
                    if cross:
                        victory_mask |= 1 << source
                    for reference_target in cross:
                        intended_pairs.append((source, mapping[reference_target]))
                self._dispatch_ops([
                    ("write_bytes", self.diplomacy_path["allied_victory"], bytes([victory_mask]))
                ])
                actual_mask = self.pm.read_uchar(self.diplomacy_path["allied_victory"])
                if actual_mask != victory_mask:
                    raise RuntimeError(
                        f"Set Allied Victory matrix verification failed: "
                        f"expected 0x{victory_mask:02X}, read 0x{actual_mask:02X}"
                    )
                not_allied: list[str] = []
                for source, target in intended_pairs:
                    row, _vision, _victory = self._read_diplomacy_state(source)
                    if not self._relation_is_allied(source, target, row[target]):
                        not_allied.append(f"P{source + 1}->P{target + 1}")
                enabled_players = [source for source in range(8) if victory_mask & (1 << source)]
                self.log(
                    f"ALLIED VICTORY MATRIX: partner grid applied by {numbering_label}; "
                    f"native mask 0x{victory_mask:02X}; enabled "
                    f"{self._player_set_label(enabled_players) if enabled_players else 'none'}; "
                    f"{len(intended_pairs)} directed intended partner cell(s)"
                )
                if not_allied:
                    self.log(
                        "ALLIED VICTORY WARNING: these selected partner cells are currently Enemy "
                        "in the Alliance matrix and cannot win together until allied: "
                        + ", ".join(not_allied)
                    )
                live_computers = sorted({
                    unit.owner for unit in self.units()
                    if 0 <= unit.owner < 8 and self._owner_type(unit.owner) == C_COMPUTER
                })
                if victory_mask and live_computers:
                    self.log(
                        "ALLIED VICTORY NOTE: Warcraft's native evaluator returns while a live "
                        "Computer player exists; the matrix is stored, but native Computer-team "
                        "victory remains a game limitation."
                    )
                return

            def load_states(players: set[int]) -> dict[int, dict[str, Any]]:
                states: dict[int, dict[str, Any]] = {}
                for owner in sorted(players):
                    row, vision, victory = self._read_diplomacy_state(owner)
                    states[owner] = {
                        "row": row,
                        "vision": vision,
                        "victory": victory,
                    }
                return states

            def build_diplomacy_calls():
                reference_mode = str(args.get("player_reference_mode", PLAYER_REFERENCE_MODES[0]))
                if kind == "Set Alliance":
                    raw_sources = self._diplomacy_players(args, "players", "player", player)
                    raw_targets = self._diplomacy_players(args, "other_players", "other_player", 1)
                    sources = self._resolve_diplomacy_reference(raw_sources, reference_mode)
                    targets = self._resolve_diplomacy_reference(raw_targets, reference_mode)
                    relation = RELATION_ALLIED if str(args.get("state", "Allied")).casefold() == "allied" else RELATION_ENEMY
                    mutual = bool(args.get("mutual", True))
                    pairs = {(source, target) for source in sources for target in targets if source != target}
                    if mutual:
                        pairs |= {(target, source) for source, target in tuple(pairs)}
                    if not pairs:
                        raise ValueError("Set Alliance needs at least one different source/target pair")
                    states = load_states({source for source, _target in pairs})
                    self._apply_relation_pairs(states, pairs, relation)
                    relation_plan = {
                        owner: bytes(int(value) & 0xFF for value in state["row"][:8])
                        for owner, state in sorted(states.items())
                    }
                    calls = [
                        self._diplomacy_call(owner, state["row"], state["vision"], state["victory"])
                        for owner, state in sorted(states.items())
                    ]
                    return calls, (
                        raw_sources, raw_targets, sources, targets, relation, mutual,
                        sorted(pairs), relation_plan, reference_mode,
                    )

                if kind == "Set Allied Victory":
                    raw_owners = self._diplomacy_players(args, "players", "player", player)
                    owners = self._resolve_diplomacy_reference(raw_owners, reference_mode)
                    enabled = bool(args.get("enabled", True))
                    states = load_states(set(owners))
                    for owner in owners:
                        states[owner]["victory"] = enabled
                    calls = [
                        self._diplomacy_call(owner, state["row"], state["vision"], state["victory"])
                        for owner, state in sorted(states.items())
                    ]
                    return calls, (raw_owners, owners, enabled, reference_mode)

                raw_sources = self._diplomacy_players(args, "source_players", "source_player", player)
                raw_viewers = self._diplomacy_players(args, "viewer_players", "viewer_player", 1)
                sources = self._resolve_diplomacy_reference(raw_sources, reference_mode)
                viewers = self._resolve_diplomacy_reference(raw_viewers, reference_mode)
                enabled = bool(args.get("enabled", True))
                mutual = bool(args.get("mutual", False))
                pairs = {(source, viewer) for source in sources for viewer in viewers if source != viewer}
                if mutual:
                    pairs |= {(viewer, source) for source, viewer in tuple(pairs)}
                if not pairs:
                    raise ValueError("Set Shared Vision needs at least one different source/viewer pair")
                # gSharedVision is indexed by the vision source.  Each byte is
                # the bit mask of viewers who receive that source's fog/units.
                # Remaster proves this in its unit-mask refresh by copying
                # gSharedVision[unitOwner] directly to Unit+0x29.
                states = load_states({source for source, _viewer in pairs})
                self._apply_shared_vision_pairs(states, pairs, enabled)
                # Preserve each exact relation row while updating the native
                # persistent vision state. The execution path verifies gEnemyTbl
                # byte-for-byte after the updater returns.
                vision_plan = {
                    owner: int(state["vision"]) & 0xFF
                    for owner, state in sorted(states.items())
                }
                return [], (
                    raw_sources, raw_viewers, sources, viewers, enabled, mutual,
                    sorted(pairs), vision_plan, reference_mode,
                )

            calls, detail = self._cached_action_value("diplomacy_calls", build_diplomacy_calls)

            if kind == "Set Alliance":
                # Use the native updater even for pre-matrix projects. Direct
                # gEnemyTbl writes can be overwritten by Remaster's diplomacy
                # state and do not reliably wake computer target acquisition.
                self._call_cdecl_batched(calls)
            elif kind == "Set Shared Vision":
                relations_before = self.pm.read_bytes(
                    self.diplomacy_path["relations"], 8 * 16
                )
                vision_plan = detail[7]
                vision_calls: list[tuple[int, list[int]]] = []
                for source, mask in sorted(vision_plan.items()):
                    row, _old_vision, victory = self._read_diplomacy_state(int(source))
                    vision_calls.append(
                        self._diplomacy_call(
                            int(source), list(row[:8]), int(mask) & 0xFF, victory
                        )
                    )
                projected_masks = self._capture_shared_vision_masks()
                for source, mask in vision_plan.items():
                    projected_masks[int(source)] = int(mask) & 0xFF
                active_sources = self._remember_shared_vision_masks(projected_masks)
                self._program_shared_vision_guard(projected_masks)
                if active_sources:
                    self._restore_offline_command_mode()
                    self._restore_shared_vision_offline_patch()
                self._call_cdecl_batched(vision_calls)
                relations_after = self.pm.read_bytes(
                    self.diplomacy_path["relations"], 8 * 16
                )
                if relations_after != relations_before:
                    # A vision-only action must never modify alliance/enemy state.
                    self.pm.write_bytes(
                        self.diplomacy_path["relations"],
                        relations_before,
                        len(relations_before),
                    )
                    raise RuntimeError(
                        "Set Shared Vision changed the alliance table; original relations restored"
                    )
            else:
                self._call_cdecl_batched(calls)

            alliance_vision_refreshed = 0
            if kind == "Set Alliance":
                _active_vision_sources, _restored_masks = self._restore_desired_shared_vision_masks()
                compatibility_active = self._sync_diplomacy_compatibility()
            else:
                compatibility_active = self._sync_diplomacy_compatibility()

            if kind == "Set Shared Vision":
                # The simulation and diplomacy guards own persistence. Existing
                # units are refreshed only once by the action-specific native calls;
                # runtime maintenance never clears or rebuilds visibility.
                active_sources, _restored_masks = self._restore_desired_shared_vision_masks()
                refreshed_units = (
                    self._refresh_shared_vision_now(active_sources)
                    if active_sources else 0
                )
                if not active_sources:
                    self._shared_vision_sources.clear()
                    self._next_shared_vision_refresh = 0.0
            if kind == "Set Alliance":
                (
                    raw_sources, raw_targets, sources, targets, relation, mutual,
                    pairs, _relation_plan, reference_mode,
                ) = detail
                state_name = "Allied" if relation == RELATION_ALLIED else "Enemy"
                touched_sources = sorted({source for source, _target in pairs})
                mask_summary: list[str] = []
                for source, target in pairs:
                    row, _vision, _victory = self._read_diplomacy_state(source)
                    if row[target] != relation:
                        raise RuntimeError(
                            f"Set Alliance verification failed for P{source + 1}->P{target + 1}"
                        )
                for source in touched_sources:
                    row, _vision, _victory = self._read_diplomacy_state(source)
                    expected_self = self._self_relation_code(source)
                    if int(row[source]) != expected_self:
                        raise RuntimeError(
                            f"Set Alliance changed P{source + 1} self relation "
                            f"{expected_self}->{int(row[source])}"
                        )
                    allied_mask, enemy_mask = self._relation_masks(source, row)
                    mask_summary.append(
                        f"P{source + 1}:allies=0x{allied_mask:02X}/enemies=0x{enemy_mask:02X}"
                    )
                stopped = self._cancel_now_friendly_combat(set(pairs)) if relation == RELATION_ALLIED else 0
                mode = self.pm.read_uchar(self.diplomacy_path["multiplayer_gate"])
                self.log(
                    f"DIPLOMACY: "
                    f"{self._diplomacy_reference_label(raw_sources, sources, reference_mode)} -> "
                    f"{self._diplomacy_reference_label(raw_targets, targets, reference_mode)} = {state_name}"
                    + (" (mutual)" if mutual else " (one-way)")
                    + f"; {len(pairs)} exact directed cell(s); matrix verified; "
                    + f"gbMultiPlayer={mode}; masks [{'; '.join(mask_summary)}]"
                    + (f"; stopped {stopped} now-friendly attack order(s)" if stopped else "")
                    + (f"; refreshed shared vision on {alliance_vision_refreshed} source unit(s)" if alliance_vision_refreshed else "")
                )
            elif kind == "Set Allied Victory":
                raw_owners, owners, enabled, reference_mode = detail
                for owner in owners:
                    _row, _vision, verified = self._read_diplomacy_state(owner)
                    if verified != enabled:
                        raise RuntimeError(
                            f"Set Allied Victory verification failed for P{owner + 1}"
                        )
                victory_mask = self.pm.read_uchar(self.diplomacy_path["allied_victory"])
                owner_summary = ", ".join(
                    f"P{owner + 1}={self._owner_type_name(self._owner_type(owner))}"
                    for owner in owners
                )
                self.log(
                    f"ALLIED VICTORY: {self._diplomacy_reference_label(raw_owners, owners, reference_mode)} "
                    f"{'enabled' if enabled else 'disabled'}; live mask 0x{victory_mask:02X} verified; "
                    f"{owner_summary}"
                )
                live_computers = sorted({
                    unit.owner for unit in self.units()
                    if 0 <= unit.owner < 8 and self._owner_type(unit.owner) == C_COMPUTER
                })
                if enabled and live_computers:
                    self.log(
                        "ALLIED VICTORY NOTE: Warcraft's native victory_multi_player source "
                        "returns immediately while any live Computer player exists. "
                        f"Computer slot(s) {self._player_set_label(live_computers)} can be allied "
                        "and share vision, but they cannot participate in native Allied Victory."
                    )
            else:
                (
                    raw_sources, raw_viewers, sources, viewers, enabled, mutual,
                    pairs, _vision_plan, reference_mode,
                ) = detail
                for source, viewer in pairs:
                    _row, vision, _victory = self._read_diplomacy_state(source)
                    if bool(vision & (1 << viewer)) != enabled:
                        raise RuntimeError(
                            f"Set Shared Vision verification failed for P{source + 1}->P{viewer + 1}"
                        )
                mode = self.pm.read_uchar(self.diplomacy_path["multiplayer_gate"])
                vision_summary = ", ".join(
                    f"P{source + 1}=0x{self.pm.read_uchar(self.diplomacy_path['shared_vision'] + source):02X}"
                    for source in sorted(active_sources or set(sources))
                )
                self.log(
                    f"SHARED VISION: "
                    f"{self._diplomacy_reference_label(raw_sources, sources, reference_mode)} -> "
                    f"{self._diplomacy_reference_label(raw_viewers, viewers, reference_mode)} "
                    f"{'enabled' if enabled else 'disabled'}"
                    + (" (mutual)" if mutual else "")
                    + f"; {len(pairs)} directed pair(s); live masks verified; "
                    + "alliance matrix unchanged; post-reset local fog compositor active"
                    + f"; gbMultiPlayer={mode} (offline commands preserved); masks [{vision_summary or 'self-only'}]"
                    + f"; refreshed {refreshed_units} existing source unit(s)"
                )
            return
        if kind == "Set Unit Property":
            prop = args.get("property", "health")
            offsets = {"action": 0x2E}
            if prop == "health":
                value = max(0, min(65535, int(args.get("value", 0))))
                units = self._selected_units(args, player)
                for unit in units: self.pm.write_ushort(unit.address + 0x22, value)
                self.log(f"Set health={value} on {len(units)} unit(s)"); return
            if prop not in offsets: raise RuntimeError(f"Unsafe/unvalidated unit property: {prop}")
            value = max(0, min(255, int(args.get("value", 0))))
            units = self._selected_units(args, player)
            for unit in units: self.pm.write_uchar(unit.address + offsets[prop], value)
            self.log(f"Set {prop}={value} on {len(units)} unit(s)"); return
        if kind in {"Set Hit Points", "Set Mana"}:
            units = self._selected_units(args, player)
            if kind == "Set Hit Points":
                value = max(0, min(65535, int(args.get("amount", args.get("value", 0)))))
                for unit in units: self.pm.write_ushort(unit.address + 0x22, value)
            else:
                value = max(0, min(255, int(args.get("amount", args.get("value", 0)))))
                for unit in units: self.pm.write_uchar(unit.address + 0x26, value)
            self.log(f"{kind}={value} on {len(units)} unit(s)"); return
        if kind == "Damage Units":
            units = self._selected_units(args, player)
            damage = max(1, min(255, int(args.get("amount", args.get("damage", 1)))))
            attacker_args = {
                "player": int(args.get("attacker_player", player)),
                "unit": args.get("attacker_unit", "Any"),
                "location": args.get("attacker_location", "Anywhere"),
            }
            attackers = self._selected_units(attacker_args, player)
            if not attackers:
                raise RuntimeError("Damage Units requires a live attacker matching attacker_player/attacker_unit")
            attacker = attackers[0]
            targets = [unit for unit in units if unit.address != attacker.address]
            changed = 0
            fallback = 0
            unchanged: list[str] = []
            for unit in targets:
                before = self.pm.read_ushort(unit.address + 0x22)
                self._call_damage_unit(attacker, unit, damage)
                after = self.pm.read_ushort(unit.address + 0x22)
                post_flags = self.pm.read_ushort(unit.address + 0x1E)
                # Lethal damage normally moves the target into Warcraft's DYING
                # state without rewriting its HP word. That is a successful
                # engine result, so never send the already-dying record through
                # the source-compatible fallback a second time.
                if after == before and not (post_flags & 0x0007):
                    after = self._source_damage_fallback(attacker, unit, damage, before)
                    fallback += 1
                    post_flags = self.pm.read_ushort(unit.address + 0x1E)
                if after != before or (damage >= before and post_flags & 0x0007):
                    changed += 1
                    if damage >= before and post_flags & 0x0007:
                        self.log(f"DAMAGE: {UNIT_NAMES[unit.unit_type]} HP {before} -> lethal (flags 0x{post_flags:04X})")
                    else:
                        self.log(f"DAMAGE: {UNIT_NAMES[unit.unit_type]} HP {before} -> {after}")
                else:
                    flags = self.pm.read_ushort(unit.address + 0x1E)
                    guard = self.pm.read_ushort(unit.address + 0x46)
                    unchanged.append(f"{UNIT_NAMES[unit.unit_type]} slot {(unit.address-self.unit_pool)//UNIT_SIZE} HP {before} flags=0x{flags:04X} guard+46={guard}")
            if unchanged:
                raise RuntimeError("Engine damage changed no HP for: " + "; ".join(unchanged))
            self.log(
                f"Damage Units: {damage} engine damage to {changed} unit(s); "
                f"attacker P{attacker.owner + 1} {UNIT_NAMES[attacker.unit_type]}"
                + (f"; source dispatcher used for {fallback}" if fallback else "")
            )
            return
        if kind == "Create Missile":
            attackers = self._selected_units(args, player)
            amount_arg = args.get("amount", 1)
            if amount_arg != "All":
                attackers = attackers[:max(0, min(64, int(amount_arg)))]
            if not attackers:
                raise RuntimeError("Create Missile found no matching attacker units")
            unsupported = [unit for unit in attackers if unit.unit_type not in REMOVE_LAND_UNIT_TYPES]
            hidden = [unit for unit in attackers if unit.sflags & 0x0008]
            if unsupported:
                names = ", ".join(sorted({UNIT_NAMES[unit.unit_type] for unit in unsupported}))
                raise RuntimeError(
                    f"Create Missile currently validates visible mobile attackers only; unsupported: {names}"
                )
            if hidden:
                raise RuntimeError("Create Missile will not fire from hidden/cargo units")
            target_args = {
                "player": int(args.get("target_player", -1)),
                "unit": args.get("target_unit", "Any"),
                "location": args.get("target_location", "Anywhere"),
            }
            targets = self._selected_units(target_args, -1)
            attacker_addresses = {unit.address for unit in attackers}
            targets = [
                target for target in targets
                if target.address not in attacker_addresses and not (target.sflags & 0x0008)
            ]
            if not targets:
                raise RuntimeError("Create Missile found no active visible target units")
            created = 0
            for attacker in attackers:
                enemies = [target for target in targets if target.owner != attacker.owner]
                if not enemies:
                    raise RuntimeError(
                        f"Create Missile found no enemy target for P{attacker.owner + 1} "
                        f"{UNIT_NAMES[attacker.unit_type]}"
                    )
                target = min(
                    enemies,
                    key=lambda candidate: (
                        (candidate.x - attacker.x) ** 2 + (candidate.y - attacker.y) ** 2,
                        candidate.address,
                    ),
                )
                missile = self._create_missile(attacker, target)
                slot = (missile.address - self.bullet_pool) // BULLET_SIZE
                self.log(
                    f"MISSILE: {MISSILE_NAMES[missile.missile_type]} slot {slot} "
                    f"P{attacker.owner + 1} {UNIT_NAMES[attacker.unit_type]} -> "
                    f"P{target.owner + 1} {UNIT_NAMES[target.unit_type]} "
                    f"damage {missile.damage} flight ({missile.x},{missile.y})->"
                    f"({missile.target_x},{missile.target_y}) flags 0x{missile.flags:02X} "
                    f"action {missile.action}"
                )
                created += 1
            self.log(
                f"Create Missile: Warcraft bullet_create launched {created} engine projectile(s); "
                "flight, impact damage, animation, and cleanup are Warcraft-owned"
            )
            return
        if kind == "Play Sound":
            sound_id = self._spell_sound_id(args.get("sound", "Thunder"))
            source = str(args.get("source", "Location")).strip().casefold()
            source_detail = "location"
            if source == "unit":
                unit_args = {
                    "player": int(args.get("sound_player", player)),
                    "unit": args.get("sound_unit", "Any"),
                    "location": args.get("sound_location", "Anywhere"),
                }
                matches = self._selected_units(unit_args, player)
                if not matches:
                    raise RuntimeError(
                        "Play Sound unit source found no live unit matching "
                        "sound_player/sound_unit/sound_location"
                    )
                sound_unit = matches[0]
                x, y = sound_unit.x, sound_unit.y
                source_detail = (
                    f"P{sound_unit.owner + 1} {UNIT_NAMES[sound_unit.unit_type]} "
                    f"slot {(sound_unit.address-self.unit_pool)//UNIT_SIZE}"
                )
            elif source in {"location", "point", "tile"}:
                x, y = self._spell_destination(args, "Play Sound")
            else:
                raise ValueError("Play Sound source must be Location or Unit")
            if not (0 <= x < self.map_width and 0 <= y < self.map_height):
                raise ValueError(f"Play Sound location ({x},{y}) is outside the live map")
            # gamesnd_spellxy accepts pixel coordinates and a zero-based index
            # into Warcraft's contiguous spell-sound bank. Use the center of the
            # selected tile so its own matrix visibility/attenuation path decides
            # whether and how loudly the local client should hear the sound.
            pixel_x = (x << 5) + 16
            pixel_y = (y << 5) + 16
            self._call_cdecl(
                self.spell_path["vision_sound"],
                [pixel_x, pixel_y, sound_id],
            )
            self.log(
                f"PLAY SOUND: {SPELL_SOUND_NAMES[sound_id]} relative ID {sound_id}, "
                f"native ID {sound_id + 69}, at ({x},{y}) from {source_detail}; Warcraft "
                "gamesnd_spellxy performed positional playback"
            )
            return
        if kind == "Cast Spell":
            spell = str(args.get("spell", "Runes")).strip().casefold()
            if spell in {
                "rune", "runes", "rune trap", "exploding rune", "caster runes"
            }:
                points = self._spell_destinations(args, "Cast Spell: Runes", player)
                cast_with_unit = self._spell_casts_with_unit(args, spell)
                if cast_with_unit:
                    if len(points) != 1:
                        raise ValueError(
                            f"Cast Spell: Runes matched {len(points)} target points, but a "
                            "native caster has one order target. Set Maximum target points "
                            "to 1 or choose Caster-free effect."
                        )
                    x, y = points[0]
                    ordered = self._order_runes(args, player, x, y)
                    self.log(
                        f"Cast Spell: queued native Runes for {ordered} Ogre-Mage "
                        f"caster(s) at ({x},{y}); Warcraft owns 200-mana payment, "
                        "the center/north/east/south/west placements, 40-mana refund "
                        "per rejected Rune, positional sound, native trap damage, "
                        "and cleanup"
                    )
                    return
                if len(points) == 1:
                    x, y = points[0]
                    slot, _delay, visual = self._cast_rune_without_unit(x, y)
                    rune_slots = [slot]
                    visual_slots = [(visual.address - self.bullet_pool) // BULLET_SIZE]
                else:
                    rune_slots, visual_slots = self._cast_runes_many_without_unit(points)
                self.log(
                    f"Cast Spell: Warcraft place_a_rune accepted {len(points)} "
                    f"caster-free Rune(s) at matching/current tiles; rune slots "
                    f"{','.join(str(value) for value in rune_slots)}, visual slots "
                    f"{','.join(str(value) for value in visual_slots)}; native "
                    "visibility, trigger detection, explosion sound, 50 damage, and cleanup are active"
                )
                return
            if spell in {"holy vision", "vision", "holyvision", "caster holy vision"}:
                owner = int(args.get("player", player))
                points = self._spell_destinations(args, "Cast Spell: Holy Vision", player)
                duration = self._holy_vision_duration(args.get("duration", "Vanilla"))
                cast_with_unit = self._spell_casts_with_unit(args, spell)
                if cast_with_unit:
                    if len(points) != 1:
                        raise ValueError(
                            f"Cast Spell: Holy Vision matched {len(points)} target points, "
                            "but a native caster has one order target. Set Maximum target "
                            "points to 1 or choose Caster-free effect."
                        )
                    if duration:
                        raise ValueError(
                            "Caster Holy Vision uses Warcraft's vanilla one-pulse duration; "
                            "use caster-free Holy Vision for an extended numeric duration"
                        )
                    x, y = points[0]
                    ordered = self._order_vision(args, player, x, y)
                    caster_owner = int(
                        args.get("caster_player", args.get("player", player))
                    )
                    self.log(
                        f"Cast Spell: queued native Holy Vision for {ordered} P"
                        f"{caster_owner + 1} Paladin caster(s) at ({x},{y}); Warcraft "
                        "owns 70-mana payment, Guard transition, seven source reveal "
                        "pulses, Sparkles, positional sounds, local camera movement, "
                        "and normal fog rebuilding"
                    )
                    return
                if len(points) == 1:
                    x, y = points[0]
                    regions, visuals, centered = self._cast_holy_vision_without_unit(
                        owner, x, y, duration
                    )
                    total_regions = len(regions)
                    visual_count = len(visuals)
                    centered_count = int(centered)
                else:
                    total_regions, visual_count, centered = (
                        self._cast_holy_vision_many_without_unit(owner, points, duration)
                    )
                    centered_count = int(centered)
                visibility = (
                    f"extended visibility {duration:g}s"
                    if duration
                    else "vanilla one-pulse visibility"
                )
                self.log(
                    f"Cast Spell: Warcraft completed caster-free Holy Vision for "
                    f"P{owner + 1} at {len(points)} unique target tile(s); "
                    f"{total_regions} source-matched 19x19 reveals, "
                    f"{visual_count} Sparkle bullets, camera centered "
                    f"{centered_count} time(s); {visibility}"
                )
                return
            if spell in {"blizzard", "ice storm", "icestorm"}:
                x, y = self._single_spell_destination(args, "Cast Spell: Blizzard", player)
                if not (0 <= x < self.map_width and 0 <= y < self.map_height):
                    raise ValueError(f"Blizzard destination ({x},{y}) is outside the live map")
                ordered = self._order_blizzard(args, player, x, y)
                self.log(
                    f"Cast Spell: queued native Blizzard for {ordered} Mage caster(s) "
                    f"at ({x},{y}); Warcraft owns movement, mana, cast animation, "
                    "five shard chains, area damage, sound, scoring, and cleanup"
                )
                return
            if spell in {"fireball", "fire ball"}:
                x, y = self._single_spell_destination(args, "Cast Spell: Fireball", player)
                if not (0 <= x < self.map_width and 0 <= y < self.map_height):
                    raise ValueError(f"Fireball destination ({x},{y}) is outside the live map")
                ordered = self._order_fireball(args, player, x, y)
                self.log(
                    f"Cast Spell: queued native Fireball for {ordered} Mage caster(s) "
                    f"at ({x},{y}); Warcraft owns movement, 100-mana payment, cast "
                    "animation, projectile flight, line damage, sound, scoring, and cleanup"
                )
                return
            if spell == "slow":
                ordered = self._order_slow(args, player)
                self.log(
                    f"Cast Spell: queued native Slow for {ordered} Mage caster(s); "
                    "Warcraft owns target pursuit, 50-mana payment, cast animation, "
                    "the -1000 speed timer, Sparkle, sound, and expiration"
                )
                return
            if spell in {"flame shield", "flameshield", "fire shield", "fireshield"}:
                ordered = self._order_flame_shield(args, player)
                self.log(
                    f"Cast Spell: queued native Flame Shield for {ordered} Mage caster(s); "
                    "Warcraft owns target pursuit, 80-mana payment, cast animation, "
                    "the 500-tick fire timer, traveling shield, five orbiting flames, "
                    "area damage, sound, scoring, and expiration"
                )
                return
            if spell in {"invisibility", "invisible", "invis"}:
                ordered = self._order_invisibility(args, player)
                self.log(
                    f"Cast Spell: queued native Invisibility for {ordered} Mage caster(s); "
                    "Warcraft owns target pursuit, 200-mana payment, cast animation, "
                    "the 2000-tick invisibility timer, Sparkle, sound, visibility "
                    "rules, reveal-on-attack behavior, and expiration"
                )
                return
            if spell in {"polymorph", "poly", "sheep"}:
                ordered = self._order_polymorph(args, player)
                self.log(
                    f"Cast Spell: queued native Polymorph for {ordered} Mage caster(s); "
                    "Warcraft owns target pursuit, 200-mana payment, cast animation, "
                    "unit_kill and hidden-target lifecycle, neutral Critter creation, "
                    "Sparkle, Morph sound, death/creation events, and cleanup"
                )
                return
            if spell in {"eye of kilrogg", "eye of kilrog", "eye", "kilrogg", "kilrog"}:
                ordered = self._order_eye(args, player)
                self.log(
                    f"Cast Spell: queued native Eye of Kilrogg for {ordered} "
                    "Ogre-Mage caster(s); Warcraft owns 70-mana payment, Guard "
                    "transition, unit_create_place placement, Eye ownership, spell "
                    "sound, unit bookkeeping, and cleanup"
                )
                return
            if spell in {"bloodlust", "blood lust", "lust"}:
                ordered = self._order_bloodlust(args, player)
                self.log(
                    f"Cast Spell: queued native Bloodlust for {ordered} Ogre-Mage "
                    "caster(s); Warcraft owns fleshy-target validation, pursuit, "
                    "60-mana payment, the Remastered 750-tick rage timer, Sparkle, "
                    "sound, combat bonuses, and expiration"
                )
                return
            if spell in {"heal", "healing"}:
                ordered = self._order_heal(args, player)
                self.log(
                    f"Cast Spell: queued native Healing for {ordered} Paladin caster(s); "
                    "Warcraft owns target pursuit, variable 5-mana-per-HP payment, "
                    "the 40-HP-per-cast cap, HP restoration, Heal visual, sound, and cleanup"
                )
                return
            if spell in {"exorcism", "exorcise"}:
                x, y = self._single_spell_destination(args, "Cast Spell: Exorcism", player)
                if not (0 <= x < self.map_width and 0 <= y < self.map_height):
                    raise ValueError(f"Exorcism destination ({x},{y}) is outside the live map")
                ordered = self._order_exorcism(args, player, x, y)
                self.log(
                    f"Cast Spell: queued native Exorcism for {ordered} Paladin caster(s) "
                    f"at ({x},{y}); Warcraft owns pursuit, the radius-{EXORCISM_RADIUS} "
                    "undead scan, variable 4-mana-per-damage payment, Exorcism visuals, "
                    "sound, engine damage, deaths, scoring, and cleanup"
                )
                return
            if spell in {"raise dead", "raisedead", "raise"}:
                x, y = self._single_spell_destination(args, "Cast Spell: Raise Dead", player)
                if not (0 <= x < self.map_width and 0 <= y < self.map_height):
                    raise ValueError(f"Raise Dead destination ({x},{y}) is outside the live map")
                ordered = self._order_raisedead(args, player, x, y)
                self.log(
                    f"Cast Spell: queued native Raise Dead for {ordered} Death Knight "
                    f"caster(s) at ({x},{y}); Warcraft owns the radius-{RAISEDEAD_RADIUS} "
                    "corpse scan, 50-mana payment per corpse, native Skeleton creation, "
                    "corpse hiding, Sparkle, Thunder sound, bookkeeping, and cleanup"
                )
                return
            if spell in {"death coil", "deathcoil", "drain life", "drainlife"}:
                x, y = self._single_spell_destination(args, "Cast Spell: Death Coil", player)
                if not (0 <= x < self.map_width and 0 <= y < self.map_height):
                    raise ValueError(f"Death Coil destination ({x},{y}) is outside the live map")
                ordered = self._order_drainlife(args, player, x, y)
                self.log(
                    f"Cast Spell: queued native Death Coil for {ordered} Death Knight caster(s) "
                    f"at ({x},{y}); Warcraft owns pursuit, the 5x5 enemy-fleshy scan, "
                    "100-mana payment, lowest-HP selection up to 50 life, projectile "
                    "damage, caster healing, sound, deaths, scoring, and cleanup"
                )
                return
            if spell in {"whirlwind", "whirl wind", "typhoon"}:
                x, y = self._single_spell_destination(args, "Cast Spell: Whirlwind", player)
                if not (0 <= x < self.map_width and 0 <= y < self.map_height):
                    raise ValueError(
                        f"Whirlwind destination ({x},{y}) is outside the live map"
                    )
                ordered = self._order_whirlwind(args, player, x, y)
                self.log(
                    f"Cast Spell: queued native Whirlwind for {ordered} Death Knight "
                    f"caster(s) at ({x},{y}); Warcraft owns 100-mana payment, cast "
                    "animation, one Typhoon projectile, randomized motion, repeated "
                    "native 4-damage hits, sound, scoring, and cleanup"
                )
                return
            if spell in {
                "death and decay", "death & decay", "death decay", "decay", "rot"
            }:
                x, y = self._single_spell_destination(args, "Cast Spell: Death and Decay", player)
                if not (0 <= x < self.map_width and 0 <= y < self.map_height):
                    raise ValueError(
                        f"Death and Decay destination ({x},{y}) is outside the live map"
                    )
                ordered = self._order_rot(args, player, x, y)
                self.log(
                    f"Cast Spell: queued native Death and Decay for {ordered} Death "
                    f"Knight caster(s) at ({x},{y}); Warcraft owns repeated "
                    f"{self.spell_path['rot_cost']}-mana waves, five Rot projectiles "
                    f"per wave, {ROT_TIMES}-tick effects, native 10-damage hits, "
                    "sound, scoring, and cleanup until mana is exhausted"
                )
                return
            if spell in {"haste", "speed"}:
                ordered = self._order_haste(args, player)
                self.log(
                    f"Cast Spell: queued native Haste for {ordered} Death Knight caster(s); "
                    "Warcraft owns target pursuit, 50-mana payment, cast animation, "
                    "the signed +1000 speed-timer operation, Sparkle, sound, and expiration"
                )
                return
            if spell in {"unholy armor", "unholy armour", "unholyarmor", "armor", "armour"}:
                ordered = self._order_armor(args, player)
                self.log(
                    f"Cast Spell: queued native Unholy Armor for {ordered} "
                    "Death Knight caster(s); Warcraft owns target pursuit, 100-mana "
                    "payment, the 500-tick invulnerability timer, native HP halving, "
                    "Sparkle, sound, damage immunity, and expiration"
                )
                return
            raise RuntimeError(
                "Cast Spell supports Runes, Holy Vision, Mage-cast Blizzard, and "
                "Mage-cast Fireball, Slow, Flame Shield, Invisibility, and Polymorph, "
                "Ogre-Mage-cast Eye of Kilrogg and Bloodlust, Paladin-cast Healing "
                "and Exorcism, plus "
                "Death Knight-cast Raise Dead, Death Coil, Whirlwind, Death and "
                "Decay, Haste, and Unholy Armor; "
                f"unsupported spell: {args.get('spell', 'Runes')}"
            )
        if kind in {"Create Units", "Create Completed Buildings"}:
            instant_building = kind == "Create Completed Buildings"
            owner = self._resolve_player_value(args.get("player", player), player)
            unit_type = int(args.get("unit", 0))
            if str(args.get("amount_mode", "Fixed amount")) == "Per matching building":
                count_owner=int(args.get("count_player", owner))
                count_type=args.get("count_building", "Any")
                count_location=args.get("count_location", "Anywhere")
                matching=sum(1 for unit in self._selected_units({"player": count_owner, "unit": "Any", "location": count_location}, player) if FIRST_BUILDING_TYPE <= unit.unit_type <= LAST_BUILDING_TYPE and bool(unit.sflags & 0x0080) and (count_type == "Any" or int(count_type) == unit.unit_type))
                multiplier=max(0, int(args.get("units_per_building", 2)))
                amount=max(0, min(64, matching * multiplier))
                self.log(f"CREATE SCALE: {matching} matching building(s) x {multiplier} = {amount} requested unit(s)")
                if amount == 0:
                    return
            else:
                amount = max(1, min(64, int(args.get("amount", 1))))
            if not 0 <= owner <= 15:
                raise ValueError(f"Invalid owner for {kind}: {owner}")
            if instant_building and unit_type not in CREATE_BUILDING_TYPES:
                raise RuntimeError("Create Completed Buildings requires a validated standard land-building ID")
            if not (0 <= unit_type < FIRST_BUILDING_TYPE or unit_type in CREATE_BUILDING_TYPES):
                raise RuntimeError(
                    "Create Units enables mobile IDs 0-57 and validated standard land buildings; "
                    f"unit ID {unit_type} requires a specialized creation path"
                )
            location_name = args.get("location", "Anywhere")
            if location_name != "Anywhere":
                if not self.scenario:
                    raise RuntimeError("Create Units location requires an active scenario")
                location = next((item for item in self.scenario.locations if item.name == location_name), None)
                if not location:
                    raise ValueError(f"Unknown location: {location_name}")
                x = (location.left + location.right) // 2
                y = (location.top + location.bottom) // 2
            else:
                if "x" not in args or "y" not in args:
                    raise ValueError("Create Units at Anywhere requires tile coordinates x and y")
                x, y = int(args["x"]), int(args["y"])
            created: list[Unit] = []
            for _ in range(amount):
                unit = self._create_unit(owner, unit_type, x, y)
                if not unit:
                    break
                if unit_type in CREATE_BUILDING_TYPES:
                    # During a live match, source unit_create must return a real
                    # construction foundation, not a completed/header-loaded
                    # structure. Warcraft's update_bldgs/grow_structure path owns
                    # all subsequent progress, HP growth, animation, and completion.
                    if unit.sflags & 0x0080 or not (unit.sflags & 0x0100):
                        raise RuntimeError(
                            f"unit_create did not start the expected building lifecycle for "
                            f"{UNIT_NAMES[unit_type]} (sFlags=0x{unit.sflags:04X})"
                        )
                label = "FOUNDATION" if unit_type in CREATE_BUILDING_TYPES else "CREATED"
                self.log(
                    f"{label}: P{owner + 1} {UNIT_NAMES[unit_type]} slot "
                    f"{(unit.address-self.unit_pool)//UNIT_SIZE} at ({unit.x},{unit.y}) "
                    f"HP {unit.health} flags 0x{unit.sflags:04X}"
                )
                if instant_building:
                    unit = self._complete_building(unit)
                    self.log(
                        f"COMPLETED BUILDING: P{owner + 1} {UNIT_NAMES[unit_type]} slot "
                        f"{(unit.address-self.unit_pool)//UNIT_SIZE} at ({unit.x},{unit.y}) "
                        f"HP {unit.health} flags 0x{unit.sflags:04X}"
                    )
                created.append(unit)
            if len(created) != amount:
                raise RuntimeError(f"unit_create placed {len(created)} of {amount} requested unit(s) near ({x},{y})")
            if instant_building:
                self.log(
                    f"Create Completed Buildings: Warcraft grow_structure completed "
                    f"{len(created)} building(s) through native construction bookkeeping"
                )
            elif unit_type in CREATE_BUILDING_TYPES:
                self.log(
                    f"Create Units: Warcraft unit_create placed {len(created)} construction foundation(s); "
                    "native grow_structure lifecycle started"
                )
            else:
                self.log(f"Create Units: Warcraft unit_create placed {len(created)} unit(s)")
            return
        if kind == "Remove Units":
            units = self._selected_units(args, player)
            amount_arg = args.get("amount", "All")
            if amount_arg != "All":
                units = units[:max(0, min(1600, int(amount_arg)))]
            unsupported = [unit for unit in units if unit.unit_type not in REMOVE_LAND_UNIT_TYPES]
            hidden = [unit for unit in units if unit.sflags & 0x0008]
            if unsupported:
                names = ", ".join(sorted({UNIT_NAMES[unit.unit_type] for unit in unsupported}))
                raise RuntimeError(f"Remove Units currently validates visible land/mobile units only; unsupported: {names}")
            if hidden:
                raise RuntimeError("Remove Units will not free hidden/cargo units until container cleanup is validated")
            removed = 0
            failed: list[str] = []
            for unit in units:
                key = self._unit_key(unit)
                calls = [
                    (self.remove_callees["cancel_tree_harvest"], [unit.address]),
                    (self.remove_callees["unplace_man"], [unit.address]),
                    (self.remove_callees["deselect_unit"], [unit.address]),
                    (self.remove_callees["strategy_alert_kill"], [unit.address]),
                    (self.remove_callees["count_remove"], [unit.address]),
                    (self.unit_free_address, [unit.address]),
                ]
                self._call_cdecl_sequence(calls)
                after = self.pm.read_ushort(unit.address + 0x1E)
                if not after & 0x0001:
                    failed.append(
                        f"{UNIT_NAMES[unit.unit_type]} slot {(unit.address-self.unit_pool)//UNIT_SIZE} "
                        f"flags 0x{unit.sflags:04X}->0x{after:04X}"
                    )
                    continue
                self._pending_removed_keys.add(key)
                removed += 1
                self.log(
                    f"REMOVED: P{unit.owner + 1} {UNIT_NAMES[unit.unit_type]} "
                    f"slot {(unit.address-self.unit_pool)//UNIT_SIZE} flags 0x{unit.sflags:04X}->0x{after:04X}"
                )
            if failed:
                raise RuntimeError("Silent unit removal was rejected for: " + "; ".join(failed))
            self.log(f"Remove Units: silently unplaced and freed {removed} unit(s)")
            return
        if kind == "Move Units":
            units = self._selected_units(args, player)
            amount_arg = args.get("amount", "All")
            if amount_arg != "All":
                units = units[:max(0, min(1600, int(amount_arg)))]
            unsupported = [unit for unit in units if unit.unit_type not in REMOVE_LAND_UNIT_TYPES]
            hidden = [unit for unit in units if unit.sflags & 0x0008]
            if unsupported:
                names = ", ".join(sorted({UNIT_NAMES[unit.unit_type] for unit in unsupported}))
                raise RuntimeError(f"Move Units currently validates visible land/mobile units only; unsupported: {names}")
            if hidden:
                raise RuntimeError("Move Units will not relocate hidden/cargo units")
            x, y = self._tile_destination(args, "Move Units")
            if not (0 <= x < self.map_width and 0 <= y < self.map_height):
                raise ValueError(f"Move Units destination ({x},{y}) is outside the live map")
            moved_count = 0
            failed: list[str] = []
            for unit in units:
                destination = self._find_move_place(unit, x, y)
                if destination is None:
                    failed.append(
                        f"{UNIT_NAMES[unit.unit_type]} slot {(unit.address-self.unit_pool)//UNIT_SIZE}: "
                        f"no valid tile near ({x},{y})"
                    )
                    continue
                px, py = destination
                moved = self._move_mobile_unit(unit, px, py)
                moved_count += 1
                self.log(
                    f"MOVED: P{unit.owner + 1} {UNIT_NAMES[unit.unit_type]} "
                    f"slot {(unit.address-self.unit_pool)//UNIT_SIZE} "
                    f"({unit.x},{unit.y})->({moved.x},{moved.y}) action {moved.action}/{moved.next_action}"
                )
            if failed:
                raise RuntimeError("Move Units could not place all selected units: " + "; ".join(failed))
            self.log(
                f"Move Units: Warcraft matrix unplace/place moved {moved_count} unit(s) "
                f"near ({x},{y})"
            )
            return
        if kind == "Order":
            order = str(args.get("order", "Move")).strip().title()
            if order not in {"Move", "Attack", "Patrol"}:
                raise RuntimeError(f"Order currently validates Move, Attack, and Patrol only; unsupported order: {order}")
            units = self._selected_units(args, player)
            amount_arg = args.get("amount", "All")
            if amount_arg != "All":
                units = units[:max(0, min(1600, int(amount_arg)))]
            unsupported = [unit for unit in units if unit.unit_type not in REMOVE_LAND_UNIT_TYPES]
            hidden = [unit for unit in units if unit.sflags & 0x0008]
            if unsupported:
                names = ", ".join(sorted({UNIT_NAMES[unit.unit_type] for unit in unsupported}))
                raise RuntimeError(f"{order} Order currently validates visible land/mobile units only; unsupported: {names}")
            if hidden:
                raise RuntimeError(f"{order} Order will not command hidden/cargo units")

            reissue = bool(args.get("reissue", False))
            unchanged = 0
            disappeared = 0

            # Warcraft's normal Attack command is an attack-move to a map tile.
            # The engine owns enemy acquisition along the route; triggers do not
            # choose or repeatedly replace a target player/unit. Legacy target-mode
            # fields are intentionally ignored for backward compatibility.

            x, y = self._tile_destination(args, f"{order} Order")
            if not (0 <= x < self.map_width and 0 <= y < self.map_height):
                raise ValueError(f"{order} Order destination ({x},{y}) is outside the live map")
            if order == "Attack":
                for unit in units:
                    self._attack_routes[self._unit_key(unit)] = (x, y)
            else:
                for unit in units:
                    self._attack_routes.pop(self._unit_key(unit), None)
            callback_name = {
                "Move": "do_move",
                "Patrol": "do_patrol",
                "Attack": "do_attack",
            }[order]
            expected_actions = {
                "Move": {3},
                "Patrol": {4, 5, 12},
                "Attack": {10, 11},
            }[order]
            signature = (("AttackLocation" if order == "Attack" else order), x, y)
            to_order: list[Unit] = []
            encounter_orders: list[tuple[Unit, Unit]] = []
            arrived = 0
            settled = 0
            retained_patrol = 0
            retained_combat = 0
            pool_end = self.unit_pool + self.max_units * UNIT_SIZE
            relation_rows: dict[int, list[int]] = {}
            world_units = self.units() if order == "Attack" else []
            encounter_radius_sq = 8 * 8
            for unit in units:
                if order == "Move" and (unit.x, unit.y) == (x, y):
                    self._issued_orders[self._unit_key(unit)] = signature
                    arrived += 1
                    continue
                still_active = (
                    unit.action in expected_actions
                    or unit.next_action in expected_actions
                    or (order == "Move" and bool(unit.sflags & 0x4000))
                )
                settled_at_target = (
                    order == "Move"
                    and unit.target_unit == 0
                    and (unit.target_x, unit.target_y) == (x, y)
                    and unit.action == 2
                    and unit.next_action == 60
                )
                patrol_route_retained = (
                    order == "Patrol"
                    and unit.target_unit == 0
                    and (
                        still_active
                        or (
                            (unit.target_x, unit.target_y) == (x, y)
                            and unit.action in {2, 4, 5, 12}
                            and unit.next_action in {4, 5, 12, 60}
                        )
                    )
                )
                attack_location_settled = (
                    order == "Attack"
                    and unit.target_unit == 0
                    and (unit.target_x, unit.target_y) == (x, y)
                    and unit.action == 2
                    and unit.next_action == 60
                )
                attack_point_retained = (
                    order == "Attack"
                    and unit.target_unit == 0
                    and (unit.target_x, unit.target_y) == (x, y)
                    and (still_active or attack_location_settled)
                )
                # Never overwrite a live enemy combat target with a repeated
                # attack-location route. The route resumes after Warcraft clears
                # the dead/lost target. Older TD projects commonly saved
                # reissue=true, which otherwise reset combat every second and
                # made opposing units run through one another without fighting.
                enemy_combat_retained = False
                if order == "Attack" and unit.target_unit:
                    target_address = int(unit.target_unit)
                    if (
                        self.unit_pool <= target_address < pool_end
                        and (target_address - self.unit_pool) % UNIT_SIZE == 0
                    ):
                        try:
                            target_data = self.pm.read_bytes(target_address, UNIT_SIZE)
                        except Exception:
                            target_data = b""
                        if target_data and self._record_is_allocated(target_data):
                            target_owner = int(target_data[0x2C])
                            if 0 <= unit.owner < 8 and 0 <= target_owner < 8:
                                row = relation_rows.get(unit.owner)
                                if row is None:
                                    row = self._read_diplomacy_state(unit.owner)[0]
                                    relation_rows[unit.owner] = row
                                enemy_combat_retained = (
                                    self._relation_is_enemy(unit.owner, target_owner, row[target_owner])
                                    and (
                                        unit.action in {8, 9, 10, 11, 12}
                                        or unit.next_action in {8, 9, 10, 11, 12}
                                    )
                                )
                if enemy_combat_retained:
                    unchanged += 1
                    retained_combat += 1
                    continue

                # Empty slots have no persistent strategy controller. Keep the
                # trigger generic (destination only), but when an enemy enters a
                # normal encounter radius, pass that live record to Warcraft's
                # native targeted Attack path. After the target dies, the preserved
                # trigger resumes the original destination route on its next run.
                if (
                    order == "Attack"
                    and 0 <= int(unit.owner) < 8
                    and self._owner_type(int(unit.owner)) == C_NONE
                    and not unit.target_unit
                ):
                    row = relation_rows.get(int(unit.owner))
                    if row is None:
                        row = self._read_diplomacy_state(int(unit.owner))[0]
                        relation_rows[int(unit.owner)] = row
                    candidates: list[tuple[int, int, Unit]] = []
                    for candidate in world_units:
                        if candidate.address == unit.address or candidate.sflags & 0x0008:
                            continue
                        if not (0 <= int(candidate.owner) < 8):
                            continue
                        if not self._relation_is_enemy(
                            int(unit.owner), int(candidate.owner), row[int(candidate.owner)]
                        ):
                            continue
                        dx = int(candidate.x) - int(unit.x)
                        dy = int(candidate.y) - int(unit.y)
                        distance_sq = dx * dx + dy * dy
                        if distance_sq <= encounter_radius_sq:
                            candidates.append((distance_sq, candidate.address, candidate))
                    if candidates:
                        _distance, _address, target = min(candidates, key=lambda item: (item[0], item[1]))
                        encounter_orders.append((unit, target))
                        continue

                move_retaliating = order == "Move" and bool(unit.target_unit)
                if not reissue and self._issued_orders.get(self._unit_key(unit)) == signature:
                    if (still_active or settled_at_target or patrol_route_retained or attack_point_retained) and not move_retaliating:
                        unchanged += 1
                        if settled_at_target or attack_location_settled:
                            settled += 1
                        if patrol_route_retained:
                            retained_patrol += 1
                        continue
                if move_retaliating:
                    self.log(
                        f"MOVE WATCHDOG: P{unit.owner + 1} {UNIT_NAMES[unit.unit_type]} "
                        f"slot {(unit.address-self.unit_pool)//UNIT_SIZE} acquired target "
                        f"0x{int(unit.target_unit):08X}; restoring route destination ({x},{y})"
                    )
                to_order.append(unit)

            self._call_cdecl_batched([
                (
                    self.order_callees["set_target"],
                    [unit.address, x, y, 0, self.order_callees[callback_name]],
                )
                for unit in to_order
            ])

            if encounter_orders:
                self._call_cdecl_batched([
                    (
                        self.order_callees["set_target"],
                        [
                            unit.address,
                            int(target.x),
                            int(target.y),
                            target.address,
                            self.order_callees["do_attack"],
                        ],
                    )
                    for unit, target in encounter_orders
                ])
                for unit, target in encounter_orders:
                    data = self.pm.read_bytes(unit.address, UNIT_SIZE)
                    if not self._record_is_allocated(data):
                        continue
                    current = self._decode_unit(unit.address, data)
                    if current.target_unit == target.address and (
                        current.action in {8, 9, 10, 11, 12}
                        or current.next_action in {8, 9, 10, 11, 12}
                    ):
                        self._issued_orders[self._unit_key(current)] = signature
                        retained_combat += 1
                        self.log(
                            f"ATTACK ENCOUNTER: P{unit.owner + 1} {UNIT_NAMES[unit.unit_type]} "
                            f"slot {(unit.address-self.unit_pool)//UNIT_SIZE} acquired nearest enemy "
                            f"P{target.owner + 1} {UNIT_NAMES[target.unit_type]} at "
                            f"({target.x},{target.y}); route destination remains ({x},{y})"
                        )
                    else:
                        self.log(
                            f"ORDER WARNING: Warcraft rejected automatic encounter target for "
                            f"P{unit.owner + 1} {UNIT_NAMES[unit.unit_type]} slot "
                            f"{(unit.address-self.unit_pool)//UNIT_SIZE}; destination route remains active"
                        )

            ordered = 0
            rejected: list[str] = []
            for unit in to_order:
                data = self.pm.read_bytes(unit.address, UNIT_SIZE)
                if not self._record_is_allocated(data):
                    self._issued_orders.pop(self._unit_key(unit), None)
                    disappeared += 1
                    continue
                current = self._decode_unit(unit.address, data)
                target_x = int.from_bytes(data[0x84:0x86], "little", signed=True)
                target_y = int.from_bytes(data[0x86:0x88], "little", signed=True)
                target_unit = int.from_bytes(data[0x88:0x8C], "little")
                saved_x = int.from_bytes(data[0x6C:0x6E], "little", signed=True)
                saved_y = int.from_bytes(data[0x6E:0x70], "little", signed=True)
                adjusted_in_bounds = 0 <= target_x < self.map_width and 0 <= target_y < self.map_height
                adjusted_toward_request = (
                    min(unit.x, x) <= target_x <= max(unit.x, x)
                    and min(unit.y, y) <= target_y <= max(unit.y, y)
                )
                makes_progress = (target_x, target_y) != (unit.x, unit.y) or (x, y) == (unit.x, unit.y)
                action_accepted = (
                    current.action in expected_actions
                    or current.next_action in expected_actions
                    or (order == "Move" and bool(current.sflags & 0x4000))
                )
                patrol_origin_accepted = order != "Patrol" or (saved_x, saved_y) == (unit.x, unit.y)
                attack_home_accepted = True
                reached_destination = (
                    order == "Move"
                    and target_unit == 0
                    and (current.x, current.y) == (x, y)
                )
                settled_at_destination = (
                    order == "Move"
                    and target_unit == 0
                    and (target_x, target_y) == (x, y)
                    and current.action == 2
                    and current.next_action == 60
                )
                attack_location_settled = (
                    order == "Attack"
                    and target_unit == 0
                    and (target_x, target_y) == (x, y)
                    and current.action == 2
                    and current.next_action == 60
                )
                accepted = (
                    reached_destination
                    or settled_at_destination
                    or (attack_location_settled and attack_home_accepted)
                    or (
                        target_unit == 0
                        and adjusted_in_bounds
                        and adjusted_toward_request
                        and makes_progress
                        and action_accepted
                        and patrol_origin_accepted
                        and attack_home_accepted
                    )
                )
                if not accepted:
                    origin_detail = (
                        f" origin ({saved_x},{saved_y})" if order == "Patrol"
                        else ""
                    )
                    rejected.append(
                        f"{UNIT_NAMES[unit.unit_type]} slot {(unit.address-self.unit_pool)//UNIT_SIZE} "
                        f"target ({target_x},{target_y}) ptr 0x{target_unit:08X} "
                        f"{origin_detail} action {current.action}/{current.next_action} "
                        f"flags 0x{current.sflags:04X}"
                    )
                    continue
                self._issued_orders[self._unit_key(current)] = signature
                origin_detail = (
                    f" origin ({saved_x},{saved_y})" if order == "Patrol"
                    else ""
                )
                if reached_destination:
                    arrived += 1
                    self.log(
                        f"MOVE ARRIVED: P{unit.owner + 1} {UNIT_NAMES[unit.unit_type]} "
                        f"slot {(unit.address-self.unit_pool)//UNIT_SIZE} at ({current.x},{current.y}); "
                        f"Warcraft returned to idle action {current.action}/{current.next_action}"
                    )
                    continue
                if settled_at_destination or attack_location_settled:
                    settled += 1
                    settled_label = "ATTACK LOCATION" if attack_location_settled else "MOVE"
                    self.log(
                        f"{settled_label} SETTLED: P{unit.owner + 1} {UNIT_NAMES[unit.unit_type]} "
                        f"slot {(unit.address-self.unit_pool)//UNIT_SIZE} at "
                        f"({current.x},{current.y}) for requested ({x},{y}); "
                        f"target retained ({target_x},{target_y}), idle action "
                        f"{current.action}/{current.next_action}"
                    )
                    continue
                ordered += 1
                label = "ATTACK LOCATION" if order == "Attack" else order.upper()
                self.log(
                    f"{label} ORDERED: P{unit.owner + 1} {UNIT_NAMES[unit.unit_type]} "
                    f"slot {(unit.address-self.unit_pool)//UNIT_SIZE} requested ({x},{y}), "
                    f"engine target ({target_x},{target_y}) "
                    f"{origin_detail} "
                    f"action {current.action}/{current.next_action} flags 0x{current.sflags:04X}"
                )
            if rejected:
                shown = rejected[:10]
                extra = len(rejected) - len(shown)
                detail = "; ".join(shown)
                if extra:
                    detail += f"; ... and {extra} more"
                self.log(
                    f"ORDER WARNING: Warcraft rejected {order} Order for: {detail}; "
                    "runtime continues"
                )
            order_label = "Attack Location" if order == "Attack" else order
            parts = [
                f"Order: Warcraft unit_set_target queued {order_label} for {ordered} unit(s) toward ({x},{y})"
            ]
            if arrived:
                parts.append(f"{arrived} already arrived")
            if settled:
                parts.append(f"{settled} settled at/near destination")
            if retained_patrol:
                parts.append(f"{retained_patrol} retained the same patrol route")
            if retained_combat:
                parts.append(f"{retained_combat} retained active enemy combat target(s)")
            if unchanged:
                parts.append(f"skipped {unchanged} unchanged order(s)")
            if disappeared:
                parts.append(f"skipped {disappeared} unit(s) that became inactive during the batch")
            self.log("; ".join(parts))
            return
        if kind == "Give Units":
            units = self._selected_units(args, player)
            new_owner = int(args.get("to_player", args.get("new_owner", player)))
            play_sound = bool(args.get("play_sound", True))
            if not 0 <= new_owner <= 15:
                raise ValueError(f"Invalid destination owner for Give Units: {new_owner}")
            amount_arg = args.get("amount", "All")
            if amount_arg != "All":
                units = units[:max(0, min(1600, int(amount_arg)))]
            units = [unit for unit in units if unit.owner != new_owner]
            given = 0
            failed: list[str] = []
            for unit in units:
                old_owner = unit.owner
                old_type = unit.unit_type
                self._call_cdecl(self.capture_unit_address, [unit.address, new_owner, int(play_sound)])
                data = self.pm.read_bytes(unit.address, UNIT_SIZE)
                if not self._record_is_allocated(data):
                    failed.append(
                        f"{UNIT_NAMES[old_type]} slot {(unit.address-self.unit_pool)//UNIT_SIZE} became inactive"
                    )
                    continue
                current = self._decode_unit(unit.address, data)
                if current.owner != new_owner:
                    failed.append(
                        f"{UNIT_NAMES[old_type]} slot {(unit.address-self.unit_pool)//UNIT_SIZE} "
                        f"owner P{old_owner + 1}->P{current.owner + 1}"
                    )
                    continue
                given += 1
                converted = ""
                if current.unit_type != old_type:
                    converted = f"; converted to {UNIT_NAMES[current.unit_type]}"
                self.log(
                    f"GIVEN: P{old_owner + 1}->P{new_owner + 1} {UNIT_NAMES[old_type]} "
                    f"slot {(unit.address-self.unit_pool)//UNIT_SIZE}{converted}"
                )
            if failed:
                raise RuntimeError("capture_unit was rejected for: " + "; ".join(failed))
            self.log(
                f"Give Units: Warcraft capture_unit transferred {given} unit(s) to P{new_owner + 1}; "
                f"capture sound {'enabled' if play_sound else 'disabled'}"
            )
            return
        if kind == "Kill Units":
            units = self._selected_units(args, player)

            # A one-tile kill location is commonly placed at the end of a Move
            # route. When that tile is crowded, Warcraft resolves additional
            # units on adjacent legal matrix cells, leaves their requested target
            # inside the location, and returns them to idle 2/60. Include only
            # units that this runtime actually ordered to that target, so a stale
            # unrelated target cannot cause an unexpected kill.
            include_settled = bool(args.get("include_settled_move_targets", True))
            location_name = args.get("location")
            if (
                include_settled
                and location_name
                and location_name != "Anywhere"
                and self.scenario
            ):
                location = next(
                    (item for item in self.scenario.locations if item.name == location_name),
                    None,
                )
                if not location:
                    raise ValueError(f"Unknown location: {location_name}")
                owner = int(args.get("player", player))
                unit_type = args.get("unit", "Any")
                selected_addresses = {unit.address for unit in units}
                for unit in self.units():
                    if unit.address in selected_addresses:
                        continue
                    if owner >= 0 and unit.owner != owner:
                        continue
                    if unit_type != "Any" and unit.unit_type != int(unit_type):
                        continue
                    issued = self._issued_orders.get(self._unit_key(unit))
                    settled_target = (
                        unit.target_unit == 0
                        and location.left <= unit.target_x <= location.right
                        and location.top <= unit.target_y <= location.bottom
                        and unit.action == 2
                        and unit.next_action == 60
                        and issued == ("Move", unit.target_x, unit.target_y)
                    )
                    if settled_target:
                        units.append(unit)
                        selected_addresses.add(unit.address)
            killable: list[Unit] = []
            for unit in units:
                before = self.pm.read_ushort(unit.address + 0x1E)
                if before & 0x0007:
                    continue
                killable.append(unit)

            # Keep large kill zones bounded so one simulation update is not
            # monopolized by an unlimited number of native callbacks.
            self._call_cdecl_batched([
                (self.damage_callees["unit_kill"], [unit.address])
                for unit in killable
            ])

            killed = 0
            failed: list[str] = []
            for unit in killable:
                before = unit.sflags
                after = self.pm.read_ushort(unit.address + 0x1E)
                action = self.pm.read_uchar(unit.address + 0x2E)
                if after & 0x0002:
                    self._issued_orders.pop(self._unit_key(unit), None)
                    killed += 1
                    self.log(
                        f"KILLED: P{unit.owner + 1} {UNIT_NAMES[unit.unit_type]} "
                        f"slot {(unit.address-self.unit_pool)//UNIT_SIZE} flags 0x{before:04X}->0x{after:04X} action {action}"
                    )
                else:
                    failed.append(
                        f"{UNIT_NAMES[unit.unit_type]} slot {(unit.address-self.unit_pool)//UNIT_SIZE} "
                        f"flags 0x{before:04X}->0x{after:04X} action {action}"
                    )
            if failed:
                raise RuntimeError("unit_kill was rejected for: " + "; ".join(failed))
            self.log(f"Kill Units: Warcraft unit_kill accepted {killed} unit(s)")
            return
        raise RuntimeError(f"Live action is locked pending dispatcher validation: {kind}")

    def player_mapping_report(self) -> list[str]:
        units = [unit for unit in self.units() if 0 <= unit.owner < 8]
        slot_to_color, color_to_slot, observed = self._live_player_color_mapping()
        local_player = int(self.pm.read_uchar(self.base + LOCAL_PLAYER_RVA))
        lines = [
            "LIVE PLAYER / COLOR / START-POSITION MAP",
            f"Local human slot: P{local_player + 1}",
            "Trigger P1-P8 means owner slots unless a diplomacy action uses Displayed colors / fixed order.",
            "Random starting locations change coordinates; displayed-color randomization can change which live slot is Red/Blue/etc.",
        ]
        for owner in range(8):
            owned = [unit for unit in units if unit.owner == owner]
            if owned:
                center_x = round(sum(unit.x for unit in owned) / len(owned))
                center_y = round(sum(unit.y for unit in owned) / len(owned))
                position = f"approx XY ({center_x},{center_y})"
            else:
                position = "no active units"
            color = slot_to_color[owner]
            confidence = "observed" if owner in observed else "inferred"
            lines.append(
                f"P{owner + 1}: {self._owner_type_name(self._owner_type(owner)):<8} "
                f"displayed {PLAYER_COLOR_NAMES[color]:<6} ({confidence}), "
                f"units {len(owned):3d}, {position}"
            )
        lines.append(
            "Fixed-color lookup: "
            + ", ".join(
                f"{PLAYER_COLOR_NAMES[color]}=P{color_to_slot[color] + 1}"
                for color in range(8)
            )
        )
        return lines

    def unit_report(self) -> list[str]:
        from collections import Counter
        units = sorted(self.units(), key=lambda u: (u.owner, u.unit_type, u.y, u.x, u.address))
        lines = [f"UNIT SNAPSHOT: {len(units)} active record(s)"]
        totals = Counter()
        for index, unit in enumerate(units, 1):
            name = UNIT_NAMES[unit.unit_type] if unit.unit_type < len(UNIT_NAMES) else f"Unknown {unit.unit_type}"
            totals[(unit.owner, name)] += 1
            slot = (unit.address - self.unit_pool) // UNIT_SIZE
            lines.append(
                f"{index:03d} Slot {slot:04d} 0x{unit.address:08X}  P{unit.owner + 1:<2} "
                f"ID {unit.unit_type:03d} {name:<22} "
                f"XY ({unit.x:3d},{unit.y:3d}) HP {unit.health:5d} MP {unit.mana:3d} "
                f"Action {unit.action:3d}/{unit.next_action:3d} Flags 0x{unit.sflags:04X}"
            )
        lines.append("SUMMARY BY PLAYER / TYPE")
        for (owner, name), count in sorted(totals.items()):
            lines.append(f"P{owner + 1:<2} {name:<22} x{count}")
        return lines

    def statistics_report(self) -> list[str]:
        lines = ["LIVE COMBAT STATISTICS"]
        for owner in range(16):
            stats = self._read_player_statistics(owner)
            lines.append(
                f"P{owner + 1:<2} "
                f"Kills {stats['Kills Men']:5d} men / {stats['Kills Buildings']:5d} buildings  "
                f"Deaths {stats['Deaths Men']:5d} men / {stats['Deaths Buildings']:5d} buildings  "
                f"Score {stats['Score']:10d}"
            )
        return lines
