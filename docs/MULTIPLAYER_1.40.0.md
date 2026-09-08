# Trigger Studio 1.40.0 multiplayer badge

## Capital M

`M` means **multiplayer-eligible**, not magically network-synchronized. For actions that mutate Warcraft simulation state, every participating client should run the same Trigger Studio 1.40 sidecar so the same deterministic mutation occurs on every simulation. Network-native text/speed actions are separately supported by Warcraft's own packet path.

Unbadged features are intentionally conservative: local UI/input/audio, wall-clock/random-sensitive operations, debugger/file/checkpoint operations, inferred edge callbacks, and unverified Remastered front-end/media APIs.

- M actions: 462 / 637
- M conditions: 211 / 361

The editor shows `M` in the palette, clause rows, clause type picker, help text, and on a whole trigger row only when every condition and action in that trigger is M-eligible.
