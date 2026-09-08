# Trigger Studio 1.41 GUI

## Menu bar

- **File** — open trigger sidecars/PUDs, save, Save As, switch/close open Trigger Files, exit.
- **Edit** — add, duplicate, delete triggers; advanced JSON.
- **View** — live console, map information, locations, forces, project state.
- **Run** — AUTO Attach + Start, attach/detach, start/stop, continue/step.
- **Tools** — validation, Blank Map Guard, live unit/player/stat snapshots, trigger/runtime diagnostics.
- **Help** — complete feature manual, example catalog, About.

## Toolbar

The toolbar intentionally contains only high-frequency commands: Open, Save, Validate, Attach, Detach, Start, Stop, Continue, Step, AUTO Attach + Start and Console. Secondary operations stay in menus so the editor remains uncluttered.

## Status badges

The header reports:

- `WARCRAFT` — waiting/AUTO/attached.
- `TRIGGERS` — stopped/running.
- `MAP` — detected map name when available.

## Runtime workflow

AUTO mode remains on by default and keeps the 1.40 match watcher behavior. Manual Stop or Detach remains authoritative for the rest of the current match. F5 and Shift+F5 are always available for detailed trigger testing.

## Multiplayer

Capital **M** behavior is unchanged from 1.40: it marks multiplayer-eligible primitives. Simulation-changing M triggers still require participating clients to use the same Trigger Studio build and synchronized sidecar.
