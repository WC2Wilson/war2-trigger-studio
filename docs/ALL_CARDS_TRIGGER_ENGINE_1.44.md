# All Cards Trigger Engine 1.44

Trigger Studio 1.44 turns the Warcraft II source command-card catalog into portable trigger definitions. Open **Tools → All Cards Trigger Engine** or click **Cards** on the toolbar.

## Importing every card

Click **Add Full Source Catalog**. The editor imports 61 source card arrays containing 418 rows. Every definition retains:

- source array and row;
- source race and producer unit/building IDs;
- panel slot and icon token;
- visibility callback and parameter;
- action callback and parameter;
- tooltip token and targeting mask.

The imported action mix is:

| Trigger-card action | Rows | Runtime behavior |
|---|---:|---|
| Source Callback | 277 | Emits `Card Clicked`; a trigger decides what happens. No unverified callback address is called. |
| Train Unit | 32 | Attempts verified native production, then the authored cross-faction fallback when enabled. |
| Build Structure | 32 | Starts Trigger Studio's validated placement surface. |
| Research Spell | 16 | Attempts native research, then sets the verified spell progression bit after a timed fallback. |
| Research Upgrade | 32 | Attempts native research, then advances the verified technology row after a timed fallback. |
| Upgrade Building | 8 | Uses native production only; an unverified replacement fallback is not guessed. |
| Cast Native Spell | 21 | Uses the Custom Ability target picker and verified native spell dispatch. |

## Human and Orc cross-faction cards

After importing, click **Enable Human ↔ Orc**. The editor adds each opposite-race counterpart to the card's producer list and enables the explicit cross-faction flag.

Examples:

- Human Barracks and Orc Barracks receive both unit sets.
- Town Hall and Great Hall receive both worker cards.
- Human and Orc naval, flying, and siege producers receive the opposite unit cards.
- Mage Tower and Temple of the Damned receive each other's spell-research cards.
- Church and Altar of Storms receive each other's cleric and spell-research cards.
- Mage and Death Knight card groups may expose each other's native spell cards through the wrong-caster override.

`examples/All_Cards_Cross_Faction_Showcase_1.44.w2trig.json` already contains the complete 418-card expanded catalog.

## Production policy

For unit, research, and building-upgrade cards, the engine first calls the verified `bldg_build_start` path. Warcraft owns its normal cost, prerequisites, busy state, progress, cancellation, and completion when that call succeeds.

If Warcraft rejects a unit or research pairing and **Allow cross-faction fallback** is enabled, Trigger Studio:

1. verifies food and resources;
2. atomically deducts the resolved card cost;
3. starts a non-blocking timed production task;
4. creates the trained unit beside the producer, grants the researched spell bit, or advances the technology row;
5. emits `Card Production Finished`.

Canceling a trigger-owned task refunds its recorded cost. A failed completion also refunds it. Unit cards with cost fields set to `-1` read the verified native unit cost tables. Research fallback costs are authored on the card; imported source rows default to zero because no unverified research-cost table is assumed. Set Gold/Lumber/Oil before using those fallbacks in a balanced map.

Cross-faction building upgrades have no trigger-owned replacement fallback. If native production rejects one, the card fails closed and emits `Card Production Failed`.

## Native spell cards

Imported `order_spell` rows become `Cast Native Spell` cards. Point/unit targeting uses the same local target picker as the Custom Ability Engine. When cross-faction is enabled, the generated internal spell ability explicitly allows a non-stock caster; without that flag, the normal caster family check remains in force.

Warcraft still owns the native spell handler, mana payment, projectiles, damage, status, scoring, and cleanup. The command-card layer does not patch a guessed modern callback object.

## Trigger primitives

Conditions:

- `Card Defined`, `Producer Has Card`, `Card Available`
- `Card Clicked`
- `Card Production Started`, `Card Production Finished`, `Card Production Failed`
- `Card Production Active`, `Card Click Count`

Actions:

- `Grant Card`, `Revoke Card`, `Enable Card`, `Disable Card`
- `Activate Card`
- `Enable All Human Cards`, `Enable All Orc Cards`, `Enable All Cards`, `Disable All Cards`
- `Cancel Trigger Card Production`
- `Show Trigger Card Page`, `Dump Card State`

`Source Callback` rows are intentionally useful: `Card Clicked` makes every source row a trigger entry point, so a map can replace Move, Stop, Attack, Patrol, auto-production, cancel, card-page, or special command behavior without calling an unverified callback.

## Multiplayer and live-test boundary

None of the 21 new card primitives has an **M** badge. Local hotkeys/target input, wall-clock fallback timing, card-event edges, and cross-faction wrong-caster behavior require controlled multiplayer verification before any safe badge is added.

Static validation targets Warcraft II Remastered x86 1.0.2.2818 (PE timestamp `0x699E13E7`). Unsupported native paths fail closed. A controlled Windows live test is still required for each map's producer pairs, placement space, costs, progress/cancel expectations, and spell targets.
