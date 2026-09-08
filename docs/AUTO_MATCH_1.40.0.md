# Trigger Studio 1.40.0 — Auto Attach / Map / Start

`AUTO Attach + Start` is enabled by default.

## State machine

1. **No Warcraft process** — Trigger Studio waits. No hooks are installed.
2. **Warcraft present, not in GAME_RUN** — Trigger Studio waits for an actual match.
3. **GAME_RUN detected** — Trigger Studio performs the same full compatibility-validated attach used by the manual Attach button.
4. **Map detection** — after attach, a read-only scan ranks live `.pud` filename strings. Exact filenames declared by open sidecars are preferred. Dynamic/heap occurrences are ranked above strings in the module image.
5. **Sidecar selection** — the detected map is matched against each open sidecar's `map_file` and sidecar filename. If needed, Trigger Studio also checks the folders containing the user's other sidecars for `<map>.w2trig.json` / `<map>.pud.w2trig.json` or a sidecar whose `map_file` matches.
6. **Auto start** — the selected sidecar is validated and the trigger engine starts.
7. **Match ends / Warcraft exits** — the runtime stops and detaches cleanly, then waits for the next match.

## Manual testing override

Attach, Start, Stop and Detach are intentionally retained. A manual **Stop** or **Detach** tells AUTO not to restart or reattach for the remainder of that match. The hold clears when a new match is detected. Turn AUTO off entirely when you want a fully manual test session.

## Safety boundary

The pre-attach watcher only reads the known game-mode and map-dimension globals. It does not patch Warcraft. Full PE/anchor validation still occurs before the normal live adapter installs or changes anything. Map-name scanning is read-only and best-effort; if no trustworthy filename is found, Trigger Studio keeps the currently selected sidecar rather than guessing a different mission.
