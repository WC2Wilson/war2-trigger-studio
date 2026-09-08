from __future__ import annotations

"""Canonical trigger names and multiplayer-safety metadata for Trigger Studio.

The editor keeps legacy names loadable for old sidecars, but only canonical names are
shown in the palette.  The capital ``M`` badge is intentionally conservative:

    M = intended for deterministic multiplayer use when every participating client
        runs the same Trigger Studio sidecar/version.  Network-native message/speed
        actions are also eligible.  M is not a promise that a one-client memory edit
        will synchronize to other Warcraft clients.

Local UI/input/audio, wall-clock/random, debugger/file/checkpoint, experimental ABI,
and best-evidence edge events are deliberately left unbadged.
"""

# Clear semantic aliases that accumulated across the 1.30 -> 1.39 feature waves.
# Old JSON remains compatible: Scenario.load migrates these names in memory.
LEGACY_ACTION_ALIASES: dict[str, str] = {
    # Keep the historical internal label loadable without exposing it in the UI.
    "Clear legacy Event History": "Clear Source Event History",
    # Objective UI generations.
    "Show Native Objectives HUD (Experimental)": "Open Objectives Screen",
    "Open Native Scenario Objectives (Experimental)": "Open Objectives Screen",
    "Show Native Objectives": "Open Objectives Screen",
    "Open Scenario Objectives": "Open Objectives Screen",
    # Win/loss wording aliases.
    "Suppress Native Win/Loss": "Enable Trigger-Controlled Results",
    "Restore Native Win/Loss": "Disable Trigger-Controlled Results",
    # Music generations where the newer action is a strict authored superset.
    "Scene Set Music (Experimental)": "Play Native Campaign Music",
    "Scene Fade Music (Experimental)": "Fade Native Music",
    "Scene Stop Music (Experimental)": "Stop Native Music",
    "Play Music": "Play Native Campaign Music",
    "Set Music Volume": "Set Native Music Volume",
    # Results generations. New wrappers add lifecycle events and keep old rendering.
    "Show Mission Results": "Open Mission Results",
    "Show Victory Statistics": "Open Victory Statistics",
    # Camera naming aliases; the implementation is still the same authored zoom state.
    "Native Camera Shrink": "Scene Camera Zoom Out",
    "Native Camera Expand": "Scene Camera Zoom In",
    # Campaign map wrapper aliases. Stop remains the newer lifecycle-aware action.
    "Show Campaign Map": "Start Native Campaign Map",
    "Add Campaign Dot": "Add Native Campaign Dot",
    "Draw Campaign Route": "Draw Native Campaign Route Segment",
    "Hide Campaign Map": "Stop Native Campaign Map",
    # Screen-fade generations.
    "Scene Fade In (Experimental)": "Fade Screen In",
    "Scene Fade Out (Experimental)": "Fade Screen Out",
    "Scene Native Fade In": "Fade Screen In",
    "Scene Native Fade Out": "Fade Screen Out",
    # Movie alias generations.
    "Play Cinematic Movie (Experimental)": "Play FMV",
    "Play Native FMV": "Play FMV",
}

LEGACY_CONDITION_ALIASES: dict[str, str] = {
    "Player Issued Order (Inferred)": "Player Issued Native Order",
    "Player Command Button Used (Inferred)": "Native Command Button Clicked",
    "Attack Connected": "Attack Hit",
    "Worker Returned Resources": "Resource Deposited",
    "Worker Entered Mine": "Worker Entered Gold Mine",
    "Worker Entered Oil Patch": "Tanker Entered Oil Patch",
    "Native Camera Zoom State": "Camera Zoom State",
}


def canonical_kind(mode: str, kind: str) -> str:
    table = LEGACY_CONDITION_ALIASES if mode == "condition" else LEGACY_ACTION_ALIASES
    seen: set[str] = set()
    current = str(kind)
    while current in table and current not in seen:
        seen.add(current)
        current = table[current]
    return current


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    folded = text.casefold()
    return any(token in folded for token in tokens)


# Exact exceptions that are explicitly routed through Warcraft's network layer or
# are deterministic controls despite words that would otherwise look local.
_MP_ACTION_FORCE_SAFE = {
    "Game Message",
    "Player Chat",
    "Set Game Speed",
}

# These are intentionally not marked M even though some are harmless in MP. They
# are local presentation/debugger/tooling surfaces rather than synchronized game
# simulation controls.
_MP_ACTION_UNSAFE_TOKENS = (
    "random", "wait", "countdown", "timer", "breakpoint", "log ", "dump", "watch",
    "assert", "comment", "local ", "camera", "cursor", "tts", "sound", "music",
    "briefing", "objective", "transmission", "slideshow", "campaign map", "fmv",
    "finale", "fade", "results", "cinematic", "dialog", "act card", "epilogue",
    "credits", "minimap", "selection", "select units", "deselect", "button",
    "target selection", "placement", "input", "checkpoint", "save native",
    "native save", "screen", "probe campaign ui", "experimental", "ability",
)

# Actions that are simulation-unsafe or specifically host/tool control even when
# their names do not hit the token list above.
_MP_ACTION_UNSAFE_EXACT = {
    "Display Text",
    "Open Objectives Screen",
    "Close Objectives Screen",
    "Use Trigger Objectives",
    "Restore Map Objectives",
    "Show Objectives HUD",
    "Hide Objectives HUD",
    "Refresh Objectives HUD",
    "Clear All Campaign Objectives",
    "Set Objective",
    "Complete Objective",
    "Clear Objective",
    "Set Campaign Objective",
    "Complete Campaign Objective",
    "Fail Campaign Objective",
    "Hide Campaign Objective",
    "Show Campaign Objective",
    "Clear Campaign Objective",
    "Append Trigger Objective",
    "Replace Trigger Objective List",
    "Lock Gameplay Input",
    "Unlock Gameplay Input",
    "Clear legacy Event History",
    "Clear Source Event History",
    "Arm Blank Map Guard",
    "Grant Card", "Revoke Card", "Enable Card", "Disable Card", "Activate Card",
    "Enable All Human Cards", "Enable All Orc Cards", "Enable All Cards", "Disable All Cards",
    "Cancel Trigger Card Production", "Show Trigger Card Page", "Dump Card State",
}

# Edge conditions reconstructed by local polling can fire on slightly different
# cycles on different machines. Keep the badge conservative and omit M.
_MP_CONDITION_EDGE_TOKENS = (
    "entered", "left", "changed", "created", "died", "removed", "damaged",
    "healed", "under attack", "started", "completed", "cancelled", "trained",
    "deposited", "returned resources", "boarded", "unloaded", "captured",
    "rescued", "hit", "missed", "expired", "selected", "deselected", "issued",
    "impact", "resumed", "paused event", "finished", "depleted", "cast ",
)
_MP_CONDITION_UNSAFE_TOKENS = (
    "elapsed time", "random", "countdown", "timer", "local ", "mouse", "key ",
    "target ", "placement", "button", "camera", "campaign map", "briefing",
    "objectives screen", "transmission", "slideshow", "fmv", "finale", "fade",
    "music", "results screen", "input lock", "native save", "tts", "event available",
    "experimental", "ability",
)
_MP_CONDITION_UNSAFE_EXACT = {
    "Card Defined", "Producer Has Card", "Card Available", "Card Clicked",
    "Card Production Started", "Card Production Finished", "Card Production Failed",
    "Card Production Active", "Card Click Count",
}


def multiplayer_safe(mode: str, kind: str) -> bool:
    """Return the conservative M-badge classification for a canonical kind."""
    kind = canonical_kind(mode, kind)
    if mode == "action":
        if kind in _MP_ACTION_FORCE_SAFE:
            return True
        if kind in _MP_ACTION_UNSAFE_EXACT:
            return False
        if _contains_any(kind, _MP_ACTION_UNSAFE_TOKENS):
            return False
        # Trigger-local arithmetic/control and Warcraft simulation mutations are M
        # under the documented same-sidecar/all-clients requirement.
        return True

    if kind in {"Always", "Never"}:
        return True
    if kind in _MP_CONDITION_UNSAFE_EXACT:
        return False
    if _contains_any(kind, _MP_CONDITION_UNSAFE_TOKENS):
        return False
    if _contains_any(kind, _MP_CONDITION_EDGE_TOKENS):
        return False
    return True


def display_kind(mode: str, kind: str) -> str:
    kind = canonical_kind(mode, kind)
    return f"M {kind}" if multiplayer_safe(mode, kind) else kind


def multiplayer_note(mode: str, kind: str) -> str:
    kind = canonical_kind(mode, kind)
    if multiplayer_safe(mode, kind):
        return (
            "M — multiplayer-eligible. For simulation-changing triggers, every "
            "participating client should run the same Trigger Studio version and "
            "the same sidecar so execution stays deterministic."
        )
    return (
        "No M badge — treat this as local-only, timing/random-sensitive, inferred "
        "edge logic, debugger/tooling, or an unverified native UI/media surface."
    )


def trigger_multiplayer_safe(trigger: object) -> bool:
    conditions = list(getattr(trigger, "conditions", ()) or ())
    actions = list(getattr(trigger, "actions", ()) or ())
    clauses = [("condition", c) for c in conditions] + [("action", a) for a in actions]
    return bool(clauses) and all(multiplayer_safe(mode, getattr(clause, "kind", "")) for mode, clause in clauses)


def cleanup_catalog(kinds: list[str], categories: dict[str, tuple[str, ...]], mode: str) -> tuple[list[str], dict[str, tuple[str, ...]]]:
    """Remove legacy aliases and duplicate category placements while preserving order."""
    aliases = LEGACY_CONDITION_ALIASES if mode == "condition" else LEGACY_ACTION_ALIASES
    canonical: list[str] = []
    seen: set[str] = set()
    for kind in kinds:
        kind = canonical_kind(mode, kind)
        if kind in aliases:  # defensive; canonical_kind normally resolves this.
            continue
        if kind not in seen:
            canonical.append(kind)
            seen.add(kind)

    cleaned: dict[str, tuple[str, ...]] = {}
    placed: set[str] = set()
    valid = set(canonical)
    for category, entries in categories.items():
        row: list[str] = []
        for raw in entries:
            kind = canonical_kind(mode, raw)
            if kind not in valid or kind in placed:
                continue
            row.append(kind)
            placed.add(kind)
        if row:
            cleaned[category] = tuple(row)
    # Keep every canonical kind discoverable even if an older category table forgot it.
    missing = [kind for kind in canonical if kind not in placed]
    if missing:
        cleaned["Other documented features"] = tuple(missing)
    return canonical, cleaned
