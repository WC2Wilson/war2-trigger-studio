# Trigger Studio 1.44 — Getting Started

## Requirements

- Windows
- Python 3
- Warcraft II Remastered x86 build supported by this release

## 1. Start Trigger Studio

Double-click `Start_Trigger_Studio.bat`. The editor opens with AUTO Attach + Start enabled.

## 2. Open or create trigger content

Use **File → Trigger Files → Add Trigger Files…** to open one or more `.w2trig.json` sidecars. To add a trigger to the active sidecar, use **Edit → Add Trigger** or `Ctrl+N`.

Each trigger can define conditions, actions, player scope, comments, enabled state, start delay, repeat interval, and maximum runs.

## 3. Build conditions and actions

Select the trigger, then add/edit its condition and action rows. The editor shows parameter documentation for the selected primitive. Use **Open Example** in the editor when available, or open the full example catalog from **Help**.

A capital **M** is only shown on primitives that have been verified for multiplayer use under Trigger Studio's same-version/same-sidecar rules. Unbadged primitives should be treated as local/caution features.

## 4. Validate

Run **Tools → Validate Trigger File** (`Ctrl+Shift+V`). Resolve validation errors before live testing.

## 5. Attach and run

With AUTO mode enabled:

1. Start Warcraft II Remastered normally.
2. Enter the map you are authoring.
3. Trigger Studio watches for the supported game state, matches the active PUD with an open sidecar when possible, attaches, and starts triggers.

Manual controls remain available under **Run** and on the toolbar:

- Attach / Detach
- Start / Stop Triggers
- Continue
- Step

A manual Stop or Detach holds AUTO for the current match so you can debug without it immediately restarting.

## 6. Custom Ability Engine

Open **Tools → Custom Ability Engine…**. Abilities are stored in the sidecar. You can configure:

- ability ID/name/description
- targeting mode and range
- allowed caster unit types
- mana/gold/lumber/oil costs
- cooldown and charges
- AI eligibility and priority
- ordered effects

Start with `examples/Custom_Ability_Engine_Showcase_1.43.w2trig.json`.

## 7. All Cards Trigger Engine

Open **Tools → All Cards Trigger Engine…**. Use it to build command-card definitions, import the full command catalog, enable authored cross-faction card behavior, and bind card events to triggers.

Start with `examples/All_Cards_Cross_Faction_Showcase_1.44.w2trig.json`.

## 8. Documentation

- `docs/FEATURES.html` — complete searchable feature manual
- `docs/EXAMPLES.html` — example catalog
- `docs/CUSTOM_ABILITY_ENGINE_1.43.md` — custom ability guide
- `docs/ALL_CARDS_TRIGGER_ENGINE_1.44.md` — card engine guide
- `docs/MULTIPLAYER_1.40.0.md` — M classification rules

## Testing advice

Make one mission-system change at a time, validate the sidecar, and test it in a controlled match. For multiplayer projects, keep every participating client on the same Trigger Studio version and the same sidecar.
