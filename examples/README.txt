Warcraft II Trigger Studio 1.44.0 examples
==========================================

- examples/actions contains one dedicated profile for each of the 666 canonical
  visible actions.
- examples/conditions contains one dedicated profile for each of the 380 canonical
  visible conditions.
- Five additional focused/demo profiles are kept at the examples root/other folders,
  including All_Cards_Cross_Faction_Showcase_1.44.w2trig.json, for 1,051 total profiles.
- Historical alias example duplicates were removed in 1.40. Old user sidecars still
  load and migrate to canonical names automatically.
- All 1,051 bundled profiles parse and Scenario.validate() with zero errors in the
  1.44 documentation release audit.

Open docs/EXAMPLES.html for the searchable canonical index. Capital M uses the same
conservative multiplayer classification as the main editor.

1.44 completeness rule
----------------------
Each canonical profile is checked to ensure its dedicated TEST action/condition is
present, every required customizable schema field is included, and the complete
scenario validates. The generated docs link directly to these profiles.
