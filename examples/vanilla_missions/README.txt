PLAYABLE BLANK-MAP VANILLA TESTS — v6

These profiles require Trigger Studio 1.35.0 or newer.

Key changes:
- Player-owned units use the new Local Human selector (-2 internally).
- Enemy units use First Non-Local Slot (-3 internally).
- No fixed White/P7 assumption.
- Cross-player alliances are explicitly Enemy; self stays Allied.
- Full shared vision is enabled for testing.
- Open Scenario Objectives invokes Warcraft II Remastered's real native Scenario Objectives screen with the authored objective strings.
- Mission result logic is armed only after all required live units/objects are verified.

Mission 1: control your Danath + 10 Footmen and kill the enemy Grunts. Danath must survive.
Mission 2: control your Turalyon + Danath + 12 Footmen, kill the enemy Grunts, then move both heroes into the spawned Circle of Power at 51,51.
