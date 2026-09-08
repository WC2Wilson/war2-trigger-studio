# Custom Ability Engine 1.43

Open **Tools → Custom Ability Engine** or click **Abilities** on the toolbar. Ability
definitions are saved in the same `.w2trig.json` sidecar as locations and triggers.

## Fast start

1. Add an ability and give it a stable ID such as `arcane_bolt`.
2. Choose its target mode and range.
3. Enter optional caster unit IDs. Empty means any selected unit can cast it.
4. Set a local hotkey, costs, cooldown, and charges.
5. Add effects in the exact order they should execute.
6. Save the trigger file, attach to a supported live match, and start triggers.
7. Select a valid caster in Warcraft and press the hotkey. Targeted abilities open
   the map-click target picker.

The showcase at `examples/Custom_Ability_Engine_Showcase_1.43.w2trig.json` contains
five ready-to-edit definitions.

## Target modes

| Mode | Cast behavior |
|---|---|
| None | Runs immediately at the caster's tile. |
| Self | Uses the caster as both source and target. |
| Point | Requires a map tile inside range. Clicking over a unit still means its tile. |
| Unit | Requires a mobile unit inside range. |
| Enemy Unit | Requires a non-allied mobile unit inside range. |
| Allied Unit | Requires an allied mobile unit inside range. |
| Building | Requires a building/map object inside range. |

## Effect composer

| Effect | Purpose |
|---|---|
| Native Spell | Queues one validated Warcraft spell order through the native caster path. |
| Damage Target | Applies exact native unit damage with the caster as attacker. |
| Damage Area | Damages up to the nearest 32 legal units in the authored radius. |
| Heal Target | Restores health without exceeding the unit type's native-verified maximum. |
| Restore Mana | Restores caster or target mana, capped at 255. |
| Teleport Caster / Target | Uses the established live placement/movement validation. |
| Spawn Unit | Creates one mobile unit. Stack the effect to summon several safely. |
| Apply Status | Applies a supported native timer or Trigger Studio custom timed effect. |
| Create Projectile | Creates one native-verified projectile at the cast point. Stack for several. |
| Issue Order | Orders the caster or target to Move, Attack, or Patrol toward the cast point. |
| Kill Target | Uses Warcraft's native kill path. |
| Run Trigger Function | Calls a synchronous trigger function with a JSON argument object. |
| Display Message | Shows text with `{ability}`, `{caster}`, `{x}`, and `{y}` substitutions. |
| Play Caster Sound | Plays the validated selection/acknowledgement sound for the caster. |
| Set Variable | Writes a trigger variable. Integer and decimal text is converted automatically. |
| Add Counter | Adds a nonnegative amount to a named trigger counter. |

## Trigger integration

The **Custom abilities 1.43** condition category exposes definition, ownership,
availability, cooldown, charge, targeting, lifecycle-event, and cast-count checks.
The **Custom Ability Engine 1.43** action category exposes grants, revokes, global
enable/disable, explicit casts, target mode, cooldown/charge control, AI control,
live ability cards, and diagnostics.

For explicit casts, save the caster/target with existing unit-reference actions.
`Cast Ability`, `Cast Ability At Point`, and `Cast Ability On Unit` intentionally
enforce the definition's matching target mode.

## Transaction and failure behavior

Effects execute top-to-bottom. Native simulation work may defer until Warcraft's next
active update; the cast remembers its effect index and resumes without resubmitting a
completed effect. Custom Mana/Gold/Lumber/Oil costs commit after the effect stack.
Cooldown, charges, completed-cast count, and `Ability Cast Finished` commit last.

Target/availability validation failures emit `Ability Cast Failed` without applying
effects or costs. If an unusual runtime failure occurs after an earlier effect already
completed, that irreversible native effect is not rolled back; the failure event and
console diagnostic identify the stopped cast.

Native Spell effects also retain Warcraft's own spell rules and built-in mana behavior.
Set custom `mana_cost` to zero when only the native spell's built-in mana cost is desired.

## Ability AI

Mark individual definitions **AI may evaluate this ability**, assign a priority, then
run `Enable Ability AI` for the computer owner. On each authored interval the engine:

1. considers enabled definitions by descending priority;
2. checks caster eligibility, charges, cooldown, mana, and resources;
3. chooses a legal in-range enemy, ally, building, or enemy-centered point;
4. casts up to the configured maximum for that evaluation.

## Multiplayer and live-test boundary

No Custom Ability Engine action or condition carries a capital M in 1.43. Local
hotkeys, map-click targeting, monotonic cooldowns, and wall-clock AI evaluation have
not been proven synchronized across live multiplayer clients.

Static validation targets Warcraft II Remastered x86 1.0.2.2818. Unknown builds and
unresolved native paths fail closed. See `BUILD_VALIDATION_1.43.0.txt` for the required
controlled Windows smoke-test checklist.
