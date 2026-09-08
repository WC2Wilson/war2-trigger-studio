# Trigger Studio 1.44.0 documentation standard

A visible trigger primitive is release-complete only when all of the following are true:

1. It has one canonical palette name and exactly one category placement.
2. It has an editor schema so its behavior is customizable from the GUI.
3. It has non-placeholder feature help explaining what it does.
4. Every editable parameter has its own documentation note, type, default, optional state, and choices when applicable.
5. It has an explicit multiplayer classification. A capital **M** means multiplayer-eligible under the same-version/same-sidecar rule; no M means local/caution.
6. It has a dedicated `.w2trig.json` example profile that contains the canonical feature in its TEST trigger.
7. Every required field appears in that dedicated example.
8. The example loads and passes `Scenario.validate()`.
9. It appears in the generated `FEATURES.html`, `EXAMPLES.html`, and `FEATURE_CATALOG_1.44.json` outputs.

The release build runs this audit and fails if any requirement is missing.
