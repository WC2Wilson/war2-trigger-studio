# Warcraft II Trigger Studio 1.44

A StarCraft-style trigger and mission-authoring environment for Warcraft II Remastered. Version 1.44 includes the Custom Ability Engine introduced in 1.43 and the All Cards Trigger Engine.

## Highlights

- Condition/action trigger editor with dedicated schemas and examples.
- Custom abilities with targeting, costs, cooldowns, charges, effects, hotkeys, and AI eligibility.
- Command-card authoring and card-trigger integration.
- Campaign objectives, scenes, actors, timers, variables, locations, briefings, and mission state.
- Automatic map/sidecar matching and AUTO Attach + Start.
- Conservative multiplayer **M** classification.
- Validation, diagnostics, step/continue controls, and generated documentation.

## Quick start

1. On Windows, double-click `Start_Trigger_Studio.bat`.
2. Open an existing `.w2trig.json` sidecar or add a new trigger with **Edit → Add Trigger**.
3. Use **File → Trigger Files → Add Trigger Files…** to keep multiple mission sidecars open.
4. Start Warcraft II Remastered. AUTO Attach + Start is enabled by default.
5. Watch the WARCRAFT / TRIGGERS / MAP status badges.
6. Use **Tools → Validate Trigger File** before sharing a sidecar.

The complete first-use walkthrough is in [`docs/GETTING_STARTED.md`](docs/GETTING_STARTED.md). The searchable feature manual is [`docs/FEATURES.html`](docs/FEATURES.html).

## Major systems

- **Tools → Custom Ability Engine…** — define and edit custom abilities.
- **Tools → All Cards Trigger Engine…** — edit/import command-card definitions and bind cards to trigger logic.
- **Help → Feature Manual** — full action/condition reference.
- **Help → Open Example Catalog** — dedicated example profiles.
- **Help → Documentation Coverage Report** — documentation/validation coverage.

## Keyboard shortcuts

- `F4` Attach
- `Shift+F4` Detach
- `F5` Start Triggers
- `Shift+F5` Stop Triggers
- `F6` Continue
- `F7` Step
- `Ctrl+Shift+V` Validate Trigger File

## License

MIT. See [`LICENSE`](LICENSE).
