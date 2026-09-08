from __future__ import annotations

from dataclasses import dataclass, replace
import json
from pathlib import Path
import re
import webbrowser
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable, Iterable

from trigger_model import Clause, Scenario
from feature_metadata import canonical_kind, cleanup_catalog, display_kind, multiplayer_note
from source_features_128 import SOURCE128_CONDITIONS, SOURCE128_ACTIONS, SOURCE128_SPELL_ACTIONS

SOURCE128_COST_SPELLS = tuple(SOURCE128_SPELL_ACTIONS)


CONDITIONS = [
    "Always", "Never", "Elapsed Time", "Counter", "Command", "Bring", "Building Count", "Unit Entered Location", "Building Completed",
    "Unit Created", "Unit Died", "Unit Removed", "Corpse Count", "Missile Count",
    "Rune Count", "Hit Points", "Mana", "Resources", "Kills", "Player Killed", "Deaths", "Score",
    "Switch", "Game State", "Unit Property",
]

ACTIONS = [
    "Display Text", "Game Message", "Player Chat", "Wait", "Set Switch", "Set Counter", "Add Counter", "Subtract Counter", "Damage Units", "Set Hit Points",
    "Set Mana", "Kill Units", "Set Unit Property", "Set Resources", "Add Resources",
    "Subtract Resources", "Award Kill Resources", "Create Units", "Create Completed Buildings", "Remove Units",
    "Move Units", "Give Units", "Order", "Create Missile", "Cast Spell", "Modify Tile",
    "Play Sound", "Run AI Script", "Set Game Speed", "Set Alliance", "Set Allied Victory", "Set Shared Vision", "Victory", "Defeat",
]

CONDITION_CATEGORIES = {
    "Logic & time": ("Always", "Never", "Elapsed Time", "Switch", "Counter", "Game State"),
    "Units & buildings": ("Command", "Bring", "Building Count", "Unit Entered Location", "Building Completed", "Unit Created", "Unit Died", "Unit Removed", "Corpse Count", "Hit Points", "Mana", "Unit Property"),
    "Combat & projectiles": ("Missile Count", "Rune Count", "Kills", "Player Killed", "Deaths", "Score"),
    "Economy": ("Resources",),
}

ACTION_CATEGORIES = {
    "Flow & messages": ("Display Text", "Game Message", "Player Chat", "Wait", "Set Switch", "Set Counter", "Add Counter", "Subtract Counter"),
    "Units & buildings": ("Create Units", "Create Completed Buildings", "Remove Units", "Move Units", "Give Units", "Order", "Damage Units", "Set Hit Points", "Set Mana", "Kill Units", "Set Unit Property"),
    "Economy": ("Set Resources", "Add Resources", "Subtract Resources", "Award Kill Resources"),
    "Spells, missiles & sound": ("Create Missile", "Cast Spell", "Play Sound"),
    "Map & AI": ("Modify Tile", "Run AI Script"),
    "Game control": ("Set Game Speed",),
    "Players & diplomacy": ("Set Alliance", "Set Shared Vision", "Set Allied Victory"),
    "Game result": ("Victory", "Defeat"),
}

# ---------------------------------------------------------------------------
# 1.24 Massive Trigger Edition additions. These extend the established lists
# instead of replacing the 1.23.38 surface, preserving old sidecars exactly.
CONDITIONS.extend([
    "Random Chance", "Countdown Timer", "Timer Expired", "Variable",
    "Player Status", "Player Has No Buildings", "Unit Health Percent",
    "Unit Order", "Unit Status", "Unit Left Location",
    "Unit Stayed In Location", "Location Empty", "Unit Damaged",
    "Unit Healed", "Unit Under Attack", "Switch Changed",
    "Counter Changed", "Variable Changed", "Trigger Enabled", "Location Exists",
    "Expression", "Unit Group Count", "Unit Group Empty", "Objective State", "Event Available",
    "Auto Spellcasting",
])
ACTIONS.extend([
    "Random Wait", "Toggle Switch", "Randomize Switch", "Copy Counter",
    "Multiply Counter", "Divide Counter", "Modulo Counter", "Clamp Counter",
    "Random Counter", "Set Variable", "Add Variable", "Subtract Variable",
    "Multiply Variable", "Divide Variable", "Modulo Variable", "Copy Variable",
    "Clamp Variable", "Random Variable", "Set Countdown Timer",
    "Start Countdown Timer", "Pause Countdown Timer", "Resume Countdown Timer",
    "Reset Countdown Timer", "Enable Trigger", "Disable Trigger",
    "Toggle Trigger", "Reset Trigger", "Run Trigger", "Stop Trigger Actions",
    "Stop Trigger Cycle", "Breakpoint", "Move Location", "Offset Location", "Resize Location",
    "Copy Location", "Randomize Location", "Follow Unit With Location",
    "Stop Following Location", "Replace Units", "Set Unit Facing",
    "Set Unit Health Percent", "Heal Units", "Apply Status Effect",
    "Clear Status Effects", "Make Invincible", "Make Vulnerable", "Complete Buildings", "Set Unit Color", "Center Camera", "Set Score", "Set Kills", "Set Deaths",
    "Set Objective", "Complete Objective", "Clear Objective",
    "Display Leaderboard", "Log State", "Assert", "Comment",
    "Create Wave", "Save Unit Group", "Add Units To Group", "Clear Unit Group",
    "Order Unit Group", "Set Unit Group Health Percent", "Move Location To Event Unit",
    "Create Units At Event", "Set Variable From Event", "Set Variable From Expression",
    "Set Counter From Expression", "Log Event Context",
    "Enable Auto Spellcasting", "Disable Auto Spellcasting", "Auto Cast Spells Now",
])
CONDITION_CATEGORIES.update({
    "Variables, timers & random": ("Random Chance", "Countdown Timer", "Timer Expired", "Variable", "Switch Changed", "Counter Changed", "Variable Changed"),
    "Player & trigger state": ("Player Status", "Player Has No Buildings", "Trigger Enabled", "Location Exists", "Objective State"),
    "Expressions, events & groups": ("Expression", "Unit Group Count", "Unit Group Empty", "Event Available"),
    "Automatic combat systems": ("Auto Spellcasting",),
    "Advanced unit events": ("Unit Health Percent", "Unit Order", "Unit Status", "Unit Left Location", "Unit Stayed In Location", "Location Empty", "Unit Damaged", "Unit Healed", "Unit Under Attack"),
})
ACTION_CATEGORIES.update({
    "Advanced flow & trigger control": ("Random Wait", "Enable Trigger", "Disable Trigger", "Toggle Trigger", "Reset Trigger", "Run Trigger", "Stop Trigger Actions", "Stop Trigger Cycle", "Breakpoint", "Comment"),
    "Switches, counters & variables": ("Toggle Switch", "Randomize Switch", "Copy Counter", "Multiply Counter", "Divide Counter", "Modulo Counter", "Clamp Counter", "Random Counter", "Set Variable", "Add Variable", "Subtract Variable", "Multiply Variable", "Divide Variable", "Modulo Variable", "Copy Variable", "Clamp Variable", "Random Variable"),
    "Countdown timers": ("Set Countdown Timer", "Start Countdown Timer", "Pause Countdown Timer", "Resume Countdown Timer", "Reset Countdown Timer"),
    "Dynamic locations": ("Move Location", "Offset Location", "Resize Location", "Copy Location", "Randomize Location", "Follow Unit With Location", "Stop Following Location"),
    "Advanced unit modification": ("Replace Units", "Set Unit Facing", "Set Unit Health Percent", "Heal Units", "Apply Status Effect", "Clear Status Effects", "Make Invincible", "Make Vulnerable", "Complete Buildings", "Set Unit Color", "Center Camera"),
    "Statistics, objectives & diagnostics": ("Set Score", "Set Kills", "Set Deaths", "Set Objective", "Complete Objective", "Clear Objective", "Display Leaderboard", "Log State", "Assert", "Log Event Context"),
    "Wave, event & unit-group power tools": ("Create Wave", "Save Unit Group", "Add Units To Group", "Clear Unit Group", "Order Unit Group", "Set Unit Group Health Percent", "Move Location To Event Unit", "Create Units At Event", "Set Variable From Event", "Set Variable From Expression", "Set Counter From Expression"),
    "Automatic spell combat": ("Enable Auto Spellcasting", "Disable Auto Spellcasting", "Auto Cast Spells Now"),
})


# ---------------------------------------------------------------------------
# 1.25 Ultimate Systems Edition: references, progression, combat systems,
# projectiles, tactical AI, wave/boss directors, economy, RPG and sappers.
CONDITIONS.extend([
    "Unit Reference Exists", "Unit Reference Alive", "Unit Reference Health",
    "Unit Reference Health Percent", "Unit Reference Mana", "Unit Reference Owner",
    "Unit Reference Type", "Unit Reference Order", "Unit Reference In Location",
    "Upgrade Level", "Spell Researched", "Spell Allowed", "Custom Effect Active",
    "Shield Amount", "Projectile Created", "Projectile Expired", "Wave Director State",
    "Wave Number", "Boss Phase", "Tactical AI Enabled", "Hero Level",
    "Hero Experience", "Inventory Item Count", "Quest State", "Force Member",
    "Active Player Count", "Sapper Count",
])
ACTIONS.extend([
    "Save Unit Reference", "Save Event Unit Reference", "Save Last Created Unit Reference",
    "Clear Unit Reference", "Order Unit Reference", "Teleport Unit Reference",
    "Give Unit Reference", "Set Unit Reference Health", "Set Unit Reference Mana",
    "Apply Effect To Unit Reference", "Kill Unit Reference",
    "Run Trigger For Each Unit In Group", "Run Trigger For Each Player",
    "Give Spell", "Remove Spell", "Give All Spells", "Remove All Spells",
    "Set Spell Allowed", "Set Upgrade Level", "Add Upgrade Level", "Give All Upgrades",
    "Clear All Upgrades", "Enable Advanced Unit Classes",
    "Create Sapper Assault", "Order Sappers Demolish", "Arm Sappers",
    "Apply Stun", "Apply Root", "Apply Silence", "Apply Fear", "Apply Taunt",
    "Apply Damage Over Time", "Apply Healing Over Time", "Add Shield",
    "Clear Custom Effects", "Set Lifesteal", "Set Critical Strike", "Set Evasion",
    "Set Reflect Damage", "Set Cleave", "Knockback Units", "Pull Units",
    "Redirect Projectiles", "Destroy Projectiles", "Duplicate Projectiles",
    "Enable Tactical AI", "Disable Tactical AI", "Start TD Stream Wave", "Stop TD Stream Wave", "Start TD Native HP Ladder", "Stop TD Native HP Ladder", "Start Wave Director",
    "Stop Wave Director", "Advance Wave Director", "Start Boss Controller",
    "Stop Boss Controller", "Transfer Resources", "Steal Resources", "Tax Player",
    "Start Periodic Income", "Stop Periodic Income", "Refill Resource Node",
    "Train Units Instantly At Buildings", "Register Hero", "Add Hero Experience",
    "Set Hero Level", "Give Inventory Item", "Remove Inventory Item", "Clear Inventory",
    "Set Quest", "Complete Quest", "Fail Quest", "Clear Quest", "Transmission",
    "Watch Expression", "Dump Unit References", "Dump Unit Group",
])
CONDITION_CATEGORIES.update({
    "Persistent unit references": (
        "Unit Reference Exists", "Unit Reference Alive", "Unit Reference Health",
        "Unit Reference Health Percent", "Unit Reference Mana", "Unit Reference Owner",
        "Unit Reference Type", "Unit Reference Order", "Unit Reference In Location",
    ),
    "Research & upgrades": ("Upgrade Level", "Spell Researched", "Spell Allowed"),
    "Custom combat & projectiles": (
        "Custom Effect Active", "Shield Amount", "Projectile Created", "Projectile Expired",
    ),
    "Directors, AI & RPG": (
        "Wave Director State", "Wave Number", "Boss Phase", "Tactical AI Enabled",
        "Hero Level", "Hero Experience", "Inventory Item Count", "Quest State",
    ),
    "Forces & special units": ("Force Member", "Active Player Count", "Sapper Count"),
})
ACTION_CATEGORIES.update({
    "Persistent unit references & loops": (
        "Save Unit Reference", "Save Event Unit Reference", "Save Last Created Unit Reference",
        "Clear Unit Reference", "Order Unit Reference", "Teleport Unit Reference",
        "Give Unit Reference", "Set Unit Reference Health", "Set Unit Reference Mana",
        "Apply Effect To Unit Reference", "Kill Unit Reference",
        "Run Trigger For Each Unit In Group", "Run Trigger For Each Player",
    ),
    "Native research & upgrade levels": (
        "Give Spell", "Remove Spell", "Give All Spells", "Remove All Spells",
        "Set Spell Allowed", "Set Upgrade Level", "Add Upgrade Level",
        "Give All Upgrades", "Clear All Upgrades", "Enable Advanced Unit Classes",
    ),
    "Sappers & demolition": ("Create Sapper Assault", "Order Sappers Demolish", "Arm Sappers"),
    "Advanced combat mechanics": (
        "Apply Stun", "Apply Root", "Apply Silence", "Apply Fear", "Apply Taunt",
        "Apply Damage Over Time", "Apply Healing Over Time", "Add Shield",
        "Clear Custom Effects", "Set Lifesteal", "Set Critical Strike", "Set Evasion",
        "Set Reflect Damage", "Set Cleave", "Knockback Units", "Pull Units",
    ),
    "Projectile control": ("Redirect Projectiles", "Destroy Projectiles", "Duplicate Projectiles"),
    "Tactical AI, waves & bosses": (
        "Enable Tactical AI", "Disable Tactical AI", "Start TD Stream Wave", "Stop TD Stream Wave", "Start TD Native HP Ladder", "Stop TD Native HP Ladder", "Start Wave Director",
        "Stop Wave Director", "Advance Wave Director", "Start Boss Controller", "Stop Boss Controller",
    ),
    "Economy & production systems": (
        "Transfer Resources", "Steal Resources", "Tax Player", "Start Periodic Income",
        "Stop Periodic Income", "Refill Resource Node", "Train Units Instantly At Buildings",
    ),
    "RPG, quests & cinematics": (
        "Register Hero", "Add Hero Experience", "Set Hero Level", "Give Inventory Item",
        "Remove Inventory Item", "Clear Inventory", "Set Quest", "Complete Quest",
        "Fail Quest", "Clear Quest", "Transmission",
    ),
    "Ultimate diagnostics": ("Watch Expression", "Dump Unit References", "Dump Unit Group"),
})

# ---------------------------------------------------------------------------
# 1.26 World Systems Edition: synchronous trigger functions, runtime lists,
# currencies/shops/equipment, hero attributes/skills, auras, squads,
# staged reinforcements, trigger cooldowns and trigger-driven votes.
CONDITIONS.extend([
    "Local Variable", "Function Depth", "List Length", "List Contains",
    "List Numeric Item", "Runtime Flag", "Trigger Cooldown Ready",
    "Custom Currency", "Shop Item Stock", "Inventory Capacity Remaining",
    "Item Equipped", "Hero Attribute", "Hero Skill Level", "Hero Skill Points",
    "Aura Enabled", "Unit In Aura", "Squad Controller State", "Squad Morale",
    "Reinforcement Director State", "Reinforcement Stage", "Vote State",
    "Vote Count", "Player Voted", "Unit Group Average Health Percent",
    "Unit Group Wounded Count", "Unit Group Near Location",
])
ACTIONS.extend([
    "Call Trigger Function", "Set Local Variable", "Copy Local To Variable",
    "Return From Function", "Create List", "Append To List", "Remove From List",
    "Set List Item", "Pop List To Variable", "Clear List", "Shuffle List",
    "Sort List", "Choose Random List Item", "Set Runtime Flag",
    "Clear Runtime Flag", "Toggle Runtime Flag", "Set Trigger Cooldown",
    "Clear Trigger Cooldown", "Set Custom Currency", "Add Custom Currency",
    "Subtract Custom Currency", "Register Shop Item", "Set Shop Stock",
    "Buy Shop Item", "Sell Inventory Item", "Equip Inventory Item",
    "Unequip Inventory Item", "Use Inventory Item", "Set Inventory Capacity",
    "Set Hero Attribute", "Add Hero Attribute", "Give Hero Skill Point",
    "Learn Hero Skill", "Reset Hero Skills", "Enable Aura", "Disable Aura",
    "Pulse Aura Now", "Start Squad Controller", "Stop Squad Controller",
    "Set Squad Destination", "Set Squad Formation", "Set Squad Morale",
    "Rally Squad", "Start Reinforcement Director", "Stop Reinforcement Director",
    "Advance Reinforcement Stage", "Start Vote", "Cast Vote", "Close Vote",
    "Reset Vote", "Dump World Systems",
])
CONDITION_CATEGORIES.update({
    "Functions, lists & runtime state": (
        "Local Variable", "Function Depth", "List Length", "List Contains",
        "List Numeric Item", "Runtime Flag", "Trigger Cooldown Ready",
    ),
    "Shops, equipment & hero builds": (
        "Custom Currency", "Shop Item Stock", "Inventory Capacity Remaining",
        "Item Equipped", "Hero Attribute", "Hero Skill Level", "Hero Skill Points",
    ),
    "Auras, squads & reinforcements": (
        "Aura Enabled", "Unit In Aura", "Squad Controller State", "Squad Morale",
        "Reinforcement Director State", "Reinforcement Stage",
        "Unit Group Average Health Percent", "Unit Group Wounded Count",
        "Unit Group Near Location",
    ),
    "Voting systems": ("Vote State", "Vote Count", "Player Voted"),
})
ACTION_CATEGORIES.update({
    "Trigger functions & local data": (
        "Call Trigger Function", "Set Local Variable", "Copy Local To Variable",
        "Return From Function", "Create List", "Append To List", "Remove From List",
        "Set List Item", "Pop List To Variable", "Clear List", "Shuffle List",
        "Sort List", "Choose Random List Item", "Set Runtime Flag",
        "Clear Runtime Flag", "Toggle Runtime Flag", "Set Trigger Cooldown",
        "Clear Trigger Cooldown",
    ),
    "Shops, equipment & hero development": (
        "Set Custom Currency", "Add Custom Currency", "Subtract Custom Currency",
        "Register Shop Item", "Set Shop Stock", "Buy Shop Item",
        "Sell Inventory Item", "Equip Inventory Item", "Unequip Inventory Item",
        "Use Inventory Item", "Set Inventory Capacity", "Set Hero Attribute",
        "Add Hero Attribute", "Give Hero Skill Point", "Learn Hero Skill",
        "Reset Hero Skills",
    ),
    "Auras, formations & staged armies": (
        "Enable Aura", "Disable Aura", "Pulse Aura Now", "Start Squad Controller",
        "Stop Squad Controller", "Set Squad Destination", "Set Squad Formation",
        "Set Squad Morale", "Rally Squad", "Start Reinforcement Director",
        "Stop Reinforcement Director", "Advance Reinforcement Stage",
    ),
    "Trigger-driven voting": ("Start Vote", "Cast Vote", "Close Vote", "Reset Vote"),
    "World-system diagnostics": ("Dump World Systems",),
})


# ---------------------------------------------------------------------------
# 1.27 Source Systems Edition: direct source-matched order callbacks,
# production, transports, workers, terrain, targeting, animation and effects.
CONDITIONS.extend([
    "Source Production State", "Source Production Progress",
    "Source Transport Cargo Count", "Source Transport Has Space",
    "Source Unit Is Loaded", "Source Worker Cargo Type",
    "Source Worker Cargo Amount", "Source Resource Node Remaining",
    "Source Tile Value", "Source Tile Is Tree", "Source Tile Is Rock",
    "Source Tile Is Wall", "Source Tile Is Demolishable",
    "Source Location Walkable", "Source Location Buildable",
    "Source Unit Has Target", "Source Unit Can Attack Target",
    "Source Target In Range", "Source Animation Action",
    "Source Animation Frozen", "Source Last Found X", "Source Last Found Y",
])
ACTIONS.extend([
    "Source Guard", "Source Follow", "Source Attack Target",
    "Source Attack Area", "Source Attack Ground", "Source Attack Wall",
    "Source Defend", "Source Defend Ground", "Source Defend Stopped",
    "Source Stand Attack", "Source Stand Ground", "Source Patrol Move",
    "Source Demolish", "Source Harvest", "Source Repair",
    "Source Return Resources", "Source Unload All",
    "Source Board Transport", "Source Unload Transport Unit",
    "Source Train Unit", "Source Research Technology",
    "Source Research Spell", "Source Upgrade Building",
    "Source Cancel Production", "Source Complete Production",
    "Source Set Production Progress", "Source Give Worker Cargo",
    "Source Clear Worker Cargo", "Source Deposit Worker Cargo",
    "Source Refill Resource Node", "Source Set Tiles",
    "Source Remove Trees", "Source Remove Rocks", "Source Place Walls",
    "Source Destroy Walls", "Source Damage Walls", "Source Kill Walls",
    "Source Find Walkable Point", "Source Find Buildable Point",
    "Source Acquire Best Target", "Source Reevaluate Target",
    "Source Clear Target", "Source Convert Unit Type",
    "Source Play Animation", "Source Freeze Animation",
    "Source Resume Animation", "Source Play Unit Sound",
    "Source Play Explosion Sound At Point", "Source Create Projectile At Point",
    "Source Create Projectile Between Units",
    "Source Attach Projectile To Unit", "Source Create Explosion Projectile",
    "Source Blizzard Volley", "Source Fire Shield Effect",
    "Source Whirlwind", "Source Raise Dead Effect",
])
CONDITION_CATEGORIES.update({
    "Source production & economy": (
        "Source Production State", "Source Production Progress",
        "Source Worker Cargo Type", "Source Worker Cargo Amount",
        "Source Resource Node Remaining",
    ),
    "Source transports & targeting": (
        "Source Transport Cargo Count", "Source Transport Has Space",
        "Source Unit Is Loaded", "Source Unit Has Target",
        "Source Unit Can Attack Target", "Source Target In Range",
    ),
    "Source terrain & placement": (
        "Source Tile Value", "Source Tile Is Tree", "Source Tile Is Rock",
        "Source Tile Is Wall", "Source Tile Is Demolishable",
        "Source Location Walkable", "Source Location Buildable",
        "Source Last Found X", "Source Last Found Y",
    ),
    "Source animation state": ("Source Animation Action", "Source Animation Frozen"),
})
ACTION_CATEGORIES.update({
    "Source-native orders": (
        "Source Guard", "Source Follow", "Source Attack Target",
        "Source Attack Area", "Source Attack Ground", "Source Attack Wall",
        "Source Defend", "Source Defend Ground", "Source Defend Stopped",
        "Source Stand Attack", "Source Stand Ground", "Source Patrol Move",
        "Source Demolish", "Source Harvest", "Source Repair",
        "Source Return Resources", "Source Unload All",
    ),
    "Source production & economy": (
        "Source Train Unit", "Source Research Technology",
        "Source Research Spell", "Source Upgrade Building",
        "Source Cancel Production", "Source Complete Production",
        "Source Set Production Progress", "Source Give Worker Cargo",
        "Source Clear Worker Cargo", "Source Deposit Worker Cargo",
        "Source Refill Resource Node",
    ),
    "Source transports & workers": (
        "Source Board Transport", "Source Unload Transport Unit",
    ),
    "Source terrain & placement": (
        "Source Set Tiles", "Source Remove Trees", "Source Remove Rocks",
        "Source Place Walls", "Source Destroy Walls", "Source Damage Walls",
        "Source Kill Walls", "Source Find Walkable Point",
        "Source Find Buildable Point",
    ),
    "Source AI, conversion, animation & sound": (
        "Source Acquire Best Target", "Source Reevaluate Target",
        "Source Clear Target", "Source Convert Unit Type",
        "Source Play Animation", "Source Freeze Animation",
        "Source Resume Animation", "Source Play Unit Sound",
        "Source Play Explosion Sound At Point",
    ),
    "Source projectiles & spell effects": (
        "Source Create Projectile At Point",
        "Source Create Projectile Between Units",
        "Source Attach Projectile To Unit", "Source Create Explosion Projectile",
        "Source Blizzard Volley", "Source Fire Shield Effect",
        "Source Whirlwind", "Source Raise Dead Effect",
    ),
})


# ---------------------------------------------------------------------------
# 1.28 Complete Source Systems: source-native and deterministic safe wrappers
# for construction, reachability, damage, fog, terrain lifecycle, workers,
# runes, projectiles, rescue, AI strategy, runtime rules and local UI helpers.
CONDITIONS.extend(SOURCE128_CONDITIONS)
ACTIONS.extend(SOURCE128_ACTIONS)
CONDITION_CATEGORIES.update({
    "Source construction & production 1.28": tuple(name for name in SOURCE128_CONDITIONS if any(word in name for word in ("Construction", "Production", "Afford", "Food", "Auto Train"))),
    "Source pathing, fog & terrain 1.28": tuple(name for name in SOURCE128_CONDITIONS if any(word in name for word in ("Reach", "Island", "Path", "Shore", "Dock", "Undock", "Visible", "Explored", "Tile", "Wall", "Tree"))),
    "Source combat, spells & projectiles 1.28": tuple(name for name in SOURCE128_CONDITIONS if any(word in name for word in ("Damage", "Armor", "Attacker", "Flee", "Rune", "Spell", "Target", "Projectile"))),
    "Source lifecycle, AI & rules 1.28": tuple(name for name in SOURCE128_CONDITIONS if any(word in name for word in ("Rescu", "Hidden", "Paused", "Corpse", "ICE", "Build Goal", "Unit Type", "Upgrade", "Input", "Mouse", "Key", "Resource", "Worker"))),
})
ACTION_CATEGORIES.update({
    "Source construction, pathing & fog 1.28": tuple(name for name in SOURCE128_ACTIONS if any(word in name for word in ("Worker To Build", "Foundation", "Construction", "Building Site", "Shore", "Dock Point", "Undock", "Reveal", "Refresh Fog", "Refresh Minimap"))),
    "Source native damage & reactions 1.28": tuple(name for name in SOURCE128_ACTIONS if any(word in name for word in ("Native Damage", "Damage Terrain", "Damage Wall", "Attacker", "Retaliation", "Nearby Units", "Flee", "Attack Decision"))),
    "Source terrain, production & workers 1.28": tuple(name for name in SOURCE128_ACTIONS if any(word in name for word in ("Tree", "Terrain", "Wall Connections", "Shore Regions", "Production", "Queue", "Training", "Auto Train", "Gold Mine", "Oil Patch", "Return Building", "Resource Building", "Harvest Cycle", "Tanker"))),
    "Source runes, projectiles & sounds 1.28": tuple(name for name in SOURCE128_ACTIONS if any(word in name for word in ("Rune", "Spell Mana", "Projectile", "Flame Spin", "Black X", "Sound"))),
    "Source lifecycle, AI, rules & local UI 1.28": tuple(name for name in SOURCE128_ACTIONS if any(word in name for word in ("Rescue", "Hide", "Show Unit", "Individual Unit", "Transport Occupants", "Corpse", "Native Action", "Native Patrol", "Native Guard", "Native Defend", "Native Attack AI", "Native Transport", "Native Oil", "Specific Player", "Strongest Player", "Native Spell AI", "Native Build", "AI Build Goal", "Suicide", "Unit Type", "Upgrade Cost", "Upgrade Research", "Vanilla", "Game", "Select Units", "Deselect", "Input", "Minimap Marker", "Local Camera", "Selected Unit Card", "Cinematic", "Dialog"))),
})

# ---------------------------------------------------------------------------
# 1.29 Campaign & Cutscene Edition. These actions model the legacy reference module,
# reference module, SLIDESHW.C, reference module, reference module, reference module and reference module scene surfaces
# using only already-validated Remaster gameplay/message/camera callbacks.
CAMPAIGN_CONDITIONS = [
    "Campaign Objective State", "Cutscene State", "Scene Actor State",
    "Scene Actor At Location", "Campaign Rescue Count", "Campaign Capture Count",
    "Campaign Rescue Possible", "Campaign Rescue Goal Met",
    "Campaign Player Eliminated", "Campaign Player Alive",
    "Campaign Genocide Complete", "Campaign Unit Type Remaining",
    "Campaign Unit Type Destroyed", "Campaign Completed Building Count",
    "Campaign Building Type Destroyed", "Campaign All Actors In Location",
    "Campaign All Actors Alive", "Campaign Any Actor Dead",
]
CAMPAIGN_ACTIONS = [
    "Set Campaign Objective", "Complete Campaign Objective", "Fail Campaign Objective",
    "Hide Campaign Objective", "Show Campaign Objective", "Clear Campaign Objective",
    "Clear All Campaign Objectives", "Use Trigger Objectives", "Restore Map Objectives",
    "Show Objectives HUD", "Hide Objectives HUD",
    "Refresh Objectives HUD", "Set Rescue Goal",
    "Show Mission Briefing", "Show Act Card", "Show Epilogue", "Show Credits",
    "Begin Cutscene", "End Cutscene",
    "Scene Create Actor", "Scene Save Actor", "Scene Clear Actor",
    "Scene Actor Talk", "Scene Actor Walk", "Scene Actor Patrol",
    "Scene Actor Attack", "Scene Actor Guard", "Scene Actor Stop",
    "Scene Actor Face", "Scene Actor Look At Actor", "Scene Actor Play Animation",
    "Scene Actor Die", "Scene Actor Remove", "Scene Actor Hide", "Scene Actor Show",
    "Scene Actor Teleport", "Scene Actor Set HP", "Scene Actor Set Mana",
    "Scene Actor Damage From Actor", "Scene Actor Change Owner",
    "Scene Actor Invincible", "Scene Actor Vulnerable",
    "Scene Actor Rescuable", "Scene Actor Not Rescuable",
    "Scene Wait For Actor State", "Scene Wait For Actor At Location",
    "Scene Wait For All Actors At Location",
    "Scene Camera Cut", "Scene Camera Pan", "Scene Camera Follow Actor",
    "Scene Stop Camera Follow", "Scene Camera Shake", "Scene Play Sound",
]
CONDITIONS.extend(CAMPAIGN_CONDITIONS)
ACTIONS.extend(CAMPAIGN_ACTIONS)
CONDITION_CATEGORIES.update({
    "Campaign objectives & mission state 1.29": (
        "Campaign Objective State", "Campaign Rescue Count", "Campaign Capture Count",
        "Campaign Rescue Possible", "Campaign Rescue Goal Met",
        "Campaign Player Eliminated", "Campaign Player Alive",
        "Campaign Genocide Complete", "Campaign Unit Type Remaining",
        "Campaign Unit Type Destroyed", "Campaign Completed Building Count",
        "Campaign Building Type Destroyed",
    ),
    "Cutscene actors 1.29": (
        "Cutscene State", "Scene Actor State", "Scene Actor At Location",
        "Campaign All Actors In Location", "Campaign All Actors Alive",
        "Campaign Any Actor Dead",
    ),
})
ACTION_CATEGORIES.update({
    "Campaign objectives & briefing 1.29": (
        "Set Campaign Objective", "Complete Campaign Objective", "Fail Campaign Objective",
        "Hide Campaign Objective", "Show Campaign Objective", "Clear Campaign Objective",
        "Clear All Campaign Objectives", "Use Trigger Objectives", "Restore Map Objectives",
        "Show Objectives HUD", "Hide Objectives HUD",
        "Refresh Objectives HUD", "Set Rescue Goal", "Show Mission Briefing",
        "Show Act Card", "Show Epilogue", "Show Credits",
    ),
    "Cutscene flow & camera 1.29": (
        "Begin Cutscene", "End Cutscene", "Scene Camera Cut", "Scene Camera Pan",
        "Scene Camera Follow Actor", "Scene Stop Camera Follow", "Scene Camera Shake",
        "Scene Play Sound",
    ),
    "Cutscene actor choreography 1.29": (
        "Scene Create Actor", "Scene Save Actor", "Scene Clear Actor",
        "Scene Actor Talk", "Scene Actor Walk", "Scene Actor Patrol",
        "Scene Actor Attack", "Scene Actor Guard", "Scene Actor Stop",
        "Scene Actor Face", "Scene Actor Look At Actor", "Scene Actor Play Animation",
        "Scene Actor Die", "Scene Actor Remove", "Scene Actor Hide", "Scene Actor Show",
        "Scene Actor Teleport", "Scene Actor Set HP", "Scene Actor Set Mana",
        "Scene Actor Damage From Actor", "Scene Actor Change Owner",
        "Scene Actor Invincible", "Scene Actor Vulnerable",
        "Scene Actor Rescuable", "Scene Actor Not Rescuable",
        "Scene Wait For Actor State", "Scene Wait For Actor At Location",
        "Scene Wait For All Actors At Location",
    ),
})

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
    "Cannon", "Cannon Muzzle Fire", "Cannon Explosion", "Demon Fire", "Black X", "None",
]

SPELL_SOUND_NAMES = (
    "Bloodlust", "Death and Decay", "Death Coil", "Exorcism", "Flame Shield",
    "Haste", "Healing", "Holy Vision", "Blizzard", "Invisibility", "Eye of Kilrogg",
    "Polymorph", "Slow", "Thunder", "Touch of Darkness", "Unholy Armor", "Whirlwind",
)

SPELL_NAMES = (
    "Runes", "Holy Vision", "Blizzard", "Fireball", "Slow", "Flame Shield",
    "Invisibility", "Polymorph", "Eye of Kilrogg", "Bloodlust", "Healing",
    "Exorcism", "Raise Dead", "Death Coil", "Whirlwind", "Death and Decay",
    "Haste", "Unholy Armor",
)

ULTIMATE_SPELL_RESEARCH = (
    "Holy Vision", "Healing", "Area Heal", "Exorcism", "Flame Shield",
    "Fireball", "Slow", "Invisibility", "Polymorph", "Blizzard",
    "Eye of Kilrogg", "Bloodlust", "Hallucinate", "Raise Dead",
    "Death Coil", "Whirlwind", "Haste", "Unholy Armor", "Runes",
    "Death and Decay", "Paladin / Ogre-Mage Conversion",
)
ULTIMATE_UPGRADES = (
    "Ranged Attack", "Melee Attack", "Armor", "Ship Attack", "Ship Armor",
    "Ship Speed", "Siege Damage", "Ranger / Berserker",
    "Longbow / Light Axes", "Scouting", "Marksmanship / Regeneration",
)
ULTIMATE_EFFECTS = (
    "Stun", "Root", "Silence", "Fear", "Taunt", "Damage Over Time",
    "Healing Over Time", "Shield", "Armed Sapper", "Bloodlust", "Haste",
    "Slow", "Invisibility", "Unholy Armor", "Flame Shield",
)
TACTICAL_PROFILES = (
    "Aggressive", "Defensive", "Focus Fire", "Kite", "Protect Hero",
    "Siege Base", "Retreat when wounded", "Hold formation",
)
TACTICAL_ROLES = ("Automatic", "Tank", "Damage", "Healer", "Caster", "Siege", "Scout", "Bodyguard")
WAVE_FORMATIONS = ("Grid", "Horizontal", "Vertical", "Compact", "Random")
QUEST_STATES = ("Active", "Completed", "Failed", "Missing")

GAME_MESSAGE_RECIPIENTS = (
    "Local player only",
    "All active players",
) + tuple(f"Player {i}" for i in range(1, 9))

PLAYER_CHAT_SENDERS = (
    "Current trigger player",
    "Local player",
) + tuple(f"Player {i}" for i in range(1, 9))

GAME_SPEED_LEVELS = (
    "Slowest", "Slower", "Slow", "Normal", "Fast", "Faster", "Fastest",
)
PLAYER_REFERENCE_MODES = (
    "Live owner slots (P1-P8)",
    "Displayed colors / fixed order (P1=Red, P2=Blue, P3=Teal, P4=Violet, P5=Orange, P6=Black, P7=White, P8=Yellow)",
)

PLAYER_CHAT_COLORS = (
    "Native sender color — no override",
    "Yellow / gold — native normal",
    "White — native highlight",
    "Red — native selected / warning",
    "Gray — native disabled",
    "Game yellow — native game palette",
)

GAME_MESSAGE_COLOR_TAGS = (
    "[yellow]", "[white]", "[red]", "[gray]", "[game]", "[previous]",
)

MESSAGE_VARIABLE_QUICK = (
    ("Elapsed seconds", "{elapsed}"),
    ("Trigger run number", "{run}"),
    ("Executing player", "{player}"),
    ("Executing player number", "{player_number}"),
    ("Gold — executing player", "{gold}"),
    ("Lumber — executing player", "{lumber}"),
    ("Oil — executing player", "{oil}"),
    ("Kills — executing player", "{kills}"),
    ("New kills this cycle — executing player", "{killdelta}"),
    ("Deaths — executing player", "{deaths}"),
    ("Score — executing player", "{score}"),
    ("Named variable", "{variable(Variable 1)}"),
    ("Named countdown timer", "{timer(Timer 1)}"),
    ("Named objective", "{objective(Objective 1)}"),
)

SPELL_MAP_TARGET_SOURCES = (
    "Location / coordinates",
    "Matching unit(s)",
)

SPELL_CAST_MODES = (
    "Automatic",
    "Caster-free effect",
    "Use caster units",
)

SPELL_TARGET_SELECTIONS = (
    "Nearest valid",
    "Most wounded",
    "Lowest health %",
    "Highest health %",
    "Lowest current HP",
    "Highest current HP",
    "Nearest then most wounded",
)

SPELL_TARGET_HEALTH_FILTERS = (
    "Spell default",
    "Any health",
    "Wounded only",
    "At or below %",
    "At or above %",
    "At or below HP",
    "At or above HP",
)

GROUND_TARGET_SPELLS = {
    "runes", "holy vision", "blizzard", "fireball", "exorcism",
    "raise dead", "death coil", "whirlwind", "death and decay",
}

UNIT_TARGET_SPELLS = {
    "slow", "flame shield", "invisibility", "polymorph", "bloodlust",
    "healing", "haste", "unholy armor",
}

COMPARISONS = ("At least", "At most", "Exactly", "Not equal")
PLAYERS = ("Local Human", "First Non-Local Slot") + tuple(f"Player {i}" for i in range(1, 17))


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: str = "text"
    default: Any = ""
    choices: tuple[str, ...] = ()
    help: str = ""
    optional: bool = False


def _field(key: str, label: str, kind: str = "text", default: Any = "", choices: Iterable[str] = (), help: str = "", optional: bool = False) -> FieldSpec:
    return FieldSpec(key, label, kind, default, tuple(choices), help, optional)


COMMON_UNIT_FIELDS = (
    _field("player", "Owner", "player", 0, help="Shown as Player 1 through Player 16; JSON stores zero-based player IDs."),
    _field("unit", "Unit or building", "unit", "Any", help="The dropdown is grouped into mobile units (IDs 0-57) and buildings/map objects (IDs 58+)."),
    _field("location", "Location", "location", "Anywhere", help="Filters objects inside the named rectangle. Anywhere ignores location bounds."),
)

COMMON_BUILDING_FIELDS = (
    _field("player", "Owner", "player", 0),
    _field("unit", "Building type", "building", 58, help="Only building and map-object IDs are shown."),
    _field("location", "Location", "location", "Anywhere"),
)

TARGET_UNIT_FIELDS = (
    _field("target_player", "Target owner", "player", 1),
    _field("target_unit", "Target unit or building", "unit", "Any"),
    _field("target_location", "Target location", "location", "Anywhere"),
)

COUNT_FIELDS = (
    _field("comparison", "Comparison", "choice", "At least", COMPARISONS),
    _field("amount", "Amount", "int", 1),
)

LOCATION_POINT_FIELDS = (
    _field("location", "Destination location", "location", "Anywhere", help="Named locations use their center. Anywhere requires X and Y."),
    _field("x", "Tile X", "int", 0, help="Used when the destination is Anywhere.", optional=True),
    _field("y", "Tile Y", "int", 0, help="Used when the destination is Anywhere.", optional=True),
)


CONDITION_SCHEMAS: dict[str, tuple[FieldSpec, ...]] = {
    "Always": (),
    "Never": (),
    "Elapsed Time": COUNT_FIELDS,
    "Counter": (
        _field("name", "Counter name", "text", "Lives"),
    ) + COUNT_FIELDS,
    "Command": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Bring": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Building Count": (
        _field("player", "Owner", "player", 0),
        _field("unit", "Building type", "building_any", "Any", help="Choose Any to count every normal building, or select one exact building type."),
        _field("location", "Location", "location", "Anywhere"),
    ) + COUNT_FIELDS,
    "Unit Entered Location": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Building Completed": COMMON_BUILDING_FIELDS + COUNT_FIELDS,
    "Unit Created": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Unit Died": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Unit Removed": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Corpse Count": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Missile Count": (
        _field("player", "Owner", "player", 0),
        _field("owner_unit", "Firing unit", "unit", "Any", optional=True),
        _field("missile", "Missile type", "missile", "Any"),
    ) + COUNT_FIELDS,
    "Rune Count": (
        _field("location", "Location", "location", "Anywhere"),
    ) + COUNT_FIELDS,
    "Hit Points": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Mana": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Resources": (
        _field("player", "Player", "player", 0),
        _field("resource", "Resource", "choice", "Gold", ("Gold", "Lumber", "Oil")),
    ) + COUNT_FIELDS,
    "Kills": (
        _field("player", "Player", "player", 0),
        _field("category", "Category", "choice", "All", ("Men", "Buildings", "All")),
    ) + COUNT_FIELDS,
    "Player Killed": (
        _field("player", "Killer player", "player", 0),
        _field("category", "Killed category", "choice", "All", ("Men", "Buildings", "All"), help="Uses Warcraft's native credited-kill counters. Friendly-fire deaths are not credited by the game."),
    ) + COUNT_FIELDS,
    "Deaths": (
        _field("player", "Player", "player", 0),
        _field("category", "Category", "choice", "All", ("Men", "Buildings", "All")),
    ) + COUNT_FIELDS,
    "Score": (_field("player", "Player", "player", 0),) + COUNT_FIELDS,
    "Switch": (
        _field("name", "Switch name", "text", "Switch 1"),
        _field("state", "State", "choice", "Set", ("Set", "Cleared")),
    ),
    "Game State": (_field("state", "State", "choice", "Playing", ("Playing", "Victory", "Defeat")),),
    "Unit Property": COMMON_UNIT_FIELDS + (
        _field("property", "Property", "choice", "health", ("health", "mana", "action", "warp", "armor", "rage", "fire", "invis")),
    ) + COUNT_FIELDS,
}


ACTION_SCHEMAS: dict[str, tuple[FieldSpec, ...]] = {
    "Display Text": (_field("text", "Message", "multiline", "Trigger fired"),),
    "Game Message": (
        _field(
            "text", "Message template", "message_template", "Round started!",
            help=(
                "Uses Warcraft's native game-information slot. Remaster stores the line's "
                "starting color in a dedicated byte, while raw 0x01-0x06 controls "
                "inside the text change color inline. [yellow], [white], [red], "
                "[gray], [game], and [previous] map to those native controls. Variables such as "
                "{count(Current|Footman|Anywhere)}, {gold}, {kills(P1|All)}, "
                "{elapsed}, and {run} expand when the action fires. The network text "
                "remains printable; the local native HUD slot receives the colors. "
                "To show this again, enable 'Repeat / preserve this trigger' in the "
                "main Trigger settings and use Max runs 0 for unlimited repeats."
            ),
        ),
        _field("color", "Starting information color", "choice", "Yellow / gold — native normal", PLAYER_CHAT_COLORS, help="Sets the native per-slot renderer color for the whole game-information line."),
        _field("recipients", "Recipients", "choice", "Local player only", GAME_MESSAGE_RECIPIENTS, help="Local uses Warcraft's one native game-information HUD slot. All/Player choices also send printable PM_STRING text to matching network players."),
        _field("seconds", "Display seconds", "int", 4, help="How long the local in-game information message remains visible. A later Game Message replaces the same native slot."),
        _field("also_log", "Also write to Trigger Studio log", "bool", True),
    ),
    "Player Chat": (
        _field(
            "text", "Chat message template", "chat_template", "Attack now!",
            help=(
                "Sends an actual native Warcraft player-chat line. Local chat enters through "
                "the source-matched rolling insertion routine. Its dedicated base-color "
                "byte controls the starting color, while [yellow], [white], [red], "
                "[gray], [game], and [previous] remain raw inline 0x01-0x06 controls. "
                "Variables such as "
                "{count(Current|Footman|Anywhere)}, "
                "{gold}, {elapsed}, and {run} expand when the action fires. The final "
                "text, including color-control bytes, may use at most 78 CP1252 bytes. "
                "Repeating chat requires 'Repeat / preserve this trigger' in the main "
                "Trigger settings; Max runs 0 means unlimited."
            ),
        ),
        _field("sender", "Chat sender", "choice", "Current trigger player", PLAYER_CHAT_SENDERS, help="Current trigger player uses the player currently executing this trigger. Local player uses Warcraft's gbLocalPlayer. Explicit senders support Player 1 through Player 8."),
        _field("color", "Starting chat color", "choice", "Native sender color — no override", PLAYER_CHAT_COLORS, help="Writes Warcraft's final native rolling-chat color byte after the slot is selected."),
        _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS, help="Local displays only on this Warcraft instance. All/Player choices send the native PM_STRING packet to matching network recipients and also display locally when applicable."),
        _field("also_log", "Also write to Trigger Studio log", "bool", True),
    ),
    "Wait": (_field("seconds", "Seconds", "duration", 1, help="Pauses only the remaining actions in this trigger. It is non-blocking and never sleeps Warcraft's main thread."),),
    "Set Switch": (
        _field("name", "Switch name", "text", "Switch 1"),
        _field("state", "State", "choice", "Set", ("Set", "Cleared")),
    ),
    "Set Counter": (
        _field("name", "Counter name", "text", "Lives"),
        _field("amount", "Value", "int", 20),
    ),
    "Add Counter": (
        _field("name", "Counter name", "text", "Lives"),
        _field("amount", "Amount to add", "int", 1),
    ),
    "Subtract Counter": (
        _field("name", "Counter name", "text", "Lives"),
        _field("amount", "Amount to subtract", "int", 1),
    ),
    "Damage Units": COMMON_UNIT_FIELDS + (
        _field("amount", "Damage", "int", 1),
        _field("attacker_player", "Attacker owner", "player", 0),
        _field("attacker_unit", "Attacker unit", "unit", "Any"),
        _field("attacker_location", "Attacker location", "location", "Anywhere", optional=True),
    ),
    "Set Hit Points": COMMON_UNIT_FIELDS + (_field("amount", "Hit points", "int", 100),),
    "Set Mana": COMMON_UNIT_FIELDS + (_field("amount", "Mana", "int", 100),),
    "Kill Units": COMMON_UNIT_FIELDS + (
        _field(
            "include_settled_move_targets",
            "Include units settled at this move target",
            "bool",
            True,
            help=(
                "When a destination tile is crowded, Warcraft may stop units on nearby legal "
                "tiles while retaining the requested move target. This includes only idle units "
                "that this trigger runtime previously ordered into the selected location."
            ),
        ),
    ),
    "Set Unit Property": COMMON_UNIT_FIELDS + (
        _field("property", "Property", "choice", "health", ("health", "action")),
        _field("value", "Value", "int", 0),
    ),
    "Set Resources": (
        _field("player", "Player", "player", 0),
        _field("resource", "Resource", "choice", "Gold", ("Gold", "Lumber", "Oil")),
        _field("amount", "Amount", "int", 0),
    ),
    "Add Resources": (
        _field("player", "Player", "player", 0),
        _field("resource", "Resource", "choice", "Gold", ("Gold", "Lumber", "Oil")),
        _field("amount", "Amount", "int", 0),
    ),
    "Subtract Resources": (
        _field("player", "Player", "player", 0),
        _field("resource", "Resource", "choice", "Gold", ("Gold", "Lumber", "Oil")),
        _field("amount", "Amount", "int", 0),
    ),
    "Award Kill Resources": (
        _field("killer_player", "Killer player", "player", 0, help="The player whose newly credited kills are counted this trigger cycle."),
        _field("category", "Killed category", "choice", "All", ("Men", "Buildings", "All")),
        _field("recipient_player", "Reward player", "player", 0),
        _field("resource", "Resource", "choice", "Gold", ("Gold", "Lumber", "Oil")),
        _field("amount_per_kill", "Amount per kill", "int", 100),
    ),
    "Create Units": COMMON_UNIT_FIELDS + (
        _field("amount_mode", "Amount source", "choice", "Fixed amount", ("Fixed amount", "Per matching building"), help="Per matching building multiplies the live completed-building count by Units per building."),
        _field("amount", "Fixed amount", "int", 1),
        _field("count_player", "Count buildings owned by", "player", 0, optional=True),
        _field("count_building", "Building type to count", "building_any", 58, optional=True),
        _field("count_location", "Building count location", "location", "Anywhere", optional=True),
        _field("units_per_building", "Units per building", "int", 2, optional=True),
        _field("x", "Tile X", "int", 0, optional=True),
        _field("y", "Tile Y", "int", 0, optional=True),
    ),
    "Create Completed Buildings": COMMON_BUILDING_FIELDS + (
        _field("amount", "Amount", "int", 1),
        _field("x", "Tile X", "int", 0, optional=True),
        _field("y", "Tile Y", "int", 0, optional=True),
    ),
    "Remove Units": COMMON_UNIT_FIELDS + (_field("amount", "Maximum units", "amount", "All"),),
    "Move Units": COMMON_UNIT_FIELDS + (
        _field("amount", "Maximum units", "amount", "All"),
        _field("destination", "Destination", "location", "Anywhere"),
        _field("x", "Tile X", "int", 0, optional=True),
        _field("y", "Tile Y", "int", 0, optional=True),
    ),
    "Give Units": COMMON_UNIT_FIELDS + (
        _field("amount", "Maximum units", "amount", "All"),
        _field("to_player", "New owner", "player", 1),
        _field("play_sound", "Play capture sound", "bool", True),
    ),
    "Order": (
        _field("order", "Order", "choice", "Move", ("Move", "Attack", "Patrol")),
    ) + COMMON_UNIT_FIELDS + (
        _field("amount", "Maximum units", "amount", "All"),
        _field(
            "reissue",
            "Reissue unchanged orders",
            "bool",
            False,
            help="Leave off for repeating triggers. Attack uses only the destination X/Y, never Patrol and never a trigger-selected enemy player. Empty wave owners remain Empty; the runtime tracks the route, acquires nearby enemies through Warcraft's native targeted Attack path, and resumes the destination after combat.",
        ),
        _field("destination", "Attack / move / patrol destination", "location", "Anywhere", optional=True),
        _field("x", "Tile X", "int", 0, optional=True),
        _field("y", "Tile Y", "int", 0, optional=True),
    ),
    "Create Missile": COMMON_UNIT_FIELDS + (
        _field("amount", "Amount", "int", 1),
    ) + TARGET_UNIT_FIELDS,
    "Cast Spell": (
        _field("spell", "Spell", "choice", "Runes", SPELL_NAMES),
        _field("cast_mode", "Casting mode", "choice", "Automatic", SPELL_CAST_MODES, help="Automatic uses a real caster when an exact Caster unit is selected. Runes and Holy Vision can instead run caster-free."),
        _field("caster_player", "Caster owner", "player", 0, optional=True),
        _field("caster_unit", "Caster unit", "mobile_unit", "Any", optional=True),
        _field("caster_location", "Caster location", "location", "Anywhere", optional=True),
        _field("amount", "Maximum casters", "amount", 1, optional=True),
        _field("player", "Fog / spell owner", "player", 0, optional=True),
        _field("map_target_source", "Map target source", "choice", "Location / coordinates", SPELL_MAP_TARGET_SOURCES, help="Ground spells can use a named location/X/Y, or the current tile of matching units."),
        _field("location", "Map target location", "location", "Anywhere", optional=True),
        _field("x", "Target tile X", "int", 0, optional=True),
        _field("y", "Target tile Y", "int", 0, optional=True),
        _field("target_player", "Unit / point target owner", "player", 1, optional=True),
        _field("target_unit", "Unit / point target type", "unit", "Any", optional=True),
        _field("target_location", "Unit / point target location", "location", "Anywhere", optional=True),
        _field("target_amount", "Maximum targets / points", "amount", "All", optional=True, help="Unit-target spells reserve one distinct target per caster. Ground spells using Matching unit(s) cast at each unique matching tile. Use a number to limit either list."),
        _field("target_selection", "Unit target priority", "choice", "Nearest valid", SPELL_TARGET_SELECTIONS, optional=True, help="Chooses the best eligible unit separately for each caster. A target is reserved before any native order is issued and cannot be reused by another caster in the same action."),
        _field("target_health", "Unit target health", "choice", "Spell default", SPELL_TARGET_HEALTH_FILTERS, optional=True, help="Spell default applies source-safe behavior: Healing requires wounded units; other unit-target spells accept any eligible health unless their native effect has another restriction."),
        _field("target_health_value", "Health threshold", "int", 50, optional=True, help="Used only by At or below/above % or HP. Percent thresholds must be 0 through 100."),
        _field("allow_self_target", "Allow caster to target itself", "bool", True, optional=True),
        _field("refresh_effects", "Recast an active effect", "bool", False, optional=True, help="Normally skips already affected units. Recasting Unholy Armor is dangerous because Warcraft halves the target's current HP again."),
        _field("interrupt_casters", "Interrupt current caster orders", "bool", False, optional=True, help="Normally skips casters already performing any spell. Enable only when deliberately replacing an active native cast/order."),
        _field("duration", "Holy Vision duration", "duration", "Vanilla", optional=True),
    ),
    "Modify Tile": (
        _field("location", "Area", "location", "Anywhere"),
        _field("x", "Left tile X", "int", 0, optional=True),
        _field("y", "Top tile Y", "int", 0, optional=True),
        _field("width", "Width", "int", 1),
        _field("height", "Height", "int", 1),
        _field("tile", "MTXM tile value", "int", 0),
        _field("refresh", "Refresh map systems", "bool", True),
    ),
    "Play Sound": (
        _field("sound", "Native spell sound", "sound", "Thunder", help="Validated bank: relative IDs 0-16, native IDs 69-85."),
        _field("source", "Position source", "choice", "Location", ("Location", "Unit")),
        _field("location", "Sound location", "location", "Anywhere"),
        _field("x", "Tile X", "int", 0, optional=True),
        _field("y", "Tile Y", "int", 0, optional=True),
        _field("sound_player", "Sound unit owner", "player", 0, optional=True),
        _field("sound_unit", "Sound unit type", "unit", "Any", optional=True),
        _field("sound_location", "Sound unit location", "location", "Anywhere", optional=True),
    ),
    "Run AI Script": (
        _field("player", "AI player", "player", 1),
        _field("script", "Script name / ID", "text", ""),
        _field("location", "Target location", "location", "Anywhere"),
    ),
    "Set Game Speed": (
        _field("speed", "Game speed", "choice", "Fastest", GAME_SPEED_LEVELS, help="Uses Warcraft's native seven-level game-speed packet: Slowest through Fastest. A one-shot trigger changes speed once; a preserved trigger can enforce it repeatedly."),
    ),
    "Set Player Relations": (
        _field("player_reference_mode", "Player numbering", "choice", PLAYER_REFERENCE_MODES[0], PLAYER_REFERENCE_MODES, help="Use live owner slots unless you specifically want displayed color names translated to current live owners."),
        _field("matrix", "Player 1-8 relation matrix", "diplomacy_matrix", {}, help="Each row is independent. Diagonal self-cells are permanently enabled and cannot be cleared."),
    ),
    "Set Alliance": (
        _field("player_reference_mode", "Player numbering", "choice", PLAYER_REFERENCE_MODES[0], PLAYER_REFERENCE_MODES, help="Live owner slots targets Warcraft's actual owner bytes. Displayed colors maps P1=Red, P2=Blue, and so on to the colors currently shown in the match."),
        _field("matrix", "Alliance for every player", "alliance_matrix", {}, help="Each row is one player. Check every player that row should be allied with. Unchecked cross-player cells are enemies. Self-cells are locked on and cannot be undone."),
    ),
    "Set Shared Vision": (
        _field("player_reference_mode", "Player numbering", "choice", PLAYER_REFERENCE_MODES[0], PLAYER_REFERENCE_MODES, help="Live owner slots uses Warcraft's real unit-owner bytes. Displayed colors translates Red, Blue, Teal, and the other shown colors to live owner slots."),
        _field("matrix", "Shared vision for every player", "vision_matrix", {}, help="Each row is a vision source. Check every player that should receive that row player's vision. Self-vision is locked on and cannot be undone."),
    ),
    "Set Allied Victory": (
        _field("player_reference_mode", "Player numbering", "choice", PLAYER_REFERENCE_MODES[0], PLAYER_REFERENCE_MODES, help="Choose whether P1-P8 means live owner slots or displayed fixed colors."),
        _field("matrix", "Allied-victory partners for every player", "victory_matrix", {}, help="Each row is one player. Check the players that row should accept as allied-victory partners. A row with only itself checked has Allied Victory disabled. Self-cells are locked on. Warcraft still requires the selected partners to be allied in the Alliance matrix."),
    ),
    "Victory": (),
    "Defeat": (),
}


CONDITION_SCHEMAS.update({
    "Random Chance": (_field("comparison", "Roll comparison", "choice", "At most", COMPARISONS), _field("amount", "Percent / roll value", "int", 25)),
    "Countdown Timer": (_field("name", "Timer name", "text", "Timer 1"),) + COUNT_FIELDS,
    "Timer Expired": (_field("name", "Timer name", "text", "Timer 1"), _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Expired (1=yes)", "int", 1)),
    "Variable": (_field("name", "Variable name", "text", "Variable 1"),) + COUNT_FIELDS,
    "Player Status": (_field("player", "Player", "player", 0), _field("state", "Status", "choice", "Human", ("Human", "Computer", "Neutral", "Empty"))),
    "Player Has No Buildings": (_field("player", "Player", "player", 0), _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "True (1=yes)", "int", 1)),
    "Unit Health Percent": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Unit Order": COMMON_UNIT_FIELDS + (_field("order", "Current order", "choice", "Idle", ("Idle", "Move", "Attack", "Patrol", "Cast Spell", "Dying")),) + COUNT_FIELDS,
    "Unit Status": COMMON_UNIT_FIELDS + (_field("status", "Status", "choice", "Bloodlust", ("Bloodlust", "Haste", "Slow", "Invisibility", "Unholy Armor", "Flame Shield", "Under Attack", "Completed", "Hidden", "Selected")),) + COUNT_FIELDS,
    "Unit Left Location": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Unit Stayed In Location": COMMON_UNIT_FIELDS + (_field("seconds", "Stayed for seconds", "float", 5.0),) + COUNT_FIELDS,
    "Location Empty": COMMON_UNIT_FIELDS + (_field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Empty (1=yes)", "int", 1)),
    "Unit Damaged": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Unit Healed": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Unit Under Attack": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Switch Changed": (_field("name", "Switch name", "text", "Switch 1"), _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Changed (1=yes)", "int", 1)),
    "Counter Changed": (_field("name", "Counter name", "text", "Counter 1"),) + COUNT_FIELDS,
    "Variable Changed": (_field("name", "Variable name", "text", "Variable 1"), _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Changed (1=yes)", "int", 1)),
    "Trigger Enabled": (_field("trigger", "Trigger name", "text", "New Trigger"), _field("state", "State", "choice", "Enabled", ("Enabled", "Disabled"))),
    "Location Exists": (_field("location", "Location", "location", "Anywhere"), _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Exists (1=yes)", "int", 1)),
    "Expression": (_field("expression", "Safe numeric expression", "multiline", "counter('Lives') + var('Wave')", help="Functions: var, counter, timer, group, event, rand, clamp, min, max, abs, round, ceil and floor."),) + COUNT_FIELDS,
    "Unit Group Count": (_field("group", "Unit-group name", "text", "Last Wave"),) + COUNT_FIELDS,
    "Unit Group Empty": (_field("group", "Unit-group name", "text", "Last Wave"), _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Empty (1=yes)", "int", 1)),
    "Objective State": (_field("name", "Objective name", "text", "Objective 1"), _field("state", "State", "choice", "Active", ("Active", "Completed", "Missing"))),
    "Event Available": (_field("event_type", "Event type", "choice", "Any", ("Any", "Unit Created", "Unit Died", "Unit Removed", "Unit Entered Location", "Unit Left Location", "Unit Damaged", "Unit Healed", "Unit Under Attack")), _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Available (1=yes)", "int", 1)),
    "Auto Spellcasting": (_field("player", "Player", "player", 0), _field("state", "State", "choice", "Enabled", ("Enabled", "Disabled"))),
})

ACTION_SCHEMAS.update({
    "Random Wait": (_field("minimum", "Minimum seconds", "float", 0.5), _field("maximum", "Maximum seconds", "float", 2.0)),
    "Toggle Switch": (_field("name", "Switch name", "text", "Switch 1"),),
    "Randomize Switch": (_field("name", "Switch name", "text", "Switch 1"),),
    "Copy Counter": (_field("name", "Destination counter", "text", "Counter 1"), _field("source", "Source counter", "text", "Counter 2")),
    "Multiply Counter": (_field("name", "Counter name", "text", "Counter 1"), _field("amount", "Multiplier", "int", 2)),
    "Divide Counter": (_field("name", "Counter name", "text", "Counter 1"), _field("amount", "Divisor", "int", 2)),
    "Modulo Counter": (_field("name", "Counter name", "text", "Counter 1"), _field("amount", "Modulo", "int", 2)),
    "Clamp Counter": (_field("name", "Counter name", "text", "Counter 1"), _field("minimum", "Minimum", "int", 0), _field("maximum", "Maximum", "int", 100)),
    "Random Counter": (_field("name", "Counter name", "text", "Counter 1"), _field("minimum", "Minimum", "int", 0), _field("maximum", "Maximum", "int", 100)),
    "Set Variable": (_field("name", "Variable name", "text", "Variable 1"), _field("value_type", "Type", "choice", "Number", ("Number", "Text")), _field("value", "Value", "text", "0")),
    "Add Variable": (_field("name", "Variable name", "text", "Variable 1"), _field("amount", "Amount", "int", 1)),
    "Subtract Variable": (_field("name", "Variable name", "text", "Variable 1"), _field("amount", "Amount", "int", 1)),
    "Multiply Variable": (_field("name", "Variable name", "text", "Variable 1"), _field("amount", "Multiplier", "int", 2)),
    "Divide Variable": (_field("name", "Variable name", "text", "Variable 1"), _field("amount", "Divisor", "int", 2)),
    "Modulo Variable": (_field("name", "Variable name", "text", "Variable 1"), _field("amount", "Modulo", "int", 2)),
    "Copy Variable": (_field("name", "Destination variable", "text", "Variable 1"), _field("source", "Source variable", "text", "Variable 2")),
    "Clamp Variable": (_field("name", "Variable name", "text", "Variable 1"), _field("minimum", "Minimum", "int", 0), _field("maximum", "Maximum", "int", 100)),
    "Random Variable": (_field("name", "Variable name", "text", "Variable 1"), _field("minimum", "Minimum", "int", 0), _field("maximum", "Maximum", "int", 100)),
    "Set Countdown Timer": (_field("name", "Timer name", "text", "Timer 1"), _field("seconds", "Seconds", "float", 60.0)),
    "Start Countdown Timer": (_field("name", "Timer name", "text", "Timer 1"), _field("seconds", "Seconds", "float", 60.0)),
    "Pause Countdown Timer": (_field("name", "Timer name", "text", "Timer 1"),),
    "Resume Countdown Timer": (_field("name", "Timer name", "text", "Timer 1"),),
    "Reset Countdown Timer": (_field("name", "Timer name", "text", "Timer 1"),),
    "Enable Trigger": (_field("trigger", "Trigger name", "text", "New Trigger"),),
    "Disable Trigger": (_field("trigger", "Trigger name", "text", "New Trigger"),),
    "Toggle Trigger": (_field("trigger", "Trigger name", "text", "New Trigger"),),
    "Reset Trigger": (_field("trigger", "Trigger name", "text", "New Trigger"), _field("current_player_only", "Reset only this executing player", "bool", False)),
    "Run Trigger": (_field("trigger", "Trigger name", "text", "New Trigger"),),
    "Stop Trigger Actions": (),
    "Stop Trigger Cycle": (),
    "Breakpoint": (_field("message", "Breakpoint note", "text", "Paused by trigger breakpoint"),),
    "Move Location": (_field("location", "Location to move", "location", "Location 1"), _field("source_location", "Center on location", "location", "Anywhere"), _field("x", "Tile X", "int", 0, optional=True), _field("y", "Tile Y", "int", 0, optional=True)),
    "Offset Location": (_field("location", "Location", "location", "Location 1"), _field("x_offset", "X offset", "int", 0), _field("y_offset", "Y offset", "int", 0)),
    "Resize Location": (_field("location", "Location", "location", "Location 1"), _field("width", "Width", "int", 1), _field("height", "Height", "int", 1)),
    "Copy Location": (_field("location", "Destination location", "location", "Location 1"), _field("source_location", "Source location", "location", "Location 1")),
    "Randomize Location": (_field("location", "Location to move", "location", "Location 1"), _field("source_location", "Random bounds", "location", "Location 1")),
    "Follow Unit With Location": (_field("location", "Location to follow", "location", "Location 1"), _field("player", "Unit owner", "player", 0), _field("unit", "Unit", "unit", "Any"), _field("unit_location", "Initial unit search", "location", "Anywhere")),
    "Stop Following Location": (_field("location", "Location", "location", "Location 1"),),
    "Replace Units": COMMON_UNIT_FIELDS + (_field("amount", "Maximum units", "amount", "All"), _field("new_unit", "Replacement unit", "mobile_unit", 0), _field("preserve_health_percent", "Preserve health percentage", "bool", True)),
    "Set Unit Facing": COMMON_UNIT_FIELDS + (_field("facing", "Facing 0=N, 1=NE ... 7=NW", "int", 0),),
    "Set Unit Health Percent": COMMON_UNIT_FIELDS + (_field("percent", "Health percent", "int", 100),),
    "Heal Units": COMMON_UNIT_FIELDS + (_field("amount", "Hit points restored", "int", 40),),
    "Apply Status Effect": COMMON_UNIT_FIELDS + (_field("status", "Effect", "choice", "Bloodlust", ("Bloodlust", "Haste", "Slow", "Invisibility", "Unholy Armor", "Flame Shield")), _field("ticks", "Native duration ticks (0=vanilla)", "int", 0)),
    "Clear Status Effects": COMMON_UNIT_FIELDS + (_field("status", "Effect", "choice", "All", ("All", "Bloodlust", "Haste", "Slow", "Invisibility", "Unholy Armor", "Flame Shield")),),
    "Make Invincible": COMMON_UNIT_FIELDS + (_field("ticks", "Native armor duration ticks", "int", 65535),),
    "Make Vulnerable": COMMON_UNIT_FIELDS,
    "Complete Buildings": COMMON_BUILDING_FIELDS,
    "Set Unit Color": COMMON_UNIT_FIELDS + (_field("color", "Displayed player color 0-7", "int", 0),),
    "Center Camera": (_field("location", "Camera location", "location", "Anywhere"), _field("x", "Tile X", "int", 0, optional=True), _field("y", "Tile Y", "int", 0, optional=True)),
    "Set Score": (_field("player", "Player", "player", 0), _field("amount", "Score", "int", 0)),
    "Set Kills": (_field("player", "Player", "player", 0), _field("category", "Category", "choice", "Men", ("Men", "Buildings")), _field("amount", "Kills", "int", 0)),
    "Set Deaths": (_field("player", "Player", "player", 0), _field("category", "Category", "choice", "Men", ("Men", "Buildings")), _field("amount", "Deaths", "int", 0)),
    "Set Objective": (_field("name", "Objective name", "text", "Objective 1"), _field("text", "Objective text", "text", "Defend the base"), _field("show_message", "Display game message", "bool", True), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS)),
    "Complete Objective": (_field("name", "Objective name", "text", "Objective 1"), _field("show_message", "Display game message", "bool", True), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS)),
    "Clear Objective": (_field("name", "Objective name", "text", "Objective 1"), _field("show_message", "Display game message", "bool", False), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS)),
    "Display Leaderboard": (_field("title", "Title", "text", "Leaderboard"), _field("metric", "Metric", "choice", "Score", ("Score", "Kills", "Deaths", "Gold", "Lumber", "Oil")), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS), _field("seconds", "Display seconds", "int", 8)),
    "Log State": (),
    "Assert": (_field("source", "Source", "choice", "Variable", ("Variable", "Counter", "Timer")), _field("name", "Name", "text", "Variable 1"), _field("comparison", "Comparison", "choice", "Exactly", COMPARISONS), _field("amount", "Expected", "int", 0)),
    "Comment": (_field("text", "Comment", "text", ""),),
    "Create Wave": (
        _field("player", "Wave owner", "player", 6), _field("unit", "Wave unit", "mobile_unit", 0),
        _field("amount_expression", "Amount expression", "text", "5 + var('Wave')", help="A fixed number or safe expression. Maximum 64."),
        _field("spawn_location", "Spawn location", "location", "Anywhere"), _field("spawn_x", "Spawn X", "int", 4, optional=True), _field("spawn_y", "Spawn Y", "int", 1, optional=True),
        _field("formation", "Formation", "choice", "Grid", ("Compact", "Horizontal line", "Vertical line", "Grid", "Random in spawn location")), _field("spacing", "Formation spacing", "int", 1),
        _field("order", "Initial order", "choice", "Attack", ("None", "Move", "Attack", "Patrol")), _field("destination", "Order destination", "location", "Anywhere"), _field("destination_x", "Destination X", "int", 4, optional=True), _field("destination_y", "Destination Y", "int", 127, optional=True),
        _field("group", "Save as unit group", "text", "Last Wave"), _field("health_percent", "Starting health percent", "int", 100), _field("mana", "Starting mana", "int", 0), _field("facing", "Facing -1=native, 0-7", "int", -1),
    ),
    "Save Unit Group": (_field("group", "Unit-group name", "text", "Unit Group 1"),) + COMMON_UNIT_FIELDS + (_field("amount", "Maximum units", "amount", "All"),),
    "Add Units To Group": (_field("group", "Unit-group name", "text", "Unit Group 1"),) + COMMON_UNIT_FIELDS + (_field("amount", "Maximum units", "amount", "All"),),
    "Clear Unit Group": (_field("group", "Unit-group name", "text", "Unit Group 1"),),
    "Order Unit Group": (_field("group", "Unit-group name", "text", "Unit Group 1"), _field("order", "Order", "choice", "Attack", ("Move", "Attack", "Patrol")), _field("destination", "Destination", "location", "Anywhere"), _field("x", "Tile X", "int", 0, optional=True), _field("y", "Tile Y", "int", 0, optional=True)),
    "Set Unit Group Health Percent": (_field("group", "Unit-group name", "text", "Unit Group 1"), _field("percent", "Health percent", "int", 100)),
    "Move Location To Event Unit": (_field("location", "Location", "location", "Tracker"),),
    "Create Units At Event": (_field("player", "Owner", "player", 0), _field("unit", "Unit", "mobile_unit", 0), _field("amount", "Amount", "int", 1), _field("x_offset", "X offset", "int", 0), _field("y_offset", "Y offset", "int", 0)),
    "Set Variable From Event": (_field("name", "Variable name", "text", "Event Value"), _field("field", "Event field", "choice", "Damage / amount", ("Event Type", "Player", "Unit Type", "X", "Y", "Health", "Mana", "Damage / amount"))),
    "Set Variable From Expression": (_field("name", "Variable name", "text", "Result"), _field("expression", "Safe expression", "multiline", "group('Last Wave') * 10 + counter('Lives')")),
    "Set Counter From Expression": (_field("name", "Counter name", "text", "Result"), _field("expression", "Safe expression", "multiline", "var('Wave') * 5")),
    "Log Event Context": (),
    "Enable Auto Spellcasting": (
        _field("player", "Caster owner", "player", 0),
        _field("profile", "Casting profile", "choice", "Balanced combat", ("Balanced combat", "Offensive", "Support", "Full spellbook rotation"), help="Balanced chooses the highest-value valid spell. Full spellbook rotation cycles through every currently valid spell for that caster class."),
        _field("range", "Target search range (tiles)", "int", 16),
        _field("cooldown", "Per-caster cooldown (seconds)", "float", 2.5),
        _field("max_casts_per_cycle", "Maximum casts per engine cycle", "int", 2),
        _field("mana_reserve", "Mana to keep in reserve", "int", 0),
        _field("keep_mana_full", "Keep spellcaster mana at 255", "bool", False, help="Useful for arena demos and custom maps with unlimited magic."),
        _field("utility_spells", "Allow utility spells", "bool", False, help="Adds Holy Vision, Eye of Kilrogg, and Invisibility when useful."),
        _field("group", "Restrict to named unit group", "text", "", optional=True),
        _field("log_casts", "Log each automatic cast", "bool", True),
    ),
    "Disable Auto Spellcasting": (_field("player", "Caster owner", "player", 0),),
    "Auto Cast Spells Now": (_field("player", "Player or All", "text", "All"),),
})
# 1.25 Ultimate Systems schemas.
_REF_FIELD = (_field("reference", "Unit reference name", "text", "Unit Reference 1"),)
_REF_COMPARE = _REF_FIELD + COUNT_FIELDS
_PROJECTILE_FIELDS = (
    _field("player", "Projectile owner", "player", 0),
    _field("owner_unit", "Firing unit", "unit", "Any", optional=True),
    _field("missile", "Missile type", "missile", "Any"),
)

CONDITION_SCHEMAS.update({
    "Unit Reference Exists": _REF_COMPARE,
    "Unit Reference Alive": _REF_COMPARE,
    "Unit Reference Health": _REF_COMPARE,
    "Unit Reference Health Percent": _REF_COMPARE,
    "Unit Reference Mana": _REF_COMPARE,
    "Unit Reference Owner": _REF_COMPARE,
    "Unit Reference Type": _REF_COMPARE,
    "Unit Reference Order": _REF_FIELD + (
        _field("order", "Order", "choice", "Attack", ("Move", "Attack", "Patrol", "Cast Spell", "Idle")),
    ) + COUNT_FIELDS,
    "Unit Reference In Location": _REF_FIELD + (
        _field("location", "Location", "location", "Anywhere"),
    ) + COUNT_FIELDS,
    "Upgrade Level": (
        _field("player", "Player", "player", 0),
        _field("upgrade", "Upgrade category", "choice", "Melee Attack", ULTIMATE_UPGRADES),
    ) + COUNT_FIELDS,
    "Spell Researched": (
        _field("player", "Player", "player", 0),
        _field("spell", "Spell", "choice", "Healing", ULTIMATE_SPELL_RESEARCH),
    ) + COUNT_FIELDS,
    "Spell Allowed": (
        _field("player", "Player", "player", 0),
        _field("spell", "Spell", "choice", "Healing", ULTIMATE_SPELL_RESEARCH),
    ) + COUNT_FIELDS,
    "Custom Effect Active": COMMON_UNIT_FIELDS + (
        _field("effect", "Custom effect", "choice", "Stun", ULTIMATE_EFFECTS),
    ) + COUNT_FIELDS,
    "Shield Amount": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Projectile Created": _PROJECTILE_FIELDS + COUNT_FIELDS,
    "Projectile Expired": _PROJECTILE_FIELDS + COUNT_FIELDS,
    "Wave Director State": (
        _field("name", "Wave Director name", "text", "Wave Director 1"),
        _field("state", "State", "choice", "Active", ("Active", "Stopped", "Complete", "Missing")),
    ),
    "Wave Number": (_field("name", "Wave Director name", "text", "Wave Director 1"),) + COUNT_FIELDS,
    "Boss Phase": (_field("name", "Boss controller name", "text", "Boss 1"),) + COUNT_FIELDS,
    "Tactical AI Enabled": (_field("name", "Tactical AI name", "text", "Squad AI 1"),) + COUNT_FIELDS,
    "Hero Level": _REF_FIELD + COUNT_FIELDS,
    "Hero Experience": _REF_FIELD + COUNT_FIELDS,
    "Inventory Item Count": _REF_FIELD + (
        _field("item", "Item name", "text", "Health Potion"),
    ) + COUNT_FIELDS,
    "Quest State": (
        _field("quest", "Quest name", "text", "Quest 1"),
        _field("state", "State", "choice", "Active", QUEST_STATES),
    ),
    "Force Member": (
        _field("force", "Force name", "text", "Force 1"),
        _field("player", "Player", "player", 0),
    ) + COUNT_FIELDS,
    "Active Player Count": COUNT_FIELDS,
    "Sapper Count": (
        _field("player", "Owner", "player", 0),
        _field("location", "Location", "location", "Anywhere"),
    ) + COUNT_FIELDS,
})

ACTION_SCHEMAS.update({
    "Save Unit Reference": (
        _field("reference", "Reference name", "text", "Unit Reference 1"),
        _field("source", "Source", "choice", "Matching units", ("Matching units", "Event unit", "Last created unit", "Unit group")),
        _field("selection", "Selection", "choice", "First matching", ("First matching", "Random", "Most wounded", "Highest health", "Nearest to reference", "Farthest from reference")),
        _field("player", "Owner", "player", 0),
        _field("unit", "Unit", "unit", "Any"),
        _field("location", "Location", "location", "Anywhere"),
        _field("group", "Source group", "text", "Unit Group 1", optional=True),
        _field("anchor_reference", "Distance anchor reference", "text", "Anchor", optional=True),
    ),
    "Save Event Unit Reference": (_field("reference", "Reference name", "text", "Event Unit"),),
    "Save Last Created Unit Reference": (_field("reference", "Reference name", "text", "Last Created Unit"),),
    "Clear Unit Reference": _REF_FIELD,
    "Order Unit Reference": _REF_FIELD + (
        _field("order", "Order", "choice", "Attack", ("Move", "Attack", "Patrol")),
        _field("destination", "Destination", "location", "Anywhere"),
        _field("x", "Tile X", "int", 0, optional=True),
        _field("y", "Tile Y", "int", 0, optional=True),
    ),
    "Teleport Unit Reference": _REF_FIELD + (
        _field("destination", "Destination", "location", "Anywhere"),
        _field("x", "Tile X", "int", 0, optional=True),
        _field("y", "Tile Y", "int", 0, optional=True),
    ),
    "Give Unit Reference": _REF_FIELD + (_field("new_owner", "New owner", "player", 0),),
    "Set Unit Reference Health": _REF_FIELD + (_field("amount", "Hit points", "int", 100),),
    "Set Unit Reference Mana": _REF_FIELD + (_field("amount", "Mana", "int", 255),),
    "Apply Effect To Unit Reference": _REF_FIELD + (
        _field("effect", "Effect", "choice", "Bloodlust", ULTIMATE_EFFECTS),
        _field("ticks", "Native effect ticks", "int", 250),
        _field("seconds", "Custom effect seconds", "float", 5.0),
        _field("amount", "Effect amount", "float", 40),
        _field("interval", "Tick interval", "float", 1.0),
        _field("source_reference", "Source reference", "text", "", optional=True),
    ),
    "Kill Unit Reference": _REF_FIELD,
    "Run Trigger For Each Unit In Group": (
        _field("group", "Unit group", "text", "Unit Group 1"),
        _field("trigger", "Trigger to call", "text", "Per Unit Action"),
        _field("reference", "Loop-unit reference", "text", "Loop Unit"),
        _field("maximum", "Maximum units", "int", 1600),
    ),
    "Run Trigger For Each Player": (
        _field("force", "Force", "text", "All Players"),
        _field("trigger", "Trigger to call", "text", "Per Player Action"),
    ),
    "Give Spell": (
        _field("player", "Player", "player", 0),
        _field("spell", "Spell", "choice", "Healing", ULTIMATE_SPELL_RESEARCH),
    ),
    "Remove Spell": (
        _field("player", "Player", "player", 0),
        _field("spell", "Spell", "choice", "Healing", ULTIMATE_SPELL_RESEARCH),
    ),
    "Give All Spells": (_field("player", "Player", "player", 0),),
    "Remove All Spells": (_field("player", "Player", "player", 0),),
    "Set Spell Allowed": (
        _field("player", "Player", "player", 0),
        _field("spell", "Spell", "choice", "Healing", ULTIMATE_SPELL_RESEARCH),
        _field("allowed", "Allowed", "bool", True),
    ),
    "Set Upgrade Level": (
        _field("player", "Player", "player", 0),
        _field("upgrade", "Upgrade category", "choice", "Melee Attack", ULTIMATE_UPGRADES),
        _field("level", "Level", "int", 1, help="0-2, matching Warcraft II's native upgrade progression range."),
    ),
    "Add Upgrade Level": (
        _field("player", "Player", "player", 0),
        _field("upgrade", "Upgrade category", "choice", "Melee Attack", ULTIMATE_UPGRADES),
        _field("amount", "Levels to add", "int", 1),
    ),
    "Give All Upgrades": (_field("player", "Player", "player", 0),),
    "Clear All Upgrades": (_field("player", "Player", "player", 0),),
    "Enable Advanced Unit Classes": (_field("player", "Player", "player", 0),),
    "Create Sapper Assault": (
        _field("player", "Owner", "player", 0),
        _field("unit", "Sapper type", "mobile_unit", 14, help="Choose Dwarves (14) or Goblins (15). Other units are rejected at runtime."),
        _field("amount", "Amount", "int", 8),
        _field("spawn_location", "Spawn location", "location", "Anywhere"),
        _field("spawn_x", "Spawn X", "int", 8, optional=True),
        _field("spawn_y", "Spawn Y", "int", 8, optional=True),
        _field("formation", "Formation", "choice", "Grid", WAVE_FORMATIONS),
        _field("spacing", "Spacing", "int", 1),
        _field("group", "Saved group", "text", "Sapper Assault"),
        _field("destination", "Demolition destination", "location", "Anywhere"),
        _field("x", "Destination X", "int", 64, optional=True),
        _field("y", "Destination Y", "int", 64, optional=True),
        _field("target_reference", "Exact target reference", "text", "", optional=True),
    ),
    "Order Sappers Demolish": (
        _field("player", "Owner", "player", 0),
        _field("unit", "Sapper type", "unit", "Any", help="Any filters the selection down to Dwarves/Goblins only."),
        _field("location", "Sapper location", "location", "Anywhere"),
        _field("destination", "Destination", "location", "Anywhere"),
        _field("x", "Tile X", "int", 64, optional=True),
        _field("y", "Tile Y", "int", 64, optional=True),
        _field("target_reference", "Target unit reference", "text", "", optional=True),
    ),
    "Arm Sappers": COMMON_UNIT_FIELDS + (_field("seconds", "Armed tag seconds", "float", 60.0),),
    "Apply Stun": COMMON_UNIT_FIELDS + (_field("seconds", "Seconds", "float", 3.0),),
    "Apply Root": COMMON_UNIT_FIELDS + (_field("seconds", "Seconds", "float", 3.0),),
    "Apply Silence": COMMON_UNIT_FIELDS + (_field("seconds", "Seconds", "float", 5.0),),
    "Apply Fear": COMMON_UNIT_FIELDS + (_field("seconds", "Seconds", "float", 4.0),),
    "Apply Taunt": COMMON_UNIT_FIELDS + (_field("seconds", "Seconds", "float", 4.0), _field("source_reference", "Taunt source reference", "text", "Tank")),
    "Apply Damage Over Time": COMMON_UNIT_FIELDS + (_field("seconds", "Duration", "float", 5.0), _field("amount", "Damage per tick", "int", 5), _field("interval", "Tick interval", "float", 1.0), _field("source_reference", "Damage source reference", "text", "", optional=True)),
    "Apply Healing Over Time": COMMON_UNIT_FIELDS + (_field("seconds", "Duration", "float", 5.0), _field("amount", "Healing per tick", "int", 5), _field("interval", "Tick interval", "float", 1.0)),
    "Add Shield": COMMON_UNIT_FIELDS + (_field("seconds", "Duration", "float", 10.0), _field("amount", "Shield points", "int", 100)),
    "Clear Custom Effects": COMMON_UNIT_FIELDS + (_field("effect", "Effect", "choice", "All", ("All",) + ULTIMATE_EFFECTS),),
    "Set Lifesteal": COMMON_UNIT_FIELDS + (_field("percent", "Lifesteal percent", "float", 20.0),),
    "Set Critical Strike": COMMON_UNIT_FIELDS + (_field("chance", "Critical chance percent", "float", 20.0), _field("multiplier", "Damage multiplier", "float", 2.0)),
    "Set Evasion": COMMON_UNIT_FIELDS + (_field("percent", "Evasion percent", "float", 20.0),),
    "Set Reflect Damage": COMMON_UNIT_FIELDS + (_field("percent", "Reflected damage percent", "float", 25.0),),
    "Set Cleave": COMMON_UNIT_FIELDS + (_field("percent", "Cleave damage percent", "float", 35.0),),
    "Knockback Units": COMMON_UNIT_FIELDS + (_field("anchor_reference", "Anchor reference", "text", "Anchor", optional=True), _field("anchor_location", "Anchor location", "location", "Anywhere"), _field("anchor_location_x", "Anchor X", "int", 0, optional=True), _field("anchor_location_y", "Anchor Y", "int", 0, optional=True), _field("distance", "Tiles", "int", 3)),
    "Pull Units": COMMON_UNIT_FIELDS + (_field("anchor_reference", "Anchor reference", "text", "Anchor", optional=True), _field("anchor_location", "Anchor location", "location", "Anywhere"), _field("anchor_location_x", "Anchor X", "int", 0, optional=True), _field("anchor_location_y", "Anchor Y", "int", 0, optional=True), _field("distance", "Tiles", "int", 3)),
    "Redirect Projectiles": _PROJECTILE_FIELDS + (_field("destination", "Destination", "location", "Anywhere"), _field("x", "X", "int", 0, optional=True), _field("y", "Y", "int", 0, optional=True)),
    "Destroy Projectiles": _PROJECTILE_FIELDS,
    "Duplicate Projectiles": _PROJECTILE_FIELDS + (_field("copies", "Copies per projectile", "int", 1), _field("destination", "Destination", "location", "Anywhere", optional=True), _field("x", "X", "int", 0, optional=True), _field("y", "Y", "int", 0, optional=True)),
    "Enable Tactical AI": (
        _field("name", "Controller name", "text", "Squad AI 1"),
        _field("group", "Unit group", "text", "Army"),
        _field("profile", "Profile", "choice", "Aggressive", TACTICAL_PROFILES),
        _field("role", "Role", "choice", "Automatic", TACTICAL_ROLES),
        _field("destination", "Primary destination", "location", "Anywhere"),
        _field("x", "Destination X", "int", 64, optional=True),
        _field("y", "Destination Y", "int", 64, optional=True),
        _field("retreat_health", "Retreat below HP %", "float", 30.0),
        _field("retreat_location", "Retreat location", "location", "Anywhere"),
        _field("retreat_x", "Retreat X", "int", 0, optional=True),
        _field("retreat_y", "Retreat Y", "int", 0, optional=True),
        _field("radius", "Formation radius", "int", 5),
    ),
    "Disable Tactical AI": (_field("name", "Controller name", "text", "Squad AI 1"),),
    "Start TD Stream Wave": (
        _field("name", "Stream name", "text", "TD Wave 1"),
        _field("player", "Wave owner", "player", 6),
        _field("unit", "Fallback creep unit", "mobile_unit", 1),
        _field("unit_roster_json", "Creep unit IDs (JSON list)", "multiline", "[0,1,8,9]"),
        _field("total", "Total creeps in wave", "int", 200),
        _field("batch_size", "Units per spawn batch", "int", 3),
        _field("interval", "Seconds between batches", "float", 0.35),
        _field("spawn_location", "Spawn location", "location", "Enemy Spawn"),
        _field("spawn_x", "Spawn X", "int", 0, optional=True),
        _field("spawn_y", "Spawn Y", "int", 0, optional=True),
        _field("route_json", "Forward waypoint locations (JSON)", "multiline", '["WP1","WP2","Leak"]'),
        _field("max_hp", "Absolute native maximum HP", "int", 100),
        _field("lane_count", "Centered lane count (1, 3, or 5)", "int", 3),
        _field("naval_as_flying", "Convert naval/immobile roster types to flyers", "bool", True),
        _field("mana", "Starting mana", "int", 0),
        _field("group", "Exact unit group", "text", "TD Wave 1"),
        _field("max_spawn_queue", "Entrance queue cap (0 = unlimited)", "int", 0),
        _field("stall_reissue", "Reissue Move after no progress (seconds)", "float", 1.0),
        _field("spawn_rescue_after", "Route nudge after stall (seconds)", "float", 2.0),
    ),
    "Stop TD Stream Wave": (_field("name", "Stream name", "text", "TD Wave 1"),),
    "Start TD Native HP Ladder": (
        _field("name", "Campaign name", "text", "TD Native HP Ladder"),
        _field("player", "Wave owner", "player", 6),
        _field("unused_unit_ids_json", "Unused mobile IDs (JSON)", "multiline", "[34,36,37,48,54]"),
        _field("total_start", "Wave 1 total creeps", "int", 160),
        _field("total_growth", "Additional creeps per wave", "int", 5),
        _field("batch_size", "Units per spawn batch", "int", 4),
        _field("interval", "Seconds between batches", "float", 0.30),
        _field("first_wave_delay", "First wave delay", "float", 15.0),
        _field("intermission", "Seconds after each cleared wave", "float", 5.0),
        _field("spawn_location", "Spawn location", "location", "Enemy Spawn"),
        _field("spawn_x", "Spawn X", "int", 0, optional=True),
        _field("spawn_y", "Spawn Y", "int", 0, optional=True),
        _field("route_json", "Forward waypoint locations (JSON)", "multiline", '["WP1","WP2","Leak"]'),
        _field("hp_scale_start_percent", "Wave 1 native-HP scale %", "float", 150.0),
        _field("hp_scale_growth_percent", "HP scale % added per wave", "float", 10.0),
        _field("hp_floor_start", "Wave 1 absolute HP floor", "int", 80),
        _field("hp_floor_growth", "HP floor added per wave", "int", 15),
        _field("lane_count", "Centered lane count (1, 3, or 5)", "int", 3),
        _field("naval_as_flying", "Convert naval types to flyers", "bool", True),
        _field("mana", "Wave caster mana", "int", 255),
        _field("max_spawn_queue", "Entrance queue cap (0 = unlimited)", "int", 0),
        _field("stall_reissue", "Reissue Move after no progress", "float", 0.9),
        _field("spawn_rescue_after", "Route nudge after stall", "float", 1.75),
        _field("builder_player", "Tower-builder player", "player", 5),
        _field("builder_unit", "Tower-builder unit", "mobile_unit", 11),
        _field("builder_refill_mana", "Builder mana refill each wave", "int", 255),
    ),
    "Stop TD Native HP Ladder": (_field("name", "Campaign name", "text", "TD Native HP Ladder"),),
    "Start Wave Director": (
        _field("name", "Director name", "text", "Wave Director 1"),
        _field("player", "Wave owner", "player", 1),
        _field("unit_pool", "Unit IDs, comma separated", "text", "1,7,13"),
        _field("spawn_location", "Spawn location", "location", "Anywhere"),
        _field("spawn_x", "Spawn X", "int", 8, optional=True),
        _field("spawn_y", "Spawn Y", "int", 8, optional=True),
        _field("destination", "Attack destination", "location", "Anywhere"),
        _field("destination_x", "Destination X", "int", 100, optional=True),
        _field("destination_y", "Destination Y", "int", 100, optional=True),
        _field("base_count", "First wave size", "int", 8),
        _field("growth", "Units added per wave", "int", 2),
        _field("intermission", "Intermission seconds", "float", 5.0),
        _field("max_waves", "Maximum waves (0 endless)", "int", 10),
        _field("boss_every", "Boss every N waves (0 off)", "int", 5),
        _field("boss_unit", "Boss unit", "mobile_unit", 49),
        _field("formation", "Formation", "choice", "Grid", WAVE_FORMATIONS),
        _field("spacing", "Spacing", "int", 1),
        _field("group_prefix", "Wave group prefix", "text", "Wave"),
        _field("start_delay", "Start delay", "float", 0.0),
    ),
    "Stop Wave Director": (_field("name", "Director name", "text", "Wave Director 1"),),
    "Advance Wave Director": (_field("name", "Director name", "text", "Wave Director 1"),),
    "Start Boss Controller": (
        _field("name", "Controller name", "text", "Boss 1"),
        _field("reference", "Boss unit reference", "text", "Boss"),
        _field("phases_json", "Phase definitions (JSON list)", "multiline", '[{"health_at_or_below":75,"message":"Phase 2!","spawn_unit":1,"spawn_count":6,"destination":"Anywhere","destination_x":64,"destination_y":64},{"health_at_or_below":35,"message":"Enrage!","invulnerable":true,"invulnerable_ticks":100}]'),
    ),
    "Stop Boss Controller": (_field("name", "Controller name", "text", "Boss 1"),),
    "Transfer Resources": (_field("source_player", "Source player", "player", 0), _field("destination_player", "Destination player", "player", 1), _field("resource", "Resource", "choice", "Gold", ("Gold", "Lumber", "Oil")), _field("amount", "Amount", "int", 500)),
    "Steal Resources": (_field("source_player", "Victim player", "player", 1), _field("destination_player", "Receiving player", "player", 0), _field("resource", "Resource", "choice", "Gold", ("Gold", "Lumber", "Oil")), _field("amount", "Amount", "int", 500)),
    "Tax Player": (_field("source_player", "Taxed player", "player", 0), _field("destination_player", "Treasury player", "player", 1), _field("resource", "Resource", "choice", "Gold", ("Gold", "Lumber", "Oil")), _field("amount", "Tax amount", "int", 100)),
    "Start Periodic Income": (_field("name", "Income name", "text", "Income 1"), _field("player", "Player", "player", 0), _field("resource", "Resource", "choice", "Gold", ("Gold", "Lumber", "Oil")), _field("amount", "Amount per payment", "int", 100), _field("interval", "Seconds between payments", "float", 5.0), _field("start_delay", "First payment delay", "float", 0.0)),
    "Stop Periodic Income": (_field("name", "Income name", "text", "Income 1"),),
    "Refill Resource Node": COMMON_UNIT_FIELDS + (_field("amount", "Resource quantity", "int", 50000),),
    "Train Units Instantly At Buildings": COMMON_BUILDING_FIELDS + (_field("new_unit", "Unit to create", "mobile_unit", 0), _field("new_owner", "New unit owner", "player", 0), _field("amount_each", "Units per building", "int", 1), _field("group", "Saved group", "text", "Instant Production")),
    "Register Hero": _REF_FIELD + (_field("level", "Starting level", "int", 1), _field("xp", "Starting XP", "int", 0), _field("next_level_xp", "XP for next level", "int", 100), _field("xp_growth", "XP requirement multiplier", "float", 1.25), _field("xp_per_kill", "XP per credited kill", "int", 10), _field("hp_per_level", "Max HP per level", "int", 10)),
    "Add Hero Experience": _REF_FIELD + (_field("amount", "Experience", "int", 25),),
    "Set Hero Level": _REF_FIELD + (_field("level", "Level", "int", 1),),
    "Give Inventory Item": _REF_FIELD + (_field("item", "Item", "text", "Health Potion"), _field("amount", "Amount", "int", 1)),
    "Remove Inventory Item": _REF_FIELD + (_field("item", "Item", "text", "Health Potion"), _field("amount", "Amount", "int", 1)),
    "Clear Inventory": _REF_FIELD,
    "Set Quest": (_field("quest", "Quest name", "text", "Quest 1"),),
    "Complete Quest": (_field("quest", "Quest name", "text", "Quest 1"),),
    "Fail Quest": (_field("quest", "Quest name", "text", "Quest 1"),),
    "Clear Quest": (_field("quest", "Quest name", "text", "Quest 1"),),
    "Transmission": (_field("speaker", "Speaker", "text", "Narrator"), _field("text", "Transmission text", "multiline", "The battle begins!"), _field("reference", "Speaker unit reference", "text", "", optional=True), _field("center_camera", "Center camera on speaker", "bool", False), _field("color", "Color", "choice", "White — native highlight", PLAYER_CHAT_COLORS), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS), _field("seconds", "Display seconds", "int", 5)),
    "Watch Expression": (_field("expression", "Expression", "multiline", "group('Army') + counter('Wave')"),),
    "Dump Unit References": (),
    "Dump Unit Group": (_field("group", "Unit group", "text", "Army"),),
})

# 1.26 World Systems schemas.
_WORLD_ATTRIBUTES = ("Strength", "Agility", "Intelligence", "Vitality")
_WORLD_EQUIPMENT_SLOTS = ("Weapon", "Armor", "Accessory 1", "Accessory 2", "Relic", "Consumable", "Any")
_WORLD_ITEM_EFFECTS = ("Heal", "Mana", "Experience", "Shield", "Bloodlust", "Haste", "Slow", "Invisibility", "Unholy Armor", "Flame Shield", "Custom Currency")
_WORLD_AURA_EFFECTS = ("Health Regeneration", "Mana Regeneration", "Damage", "Shield", "Silence", "Bloodlust", "Haste", "Slow", "Invisibility", "Unholy Armor", "Flame Shield")
_WORLD_FORMATIONS = ("Grid", "Horizontal line", "Vertical line", "Compact")

CONDITION_SCHEMAS.update({
    "Local Variable": (_field("name", "Local / argument name", "text", "amount"),) + COUNT_FIELDS,
    "Function Depth": COUNT_FIELDS,
    "List Length": (_field("name", "Runtime list", "text", "List 1"),) + COUNT_FIELDS,
    "List Contains": (_field("name", "Runtime list", "text", "List 1"), _field("value", "Value", "text", "Item"), _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Contains (1=yes)", "int", 1)),
    "List Numeric Item": (_field("name", "Runtime list", "text", "List 1"), _field("index", "Zero-based item index", "int", 0)) + COUNT_FIELDS,
    "Runtime Flag": (_field("name", "Runtime flag", "text", "Flag 1"), _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Set (1=yes)", "int", 1)),
    "Trigger Cooldown Ready": (_field("name", "Cooldown name", "text", "Ability Cooldown"), _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Ready (1=yes)", "int", 1)),
    "Custom Currency": (_field("player", "Player", "player", 0), _field("currency", "Currency name", "text", "Credits")) + COUNT_FIELDS,
    "Shop Item Stock": (_field("item", "Shop item", "text", "Health Potion"),) + COUNT_FIELDS,
    "Inventory Capacity Remaining": (_field("reference", "Unit reference", "text", "Hero"),) + COUNT_FIELDS,
    "Item Equipped": (_field("reference", "Unit reference", "text", "Hero"), _field("item", "Item", "text", "Iron Sword"), _field("slot", "Equipment slot", "choice", "Any", _WORLD_EQUIPMENT_SLOTS), _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Equipped (1=yes)", "int", 1)),
    "Hero Attribute": (_field("reference", "Hero reference", "text", "Hero"), _field("attribute", "Attribute", "choice", "Strength", _WORLD_ATTRIBUTES)) + COUNT_FIELDS,
    "Hero Skill Level": (_field("reference", "Hero reference", "text", "Hero"), _field("skill", "Skill name", "text", "Cleave")) + COUNT_FIELDS,
    "Hero Skill Points": (_field("reference", "Hero reference", "text", "Hero"),) + COUNT_FIELDS,
    "Aura Enabled": (_field("name", "Aura name", "text", "Regeneration Aura"), _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Enabled (1=yes)", "int", 1)),
    "Unit In Aura": (_field("name", "Aura name", "text", "Regeneration Aura"),) + COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Squad Controller State": (_field("name", "Squad controller", "text", "Assault Squad"), _field("state", "State", "choice", "Active", ("Active", "Retreating", "Stopped", "Complete", "Missing"))),
    "Squad Morale": (_field("name", "Squad controller", "text", "Assault Squad"),) + COUNT_FIELDS,
    "Reinforcement Director State": (_field("name", "Reinforcement director", "text", "Battle Reinforcements"), _field("state", "State", "choice", "Active", ("Active", "Stopped", "Complete", "Missing"))),
    "Reinforcement Stage": (_field("name", "Reinforcement director", "text", "Battle Reinforcements"),) + COUNT_FIELDS,
    "Vote State": (_field("name", "Vote name", "text", "Difficulty Vote"), _field("state", "State", "choice", "Open", ("Open", "Closed", "Missing"))),
    "Vote Count": (_field("name", "Vote name", "text", "Difficulty Vote"), _field("option", "Option", "text", "Hard")) + COUNT_FIELDS,
    "Player Voted": (_field("name", "Vote name", "text", "Difficulty Vote"), _field("player", "Player", "player", 0), _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Voted (1=yes)", "int", 1)),
    "Unit Group Average Health Percent": (_field("group", "Unit group", "text", "Army"),) + COUNT_FIELDS,
    "Unit Group Wounded Count": (_field("group", "Unit group", "text", "Army"), _field("health_percent", "At or below health %", "int", 50)) + COUNT_FIELDS,
    "Unit Group Near Location": (_field("group", "Unit group", "text", "Army"), _field("location", "Location", "location", "Location 1"), _field("radius", "Extra radius in tiles", "int", 0)) + COUNT_FIELDS,
})

ACTION_SCHEMAS.update({
    "Call Trigger Function": (_field("trigger", "Function trigger", "text", "Calculate Reward"), _field("arguments_json", "Arguments JSON", "multiline", '{"kills": "=counter(\\"Kills\\")", "multiplier": 100}', help="Values beginning with = are evaluated as safe expressions."), _field("return_variable", "Store return in variable", "text", "Function Result", optional=True), _field("default_return", "Default return", "text", "0")),
    "Set Local Variable": (_field("name", "Local name", "text", "result"), _field("use_expression", "Use expression", "bool", True), _field("expression", "Expression", "multiline", "var('kills') * var('multiplier')"), _field("value", "Literal value", "text", "0", optional=True)),
    "Copy Local To Variable": (_field("local", "Local name", "text", "result"), _field("variable", "Global variable", "text", "Result")),
    "Return From Function": (_field("use_expression", "Use expression", "bool", True), _field("expression", "Return expression", "multiline", "var('result')"), _field("value", "Literal return", "text", "0", optional=True)),
    "Create List": (_field("name", "Runtime list", "text", "Loot Table"), _field("values", "JSON list or comma-separated values", "multiline", '["Potion", "Sword", "Gold"]')),
    "Append To List": (_field("name", "Runtime list", "text", "Loot Table"), _field("use_expression", "Use expression", "bool", False), _field("expression", "Expression", "multiline", "counter('Wave')"), _field("value", "Literal value", "text", "Potion")),
    "Remove From List": (_field("name", "Runtime list", "text", "Loot Table"), _field("value", "Remove matching value", "text", "Potion")),
    "Set List Item": (_field("name", "Runtime list", "text", "Loot Table"), _field("index", "Zero-based index", "int", 0), _field("use_expression", "Use expression", "bool", False), _field("expression", "Expression", "multiline", "counter('Wave')"), _field("value", "Literal value", "text", "Potion")),
    "Pop List To Variable": (_field("name", "Runtime list", "text", "Loot Table"), _field("index", "Index (-1 is last)", "int", -1), _field("variable", "Destination variable", "text", "Loot")),
    "Clear List": (_field("name", "Runtime list", "text", "Loot Table"),),
    "Shuffle List": (_field("name", "Runtime list", "text", "Loot Table"),),
    "Sort List": (_field("name", "Runtime list", "text", "Loot Table"), _field("descending", "Descending", "bool", False)),
    "Choose Random List Item": (_field("name", "Runtime list", "text", "Loot Table"), _field("variable", "Destination variable", "text", "Loot")),
    "Set Runtime Flag": (_field("name", "Runtime flag", "text", "Boss Enraged"),),
    "Clear Runtime Flag": (_field("name", "Runtime flag", "text", "Boss Enraged"),),
    "Toggle Runtime Flag": (_field("name", "Runtime flag", "text", "Boss Enraged"),),
    "Set Trigger Cooldown": (_field("name", "Cooldown name", "text", "Boss Ability"), _field("seconds", "Cooldown seconds", "float", 5.0)),
    "Clear Trigger Cooldown": (_field("name", "Cooldown name", "text", "Boss Ability"),),
    "Set Custom Currency": (_field("player", "Player", "player", 0), _field("currency", "Currency", "text", "Credits"), _field("amount", "Amount", "int", 0)),
    "Add Custom Currency": (_field("player", "Player", "player", 0), _field("currency", "Currency", "text", "Credits"), _field("amount", "Amount", "int", 100)),
    "Subtract Custom Currency": (_field("player", "Player", "player", 0), _field("currency", "Currency", "text", "Credits"), _field("amount", "Amount", "int", 100)),
    "Register Shop Item": (_field("item", "Item name", "text", "Health Potion"), _field("price", "Price", "int", 100), _field("currency_type", "Payment type", "choice", "Gold", ("Gold", "Lumber", "Oil", "Custom Currency")), _field("currency_name", "Custom currency name", "text", "Credits", optional=True), _field("stock", "Starting stock", "int", 10), _field("max_stock", "Maximum stock", "int", 10), _field("effect", "Use effect", "choice", "Heal", _WORLD_ITEM_EFFECTS), _field("effect_amount", "Effect amount / ticks", "int", 40), _field("duration", "Effect duration seconds", "float", 5.0), _field("effect_currency", "Currency granted by item", "text", "Credits", optional=True), _field("slot", "Equipment slot", "choice", "Consumable", _WORLD_EQUIPMENT_SLOTS), _field("bonuses_json", "Equipment attribute bonuses JSON", "multiline", '{"Strength": 5}', optional=True)),
    "Set Shop Stock": (_field("item", "Shop item", "text", "Health Potion"), _field("amount", "Stock", "int", 10)),
    "Buy Shop Item": (_field("reference", "Buyer unit reference", "text", "Hero"), _field("player", "Paying player", "player", 0), _field("item", "Shop item", "text", "Health Potion"), _field("amount", "Quantity", "int", 1)),
    "Sell Inventory Item": (_field("reference", "Seller unit reference", "text", "Hero"), _field("player", "Refund player", "player", 0), _field("item", "Item", "text", "Health Potion"), _field("amount", "Quantity", "int", 1), _field("refund_percent", "Refund percent", "int", 50)),
    "Equip Inventory Item": (_field("reference", "Unit reference", "text", "Hero"), _field("item", "Item", "text", "Iron Sword"), _field("slot", "Equipment slot", "choice", "Weapon", _WORLD_EQUIPMENT_SLOTS)),
    "Unequip Inventory Item": (_field("reference", "Unit reference", "text", "Hero"), _field("item", "Item or Any", "text", "Any"), _field("slot", "Equipment slot", "choice", "Weapon", _WORLD_EQUIPMENT_SLOTS)),
    "Use Inventory Item": (_field("reference", "Unit reference", "text", "Hero"), _field("item", "Item", "text", "Health Potion"), _field("amount", "Quantity", "int", 1)),
    "Set Inventory Capacity": (_field("reference", "Unit reference", "text", "Hero"), _field("capacity", "Item capacity", "int", 12)),
    "Set Hero Attribute": (_field("reference", "Hero reference", "text", "Hero"), _field("attribute", "Attribute", "choice", "Strength", _WORLD_ATTRIBUTES), _field("amount", "Value", "int", 10)),
    "Add Hero Attribute": (_field("reference", "Hero reference", "text", "Hero"), _field("attribute", "Attribute", "choice", "Strength", _WORLD_ATTRIBUTES), _field("amount", "Amount", "int", 1)),
    "Give Hero Skill Point": (_field("reference", "Hero reference", "text", "Hero"), _field("amount", "Skill points", "int", 1)),
    "Learn Hero Skill": (_field("reference", "Hero reference", "text", "Hero"), _field("skill", "Skill name", "text", "Cleave"), _field("levels", "Levels to learn", "int", 1), _field("cost", "Skill-point cost", "int", 1)),
    "Reset Hero Skills": (_field("reference", "Hero reference", "text", "Hero"), _field("refund", "Refund learned levels as points", "bool", True)),
    "Enable Aura": (_field("name", "Aura name", "text", "Regeneration Aura"), _field("source_reference", "Aura source reference", "text", "Aura Source"), _field("effect", "Aura effect", "choice", "Health Regeneration", _WORLD_AURA_EFFECTS), _field("radius", "Radius in tiles", "int", 6), _field("relation", "Affected relation", "choice", "Allies", ("Allies", "Enemies", "All")), _field("amount", "Amount / native ticks", "int", 3), _field("interval", "Pulse interval seconds", "float", 1.0), _field("group", "Optional exact target group", "text", "", optional=True)),
    "Disable Aura": (_field("name", "Aura name", "text", "Regeneration Aura"),),
    "Pulse Aura Now": (_field("name", "Aura name", "text", "Regeneration Aura"),),
    "Start Squad Controller": (_field("name", "Controller name", "text", "Assault Squad"), _field("group", "Exact unit group", "text", "Army"), _field("profile", "Profile", "choice", "Attack", ("Attack", "Aggressive", "Protect Casters", "Regroup", "Hold")), _field("formation", "Formation", "choice", "Grid", _WORLD_FORMATIONS), _field("spacing", "Formation spacing", "int", 2), _field("destination", "Destination", "location", "Anywhere"), _field("x", "Destination X", "int", 64, optional=True), _field("y", "Destination Y", "int", 64, optional=True), _field("retreat_location", "Retreat location", "location", "Anywhere"), _field("retreat_x", "Retreat X", "int", 0, optional=True), _field("retreat_y", "Retreat Y", "int", 0, optional=True), _field("retreat_morale", "Retreat below morale %", "int", 20), _field("cadence", "Update interval seconds", "float", 1.0)),
    "Stop Squad Controller": (_field("name", "Controller name", "text", "Assault Squad"),),
    "Set Squad Destination": (_field("name", "Controller name", "text", "Assault Squad"), _field("destination", "Destination", "location", "Anywhere"), _field("x", "Destination X", "int", 64, optional=True), _field("y", "Destination Y", "int", 64, optional=True)),
    "Set Squad Formation": (_field("name", "Controller name", "text", "Assault Squad"), _field("formation", "Formation", "choice", "Grid", _WORLD_FORMATIONS), _field("spacing", "Spacing", "int", 2)),
    "Set Squad Morale": (_field("name", "Controller name", "text", "Assault Squad"), _field("morale", "Morale percent", "int", 100)),
    "Rally Squad": (_field("name", "Controller name", "text", "Assault Squad"),),
    "Start Reinforcement Director": (_field("name", "Director name", "text", "Battle Reinforcements"), _field("stages_json", "Stages JSON", "multiline", '[{"delay": 5, "waves": [{"player": 0, "unit": 0, "amount": 12, "spawn_x": 8, "spawn_y": 8, "destination_x": 64, "destination_y": 64, "group": "Wave 1"}]}]', help="Each stage has a delay and a waves list. Wave fields match Create Wave.")),
    "Stop Reinforcement Director": (_field("name", "Director name", "text", "Battle Reinforcements"),),
    "Advance Reinforcement Stage": (_field("name", "Director name", "text", "Battle Reinforcements"),),
    "Start Vote": (_field("name", "Vote name", "text", "Difficulty Vote"), _field("question", "Question", "text", "Choose difficulty"), _field("options", "Options JSON or comma-separated", "multiline", '["Normal", "Hard", "Insane"]'), _field("force", "Eligible Force or All Players", "text", "All Players")),
    "Cast Vote": (_field("name", "Vote name", "text", "Difficulty Vote"), _field("player", "Voting player", "player", 0), _field("option", "Option", "text", "Hard")),
    "Close Vote": (_field("name", "Vote name", "text", "Difficulty Vote"), _field("result_variable", "Winner variable", "text", "Difficulty"), _field("tie_result", "Tie result", "text", "Tie")),
    "Reset Vote": (_field("name", "Vote name", "text", "Difficulty Vote"),),
    "Dump World Systems": (),
})


# 1.27 Source Systems schemas.
_SOURCE_SELECTION_AMOUNT = (_field("amount", "Maximum matching units", "amount", "All"),)
_SOURCE_POINT = (
    _field("destination", "Destination", "location", "Anywhere"),
    _field("x", "Destination X", "int", 0, optional=True),
    _field("y", "Destination Y", "int", 0, optional=True),
)
_SOURCE_OPTIONAL_TARGET = (
    _field("use_target_unit", "Use a matching target unit", "bool", False),
) + TARGET_UNIT_FIELDS
_SOURCE_TILE_FILTER = (
    _field("tile_values", "Tile values", "text", "", help="Comma-separated decimal or 0x-prefixed MTXM tile IDs. Read Source Tile Value first.", optional=True),
)
_SOURCE_TERRAIN_REGION = (
    _field("location", "Region location", "location", "Anywhere"),
    _field("x", "Top-left X", "int", 0, optional=True),
    _field("y", "Top-left Y", "int", 0, optional=True),
    _field("width", "Width", "int", 1),
    _field("height", "Height", "int", 1),
)

CONDITION_SCHEMAS.update({
    "Source Production State": COMMON_BUILDING_FIELDS + (
        _field("state", "State", "choice", "Idle", ("Idle", "Training Unit", "Researching Technology", "Researching Spell", "Upgrading Building", "Missing")),
    ),
    "Source Production Progress": COMMON_BUILDING_FIELDS + COUNT_FIELDS,
    "Source Transport Cargo Count": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Source Transport Has Space": COMMON_UNIT_FIELDS + (
        _field("comparison", "Comparison", "choice", "At least", COMPARISONS),
        _field("amount", "True = 1", "int", 1),
    ),
    "Source Unit Is Loaded": COMMON_UNIT_FIELDS + (
        _field("comparison", "Comparison", "choice", "At least", COMPARISONS),
        _field("amount", "True = 1", "int", 1),
    ),
    "Source Worker Cargo Type": COMMON_UNIT_FIELDS + (
        _field("state", "Cargo", "choice", "Gold", ("None", "Gold", "Lumber", "Oil")),
    ),
    "Source Worker Cargo Amount": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Source Resource Node Remaining": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Source Tile Value": LOCATION_POINT_FIELDS + COUNT_FIELDS,
    "Source Tile Is Tree": LOCATION_POINT_FIELDS + _SOURCE_TILE_FILTER + (
        _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "True = 1", "int", 1),
    ),
    "Source Tile Is Rock": LOCATION_POINT_FIELDS + _SOURCE_TILE_FILTER + (
        _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "True = 1", "int", 1),
    ),
    "Source Tile Is Wall": LOCATION_POINT_FIELDS + _SOURCE_TILE_FILTER + (
        _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "True = 1", "int", 1),
    ),
    "Source Tile Is Demolishable": LOCATION_POINT_FIELDS + _SOURCE_TILE_FILTER + (
        _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "True = 1", "int", 1),
    ),
    "Source Location Walkable": COMMON_UNIT_FIELDS + _SOURCE_POINT + (
        _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "True = 1", "int", 1),
    ),
    "Source Location Buildable": COMMON_UNIT_FIELDS + _SOURCE_POINT + (
        _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "True = 1", "int", 1),
    ),
    "Source Unit Has Target": COMMON_UNIT_FIELDS + (
        _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "True = 1", "int", 1),
    ),
    "Source Unit Can Attack Target": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + (
        _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "True = 1", "int", 1),
    ),
    "Source Target In Range": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + COUNT_FIELDS,
    "Source Animation Action": COMMON_UNIT_FIELDS + COUNT_FIELDS,
    "Source Animation Frozen": COMMON_UNIT_FIELDS + (
        _field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "True = 1", "int", 1),
    ),
    "Source Last Found X": COUNT_FIELDS,
    "Source Last Found Y": COUNT_FIELDS,
})

ACTION_SCHEMAS.update({
    "Source Guard": COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Follow": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Attack Target": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Attack Area": COMMON_UNIT_FIELDS + _SOURCE_POINT + _SOURCE_SELECTION_AMOUNT,
    "Source Attack Ground": COMMON_UNIT_FIELDS + _SOURCE_POINT + _SOURCE_SELECTION_AMOUNT,
    "Source Attack Wall": COMMON_UNIT_FIELDS + _SOURCE_POINT + _SOURCE_SELECTION_AMOUNT,
    "Source Defend": COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Defend Ground": COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Defend Stopped": COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Stand Attack": COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Stand Ground": COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Patrol Move": COMMON_UNIT_FIELDS + _SOURCE_POINT + _SOURCE_SELECTION_AMOUNT,
    "Source Demolish": COMMON_UNIT_FIELDS + _SOURCE_OPTIONAL_TARGET + _SOURCE_POINT + _SOURCE_SELECTION_AMOUNT,
    "Source Harvest": COMMON_UNIT_FIELDS + _SOURCE_OPTIONAL_TARGET + _SOURCE_POINT + _SOURCE_SELECTION_AMOUNT,
    "Source Repair": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Return Resources": COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Unload All": COMMON_UNIT_FIELDS + _SOURCE_POINT + _SOURCE_SELECTION_AMOUNT,
    "Source Board Transport": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Unload Transport Unit": COMMON_UNIT_FIELDS + (
        _field("cargo_unit", "Cargo unit", "mobile_unit", "Any"),
    ) + _SOURCE_SELECTION_AMOUNT,
    "Source Train Unit": COMMON_BUILDING_FIELDS + (
        _field("new_unit", "Unit to train", "mobile_unit", 0),
    ) + _SOURCE_SELECTION_AMOUNT,
    "Source Research Technology": COMMON_BUILDING_FIELDS + (
        _field("upgrade", "Technology", "choice", "Melee Attack", ULTIMATE_UPGRADES),
    ) + _SOURCE_SELECTION_AMOUNT,
    "Source Research Spell": COMMON_BUILDING_FIELDS + (
        _field("spell", "Spell research", "choice", "Holy Vision", ULTIMATE_SPELL_RESEARCH),
    ) + _SOURCE_SELECTION_AMOUNT,
    "Source Upgrade Building": COMMON_BUILDING_FIELDS + (
        _field("new_building", "Upgrade into", "building", 86),
    ) + _SOURCE_SELECTION_AMOUNT,
    "Source Cancel Production": COMMON_BUILDING_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Complete Production": COMMON_BUILDING_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Set Production Progress": COMMON_BUILDING_FIELDS + (
        _field("percent", "Completion percent", "int", 50),
    ) + _SOURCE_SELECTION_AMOUNT,
    "Source Give Worker Cargo": COMMON_UNIT_FIELDS + (
        _field("cargo", "Cargo", "choice", "Gold", ("Gold", "Lumber", "Oil")),
        _field("cargo_amount", "Cargo amount", "int", 100),
    ) + _SOURCE_SELECTION_AMOUNT,
    "Source Clear Worker Cargo": COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Deposit Worker Cargo": COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Refill Resource Node": COMMON_UNIT_FIELDS + (
        _field("resource_amount", "Resource remaining", "int", 50000),
    ) + _SOURCE_SELECTION_AMOUNT,
    "Source Set Tiles": _SOURCE_TERRAIN_REGION + (
        _field("tile", "New MTXM tile value", "int", 0),
    ),
    "Source Remove Trees": _SOURCE_TERRAIN_REGION + _SOURCE_TILE_FILTER + (
        _field("replacement_tile", "Replacement tile", "int", 0),
    ),
    "Source Remove Rocks": _SOURCE_TERRAIN_REGION + _SOURCE_TILE_FILTER + (
        _field("replacement_tile", "Replacement tile", "int", 0),
    ),
    "Source Place Walls": _SOURCE_TERRAIN_REGION + (
        _field("wall_tile", "Wall MTXM tile value", "int", 0),
    ),
    "Source Destroy Walls": _SOURCE_TERRAIN_REGION + _SOURCE_TILE_FILTER + (
        _field("replacement_tile", "Replacement tile", "int", 0),
    ),
    "Source Damage Walls": (
        _field("player", "Wall owner", "player", 0),
        _field("location", "Wall location", "location", "Anywhere"),
        _field("damage", "Damage", "int", 20),
        _field("attacker_player", "Damage-credit player", "player", 0),
        _field("attacker_unit", "Damage-credit attacker", "unit", "Any"),
        _field("attacker_location", "Attacker location", "location", "Anywhere"),
    ),
    "Source Kill Walls": (
        _field("player", "Wall owner", "player", 0), _field("location", "Wall location", "location", "Anywhere"),
    ),
    "Source Find Walkable Point": COMMON_UNIT_FIELDS + _SOURCE_POINT + (
        _field("x_variable", "Store X in variable", "text", "Found X"),
        _field("y_variable", "Store Y in variable", "text", "Found Y"),
    ),
    "Source Find Buildable Point": COMMON_UNIT_FIELDS + _SOURCE_POINT + (
        _field("x_variable", "Store X in variable", "text", "Found X"),
        _field("y_variable", "Store Y in variable", "text", "Found Y"),
    ),
    "Source Acquire Best Target": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + (
        _field("radius", "Maximum radius (0 = unlimited)", "int", 0),
    ) + _SOURCE_SELECTION_AMOUNT,
    "Source Reevaluate Target": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + (
        _field("radius", "Maximum radius (0 = unlimited)", "int", 0),
    ) + _SOURCE_SELECTION_AMOUNT,
    "Source Clear Target": COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Convert Unit Type": COMMON_UNIT_FIELDS + (
        _field("new_unit", "New unit type", "unit", 0),
        _field("preserve_health_percent", "Preserve health percentage", "bool", True),
    ) + _SOURCE_SELECTION_AMOUNT,
    "Source Play Animation": COMMON_UNIT_FIELDS + (
        _field("animation", "Native sequence/action byte", "int", 0),
        _field("frame", "Frame", "int", 0),
        _field("facing", "Facing 0-7", "int", 0),
        _field("timer", "Sequence timer", "int", 1),
    ) + _SOURCE_SELECTION_AMOUNT,
    "Source Freeze Animation": COMMON_UNIT_FIELDS + (
        _field("animation", "Native sequence/action byte", "int", 0, optional=True),
        _field("frame", "Frame", "int", 0, optional=True),
        _field("facing", "Facing 0-7", "int", 0, optional=True),
    ) + _SOURCE_SELECTION_AMOUNT,
    "Source Resume Animation": COMMON_UNIT_FIELDS + (
        _field("timer", "Resume timer", "int", 1),
    ) + _SOURCE_SELECTION_AMOUNT,
    "Source Play Unit Sound": COMMON_UNIT_FIELDS + (
        _field("event", "Contextual event", "choice", "Selection", ("Selection", "Under Attack", "Harvest", "Unit Death", "Building Destruction", "Spell")),
        _field("sound", "Spell sound", "sound", "Thunder"),
    ) + _SOURCE_SELECTION_AMOUNT,
    "Source Play Explosion Sound At Point": _SOURCE_POINT + (
        _field("count", "Repeat count", "int", 1),
    ),
    "Source Create Projectile At Point": _SOURCE_POINT + (
        _field("missile", "Projectile", "missile", 0),
        _field("count", "Count", "int", 1),
    ),
    "Source Create Projectile Between Units": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Attach Projectile To Unit": COMMON_UNIT_FIELDS + (
        _field("missile", "Projectile", "missile", 22),
    ) + _SOURCE_SELECTION_AMOUNT,
    "Source Create Explosion Projectile": _SOURCE_POINT + (
        _field("missile", "Explosion projectile", "missile", 20),
        _field("count", "Count", "int", 1),
    ),
    "Source Blizzard Volley": ACTION_SCHEMAS["Cast Spell"],
    "Source Fire Shield Effect": ACTION_SCHEMAS["Cast Spell"],
    "Source Whirlwind": ACTION_SCHEMAS["Cast Spell"],
    "Source Raise Dead Effect": ACTION_SCHEMAS["Cast Spell"],
})


# 1.28 Complete Source Systems schemas.  Every condition/action is authorable;
# defaults stay conservative and exact source filters are exposed where needed.
_SOURCE_BOOL_RESULT = (
    _field("comparison", "Comparison", "choice", "At least", COMPARISONS),
    _field("amount", "True = 1", "int", 1),
)
_SOURCE_RULE_UNIT = (
    _field("unit_type", "Unit type", "unit", 0),
)
_SOURCE_MISSILE_SELECTION = (
    _field("player", "Projectile owner", "player", 0),
    _field("owner_unit", "Firing unit", "unit", "Any"),
    _field("missile", "Projectile type", "missile", "Any"),
    _field("location", "Projectile location", "location", "Anywhere"),
)

for _kind in SOURCE128_CONDITIONS:
    CONDITION_SCHEMAS.setdefault(_kind, COMMON_UNIT_FIELDS + COUNT_FIELDS)
for _kind in SOURCE128_ACTIONS:
    ACTION_SCHEMAS.setdefault(_kind, COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT)

CONDITION_SCHEMAS.update({
    "Source Construction Progress": COMMON_BUILDING_FIELDS + COUNT_FIELDS,
    "Source Worker Is Constructing": COMMON_UNIT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Player Can Afford Unit": (
        _field("player", "Player", "player", 0), _field("new_unit", "Unit", "unit", 0),
    ) + _SOURCE_BOOL_RESULT,
    "Source Player Can Afford Upgrade": (
        _field("player", "Player", "player", 0), _field("upgrade", "Upgrade", "choice", "Melee Attack", ULTIMATE_UPGRADES),
    ) + _SOURCE_BOOL_RESULT,
    "Source Player Has Enough Food": (
        _field("player", "Player", "player", 0), _field("food", "Required free food", "int", 1),
    ) + _SOURCE_BOOL_RESULT,
    "Source Building Production Type": COMMON_BUILDING_FIELDS + COUNT_FIELDS,
    "Source Building Production Item": COMMON_BUILDING_FIELDS + COUNT_FIELDS,
    "Source Production Time Remaining": COMMON_BUILDING_FIELDS + COUNT_FIELDS,
    "Source Production Is Paused": COMMON_BUILDING_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Production Is Waiting": COMMON_BUILDING_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Production Queue Count": COMMON_BUILDING_FIELDS + COUNT_FIELDS,
    "Source Auto Train Remaining": COMMON_BUILDING_FIELDS + COUNT_FIELDS,
    "Source Unit Can Reach Location": COMMON_UNIT_FIELDS + _SOURCE_POINT + (
        _field("max_nodes", "Path search node limit", "int", 768),
    ) + _SOURCE_BOOL_RESULT,
    "Source Unit Can Reach Unit": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + (
        _field("max_nodes", "Path search node limit", "int", 768),
    ) + _SOURCE_BOOL_RESULT,
    "Source Locations On Same Island": COMMON_UNIT_FIELDS + (
        _field("start_location", "Start location", "location", "Anywhere"),
        _field("start_x", "Start X", "int", 0, optional=True),
        _field("start_y", "Start Y", "int", 0, optional=True),
    ) + _SOURCE_POINT + (_field("max_nodes", "Path search node limit", "int", 768),) + _SOURCE_BOOL_RESULT,
    "Source Target Path Is Valid": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + (
        _field("max_nodes", "Path search node limit", "int", 768),
    ) + _SOURCE_BOOL_RESULT,
    "Source Last Shore X": COUNT_FIELDS, "Source Last Shore Y": COUNT_FIELDS,
    "Source Last Dock X": COUNT_FIELDS, "Source Last Dock Y": COUNT_FIELDS,
    "Source Last Undock X": COUNT_FIELDS, "Source Last Undock Y": COUNT_FIELDS,
    "Source Predicted Native Damage": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + COUNT_FIELDS,
    "Source Native Armor Reduction": TARGET_UNIT_FIELDS + COUNT_FIELDS,
    "Source Last Native Damage": COUNT_FIELDS,
    "Source Last Terrain Damage": COUNT_FIELDS,
    "Source Location Is Visible": (_field("player", "Viewing player", "player", 0),) + _SOURCE_POINT + _SOURCE_BOOL_RESULT,
    "Source Location Is Explored": (_field("player", "Viewing player", "player", 0),) + _SOURCE_POINT + _SOURCE_BOOL_RESULT,
    "Source Unit Has Valid Attacker": COMMON_UNIT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Unit Is Fleeing": COMMON_UNIT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Tile Is Being Chopped": COMMON_UNIT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Tile Region Type": LOCATION_POINT_FIELDS + COUNT_FIELDS,
    "Source Tile Has Land Access": COMMON_UNIT_FIELDS + _SOURCE_POINT + _SOURCE_BOOL_RESULT,
    "Source Tile Has Water Access": COMMON_UNIT_FIELDS + _SOURCE_POINT + _SOURCE_BOOL_RESULT,
    "Source Wall Is Connected": LOCATION_POINT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Tree Is Reachable": COMMON_UNIT_FIELDS + _SOURCE_POINT + (
        _field("max_nodes", "Path search node limit", "int", 768),
    ) + _SOURCE_BOOL_RESULT,
    "Source Worker Can Return Resources": COMMON_UNIT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Worker Is Inside Resource": COMMON_UNIT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Last Resource X": COUNT_FIELDS, "Source Last Resource Y": COUNT_FIELDS,
    "Source Rune Exists At Location": LOCATION_POINT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Rune Owner": LOCATION_POINT_FIELDS + COUNT_FIELDS,
    "Source Rune Lifetime": LOCATION_POINT_FIELDS + COUNT_FIELDS,
    "Source Can Cast Spell On Unit": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + (
        _field("spell", "Spell", "choice", "Holy Vision", SOURCE128_COST_SPELLS),
    ) + _SOURCE_BOOL_RESULT,
    "Source Target Is Wooden": TARGET_UNIT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Target Is Fleshy": TARGET_UNIT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Target Is Drainable": TARGET_UNIT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Target Is Valid For Spell": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + (
        _field("spell", "Spell", "choice", "Holy Vision", SOURCE128_COST_SPELLS),
    ) + _SOURCE_BOOL_RESULT,
    "Source Spell Mana Cost": (_field("spell", "Spell", "choice", "Holy Vision", SOURCE128_COST_SPELLS),) + COUNT_FIELDS,
    "Source Projectile Hit Unit": _SOURCE_MISSILE_SELECTION + TARGET_UNIT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Projectile Hit Location": _SOURCE_MISSILE_SELECTION + _SOURCE_POINT + (
        _field("radius", "Hit radius", "int", 1),
    ) + _SOURCE_BOOL_RESULT,
    "Source Projectile Frozen": _SOURCE_MISSILE_SELECTION + _SOURCE_BOOL_RESULT,
    "Source Projectile Lifetime": _SOURCE_MISSILE_SELECTION + COUNT_FIELDS,
    "Source Unit Is Rescuable": COMMON_UNIT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Unit Was Rescued": COMMON_UNIT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Unit Is Hidden": COMMON_UNIT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Unit Is Paused": COMMON_UNIT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source Corpse Decay Active": COMMON_UNIT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source ICE Strategy Active": COMMON_UNIT_FIELDS + _SOURCE_BOOL_RESULT,
    "Source AI Build Goal": (_field("player", "AI player", "player", 0),) + COUNT_FIELDS,
    "Source Unit Type Maximum HP": _SOURCE_RULE_UNIT + COUNT_FIELDS,
    "Source Unit Type Armor": _SOURCE_RULE_UNIT + COUNT_FIELDS,
    "Source Unit Type Basic Damage": _SOURCE_RULE_UNIT + COUNT_FIELDS,
    "Source Unit Type Piercing Damage": _SOURCE_RULE_UNIT + COUNT_FIELDS,
    "Source Unit Type Attack Range": _SOURCE_RULE_UNIT + COUNT_FIELDS,
    "Source Unit Type Sight": _SOURCE_RULE_UNIT + COUNT_FIELDS,
    "Source Unit Type Speed": _SOURCE_RULE_UNIT + COUNT_FIELDS,
    "Source Unit Type Projectile": _SOURCE_RULE_UNIT + COUNT_FIELDS,
    "Source Unit Type Gold Cost": _SOURCE_RULE_UNIT + COUNT_FIELDS,
    "Source Unit Type Lumber Cost": _SOURCE_RULE_UNIT + COUNT_FIELDS,
    "Source Unit Type Oil Cost": _SOURCE_RULE_UNIT + COUNT_FIELDS,
    "Source Unit Type Build Time": _SOURCE_RULE_UNIT + COUNT_FIELDS,
    "Source Upgrade Cost": (_field("upgrade", "Upgrade", "choice", "Melee Attack", ULTIMATE_UPGRADES),) + COUNT_FIELDS,
    "Source Upgrade Research Time": (_field("upgrade", "Upgrade", "choice", "Melee Attack", ULTIMATE_UPGRADES),) + COUNT_FIELDS,
    "Source Local Input Locked": _SOURCE_BOOL_RESULT,
    "Source Local Mouse Button": COUNT_FIELDS,
    "Source Local Key": (_field("key", "Key", "text", "Space"),) + _SOURCE_BOOL_RESULT,
})

# Construction and pathing actions.
ACTION_SCHEMAS.update({
    "Source Order Worker To Build": COMMON_UNIT_FIELDS + (
        _field("new_building", "Building", "building", 58),
    ) + _SOURCE_POINT + (_field("count", "Foundations", "int", 1),) + _SOURCE_SELECTION_AMOUNT,
    "Source Place Building Foundation": (
        _field("player", "Owner", "player", 0), _field("new_building", "Building", "building", 58),
    ) + _SOURCE_POINT + (_field("count", "Foundations", "int", 1),),
    "Source Cancel Construction": COMMON_BUILDING_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Find Nearest Building Site": COMMON_BUILDING_FIELDS + _SOURCE_POINT + (
        _field("x_variable", "Store X", "text", "Build Site X"),
        _field("y_variable", "Store Y", "text", "Build Site Y"),
    ),
    "Source Find Shore Point": COMMON_UNIT_FIELDS + _SOURCE_POINT + (
        _field("radius", "Search radius", "int", 24), _field("x_variable", "Store X", "text", "Shore X"), _field("y_variable", "Store Y", "text", "Shore Y"),
    ),
    "Source Find Dock Point": COMMON_UNIT_FIELDS + _SOURCE_POINT + (
        _field("radius", "Search radius", "int", 24), _field("x_variable", "Store X", "text", "Dock X"), _field("y_variable", "Store Y", "text", "Dock Y"),
    ),
    "Source Find Undock Point": COMMON_UNIT_FIELDS + _SOURCE_POINT + (
        _field("radius", "Search radius", "int", 24), _field("x_variable", "Store X", "text", "Undock X"), _field("y_variable", "Store Y", "text", "Undock Y"),
    ),
})

# Combat/fog/AI actions.
for _kind in ("Source Calculate Native Damage", "Source Deal Native Attack Damage", "Source Damage Wall With Attack"):
    ACTION_SCHEMAS[_kind] = COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + (
        _field("variable", "Store total damage", "text", "Native Damage"),
    ) + _SOURCE_SELECTION_AMOUNT
ACTION_SCHEMAS.update({
    "Source Damage Terrain": _SOURCE_TERRAIN_REGION + (_field("damage", "Native terrain damage", "int", 20),),
    "Source Reveal Area For Player": (_field("reveal_player", "Player to reveal for", "player", 0),) + _SOURCE_TERRAIN_REGION,
    "Source Reveal Radius": (_field("reveal_player", "Player to reveal for", "player", 0),) + _SOURCE_POINT + (_field("radius", "Radius", "int", 9),),
    "Source Refresh Fog": (), "Source Refresh Minimap": (),
    "Source Set Attacker": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Clear Attacker": COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Run Native Retaliation": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Run Native Attack Decision": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Call Nearby Units For Help": COMMON_UNIT_FIELDS + (_field("radius", "Help radius", "int", 8),) + _SOURCE_SELECTION_AMOUNT,
    "Source Force Unit To Flee": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + (_field("radius", "Flee distance", "int", 8),) + _SOURCE_SELECTION_AMOUNT,
})

# Terrain lifecycle.
ACTION_SCHEMAS.update({
    "Source Begin Tree Harvest": COMMON_UNIT_FIELDS + _SOURCE_POINT + _SOURCE_SELECTION_AMOUNT,
    "Source Cancel Tree Harvest": COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Finish Tree Harvest": COMMON_UNIT_FIELDS + (_field("cargo_amount", "Lumber cargo", "int", 100),) + _SOURCE_SELECTION_AMOUNT,
    "Source Find Reachable Tree": COMMON_UNIT_FIELDS + _SOURCE_TERRAIN_REGION + _SOURCE_TILE_FILTER + (
        _field("max_nodes", "Path search node limit", "int", 768), _field("x_variable", "Store X", "text", "Tree X"), _field("y_variable", "Store Y", "text", "Tree Y"),
    ),
    "Source Native Demolish Tile": _SOURCE_TERRAIN_REGION + (_field("damage", "Damage", "int", 65535),),
    "Source Remove Terrain Region": _SOURCE_TERRAIN_REGION + (_field("replacement_tile", "Replacement MTXM tile", "int", 0),),
    "Source Rebuild Wall Connections": COMMON_UNIT_FIELDS + _SOURCE_TERRAIN_REGION,
    "Source Rebuild Shore Regions": COMMON_UNIT_FIELDS + _SOURCE_TERRAIN_REGION,
    "Source Refresh Terrain Pathing": COMMON_UNIT_FIELDS + _SOURCE_TERRAIN_REGION,
    "Source Refresh Terrain Minimap": (),
})

# Production/worker actions.
for _kind in ("Source Pause Production", "Source Resume Production", "Source Clear Production Queue"):
    ACTION_SCHEMAS[_kind] = COMMON_BUILDING_FIELDS + _SOURCE_SELECTION_AMOUNT
ACTION_SCHEMAS.update({
    "Source Queue Unit": COMMON_BUILDING_FIELDS + (_field("new_unit", "Queued unit", "mobile_unit", 0),) + _SOURCE_SELECTION_AMOUNT,
    "Source Enable Continuous Training": COMMON_BUILDING_FIELDS + (_field("new_unit", "Unit", "mobile_unit", 0),) + _SOURCE_SELECTION_AMOUNT,
    "Source Set Auto Train Count": COMMON_BUILDING_FIELDS + (_field("new_unit", "Unit", "mobile_unit", 0), _field("count", "Training count", "int", 1)) + _SOURCE_SELECTION_AMOUNT,
})
for _kind in ("Source Find Nearest Gold Mine", "Source Find Nearest Oil Patch", "Source Find Nearest Return Building"):
    ACTION_SCHEMAS[_kind] = COMMON_UNIT_FIELDS + (_field("x_variable", "Store X", "text", "Resource X"), _field("y_variable", "Store Y", "text", "Resource Y")) + _SOURCE_SELECTION_AMOUNT
ACTION_SCHEMAS["Source Find Nearest Reachable Tree"] = COMMON_UNIT_FIELDS + _SOURCE_TERRAIN_REGION + _SOURCE_TILE_FILTER + (_field("max_nodes", "Path search node limit", "int", 768), _field("x_variable", "Store X", "text", "Tree X"), _field("y_variable", "Store Y", "text", "Tree Y")) + _SOURCE_SELECTION_AMOUNT
ACTION_SCHEMAS.update({
    "Source Force Worker Into Resource Building": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Force Worker Out Of Building": COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Complete Harvest Cycle": COMMON_UNIT_FIELDS + (
        _field("cargo", "Cargo type", "choice", "Gold", ("Gold", "Lumber", "Oil")),
        _field("cargo_amount", "Cargo amount", "int", 100),
    ) + _SOURCE_SELECTION_AMOUNT,
    "Source Tanker Dock": COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Tanker Collect Oil": COMMON_UNIT_FIELDS + (_field("cargo_amount", "Oil cargo", "int", 100),) + _SOURCE_SELECTION_AMOUNT,
    "Source Tanker Deposit Oil": COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
})

# Rune and projectile actions.
ACTION_SCHEMAS.update({
    "Source Place Rune": _SOURCE_POINT,
    "Source Remove Rune": _SOURCE_POINT,
    "Source Trigger Rune": _SOURCE_POINT + (_field("damage", "Trigger damage", "int", 50),),
    "Source Set Rune Lifetime": _SOURCE_POINT + (_field("lifetime", "Native lifetime ticks", "int", 2048),),
    "Source Set Spell Mana Cost": (_field("spell", "Spell", "choice", "Holy Vision", SOURCE128_COST_SPELLS), _field("mana_cost", "Mana cost", "int", 0)),
})
for _kind in ("Source Set Projectile Type", "Source Set Projectile Damage", "Source Set Projectile Speed", "Source Set Projectile Lifetime", "Source Set Projectile Action", "Source Freeze Projectile", "Source Resume Projectile"):
    ACTION_SCHEMAS[_kind] = _SOURCE_MISSILE_SELECTION + _SOURCE_SELECTION_AMOUNT
ACTION_SCHEMAS["Source Set Projectile Type"] += (_field("new_missile", "New projectile type", "missile", 0),)
ACTION_SCHEMAS["Source Set Projectile Damage"] += (_field("damage", "Damage byte", "int", 20),)
ACTION_SCHEMAS["Source Set Projectile Speed"] += (_field("speed", "Speed percent", "int", 100),)
ACTION_SCHEMAS["Source Set Projectile Lifetime"] += (_field("lifetime", "Lifetime ticks", "int", 60),)
ACTION_SCHEMAS["Source Set Projectile Action"] += (_field("projectile_action", "Native action byte", "int", 0),)
ACTION_SCHEMAS["Source Set Projectile Owner"] = _SOURCE_MISSILE_SELECTION + TARGET_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT
ACTION_SCHEMAS["Source Set Projectile Target"] = _SOURCE_MISSILE_SELECTION + TARGET_UNIT_FIELDS + _SOURCE_POINT + _SOURCE_SELECTION_AMOUNT
for _kind in ("Source Create Tower Projectile", "Source Create Fire Projectile", "Source Create Flame Spin", "Source Create Black X Marker", "Source Create Stationary Projectile"):
    ACTION_SCHEMAS[_kind] = _SOURCE_POINT + (_field("new_missile", "Projectile type override", "missile", 0, optional=True), _field("count", "Count", "int", 1))

# Context sounds.
for _kind in tuple(name for name in SOURCE128_ACTIONS if name.startswith("Source Play ") and name.endswith(" Sound")):
    ACTION_SCHEMAS[_kind] = COMMON_UNIT_FIELDS + (_field("sound", "Spell sound fallback", "sound", "Thunder"),) + _SOURCE_SELECTION_AMOUNT

# Rescue/lifecycle/AI.
for _kind in ("Source Enable Unit Rescue", "Source Disable Unit Rescue", "Source Check Rescue Now", "Source Hide Unit Natively", "Source Show Unit Natively", "Source Pause Individual Unit", "Source Resume Individual Unit", "Source Begin Corpse Decay", "Source Stop Corpse Decay", "Source Set Current Native Action", "Source Set Next Native Action"):
    ACTION_SCHEMAS[_kind] = COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT
ACTION_SCHEMAS["Source Begin Corpse Decay"] += (_field("timer", "Decay timer", "int", 30),)
ACTION_SCHEMAS["Source Set Current Native Action"] += (_field("native_action", "Native action byte", "int", 2),)
ACTION_SCHEMAS["Source Set Next Native Action"] += (_field("native_action", "Native action byte", "int", 60),)
ACTION_SCHEMAS["Source Kill Transport Occupants"] = COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT
ACTION_SCHEMAS["Source Eject Transport Occupants"] = COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT
for _kind in ("Source Run Native Patrol AI", "Source Run Native Guard AI", "Source Run Native Defend AI", "Source Run Native Attack AI", "Source Run Native Transport AI", "Source Run Native Oil Patrol", "Source Attack Specific Player", "Source Attack Strongest Player", "Source Run Native Spell AI", "Source Run Native Build Strategy", "Source Force AI Suicide Attack"):
    ACTION_SCHEMAS[_kind] = COMMON_UNIT_FIELDS + TARGET_UNIT_FIELDS + _SOURCE_POINT + (_field("cadence", "Decision cadence seconds", "float", 0.75),) + _SOURCE_SELECTION_AMOUNT
ACTION_SCHEMAS["Source Set AI Build Goal"] = (_field("player", "AI player", "player", 0), _field("new_building", "Building goal", "building", 58), _field("count", "Goal count", "int", 1))

# Runtime unit/upgrade rules.
_RULE_ACTIONS = {
    "Source Set Unit Type Maximum HP": (100, "Maximum HP"),
    "Source Set Unit Type Armor": (0, "Armor"),
    "Source Set Unit Type Basic Damage": (0, "Basic damage"),
    "Source Set Unit Type Piercing Damage": (0, "Piercing damage"),
    "Source Set Unit Type Attack Range": (1, "Attack range"),
    "Source Set Unit Type Sight": (9, "Sight radius"),
    "Source Set Unit Type Speed": (100, "Speed percent"),
    "Source Set Unit Type Projectile": (0, "Projectile ID"),
    "Source Set Unit Type Gold Cost": (0, "Gold cost"),
    "Source Set Unit Type Lumber Cost": (0, "Lumber cost"),
    "Source Set Unit Type Oil Cost": (0, "Oil cost"),
    "Source Set Unit Type Build Time": (0, "Build time"),
}
for _kind, (_default, _label) in _RULE_ACTIONS.items():
    ACTION_SCHEMAS[_kind] = _SOURCE_RULE_UNIT + (_field("value", _label, "int", _default), _field("apply_to_existing", "Apply to current units", "bool", True))
ACTION_SCHEMAS["Source Set Upgrade Cost"] = (_field("upgrade", "Upgrade", "choice", "Melee Attack", ULTIMATE_UPGRADES), _field("value", "Cost", "int", 0))
ACTION_SCHEMAS["Source Set Upgrade Research Time"] = (_field("upgrade", "Upgrade", "choice", "Melee Attack", ULTIMATE_UPGRADES), _field("value", "Research time", "int", 0))
ACTION_SCHEMAS["Source Restore Vanilla Unit Type"] = _SOURCE_RULE_UNIT
ACTION_SCHEMAS["Source Restore All Vanilla Rules"] = ()

# Local-only interface helpers.
ACTION_SCHEMAS.update({
    "Source Pause Game": (), "Source Resume Game": (),
    "Source Select Units": COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Deselect Units": COMMON_UNIT_FIELDS + _SOURCE_SELECTION_AMOUNT,
    "Source Lock Player Input": (), "Source Unlock Player Input": (),
    "Source Show Minimap Marker": _SOURCE_POINT + (_field("duration", "Duration seconds (0=until cleared)", "float", 3.0),),
    "Source Clear Minimap Markers": (),
    "Source Set Local Camera": _SOURCE_POINT,
    "Source Set Selected Unit Card": (_field("text", "Card/status message", "text", "Selected unit card changed"),),
    "Source Play Local Cinematic": (_field("text", "Cinematic/message", "text", "Cinematic"),),
    "Source Show Local Dialog": (_field("text", "Dialog text", "multiline", "Dialog"),),
})


KIND_HELP: dict[str, str] = {
    "Always": "Always true. Use this for triggers controlled only by their start delay, repeat interval, or actions.",
    "Never": "Always false. Useful for temporarily disabling a condition block without deleting it.",
    "Elapsed Time": "Compares seconds since Start Triggers was pressed. Use trigger-level Start delay for simpler one-shot timing.",
    "Command": "Counts matching units or buildings owned by a player anywhere or inside a location.",
    "Bring": "Counts matching units or buildings currently inside a named location.",
    "Unit Entered Location": "Event condition: counts matching units that crossed from outside to inside since the previous engine cycle. A unit remaining inside is counted only once; newly created units inside count as entries.",
    "Building Completed": "Counts matching completed structures; foundations still under construction do not count.",
    "Unit Created": "Fires from the live event snapshot when a matching object appears after the trigger engine starts.",
    "Unit Died": "Fires when a matching live object disappears through Warcraft's death path.",
    "Unit Removed": "Fires when a matching object is deliberately removed rather than killed.",
    "Corpse Count": "Counts live corpse records that match the owner, type, and location filters.",
    "Missile Count": "Counts active native projectile records by owner, firing unit, and missile type.",
    "Rune Count": "Counts active native Rune traps in a location.",
    "Hit Points": "Reads the first matching unit or building's current hit points.",
    "Mana": "Reads the first matching caster's current mana.",
    "Resources": "Compares a player's current Gold, Lumber, or Oil.",
    "Kills": "Compares Warcraft's cumulative men, building, or combined kill statistics.",
    "Player Killed": "Counts only newly credited kills since the previous trigger-engine cycle. Use this as an event condition for rewards and wave logic.",
    "Deaths": "Compares Warcraft's cumulative men, building, or combined death statistics.",
    "Score": "Compares Warcraft's live score table for one player.",
    "Switch": "Checks a named trigger-only boolean flag. Switches do not alter Warcraft memory.",
    "Counter": "Compares a named trigger-only integer such as Lives, Round, or Wave. Use Set/Add/Subtract Counter actions to change it.",
    "Game State": "Checks Playing, Victory, or Defeat from Warcraft's live game-mode state.",
    "Unit Property": "Reads one raw validated property from the first matching object, such as health, mana, action, or a spell timer.",
    "Display Text": "Writes a message only to the Trigger Studio live log.",
    "Game Message": "Displays Warcraft's native game-information slot. The selected color is written to the exact renderer-owned system color byte after map_msg resets it. Repeat is controlled by the trigger Preserve setting.",
    "Player Chat": "Sends a real Warcraft player-chat line through PM_STRING and the native rolling chat queue. The selected color is written to the exact renderer-owned color byte for the final rotating slot.",
    "Wait": "Delays only the actions below it. The scheduler resumes later without blocking the editor or Warcraft.",
    "Set Switch": "Sets or clears a named trigger-only flag for coordinating multiple triggers.",
    "Set Counter": "Sets a named trigger-only integer. Chat can display it with {counter(Lives)}.",
    "Add Counter": "Adds to a named trigger-only integer, useful for scores, rounds, and accumulated objectives.",
    "Subtract Counter": "Subtracts without going below zero, useful for tower-defense lives and limited attempts.",
    "Damage Units": "Calls Warcraft's native damage routine so deaths, scores, AI response, and attacker credit remain native.",
    "Set Hit Points": "Writes a validated hit-point value to every matching object.",
    "Set Mana": "Writes a validated mana value to every matching caster.",
    "Kill Units": (
        "Uses Warcraft's real kill path for matching objects. For end-of-route kill zones, it can "
        "also include units that Warcraft settled beside a crowded destination while retaining a "
        "move target inside the location."
    ),
    "Set Unit Property": "Changes one explicitly validated raw property. Unsupported properties remain blocked.",
    "Set Resources": "Replaces a player's selected resource total.",
    "Add Resources": "Adds to a player's selected resource total, clamped to Warcraft's supported range.",
    "Subtract Resources": "Subtracts from a player's selected resource total without going below zero.",
    "Award Kill Resources": "Awards resources once per newly credited native kill in the current trigger cycle. Example: 100 Gold for every Player 1 men/building kill.",
    "Create Units": "Creates mobile units or normal construction foundations through Warcraft's native allocator and placement path.",
    "Create Completed Buildings": "Creates a building foundation and completes it through Warcraft's native growth/completion bookkeeping.",
    "Remove Units": "Silently removes matching objects through validated map, owner-list, draw-list, and allocator cleanup.",
    "Move Units": "Teleports matching mobile units using Warcraft's placement validation and map matrix updates.",
    "Give Units": "Transfers ownership through Warcraft's native capture routine.",
    "Order": "Queues a native Move, destination Attack, or Patrol order. Attack uses only X/Y, never Patrol or trigger-selected enemy fields. Empty wave owners remain Empty while a runtime route tracker hands nearby enemies to Warcraft's native targeted Attack path and resumes the destination afterward. Repeating triggers skip unchanged routes by default.",
    "Create Missile": "Creates Warcraft-owned projectile records from matching ranged attackers toward matching targets.",
    "Cast Spell": "Uses Warcraft's native spell paths with native-aware eligibility. Unit-target spells reserve distinct targets per caster, skip busy casters and invalid/already-affected targets, and expose nearest/health priority controls. Healing never casts on full-health units. Native hero equivalents are accepted: Khadgar as a Mage; Turalyon/Uther as Paladins; Teron/Gul'dan as Death Knights; Dentarg/Cho'gall as Ogre-Mages. Ground-target spells can use a location, coordinates, or matching unit tiles.",
    "Modify Tile": "Authoring is available, but live execution remains locked until rendering, pathing, fog, and minimap refresh are validated together.",
    "Play Sound": "Plays one of the 17 validated native positional spell sounds at a location, tile, or matching unit.",
    "Run AI Script": "Authoring is available, but live execution remains locked until the exact native AI script contract is validated.",
    "Set Game Speed": "Changes Warcraft's native simulation speed using the original PM_SET_SPEED packet path. The seven native-verified levels are Slowest, Slower, Slow, Normal, Fast, Faster, and Fastest.",
    "Set Player Relations": "Edit every Player 1-8 alliance, shared-vision, and allied-victory setting in one exact matrix. Self-relations are locked on and cannot be undone.",
    "Building Count": "Counts completed normal buildings owned by a player, optionally restricted to one building type and location.",
    "Set Alliance": "Use the 8x8 checkbox grid directly. CHECKED means Allied; UNCHECKED means Enemy for other players. Self boxes stay locked Allied. Warcraft uses 1 for Allied and 0 for Enemy in the live relation table.",
    "Set Allied Victory": "Use the 8x8 checkbox grid to define each player’s intended allied-victory partners. A row with no cross-player partner has Allied Victory disabled. Warcraft’s native evaluator still excludes live Computer players.",
    "Set Shared Vision": "Use the 8x8 checkbox grid directly: each row is the vision source and each checked column receives that player’s vision. Self-vision is locked on. Offline Computer vision uses a private vision-mode byte read only by fog and unit-visibility routines, while the real command mode remains offline. Warcraft performs one native cache initialization when the matrix changes and no repeating rebuild.",
    "Victory": "Requests Warcraft's synchronized native victory transition and result flow.",
    "Defeat": "Requests Warcraft's synchronized native defeat transition and result flow.",
}


VALUE_HELP = {
    "amount": "Use All where supported, otherwise enter an integer.",
    "location": "Named locations are created with the Locations button in the main toolbar.",
}


def players_label(value: Any, fallback: int = 0) -> str:
    if value is None:
        players = [fallback]
    elif isinstance(value, (list, tuple, set)):
        players = sorted(set(int(player) for player in value))
    else:
        players = [int(value)]
    if players == list(range(8)):
        return "Players 1-8"
    return ", ".join(f"Player {player + 1}" for player in players) if players else "No players"


def unit_label(value: Any) -> str:
    if value == "Any" or value is None:
        return "Any unit"
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    return f"{UNIT_NAMES[number]} ({number})" if 0 <= number < len(UNIT_NAMES) else f"Unit {number}"


KIND_HELP.update({
    "Random Chance": "Rolls 1-100 each evaluation. At most 25 is a 25% chance.",
    "Countdown Timer": "Compares a named non-blocking countdown timer's remaining seconds.",
    "Timer Expired": "True after a named countdown has been started and reaches zero.",
    "Variable": "Compares a named numeric variable. Variables support full arithmetic and message tokens.",
    "Player Status": "Checks whether a live owner slot is Human, Computer, Neutral, or Empty.",
    "Unit Left Location": "Event condition: matching units crossed from inside to outside since the prior cycle.",
    "Unit Stayed In Location": "Counts units continuously inside a named location for the requested duration.",
    "Unit Damaged": "Event condition generated from live HP loss between engine cycles.",
    "Unit Healed": "Event condition generated from live HP gain between engine cycles.",
    "Unit Under Attack": "Event condition generated when Warcraft raises SF_UNDER_ATTACK.",
    "Random Wait": "Pauses only this trigger action sequence for a random duration; Warcraft never sleeps.",
    "Run Trigger": "Calls another trigger's actions like a function while preserving recursion safety.",
    "Move Location": "Moves a named rectangle at runtime without modifying the map file.",
    "Follow Unit With Location": "Continuously centers a dynamic location on the first matching live unit.",
    "Replace Units": "Creates a replacement through Warcraft's native constructor and safely removes the old mobile unit.",
    "Apply Status Effect": "Writes native-verified native spell timers for Bloodlust, Haste, Slow, Invisibility, Unholy Armor, or Flame Shield.",
    "Display Leaderboard": "Builds a live P1-P8 leaderboard and displays it through the validated native game-message path.",
    "Make Invincible": "Uses Warcraft's native-verified Unholy Armor timer as native damage immunity without forcing a caster.",
    "Complete Buildings": "Finishes matching foundations through Warcraft's validated grow_structure lifecycle.",
    "Center Camera": "Centers the local camera on a named location or tile through Warcraft's validated camera routine.",
    "Assert": "Logs success or raises a recoverable action error when a variable, counter, or timer does not match.",
    "Breakpoint": "Pauses trigger evaluation after the current action without pausing Warcraft. Use Continue or Step in the toolbar.",
})

KIND_HELP.update({
    "Expression": "Evaluates a sandboxed arithmetic expression using variables, counters, timers, named unit groups, event data, and random values.",
    "Unit Group Count": "Counts live members of a named persistent unit group.",
    "Unit Group Empty": "True when a named unit group has no surviving live members.",
    "Objective State": "Checks whether an objective is active, completed, or missing.",
    "Event Available": "Checks whether a supported live event occurred during the current trigger cycle.",
    "Create Wave": "Creates a formation, saves exact spawned units to a named group, and optionally gives the entire wave a native Move, Attack, or Patrol order.",
    "Save Unit Group": "Captures exact live unit references into a named group for later actions.",
    "Add Units To Group": "Adds matching live units to an existing named group.",
    "Clear Unit Group": "Forgets a named unit group without changing the units.",
    "Order Unit Group": "Orders only the exact surviving members of a named group.",
    "Set Unit Group Health Percent": "Sets health on the exact surviving members of a named group.",
    "Move Location To Event Unit": "Centers a location on the event unit that satisfied this trigger.",
    "Create Units At Event": "Creates units at the current event coordinates.",
    "Set Variable From Event": "Copies event player, unit type, coordinates, health, mana, type, or amount into a variable.",
    "Set Variable From Expression": "Stores a sandboxed expression result in a variable.",
    "Set Counter From Expression": "Stores a sandboxed expression result in a counter.",
    "Log Event Context": "Writes all current event fields to the runtime log.",
    "Auto Spellcasting": "Checks whether a player's smart automatic native spell controller is enabled.",
    "Enable Auto Spellcasting": "Enables smart spells for Mage, Paladin, Ogre-Mage, Death Knight, and caster heroes. Only a caster with a valid spell pauses for one cast; its saved combat route resumes afterward. Healing and Flame Shield use atomic source-equivalent effects while remaining spells use native do_unit_spell.",
    "Disable Auto Spellcasting": "Stops automatic spell selection for one player without changing existing spell effects.",
    "Auto Cast Spells Now": "Runs one smart pass. Routed casters may first receive a safe parking order; the following maintenance pass casts after Guard settles.",
})

KIND_HELP.update({
    "Unit Reference Exists": "Checks whether a named persistent unit handle still resolves to the same live allocation token.",
    "Unit Reference Alive": "Checks the exact referenced unit rather than all units of the same type.",
    "Upgrade Level": "Reads the native-verified per-player native upgrade-level byte for the selected technology row.",
    "Spell Researched": "Checks the selected native glSpells research bit for one player.",
    "Spell Allowed": "Checks whether the scenario currently allows the selected native spell research bit.",
    "Save Unit Reference": "Stores one exact live unit using its address plus allocation token, preventing recycled-slot confusion.",
    "Run Trigger For Each Unit In Group": "Calls another trigger once for each exact live group member while exposing it as a named loop reference.",
    "Run Trigger For Each Player": "Calls another trigger for every P1-P8 player or every member of a named Force.",
    "Give Spell": "Sets the selected player’s native spell-researched bit and ensures the corresponding allowed bit is enabled. This grants normal eligible casters access to that researched spell.",
    "Remove Spell": "Clears one native researched-spell bit without modifying unrelated spells.",
    "Set Spell Allowed": "Enables or disables one scenario-level spell permission; disabling also clears that researched bit.",
    "Set Upgrade Level": "Writes one native-verified native player upgrade level. Levels 0-2 match Warcraft II's native progression range.",
    "Give All Upgrades": "Sets every native-verified upgrade row to level 2 for the selected player.",
    "Enable Advanced Unit Classes": "Grants the Paladin/Ogre-Mage conversion research and replaces existing Knights/Ogres with their advanced caster classes.",
    "Create Sapper Assault": "Creates Dwarves or Goblins as an exact group and immediately publishes Warcraft’s real demolition order toward a tile or referenced target.",
    "Order Sappers Demolish": "Orders existing Dwarves/Goblins through the native-verified do_unit_demolish function.",
    "Arm Sappers": "Adds a harmless trigger tag for sapper logic. It intentionally avoids native Invisibility/Unholy Armor timers, which make sappers explode in the source logic.",
    "Apply Stun": "Temporarily parks matching units with a target-less native order.",
    "Apply Silence": "Blocks smart automatic spell selection for matching casters while the effect is active.",
    "Apply Damage Over Time": "Applies bounded periodic native unit damage with allocation-token validation.",
    "Add Shield": "Adds a trigger-level damage-absorbing shield that is consumed before HP loss is retained.",
    "Set Critical Strike": "Adds a trigger-level post-hit critical strike chance and multiplier.",
    "Redirect Projectiles": "Retargets matching live projectile records toward a new tile while clearing their unit target pointer.",
    "Projectile Created": "Event condition raised for projectiles that appeared since the previous engine cycle.",
    "Enable Tactical AI": "Maintains a named exact unit group using attack, retreat, or hold-formation behavior without enabling Warcraft’s strategy AI.",
    "Start TD Stream Wave": "Streams hundreds of mixed-roster TD creeps in centered lanes. Uses a real absolute native max-HP table value so current/max HP and health bars agree; naval roster types can be temporarily converted to flyers.",
    "Stop TD Stream Wave": "Stops future batches for a named TD stream wave while leaving already-spawned units alive.",
    "Start TD Native HP Ladder": "Runs one wave for every real mobile unit ID 0-57 except reserved slots. At runtime it reads Warcraft's native max-HP table, sorts the 53 usable types weakest-to-strongest, then increases both absolute HP and unit count while streaming each type through the centered TD route.",
    "Stop TD Native HP Ladder": "Stops the named native-HP ladder and restores the active wave's temporary max-HP/movement type overrides.",
    "Start Wave Director": "Runs escalating waves from a weighted unit-ID pool, exact groups, formations, intermissions, boss intervals, and optional endless mode.",
    "Start Boss Controller": "Runs JSON-defined health phases for one persistent boss reference, including messages, adds, and temporary invulnerability.",
    "Register Hero": "Adds trigger-level XP, levels, and HP growth to one persistent unit reference without replacing Warcraft’s native score system.",
    "Transmission": "Displays a speaker-labelled native message and can center the camera on a referenced unit.",
    "Refill Resource Node": "Refills only Gold Mine or Oil Patch resource objects through their native-verified resource word.",
    "Train Units Instantly At Buildings": "Creates units beside each selected building and saves the exact results as a named group.",
    "Watch Expression": "Evaluates and logs a safe trigger expression for live debugging.",
})

KIND_HELP.update({
    "Call Trigger Function": "Calls another trigger synchronously with JSON arguments, local variables, a return value, recursion protection, and a 16-frame depth limit. Function triggers cannot contain Wait, Random Wait, or Breakpoint.",
    "Set Local Variable": "Sets a function-local value. var('name') resolves locals before global variables while the function is running.",
    "Return From Function": "Returns a value immediately from the current synchronous trigger function without marking that trigger complete.",
    "Create List": "Creates a runtime list from JSON or comma-separated values for loot tables, rotations, and scripted sequences.",
    "Choose Random List Item": "Selects one runtime-list entry and stores it in a global variable.",
    "Trigger Cooldown Ready": "Checks a named trigger-only cooldown without blocking Warcraft or other triggers.",
    "Register Shop Item": "Defines price, stock, use effect, equipment slot, and optional attribute bonuses for a trigger-level shop item.",
    "Buy Shop Item": "Charges native Gold/Lumber/Oil or a named custom currency and places the purchased item in the exact referenced unit's inventory.",
    "Equip Inventory Item": "Equips an owned item into a trigger-level slot. Registered attribute bonuses are included in Hero Attribute conditions.",
    "Use Inventory Item": "Consumes a registered item and applies its safe HP, mana, XP, shield, status, or custom-currency effect.",
    "Hero Attribute": "Reads a trigger-level hero attribute including bonuses from equipped registered items.",
    "Learn Hero Skill": "Spends trigger-level skill points to raise a named skill for one persistent hero reference.",
    "Enable Aura": "Runs a bounded periodic aura around an exact source reference. It can regenerate HP/mana, damage, shield, silence, or refresh validated native status timers.",
    "Unit In Aura": "Counts selected units currently inside a named aura after relation, radius, and optional exact-group filtering.",
    "Start Squad Controller": "Maintains an exact group as a formation, preserves active combat and spell casts, tracks morale from surviving members, and can retreat below a threshold.",
    "Rally Squad": "Immediately reforms and orders the selected squad controller without waiting for its normal cadence.",
    "Start Reinforcement Director": "Runs a JSON schedule of staged Create Wave definitions. Only one due stage is published per maintenance pass to avoid burst mailbox contention.",
    "Start Vote": "Creates a trigger-driven vote state for All Players or a named Force. Cast Vote actions provide the player input; this does not claim to parse Warcraft chat.",
    "Close Vote": "Counts registered choices, resolves a winner or tie result, and stores the result in a variable.",
    "Unit Group Average Health Percent": "Returns the average live health percentage of an exact named unit group.",
    "Dump World Systems": "Logs counts for runtime functions, lists, shops, auras, squad controllers, reinforcement directors, and votes.",
})


KIND_HELP.update({
    "Source Production State": "Reads the source TBuild order and UF_BUILD_ON flag to distinguish training, technology, spell research, building upgrades, and idle state.",
    "Source Production Progress": "Reads bldCurr/bldTotal and returns native completion percentage.",
    "Source Transport Cargo Count": "Counts the six source transport cargo-slot indices.",
    "Source Unit Is Loaded": "Checks whether the exact unit slot is present in a live transport's source cargo list.",
    "Source Tile Value": "Reads the live 16-bit MTXM value at one tile. Use this to discover exact tileset IDs for tree, rock, wall, and demolishable filters.",
    "Source Location Walkable": "Calls Warcraft's native unit-placeability query for the selected prototype unit at the requested tile.",
    "Source Guard": "Publishes a target through unit_set_target and the source do_unit_guard callback.",
    "Source Follow": "Publishes a real follow order toward the nearest matching target unit.",
    "Source Attack Ground": "Uses Warcraft's source do_unit_attack_ground callback, including its movement-to-range behavior.",
    "Source Demolish": "Uses the native sapper demolition callback against a matching unit or an authored map tile.",
    "Source Harvest": "Resets the worker harvest counter and enters Warcraft's native gold/lumber/oil harvesting order.",
    "Source Repair": "Uses the native peon repair callback; only buildings and transports are accepted by Warcraft.",
    "Source Return Resources": "Invokes the native return routine, which finds a valid drop-off point when no target is supplied.",
    "Source Board Transport": "Orders passengers toward a same-owner transport so Warcraft's native auto-pickup and entry sequence can load them safely.",
    "Source Unload Transport Unit": "Calls source unit_order_unload_transport for one matching cargo unit while the transport is docked or unloading.",
    "Source Train Unit": "Calls bldg_build_start with BUILD_UNIT. Warcraft checks cost, prerequisites, busy state, and production timing.",
    "Source Research Technology": "Calls bldg_build_start with BUILD_TECH and the source technology row.",
    "Source Research Spell": "Calls bldg_build_start with BUILD_SPELL and the source spell-research index.",
    "Source Upgrade Building": "Starts a native BUILD_UPGRADE operation such as Town Hall to Keep or Great Hall to Stronghold.",
    "Source Cancel Production": "Sets UF_BUILD_CANCEL and lets the native building dispatcher perform cancellation and refunds.",
    "Source Complete Production": "Advances bldCurr to bldTotal and invokes the native building dispatcher once.",
    "Source Give Worker Cargo": "Writes the source PEON_LOADED, gold/lumber flags, and cargo word. Oil uses LOADED without gold/lumber bits.",
    "Source Deposit Worker Cargo": "Adds carried cargo to the worker owner's native resource table and clears the source cargo fields atomically.",
    "Source Set Tiles": "Experimental live MTXM mutation. It changes displayed tile data but some terrain/pathing/minimap caches may require a native region rebuild or camera refresh.",
    "Source Remove Trees": "Replaces only MTXM values listed in Tile values; it refuses an empty filter to avoid erasing unrelated terrain.",
    "Source Damage Walls": "Uses native damage_damage_unit with a real attacker so damage and kill credit remain source-compatible.",
    "Source Find Walkable Point": "Searches Warcraft's native placement candidates and stores the resulting tile in variables and Source Last Found X/Y.",
    "Source Acquire Best Target": "Chooses the nearest relation-valid target and publishes a native attack-target order without enabling strategy AI.",
    "Source Convert Unit Type": "Uses the validated replacement system while preserving owner, position, and optionally health percentage.",
    "Source Play Animation": "Writes source sequence timer/action/frame/facing bytes atomically and marks the record for redraw.",
    "Source Freeze Animation": "Maintains source sequence fields every runtime cycle while leaving HP, target, orders, and ownership untouched.",
    "Source Play Unit Sound": "Calls validated contextual selection, under-attack, harvest, unit-death, building-destruction, or spell sound routines for matching live units.",
    "Source Play Explosion Sound At Point": "Calls the source gamesnd_explode tile-position routine without creating or damaging an object.",
    "Source Create Projectile At Point": "Calls the native bullet_create_xy constructor with pixel-aligned coordinates and a source missile type.",
    "Source Create Projectile Between Units": "Uses Warcraft's native attacker projectile assignment and target path.",
    "Source Blizzard Volley": "Routes through the validated Cast Spell implementation with Blizzard selected.",
})


# 1.28 tooltips.  Exact callbacks, safe deterministic wrappers, local-only UI,
# and trigger-owned compatibility layers are identified instead of being mixed.
for _kind in SOURCE128_CONDITIONS:
    KIND_HELP.setdefault(_kind, "Reads a Warcraft II source-derived 1.28 runtime value. Boolean results compare as 1/0; numeric results use the selected comparison.")
for _kind in SOURCE128_ACTIONS:
    KIND_HELP.setdefault(_kind, "Runs a guarded Warcraft II source-derived 1.28 action. Exact native callbacks execute on the simulation dispatcher; compatibility systems use deterministic trigger-owned state when no Remaster callback is proven.")
KIND_HELP.update({
    "Source Order Worker To Build": "Creates a real unfinished foundation through Warcraft's validated unit constructor, then gives matching workers the native repair/build target. It does not create a completed building.",
    "Source Place Building Foundation": "Creates an unfinished building foundation using the same native allocator and grow-structure lifecycle used by Create Units.",
    "Source Unit Can Reach Location": "Runs a bounded graph search whose nodes are accepted by Warcraft's native mtx_unit_placeable query. This is stronger than checking only the destination tile.",
    "Source Locations On Same Island": "Uses the selected prototype unit and native placeability to prove a bounded route between two points. Raise the node limit for large maps.",
    "Source Calculate Native Damage": "Calls Warcraft's source-matched damage_unit_vs_unit roll and stores the total without applying it. Because this is the real native roll, it advances synchronized combat RNG.",
    "Source Predicted Native Damage": "Computes a deterministic source-compatible estimate from the native strength, piercing, and armor functions without consuming the random damage roll.",
    "Source Deal Native Attack Damage": "Rolls damage through damage_unit_vs_unit, then applies it through damage_damage_unit so death, credit, score, and retaliation remain native.",
    "Source Damage Terrain": "Calls the validated damage_damage_mtx routine for every tile in the bounded region.",
    "Source Reveal Area For Player": "Tiles Warcraft's validated 19x19 Holy Vision unmask callback across the selected area. The runtime remembers these trigger reveals for visibility/exploration conditions.",
    "Source Refresh Fog": "Republishes trigger-owned reveals through the native fog callback. The normal live dispatcher still performs Warcraft's post-mask local fog composition.",
    "Source Run Native Retaliation": "Uses the source attacker pointer and validated native attack-target callback. It does not enable the full legacy ICE strategy globals.",
    "Source Rebuild Wall Connections": "Safe compatibility rebuild: invalidates trigger path caches and forces Warcraft placement queries across the edited region. It deliberately avoids calling an unverified legacy wall-region address.",
    "Source Pause Production": "Freezes only bldCurr/bldTotal/mana progress every trigger cycle; Warcraft's simulation and the trigger engine continue running.",
    "Source Queue Unit": "Adds a trigger-owned queue entry. When the building becomes idle, the runtime calls the validated bldg_build_start routine.",
    "Source Enable Continuous Training": "Restarts the selected native unit production whenever the building becomes idle. Native affordability/prerequisite checks still decide whether each start succeeds.",
    "Source Worker Can Return Resources": "Checks native worker cargo flags and searches same-owner Town Hall/Lumber/Oil return-capable source classes.",
    "Source Rune Owner": "Returns -1 because Warcraft's native rune table stores X, Y, and lifetime but no owner field.",
    "Source Place Rune": "Places a native ownerless Rune at the selected point. Warcraft's rune table does not store a player owner.",
    "Source Complete Harvest Cycle": "Sets native worker cargo flags and amount for Gold, Lumber, or Oil so the worker can be returned through the normal deposit path.",
    "Source Location Is Explored": "Reports areas revealed by 1.28 reveal actions. The Remaster's historical explored-mask layout is not guessed, so naturally explored-but-not-trigger-revealed areas may report false.",
    "Source Set Spell Mana Cost": "Writes the validated gwCastingCost entry for the selected source spell action. Restore All Vanilla Rules returns any changed cost to its attach-time value.",
    "Source Freeze Projectile": "Maintains projectile X/Y, target coordinates, and lifetime without suspending Warcraft's bullet loop.",
    "Source Set Projectile Speed": "A bounded trigger-owned speed correction layered over the native projectile record. Collision/action fields remain owned by Warcraft.",
    "Source Enable Unit Rescue": "Sets UF_RESCUE and enables deterministic source-range capture checks. Ownership transfer uses the already validated Give Units/capture path.",
    "Source Run Native Build Strategy": "Safe source-order strategy wrapper. It follows the authored AI Build Goal using validated foundation creation and worker repair instead of touching legacy-only ICE global tables.",
    "Source Run Native Spell AI": "Runs the established native-aware automatic spell pass for matching caster owners; no unverified legacy strategy pointer is called.",
    "Source Set Unit Type Maximum HP": "Changes the proven live global unit HP table. Existing units are optionally clamped; future native units use the changed maximum until restored.",
    "Source Set Unit Type Armor": "Changes the proven live global armor byte for the selected type until restored.",
    "Source Set Unit Type Basic Damage": "Changes the proven native strength table byte for the selected type until restored.",
    "Source Set Unit Type Piercing Damage": "Changes the proven native piercing table byte for the selected type until restored.",
    "Source Set Unit Type Projectile": "Changes the proven native projectile-assignment table byte for the selected type until restored.",
    "Source Set Unit Type Attack Range": "Stores a trigger-owned Remaster compatibility override used by 1.28 targeting systems. No unproven global range RVA is written.",
    "Source Set Unit Type Sight": "Stores a trigger-owned sight override used by 1.28 visibility checks and reveal helpers. Native fog range pointers are not guessed.",
    "Source Set Unit Type Speed": "Stores a trigger-owned speed percentage and applies native Haste state to matching current units when above normal.",
    "Source Set Unit Type Gold Cost": "Stores a trigger-owned cost override used by 1.28 affordability conditions. Native UI/DAT cost arrays are not guessed.",
    "Source Restore All Vanilla Rules": "Restores every exact table entry saved before its first write and clears all trigger-owned compatibility overrides.",
    "Source Lock Player Input": "Local Trigger Studio state only. It is intentionally not used to make synchronized gameplay decisions or patch unverified Remaster input callbacks.",
    "Source Set Selected Unit Card": "Local compatibility helper. Displays the authored card/status text safely instead of calling a legacy UI pointer that is not proven in the Remaster.",
    "Source Play Local Cinematic": "Local compatibility helper that publishes the authored cinematic text through the validated native message system; it does not call legacy FMV routines.",
})



# ---------------------------------------------------------------------------
# 1.29 campaign/cutscene schemas and help.
_CAMPAIGN_OBJ_STATES = ("Active", "Completed", "Failed", "Hidden", "Missing")
_CUTSCENE_STATES = ("Inactive", "Active")
_SCENE_ACTOR_STATES = ("Alive", "Dead", "Hidden", "Removed", "Missing")
_SCENE_ACTOR = (_field("actor", "Scene actor / unit reference", "text", "Archer"),)
_SCENE_POINT = (
    _field("destination", "Destination", "location", "Anywhere"),
    _field("x", "Tile X", "int", 0, optional=True),
    _field("y", "Tile Y", "int", 0, optional=True),
)

CONDITION_SCHEMAS.update({
    "Campaign Objective State": (
        _field("name", "Objective name", "text", "Objective 1"),
        _field("state", "State", "choice", "Active", _CAMPAIGN_OBJ_STATES),
    ),
    "Cutscene State": (_field("state", "State", "choice", "Active", _CUTSCENE_STATES),),
    "Scene Actor State": _SCENE_ACTOR + (_field("state", "State", "choice", "Alive", _SCENE_ACTOR_STATES),),
    "Scene Actor At Location": _SCENE_ACTOR + (
        _field("location", "Location", "location", "Anywhere"),
        _field("x", "Tile X", "int", 0, optional=True),
        _field("y", "Tile Y", "int", 0, optional=True),
        _field("radius", "Arrival radius", "int", 0),
    ) + COUNT_FIELDS,
    "Campaign Rescue Count": (_field("player", "Rescuing player", "player", 0),) + COUNT_FIELDS,
    "Campaign Capture Count": (_field("player", "Receiving player", "player", 0),) + COUNT_FIELDS,
    "Campaign Rescue Possible": (
        _field("player", "Rescuing player", "player", 0),
        _field("required", "Required rescue total", "int", 1),
    ) + COUNT_FIELDS,
    "Campaign Rescue Goal Met": (_field("player", "Rescuing player", "player", 0),) + COUNT_FIELDS,
    "Campaign Player Eliminated": (_field("player", "Player", "player", 1),) + COUNT_FIELDS,
    "Campaign Player Alive": (_field("player", "Player", "player", 0),) + COUNT_FIELDS,
    "Campaign Genocide Complete": (
        _field("target_player", "Target owner (-1 = all other P1-P8)", "int", -1),
    ) + COUNT_FIELDS,
    "Campaign Unit Type Remaining": (
        _field("player", "Player", "player", 1),
        _field("unit", "Unit type", "unit", 0),
    ) + COUNT_FIELDS,
    "Campaign Unit Type Destroyed": (
        _field("player", "Player", "player", 1),
        _field("unit", "Unit type", "unit", 0),
    ) + COUNT_FIELDS,
    "Campaign Completed Building Count": (
        _field("player", "Player", "player", 0),
        _field("unit", "Building type", "unit", "Any"),
    ) + COUNT_FIELDS,
    "Campaign Building Type Destroyed": (
        _field("player", "Player", "player", 1),
        _field("unit", "Building type", "building", 58),
    ) + COUNT_FIELDS,
    "Campaign All Actors In Location": (
        _field("actors", "Actor names, comma-separated", "text", "Turalyon, Danath, Alleria"),
        _field("location", "Destination", "location", "Anywhere"),
        _field("x", "Tile X", "int", 0, optional=True),
        _field("y", "Tile Y", "int", 0, optional=True),
        _field("radius", "Radius", "int", 1),
    ) + COUNT_FIELDS,
    "Campaign All Actors Alive": (
        _field("actors", "Actor names, comma-separated", "text", "Turalyon, Danath, Alleria"),
    ) + COUNT_FIELDS,
    "Campaign Any Actor Dead": (
        _field("actors", "Actor names, comma-separated", "text", "Turalyon, Danath, Alleria"),
    ) + COUNT_FIELDS,
})

_OBJECTIVE_COMMON = (
    _field("name", "Objective name", "text", "Objective 1"),
    _field("announce", "Announce change", "bool", True),
    _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
    _field("color", "Message color", "choice", "Yellow / gold — native normal", PLAYER_CHAT_COLORS),
    _field("seconds", "Message seconds", "int", 4),
)
ACTION_SCHEMAS.update({
    "Set Campaign Objective": (
        _field("name", "Objective name", "text", "Objective 1"),
        _field("text", "Objective text", "multiline", "Defend the base"),
        _field("announce", "Announce objective", "bool", True),
        _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
        _field("color", "Message color", "choice", "Yellow / gold — native normal", PLAYER_CHAT_COLORS),
        _field("seconds", "Message seconds", "int", 4),
    ),
    "Complete Campaign Objective": _OBJECTIVE_COMMON,
    "Fail Campaign Objective": _OBJECTIVE_COMMON,
    "Hide Campaign Objective": _OBJECTIVE_COMMON,
    "Show Campaign Objective": _OBJECTIVE_COMMON,
    "Clear Campaign Objective": _OBJECTIVE_COMMON,
    "Clear All Campaign Objectives": (),
    "Use Trigger Objectives": (),
    "Restore Map Objectives": (),
    "Show Objectives HUD": (
        _field("refresh_seconds", "Refresh every seconds", "float", 3.5),
        _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
        _field("color", "HUD color", "choice", "Yellow / gold — native normal", PLAYER_CHAT_COLORS),
    ),
    "Hide Objectives HUD": (),
    "Refresh Objectives HUD": (),
    "Set Rescue Goal": (
        _field("player", "Player", "player", 0),
        _field("amount", "Required rescues", "int", 1),
    ),
    "Show Mission Briefing": (
        _field("title", "Mission title", "text", "Mission Briefing"),
        _field("story", "Briefing / dispatch text", "multiline", "Your forces have arrived..."),
        _field("objectives", "Objective lines (blank = current objectives)", "multiline", "", optional=True),
        _field("seconds", "Display seconds", "float", 8.0),
        _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
        _field("color", "Text color", "choice", "White — native highlight", PLAYER_CHAT_COLORS),
    ),
    "Show Act Card": (
        _field("title", "Act title", "text", "ACT I"),
        _field("subtitle", "Subtitle", "text", "The Gathering Storm"),
        _field("seconds", "Display seconds", "float", 4.0),
        _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
        _field("color", "Text color", "choice", "White — native highlight", PLAYER_CHAT_COLORS),
    ),
    "Show Epilogue": (
        _field("text", "Epilogue text", "multiline", "Victory!"),
        _field("seconds", "Display seconds", "float", 10.0),
        _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
        _field("color", "Text color", "choice", "White — native highlight", PLAYER_CHAT_COLORS),
    ),
    "Show Credits": (
        _field("text", "Credits text", "multiline", "Created with Warcraft II Trigger Studio"),
        _field("seconds", "Display seconds", "float", 10.0),
        _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
        _field("color", "Text color", "choice", "White — native highlight", PLAYER_CHAT_COLORS),
    ),
    "Begin Cutscene": (
        _field("name", "Scene name", "text", "Intro Scene"),
        _field("mark_input_locked", "Mark local input locked", "bool", True, help="Authoring state only; 1.29 does not patch unverified Remaster input callbacks."),
        _field("hide_objectives", "Hide objective banner during scene", "bool", True),
        _field("deselect_units", "Deselect current units", "bool", True),
    ),
    "End Cutscene": (_field("restore_camera", "Restore pre-scene camera", "bool", True),),
    "Scene Create Actor": (
        _field("actor", "Actor name / reference", "text", "Archer"),
        _field("player", "Owner", "player", 0),
        _field("unit", "Unit type", "unit", 8),
        _field("location", "Spawn location", "location", "Anywhere"),
        _field("x", "Tile X", "int", 10, optional=True),
        _field("y", "Tile Y", "int", 10, optional=True),
        _field("facing", "Facing 0=N ... 7=NW", "int", 4),
        _field("invincible", "Start invincible", "bool", False),
    ),
    "Scene Save Actor": (_field("actor", "Actor name / reference", "text", "Archer"),) + COMMON_UNIT_FIELDS,
    "Scene Clear Actor": _SCENE_ACTOR,
    "Scene Actor Talk": _SCENE_ACTOR + (
        _field("speaker", "Speaker label", "text", "Archer"),
        _field("text", "Dialogue", "multiline", "We cannot hold them much longer!"),
        _field("voice_bark", "Play native unit voice bark", "bool", True),
        _field("center_camera", "Cut camera to actor", "bool", False),
        _field("wait", "Wait for line duration", "bool", True),
        _field("seconds", "Line duration", "float", 4.0),
        _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
        _field("color", "Dialogue color", "choice", "White — native highlight", PLAYER_CHAT_COLORS),
    ),
    "Scene Actor Walk": _SCENE_ACTOR + _SCENE_POINT + (
        _field("wait_for_arrival", "Wait until actor arrives", "bool", True),
        _field("arrival_radius", "Arrival radius", "int", 1),
        _field("timeout", "Timeout seconds (0=no timeout)", "float", 30.0),
        _field("on_timeout", "On timeout", "choice", "Continue", ("Continue", "Teleport", "Error")),
    ),
    "Scene Actor Patrol": _SCENE_ACTOR + _SCENE_POINT + (
        _field("wait_for_arrival", "Wait until actor reaches patrol point", "bool", False),
        _field("arrival_radius", "Arrival radius", "int", 1),
        _field("timeout", "Timeout seconds", "float", 30.0),
        _field("on_timeout", "On timeout", "choice", "Continue", ("Continue", "Teleport", "Error")),
    ),
    "Scene Actor Attack": _SCENE_ACTOR + (
        _field("target_actor", "Target actor/reference (optional)", "text", "", optional=True),
    ) + _SCENE_POINT + (
        _field("wait_for_target_death", "Wait until target dies", "bool", False),
        _field("timeout", "Timeout seconds", "float", 30.0),
    ),
    "Scene Actor Guard": _SCENE_ACTOR,
    "Scene Actor Stop": _SCENE_ACTOR,
    "Scene Actor Face": _SCENE_ACTOR + (_field("facing", "Facing 0=N ... 7=NW", "int", 0),),
    "Scene Actor Look At Actor": _SCENE_ACTOR + (_field("target_actor", "Target actor/reference", "text", "Target"),),
    "Scene Actor Play Animation": _SCENE_ACTOR + (
        _field("animation", "Native animation/action byte", "int", 0),
        _field("frame", "Frame", "int", 0),
        _field("facing", "Facing 0-7", "int", 0, optional=True),
        _field("timer", "Sequence timer", "int", 1),
        _field("seconds", "Hold action before continuing", "float", 0.0),
    ),
    "Scene Actor Die": _SCENE_ACTOR,
    "Scene Actor Remove": _SCENE_ACTOR,
    "Scene Actor Hide": _SCENE_ACTOR,
    "Scene Actor Show": _SCENE_ACTOR,
    "Scene Actor Teleport": _SCENE_ACTOR + _SCENE_POINT,
    "Scene Actor Set HP": _SCENE_ACTOR + (_field("amount", "Hit points", "int", 100),),
    "Scene Actor Set Mana": _SCENE_ACTOR + (_field("amount", "Mana", "int", 255),),
    "Scene Actor Damage From Actor": _SCENE_ACTOR + (
        _field("attacker_actor", "Attacker actor/reference", "text", "Attacker"),
        _field("amount", "Native damage", "int", 20),
    ),
    "Scene Actor Change Owner": _SCENE_ACTOR + (_field("new_owner", "New owner", "player", 0),),
    "Scene Actor Invincible": _SCENE_ACTOR,
    "Scene Actor Vulnerable": _SCENE_ACTOR,
    "Scene Actor Rescuable": _SCENE_ACTOR,
    "Scene Actor Not Rescuable": _SCENE_ACTOR,
    "Scene Wait For Actor State": _SCENE_ACTOR + (
        _field("state", "Required state", "choice", "Dead", _SCENE_ACTOR_STATES),
        _field("timeout", "Timeout seconds (0=no timeout)", "float", 0.0),
        _field("on_timeout", "On timeout", "choice", "Continue", ("Continue", "Error")),
    ),
    "Scene Wait For Actor At Location": _SCENE_ACTOR + _SCENE_POINT + (
        _field("radius", "Arrival radius", "int", 1),
        _field("timeout", "Timeout seconds (0=no timeout)", "float", 30.0),
        _field("on_timeout", "On timeout", "choice", "Continue", ("Continue", "Error")),
    ),
    "Scene Wait For All Actors At Location": (
        _field("actors", "Actor names, comma-separated", "text", "Archer, Grunt"),
    ) + _SCENE_POINT + (
        _field("radius", "Arrival radius", "int", 1),
        _field("timeout", "Timeout seconds (0=no timeout)", "float", 30.0),
        _field("on_timeout", "On timeout", "choice", "Continue", ("Continue", "Error")),
    ),
    "Scene Camera Cut": _SCENE_POINT,
    "Scene Camera Pan": _SCENE_POINT + (
        _field("seconds", "Pan duration", "float", 2.0),
        _field("step_seconds", "Pan update interval", "float", 0.08),
    ),
    "Scene Camera Follow Actor": _SCENE_ACTOR + (_field("cadence", "Camera update seconds", "float", 0.20),),
    "Scene Stop Camera Follow": (),
    "Scene Camera Shake": (
        _field("magnitude", "Shake radius in tiles", "int", 1),
        _field("seconds", "Shake duration", "float", 0.75),
    ),
    "Scene Play Sound": (
        _field("actor", "Actor/reference (blank = point sound)", "text", "", optional=True),
        _field("event", "Actor sound event", "choice", "Selection", ("Selection", "Under Attack", "Harvest", "Unit Death", "Building Destruction", "Spell", "Explosion")),
        _field("sound", "Spell sound fallback", "sound", "Thunder"),
        _field("destination", "Point sound location", "location", "Anywhere"),
        _field("x", "Tile X", "int", 0, optional=True),
        _field("y", "Tile Y", "int", 0, optional=True),
    ),
})

KIND_HELP.update({
    "Campaign Objective State": "Reads 1.29's authored campaign objective state: Active, Completed, Failed, Hidden, or Missing.",
    "Cutscene State": "Tests whether the 1.29 cinematic director is currently inside Begin Cutscene / End Cutscene.",
    "Scene Actor State": "Tests a named generation-safe unit reference used by the scene director.",
    "Scene Actor At Location": "Checks whether a named scene actor is within the authored tile radius.",
    "Campaign Rescue Count": "Cumulative rescue count derived from the native-verified UF_RESCUE / Give Units rescue path.",
    "Campaign Capture Count": "Counts live owner changes received by a player during the current trigger run.",
    "Campaign Rescue Possible": "Source reference module-style rescue feasibility: already rescued plus currently rescue-enabled units must still be able to satisfy the required total.",
    "Campaign Rescue Goal Met": "Checks the cumulative rescued count against Set Rescue Goal for that player.",
    "Campaign Player Eliminated": "Source reference module slot_alive-style check: buildings plus non-tanker/non-transport/non-flyer men. Auxiliary naval/air units do not keep the slot alive.",
    "Campaign Player Alive": "Inverse of Campaign Player Eliminated using reference module slot_alive semantics.",
    "Campaign Genocide Complete": "Source reference module VIC_GENOCIDE-style check against one owner or all other P1-P8 owners, excluding tanker/transport/flyer men from the required kill count.",
    "Campaign Unit Type Destroyed": "True when the selected player's live count for one unit type reaches zero.",
    "Campaign Building Type Destroyed": "True when no live building of the selected type remains for that player.",
    "Campaign All Actors In Location": "Useful for escort/exit missions such as multiple heroes reaching a Circle of Power.",
    "Campaign All Actors Alive": "Protect-the-heroes success check for a comma-separated set of named scene actors.",
    "Campaign Any Actor Dead": "Protect-the-heroes failure condition for campaign missions.",
    "Set Campaign Objective": "Creates or updates an authored objective and marks it Active. In 1.38 any trigger objective mutation automatically activates trigger-over-map precedence. The text is exposed to Warcraft II Remastered's native Objectives renderer through an allocator-free vector view; Game Message is not used as the objective renderer.",
    "Use Trigger Objectives": "Explicitly activates the trigger objective list as the native Objectives source. Trigger objectives win over objectives already present in the PUD/campaign until Restore Map Objectives is used.",
    "Restore Map Objectives": "Hands native Objectives rendering back to Warcraft. The next Objectives screen uses the PUD/campaign's own objective list instead of Trigger Studio's override.",
    "Complete Campaign Objective": "Marks a campaign objective Completed and can announce it immediately.",
    "Fail Campaign Objective": "Marks a campaign objective Failed and can announce it immediately.",
    "Show Objectives HUD": "Stages the current authored objective list for Warcraft II Remastered's native Scenario Objectives renderer. Use Open Scenario Objectives to display the real Warcraft objective screen.",
    "Show Mission Briefing": "legacy reference module-inspired authored briefing action. Story text still uses the validated information-message path; campaign objectives themselves should use Set Campaign Objective + Open Scenario Objectives for the native Warcraft objective screen.",
    "Show Act Card": "legacy reference module-inspired act/title card using safe native in-game text.",
    "Show Epilogue": "legacy reference module-inspired epilogue text surface using the validated native message path.",
    "Show Credits": "legacy reference module-inspired credits text surface. Scrolling/front-end movie widgets remain unbound until their Remaster ABI is verified.",
    "Begin Cutscene": "Starts the cinematic director, saves the camera and establishes scene-local state. The input-lock flag is an authoring marker only; 1.29 deliberately does not patch unverified Remaster input callbacks.",
    "End Cutscene": "Ends the cinematic director and optionally restores the camera position saved by Begin Cutscene.",
    "Scene Create Actor": "Creates one real Warcraft unit and stores a generation-safe named actor reference for later dialogue, movement, animation and death actions.",
    "Scene Actor Talk": "Displays speaker-labelled dialogue, optionally plays the unit's native selection voice bark, can cut the camera to the actor, and can block until the line duration ends.",
    "Scene Actor Walk": "Issues the actor a native Move order and can block the trigger sequence until the actor actually reaches the destination.",
    "Scene Actor Attack": "Issues a native attack order against a named actor or point and can wait for a named target to die.",
    "Scene Actor Face": "Changes the actor's native facing byte and marks the sprite record for redraw.",
    "Scene Actor Look At Actor": "Computes one of Warcraft's eight native facings from actor-to-actor tile positions.",
    "Scene Actor Play Animation": "Uses the source sequence timer/action/frame/facing fields already exposed by Source Play Animation, but addresses a named scene actor.",
    "Scene Actor Die": "Runs Warcraft's validated unit_kill callback for the named actor, preserving the normal death lifecycle rather than deleting the unit record.",
    "Scene Actor Remove": "Safely removes a named actor without playing the death lifecycle.",
    "Scene Actor Set HP": "Sets the named actor's HP through the same generation-safe unit-reference path used by the runtime editor.",
    "Scene Actor Set Mana": "Sets the named actor's mana through the generation-safe unit-reference path.",
    "Scene Actor Damage From Actor": "Applies Warcraft's validated native unit damage from one named scene actor to another, preserving normal hit/death bookkeeping.",
    "Scene Actor Change Owner": "Transfers the named actor through Warcraft's validated capture_unit routine and refreshes the actor reference.",
    "Scene Wait For Actor State": "Blocks the scene sequence until the named actor reaches Alive/Dead/Hidden/Removed/Missing or a timeout fires.",
    "Scene Wait For Actor At Location": "Blocks the scene until one actor reaches a destination radius.",
    "Scene Wait For All Actors At Location": "Blocks the scene until every named actor reaches the destination radius.",
    "Scene Camera Cut": "Cuts the local camera through the validated cell_set_pos / Holy Vision camera callback.",
    "Scene Camera Pan": "Smoothstep camera pan advanced outside the action journal so every changing coordinate is published safely through the simulation mailbox.",
    "Scene Camera Follow Actor": "Follows a named actor with throttled validated camera updates until Scene Stop Camera Follow or End Cutscene.",
    "Scene Camera Shake": "Short local camera shake around the current native-verified camera position.",
    "Scene Play Sound": "Plays validated contextual unit sounds or a point explosion sound for scene staging.",
})

def player_label(value: Any, fallback: int | None = None) -> str:
    if value is None:
        value = fallback
    try:
        return f"Player {int(value) + 1}"
    except (TypeError, ValueError):
        return str(value)


def missile_label(value: Any) -> str:
    if value == "Any" or value is None:
        return "Any missile"
    try:
        number = int(value)
    except (TypeError, ValueError):
        text = str(value)
        return text
    return f"{MISSILE_NAMES[number]} ({number})" if 0 <= number < len(MISSILE_NAMES) else f"Missile {number}"


def sound_label(value: Any) -> str:
    try:
        sound_id = int(value)
        if 69 <= sound_id <= 85:
            sound_id -= 69
    except (TypeError, ValueError):
        key = str(value).strip().casefold()
        sound_id = next((i for i, name in enumerate(SPELL_SOUND_NAMES) if name.casefold() == key), 13)
    if 0 <= sound_id < len(SPELL_SOUND_NAMES):
        return f"{SPELL_SOUND_NAMES[sound_id]} [relative {sound_id}, native {sound_id + 69}]"
    return str(value)


def amount_text(value: Any) -> str:
    return "all" if str(value).casefold() == "all" else str(value)


def clause_summary(clause: Clause, player: int = 0) -> str:
    a = clause.args
    k = clause.kind
    owner = player_label(a.get("player", player))
    unit = unit_label(a.get("unit", "Any"))
    location = a.get("location", "Anywhere")
    comparison = a.get("comparison", "At least")
    amount = a.get("amount", 0)

    if k in {"Always", "Never"}:
        return k
    if k == "Elapsed Time":
        return f"Elapsed time is {comparison.casefold()} {amount}"
    if k in {"Command", "Bring", "Unit Entered Location", "Building Completed", "Unit Created", "Unit Died", "Unit Removed", "Corpse Count"}:
        verb = {
            "Command": "commands", "Bring": "brings", "Unit Entered Location": "newly entered", "Building Completed": "has completed",
            "Unit Created": "created", "Unit Died": "lost", "Unit Removed": "had removed",
            "Corpse Count": "has corpses of",
        }[k]
        where = "" if location == "Anywhere" else f" at {location}"
        return f"{owner} {verb} {comparison.casefold()} {amount} {unit}{where}"
    if k == "Missile Count":
        return f"{owner} has {comparison.casefold()} {amount} {missile_label(a.get('missile', 'Any'))} projectile(s)"
    if k == "Rune Count":
        return f"{comparison} {amount} rune(s) at {location}"
    if k in {"Hit Points", "Mana"}:
        return f"First {owner} {unit} at {location} has {k.casefold()} {comparison.casefold()} {amount}"
    if k == "Resources":
        return f"{owner} has {comparison.casefold()} {amount} {a.get('resource', 'Gold')}"
    if k in {"Kills", "Deaths"}:
        return f"{owner} {k.casefold()} ({a.get('category', 'All')}) is {comparison.casefold()} {amount}"
    if k == "Player Killed":
        return f"{owner} newly killed ({a.get('category', 'All')}) {comparison.casefold()} {amount} this trigger cycle"
    if k == "Score":
        return f"{owner} score is {comparison.casefold()} {amount}"
    if k == "Switch":
        return f"Switch {a.get('name', 'Switch 1')} is {a.get('state', 'Set')}"
    if k == "Counter":
        return f"Counter {a.get('name', 'Lives')} is {comparison.casefold()} {amount}"
    if k == "Game State":
        return f"Game state is {a.get('state', 'Playing')}"
    if k == "Unit Property":
        return f"First {owner} {unit} {a.get('property', 'health')} is {comparison.casefold()} {amount}"

    if k in {"Random Chance", "Countdown Timer", "Timer Expired", "Variable", "Counter Changed", "Expression", "Unit Group Count"}:
        return f"{k} {a.get('name', '')} is {comparison.casefold()} {amount}"
    if k in {"Switch Changed", "Variable Changed", "Location Exists", "Player Has No Buildings", "Unit Group Empty", "Event Available"}:
        return f"{k}: {a.get('name', a.get('location', owner))}"
    if k in {"Player Status", "Trigger Enabled", "Objective State"}:
        return f"{k} is {a.get('state')}"
    if k in {"Unit Health Percent", "Unit Order", "Unit Status", "Unit Left Location", "Unit Stayed In Location", "Location Empty", "Unit Damaged", "Unit Healed", "Unit Under Attack"}:
        return f"{k}: {owner} {unit} at {location} {comparison.casefold()} {amount}"

    if k == "Display Text":
        text = str(a.get("text", "")); return f'Log "{text[:72]}{"…" if len(text) > 72 else ""}"'
    if k == "Game Message":
        text = str(a.get("text", ""))
        recipients = a.get("recipients", "Local player only")
        color = a.get("color", "Yellow / gold — native normal")
        return f'Show {color} game information "{text[:60]}{"…" if len(text) > 60 else ""}" to {recipients}'
    if k == "Player Chat":
        text = str(a.get("text", ""))
        recipients = a.get("recipients", "All active players")
        sender = a.get("sender", "Current trigger player")
        return f'Send native player chat "{text[:60]}{"…" if len(text) > 60 else ""}" as {sender} to {recipients}'
    if k == "Wait":
        seconds = a.get("seconds", a.get("ticks", 0))
        return f"Wait {seconds} second(s), then continue with the actions below"
    if k == "Set Switch":
        return f"Set switch {a.get('name', 'Switch 1')} to {a.get('state', 'Set')}"
    if k in {"Set Counter", "Add Counter", "Subtract Counter"}:
        verb = {"Set Counter": "Set", "Add Counter": "Add to", "Subtract Counter": "Subtract from"}[k]
        return f"{verb} counter {a.get('name', 'Lives')} by/to {amount}"
    if k == "Random Wait":
        return f"Wait randomly from {a.get('minimum', 0)} to {a.get('maximum', 0)} second(s)"
    if k in {"Toggle Switch", "Randomize Switch"}:
        return f"{k}: {a.get('name', 'Switch 1')}"
    if "Counter" in k and k not in {"Set Counter", "Add Counter", "Subtract Counter"}:
        return f"{k}: {a.get('name', 'Counter 1')}"
    if "Variable" in k:
        return f"{k}: {a.get('name', 'Variable 1')}"
    if "Countdown Timer" in k:
        return f"{k}: {a.get('name', 'Timer 1')}"
    if k in {"Enable Trigger", "Disable Trigger", "Toggle Trigger", "Reset Trigger", "Run Trigger"}:
        return f"{k}: {a.get('trigger', '')}"
    if k in {"Stop Trigger Actions", "Stop Trigger Cycle", "Breakpoint", "Log State", "Log Event Context", "Comment"}:
        return k
    if k in {"Move Location", "Offset Location", "Resize Location", "Copy Location", "Randomize Location", "Follow Unit With Location", "Stop Following Location"}:
        return f"{k}: {a.get('location', '')}"
    if k in {"Replace Units", "Set Unit Facing", "Set Unit Health Percent", "Heal Units", "Apply Status Effect", "Clear Status Effects", "Make Invincible", "Make Vulnerable", "Complete Buildings", "Set Unit Color", "Center Camera", "Move Location To Event Unit", "Create Units At Event"}:
        return f"{k}: {owner} {unit} at {location}"
    if k in {"Set Score", "Set Kills", "Set Deaths"}:
        return f"{k}: {owner} -> {amount}"
    if k in {"Set Objective", "Complete Objective", "Clear Objective"}:
        return f"{k}: {a.get('name', 'Objective 1')}"
    if k == "Display Leaderboard":
        return f"Display {a.get('metric', 'Score')} leaderboard"
    if k == "Assert":
        return f"Assert {a.get('source', 'Variable')} {a.get('name', '')} {comparison.casefold()} {amount}"
    if k == "Create Wave":
        return f"Create Wave: {a.get('amount_expression', '1')} x {owner} {unit}, {a.get('formation', 'Compact')} -> {a.get('order', 'Attack')} {a.get('destination', 'Anywhere')} as group {a.get('group', 'Last Wave')}"
    if k in {"Save Unit Group", "Add Units To Group", "Clear Unit Group", "Order Unit Group", "Set Unit Group Health Percent"}:
        return f"{k}: {a.get('group', 'Unit Group 1')}"
    if k in {"Set Variable From Event", "Set Variable From Expression", "Set Counter From Expression"}:
        return f"{k}: {a.get('name', '')}"
    if k == "Enable Auto Spellcasting":
        return f"Auto Spells: P{int(a.get('player', 0)) + 1}, {a.get('profile', 'Balanced combat')}, range {a.get('range', 16)}, cooldown {a.get('cooldown', 2.5)}s"
    if k == "Disable Auto Spellcasting":
        return f"Disable Auto Spells: P{int(a.get('player', 0)) + 1}"
    if k == "Auto Cast Spells Now":
        return f"Auto Cast Now: {a.get('player', 'All')}"
    if k in {"Set Resources", "Add Resources", "Subtract Resources"}:
        verb = {"Set Resources": "Set", "Add Resources": "Add", "Subtract Resources": "Subtract"}[k]
        prep = "to" if k == "Set Resources" else "from" if k == "Subtract Resources" else "to"
        return f"{verb} {amount} {a.get('resource', 'Gold')} {prep} {owner}"
    if k == "Award Kill Resources":
        return (
            f"Award {a.get('amount_per_kill', 100)} {a.get('resource', 'Gold')} per "
            f"{player_label(a.get('killer_player', player))} {a.get('category', 'All')} kill "
            f"to {player_label(a.get('recipient_player', player))}"
        )
    if k in {"Set Hit Points", "Set Mana"}:
        return f"{k} of {owner} {unit} at {location} to {amount}"
    if k == "Set Unit Property":
        return f"Set {a.get('property', 'health')}={a.get('value', 0)} on {owner} {unit} at {location}"
    if k == "Damage Units":
        return f"Damage {owner} {unit} at {location} by {amount} using {player_label(a.get('attacker_player', player))} {unit_label(a.get('attacker_unit', 'Any'))}"
    if k == "Kill Units":
        suffix = " (including settled arrivals)" if a.get("include_settled_move_targets", True) else ""
        return f"Kill Units: all {owner} {unit} at {location}{suffix}"
    if k == "Remove Units":
        return f"Remove Units: {amount_text(a.get('amount', 'All'))} {owner} {unit} at {location}"
    if k in {"Create Units", "Create Completed Buildings"}:
        destination = f"({a.get('x', '?')},{a.get('y', '?')})" if location == "Anywhere" else location
        return f"{k}: {amount} {owner} {unit} at {destination}"
    if k == "Move Units":
        destination = a.get("destination", "Anywhere")
        point = f"({a.get('x', '?')},{a.get('y', '?')})" if destination == "Anywhere" else destination
        return f"Move {amount_text(amount)} {owner} {unit} from {location} to {point}"
    if k == "Give Units":
        return f"Give {amount_text(amount)} {owner} {unit} at {location} to {player_label(a.get('to_player', player))}"
    if k == "Order":
        order = a.get("order", "Move")
        destination = a.get("destination", "Anywhere")
        target = f"({a.get('x', '?')},{a.get('y', '?')})" if destination == "Anywhere" else destination
        suffix = " (force reissue)" if a.get("reissue", False) else ""
        return f"Order {amount_text(amount)} {owner} {unit} to {order} {target}{suffix}"
    if k == "Create Missile":
        return f"Create {amount} native missile(s) from {owner} {unit} to {player_label(a.get('target_player', 1))} {unit_label(a.get('target_unit', 'Any'))}"
    if k == "Cast Spell":
        spell = str(a.get("spell", "Runes"))
        spell_key = spell.casefold()
        cast_mode = str(a.get("cast_mode", "Automatic"))
        caster_unit = a.get("caster_unit")
        caster_free = cast_mode == "Caster-free effect" or (
            cast_mode == "Automatic"
            and spell_key in {"runes", "holy vision"}
            and caster_unit in (None, "", "Any")
        )
        caster = "without a caster" if caster_free else (
            f"with {player_label(a.get('caster_player', a.get('player', player)))} "
            f"{unit_label(caster_unit if caster_unit not in (None, '') else 'Any')}"
        )
        if spell_key in UNIT_TARGET_SPELLS:
            priority = str(a.get("target_selection", "Nearest valid"))
            health = str(a.get("target_health", "Spell default"))
            limit = amount_text(a.get("target_amount", "All"))
            target = (
                f" on up to {limit} distinct {player_label(a.get('target_player', 1))} "
                f"{unit_label(a.get('target_unit', 'Any'))} target(s) "
                f"[{priority}; {health}]"
            )
        elif (
            str(a.get("map_target_source", "Location / coordinates")) == "Matching unit(s)"
            or (
                "x" not in a and "y" not in a
                and (
                    a.get("target_unit", "Any") not in (None, "", "Any")
                    or (a.get("target_location", "Anywhere") or "Anywhere") != "Anywhere"
                )
            )
        ):
            limit = amount_text(a.get("target_amount", "All"))
            target = (
                f" at {limit} matching {player_label(a.get('target_player', 1))} "
                f"{unit_label(a.get('target_unit', 'Any'))} tile(s)"
            )
        else:
            loc = a.get("location", "Anywhere")
            point = f"({a.get('x', '?')},{a.get('y', '?')})" if loc in (None, "", "Anywhere") else loc
            target = f" at {point}"
        return f"Cast {spell} {caster}{target}"
    if k == "Play Sound":
        if str(a.get("source", "Location")).casefold() == "unit":
            position = f"{player_label(a.get('sound_player', player))} {unit_label(a.get('sound_unit', 'Any'))}"
        else:
            loc = a.get("location", "Anywhere")
            position = f"({a.get('x', '?')},{a.get('y', '?')})" if loc == "Anywhere" else loc
        return f"Play {sound_label(a.get('sound', 'Thunder'))} at {position}"
    if k == "Set Game Speed":
        return f"Set game speed to {a.get('speed', 'Fastest')}"
    if k == "Set Player Relations":
        return "Apply exact Player 1-8 alliance, vision, and allied-victory matrix"
    if k == "Set Alliance":
        rows = a.get("matrix", [])
        cross = sum(1 for source, row in enumerate(rows if isinstance(rows, list) else []) for target in row if int(target) != source)
        numbering = "displayed colors" if a.get("player_reference_mode") == PLAYER_REFERENCE_MODES[1] else "live owner slots"
        return f"Set exact alliance grid for Players 1-8: {cross} directed allied cross-player cell(s), all other cross-player cells Enemy, by {numbering}"
    if k == "Set Shared Vision":
        rows = a.get("matrix", [])
        cross = sum(1 for source, row in enumerate(rows if isinstance(rows, list) else []) for target in row if int(target) != source)
        numbering = "displayed colors" if a.get("player_reference_mode") == PLAYER_REFERENCE_MODES[1] else "live owner slots"
        return f"Set exact shared-vision grid for Players 1-8: {cross} directed cross-player vision cell(s), by {numbering}"
    if k == "Set Allied Victory":
        rows = a.get("matrix", [])
        enabled_rows = sum(1 for source, row in enumerate(rows if isinstance(rows, list) else []) if any(int(target) != source for target in row))
        cross = sum(1 for source, row in enumerate(rows if isinstance(rows, list) else []) for target in row if int(target) != source)
        numbering = "displayed colors" if a.get("player_reference_mode") == PLAYER_REFERENCE_MODES[1] else "live owner slots"
        return f"Set allied-victory partner grid: {cross} directed partner cell(s), {enabled_rows} player row(s) enabled, by {numbering}"
    if k == "Modify Tile":
        return f"Set {a.get('width', 1)}×{a.get('height', 1)} tile area at {location} to MTXM {a.get('tile', 0)}"
    if k == "Run AI Script":
        return f"Run AI script {a.get('script', '')!r} for {owner} at {location}"
    return k


class PlayerMultiSelectWidget(ttk.Frame):
    """Compact Players 1-8 checkbox selector with All/None controls."""

    def __init__(
        self,
        master: tk.Misc,
        value: Any,
        on_change: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.on_change = on_change
        selected = self._normalize(value)
        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(0, 4))
        ttk.Button(controls, text="All", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(controls, text="None", command=lambda: self._set_all(False)).pack(side="left", padx=(5, 0))
        self.summary_var = tk.StringVar()
        ttk.Label(controls, textvariable=self.summary_var).pack(side="left", padx=(10, 0))

        grid = ttk.Frame(self)
        grid.pack(fill="x")
        self.player_vars: list[tk.BooleanVar] = []
        for player in range(8):
            var = tk.BooleanVar(value=player in selected)
            self.player_vars.append(var)
            check = tk.Checkbutton(
                grid,
                text=f"Player {player + 1}",
                variable=var,
                bg="#20242b",
                fg="#e6e6e6",
                activebackground="#2a3038",
                activeforeground="#e6e6e6",
                selectcolor="#354452",
                highlightthickness=0,
                bd=1,
                relief="flat",
                padx=6,
                pady=3,
                command=self._changed,
            )
            check.grid(row=player // 4, column=player % 4, sticky="ew", padx=(0, 4), pady=2)
        for column in range(4):
            grid.columnconfigure(column, weight=1)
        self._changed(notify=False)

    @staticmethod
    def _normalize(value: Any) -> set[int]:
        if value is None:
            return set()
        if isinstance(value, str):
            if value.strip().casefold() in {"all", "all players", "players 1-8"}:
                return set(range(8))
            result: set[int] = set()
            for token in value.replace(";", ",").split(","):
                token = token.strip()
                if not token:
                    continue
                if token.casefold().startswith("player "):
                    result.add(int(token.split()[-1]) - 1)
                elif token.casefold().startswith("p") and token[1:].isdigit():
                    result.add(int(token[1:]) - 1)
                else:
                    result.add(int(token, 0))
            return {player for player in result if 0 <= player <= 7}
        if isinstance(value, (list, tuple, set)):
            return {int(player) for player in value if 0 <= int(player) <= 7}
        player = int(value)
        return {player} if 0 <= player <= 7 else set()

    def _set_all(self, enabled: bool) -> None:
        for var in self.player_vars:
            var.set(enabled)
        self._changed()

    def _changed(self, notify: bool = True) -> None:
        selected = self.get()
        self.summary_var.set(
            "All Players 1-8" if selected == list(range(8))
            else (", ".join(f"P{player + 1}" for player in selected) or "No players selected")
        )
        if notify:
            self.on_change()

    def get(self) -> list[int]:
        return [index for index, var in enumerate(self.player_vars) if var.get()]



class PlayerPairMatrixWidget(ttk.Frame):
    """One explicit Player 1-8 relation grid used by each existing diplomacy action."""

    MODE_TEXT = {
        "alliance": (
            "CHECKED = ALLIED. UNCHECKED = ENEMY for other players. Self is locked in the UI and its native owner/self code is preserved.",
            "Allied",
            "Enemy",
        ),
        "vision": (
            "Checked = this row player shares vision with that column player.",
            "Vision shared",
            "No vision",
        ),
        "victory": (
            "Checked = intended allied-victory partner. A row with only itself checked is disabled.",
            "Victory partner",
            "Not a partner",
        ),
    }

    def __init__(self, master: tk.Misc, value: Any, on_change: Callable[[], None], mode: str) -> None:
        super().__init__(master)
        self.on_change = on_change
        self.mode = mode
        self.vars: list[list[tk.BooleanVar]] = []
        self.summary_var = tk.StringVar()

        description, checked_text, unchecked_text = self.MODE_TEXT[mode]
        ttk.Label(self, text=description, wraplength=760, justify="left").grid(
            row=0, column=0, columnspan=10, sticky="w", padx=4, pady=(2, 6)
        )
        ttk.Label(
            self,
            text=f"{checked_text}; {unchecked_text}. The diagonal self-cells are locked on.",
            wraplength=760,
            justify="left",
        ).grid(row=1, column=0, columnspan=10, sticky="w", padx=4, pady=(0, 8))

        preset = ttk.Frame(self)
        preset.grid(row=2, column=0, columnspan=10, sticky="w", padx=4, pady=(0, 8))
        ttk.Label(preset, text="Presets:").pack(side="left", padx=(0, 6))
        ttk.Button(preset, text="Self only / FFA", command=lambda: self._apply_groups([[p] for p in range(8)])).pack(side="left", padx=2)
        ttk.Button(preset, text="Everyone", command=lambda: self._apply_groups([list(range(8))])).pack(side="left", padx=2)
        ttk.Button(preset, text="2v2v2v2", command=lambda: self._apply_groups([[0,1],[2,3],[4,5],[6,7]])).pack(side="left", padx=2)
        ttk.Button(preset, text="4v4", command=lambda: self._apply_groups([[0,1,2,3],[4,5,6,7]])).pack(side="left", padx=2)

        ttk.Label(self, text="Player \\ Player", anchor="center").grid(row=3, column=0, padx=(4, 8), pady=4, sticky="ew")
        for column in range(8):
            ttk.Label(self, text=f"P{column + 1}", anchor="center").grid(
                row=3, column=column + 1, padx=7, pady=4, sticky="ew"
            )

        rows = self._normalize(value)
        for row in range(8):
            ttk.Label(self, text=f"Player {row + 1}").grid(row=row + 4, column=0, sticky="w", padx=(4, 8), pady=4)
            line: list[tk.BooleanVar] = []
            selected = set(rows[row])
            selected.add(row)
            for column in range(8):
                variable = tk.BooleanVar(value=column in selected)
                line.append(variable)
                check = ttk.Checkbutton(self, variable=variable, command=self._changed)
                check.grid(row=row + 4, column=column + 1, padx=8, pady=4)
                if row == column:
                    variable.set(True)
                    check.state(["disabled"])
            self.vars.append(line)

        ttk.Label(self, textvariable=self.summary_var, wraplength=760, justify="left").grid(
            row=12, column=0, columnspan=10, sticky="w", padx=4, pady=(8, 2)
        )
        self._changed(notify=False)

    @staticmethod
    def _normalize(value: Any) -> list[list[int]]:
        if isinstance(value, dict):
            value = value.get("rows", value.get("matrix", []))
        rows = value if isinstance(value, list) else []
        result: list[list[int]] = []
        for row in range(8):
            raw = rows[row] if row < len(rows) and isinstance(rows[row], (list, tuple, set)) else [row]
            selected = {int(item) for item in raw if 0 <= int(item) <= 7}
            selected.add(row)
            result.append(sorted(selected))
        return result

    def _apply_groups(self, groups: list[list[int]]) -> None:
        rows = [{row} for row in range(8)]
        for group in groups:
            members = {int(player) for player in group if 0 <= int(player) <= 7}
            for source in members:
                rows[source].update(members)
        for source, line in enumerate(self.vars):
            for target, variable in enumerate(line):
                variable.set(target in rows[source] or target == source)
        self._changed()

    def _changed(self, notify: bool = True) -> None:
        rows = self.get()
        cross = sum(1 for source, row in enumerate(rows) for target in row if target != source)
        if self.mode == "alliance":
            enemy = 56 - cross
            summary = f"{cross} directed cross-player Allied cell(s); {enemy} directed Enemy cell(s)."
        elif self.mode == "vision":
            summary = f"{cross} directed cross-player shared-vision cell(s)."
        else:
            enabled = sum(1 for source, row in enumerate(rows) if any(target != source for target in row))
            summary = f"{cross} directed allied-victory partner cell(s); {enabled} player row(s) enabled."
        self.summary_var.set(summary)
        if notify:
            self.on_change()

    def get(self) -> list[list[int]]:
        result: list[list[int]] = []
        for source, line in enumerate(self.vars):
            selected = [target for target, variable in enumerate(line) if variable.get()]
            if source not in selected:
                selected.append(source)
            result.append(sorted(set(selected)))
        return result


class DiplomacyMatrixWidget(ttk.Frame):
    """Three explicit Player 1-8 matrices. Diagonal cells are locked on."""

    def __init__(self, master: tk.Misc, value: Any, on_change: Callable[[], None]) -> None:
        super().__init__(master)
        self.on_change = on_change
        data = value if isinstance(value, dict) else {}
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)
        self.alliance_vars = self._matrix_tab("Alliance", data.get("alliance"), diagonal=True)
        self.vision_vars = self._matrix_tab("Shared vision", data.get("vision"), diagonal=True)
        victory = ttk.Frame(self.notebook)
        self.notebook.add(victory, text="Allied victory")
        ttk.Label(victory, text="Enable native Allied Victory independently for each player. Computer players remain limited by Warcraft's original victory code.", wraplength=720).grid(row=0,column=0,columnspan=8,sticky="w",padx=6,pady=6)
        selected=set(int(x) for x in data.get("allied_victory", []))
        self.victory_vars=[]
        for p in range(8):
            v=tk.BooleanVar(value=p in selected); self.victory_vars.append(v)
            ttk.Checkbutton(victory,text=f"P{p+1}",variable=v,command=self.on_change).grid(row=1,column=p,sticky="w",padx=6,pady=6)

    def _matrix_tab(self, title: str, raw: Any, diagonal: bool) -> list[list[tk.BooleanVar]]:
        frame=ttk.Frame(self.notebook); self.notebook.add(frame,text=title)
        rows=raw if isinstance(raw,list) else []
        ttk.Label(frame,text="From / To").grid(row=0,column=0,padx=5,pady=4)
        for c in range(8): ttk.Label(frame,text=f"P{c+1}").grid(row=0,column=c+1,padx=5,pady=4)
        out=[]
        for r in range(8):
            ttk.Label(frame,text=f"P{r+1}").grid(row=r+1,column=0,padx=5,pady=4)
            selected=set(int(x) for x in (rows[r] if r < len(rows) and isinstance(rows[r],list) else [r]))
            selected.add(r)
            line=[]
            for c in range(8):
                v=tk.BooleanVar(value=c in selected); line.append(v)
                cb=ttk.Checkbutton(frame,variable=v,command=self.on_change)
                cb.grid(row=r+1,column=c+1,padx=7,pady=3)
                if diagonal and r==c:
                    v.set(True); cb.state(["disabled"])
            out.append(line)
        return out

    def get(self) -> dict[str, Any]:
        def rows(matrix):
            result=[]
            for r,line in enumerate(matrix):
                selected=[c for c,v in enumerate(line) if v.get()]
                if r not in selected: selected.append(r)
                result.append(sorted(set(selected)))
            return result
        return {
            "alliance": rows(self.alliance_vars),
            "vision": rows(self.vision_vars),
            "allied_victory": [p for p,v in enumerate(self.victory_vars) if v.get()],
        }


class MessageTemplateWidget(ttk.Frame):
    """Message editor with variable and native color insertion helpers."""

    VARIABLE_TYPES = (
        "Current unit count",
        "Completed building count",
        "Created unit count",
        "Died unit count",
        "Removed unit count",
        "Corpse count",
    )

    VARIABLE_FUNCTIONS = {
        "Current unit count": "count",
        "Completed building count": "completed",
        "Created unit count": "created",
        "Died unit count": "died",
        "Removed unit count": "removed",
        "Corpse count": "corpses",
    }

    def __init__(
        self,
        master: tk.Misc,
        scenario: Scenario,
        value: Any,
        on_change: Callable[[], None],
        allow_colors: bool = True,
    ) -> None:
        super().__init__(master)
        self.scenario = scenario
        self.on_change = on_change

        self.text = tk.Text(
            self,
            height=6,
            bg="#15181d",
            fg="#e6e6e6",
            insertbackground="#c7ccd1",
            selectbackground="#2b3440",
            selectforeground="#e6e6e6",
            highlightthickness=0,
            relief="flat",
            wrap="word",
        )
        self.text.pack(fill="both", expand=True)
        self.text.insert("1.0", str(value))
        self.text.bind("<KeyRelease>", lambda _e: self.on_change())

        quick = ttk.Frame(self)
        quick.pack(fill="x", pady=(5, 0))
        self.quick_label_to_token = dict(MESSAGE_VARIABLE_QUICK)
        self.quick_var = tk.StringVar(value=MESSAGE_VARIABLE_QUICK[0][0])
        ttk.Combobox(
            quick,
            textvariable=self.quick_var,
            values=tuple(label for label, _token in MESSAGE_VARIABLE_QUICK),
            state="readonly",
            width=29,
        ).pack(side="left", fill="x", expand=True)
        ttk.Button(
            quick, text="Insert variable", command=self._insert_quick
        ).pack(side="left", padx=(5, 0))
        ttk.Button(
            quick, text="Unit count…", command=self._open_unit_variable
        ).pack(side="left", padx=(5, 0))

        self.color_var = tk.StringVar(value="[yellow]")
        if allow_colors:
            colors = ttk.Frame(self)
            colors.pack(fill="x", pady=(5, 0))
            ttk.Combobox(
                colors,
                textvariable=self.color_var,
                values=GAME_MESSAGE_COLOR_TAGS,
                state="readonly",
                width=18,
            ).pack(side="left")
            ttk.Button(
                colors, text="Insert color override", command=self._insert_color
            ).pack(side="left", padx=(5, 0))
            ttk.Label(
                colors, text="Chat tags can change color inline; [previous] restores the prior table."
            ).pack(side="left", padx=(8, 0))

    def get(self) -> str:
        return self.text.get("1.0", "end-1c")

    def _insert(self, token: str) -> None:
        self.text.insert("insert", token)
        self.text.focus_set()
        self.on_change()

    def _insert_quick(self) -> None:
        token = self.quick_label_to_token.get(self.quick_var.get(), "{elapsed}")
        self._insert(token)

    def _insert_color(self) -> None:
        self._insert(self.color_var.get())

    def _open_unit_variable(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Insert message count variable")
        dialog.configure(bg="#171a1f")
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        dialog.resizable(True, False)

        frame = ttk.Frame(dialog, padding=12)
        frame.pack(fill="both", expand=True)
        kind_var = tk.StringVar(value=self.VARIABLE_TYPES[0])
        player_var = tk.StringVar(value="Executing player")
        unit_var = tk.StringVar(value="UNIT 000 - Footman")
        location_var = tk.StringVar(value="Anywhere")

        rows = (
            ("Value", kind_var, self.VARIABLE_TYPES),
            ("Player", player_var, ("Executing player", "All players") + PLAYERS),
            (
                "Unit / building",
                unit_var,
                ("Any",) + tuple(
                    f"{'UNIT' if i < 58 else 'BUILDING'} {i:03d} - {name}"
                    for i, name in enumerate(UNIT_NAMES)
                ),
            ),
            (
                "Location",
                location_var,
                ("Anywhere",) + tuple(loc.name for loc in self.scenario.locations),
            ),
        )
        for row, (label, var, values) in enumerate(rows):
            ttk.Label(frame, text=label, width=18).grid(
                row=row, column=0, sticky="w", pady=4
            )
            ttk.Combobox(
                frame, textvariable=var, values=values, state="readonly"
            ).grid(row=row, column=1, sticky="ew", pady=4)
        frame.columnconfigure(1, weight=1)

        def insert_token() -> None:
            player_text = player_var.get()
            if player_text == "Executing player":
                player_token = "Current"
            elif player_text == "All players":
                player_token = "All"
            else:
                player_token = "P" + player_text.split()[-1]

            unit_text = unit_var.get()
            if unit_text == "Any":
                unit_token = "Any"
            else:
                import re
                match = re.search(r"\b(\d{1,3})\b", unit_text)
                unit_token = UNIT_NAMES[int(match.group(1))] if match else "Any"

            function = self.VARIABLE_FUNCTIONS[kind_var.get()]
            token = "{" + function + "(" + "|".join(
                (player_token, unit_token, location_var.get())
            ) + ")}"
            self._insert(token)
            dialog.destroy()

        buttons = ttk.Frame(frame)
        buttons.grid(
            row=len(rows), column=0, columnspan=2, sticky="e", pady=(10, 0)
        )
        ttk.Button(
            buttons, text="Cancel", command=dialog.destroy
        ).pack(side="right", padx=(5, 0))
        ttk.Button(
            buttons, text="Insert", command=insert_token
        ).pack(side="right")
        dialog.bind("<Escape>", lambda _e: dialog.destroy())
        dialog.bind("<Return>", lambda _e: insert_token())
        dialog.wait_visibility()
        dialog.focus_set()


class ClauseDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        scenario: Scenario,
        mode: str,
        clause: Clause | None = None,
        live_preview: Callable[[dict[str, Any]], None] | None = None,
        initial_kind: str | None = None,
    ):
        super().__init__(master)
        self.configure(bg="#171a1f")
        self.scenario = scenario
        self.mode = mode
        self.live_preview = live_preview
        self.result: Clause | None = None
        self.original_args = dict(clause.args) if clause else {}
        self.vars: dict[str, Any] = {}
        self.widgets: dict[str, tk.Widget] = {}
        self._field_specs: tuple[FieldSpec, ...] = ()
        kinds = CONDITIONS if mode == "condition" else ACTIONS
        self._kinds = list(kinds)
        self._kind_display = {kind: display_kind(mode, kind) for kind in self._kinds}
        self._kind_from_display = {shown: kind for kind, shown in self._kind_display.items()}
        self.title(("Edit" if clause else "Add") + (" Condition" if mode == "condition" else " Action"))
        self.geometry("720x730")
        self.minsize(620, 560)
        self.transient(master)
        self.grab_set()

        top = ttk.Frame(self)
        top.pack(fill="x", padx=12, pady=(12, 5))
        ttk.Label(top, text="Type", width=16).pack(side="left")
        selected_kind = canonical_kind(mode, clause.kind) if clause else (canonical_kind(mode, initial_kind) if initial_kind else kinds[0])
        if selected_kind not in kinds:
            selected_kind = kinds[0]
        self.kind_var = tk.StringVar(value=self._kind_display[selected_kind])
        kind_box = ttk.Combobox(top, textvariable=self.kind_var, values=[self._kind_display[k] for k in kinds], state="readonly")
        kind_box.pack(side="left", fill="x", expand=True)
        kind_box.bind("<<ComboboxSelected>>", lambda _e: self._rebuild_form())

        self.help_var = tk.StringVar()
        ttk.Label(self, textvariable=self.help_var, wraplength=670, justify="left").pack(fill="x", padx=12, pady=(2, 8))

        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True, padx=12)
        self.canvas = tk.Canvas(outer, bg="#20242b", highlightthickness=0)
        scroll = ttk.Scrollbar(outer, orient="vertical", command=self.canvas.yview)
        self.form = ttk.Frame(self.canvas)
        self.form_window = self.canvas.create_window((0, 0), window=self.form, anchor="nw")
        self.canvas.configure(yscrollcommand=scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.form.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.form_window, width=e.width))

        preview_box = ttk.LabelFrame(self, text="Plain-English preview")
        preview_box.pack(fill="x", padx=12, pady=10)
        self.preview_var = tk.StringVar()
        ttk.Label(preview_box, textvariable=self.preview_var, wraplength=665, justify="left").pack(fill="x", padx=8, pady=8)

        buttons = ttk.Frame(self)
        buttons.pack(fill="x", padx=12, pady=(0, 12))
        self.test_button = ttk.Button(buttons, text="Test in Warcraft", command=self._test_sound)
        ttk.Button(buttons, text="Open Example", command=self._open_example).pack(side="left", padx=3)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=3)
        ttk.Button(buttons, text="OK", command=self._accept).pack(side="right", padx=3)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Control-Return>", lambda _e: self._accept())
        self._rebuild_form(initial=True)
        self.wait_visibility()
        self.focus_set()

    def _open_example(self) -> None:
        """Open the dedicated one-feature example for the selected canonical kind."""
        kind = self._actual_kind()
        folder_name = "conditions" if self.mode == "condition" else "actions"
        base = Path(__file__).resolve().parent.parent / "examples" / folder_name
        stem = re.sub(r"[^A-Za-z0-9]+", "_", kind).strip("_")
        matches = sorted(base.glob(f"*_{stem}.w2trig.json"))
        # A future rename may leave a legacy filename. Verify the file contents,
        # then fall back to a catalog scan rather than opening the wrong profile.
        def contains_feature(path: Path) -> bool:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                return False
            key = "conditions" if self.mode == "condition" else "actions"
            return any(
                canonical_kind(self.mode, str(item.get("kind", ""))) == kind
                for trigger in data.get("triggers", [])
                for item in trigger.get(key, [])
            )
        matches = [path for path in matches if contains_feature(path)]
        if not matches:
            matches = [path for path in sorted(base.glob("*.w2trig.json")) if contains_feature(path)]
        if not matches:
            messagebox.showerror("Example", f"Dedicated example for {kind} was not found.", parent=self)
            return
        try:
            webbrowser.open(matches[0].as_uri())
        except Exception as exc:
            messagebox.showerror("Example", str(exc), parent=self)

    def _actual_kind(self) -> str:
        shown = self.kind_var.get()
        return canonical_kind(self.mode, self._kind_from_display.get(shown, shown))

    def _schema(self) -> tuple[FieldSpec, ...]:
        table = CONDITION_SCHEMAS if self.mode == "condition" else ACTION_SCHEMAS
        kind = self._actual_kind()
        fields = table.get(kind, ())
        if self.mode == "condition" and kind not in {"Always", "Never"}:
            fields = fields + (_field("negate", "NOT / invert this condition", "bool", False, help="Inverts the final condition result, enabling compact NOT logic."),)
        return fields

    def _rebuild_form(self, initial: bool = False) -> None:
        retained = self._collect_args(silent=True) if self.vars else dict(self.original_args)
        for child in self.form.winfo_children():
            child.destroy()
        self.vars.clear()
        self.widgets.clear()
        self._field_specs = self._schema()
        kind = self._actual_kind()
        if kind == "Set Alliance" and "matrix" not in retained:
            rows = [[row] for row in range(8)]
            sources = retained.get("players", [retained.get("player", 0)])
            targets = retained.get("other_players", [retained.get("other_player", 1)])
            sources = [int(value) for value in (sources if isinstance(sources, (list, tuple, set)) else [sources])]
            targets = [int(value) for value in (targets if isinstance(targets, (list, tuple, set)) else [targets])]
            allied = str(retained.get("state", "Allied")).casefold() == "allied"
            mutual = bool(retained.get("mutual", True))
            for source in sources:
                for target in targets:
                    if 0 <= source < 8 and 0 <= target < 8 and source != target:
                        if allied and target not in rows[source]: rows[source].append(target)
                        if mutual and allied and source not in rows[target]: rows[target].append(source)
            retained["matrix"] = [sorted(set(row)) for row in rows]
        elif kind == "Set Shared Vision" and "matrix" not in retained:
            rows = [[row] for row in range(8)]
            sources = retained.get("source_players", [retained.get("source_player", 0)])
            viewers = retained.get("viewer_players", [retained.get("viewer_player", 1)])
            sources = [int(value) for value in (sources if isinstance(sources, (list, tuple, set)) else [sources])]
            viewers = [int(value) for value in (viewers if isinstance(viewers, (list, tuple, set)) else [viewers])]
            enabled = bool(retained.get("enabled", True))
            mutual = bool(retained.get("mutual", False))
            if enabled:
                for source in sources:
                    for viewer in viewers:
                        if 0 <= source < 8 and 0 <= viewer < 8 and source != viewer:
                            if viewer not in rows[source]: rows[source].append(viewer)
                            if mutual and source not in rows[viewer]: rows[viewer].append(source)
            retained["matrix"] = [sorted(set(row)) for row in rows]
        elif kind == "Set Allied Victory" and "matrix" not in retained:
            rows = [[row] for row in range(8)]
            players = retained.get("players", [retained.get("player", 0)])
            players = [int(value) for value in (players if isinstance(players, (list, tuple, set)) else [players])]
            if bool(retained.get("enabled", True)):
                valid = [player for player in players if 0 <= player < 8]
                for source in valid:
                    rows[source].extend(target for target in valid if target != source)
            retained["matrix"] = [sorted(set(row)) for row in rows]
        base_help = KIND_HELP.get(kind, "Configure the fields below. Optional blank values are omitted from JSON.")
        self.help_var.set(base_help + "\n\n" + multiplayer_note(self.mode, kind))

        for row, spec in enumerate(self._field_specs):
            label = ttk.Label(self.form, text=spec.label + (" (optional)" if spec.optional else ""))
            label.grid(row=row * 2, column=0, sticky="nw", padx=(4, 12), pady=(8, 2))
            if spec.key in retained:
                value = retained[spec.key]
            elif spec.key == "seconds" and "ticks" in retained:
                value = retained["ticks"]
            else:
                value = "" if spec.optional else spec.default
            widget = self._make_widget(spec, value)
            widget.grid(row=row * 2, column=1, sticky="ew", padx=4, pady=(6, 2))
            self.widgets[spec.key] = widget
            help_text = spec.help or VALUE_HELP.get(spec.key, "")
            if help_text:
                ttk.Label(self.form, text=help_text, wraplength=455, justify="left").grid(
                    row=row * 2 + 1, column=1, sticky="w", padx=4, pady=(0, 2)
                )
        self.form.columnconfigure(1, weight=1)
        if kind == "Play Sound" and self.live_preview:
            self.test_button.pack(side="left", padx=3)
        else:
            self.test_button.pack_forget()
        self._update_preview()
        if not initial:
            self.canvas.yview_moveto(0)

    def _make_widget(self, spec: FieldSpec, value: Any) -> tk.Widget:
        kind = spec.kind
        if kind == "bool":
            var = tk.BooleanVar(value=bool(value))
            self.vars[spec.key] = var
            widget = tk.Checkbutton(
                self.form,
                variable=var,
                text="Enabled",
                indicatoron=False,
                bg="#20242b",
                fg="#e6e6e6",
                activebackground="#2a3038",
                activeforeground="#e6e6e6",
                selectcolor="#354452",
                highlightthickness=0,
                bd=1,
                relief="flat",
                offrelief="flat",
                overrelief="flat",
                padx=8,
                pady=4,
            )
            var.trace_add("write", lambda *_: self._update_preview())
            return widget
        if kind == "players":
            widget = PlayerMultiSelectWidget(
                self.form,
                value,
                self._update_preview,
            )
            self.vars[spec.key] = widget
            return widget
        if kind in {"alliance_matrix", "vision_matrix", "victory_matrix"}:
            mode = {
                "alliance_matrix": "alliance",
                "vision_matrix": "vision",
                "victory_matrix": "victory",
            }[kind]
            widget = PlayerPairMatrixWidget(self.form, value, self._update_preview, mode)
            self.vars[spec.key] = widget
            return widget
        if kind == "diplomacy_matrix":
            widget = DiplomacyMatrixWidget(self.form, value, self._update_preview)
            self.vars[spec.key] = widget
            return widget
        if kind in {"message_template", "chat_template"}:
            widget = MessageTemplateWidget(
                self.form,
                self.scenario,
                value,
                self._update_preview,
                allow_colors=True,
            )
            self.vars[spec.key] = widget
            return widget
        if kind == "multiline":
            widget = tk.Text(self.form, height=5, bg="#15181d", fg="#e6e6e6", insertbackground="#c7ccd1", selectbackground="#2b3440", selectforeground="#e6e6e6", highlightthickness=0, relief="flat", wrap="word")
            widget.insert("1.0", str(value))
            widget.bind("<KeyRelease>", lambda _e: self._update_preview())
            self.vars[spec.key] = widget
            return widget

        choices: tuple[str, ...] = spec.choices
        display = value
        blank_optional = spec.optional and (value is None or str(value).strip() == "")
        if kind == "player":
            choices = (("",) if spec.optional else ()) + PLAYERS
            if blank_optional:
                display = ""
            else:
                try:
                    number = int(value)
                    if number == -2:
                        display = "Local Human"
                    elif number == -3:
                        display = "First Non-Local Slot"
                    else:
                        display = f"Player {number + 1}"
                except (TypeError, ValueError):
                    text_value = str(value).strip().casefold()
                    if text_value in {"local human", "local player", "current local player"}:
                        display = "Local Human"
                    elif text_value in {"first non-local slot", "first non local slot", "non-local", "non local"}:
                        display = "First Non-Local Slot"
                    else:
                        display = "Player 1"
        elif kind in {"unit", "mobile_unit", "building", "building_any"}:
            if kind == "mobile_unit":
                numbers = range(0, 58)
                label_prefix = "UNIT"
            elif kind in {"building", "building_any"}:
                numbers = range(58, len(UNIT_NAMES))
                label_prefix = "BUILDING"
            else:
                numbers = range(len(UNIT_NAMES))
                label_prefix = ""
            formatted = []
            for i in numbers:
                prefix = label_prefix or ("UNIT" if i < 58 else "BUILDING")
                formatted.append(f"{prefix} {i:03d} - {UNIT_NAMES[i]}")
            allow_any = True
            choices = (("",) if spec.optional else ()) + ("Any",) + tuple(formatted)
            if blank_optional:
                display = ""
            elif (value == "Any" or value is None) and allow_any:
                display = "Any"
            else:
                try:
                    number = int(value)
                    prefix = label_prefix or ("UNIT" if number < 58 else "BUILDING")
                    display = f"{prefix} {number:03d} - {UNIT_NAMES[number]}" if number in numbers else str(number)
                except (TypeError, ValueError):
                    display = str(value)
        elif kind == "missile":
            choices = (("",) if spec.optional else ()) + ("Any",) + tuple(f"{i:02d} - {name}" for i, name in enumerate(MISSILE_NAMES))
            if blank_optional:
                display = ""
            elif value == "Any" or value is None:
                display = "Any"
            else:
                try:
                    number = int(value); display = f"{number:02d} - {MISSILE_NAMES[number]}" if 0 <= number < len(MISSILE_NAMES) else str(value)
                except (TypeError, ValueError):
                    number = next((i for i, name in enumerate(MISSILE_NAMES) if name.casefold() == str(value).casefold()), None)
                    display = f"{number:02d} - {MISSILE_NAMES[number]}" if number is not None else str(value)
        elif kind == "sound":
            choices = tuple(f"{i:02d} / {i + 69:02d} - {name}" for i, name in enumerate(SPELL_SOUND_NAMES))
            try:
                number = int(value)
                if 69 <= number <= 85: number -= 69
            except (TypeError, ValueError):
                number = next((i for i, name in enumerate(SPELL_SOUND_NAMES) if name.casefold() == str(value).casefold()), 13)
            display = choices[number] if 0 <= number < len(choices) else choices[13]
        elif kind == "location":
            choices = (("",) if spec.optional else ()) + ("Anywhere",) + tuple(loc.name for loc in self.scenario.locations)
            display = "" if blank_optional else str(value or "Anywhere")
        elif kind == "amount":
            choices = (("",) if spec.optional else ()) + ("All",) + tuple(str(i) for i in range(1, 17))
            display = "" if blank_optional else str(value)
        elif kind == "duration":
            choices = (("",) if spec.optional else ()) + ("Vanilla", "0", "1", "2", "3", "5", "10", "30", "60")
            display = "" if blank_optional else str(value)

        var = tk.StringVar(value=str(display))
        self.vars[spec.key] = var
        if choices:
            widget = ttk.Combobox(self.form, textvariable=var, values=choices, state="normal" if kind in {"amount", "duration"} else "readonly")
            widget.bind("<<ComboboxSelected>>", lambda _e: self._update_preview())
            widget.bind("<KeyRelease>", lambda _e: self._update_preview())
        else:
            widget = ttk.Entry(self.form, textvariable=var)
            var.trace_add("write", lambda *_: self._update_preview())
        return widget

    @staticmethod
    def _decode_choice(spec: FieldSpec, raw: Any) -> Any:
        if spec.kind == "bool":
            return bool(raw)
        if spec.kind in {"alliance_matrix", "vision_matrix", "victory_matrix", "diplomacy_matrix"}:
            return raw
        text = str(raw).strip()
        if spec.optional and text == "":
            return None
        if spec.kind == "players":
            if isinstance(raw, (list, tuple, set)):
                return sorted(set(int(player) for player in raw))
            return sorted(PlayerMultiSelectWidget._normalize(raw))
        if spec.kind == "player":
            folded = text.casefold()
            if folded in {"local human", "local player", "current local player"}:
                return -2
            if folded in {"first non-local slot", "first non local slot", "non-local", "non local"}:
                return -3
            if folded.startswith("player "):
                return int(text.split()[-1], 10) - 1
            return int(text, 10)
        if spec.kind in {"unit", "mobile_unit", "building", "building_any", "missile"}:
            if text.casefold() == "any":
                return "Any"
            import re
            match = re.search(r"\b(\d{1,3})\b", text)
            if not match:
                raise ValueError(f"Could not read an ID from {text!r}")
            return int(match.group(1), 10)
        if spec.kind == "sound":
            first = text.split("/", 1)[0].strip()
            return SPELL_SOUND_NAMES[int(first, 10)]
        if spec.kind == "int":
            return int(text, 0)
        if spec.kind == "amount":
            return "All" if text.casefold() == "all" else int(text, 0)
        if spec.kind == "duration":
            return "Vanilla" if text.casefold() == "vanilla" else float(text)
        return text

    def _collect_args(self, silent: bool = False) -> dict[str, Any]:
        args: dict[str, Any] = {}
        for spec in self._field_specs:
            holder = self.vars.get(spec.key)
            if isinstance(holder, tk.Text):
                raw = holder.get("1.0", "end-1c")
            elif hasattr(holder, "get"):
                raw = holder.get()
            else:
                raw = holder
            try:
                value = self._decode_choice(spec, raw)
            except (TypeError, ValueError) as exc:
                if silent:
                    continue
                raise ValueError(f"{spec.label}: {exc}") from exc
            if value is None:
                continue
            args[spec.key] = value
        return args

    def _update_preview(self) -> None:
        try:
            clause = Clause(self._actual_kind(), self._collect_args(silent=True))
            self.preview_var.set(clause_summary(clause))
        except Exception:
            self.preview_var.set(display_kind(self.mode, self._actual_kind()))

    def _accept(self) -> None:
        try:
            args = self._collect_args()
            self._validate_args(args)
            self.result = Clause(self._actual_kind(), args)
        except Exception as exc:
            messagebox.showerror("Invalid clause", str(exc), parent=self)
            return
        self.destroy()

    def _validate_args(self, args: dict[str, Any]) -> None:
        kind = self._actual_kind()
        for key in ("player", "target_player", "to_player", "caster_player", "sound_player", "killer_player", "recipient_player", "other_player", "source_player", "viewer_player"):
            if key in args and not 0 <= int(args[key]) <= 15:
                raise ValueError(f"{key.replace('_', ' ').title()} must be Player 1 through Player 16")
        if "amount" in args and args["amount"] != "All" and kind not in {"Unit Property"}:
            int(args["amount"])
        if kind == "Call Trigger Function":
            value = json.loads(str(args.get("arguments_json", "{}")))
            if not isinstance(value, dict):
                raise ValueError("Function arguments must be a JSON object")
        if kind == "Register Shop Item":
            value = json.loads(str(args.get("bonuses_json", "{}")) or "{}")
            if not isinstance(value, dict):
                raise ValueError("Equipment bonuses must be a JSON object")
        if kind == "Start Reinforcement Director":
            value = json.loads(str(args.get("stages_json", "[]")) or "[]")
            if not isinstance(value, list) or any(not isinstance(stage, dict) for stage in value):
                raise ValueError("Reinforcement stages must be a JSON list of objects")
        if kind == "Start Vote":
            raw = str(args.get("options", "[]")).strip()
            value = json.loads(raw) if raw.startswith("[") else [item.strip() for item in raw.split(",") if item.strip()]
            if not isinstance(value, list) or len(value) < 2:
                raise ValueError("A vote requires at least two options")
        if kind == "Order":
            order = str(args.get("order", "Move")).strip().title()
            if order in {"Move", "Attack", "Patrol"} and (args.get("destination", "Anywhere") or "Anywhere") == "Anywhere":
                if "x" not in args or "y" not in args:
                    raise ValueError(f"{order} Order at Anywhere requires Tile X and Tile Y")
        if kind == "Set Game Speed":
            speed = str(args.get("speed", "Fastest")).strip()
            if speed not in GAME_SPEED_LEVELS and not (speed.isdigit() and 0 <= int(speed) <= 6):
                raise ValueError("Game speed must be Slowest, Slower, Slow, Normal, Fast, Faster, Fastest, or numeric 0 through 6")
        if kind == "Set Player Relations":
            matrix=args.get("matrix", {})
            if not isinstance(matrix, dict): raise ValueError("Player relation matrix is invalid")
            for key in ("alliance", "vision"):
                rows=matrix.get(key, [])
                if len(rows)!=8: raise ValueError(f"{key.title()} matrix must contain all 8 players")
                for p,row in enumerate(rows):
                    if p not in set(int(x) for x in row): raise ValueError(f"Player {p+1} cannot disable its own {key}")
        if kind in {"Set Alliance", "Set Allied Victory", "Set Shared Vision"}:
            reference_mode = str(args.get("player_reference_mode", PLAYER_REFERENCE_MODES[0]))
            if reference_mode not in PLAYER_REFERENCE_MODES:
                raise ValueError("Player numbering must use live owner slots or displayed fixed colors")
            if "matrix" in args:
                rows = args.get("matrix")
                if not isinstance(rows, list) or len(rows) != 8:
                    raise ValueError(f"{kind} matrix must contain all 8 player rows")
                for source, row in enumerate(rows):
                    if not isinstance(row, (list, tuple, set)):
                        raise ValueError(f"Player {source + 1} row is invalid")
                    normalized = {int(target) for target in row}
                    if any(not 0 <= target <= 7 for target in normalized):
                        raise ValueError(f"Player {source + 1} row supports Player 1 through Player 8")
                    if source not in normalized:
                        raise ValueError(f"Player {source + 1} cannot disable its own relation")
            else:
                # Backward compatibility for trigger files created before 1.23.24.
                keys = {
                    "Set Alliance": ("players", "other_players"),
                    "Set Allied Victory": ("players",),
                    "Set Shared Vision": ("source_players", "viewer_players"),
                }[kind]
                for key in keys:
                    values = args.get(key, [])
                    if not isinstance(values, (list, tuple, set)):
                        values = [values]
                    if not values:
                        raise ValueError(f"{key.replace('_', ' ').title()} requires at least one player")
                    if any(not 0 <= int(value) <= 7 for value in values):
                        raise ValueError(f"{key.replace('_', ' ').title()} supports Player 1 through Player 8")
        if kind == "Award Kill Resources":
            if int(args.get("amount_per_kill", 0)) < 0:
                raise ValueError("Amount per kill cannot be negative")
        if kind == "Play Sound":
            if args.get("source", "Location") == "Location" and args.get("location", "Anywhere") == "Anywhere":
                if "x" not in args or "y" not in args:
                    raise ValueError("Play Sound at Anywhere requires Tile X and Tile Y")
        if kind in {"Game Message", "Player Chat"}:
            template = str(args.get("text", "")).replace("\x00", " ")
            if not template.strip():
                raise ValueError(f"{kind} template cannot be empty")
            if len(template) > 2048:
                raise ValueError(f"{kind} templates are limited to 2048 editor characters")
            if kind == "Game Message":
                seconds = int(args.get("seconds", 4))
                if not 1 <= seconds <= 60:
                    raise ValueError("Game Message display seconds must be from 1 through 60")
        if kind == "Cast Spell":
            spell_key = str(args.get("spell", "Runes")).casefold()
            cast_mode = str(args.get("cast_mode", "Automatic"))
            if cast_mode == "Caster-free effect" and spell_key not in {"runes", "holy vision"}:
                raise ValueError("Caster-free mode is supported only for Runes and Holy Vision")
            if spell_key in GROUND_TARGET_SPELLS:
                source = str(args.get("map_target_source", "Location / coordinates"))
                if source == "Location / coordinates":
                    location_name = args.get("location", "Anywhere") or "Anywhere"
                    implicit_unit_target = (
                        args.get("target_unit", "Any") not in (None, "", "Any")
                        or (args.get("target_location", "Anywhere") or "Anywhere") != "Anywhere"
                    )
                    if (
                        location_name == "Anywhere"
                        and ("x" not in args or "y" not in args)
                        and not implicit_unit_target
                    ):
                        raise ValueError(
                            "Ground spell target needs Tile X and Tile Y, a named location, "
                            "or a matching Unit / point target"
                        )
            target_amount = args.get("target_amount", "All")
            if target_amount != "All" and not 1 <= int(target_amount) <= 64:
                raise ValueError("Maximum targets / points must be 1 through 64, or All")
            if spell_key in UNIT_TARGET_SPELLS:
                health_mode = str(args.get("target_health", "Spell default"))
                threshold = int(args.get("target_health_value", 50))
                if "%" in health_mode and not 0 <= threshold <= 100:
                    raise ValueError("Spell target percentage threshold must be 0 through 100")
                if "HP" in health_mode and threshold < 0:
                    raise ValueError("Spell target HP threshold cannot be negative")
        if kind in {"Move Units", "Order"} and args.get("order", "Move") != "Attack":
            if args.get("destination", "Anywhere") == "Anywhere" and ("x" not in args or "y" not in args):
                raise ValueError("Anywhere destination requires Tile X and Tile Y")
        if kind in {"Create Units", "Create Completed Buildings"}:
            if kind == "Create Completed Buildings" and args.get("unit") == "Any":
                raise ValueError("Create Completed Buildings requires one exact building type")
            if args.get("location", "Anywhere") == "Anywhere" and ("x" not in args or "y" not in args):
                raise ValueError(f"{kind} at Anywhere requires Tile X and Tile Y")

    def _test_sound(self) -> None:
        if not self.live_preview:
            return
        try:
            args = self._collect_args()
            self._validate_args(args)
            self.live_preview(args)
        except Exception as exc:
            messagebox.showerror("Sound preview", str(exc), parent=self)


def edit_clause(
    master: tk.Misc,
    scenario: Scenario,
    mode: str,
    clause: Clause | None = None,
    live_preview: Callable[[dict[str, Any]], None] | None = None,
    initial_kind: str | None = None,
) -> Clause | None:
    dialog = ClauseDialog(master, scenario, mode, clause, live_preview, initial_kind)
    master.wait_window(dialog)
    return dialog.result


# ---------------------------------------------------------------------------
# 1.28.1 TD Raise Tower extension.
# ---------------------------------------------------------------------------
for _kind in ("Enable Death Knight Tower Builder", "Disable Death Knight Tower Builder"):
    if _kind not in ACTIONS:
        ACTIONS.append(_kind)
ACTION_CATEGORIES["Tower defense systems"] = (
    "Enable Death Knight Tower Builder",
    "Disable Death Knight Tower Builder",
)
ACTION_SCHEMAS.update({
    "Enable Death Knight Tower Builder": (
        _field("player", "Builder owner", "player", 0),
        _field("caster_unit", "Death Knight caster", "mobile_unit", 11),
        _field("tower_unit", "Tower building", "building", 97),
        _field("mana_cost", "Mana per tower", "int", 50),
        _field("location_prefix", "Allowed pad location prefix", "text", "Tower Pad "),
    ),
    "Disable Death Knight Tower Builder": (),
})
KIND_HELP.update({
    "Enable Death Knight Tower Builder": "Repurposes only the selected player's Death Knight Raise Dead effect into instant tower placement on named Tower Pad locations. No corpse is required; native Raise Dead remains intact for other players. The spell range is temporarily global and restored when disabled or detached.",
    "Disable Death Knight Tower Builder": "Restores Warcraft's native Raise Dead dispatch and six-tile range.",
})

# ---------------------------------------------------------------------------
# 1.30 Complete Mission Scripting expansion.
# legacy-source feature coverage: production/resource/transport/capture events,
# generation-safe scene choreography, 8-line transmission history, external
# campaign checkpoints, and fail-closed probes for modern Remastered campaign UI.
MISSION130_EVENT_TYPES = (
    "Construction Started", "Construction Completed", "Construction Cancelled",
    "Training Started", "Unit Trained", "Technology Research Started",
    "Technology Research Completed", "Spell Research Started", "Spell Research Completed",
    "Upgrade Completed", "Resource Deposited", "Worker Returned Resources", "Worker Entered Resource",
    "Worker Entered Mine", "Worker Entered Oil Patch", "Worker Exited Resource", "Passenger Boarded Transport", "Passenger Unloaded Transport",
    "Unit Captured", "Unit Rescued", "Projectile Hit Unit", "Projectile Hit Location",
    "Unit Order Changed", "Player Issued Order (Inferred)", "Player Command Button Used (Inferred)", "Unit Selected", "Unit Deselected", "Actor Selected", "Actor Deselected",
    "Enemy Entered Actor Sight", "Enemy Left Actor Sight",
    "Enemy Entered Actor Attack Range", "Enemy Left Actor Attack Range",
)
MISSION130_CONDITIONS = [
    *MISSION130_EVENT_TYPES,
    "Mission Event Count", "Transmission History Count", "Campaign Checkpoint Exists",
    "Campaign UI Capability", "Cutscene Input Lock State",
]
MISSION130_ACTIONS = [
    "Scene Transmission", "Scene Narration", "Show Transmission History", "Clear Transmission History",
    "Lock Cutscene Input", "Unlock Cutscene Input",
    "Save Campaign Checkpoint", "Load Campaign Checkpoint", "Delete Campaign Checkpoint",
    "Scene Actor Follow Actor", "Scene Actor Flee From Actor", "Scene Actor Repair Actor",
    "Scene Actor Demolish Actor", "Scene Actor Harvest Actor", "Scene Actor Return Resources",
    "Scene Actor Board Transport", "Scene Actor Unload From Transport",
    "Scene Actor Rescue To Player", "Scene Actor Capture By Player",
    "Scene Actor Select", "Scene Actor Deselect", "Scene Actor Voice", "Scene Actor Build Building",
    "Scene Wait For Audio", "Scene Fade In (Experimental)", "Scene Fade Out (Experimental)",
    "Scene Set Music (Experimental)", "Scene Fade Music (Experimental)", "Scene Stop Music (Experimental)",
    "Scene Group Move", "Scene Group Attack", "Scene Group Patrol", "Scene Group Die", "Scene Group Face",
    "Probe Campaign UI", "Show Native Objectives HUD (Experimental)",
    "Open Native Scenario Objectives (Experimental)", "Show Native Mission Briefing (Experimental)",
    "Native Portrait Transmission (Experimental)", "Native Campaign Interlude (Experimental)",
    "Play Cinematic Movie (Experimental)", "Native Save Extension (Experimental)",
]
for _kind in MISSION130_CONDITIONS:
    if _kind not in CONDITIONS:
        CONDITIONS.append(_kind)
for _kind in MISSION130_ACTIONS:
    if _kind not in ACTIONS:
        ACTIONS.append(_kind)

CONDITION_CATEGORIES.update({
    "Mission events — construction & production 1.30": (
        "Construction Started", "Construction Completed", "Construction Cancelled",
        "Training Started", "Unit Trained", "Technology Research Started",
        "Technology Research Completed", "Spell Research Started", "Spell Research Completed", "Upgrade Completed",
    ),
    "Mission events — economy, transport & ownership 1.30": (
        "Resource Deposited", "Worker Returned Resources", "Worker Entered Resource", "Worker Entered Mine", "Worker Entered Oil Patch", "Worker Exited Resource",
        "Passenger Boarded Transport", "Passenger Unloaded Transport", "Unit Captured", "Unit Rescued",
    ),
    "Mission events — combat, orders & selection 1.30": (
        "Projectile Hit Unit", "Projectile Hit Location", "Unit Order Changed", "Player Issued Order (Inferred)", "Player Command Button Used (Inferred)", "Unit Selected", "Unit Deselected",
        "Actor Selected", "Actor Deselected", "Enemy Entered Actor Sight", "Enemy Left Actor Sight",
        "Enemy Entered Actor Attack Range", "Enemy Left Actor Attack Range", "Mission Event Count",
    ),
    "Campaign persistence & native UI capability 1.30": (
        "Transmission History Count", "Campaign Checkpoint Exists", "Campaign UI Capability", "Cutscene Input Lock State",
    ),
})
ACTION_CATEGORIES.update({
    "Cutscene transmissions & input 1.30": (
        "Scene Transmission", "Scene Narration", "Show Transmission History", "Clear Transmission History",
        "Lock Cutscene Input", "Unlock Cutscene Input", "Scene Wait For Audio",
        "Scene Fade In (Experimental)", "Scene Fade Out (Experimental)",
        "Scene Set Music (Experimental)", "Scene Fade Music (Experimental)", "Scene Stop Music (Experimental)",
    ),
    "Cutscene actor choreography 1.30": (
        "Scene Actor Follow Actor", "Scene Actor Flee From Actor", "Scene Actor Repair Actor",
        "Scene Actor Demolish Actor", "Scene Actor Harvest Actor", "Scene Actor Return Resources",
        "Scene Actor Board Transport", "Scene Actor Unload From Transport",
        "Scene Actor Rescue To Player", "Scene Actor Capture By Player",
        "Scene Actor Select", "Scene Actor Deselect", "Scene Actor Voice", "Scene Actor Build Building",
        "Scene Group Move", "Scene Group Attack", "Scene Group Patrol", "Scene Group Die", "Scene Group Face",
    ),
    "Campaign checkpoints 1.30": (
        "Save Campaign Checkpoint", "Load Campaign Checkpoint", "Delete Campaign Checkpoint", "Native Save Extension (Experimental)",
    ),
    "Native campaign frontend — experimental / fail-closed 1.30": (
        "Probe Campaign UI", "Show Native Objectives HUD (Experimental)", "Open Native Scenario Objectives (Experimental)",
        "Show Native Mission Briefing (Experimental)", "Native Portrait Transmission (Experimental)",
        "Native Campaign Interlude (Experimental)", "Play Cinematic Movie (Experimental)",
    ),
})

# Expand the generic Event Available picker so every 1.30 edge event can also be
# consumed through the old generic event-context action family.
CONDITION_SCHEMAS["Event Available"] = (
    _field("event_type", "Event type", "choice", "Any", ("Any", "Unit Created", "Unit Died", "Unit Removed", "Unit Entered Location", "Unit Left Location", "Unit Damaged", "Unit Healed", "Unit Under Attack") + MISSION130_EVENT_TYPES),
    _field("comparison", "Comparison", "choice", "At least", COMPARISONS),
    _field("amount", "Available (1=yes)", "int", 1),
)

_EVENT_BASE = (
    _field("player", "Player / receiving owner", "player", None, optional=True),
    _field("unit", "Unit type", "unit", "Any", optional=True),
    _field("location", "Location", "location", "Anywhere", optional=True),
)
for _kind in (
    "Construction Started", "Construction Completed", "Construction Cancelled",
    "Training Started", "Unit Trained", "Technology Research Started", "Technology Research Completed",
    "Spell Research Started", "Spell Research Completed", "Upgrade Completed",
    "Unit Captured", "Unit Rescued", "Projectile Hit Unit", "Projectile Hit Location",
    "Unit Order Changed", "Player Issued Order (Inferred)", "Player Command Button Used (Inferred)", "Unit Selected", "Unit Deselected",
):
    CONDITION_SCHEMAS[_kind] = _EVENT_BASE + COUNT_FIELDS

CONDITION_SCHEMAS["Resource Deposited"] = _EVENT_BASE + (
    _field("resource", "Resource", "choice", "Any resource", ("Any resource", "Gold", "Lumber", "Oil")),
) + COUNT_FIELDS
CONDITION_SCHEMAS["Worker Returned Resources"] = CONDITION_SCHEMAS["Resource Deposited"]
CONDITION_SCHEMAS["Worker Entered Resource"] = _EVENT_BASE + COUNT_FIELDS
CONDITION_SCHEMAS["Worker Entered Mine"] = _EVENT_BASE + COUNT_FIELDS
CONDITION_SCHEMAS["Worker Entered Oil Patch"] = _EVENT_BASE + COUNT_FIELDS
CONDITION_SCHEMAS["Worker Exited Resource"] = _EVENT_BASE + COUNT_FIELDS
CONDITION_SCHEMAS["Passenger Boarded Transport"] = _EVENT_BASE + COUNT_FIELDS
CONDITION_SCHEMAS["Passenger Unloaded Transport"] = _EVENT_BASE + COUNT_FIELDS
CONDITION_SCHEMAS["Actor Selected"] = (
    _field("actor", "Scene actor", "text", "Archer"),
) + COUNT_FIELDS
CONDITION_SCHEMAS["Actor Deselected"] = CONDITION_SCHEMAS["Actor Selected"]
for _kind in ("Enemy Entered Actor Sight", "Enemy Left Actor Sight", "Enemy Entered Actor Attack Range", "Enemy Left Actor Attack Range"):
    CONDITION_SCHEMAS[_kind] = (
        _field("actor", "Watching scene actor", "text", "Archer"),
        _field("player", "Enemy owner", "player", None, optional=True),
        _field("unit", "Enemy unit type", "unit", "Any", optional=True),
        _field("location", "Enemy location", "location", "Anywhere", optional=True),
    ) + COUNT_FIELDS
CONDITION_SCHEMAS["Mission Event Count"] = (
    _field("event_type", "Event type", "choice", "Unit Created", ("Unit Created", "Unit Died", "Unit Removed", "Unit Entered Location", "Unit Left Location", "Unit Damaged", "Unit Healed", "Unit Under Attack") + MISSION130_EVENT_TYPES),
    _field("player", "Player", "player", None, optional=True),
    _field("unit", "Unit type", "unit", "Any", optional=True),
    _field("location", "Location", "location", "Anywhere", optional=True),
) + COUNT_FIELDS
CONDITION_SCHEMAS["Transmission History Count"] = COUNT_FIELDS
CONDITION_SCHEMAS["Campaign Checkpoint Exists"] = (
    _field("name", "Checkpoint name", "text", "checkpoint"),
) + COUNT_FIELDS
CONDITION_SCHEMAS["Campaign UI Capability"] = (
    _field("state", "Capability", "choice", "Detected / ABI Unverified", ("Detected / ABI Unverified", "Unavailable")),
)
CONDITION_SCHEMAS["Cutscene Input Lock State"] = (
    _field("state", "Input state", "choice", "Soft Locked", ("Unlocked", "Soft Locked", "Experimental / Fail Closed")),
)

# The comparison engine compares enum-returning conditions against their schema's
# state field, so keep the established enum pattern used by Cutscene State.

_TRANSMISSION_COMMON = (
    _field("actor", "Scene actor/reference", "text", "Archer", optional=True),
    _field("speaker", "Speaker label", "text", "Archer"),
    _field("text", "Dialogue / narration", "multiline", "We cannot hold them much longer!"),
    _field("voice_bark", "Play native unit voice bark", "bool", True),
    _field("center_camera", "Center camera on speaker", "bool", False),
    _field("wait", "Wait for transmission duration", "bool", True),
    _field("seconds", "Duration seconds", "float", 4.0),
    _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
    _field("color", "Text color", "choice", "White — native highlight", PLAYER_CHAT_COLORS),
)
ACTION_SCHEMAS["Scene Transmission"] = _TRANSMISSION_COMMON
ACTION_SCHEMAS["Scene Narration"] = (
    _field("speaker", "Narrator label", "text", "Narrator"),
    _field("text", "Narration", "multiline", "The battle for Lordaeron begins..."),
    _field("wait", "Wait for narration duration", "bool", True),
    _field("seconds", "Duration seconds", "float", 5.0),
    _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
    _field("color", "Text color", "choice", "White — native highlight", PLAYER_CHAT_COLORS),
)
ACTION_SCHEMAS["Show Transmission History"] = (
    _field("seconds", "Display seconds", "int", 8),
    _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
    _field("color", "Text color", "choice", "White — native highlight", PLAYER_CHAT_COLORS),
)
ACTION_SCHEMAS["Clear Transmission History"] = ()
ACTION_SCHEMAS["Lock Cutscene Input"] = (
    _field("mode", "Input lock mode", "choice", "Soft Lock", ("Off", "Soft Lock", "Experimental Native (Fail Closed)")),
    _field("fallback_to_soft_lock", "Fallback to safe soft lock", "bool", True),
)
ACTION_SCHEMAS["Unlock Cutscene Input"] = ()
# Upgrade the 1.29 Begin Cutscene schema in place.
ACTION_SCHEMAS["Begin Cutscene"] = (
    _field("name", "Scene name", "text", "Intro Scene"),
    _field("input_mode", "Input lock mode", "choice", "Soft Lock", ("Off", "Soft Lock", "Experimental Native (Fail Closed)")),
    _field("fallback_to_soft_lock", "Fallback to safe soft lock", "bool", True),
    _field("mark_input_locked", "Set authoring input-lock state", "bool", True),
    _field("hide_objectives", "Hide objective banner during scene", "bool", True),
    _field("deselect_units", "Deselect current units", "bool", True),
)

_CHECKPOINT_NAME = (_field("name", "Checkpoint name", "text", "checkpoint"),)
ACTION_SCHEMAS["Save Campaign Checkpoint"] = _CHECKPOINT_NAME
ACTION_SCHEMAS["Load Campaign Checkpoint"] = _CHECKPOINT_NAME + (
    _field("restore_resources", "Restore Gold/Lumber/Oil", "bool", True),
    _field("restore_camera", "Restore saved camera", "bool", True),
    _field("recreate_missing_actors", "Recreate missing live actors", "bool", False),
)
ACTION_SCHEMAS["Delete Campaign Checkpoint"] = _CHECKPOINT_NAME

_ACTOR_PAIR = (
    _field("actor", "Scene actor", "text", "Archer"),
    _field("target_actor", "Target scene actor", "text", "Target"),
)
ACTION_SCHEMAS["Scene Actor Follow Actor"] = _ACTOR_PAIR
ACTION_SCHEMAS["Scene Actor Flee From Actor"] = _ACTOR_PAIR + (_field("distance", "Flee distance in tiles", "int", 6),)
ACTION_SCHEMAS["Scene Actor Repair Actor"] = _ACTOR_PAIR
ACTION_SCHEMAS["Scene Actor Demolish Actor"] = _ACTOR_PAIR
ACTION_SCHEMAS["Scene Actor Harvest Actor"] = _ACTOR_PAIR
ACTION_SCHEMAS["Scene Actor Return Resources"] = _SCENE_ACTOR
ACTION_SCHEMAS["Scene Actor Board Transport"] = (
    _field("actor", "Passenger scene actor", "text", "Archer"),
    _field("transport_actor", "Transport scene actor", "text", "Transport"),
)
ACTION_SCHEMAS["Scene Actor Unload From Transport"] = _SCENE_ACTOR
ACTION_SCHEMAS["Scene Actor Rescue To Player"] = _SCENE_ACTOR + (_field("new_owner", "Rescuing player", "player", 0),)
ACTION_SCHEMAS["Scene Actor Capture By Player"] = _SCENE_ACTOR + (_field("new_owner", "Capturing player", "player", 0),)
ACTION_SCHEMAS["Scene Actor Select"] = _SCENE_ACTOR
ACTION_SCHEMAS["Scene Actor Deselect"] = _SCENE_ACTOR
ACTION_SCHEMAS["Scene Actor Voice"] = _SCENE_ACTOR + (
    _field("event", "Voice / sound event", "choice", "Selection", ("Selection", "Acknowledgement", "Attack", "Under Attack", "Harvest", "Unit Death", "Building Destruction", "Build Started", "Build Complete", "Rescue", "Capture", "Dock", "Spell Sound")),
    _field("sound", "Spell/effect sound when event=Spell Sound", "text", "Thunder", optional=True),
    _field("estimated_seconds", "Estimated audio duration", "float", 1.5),
)
ACTION_SCHEMAS["Scene Actor Build Building"] = _SCENE_ACTOR + (
    _field("new_building", "Building type", "building", 58),
    _field("building_actor", "Save foundation as scene actor", "text", "", optional=True),
) + _SCENE_POINT
ACTION_SCHEMAS["Scene Wait For Audio"] = (_field("seconds", "Minimum wait seconds", "float", 0.0),)
ACTION_SCHEMAS["Scene Fade In (Experimental)"] = (
    _field("seconds", "Fade duration", "float", 0.75),
    _field("fallback_to_timing_only", "Fallback to timing-only authoring", "bool", True),
)
ACTION_SCHEMAS["Scene Fade Out (Experimental)"] = ACTION_SCHEMAS["Scene Fade In (Experimental)"]
ACTION_SCHEMAS["Scene Set Music (Experimental)"] = (
    _field("track", "Music asset / track name", "text", ""),
    _field("volume", "Volume 0-100", "int", 100),
    _field("fallback_to_state_only", "Fallback to authored state only", "bool", True),
)
ACTION_SCHEMAS["Scene Fade Music (Experimental)"] = (
    _field("to_volume", "Target volume 0-100", "int", 0),
    _field("seconds", "Fade duration", "float", 1.0),
    _field("fallback_to_state_only", "Fallback to authored state only", "bool", True),
)
ACTION_SCHEMAS["Scene Stop Music (Experimental)"] = (_field("fallback_to_state_only", "Fallback to authored state only", "bool", True),)

_GROUP_ACTORS = (_field("actors", "Actor names, comma-separated", "text", "Archer 1, Archer 2, Archer 3"),)
_GROUP_POINT = _GROUP_ACTORS + _SCENE_POINT
ACTION_SCHEMAS["Scene Group Move"] = _GROUP_POINT
ACTION_SCHEMAS["Scene Group Attack"] = _GROUP_POINT
ACTION_SCHEMAS["Scene Group Patrol"] = _GROUP_POINT
ACTION_SCHEMAS["Scene Group Die"] = _GROUP_ACTORS
ACTION_SCHEMAS["Scene Group Face"] = _GROUP_ACTORS + (_field("facing", "Facing 0=N ... 7=NW", "int", 0),)

_EXPERIMENTAL_SAFE = (
    _field("fallback_to_safe", "Use safe fallback instead of error", "bool", True),
)
ACTION_SCHEMAS["Probe Campaign UI"] = (_field("show_message", "Show probe result in game", "bool", True),)
ACTION_SCHEMAS["Show Native Objectives HUD (Experimental)"] = (
    _field("refresh_seconds", "Fallback HUD refresh", "float", 3.5),
    _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
    _field("color", "HUD color", "choice", "Yellow / gold — native normal", PLAYER_CHAT_COLORS),
) + _EXPERIMENTAL_SAFE
ACTION_SCHEMAS["Open Native Scenario Objectives (Experimental)"] = _EXPERIMENTAL_SAFE
ACTION_SCHEMAS["Show Native Mission Briefing (Experimental)"] = ACTION_SCHEMAS["Show Mission Briefing"] + _EXPERIMENTAL_SAFE
ACTION_SCHEMAS["Native Portrait Transmission (Experimental)"] = _TRANSMISSION_COMMON + _EXPERIMENTAL_SAFE
ACTION_SCHEMAS["Native Campaign Interlude (Experimental)"] = (
    _field("title", "Interlude / act title", "text", "ACT I"),
    _field("subtitle", "Subtitle", "text", "The Gathering Storm"),
    _field("text", "Fallback text", "multiline", ""),
    _field("seconds", "Display seconds", "float", 5.0),
    _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
    _field("color", "Text color", "choice", "White — native highlight", PLAYER_CHAT_COLORS),
) + _EXPERIMENTAL_SAFE
ACTION_SCHEMAS["Play Cinematic Movie (Experimental)"] = (
    _field("movie", "Movie / cinematic asset name", "text", ""),
    _field("title", "Fallback title", "text", "CINEMATIC"),
    _field("fallback_text", "Fallback text", "multiline", ""),
    _field("seconds", "Fallback display seconds", "float", 5.0),
    _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
    _field("color", "Text color", "choice", "White — native highlight", PLAYER_CHAT_COLORS),
) + _EXPERIMENTAL_SAFE
ACTION_SCHEMAS["Native Save Extension (Experimental)"] = _CHECKPOINT_NAME + _EXPERIMENTAL_SAFE

KIND_HELP.update({
    "Construction Started": "Edge event when a newly-created building exists without SF_COMPLETED.",
    "Construction Completed": "Edge event when the same building changes from incomplete to SF_COMPLETED.",
    "Construction Cancelled": "Safe inferred edge: an unfinished building disappeared before completion. Until the native cancel-order hook is verified this can also include destruction of an unfinished building.",
    "Training Started": "Native-verified production edge from UF_BUILD_ON + TBuild.bldOrder=BUILD_UNIT.",
    "Unit Trained": "Native-verified production-completion edge correlated with the newly created trained unit when possible.",
    "Technology Research Started": "Native-verified BUILD_TECH/BUILD_UPGRADE production start edge.",
    "Technology Research Completed": "Native-verified production completion edge for technology/building upgrade work.",
    "Spell Research Started": "Native-verified BUILD_SPELL production start edge.",
    "Spell Research Completed": "Detects newly-set bits in the validated glSpells player array.",
    "Upgrade Completed": "Detects level increases in the source-correlated sgbTechTbl when its live resolver is unambiguous.",
    "Resource Deposited": "Detects a Peon/Peasant/Tanker loaded-cargo transition to empty and exposes resource + deposited amount in event context.",
    "Worker Entered Resource": "Inferred source-engine edge from a worker/tanker becoming hidden outside a transport. Intended for mine/oil harvesting scenes.",
    "Worker Exited Resource": "Inferred source-engine edge from a worker/tanker leaving hidden resource occupancy.",
    "Passenger Boarded Transport": "Detects a new slot in the native six-entry transport cargo array.",
    "Passenger Unloaded Transport": "Detects removal from the native six-entry transport cargo array.",
    "Unit Captured": "Detects a live unit's owner change and exposes old_owner/new_owner through event context.",
    "Unit Rescued": "Publishes the already native-verified rescue edge from Trigger Studio's rescue system.",
    "Projectile Hit Unit": "Inferred projectile impact event: a native missile disappeared while retaining a live unit target. Exact impact-vs-expiry separation remains unverified and is flagged in event context.",
    "Projectile Hit Location": "Inferred projectile impact event for a missile that disappeared with a point target.",
    "Unit Order Changed": "Detects action/next-action/target changes. This can be caused by player, AI, combat or triggers; it does not falsely claim a human click.",
    "Actor Selected": "Named scene-actor selection edge using Warcraft's validated SF_SELECTED bit.",
    "Actor Deselected": "Named scene-actor deselection edge using Warcraft's validated SF_SELECTED bit.",
    "Enemy Entered Actor Sight": "Named actor proximity edge using the live/overridden source sight-range rule and native diplomacy matrix.",
    "Enemy Entered Actor Attack Range": "Named actor proximity edge using the live/overridden source attack-range rule and native diplomacy matrix.",
    "Scene Transmission": "Campaign-style authored transmission: optional camera cut + native unit bark + Warcraft game text + last-eight history. The modern portrait widget remains experimental.",
    "Scene Narration": "Narrator transmission with wait/history support and no actor requirement.",
    "Lock Cutscene Input": "Soft Lock continuously clears native selection during a scene. Experimental Native fails closed unless safe fallback is enabled; no unverified Remastered input callback is patched.",
    "Save Campaign Checkpoint": "Writes Trigger Studio mission state to checkpoints/<name>.json: variables, counters, switches, timers, objectives, actors, resources, transmissions and camera. This is external state, not Warcraft SFILE injection.",
    "Load Campaign Checkpoint": "Restores an external 1.30 checkpoint using generation-safe actor rematching; it never restores stale raw unit pointers.",
    "Scene Actor Follow Actor": "Uses native-verified do_follow against a named target actor.",
    "Scene Actor Flee From Actor": "Computes a safe tile away from the target and queues Warcraft's normal Move order.",
    "Scene Actor Repair Actor": "Uses native-verified do_repair against a named actor/building.",
    "Scene Actor Demolish Actor": "Uses native-verified do_demolish against a named actor/building.",
    "Scene Actor Harvest Actor": "Uses native-verified do_harvest against a named resource actor/node.",
    "Scene Actor Board Transport": "Orders the named actor toward a named transport using the same native-verified boarding path as Source Board Transport.",
    "Scene Actor Unload From Transport": "Finds the actor's live transport slot and calls native-verified unit_unload_transport.",
    "Worker Returned Resources": "Alias of the source cargo-loaded to empty deposit edge, with Gold/Lumber/Oil and deposited amount in event context.",
    "Worker Entered Mine": "Peon/Peasant hidden-resource occupancy edge, separated from tanker oil-patch entry.",
    "Worker Entered Oil Patch": "Tanker hidden-resource occupancy edge for oil harvesting.",
    "Player Issued Order (Inferred)": "A selected local-human unit changed its native action/target state. Useful for scenes, but deliberately marked Inferred because AI/combat can also alter selected units.",
    "Player Command Button Used (Inferred)": "Selected local unit/building entered a new native action or production state. Exact Remastered command-button callback remains unhooked.",
    "Scene Actor Select": "Sets Warcraft's validated SF_SELECTED bit for the exact named actor.",
    "Scene Actor Deselect": "Uses native deselect_unit when available and otherwise clears the validated SF_SELECTED bit.",
    "Scene Actor Voice": "Uses independently validated GAMESND callbacks for Selection, Under Attack, Harvest, Unit Death, Building Destruction and Spell Sound. Other legacy-named voice events use the verified Selection fallback until their exact 2818 starts are independently mapped.",
    "Scene Actor Build Building": "Creates a native building foundation at the authored point, optionally saves it as a scene actor, then orders the named worker through do_repair/build construction behavior.",
    "Scene Wait For Audio": "Blocks the scene until the last authored actor audio estimate and optional minimum wait have elapsed.",
    "Scene Fade In (Experimental)": "legacy vid_fade proves the presentation feature, but Remastered renderer fade ABI is unverified. This fails closed or uses timing-only fallback; it never claims a visual fade occurred.",
    "Scene Set Music (Experimental)": "Authors campaign music state but does not guess Remastered's music-stream ABI. Disable fallback to fail closed.",
    "Scene Fade Music (Experimental)": "Authors music-fade timing/state while the modern music ABI remains unverified.",
    "Probe Campaign UI": "Scans the live Remastered image for fe_objectives/objectives_header/objectives_background/hide_objectives/generic_objectives markers. Detection is not treated as a verified modern C++ ABI.",
    "Show Native Objectives HUD (Experimental)": "Native Remastered objective widget injection is not allocator/calling-convention safe yet. This action fails closed or uses the validated Trigger Studio HUD fallback.",
    "Native Portrait Transmission (Experimental)": "The Remastered portrait/transmission queue ABI is not proven. Safe fallback uses Scene Transmission and never guesses a C++ object layout.",
    "Play Cinematic Movie (Experimental)": "legacy finale/interlude movie functions are platform-specific. Remastered movie playback ABI is unverified, so this action fails closed or displays a safe authored cinematic card.",
    "Native Save Extension (Experimental)": "legacy SFILE proves campaign save-state exists, but extending Remastered's native save format is unverified. Safe fallback writes the external Trigger Studio checkpoint format.",
})

# Refine production-completion event filters with source-native names.
CONDITION_SCHEMAS["Spell Research Started"] = _EVENT_BASE + (_field("spell", "Spell", "choice", "Any spell", ("Any spell",) + ULTIMATE_SPELL_RESEARCH),) + COUNT_FIELDS
CONDITION_SCHEMAS["Spell Research Completed"] = CONDITION_SCHEMAS["Spell Research Started"]
CONDITION_SCHEMAS["Technology Research Started"] = _EVENT_BASE + (_field("upgrade", "Technology / upgrade", "choice", "Any upgrade", ("Any upgrade",) + ULTIMATE_UPGRADES),) + COUNT_FIELDS
CONDITION_SCHEMAS["Technology Research Completed"] = CONDITION_SCHEMAS["Technology Research Started"]
CONDITION_SCHEMAS["Upgrade Completed"] = CONDITION_SCHEMAS["Technology Research Started"]

# 1.30 scene-building production conveniences backed by bldg_build_start/dispatch.
_M130_PRODUCTION_ACTIONS = ("Scene Actor Train Unit", "Scene Actor Research Technology", "Scene Actor Research Spell", "Scene Actor Upgrade Building", "Scene Actor Cancel Production", "Scene Actor Complete Production")
for _kind in _M130_PRODUCTION_ACTIONS:
    if _kind not in ACTIONS: ACTIONS.append(_kind)
ACTION_CATEGORIES["Cutscene actor choreography 1.30"] = ACTION_CATEGORIES["Cutscene actor choreography 1.30"] + _M130_PRODUCTION_ACTIONS
ACTION_SCHEMAS["Scene Actor Train Unit"] = _SCENE_ACTOR + (_field("new_unit", "Unit to train", "mobile_unit", 0),)
ACTION_SCHEMAS["Scene Actor Research Technology"] = _SCENE_ACTOR + (_field("upgrade", "Technology", "choice", "Melee Attack", ULTIMATE_UPGRADES),)
ACTION_SCHEMAS["Scene Actor Research Spell"] = _SCENE_ACTOR + (_field("spell", "Spell", "choice", "Holy Vision", ULTIMATE_SPELL_RESEARCH),)
ACTION_SCHEMAS["Scene Actor Upgrade Building"] = _SCENE_ACTOR + (_field("new_building", "Upgrade result building", "building", 58),)
ACTION_SCHEMAS["Scene Actor Cancel Production"] = _SCENE_ACTOR
ACTION_SCHEMAS["Scene Actor Complete Production"] = _SCENE_ACTOR
KIND_HELP["Scene Actor Train Unit"] = "Starts native BUILD_UNIT on an exact named building actor through native-verified bldg_build_start; Warcraft still checks cost, prerequisites and busy state."
KIND_HELP["Scene Actor Research Technology"] = "Starts native BUILD_TECH on an exact named building actor."
KIND_HELP["Scene Actor Research Spell"] = "Starts native BUILD_SPELL on an exact named building actor."
KIND_HELP["Scene Actor Upgrade Building"] = "Starts native BUILD_UPGRADE on an exact named building actor."
KIND_HELP["Scene Actor Cancel Production"] = "Sets the source UF_BUILD_CANCEL path on a named building and dispatches native production cancellation."
KIND_HELP["Scene Actor Complete Production"] = "Advances the named building's current production to its native total and lets bldg_dispatch_build finish it."

# 1.30 exact named-actor native spell choreography through do_unit_spell/gwActionType.
_M130_SCENE_SPELL_ACTIONS=("Scene Actor Cast Spell On Actor","Scene Actor Cast Spell At Point")
for _kind in _M130_SCENE_SPELL_ACTIONS:
    if _kind not in ACTIONS: ACTIONS.append(_kind)
ACTION_CATEGORIES["Cutscene actor choreography 1.30"] = ACTION_CATEGORIES["Cutscene actor choreography 1.30"] + _M130_SCENE_SPELL_ACTIONS
ACTION_SCHEMAS["Scene Actor Cast Spell On Actor"] = _SCENE_ACTOR + (_field("spell", "Native spell", "choice", "Fireball", SPELL_NAMES), _field("target_actor", "Target scene actor", "text", "Target"), _field("allow_wrong_caster", "Allow non-native caster type (research only)", "bool", False))
ACTION_SCHEMAS["Scene Actor Cast Spell At Point"] = _SCENE_ACTOR + (_field("spell", "Native spell", "choice", "Blizzard", SPELL_NAMES),) + _SCENE_POINT + (_field("allow_wrong_caster", "Allow non-native caster type (research only)", "bool", False),)
KIND_HELP["Scene Actor Cast Spell On Actor"] = "Queues the exact named actor through validated gwActionType + do_unit_spell with a named PTUnit target. Native caster-class validation is enforced by default."
KIND_HELP["Scene Actor Cast Spell At Point"] = "Queues the exact named actor through validated gwActionType + do_unit_spell with a tile target. Warcraft retains normal native spell action handling."

# ---------------------------------------------------------------------------
# 1.31 Blank-map scenario control + local Windows TTS + scene input helpers.
MISSION131_CONDITIONS = [
    "Native Win/Loss Suppressed",
    "Blank Map Guard Armed",
    "TTS Available",
    "TTS Speaking",
    "Local Key Pressed",
    "Local Key Held",
]
MISSION131_ACTIONS = [
    "Blank Map Bootstrap",
    "Enable Trigger-Controlled Results",
    "Disable Trigger-Controlled Results",
    "Suppress Native Win/Loss",
    "Restore Native Win/Loss",
    "Scene Actor TTS",
    "Scene Narrator TTS",
    "Scene Wait For TTS",
    "Scene Wait For Local Key",
    "Scene Choice",
    "List TTS Voices",
    "Stop TTS",
]
for _kind in MISSION131_CONDITIONS:
    if _kind not in CONDITIONS:
        CONDITIONS.append(_kind)
for _kind in MISSION131_ACTIONS:
    if _kind not in ACTIONS:
        ACTIONS.append(_kind)

CONDITION_CATEGORIES.update({
    "Trigger-driven scenario bootstrap 1.31": (
        "Native Win/Loss Suppressed", "Blank Map Guard Armed",
    ),
    "Local scene input & speech 1.31": (
        "TTS Available", "TTS Speaking", "Local Key Pressed", "Local Key Held",
    ),
})
ACTION_CATEGORIES.update({
    "Trigger-driven scenario bootstrap 1.31": (
        "Blank Map Bootstrap", "Enable Trigger-Controlled Results", "Disable Trigger-Controlled Results",
        "Suppress Native Win/Loss", "Restore Native Win/Loss",
    ),
    "Cutscene speech & local input 1.31": (
        "Scene Actor TTS", "Scene Narrator TTS", "Scene Wait For TTS", "Scene Wait For Local Key", "Scene Choice", "List TTS Voices", "Stop TTS",
    ),
})

_YES_NO = ("Yes", "No")
CONDITION_SCHEMAS["Native Win/Loss Suppressed"] = (
    _field("state", "Suppressed", "choice", "Yes", _YES_NO),
)
CONDITION_SCHEMAS["Blank Map Guard Armed"] = (
    _field("state", "Guard armed", "choice", "Yes", _YES_NO),
)
CONDITION_SCHEMAS["TTS Available"] = (
    _field("state", "TTS available", "choice", "Yes", _YES_NO),
)
CONDITION_SCHEMAS["TTS Speaking"] = (
    _field("state", "Speech active", "choice", "Yes", _YES_NO),
)
_LOCAL_SCENE_KEYS = (
    "Escape", "Space", "Enter", "Tab", "Backspace",
    "Left", "Up", "Right", "Down",
    "0", "1", "2", "3", "4", "5", "6", "7", "8", "9",
    "A", "B", "C", "D", "E", "F", "G", "H", "I", "J", "K", "L", "M",
    "N", "O", "P", "Q", "R", "S", "T", "U", "V", "W", "X", "Y", "Z",
    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12",
)
CONDITION_SCHEMAS["Local Key Pressed"] = (
    _field("key", "Local key", "choice", "Escape", _LOCAL_SCENE_KEYS),
) + COUNT_FIELDS
CONDITION_SCHEMAS["Local Key Held"] = CONDITION_SCHEMAS["Local Key Pressed"]

_BLANK_MESSAGE = (
    _field("message", "Show initialization message", "bool", True),
    _field("text", "Initialization text", "text", "Trigger-controlled scenario initialized."),
    _field("seconds", "Display seconds", "int", 4),
    _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
    _field("color", "Text color", "choice", "White — native highlight", PLAYER_CHAT_COLORS),
)
ACTION_SCHEMAS["Blank Map Bootstrap"] = _BLANK_MESSAGE
ACTION_SCHEMAS["Enable Trigger-Controlled Results"] = ()
ACTION_SCHEMAS["Disable Trigger-Controlled Results"] = ()
ACTION_SCHEMAS["Suppress Native Win/Loss"] = ()
ACTION_SCHEMAS["Restore Native Win/Loss"] = ()

_TTS_COMMON = (
    _field("text", "Speech text", "multiline", "Something is wrong..."),
    _field("gender", "Voice gender", "choice", "Auto", ("Auto", "Male", "Female", "Neutral")),
    _field("voice_name", "Exact installed voice name (optional)", "text", "", optional=True),
    _field("rate", "Speech rate (-10 to 10)", "int", 0),
    _field("volume", "Volume (0 to 100)", "int", 100),
    _field("subtitle", "Show Warcraft subtitle", "bool", True),
    _field("subtitle_seconds", "Subtitle seconds", "int", 5),
    _field("recipients", "Subtitle recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
    _field("color", "Subtitle color", "choice", "White — native highlight", PLAYER_CHAT_COLORS),
    _field("also_log", "Also log line", "bool", True),
    _field("wait", "Wait until speech ends", "bool", True),
)
ACTION_SCHEMAS["Scene Actor TTS"] = _SCENE_ACTOR + (
    _field("speaker", "Subtitle speaker label", "text", "", optional=True),
    _field("camera_cut", "Cut camera to actor", "bool", False),
) + _TTS_COMMON
ACTION_SCHEMAS["Scene Narrator TTS"] = (
    _field("speaker", "Speaker label", "text", "Narrator"),
) + _TTS_COMMON
ACTION_SCHEMAS["Scene Wait For TTS"] = ()
ACTION_SCHEMAS["Scene Wait For Local Key"] = (
    _field("key", "Local key", "choice", "Space", _LOCAL_SCENE_KEYS),
    _field("timeout", "Timeout seconds (0=no timeout)", "float", 0.0),
    _field("on_timeout", "On timeout", "choice", "Continue", ("Continue", "Error")),
    _field("set_variable", "Set variable on key (optional)", "text", "", optional=True),
    _field("value", "Variable value", "int", 1),
)
ACTION_SCHEMAS["Scene Choice"] = (
    _field("prompt", "Prompt", "multiline", "What should we do?"),
    _field("option1", "Option 1", "text", "Fight"),
    _field("option2", "Option 2", "text", "Retreat"),
    _field("option3", "Option 3 (optional)", "text", "", optional=True),
    _field("option4", "Option 4 (optional)", "text", "", optional=True),
    _field("variable", "Store selected option number in variable", "text", "Choice"),
    _field("timeout", "Timeout seconds (0=no timeout)", "float", 0.0),
    _field("default_choice", "Default option on timeout (0=none)", "int", 0),
    _field("on_timeout", "No valid default", "choice", "Continue", ("Continue", "Error")),
    _field("seconds", "Prompt display seconds", "int", 12),
    _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
    _field("color", "Prompt color", "choice", "White — native highlight", PLAYER_CHAT_COLORS),
    _field("also_log", "Also log prompt", "bool", True),
    _field("tts", "Read prompt/options with TTS", "bool", False),
    _field("gender", "TTS voice gender", "choice", "Auto", ("Auto", "Male", "Female", "Neutral")),
    _field("voice_name", "Exact installed voice name (optional)", "text", "", optional=True),
    _field("rate", "TTS rate (-10 to 10)", "int", 0),
    _field("volume", "TTS volume (0 to 100)", "int", 100),
)
ACTION_SCHEMAS["List TTS Voices"] = (
    _field("refresh", "Refresh installed voice list", "bool", True),
)
ACTION_SCHEMAS["Stop TTS"] = ()

KIND_HELP.update({
    "Native Win/Loss Suppressed": "Yes when the legacy-source CHEAT_NOVICTORY bit is active or the source-signature pre-map victory_update bridge is armed.",
    "Blank Map Guard Armed": "Checks whether the source-signature temporary pre-map victory_update RET bridge is active. Arm it before entering a completely empty map.",
    "Blank Map Bootstrap": "First action for a truly trigger-driven scenario. Sets source CHEAT_NOVICTORY (0x200), restores the temporary pre-map code bridge, and leaves explicit Victory/Defeat trigger actions working.",
    "Enable Trigger-Controlled Results": "Disables Warcraft's stock automatic victory/loss checks through the source CHEAT_NOVICTORY bit. Explicit Victory and Defeat actions still call the validated game_set_mode path.",
    "Disable Trigger-Controlled Results": "Restores Warcraft's automatic win/loss checks by clearing CHEAT_NOVICTORY and removing the 1.31 pre-map bridge if it is still present.",
    "Suppress Native Win/Loss": "Alias of Enable Trigger-Controlled Results for authored missions that want all victory/defeat logic in triggers.",
    "Restore Native Win/Loss": "Alias of Disable Trigger-Controlled Results.",
    "TTS Available": "Yes when Windows System.Speech exposes at least one installed SAPI voice. No cloud service or extra Python package is required.",
    "TTS Speaking": "Yes while a Trigger Studio local text-to-speech process is still speaking.",
    "Scene Actor TTS": "Makes a named scene actor speak authored text through an installed Windows voice. Auto/Male/Female/Neutral selection uses VoiceInfo.Gender; exact voice names can override it. Optional Warcraft subtitle and camera cut are included.",
    "Scene Narrator TTS": "Local Windows text-to-speech without requiring a scene actor. Useful for mission narration, briefings, commanders, and off-screen characters.",
    "Scene Wait For TTS": "Blocks the current scene sequence until all Trigger Studio TTS speech has finished.",
    "Scene Wait For Local Key": "Blocks a cutscene until the chosen local key is newly pressed. Useful for Space-to-continue dialogue, Escape-to-skip branches, and authored single-player choices. Optional variable output can feed later trigger branches.",
    "Scene Choice": "Displays 2-4 numbered choices and blocks until the local player presses 1-4. Stores the selected option number in a trigger variable for branching. Optional Windows TTS can read the prompt and choices aloud.",
    "List TTS Voices": "Writes every System.Speech voice name, gender, and culture visible on this Windows installation to the Trigger Console.",
    "Stop TTS": "Stops all speech processes started by Trigger Studio.",
    "Local Key Pressed": "Local-only edge condition using Windows keyboard state. Useful for Escape-to-skip cinematics, Space-to-continue dialogue, or numbered scene choices. Do not use as synchronized multiplayer game logic.",
    "Local Key Held": "Local-only held-key condition using Windows keyboard state. Intended for cutscene UI and local scenario controls, not synchronized multiplayer rules.",
})

# ---------------------------------------------------------------------------
# 1.32 Complete legacy mission-surface expansion.
# reference module / reference module / game_evt.c / reference module / reference module / reference module /
# reference module / reference module / reference module / reference module / reference module / unit.c.
MISSION132_CONDITIONS = [
    "Target Selection Active", "Target Tile Selected", "Target Unit Selected",
    "Target Is Building", "Target Too Far For Spell", "Target X", "Target Y",
    "Target Unit Type", "Target Unit Owner", "Placement Valid", "Player Placed Building",
    "Left Clicked Map", "Right Clicked Map", "Mouse Moved Over Tile", "Minimap Clicked", "Minimap Dragged",
    "Key Down", "Key Up", "Player Issued Command", "Button Clicked", "Command Available",
    "Can Train Unit", "Can Build Structure", "Can Research Spell", "Can Research Upgrade", "Prerequisites Met",
    "Auto Build Waiting", "Production Put On Hold", "Construction Progress Changed",
    "Animation Started", "Animation Finished", "Can Attack Target", "Can Hit Target", "Attack Connected",
    "Projectile Impacted Unit", "Projectile Impacted Terrain", "Projectile Missed", "Projectile Native Expired",
    "All Possible Building Upgrades Complete", "Campaign Map Visible", "Camera Zoom State",
]
MISSION132_ACTIONS = [
    "Configure Local Input Mapping", "Begin Target Selection", "Cancel Target Selection", "Wait For Target", "Store Selected Target", "Show Targeting Prompt",
    "Begin Building Placement", "Cancel Placement", "Wait For Placement",
    "Create Command Button", "Replace Button", "Remove Button", "Enable Button", "Disable Button", "Set Button Icon", "Set Tooltip", "Set Hotkey", "Button Starts Target Mode", "Show Custom Command Card",
    "Enable Auto Production", "Set Auto Build List", "Enable Auto Upgrade", "Pause Auto Build",
    "Pay Unit Cost", "Refund Unit Cost", "Pay Upgrade Cost", "Try Purchase",
    "Loop Animation", "Stop Animation At Frame", "Scene Wait For Animation", "Stop Animation Loop", "Play Death Sequence Only", "Play Attack Sequence Only", "Play Cast Sequence Only", "Unit Fidget/Idle Animation",
    "Deal Native Area Damage", "Native Splash Attack", "Damage Units Around Point",
    "Play Music", "Crossfade Music", "Loop Sound", "Stop Sound", "Set Music Volume", "Set SFX Volume", "Wait Until Sound Finished",
    "Set Mission Rank", "Set Bonus Score", "Set Mission Time", "Show Mission Results", "Show Victory Statistics",
    "Scene Camera Zoom In", "Scene Camera Zoom Out",
    "Show Campaign Map", "Add Campaign Dot", "Draw Campaign Route", "Pulse Campaign Location", "Hide Campaign Map",
    "Clear Current Game Message", "Cursor Set", "Cursor Hide", "Cursor Restore", "Show Native Cost/Mana Prompt",
    "Show Native Objectives", "Open Scenario Objectives", "Show Native Briefing", "Native Portrait Transmission", "Show Native Interlude", "Play Native FMV", "Save Native Campaign State", "Scene Native Fade In", "Scene Native Fade Out",
]
for _kind in MISSION132_CONDITIONS:
    if _kind not in CONDITIONS:
        CONDITIONS.append(_kind)
for _kind in MISSION132_ACTIONS:
    if _kind not in ACTIONS:
        ACTIONS.append(_kind)

CONDITION_CATEGORIES.update({
    "Interactive targeting & input 1.32": tuple(k for k in MISSION132_CONDITIONS if k in {
        "Target Selection Active","Target Tile Selected","Target Unit Selected","Target Is Building","Target Too Far For Spell","Target X","Target Y","Target Unit Type","Target Unit Owner","Left Clicked Map","Right Clicked Map","Mouse Moved Over Tile","Minimap Clicked","Minimap Dragged","Key Down","Key Up","Player Issued Command"}),
    "Placement, buttons & prerequisites 1.32": tuple(k for k in MISSION132_CONDITIONS if k in {
        "Placement Valid","Player Placed Building","Button Clicked","Command Available","Can Train Unit","Can Build Structure","Can Research Spell","Can Research Upgrade","Prerequisites Met","Auto Build Waiting","Production Put On Hold","All Possible Building Upgrades Complete"}),
    "Animation & exact-edge upgrades 1.32": tuple(k for k in MISSION132_CONDITIONS if k in {
        "Construction Progress Changed","Animation Started","Animation Finished","Can Attack Target","Can Hit Target","Attack Connected","Projectile Impacted Unit","Projectile Impacted Terrain","Projectile Missed","Projectile Native Expired"}),
    "Campaign presentation state 1.32": ("Campaign Map Visible","Camera Zoom State"),
})
ACTION_CATEGORIES.update({
    "Interactive targeting & placement 1.32": tuple(k for k in MISSION132_ACTIONS if k in {"Configure Local Input Mapping","Begin Target Selection","Cancel Target Selection","Wait For Target","Store Selected Target","Show Targeting Prompt","Begin Building Placement","Cancel Placement","Wait For Placement","Cursor Set","Cursor Hide","Cursor Restore"}),
    "Custom command buttons 1.32": tuple(k for k in MISSION132_ACTIONS if k in {"Create Command Button","Replace Button","Remove Button","Enable Button","Disable Button","Set Button Icon","Set Tooltip","Set Hotkey","Button Starts Target Mode","Show Custom Command Card"}),
    "Production, prerequisites & cost 1.32": tuple(k for k in MISSION132_ACTIONS if k in {"Enable Auto Production","Set Auto Build List","Enable Auto Upgrade","Pause Auto Build","Pay Unit Cost","Refund Unit Cost","Pay Upgrade Cost","Try Purchase","Show Native Cost/Mana Prompt"}),
    "Scene animation & combat 1.32": tuple(k for k in MISSION132_ACTIONS if k in {"Loop Animation","Stop Animation At Frame","Scene Wait For Animation","Stop Animation Loop","Play Death Sequence Only","Play Attack Sequence Only","Play Cast Sequence Only","Unit Fidget/Idle Animation","Deal Native Area Damage","Native Splash Attack","Damage Units Around Point"}),
    "Scene audio & mission results 1.32": tuple(k for k in MISSION132_ACTIONS if k in {"Play Music","Crossfade Music","Loop Sound","Stop Sound","Set Music Volume","Set SFX Volume","Wait Until Sound Finished","Set Mission Rank","Set Bonus Score","Set Mission Time","Show Mission Results","Show Victory Statistics"}),
    "Campaign map, zoom & native front-end 1.32": tuple(k for k in MISSION132_ACTIONS if k in {"Scene Camera Zoom In","Scene Camera Zoom Out","Show Campaign Map","Add Campaign Dot","Draw Campaign Route","Pulse Campaign Location","Hide Campaign Map","Clear Current Game Message","Show Native Objectives","Open Scenario Objectives","Show Native Briefing","Native Portrait Transmission","Show Native Interlude","Play Native FMV","Save Native Campaign State","Scene Native Fade In","Scene Native Fade Out"}),
})

_M132_YN = ("Yes", "No")
_M132_EVENT_COMMON = (
    _field("player", "Player (optional filter)", "player", -1, optional=True),
    _field("unit", "Unit type", "unit", "Any", optional=True),
    _field("location", "Location", "location", "Anywhere"),
) + COUNT_FIELDS
for _k in ("Left Clicked Map","Right Clicked Map","Mouse Moved Over Tile","Minimap Clicked","Minimap Dragged","Construction Progress Changed","Animation Started","Animation Finished","Attack Connected","Projectile Impacted Unit","Projectile Impacted Terrain","Projectile Missed","Projectile Native Expired"):
    CONDITION_SCHEMAS[_k] = _M132_EVENT_COMMON

for _k in ("Target Selection Active","Target Is Building","Placement Valid","Command Available","Can Train Unit","Can Build Structure","Can Research Spell","Can Research Upgrade","Prerequisites Met","Auto Build Waiting","Production Put On Hold","Can Attack Target","Can Hit Target","All Possible Building Upgrades Complete","Campaign Map Visible"):
    CONDITION_SCHEMAS[_k] = (_field("state", "Expected", "choice", "Yes", _M132_YN),)
CONDITION_SCHEMAS["Target Tile Selected"] = COUNT_FIELDS
CONDITION_SCHEMAS["Target Unit Selected"] = COUNT_FIELDS
for _k in ("Target X","Target Y","Target Unit Type","Target Unit Owner"):
    CONDITION_SCHEMAS[_k] = COUNT_FIELDS
CONDITION_SCHEMAS["Target Too Far For Spell"] = _SCENE_ACTOR + (_field("range", "Maximum tile range", "int", 8), _field("state", "Expected", "choice", "Yes", _M132_YN))
CONDITION_SCHEMAS["Player Placed Building"] = COUNT_FIELDS
CONDITION_SCHEMAS["Key Down"] = (_field("key", "Key", "choice", "Space", _LOCAL_SCENE_KEYS),) + COUNT_FIELDS
CONDITION_SCHEMAS["Key Up"] = CONDITION_SCHEMAS["Key Down"]
CONDITION_SCHEMAS["Player Issued Command"] = _M132_EVENT_COMMON
CONDITION_SCHEMAS["Button Clicked"] = (_field("button_id", "Button ID", "text", "Ability1"),) + COUNT_FIELDS
CONDITION_SCHEMAS["Command Available"] = (_field("button_id", "Button ID", "text", "Ability1"), _field("state", "Expected", "choice", "Yes", _M132_YN))
_PREREQ_FIELDS = (
    _field("player", "Player", "player", 0),
    _field("required_units", "Required unit counts (e.g. 58x1,62x2)", "text", "", optional=True),
)
CONDITION_SCHEMAS["Can Train Unit"] = _PREREQ_FIELDS + (_field("unit", "Unit", "mobile_unit", 0), _field("state", "Expected", "choice", "Yes", _M132_YN))
CONDITION_SCHEMAS["Can Build Structure"] = _PREREQ_FIELDS + (_field("building", "Building", "building_any", 58), _field("state", "Expected", "choice", "Yes", _M132_YN))
CONDITION_SCHEMAS["Can Research Spell"] = _PREREQ_FIELDS + (_field("spell", "Spell", "choice", "Blizzard", SPELL_NAMES), _field("state", "Expected", "choice", "Yes", _M132_YN))
CONDITION_SCHEMAS["Can Research Upgrade"] = _PREREQ_FIELDS + (_field("upgrade", "Upgrade", "choice", "Melee Attack", ULTIMATE_UPGRADES), _field("max_level", "Maximum level", "int", 2), _field("state", "Expected", "choice", "Yes", _M132_YN))
CONDITION_SCHEMAS["Prerequisites Met"] = _PREREQ_FIELDS + (_field("state", "Expected", "choice", "Yes", _M132_YN),)
CONDITION_SCHEMAS["Auto Build Waiting"] = (_field("actor", "Building actor/reference", "text", "Barracks"), _field("state", "Expected", "choice", "Yes", _M132_YN))
CONDITION_SCHEMAS["Production Put On Hold"] = CONDITION_SCHEMAS["Auto Build Waiting"]
CONDITION_SCHEMAS["Can Attack Target"] = (_field("actor", "Attacker actor", "text", "Archer"), _field("target_actor", "Target actor", "text", "Grunt"), _field("state", "Expected", "choice", "Yes", _M132_YN))
CONDITION_SCHEMAS["Can Hit Target"] = CONDITION_SCHEMAS["Can Attack Target"]
CONDITION_SCHEMAS["All Possible Building Upgrades Complete"] = (
    _field("player", "Player", "player", 0), _field("upgrade_rows", "Upgrade rows (blank=all known)", "text", "", optional=True), _field("max_level", "Required level", "int", 2), _field("state", "Expected", "choice", "Yes", _M132_YN),
)
CONDITION_SCHEMAS["Campaign Map Visible"] = (_field("state", "Expected", "choice", "Yes", _M132_YN),)
CONDITION_SCHEMAS["Camera Zoom State"] = COUNT_FIELDS

ACTION_SCHEMAS["Configure Local Input Mapping"] = (
    _field("viewport_left", "Viewport left pixels", "float", 0.0), _field("viewport_top", "Viewport top pixels", "float", 0.0),
    _field("pixel_scale_x", "Rendered X scale vs 32px tile", "float", 1.0), _field("pixel_scale_y", "Rendered Y scale vs 32px tile", "float", 1.0),
    _field("minimap_left", "Minimap left (-1 disables)", "float", -1.0), _field("minimap_top", "Minimap top", "float", -1.0), _field("minimap_right", "Minimap right", "float", -1.0), _field("minimap_bottom", "Minimap bottom", "float", -1.0),
)
ACTION_SCHEMAS["Begin Target Selection"] = (
    _field("prompt", "Targeting prompt", "text", "Select a target"), _field("target_kind", "Target kind", "choice", "Any", ("Any","Tile","Unit","Building")),
    _field("show_prompt", "Show prompt", "bool", True), _field("seconds", "Prompt seconds", "int", 5), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS), _field("color", "Color", "choice", "White — native highlight", PLAYER_CHAT_COLORS),
)
ACTION_SCHEMAS["Cancel Target Selection"] = ()
ACTION_SCHEMAS["Wait For Target"] = (_field("timeout", "Timeout seconds (0=no timeout)", "float", 0.0), _field("on_timeout", "On timeout", "choice", "Continue", ("Continue","Error")), _field("close_mode", "End target mode after selection", "bool", True))
ACTION_SCHEMAS["Store Selected Target"] = (_field("x_variable", "X variable", "text", "TargetX"), _field("y_variable", "Y variable", "text", "TargetY"), _field("unit_reference", "Save target unit reference (optional)", "text", "", optional=True))
ACTION_SCHEMAS["Show Targeting Prompt"] = (_field("text", "Prompt", "text", "Select a target"), _field("seconds", "Seconds", "int", 5), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS), _field("color", "Color", "choice", "White — native highlight", PLAYER_CHAT_COLORS), _field("also_log", "Also log", "bool", False))
ACTION_SCHEMAS["Begin Building Placement"] = (
    _field("player", "Owner", "player", 0), _field("building", "Building", "building_any", 58), _field("complete", "Complete immediately after placement", "bool", False), _field("prompt", "Prompt", "text", "Choose a building location"), _field("show_prompt", "Show prompt", "bool", True),
)
ACTION_SCHEMAS["Cancel Placement"] = ()
ACTION_SCHEMAS["Wait For Placement"] = (_field("timeout", "Timeout seconds (0=no timeout)", "float", 0.0), _field("on_timeout", "On timeout", "choice", "Continue", ("Continue","Error")))

_BUTTON_BASE = (
    _field("button_id", "Button ID", "text", "Ability1"), _field("label", "Label", "text", "Special Ability"), _field("icon", "Icon/asset label", "text", "", optional=True), _field("tooltip", "Tooltip", "multiline", ""), _field("hotkey", "Hotkey", "choice", "A", _LOCAL_SCENE_KEYS), _field("enabled", "Enabled", "bool", True), _field("target_mode", "Starts target mode", "bool", False), _field("prompt", "Target prompt", "text", "Select a target"),
)
ACTION_SCHEMAS["Create Command Button"] = _BUTTON_BASE
ACTION_SCHEMAS["Replace Button"] = _BUTTON_BASE
for _k in ("Remove Button","Enable Button","Disable Button"):
    ACTION_SCHEMAS[_k] = (_field("button_id", "Button ID", "text", "Ability1"),)
ACTION_SCHEMAS["Set Button Icon"] = (_field("button_id", "Button ID", "text", "Ability1"), _field("icon", "Icon/asset label", "text", ""))
ACTION_SCHEMAS["Set Tooltip"] = (_field("button_id", "Button ID", "text", "Ability1"), _field("tooltip", "Tooltip", "multiline", ""))
ACTION_SCHEMAS["Set Hotkey"] = (_field("button_id", "Button ID", "text", "Ability1"), _field("hotkey", "Hotkey", "choice", "A", _LOCAL_SCENE_KEYS))
ACTION_SCHEMAS["Button Starts Target Mode"] = (_field("button_id", "Button ID", "text", "Ability1"), _field("prompt", "Prompt", "text", "Select a target"), _field("target_kind", "Target kind", "choice", "Any", ("Any","Tile","Unit","Building")))
ACTION_SCHEMAS["Show Custom Command Card"] = (_field("title", "Title", "text", "CUSTOM COMMANDS"), _field("seconds", "Seconds", "int", 8), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS), _field("color", "Color", "choice", "White — native highlight", PLAYER_CHAT_COLORS))

_AUTO_BASE = (_field("actor", "Building actor/reference", "text", "Barracks"), _field("items", "Comma-separated unit/upgrade IDs", "text", "0,1"), _field("enabled", "Enabled", "bool", True), _field("loop", "Loop list", "bool", True))
ACTION_SCHEMAS["Enable Auto Production"] = _AUTO_BASE
ACTION_SCHEMAS["Set Auto Build List"] = (_field("actor", "Building actor/reference", "text", "Barracks"), _field("items", "Comma-separated unit IDs", "text", "0,1"))
ACTION_SCHEMAS["Enable Auto Upgrade"] = (_field("actor", "Building actor/reference", "text", "Blacksmith"), _field("items", "Upgrade IDs/names", "text", "0,1"), _field("enabled", "Enabled", "bool", True), _field("loop", "Loop list", "bool", False))
ACTION_SCHEMAS["Pause Auto Build"] = (_field("actor", "Building actor/reference", "text", "Barracks"), _field("paused", "Paused", "bool", True))

_UNIT_COST = (_field("player", "Player", "player", 0), _field("unit", "Unit/object", "unit", 0), _field("fraction", "Cost/refund fraction", "float", 1.0))
ACTION_SCHEMAS["Pay Unit Cost"] = _UNIT_COST
ACTION_SCHEMAS["Refund Unit Cost"] = _UNIT_COST
ACTION_SCHEMAS["Try Purchase"] = _UNIT_COST + (_field("result_variable", "Result variable (1=paid, 0=insufficient)", "text", "PurchaseOK"),)
ACTION_SCHEMAS["Pay Upgrade Cost"] = (_field("player", "Player", "player", 0), _field("upgrade", "Upgrade", "choice", "Melee Attack", ULTIMATE_UPGRADES), _field("gold", "Gold override (0=rule cost)", "int", 0), _field("lumber", "Lumber", "int", 0), _field("oil", "Oil", "int", 0))

_ANIM_BASE = _SCENE_ACTOR + (_field("animation", "Animation/sequence byte", "int", 0), _field("frame", "Frame", "int", 0), _field("timer", "Animation timer", "int", 1))
ACTION_SCHEMAS["Loop Animation"] = _ANIM_BASE
ACTION_SCHEMAS["Stop Animation At Frame"] = _ANIM_BASE
ACTION_SCHEMAS["Scene Wait For Animation"] = _SCENE_ACTOR + (_field("animation", "Animation (-1=any)", "int", -1), _field("timeout", "Timeout seconds", "float", 0.0), _field("on_timeout", "On timeout", "choice", "Continue", ("Continue","Error")))
ACTION_SCHEMAS["Stop Animation Loop"] = _SCENE_ACTOR
ACTION_SCHEMAS["Play Death Sequence Only"] = _SCENE_ACTOR + (_field("animation", "Sequence (legacy USEQ_DIE=1)", "int", 1), _field("frame", "Frame", "int", 0), _field("timer", "Animation timer", "int", 1))
ACTION_SCHEMAS["Play Attack Sequence Only"] = _SCENE_ACTOR + (_field("animation", "Sequence (legacy USEQ_ATTACK=4)", "int", 4), _field("frame", "Frame", "int", 0), _field("timer", "Animation timer", "int", 1))
ACTION_SCHEMAS["Play Cast Sequence Only"] = _SCENE_ACTOR + (_field("animation", "Sequence (spells map to USEQ_ATTACK=4)", "int", 4), _field("frame", "Frame", "int", 0), _field("timer", "Animation timer", "int", 1))
ACTION_SCHEMAS["Unit Fidget/Idle Animation"] = _SCENE_ACTOR + (_field("animation", "Sequence (legacy USEQ_STOP=2)", "int", 2), _field("frame", "Frame", "int", 0), _field("timer", "Animation timer", "int", 1))

_AREA_COMMON = (_field("actor", "Attacker actor/reference (optional)", "text", "", optional=True), _field("location", "Center location", "location", "Anywhere"), _field("x", "Tile X", "int", 0), _field("y", "Tile Y", "int", 0), _field("x_variable", "X variable override", "text", "", optional=True), _field("y_variable", "Y variable override", "text", "", optional=True), _field("radius", "Radius tiles", "int", 2), _field("damage", "Damage (0=native attacker roll)", "int", 0), _field("friendly_fire", "Friendly fire", "bool", False))
ACTION_SCHEMAS["Deal Native Area Damage"] = _AREA_COMMON
ACTION_SCHEMAS["Damage Units Around Point"] = _AREA_COMMON
ACTION_SCHEMAS["Native Splash Attack"] = _SCENE_ACTOR + (_field("radius", "Radius tiles", "int", 2), _field("damage", "Damage (0=native attacker roll)", "int", 0), _field("friendly_fire", "Friendly fire", "bool", False))

ACTION_SCHEMAS["Play Music"] = (_field("track", "Track/file/asset name", "text", ""), _field("volume", "Volume 0-100", "int", 100))
ACTION_SCHEMAS["Crossfade Music"] = (_field("track", "New track/file/asset", "text", ""), _field("to_volume", "Target volume", "int", 100), _field("seconds", "Fade seconds", "float", 1.0))
ACTION_SCHEMAS["Loop Sound"] = (_field("file", "Sound file/asset (optional)", "text", "", optional=True), _field("actor", "Actor voice fallback", "text", "", optional=True), _field("event", "Voice event", "choice", "Selection", ("Selection","Under Attack","Harvest","Unit Death","Building Destruction","Spell Sound")), _field("estimated_seconds", "Estimated seconds", "float", 1.5))
ACTION_SCHEMAS["Stop Sound"] = ()
ACTION_SCHEMAS["Set Music Volume"] = (_field("volume", "Volume 0-100", "int", 100),)
ACTION_SCHEMAS["Set SFX Volume"] = (_field("volume", "Volume 0-100", "int", 100),)
ACTION_SCHEMAS["Wait Until Sound Finished"] = (_field("seconds", "Minimum seconds", "float", 0.0),)

ACTION_SCHEMAS["Set Mission Rank"] = (_field("rank", "Rank/title", "text", "Commander"),)
ACTION_SCHEMAS["Set Bonus Score"] = (_field("score", "Bonus score", "int", 0),)
ACTION_SCHEMAS["Set Mission Time"] = (_field("seconds", "Mission time seconds", "float", 0.0),)
_RESULTS = (_field("title", "Title", "text", "MISSION RESULTS"), _field("rank", "Fallback rank", "text", "Commander"), _field("seconds", "Display seconds", "int", 10), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS), _field("color", "Color", "choice", "Yellow / gold — native normal", PLAYER_CHAT_COLORS), _field("victory", "Also issue Victory", "bool", False))
ACTION_SCHEMAS["Show Mission Results"] = _RESULTS
ACTION_SCHEMAS["Show Victory Statistics"] = _RESULTS

_ZOOM = (_field("step", "Zoom step", "float", 0.10), _field("fallback_to_state_only", "Use authored zoom state when native renderer ABI is unverified", "bool", True))
ACTION_SCHEMAS["Scene Camera Zoom In"] = _ZOOM
ACTION_SCHEMAS["Scene Camera Zoom Out"] = _ZOOM
ACTION_SCHEMAS["Show Campaign Map"] = (_field("title", "Map title", "text", "CAMPAIGN MAP"), _field("seconds", "Display seconds", "int", 5), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS), _field("color", "Color", "choice", "White — native highlight", PLAYER_CHAT_COLORS))
_CAM_POINT = (_field("location", "Location", "location", "Anywhere"), _field("x", "Tile X", "int", 0), _field("y", "Tile Y", "int", 0), _field("x_variable", "X variable override", "text", "", optional=True), _field("y_variable", "Y variable override", "text", "", optional=True))
ACTION_SCHEMAS["Add Campaign Dot"] = _CAM_POINT + (_field("label", "Label", "text", "Objective"), _field("duration", "Marker seconds (0=until hidden)", "float", 0.0))
ACTION_SCHEMAS["Draw Campaign Route"] = (_field("locations", "Comma-separated location names", "text", "Start,Middle,End"), _field("duration", "Marker seconds", "float", 0.0))
ACTION_SCHEMAS["Pulse Campaign Location"] = _CAM_POINT + (_field("pulses", "Pulses", "int", 3), _field("interval", "Pulse interval", "float", 0.5))
ACTION_SCHEMAS["Hide Campaign Map"] = ()
ACTION_SCHEMAS["Clear Current Game Message"] = (_field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),)
ACTION_SCHEMAS["Cursor Set"] = (_field("cursor", "Cursor label", "text", "Target"),)
ACTION_SCHEMAS["Cursor Hide"] = ()
ACTION_SCHEMAS["Cursor Restore"] = ()
ACTION_SCHEMAS["Show Native Cost/Mana Prompt"] = (_field("unit", "Unit/object", "unit", 0), _field("mana", "Mana cost", "int", 0), _field("prefix", "Prefix", "text", "Cost"), _field("seconds", "Seconds", "int", 4), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS), _field("color", "Color", "choice", "White — native highlight", PLAYER_CHAT_COLORS))

# Friendly native-front-end aliases retain 1.30's explicit fallback/fail-closed knobs.
ACTION_SCHEMAS["Show Native Objectives"] = ACTION_SCHEMAS.get("Show Native Objectives HUD (Experimental)", ())
ACTION_SCHEMAS["Open Scenario Objectives"] = ACTION_SCHEMAS.get("Open Native Scenario Objectives (Experimental)", ())
ACTION_SCHEMAS["Show Native Briefing"] = ACTION_SCHEMAS.get("Show Native Mission Briefing (Experimental)", ())
ACTION_SCHEMAS["Native Portrait Transmission"] = ACTION_SCHEMAS.get("Native Portrait Transmission (Experimental)", ())
ACTION_SCHEMAS["Show Native Interlude"] = ACTION_SCHEMAS.get("Native Campaign Interlude (Experimental)", ())
ACTION_SCHEMAS["Play Native FMV"] = ACTION_SCHEMAS.get("Play Cinematic Movie (Experimental)", ())
ACTION_SCHEMAS["Save Native Campaign State"] = ACTION_SCHEMAS.get("Native Save Extension (Experimental)", ())
ACTION_SCHEMAS["Scene Native Fade In"] = ACTION_SCHEMAS.get("Scene Fade In (Experimental)", ())
ACTION_SCHEMAS["Scene Native Fade Out"] = ACTION_SCHEMAS.get("Scene Fade Out (Experimental)", ())

KIND_HELP.update({
    "Begin Target Selection": "reference module-shaped local target mode. 1.32 captures a local Windows click and converts it to a Warcraft tile using the current camera plus author-configurable viewport scale/margins. It is intentionally local single-player input, not a guessed Remastered reference module callback.",
    "Begin Building Placement": "reference module-shaped interactive placement. The click is preview-validated when possible, then native unit_create/mtx_place_bldg remains the final authority when Wait For Placement creates the foundation.",
    "Create Command Button": "Creates a trigger-owned custom command descriptor with label/icon/tooltip/hotkey. Hotkey clicks work now; direct mutation of Remastered's modern command-card C++ objects remains a separate ABI research item.",
    "Button Clicked": "Local edge on a custom command button's hotkey. Useful for custom abilities and scene interaction without pretending an unverified Remastered statbtn callback is hooked.",
    "Can Train Unit": "Source-shaped production availability helper combining affordability, type range and optional authored prerequisite counts.",
    "Can Build Structure": "Source-shaped building availability helper combining affordability, building range and optional authored prerequisite counts.",
    "Can Research Spell": "Checks native research bits plus optional authored prerequisites.",
    "Can Research Upgrade": "Checks live upgrade level, affordability rule state and optional authored prerequisites.",
    "Enable Auto Production": "Trigger-owned equivalent of legacy bldg_auto_build, driven by the verified Remastered bldg_build_start path rather than legacy-only UI globals.",
    "Enable Auto Upgrade": "Trigger-owned equivalent of legacy bldg_auto_upgrade using verified Remastered production state.",
    "Pay Unit Cost": "Atomic Gold/Lumber/Oil deduction using the source cost-table contract; fails before writing if the player cannot afford the full transaction.",
    "Refund Unit Cost": "Atomic source-shaped resource refund. Fraction allows 0.75-style cancellation refunds without mismatched partial writes.",
    "Scene Wait For Animation": "Blocks until the actor's native animation timer reaches zero after the requested sequence was observed.",
    "Attack Connected": "Best-evidence attack edge: an attacker retained a target and that target's native HP decreased during the same snapshot interval. It is labeled as an inferred callback until reference module's exact Remastered impact path is hooked.",
    "Projectile Impacted Unit": "Improved projectile-end classifier using stored target, proximity and disappearance. Safer than treating every disappearance as a hit, but still explicitly inferred until the exact reference module impact callback is mapped.",
    "Play Music": "Friendly alias for the existing state-backed/fail-closed Remastered music layer. It does not jump to legacy reference module addresses.",
    "Scene Camera Zoom In": "Authors gamemap_shrink/expand-style zoom state. Native Remastered renderer zoom remains fail-closed until the exact camera-scale ABI is verified.",
    "Show Campaign Map": "Safe campaign-map interlude authoring surface. Uses in-game presentation/minimap markers now; genuine Remastered interlude object model remains experimental.",
    "Show Native Objectives": "Stages the trigger objective override when active, then enters Warcraft's real in-game Menu -> Objectives submenu. 1.38 hooks the native renderer provider/destructor call sites with an allocator-free view instead of calling the old pre-mission/modal renderer or transferring heap ownership.",
    "Open Scenario Objectives": "Opens Warcraft's actual in-game Menu -> Objectives submenu (native pause-menu state 2). If trigger objectives are active they replace the map/campaign objective lines; otherwise Warcraft renders the map/campaign objectives unchanged.",
    "Native Portrait Transmission": "Friendly alias of the experimental portrait transmission bridge; falls back to validated Scene Transmission until Remastered portrait-queue ABI ownership is proven.",
    "Play Native FMV": "Friendly alias of the fail-closed cinematic movie bridge. No guessed movie-player function is invoked.",
    "All Possible Building Upgrades Complete": "Source-inspired convenience condition over selected live upgrade rows/levels. Use upgrade_rows to narrow it to upgrades relevant to a specific building.",
    "Configure Local Input Mapping": "Calibrates local mouse-to-world conversion for target/placement input. This exists because Remastered can scale the 32px Warcraft viewport independently of the Windows client size.",
})

# ---------------------------------------------------------------------------
# 1.39 legacy completion surface.  These names expose every remaining useful
# mission-author-facing source concept identified by the legacy audits.  Exact
# Remastered callbacks that are not proven stay best-evidence/state-backed or
# fail-closed; the editor help says which boundary applies.
MISSION139_CONDITIONS = [
    "Player Issued Native Order", "Native Command Button Clicked",
    "Attack Hit", "Attack Missed", "Projectile Impact",
    "Production Cancelled", "Training Cancelled", "Research Cancelled",
    "Upgrade Started", "Upgrade Cancelled", "Production Resumed", "Production Paused Event",
    "Worker Entered Gold Mine", "Worker Exited Gold Mine", "Tanker Entered Oil Patch", "Tanker Exited Oil Patch",
    "Resource Harvested", "Resource Node Depleted",
    "Spell Cast Started", "Spell Cast Finished", "Spell Cast Interrupted",
    "Unit Entered Player Vision", "Unit Left Player Vision", "Unit Entered Attack Range", "Unit Left Attack Range",
    "Briefing Active", "Briefing Scrolling", "Briefing Finished",
    "Objectives Screen Is Open", "Objectives Screen Opened", "Objectives Screen Closed",
    "Transmission Active", "Transmission Started", "Transmission Finished",
    "Slideshow Active", "Slideshow Finished", "Campaign Map Finished",
    "FMV Active", "FMV Finished", "Finale Active", "Finale Finished",
    "Fade Active", "Fade Percent", "Fade Finished",
    "Music Playing", "Music Finished",
    "Results Screen Is Open", "Results Screen Opened", "Results Screen Closed",
    "Hard Cutscene Input Lock Active",
    "Before Native Save", "After Native Save", "After Native Load",
    "Native Camera Zoom State", "Campaign Map Scale", "Campaign Map Screen X", "Campaign Map Screen Y", "Game Paused Event", "Game Resumed Event",
    "Diplomacy Changed", "Shared Vision Changed", "AI Build Goal Met",
]
MISSION139_ACTIONS = [
    "Set Briefing Text Area", "Set Briefing Image", "Activate Briefing", "Start Scrolling Briefing", "Stop Scrolling Briefing", "Deactivate Briefing",
    "Append Trigger Objective", "Replace Trigger Objective List", "Open Objectives Screen", "Close Objectives Screen",
    "Set Transmission Portrait", "Clear Transmission Portrait", "Start Portrait Transmission", "Stop Portrait Transmission",
    "Start Campaign Slideshow", "Show Slideshow Frame", "Next Slideshow Frame", "Stop Campaign Slideshow",
    "Start Native Campaign Map", "Add Native Campaign Dot", "Draw Native Campaign Route Segment", "Set Campaign Map Scale", "Set Campaign Map Position", "Stop Native Campaign Map",
    "Play FMV", "Stop FMV", "Start Finale", "Show Scrolling Finale Text", "Stop Finale",
    "Fade Screen In", "Fade Screen Out", "Fade Screen To Black", "Set Screen Fade Percent",
    "Play Native Campaign Music", "Fade Native Music", "Stop Native Music", "Set Native Music Volume",
    "Open Mission Results", "Open Victory Statistics", "Close Mission Results",
    "Lock Gameplay Input", "Unlock Gameplay Input",
    "Mark Before Native Save", "Mark After Native Save", "Mark After Native Load",
    "Native Camera Shrink", "Native Camera Expand", "Clear legacy Event History",
]
for _kind in MISSION139_CONDITIONS:
    if _kind not in CONDITIONS:
        CONDITIONS.append(_kind)
for _kind in MISSION139_ACTIONS:
    if _kind not in ACTIONS:
        ACTIONS.append(_kind)

CONDITION_CATEGORIES.update({
    "Exact-edge / best-evidence events 1.39": tuple(k for k in MISSION139_CONDITIONS if k in {
        "Player Issued Native Order","Native Command Button Clicked","Attack Hit","Attack Missed","Projectile Impact",
        "Production Cancelled","Training Cancelled","Research Cancelled","Upgrade Started","Upgrade Cancelled","Production Resumed","Production Paused Event",
        "Resource Harvested","Resource Node Depleted","Spell Cast Started","Spell Cast Finished","Spell Cast Interrupted",
        "Game Paused Event","Game Resumed Event","Diplomacy Changed","Shared Vision Changed","AI Build Goal Met"}),
    "Resource / vision / range events 1.39": tuple(k for k in MISSION139_CONDITIONS if k in {
        "Worker Entered Gold Mine","Worker Exited Gold Mine","Tanker Entered Oil Patch","Tanker Exited Oil Patch",
        "Unit Entered Player Vision","Unit Left Player Vision","Unit Entered Attack Range","Unit Left Attack Range"}),
    "legacy briefing / objectives / transmission 1.39": tuple(k for k in MISSION139_CONDITIONS if k in {
        "Briefing Active","Briefing Scrolling","Briefing Finished","Objectives Screen Is Open","Objectives Screen Opened","Objectives Screen Closed",
        "Transmission Active","Transmission Started","Transmission Finished"}),
    "legacy slideshow / finale / media 1.39": tuple(k for k in MISSION139_CONDITIONS if k in {
        "Slideshow Active","Slideshow Finished","Campaign Map Finished","FMV Active","FMV Finished","Finale Active","Finale Finished",
        "Fade Active","Fade Percent","Fade Finished","Music Playing","Music Finished","Results Screen Is Open","Results Screen Opened","Results Screen Closed"}),
    "legacy input / save / camera 1.39": tuple(k for k in MISSION139_CONDITIONS if k in {
        "Hard Cutscene Input Lock Active","Before Native Save","After Native Save","After Native Load","Native Camera Zoom State","Campaign Map Scale","Campaign Map Screen X","Campaign Map Screen Y"}),
})
ACTION_CATEGORIES.update({
    "legacy briefing / objectives 1.39": tuple(k for k in MISSION139_ACTIONS if k in {
        "Set Briefing Text Area","Set Briefing Image","Activate Briefing","Start Scrolling Briefing","Stop Scrolling Briefing","Deactivate Briefing",
        "Append Trigger Objective","Replace Trigger Objective List","Open Objectives Screen","Close Objectives Screen"}),
    "legacy portrait / slideshow / campaign map 1.39": tuple(k for k in MISSION139_ACTIONS if k in {
        "Set Transmission Portrait","Clear Transmission Portrait","Start Portrait Transmission","Stop Portrait Transmission",
        "Start Campaign Slideshow","Show Slideshow Frame","Next Slideshow Frame","Stop Campaign Slideshow",
        "Start Native Campaign Map","Add Native Campaign Dot","Draw Native Campaign Route Segment","Set Campaign Map Scale","Set Campaign Map Position","Stop Native Campaign Map"}),
    "legacy finale / FMV / fade / music 1.39": tuple(k for k in MISSION139_ACTIONS if k in {
        "Play FMV","Stop FMV","Start Finale","Show Scrolling Finale Text","Stop Finale",
        "Fade Screen In","Fade Screen Out","Fade Screen To Black","Set Screen Fade Percent",
        "Play Native Campaign Music","Fade Native Music","Stop Native Music","Set Native Music Volume"}),
    "legacy results / input / save / camera 1.39": tuple(k for k in MISSION139_ACTIONS if k in {
        "Open Mission Results","Open Victory Statistics","Close Mission Results","Lock Gameplay Input","Unlock Gameplay Input",
        "Mark Before Native Save","Mark After Native Save","Mark After Native Load","Native Camera Shrink","Native Camera Expand","Clear legacy Event History"}),
})

_M139_YN = ("Yes", "No")
_M139_EVENT = (
    _field("player", "Player filter (-1 = any)", "player", -1, optional=True),
    _field("unit", "Unit type", "unit", "Any", optional=True),
    _field("location", "Location", "location", "Anywhere"),
) + COUNT_FIELDS
for _k in (
    "Player Issued Native Order","Native Command Button Clicked","Attack Hit","Attack Missed","Production Cancelled","Training Cancelled","Research Cancelled",
    "Upgrade Started","Upgrade Cancelled","Production Resumed","Production Paused Event","Worker Entered Gold Mine","Worker Exited Gold Mine","Tanker Entered Oil Patch","Tanker Exited Oil Patch",
    "Resource Harvested","Resource Node Depleted","Spell Cast Started","Spell Cast Finished","Spell Cast Interrupted","Unit Entered Player Vision","Unit Left Player Vision",
    "Unit Entered Attack Range","Unit Left Attack Range","Briefing Finished","Objectives Screen Opened","Objectives Screen Closed","Transmission Started","Transmission Finished",
    "Slideshow Finished","Campaign Map Finished","FMV Finished","Finale Finished","Fade Finished","Music Finished","Results Screen Opened","Results Screen Closed",
    "Before Native Save","After Native Save","After Native Load","Game Paused Event","Game Resumed Event","AI Build Goal Met",
):
    CONDITION_SCHEMAS[_k] = _M139_EVENT
CONDITION_SCHEMAS["Projectile Impact"] = _M139_EVENT + (_field("impact_kind", "Impact kind", "choice", "Any", ("Any","Unit","Terrain"), optional=True),)
CONDITION_SCHEMAS["Diplomacy Changed"] = (
    _field("source_player", "Source player (-1 = any)", "int", -1, optional=True),
    _field("target_player", "Target player (-1 = any)", "int", -1, optional=True),
    _field("new_relation", "New relation (-1 = any; 0 Enemy / 1 Allied)", "int", -1, optional=True),
) + COUNT_FIELDS
CONDITION_SCHEMAS["Shared Vision Changed"] = (_field("source_player", "Source player (-1 = any)", "int", -1, optional=True),) + COUNT_FIELDS
for _k in ("Briefing Active","Briefing Scrolling","Objectives Screen Is Open","Transmission Active","Slideshow Active","FMV Active","Finale Active","Fade Active","Music Playing","Results Screen Is Open","Hard Cutscene Input Lock Active"):
    CONDITION_SCHEMAS[_k] = (_field("state", "Expected", "choice", "Yes", _M139_YN),)
CONDITION_SCHEMAS["Fade Percent"] = (_field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Percent", "int", 100))
CONDITION_SCHEMAS["Native Camera Zoom State"] = (_field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Zoom value", "float", 1.0))
CONDITION_SCHEMAS["Campaign Map Scale"] = (_field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Scale", "float", 1.0))
CONDITION_SCHEMAS["Campaign Map Screen X"] = (_field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Screen X", "int", 0))
CONDITION_SCHEMAS["Campaign Map Screen Y"] = (_field("comparison", "Comparison", "choice", "At least", COMPARISONS), _field("amount", "Screen Y", "int", 0))

ACTION_SCHEMAS["Set Briefing Text Area"] = (
    _field("left", "Left", "int", 0), _field("top", "Top", "int", 0), _field("right", "Right", "int", 640), _field("bottom", "Bottom", "int", 480),
)
ACTION_SCHEMAS["Set Briefing Image"] = (_field("image", "Image/asset name", "text", ""),)
_BRIEFING139 = (
    _field("text", "Briefing text", "multiline", "Mission briefing"), _field("seconds", "Auto-finish seconds (0 = manual)", "float", 0.0),
    _field("message_seconds", "Safe in-game display seconds", "int", 6), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
    _field("color", "Text color", "choice", "White — native highlight", PLAYER_CHAT_COLORS),
)
ACTION_SCHEMAS["Activate Briefing"] = _BRIEFING139 + (_field("scrolling", "Scrolling state", "bool", False),)
ACTION_SCHEMAS["Start Scrolling Briefing"] = _BRIEFING139
ACTION_SCHEMAS["Stop Scrolling Briefing"] = ()
ACTION_SCHEMAS["Deactivate Briefing"] = ()
ACTION_SCHEMAS["Append Trigger Objective"] = ACTION_SCHEMAS.get("Set Campaign Objective", ())
ACTION_SCHEMAS["Replace Trigger Objective List"] = (_field("objectives", "Objectives (one per line)", "multiline", "Destroy all enemy forces\nKeep the hero alive"),)
ACTION_SCHEMAS["Open Objectives Screen"] = ACTION_SCHEMAS.get("Open Scenario Objectives", ())
ACTION_SCHEMAS["Close Objectives Screen"] = ()
ACTION_SCHEMAS["Set Transmission Portrait"] = (_field("portrait", "Portrait/actor label", "text", "Commander"),)
ACTION_SCHEMAS["Clear Transmission Portrait"] = ()
ACTION_SCHEMAS["Start Portrait Transmission"] = (
    _field("actor", "Actor / portrait source", "text", "", optional=True), _field("text", "Transmission text", "multiline", "Commander, the enemy approaches."),
    _field("seconds", "Duration seconds", "float", 4.0), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS),
)
ACTION_SCHEMAS["Stop Portrait Transmission"] = ()
ACTION_SCHEMAS["Start Campaign Slideshow"] = (_field("title", "Slideshow title", "text", "ACT I"), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS))
_SLIDE139 = (_field("index", "Frame index", "int", 0), _field("text", "Frame text", "multiline", ""), _field("seconds", "Auto-finish seconds", "float", 0.0), _field("message_seconds", "Display seconds", "int", 4), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS), _field("color", "Color", "choice", "White — native highlight", PLAYER_CHAT_COLORS))
ACTION_SCHEMAS["Show Slideshow Frame"] = _SLIDE139
ACTION_SCHEMAS["Next Slideshow Frame"] = _SLIDE139
ACTION_SCHEMAS["Stop Campaign Slideshow"] = ()
ACTION_SCHEMAS["Start Native Campaign Map"] = ACTION_SCHEMAS.get("Show Campaign Map", ())
ACTION_SCHEMAS["Add Native Campaign Dot"] = ACTION_SCHEMAS.get("Add Campaign Dot", ())
ACTION_SCHEMAS["Draw Native Campaign Route Segment"] = ACTION_SCHEMAS.get("Draw Campaign Route", ())
ACTION_SCHEMAS["Set Campaign Map Scale"] = (_field("scale", "Campaign map scale", "float", 1.0),)
ACTION_SCHEMAS["Set Campaign Map Position"] = (_field("x", "Screen X", "int", 0), _field("y", "Screen Y", "int", 0))
ACTION_SCHEMAS["Stop Native Campaign Map"] = ()
ACTION_SCHEMAS["Play FMV"] = (_field("movie", "Movie/asset name", "text", ""), _field("seconds", "Fallback duration", "float", 5.0), _field("fallback_text", "Fallback text", "multiline", "", optional=True), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS), _field("require_native", "Require verified native movie player (fail closed)", "bool", False))
ACTION_SCHEMAS["Stop FMV"] = ()
ACTION_SCHEMAS["Start Finale"] = (_field("text", "Finale text", "multiline", "VICTORY"), _field("seconds", "Auto-finish seconds (0=manual)", "float", 0.0), _field("message_seconds", "Display seconds", "int", 6), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS))
ACTION_SCHEMAS["Show Scrolling Finale Text"] = (_field("text", "Scrolling text", "multiline", "The End"), _field("seconds", "Display seconds", "int", 6), _field("recipients", "Recipients", "choice", "All active players", GAME_MESSAGE_RECIPIENTS), _field("color", "Color", "choice", "White — native highlight", PLAYER_CHAT_COLORS))
ACTION_SCHEMAS["Stop Finale"] = ()
_FADE139 = (_field("seconds", "Fade seconds", "float", 0.75),)
ACTION_SCHEMAS["Fade Screen In"] = _FADE139
ACTION_SCHEMAS["Fade Screen Out"] = _FADE139
ACTION_SCHEMAS["Fade Screen To Black"] = _FADE139
ACTION_SCHEMAS["Set Screen Fade Percent"] = (_field("percent", "Black overlay percent", "int", 100),)
ACTION_SCHEMAS["Play Native Campaign Music"] = (_field("track", "Track/asset", "text", ""), _field("volume", "Volume 0-100", "int", 100), _field("estimated_seconds", "Estimated length (0=unknown)", "float", 0.0), _field("require_native", "Require verified native stream (fail closed)", "bool", False))
ACTION_SCHEMAS["Fade Native Music"] = (_field("to_volume", "Target volume", "int", 0), _field("seconds", "Authored fade seconds", "float", 1.0))
ACTION_SCHEMAS["Stop Native Music"] = ()
ACTION_SCHEMAS["Set Native Music Volume"] = (_field("volume", "Volume 0-100", "int", 100),)
ACTION_SCHEMAS["Open Mission Results"] = ACTION_SCHEMAS.get("Show Mission Results", ())
ACTION_SCHEMAS["Open Victory Statistics"] = ACTION_SCHEMAS.get("Show Victory Statistics", ())
ACTION_SCHEMAS["Close Mission Results"] = ()
ACTION_SCHEMAS["Lock Gameplay Input"] = ()
ACTION_SCHEMAS["Unlock Gameplay Input"] = ()
ACTION_SCHEMAS["Mark Before Native Save"] = ()
ACTION_SCHEMAS["Mark After Native Save"] = ()
ACTION_SCHEMAS["Mark After Native Load"] = ()
ACTION_SCHEMAS["Native Camera Shrink"] = ACTION_SCHEMAS.get("Scene Camera Zoom Out", ())
ACTION_SCHEMAS["Native Camera Expand"] = ACTION_SCHEMAS.get("Scene Camera Zoom In", ())
ACTION_SCHEMAS["Clear legacy Event History"] = ()

KIND_HELP.update({
    "Player Issued Native Order": "Best-evidence local-human order edge promoted from the source-shaped order transition tracker. It is not falsely claimed as the exact Remastered command decoder until that callback is verified.",
    "Native Command Button Clicked": "Best-evidence command-button edge. Custom Trigger Studio hotkeys are exact locally; stock Remastered command-card attribution remains inferred until the exact statbtn callback is hooked.",
    "Attack Hit": "Best-evidence hit edge from a retained native target plus target HP loss. Native damage is real; exact reference module hit callback attribution remains a research target.",
    "Attack Missed": "Best-evidence miss edge derived from the improved native projectile lifetime/proximity classifier.",
    "Projectile Impact": "Unified best-evidence projectile impact condition. Filter Impact kind by Unit or Terrain. Exact reference module impact-vs-expiry callback remains unverified.",
    "Production Cancelled": "Best-evidence cancellation when native production clears before its stored current/total progress reaches completion.",
    "Resource Harvested": "Best-evidence cargo empty-to-loaded edge using the source worker cargo flags and amount.",
    "Resource Node Depleted": "Exact native remaining-counter edge at the native-verified resource-node field (+0x8A).",
    "Spell Cast Started": "Source-shaped cast lifecycle edge from the validated native spell action IDs.",
    "Unit Entered Player Vision": "General authoring alias over the verified named-actor sight-range edge; exact renderer fog callback is not claimed.",
    "Set Briefing Text Area": "legacy reference module set_scrolling_rect-shaped authoring state. Remastered briefing widget ownership is still unverified.",
    "Start Scrolling Briefing": "legacy init/draw_scrolling_text-shaped mission surface. Uses safe Warcraft text now; native briefing object construction remains fail-closed.",
    "Open Objectives Screen": "Uses the existing 1.38 native in-game Objectives opener and trigger-over-map objective policy.",
    "Start Portrait Transmission": "First-class portrait/transmission authoring state with validated Scene Transmission fallback. Exact Remastered portrait widget/queue remains unverified.",
    "Start Campaign Slideshow": "legacy SLIDESHW.C-shaped slideshow state. Safe text/minimap presentation is available without guessing the modern front-end ABI.",
    "Play FMV": "legacy finale_flic-shaped action. By default it provides timed authored fallback presentation; Require native fails closed because the Remastered movie-player ABI is not verified.",
    "Fade Screen In": "legacy set_fade_position-shaped authored fade timing/state. It does not claim a verified Remastered renderer fade call.",
    "Play Native Campaign Music": "legacy reference module-shaped music state. Require native fails closed until the Remastered music stream API is verified.",
    "Lock Gameplay Input": "Sets the existing native-verified local input-lock authoring state. It does not patch an unverified Remastered keyboard/mouse dispatch vtable.",
    "Before Native Save": "Event marker for an authored native-save integration sequence. Arbitrary Warcraft save interception is not claimed until the SFILE serializer hook is verified.",
    "Native Camera Shrink": "legacy gamemap_shrink-shaped alias over the authored zoom state; exact native Remastered renderer scale remains unverified.",
    "Set Campaign Map Scale": "legacy reference module set_screen_scale-shaped campaign-map state. It is authoring state until the modern campaign-map front-end ABI is proven.",
    "Set Campaign Map Position": "legacy reference module set_screen_xy-shaped campaign-map state. It does not write an unverified Remastered UI object.",
    "Diplomacy Changed": "Edge from the already-resolved live 8x8 relationship matrix.",
    "Shared Vision Changed": "Edge from the already-resolved live shared-vision masks.",
    "AI Build Goal Met": "Completion edge for Trigger Studio's source-shaped AI build goal controller.",
})


# ---------------------------------------------------------------------------
# 1.40 catalog cleanup / customization pass.
# Event conditions now expose the event-specific fields already stored in the
# runtime record, so authors can filter the exact order/button/resource/spell/etc.
_EVENT_COMPARE = COUNT_FIELDS
CONDITION_SCHEMAS["Player Issued Native Order"] = _M139_EVENT + (
    _field("order", "Native order/action ID (-1 = any)", "int", -1, optional=True),
    _field("target_x", "Target tile X (-1 = any)", "int", -1, optional=True),
    _field("target_y", "Target tile Y (-1 = any)", "int", -1, optional=True),
)
CONDITION_SCHEMAS["Native Command Button Clicked"] = _M139_EVENT + (
    _field("command", "Command/button ID (-1 = any)", "int", -1, optional=True),
    _field("production_order", "Production order (-1 = any)", "int", -1, optional=True),
    _field("production_parm", "Production parameter (-1 = any)", "int", -1, optional=True),
)
for _k in ("Attack Hit", "Attack Missed"):
    CONDITION_SCHEMAS[_k] = _M139_EVENT + (
        _field("target_player", "Target player (-1 = any)", "int", -1, optional=True),
        _field("target_unit_type", "Target unit type (-1 = any)", "int", -1, optional=True),
        _field("missile_type", "Projectile type (-1 = any)", "int", -1, optional=True),
    )
CONDITION_SCHEMAS["Projectile Impact"] = _M139_EVENT + (
    _field("impact_kind", "Impact kind", "choice", "Any", ("Any", "Unit", "Terrain"), optional=True),
    _field("missile_type", "Projectile type (-1 = any)", "int", -1, optional=True),
    _field("target_x", "Target tile X (-1 = any)", "int", -1, optional=True),
    _field("target_y", "Target tile Y (-1 = any)", "int", -1, optional=True),
)
for _k in ("Resource Harvested", "Resource Node Depleted"):
    CONDITION_SCHEMAS[_k] = _M139_EVENT + (
        _field("resource", "Resource", "choice", "Any resource", ("Any resource", "Gold", "Lumber", "Oil"), optional=True),
    )
for _k in ("Spell Cast Started", "Spell Cast Finished", "Spell Cast Interrupted"):
    CONDITION_SCHEMAS[_k] = _M139_EVENT + (
        _field("spell", "Spell", "text", "Any spell", optional=True),
    )
for _k in ("Unit Entered Player Vision", "Unit Left Player Vision"):
    CONDITION_SCHEMAS[_k] = _M139_EVENT + (
        _field("viewer_player", "Viewer player (-1 = any)", "int", -1, optional=True),
    )
for _k in ("Unit Entered Attack Range", "Unit Left Attack Range"):
    CONDITION_SCHEMAS[_k] = _M139_EVENT + (
        _field("actor", "Actor name (blank = any)", "text", "", optional=True),
        _field("target_actor", "Target actor (blank = any)", "text", "", optional=True),
    )
for _k in ("Production Cancelled", "Training Cancelled", "Research Cancelled", "Upgrade Started", "Upgrade Cancelled", "Production Resumed", "Production Paused Event"):
    CONDITION_SCHEMAS[_k] = _M139_EVENT + (
        _field("production_order", "Production order (-1 = any)", "int", -1, optional=True),
        _field("production_parm", "Production parameter (-1 = any)", "int", -1, optional=True),
    )

# ---------------------------------------------------------------------------
# 1.43 Custom Ability Engine. Definitions live in Scenario.abilities and are
# edited from Tools -> Custom Ability Engine. These clauses manipulate or query
# live per-caster state by stable ability ID.
ABILITY_CONDITIONS_143 = (
    "Ability Defined", "Unit Has Ability", "Ability Available", "Ability On Cooldown",
    "Ability Charges", "Ability Targeting", "Ability Cast Started",
    "Ability Cast Finished", "Ability Cast Failed", "Ability Cast Count",
)
ABILITY_ACTIONS_143 = (
    "Grant Ability", "Revoke Ability", "Enable Ability", "Disable Ability",
    "Begin Ability Targeting", "Cancel Ability Targeting", "Cast Ability",
    "Cast Ability At Point", "Cast Ability On Unit", "Reset Ability Cooldown",
    "Set Ability Charges", "Add Ability Charges", "Enable Ability AI",
    "Disable Ability AI", "Cast Best Ability For AI", "Show Ability Card",
    "Dump Ability State",
)
CONDITIONS.extend(ABILITY_CONDITIONS_143)
ACTIONS.extend(ABILITY_ACTIONS_143)
CONDITION_CATEGORIES["Custom abilities 1.43"] = ABILITY_CONDITIONS_143
ACTION_CATEGORIES["Custom Ability Engine 1.43"] = ABILITY_ACTIONS_143

_ABILITY_ID = (_field("ability_id", "Ability ID", "text", "arcane_bolt", help="Enter the stable ID defined in Tools -> Custom Ability Engine."),)
_ABILITY_CASTER = _ABILITY_ID + (_field("caster_reference", "Caster unit reference", "text", "Ability Caster", help="Name of a saved unit reference. Leave blank to use the first locally selected unit."),)
_ABILITY_EVENT = _ABILITY_ID + COUNT_FIELDS

CONDITION_SCHEMAS.update({
    "Ability Defined": _ABILITY_ID + COUNT_FIELDS,
    "Unit Has Ability": _ABILITY_CASTER + COUNT_FIELDS,
    "Ability Available": _ABILITY_CASTER + COUNT_FIELDS,
    "Ability On Cooldown": _ABILITY_CASTER + COUNT_FIELDS,
    "Ability Charges": _ABILITY_CASTER + COUNT_FIELDS,
    "Ability Targeting": _ABILITY_ID + COUNT_FIELDS,
    "Ability Cast Started": _ABILITY_EVENT,
    "Ability Cast Finished": _ABILITY_EVENT,
    "Ability Cast Failed": _ABILITY_EVENT + (_field("reason", "Failure reason (blank = any)", "text", "", optional=True),),
    "Ability Cast Count": _ABILITY_ID + (_field("player", "Caster owner", "player", 0),) + COUNT_FIELDS,
})
ACTION_SCHEMAS.update({
    "Grant Ability": _ABILITY_CASTER,
    "Revoke Ability": _ABILITY_CASTER,
    "Enable Ability": _ABILITY_ID,
    "Disable Ability": _ABILITY_ID,
    "Begin Ability Targeting": _ABILITY_CASTER + (_field("show_prompt", "Show targeting prompt", "bool", True),),
    "Cancel Ability Targeting": (),
    "Cast Ability": _ABILITY_CASTER,
    "Cast Ability At Point": _ABILITY_CASTER + LOCATION_POINT_FIELDS,
    "Cast Ability On Unit": _ABILITY_CASTER + (_field("target_reference", "Target unit reference", "text", "Ability Target", help="Name of the saved target unit reference. If blank, the most recent local target selection is used."),),
    "Reset Ability Cooldown": _ABILITY_CASTER,
    "Set Ability Charges": _ABILITY_CASTER + (_field("amount", "Charges", "int", 1),),
    "Add Ability Charges": _ABILITY_CASTER + (_field("amount", "Charges to add", "int", 1),),
    "Enable Ability AI": (
        _field("player", "AI owner", "player", 1),
        _field("interval", "Evaluation interval (seconds)", "float", 1.0),
        _field("max_casts", "Maximum casts per evaluation", "int", 1),
    ),
    "Disable Ability AI": (_field("player", "AI owner", "player", 1),),
    "Cast Best Ability For AI": (_field("player", "AI owner", "player", 1),),
    "Show Ability Card": _ABILITY_CASTER + (_field("seconds", "Display seconds", "int", 7),),
    "Dump Ability State": (),
})
KIND_HELP.update({
    "Ability Defined": "Counts whether a valid definition with this stable ID was loaded from the current trigger sidecar.",
    "Unit Has Ability": "Counts whether the referenced caster knows the ability through its caster-type rule or a live Grant Ability override.",
    "Ability Available": "Checks enabled state, caster eligibility, cooldown, charges, mana, and Gold/Lumber/Oil affordability.",
    "Ability On Cooldown": "Returns 1 while this caster's monotonic cooldown for the ability has time remaining.",
    "Ability Charges": "Returns remaining per-caster charges. Unlimited abilities report a large count so ordinary At least comparisons work.",
    "Ability Targeting": "Counts an active local target-selection session for the ability ID.",
    "Ability Cast Started": "Event emitted after caster, availability, and target validation create a resumable cast task.",
    "Ability Cast Finished": "Event emitted once every ordered effect, custom cost payment, cooldown, and charge update completes.",
    "Ability Cast Failed": "Event emitted when validation or a runtime effect rejects a custom cast. The optional reason field can filter exact failures.",
    "Ability Cast Count": "Counts completed custom casts by ability ID and caster owner for the current trigger run.",
    "Grant Ability": "Adds a live per-unit ability grant using the unit's generation-safe reference key.",
    "Revoke Ability": "Blocks a live unit from using an ability even when its unit type is allowed by the definition.",
    "Enable Ability": "Globally enables a loaded ability definition for the current trigger run.",
    "Disable Ability": "Globally disables a loaded ability definition without deleting it from the sidecar.",
    "Begin Ability Targeting": "Starts Trigger Studio's local map-click targeting surface for the ability and remembered caster.",
    "Cancel Ability Targeting": "Cancels the active Custom Ability Engine target selection without casting.",
    "Cast Ability": "Casts a None/Self ability from a referenced caster. Use the point or unit variants for targeted definitions.",
    "Cast Ability At Point": "Validates range and casts at a named location center or explicit tile coordinates.",
    "Cast Ability On Unit": "Validates relation, unit/building kind, and range before casting on a saved target reference.",
    "Reset Ability Cooldown": "Clears the referenced caster's cooldown for one ability.",
    "Set Ability Charges": "Sets remaining per-caster charges, clamped to the definition's maximum.",
    "Add Ability Charges": "Adds per-caster charges, clamped to the definition's maximum.",
    "Enable Ability AI": "Enables trigger-owned ability evaluation for one player. AI-enabled definitions are considered by priority and legal targets.",
    "Disable Ability AI": "Stops trigger-owned custom ability evaluation for one player.",
    "Cast Best Ability For AI": "Immediately evaluates AI-enabled definitions by priority and casts the first affordable legal choice.",
    "Show Ability Card": "Displays a live summary of description, hotkey, costs, cooldown, and charges through Warcraft's information-message path.",
    "Dump Ability State": "Writes a compact diagnostic snapshot of definitions, cooldowns, charges, active casts, targeting, and AI owners to the Trigger Studio console.",
})

# ---------------------------------------------------------------------------
# 1.44 All Cards Trigger Engine. Scenario.cards may contain the complete 418-row
# source catalog plus any custom definitions. Card input/timing is deliberately
# local/caution and carries no multiplayer-safe badge.
CARD_CONDITIONS_144 = (
    "Card Defined", "Producer Has Card", "Card Available", "Card Clicked",
    "Card Production Started", "Card Production Finished", "Card Production Failed",
    "Card Production Active", "Card Click Count",
)
CARD_ACTIONS_144 = (
    "Grant Card", "Revoke Card", "Enable Card", "Disable Card", "Activate Card",
    "Enable All Human Cards", "Enable All Orc Cards", "Enable All Cards", "Disable All Cards",
    "Cancel Trigger Card Production", "Show Trigger Card Page", "Dump Card State",
)
CONDITIONS.extend(CARD_CONDITIONS_144); ACTIONS.extend(CARD_ACTIONS_144)
CONDITION_CATEGORIES["Trigger command cards 1.44"] = CARD_CONDITIONS_144
ACTION_CATEGORIES["All Cards Trigger Engine 1.44"] = CARD_ACTIONS_144

_CARD_ID = (_field("card_id", "Card ID", "text", "stock.sgHBarracksCard.0", help="Stable ID from Tools -> All Cards Trigger Engine."),)
_CARD_PRODUCER = _CARD_ID + (_field("producer_reference", "Producer unit reference", "text", "", help="Leave blank to use the first locally selected producer.", optional=True),)
_CARD_EVENT = _CARD_ID + COUNT_FIELDS
CONDITION_SCHEMAS.update({
    "Card Defined": _CARD_ID + COUNT_FIELDS,
    "Producer Has Card": _CARD_PRODUCER + COUNT_FIELDS,
    "Card Available": _CARD_PRODUCER + COUNT_FIELDS,
    "Card Clicked": _CARD_EVENT,
    "Card Production Started": _CARD_EVENT,
    "Card Production Finished": _CARD_EVENT,
    "Card Production Failed": _CARD_EVENT + (_field("reason", "Failure reason (blank = any)", "text", "", optional=True),),
    "Card Production Active": _CARD_PRODUCER + COUNT_FIELDS,
    "Card Click Count": _CARD_ID + (_field("player", "Producer owner", "player", 0),) + COUNT_FIELDS,
})
ACTION_SCHEMAS.update({
    "Grant Card": _CARD_PRODUCER, "Revoke Card": _CARD_PRODUCER,
    "Enable Card": _CARD_ID, "Disable Card": _CARD_ID, "Activate Card": _CARD_PRODUCER,
    "Enable All Human Cards": (), "Enable All Orc Cards": (), "Enable All Cards": (), "Disable All Cards": (),
    "Cancel Trigger Card Production": (_field("producer_reference", "Producer unit reference", "text", "", help="Leave blank to use the first locally selected producer.", optional=True),),
    "Show Trigger Card Page": (
        _field("producer_reference", "Producer unit reference", "text", "", help="Leave blank to use the first locally selected producer.", optional=True),
        _field("page", "Card page (blank = all)", "text", "", optional=True),
        _field("title", "Title", "text", "TRIGGER CARDS"), _field("seconds", "Display seconds", "int", 8),
    ),
    "Dump Card State": (),
})
KIND_HELP.update({
    "Card Defined": "Counts whether a valid command-card definition with this stable ID was loaded from Scenario.cards.",
    "Producer Has Card": "Checks source producer IDs plus live per-unit Grant Card and Revoke Card overrides.",
    "Card Available": "Checks enabled state, producer eligibility, busy state, food, and authored/native resource cost.",
    "Card Clicked": "Event emitted for every source or custom trigger card activation, including rows whose native callback remains intentionally uncalled.",
    "Card Production Started": "Event emitted after verified native production starts or a cross-faction timed fallback is paid and scheduled.",
    "Card Production Finished": "Event emitted when native production clears or the validated cross-faction creation/research fallback completes.",
    "Card Production Failed": "Event emitted when card validation, affordability, producer state, native pairing, or fallback completion rejects the request.",
    "Card Production Active": "Returns 1 while this producer has a native or trigger-owned card production task tracked by the engine.",
    "Card Click Count": "Counts card activations by stable ID and producer owner during the current trigger run.",
    "Grant Card": "Gives one exact live producer a card regardless of its source producer-type list.",
    "Revoke Card": "Blocks one exact live producer from a card even when the source producer-type list includes it.",
    "Enable Card": "Enables one loaded card definition for this trigger run.",
    "Disable Card": "Disables one loaded card definition without removing it from the sidecar.",
    "Activate Card": "Clicks a card for a saved or locally selected producer. Production uses the native start path first and the authored cross-faction fallback only when enabled.",
    "Enable All Human Cards": "Enables every loaded card whose source race is Human.",
    "Enable All Orc Cards": "Enables every loaded card whose source race is Orc.",
    "Enable All Cards": "Enables every loaded source and custom trigger card.",
    "Disable All Cards": "Disables every loaded source and custom trigger card.",
    "Cancel Trigger Card Production": "Cancels a tracked card task. Trigger-owned cross-faction costs are refunded; native production remains under Warcraft's own Cancel path.",
    "Show Trigger Card Page": "Displays up to 32 eligible cards for the selected producer through Warcraft's information-message path, optionally filtered by source/custom page.",
    "Dump Card State": "Writes definition, enabled, active-production, and click totals to the Trigger Studio console.",
})

# Public palettes, field help, and generated manuals use neutral source language.
# Historical sidecar aliases and developer-only implementation notes remain
# loadable internally but are never presented as a category or help label.
def _public_source_label(value: str) -> str:
    return str(value).replace("legacy", "Warcraft II source")

CONDITION_CATEGORIES = {_public_source_label(category): entries for category, entries in CONDITION_CATEGORIES.items()}
ACTION_CATEGORIES = {_public_source_label(category): entries for category, entries in ACTION_CATEGORIES.items()}
KIND_HELP = {kind: _public_source_label(help_text) for kind, help_text in KIND_HELP.items()}
for _table in (CONDITION_SCHEMAS, ACTION_SCHEMAS):
    for _schema_kind, _specs in list(_table.items()):
        _table[_schema_kind] = tuple(replace(_spec, label=_public_source_label(_spec.label), help=_public_source_label(_spec.help), choices=tuple(_public_source_label(choice) for choice in _spec.choices)) for _spec in _specs)

# Every visible canonical entry is unique and appears in one palette category.
# Legacy aliases remain in schema/help tables so old sidecars can be migrated.
ACTIONS, ACTION_CATEGORIES = cleanup_catalog(ACTIONS, ACTION_CATEGORIES, "action")
CONDITIONS, CONDITION_CATEGORIES = cleanup_catalog(CONDITIONS, CONDITION_CATEGORIES, "condition")

# Guarantee that every visible primitive has an explicit schema and useful help
# entry. Older catalogs had hundreds of placeholder "Documented action" lines;
# 1.40 replaces those placeholders with category + customization information so
# every palette entry explains how it is authored even when its implementation
# does not need a long special-case note.
def _category_for(kind: str, categories: dict[str, tuple[str, ...]]) -> str:
    return next((category for category, entries in categories.items() if kind in entries), "Other documented features")

def _ensure_help(kind: str, mode: str, schemas: dict[str, tuple[FieldSpec, ...]], categories: dict[str, tuple[str, ...]]) -> None:
    specs = schemas.setdefault(kind, ())
    current = str(KIND_HELP.get(kind, "")).strip()
    if current and not current.startswith("Documented action") and not current.startswith("Documented condition"):
        return
    category = _category_for(kind, categories)
    if specs:
        fields = ", ".join(spec.label for spec in specs)
        detail = f"Customizable fields: {fields}."
    else:
        detail = "This primitive has no extra clause parameters; trigger players, timing, repeat policy, enable state, and comments remain configurable at the trigger level."
    KIND_HELP[kind] = f"{kind} is a {mode} in the {category} family. {detail}"

for _kind in CONDITIONS:
    _ensure_help(_kind, "condition", CONDITION_SCHEMAS, CONDITION_CATEGORIES)
for _kind in ACTIONS:
    _ensure_help(_kind, "action", ACTION_SCHEMAS, ACTION_CATEGORIES)

# 1.42 documentation contract: every customizable field has its own note.
# Existing hand-authored notes win; missing notes are filled from shared semantic
# keys or a type/default-aware fallback. This keeps the editor and generated
# manual synchronized instead of maintaining a second hand-written parameter list.
def _document_field(spec: FieldSpec) -> FieldSpec:
    if str(spec.help).strip():
        return spec
    shared = str(VALUE_HELP.get(spec.key, "")).strip()
    if shared:
        return replace(spec, help=shared)
    kind_notes = {
        "player": "Select the Warcraft player/owner used by this feature. Player labels are shown in the editor; JSON uses the runtime player value.",
        "players": "Select one or more Warcraft players. The feature applies only to the checked players.",
        "unit": "Choose the unit, building, or Any filter used by this feature.",
        "mobile_unit": "Choose the mobile Warcraft unit type used by this feature.",
        "building": "Choose the building or map-object type used by this feature.",
        "building_any": "Choose a specific building type or Any when the feature supports a building-wide filter.",
        "location": "Choose a named trigger location or Anywhere. Point-based features may expose X/Y when Anywhere is selected.",
        "missile": "Choose the Warcraft projectile/missile type used by this feature.",
        "choice": "Choose one of the supported values for this feature.",
        "bool": "Enable or disable this option for the feature.",
        "int": "Enter a whole-number value used by this feature.",
        "float": "Enter a numeric value; decimal values are allowed.",
        "amount": "Enter a numeric limit or choose All when the feature supports applying to every match.",
        "text": "Enter the text value used by this feature.",
        "multiline": "Enter one or more lines of text used by this feature.",
        "message_template": "Enter the Warcraft message template. Supported Trigger Studio substitutions are expanded when the action fires.",
        "chat_template": "Enter the Warcraft chat template. Supported Trigger Studio substitutions are expanded when the action fires.",
        "expression": "Enter a Trigger Studio expression evaluated when this feature runs.",
        "json": "Enter valid JSON for this advanced feature field.",
    }
    note = kind_notes.get(spec.kind, f"Configure the {spec.label} value used by this feature.")
    if spec.choices:
        shown = [str(value) for value in spec.choices[:12]]
        suffix = ", ".join(shown)
        if len(spec.choices) > 12:
            suffix += f", … ({len(spec.choices)} choices total)"
        note += f" Choices: {suffix}."
    if spec.optional:
        note = "Optional. " + note
    else:
        note += f" Default: {spec.default!r}."
    return replace(spec, help=note)

def _document_schema_table(table: dict[str, tuple[FieldSpec, ...]], kinds: list[str]) -> None:
    for feature_kind in kinds:
        table[feature_kind] = tuple(_document_field(spec) for spec in table.setdefault(feature_kind, ()))

_document_schema_table(CONDITION_SCHEMAS, CONDITIONS)
_document_schema_table(ACTION_SCHEMAS, ACTIONS)
