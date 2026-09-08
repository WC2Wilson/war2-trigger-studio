from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
import unittest
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ability_defs import new_ability, normalize_ability, validate_abilities
from ability_engine import AbilityEngineMixin
from clause_editor import (
    ABILITY_ACTIONS_143, ABILITY_CONDITIONS_143, ACTIONS, CONDITIONS, ACTION_CATEGORIES,
    ACTION_SCHEMAS, CONDITION_CATEGORIES, CONDITION_SCHEMAS, KIND_HELP,
)
from feature_metadata import multiplayer_safe
from trigger_model import Scenario


@dataclass
class FakeUnit:
    address: int = 0x1000
    token: int = 7
    x: int = 10
    y: int = 10
    owner: int = 0
    unit_type: int = 10
    mana: int = 100
    health: int = 60
    sflags: int = 0


class FakeRuntime(AbilityEngineMixin):
    def __init__(self, ability: dict):
        self._world = [FakeUnit()]
        self._ability_definitions = {ability["id"].casefold(): normalize_ability(ability)}
        self._ability_enabled = {ability["id"].casefold(): True}
        self._ability_grants = {}; self._ability_revokes = {}; self._ability_cooldowns = {}; self._ability_charges = {}
        self._ability_cast_counts = {}; self._ability_pending_events = []; self._ability_tasks = {}; self._ability_action_task = {}; self._ability_next_serial = 1
        self.variables = {}; self.counters = {}; self.messages = []; self.logs = []

    def units(self): return list(self._world)
    def _read_resource(self, owner, resource): return 10000
    def _players_allied(self, source_owner, target_owner): return source_owner == target_owner
    def _game_message(self, args, player): self.messages.append(str(args.get("text", "")))
    def log(self, message): self.logs.append(str(message))


class AbilityDefinitionTests(unittest.TestCase):
    def test_normalize_and_validate(self):
        ability = new_ability(); ability.update({"id": "blink", "target": "Point", "caster_types": "10, 24", "cooldown": "2.5"})
        normalized = normalize_ability(ability)
        self.assertEqual(normalized["caster_types"], [10, 24])
        self.assertEqual(normalized["cooldown"], 2.5)
        self.assertEqual(validate_abilities([normalized]), [])

    def test_duplicate_ids_and_bad_effect_are_rejected(self):
        first = new_ability(); first["id"] = "same"
        second = new_ability(2); second["id"] = "same"; second["effects"] = [{"kind": "Unknown"}]
        errors = validate_abilities([first, second])
        self.assertTrue(any("Duplicate" in error for error in errors))
        self.assertTrue(any("unknown kind" in error for error in errors))

    def test_sidecar_v3_round_trip_and_v2_compatibility(self):
        scenario = Scenario(abilities=[new_ability()])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ability.w2trig.json"; scenario.save(path)
            loaded = Scenario.load(path)
            self.assertEqual(loaded.abilities[0]["id"], "ability_1")
            legacy = json.loads(path.read_text(encoding="utf-8")); legacy["version"] = 2; legacy.pop("abilities")
            path.write_text(json.dumps(legacy), encoding="utf-8")
            self.assertEqual(Scenario.load(path).abilities, [])


class AbilityRuntimeTests(unittest.TestCase):
    def test_resumable_cast_commits_state_once(self):
        ability = new_ability(); ability.update({
            "id": "scripted", "name": "Scripted", "target": "None", "cooldown": 3.0,
            "max_charges": 2, "caster_types": [], "effects": [
                {"kind": "Set Variable", "name": "Result", "value": "42"},
                {"kind": "Add Counter", "name": "Casts", "amount": 1},
                {"kind": "Display Message", "text": "{ability} complete"},
            ],
        })
        runtime = FakeRuntime(ability); caster = runtime.units()[0]
        task = runtime._ability_start_cast(caster, runtime._ability_definition("scripted"), 0, None, caster.x, caster.y)
        self.assertTrue(runtime._ability_process_task(task))
        self.assertEqual(runtime.variables["Result"], 42)
        self.assertEqual(runtime.counters["Casts"], 1)
        self.assertEqual(runtime.messages, ["Scripted complete"])
        self.assertEqual(runtime._ability_cast_counts[("scripted", 0)], 1)
        self.assertEqual(runtime._ability_charge_count(caster, runtime._ability_definition("scripted")), 1)
        self.assertGreater(runtime._ability_cooldown_remaining(caster, runtime._ability_definition("scripted")), 0)
        self.assertEqual([event[0] for event in runtime._ability_pending_events], ["Ability Cast Started", "Ability Cast Finished"])

    def test_enemy_and_range_validation(self):
        ability = new_ability(); ability.update({"id": "bolt", "target": "Enemy Unit", "range": 4})
        runtime = FakeRuntime(ability); caster = runtime.units()[0]
        ally = FakeUnit(address=0x2000, token=8, x=12, y=10, owner=0)
        enemy_far = FakeUnit(address=0x3000, token=9, x=20, y=10, owner=1)
        self.assertIn("enemy target required", runtime._ability_target_reason(caster, runtime._ability_definition("bolt"), ally, ally.x, ally.y))
        self.assertIn("outside range", runtime._ability_target_reason(caster, runtime._ability_definition("bolt"), enemy_far, enemy_far.x, enemy_far.y))


class AbilityCatalogTests(unittest.TestCase):
    def test_catalog_is_complete_and_conservative(self):
        for kind in ABILITY_ACTIONS_143:
            self.assertIn(kind, ACTION_SCHEMAS); self.assertIn(kind, KIND_HELP)
            self.assertFalse(multiplayer_safe("action", kind))
        for kind in ABILITY_CONDITIONS_143:
            self.assertIn(kind, CONDITION_SCHEMAS); self.assertIn(kind, KIND_HELP)
            self.assertFalse(multiplayer_safe("condition", kind))

    def test_public_catalog_has_no_legacy_platform_label(self):
        public = json.dumps({"actions": ACTION_CATEGORIES, "conditions": CONDITION_CATEGORIES, "help": {k: KIND_HELP[k] for k in [*ACTIONS, *CONDITIONS]}, "action_fields": {k: [s.label for s in ACTION_SCHEMAS[k]] for k in ACTIONS}, "condition_fields": {k: [s.label for s in CONDITION_SCHEMAS[k]] for k in CONDITIONS}})
        self.assertNotIn("legacy", public)


if __name__ == "__main__":
    unittest.main()
