Warcraft II Trigger Studio 1.44.0
==================================

All Cards Trigger Engine + cross-faction production/spells.


ALL CARDS TRIGGER ENGINE (1.44)
-------------------------------
Open Tools -> All Cards Trigger Engine or click Cards. Click Add Full Source
Catalog to import every source command row: 61 card arrays and 418 editable cards.
The sidecar v4 cards list keeps the original page, slot, icon, visibility callback,
action callback, parameters, tooltip token, and target mask.

Translated rows execute through verified Trigger Studio paths:
- 32 Train Unit cards
- 32 Build Structure cards
- 16 Research Spell cards
- 32 Research Upgrade cards
- 8 Upgrade Building cards
- 21 Cast Native Spell cards
- 277 remaining source command rows emit Card Clicked and can run any trigger logic

Click Enable Human <-> Orc after importing the catalog. It adds the opposite-race
producer IDs to racial cards. Human Barracks can train Orc units; Orc Barracks can
train Human units. Mage Towers/Churches and their Orc counterparts can research each
other's spells. Native spell cards can use the Custom Ability target picker across
races when the explicit cross-faction flag is enabled.

Production always tries Warcraft's verified bldg_build_start path first. If the
stock producer table rejects an authored cross-race unit or research card, the engine
uses a paid, timed trigger-owned fallback built from validated resource, unit-create,
spell-bit, and technology-level primitives. It never jumps to an unverified modern
command-card callback. Building-upgrade replacement has no guessed fallback and
fails closed if native production rejects it.

Try examples/All_Cards_Cross_Faction_Showcase_1.44.w2trig.json. It contains all 418
cards with Human/Orc expansion already enabled. The full guide is
docs/ALL_CARDS_TRIGGER_ENGINE_1.44.md.

1.44 catalog totals:
- 666 canonical actions
- 380 canonical conditions
- 1,046 visible primitives
- 666 dedicated action examples + 380 dedicated condition examples
- 1,051 bundled .w2trig.json profiles; all validate with zero errors
- 4,198 documented customizable parameter fields

All 21 new card primitives are deliberately unbadged: hotkeys, card events, wall-clock
fallback timing, and cross-faction overrides have not been verified multiplayer-safe.


CUSTOM ABILITY ENGINE (1.43, INCLUDED)
--------------------------------------
Open Tools -> Custom Ability Engine or click Abilities on the toolbar. Abilities are
stored directly in the .w2trig.json sidecar and move with the rest of the scenario.

Each definition can customize:
- stable ID, name, description, icon/asset note, and local hotkey;
- None, Self, Point, Unit, Enemy Unit, Allied Unit, or Building targeting;
- tile range and allowed Warcraft unit-type IDs;
- Mana, Gold, Lumber, and Oil cost;
- per-caster cooldown and limited/unlimited charges;
- enabled state, AI eligibility, and AI priority;
- an ordered stack of 17 effect types.

The included effect composer can use a validated native spell, exact unit/area
damage, healing, mana restoration, teleports, native unit creation, statuses,
projectiles, orders, target kills, synchronous trigger functions, game messages,
caster sounds, variables, and counters.

The live cast pipeline is resumable: if Warcraft's simulation-thread mailbox needs
another update, the cast resumes at the same effect instead of firing completed
effects twice. Costs, cooldown, charges, cast counts, and finished events commit only
after the effect stack completes.

Local hotkeys open the existing map-click target picker. Trigger-owned AI evaluates
AI-enabled definitions by priority, affordability, range, relation, and legal target.
These local/wall-clock features are intentionally not given an M badge.

Try examples/Custom_Ability_Engine_Showcase_1.43.w2trig.json. Its five editable
abilities demonstrate focused damage, ally protection, blink, area damage, summons,
hotkeys, costs, cooldowns, charges, events, and AI casting.
The complete authoring guide is docs/CUSTOM_ABILITY_ENGINE_1.43.md.

1.43 catalog totals:
- 654 canonical actions
- 371 canonical conditions
- 1,025 visible primitives
- 654 dedicated action examples + 371 dedicated condition examples
- 1,029 bundled .w2trig.json profiles; all validate with zero errors
- 4,153 documented customizable parameter fields


DOCUMENTATION COMPLETENESS + DESKTOP SHELL (1.42)
-------------------------------------------------


DOCUMENTATION COMPLETENESS (1.42)
---------------------------------
Documentation is now a release gate, not a best-effort export. Every one of the 998
canonical visible trigger primitives must have all of the following before a release
passes: a unique palette entry, customization schema, feature description, M/non-M
classification, documentation for every editable parameter, one dedicated example,
all required fields present in that example, and a clean Scenario.validate() result.

The Add/Edit Condition and Action dialogs now show documentation beneath every
parameter and include an Open Example button for the selected primitive. Help ->
Documentation Coverage Report opens the generated completeness audit.

1.42 audited:
- 637 canonical actions / 637 dedicated action examples
- 361 canonical conditions / 361 dedicated condition examples
- 998 visible primitives total
- 4,082 documented customizable parameter fields
- 1,001 bundled .w2trig.json profiles; all validate with zero errors

Use Check_Documentation.bat to rerun the release audit and
Rebuild_Documentation.bat to regenerate the manual/catalog from the live editor schema.

GUI highlights
--------------
- Conventional File / Edit / View / Run / Tools / Help menu bar.
- Compact toolbar for Open, Save, Validate, Attach, Detach, Start, Stop, Continue, Step and Console.
- F4/Shift+F4 attach controls and F5/Shift+F5 trigger Start/Stop shortcuts.
- AUTO Attach + Start remains enabled by default. Manual Start/Stop/Detach remain authoritative for deep testing.
- Header shows the active trigger filename and live WARCRAFT / TRIGGERS / MAP status badges.
- Live logging no longer forces the console window to the foreground.
- Existing Trigger Files workspace, multiplayer M badges, duplicate cleanup, full parameter customization and documentation remain intact.

WARCRAFT II TRIGGER STUDIO 1.40.0
================================
Multiplayer Badge + Canonical Catalog + Auto Match Runtime

START
-----
Double-click Start_Trigger_Studio.bat.
The release runs the editable ./src runtime. The shipped source IS the runtime.

AUTO MODE (DEFAULT ON)
----------------------
1. Start Trigger Studio. AUTO Attach + Start is enabled by default.
2. Open the trigger sidecars you are working with (mission01, mission02, etc.).
3. Start Warcraft II normally.
4. Trigger Studio watches for Warcraft without installing hooks.
5. When Warcraft enters GAME_RUN, Trigger Studio performs the normal validated attach.
6. It reads the active process for the current .pud filename, switches to the matching
   open sidecar (or a matching sidecar beside your other mission files), then starts
   the trigger engine automatically.

Manual Attach / Start / Stop / Detach remain in the toolbar for deep testing.
A manual Stop or Detach holds AUTO for the rest of the current match; AUTO is allowed
again when the next match starts.

MULTIPLAYER M BADGE
-------------------
A capital M is displayed before a primitive that is multiplayer-eligible.
It appears in the palette, clause rows/type picker/help, and before a whole trigger
name only when every condition and action in that trigger is M-eligible.

M is intentionally conservative. For simulation-changing triggers, every participating
client should run the same Trigger Studio 1.43 version and the same sidecar so each
simulation receives the same deterministic changes. M does NOT mean a one-client
memory edit automatically synchronizes through Warcraft networking.

Local UI/input/audio/media, wall-clock/random-sensitive operations, debugger/file
operations, inferred edge callbacks, and unverified native front-end APIs are left
unbadged.

NO DUPLICATE PALETTE ENTRIES
----------------------------
1.40 consolidates 25 historical action aliases and 7 historical condition aliases.
Old sidecars still load: aliases are migrated to canonical names in memory and saved
back canonically. Duplicate category placements were also removed.

Canonical visible catalog:
- 637 actions
- 361 conditions
- 998 total primitives

Every visible primitive has:
- exactly one palette placement;
- an editor schema (or an explicit no-extra-parameters schema);
- help/documentation;
- multiplayer classification;
- a dedicated validation example.

CUSTOMIZATION / DOCUMENTATION
-----------------------------
Use Feature Manual for the searchable catalog. Every entry documents its category,
M status, description, parameter keys, labels, types, defaults, choices/notes, and a
dedicated example profile. Trigger-level players, enabled state, comments, start delay,
repeat interval and maximum runs remain editable independently of clause parameters.

Important docs:
- docs/FEATURES.html
- docs/FEATURE_CATALOG_1.42.json
- docs/MULTIPLAYER_1.40.0.md
- docs/DUPLICATE_AUDIT_1.40.0.txt
- docs/AUTO_MATCH_1.40.0.md

SOURCE
------
Complete editable source is in ./src, including feature_metadata.py and all runtime
modules. Keep the source with every release.

LIVE TEST NOTE
--------------
Static validation targets Warcraft II Remastered x86 1.0.2.2818. AUTO process/map
probing is read-only before the normal validated attach. Features whose exact modern
Remastered callback/object ABI is still unverified remain state-backed, best-evidence,
or fail-closed and still require controlled Windows live testing.
