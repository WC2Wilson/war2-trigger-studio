from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from card_defs import enable_cross_faction, normalize_card, stock_cards, validate_cards
from card_engine import CardEngineMixin
from clause_editor import CARD_ACTIONS_144, CARD_CONDITIONS_144
from feature_metadata import multiplayer_safe
from source_features import BUILD_SPELL, BUILD_TECH, BUILD_UNIT, BUILD_UPGRADE
from trigger_model import Clause, Scenario, Trigger
from ultimate_features import SPELL_BITS, UPGRADE_ROWS


class AllCardsTriggerEngineTests(unittest.TestCase):
    def test_complete_source_catalog_is_portable(self) -> None:
        cards = stock_cards()
        self.assertEqual(418, len(cards))
        self.assertEqual(418, len({card["id"] for card in cards}))
        self.assertEqual([], validate_cards(cards))
        actions = {card["action"] for card in cards}
        self.assertTrue({"Source Callback", "Train Unit", "Build Structure", "Research Spell", "Research Upgrade", "Upgrade Building", "Cast Native Spell"}.issubset(actions))

    def test_cross_faction_expands_units_buildings_and_spell_cards(self) -> None:
        cards = stock_cards(); changed = enable_cross_faction(cards)
        self.assertGreater(changed, 400)
        by_id = {card["id"]: card for card in cards}
        self.assertEqual([60, 61], by_id["stock.sgHBarracksCard.0"]["producer_types"])
        self.assertEqual([60, 61], by_id["stock.sgOBarracksCard.0"]["producer_types"])
        self.assertEqual([80, 81], by_id["stock.sgHWTowerCard.1"]["producer_types"])
        self.assertIn(11, by_id["stock.sgHWizardCard.3"]["producer_types"])
        self.assertTrue(by_id["stock.sgHWizardCard.3"]["allow_cross_faction"])
        self.assertEqual([], validate_cards(cards))

    def test_schema_v4_roundtrip_and_v3_compatibility(self) -> None:
        card = next(card for card in stock_cards() if card["id"] == "stock.sgHBarracksCard.0")
        scenario = Scenario(cards=[card], triggers=[Trigger(name="Card", players=[0], conditions=[Clause("Always", {})], actions=[Clause("Activate Card", {"card_id": card["id"], "producer_reference": ""})])])
        self.assertEqual([], scenario.validate())
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "card.w2trig.json"; scenario.save(path); loaded = Scenario.load(path)
            self.assertEqual(card["id"], loaded.cards[0]["id"])
            raw = json.loads(path.read_text(encoding="utf-8")); raw["version"] = 3; raw.pop("cards", None); path.write_text(json.dumps(raw), encoding="utf-8")
            self.assertEqual([], Scenario.load(path).cards)

    def test_source_production_routes_use_verified_orders(self) -> None:
        engine = object.__new__(CardEngineMixin)
        self.assertEqual((BUILD_UNIT, 1), engine._card_native_order(normalize_card({"id":"a","name":"a","action":"Train Unit","unit_type":1,"producer_types":[]})))
        self.assertEqual((BUILD_SPELL, SPELL_BITS["Bloodlust"]), engine._card_native_order(normalize_card({"id":"b","name":"b","action":"Research Spell","spell":"Bloodlust","producer_types":[]})))
        self.assertEqual((BUILD_TECH, UPGRADE_ROWS["Armor"]), engine._card_native_order(normalize_card({"id":"c","name":"c","action":"Research Upgrade","upgrade":"Armor","producer_types":[]})))
        self.assertEqual((BUILD_UPGRADE, 91), engine._card_native_order(normalize_card({"id":"d","name":"d","action":"Upgrade Building","building_type":91,"producer_types":[]})))

    def test_card_primitives_are_not_marked_multiplayer_safe(self) -> None:
        for kind in CARD_ACTIONS_144:
            self.assertFalse(multiplayer_safe("action", kind), kind)
        for kind in CARD_CONDITIONS_144:
            self.assertFalse(multiplayer_safe("condition", kind), kind)

    def test_full_showcase_validates(self) -> None:
        showcase = Scenario.load(ROOT / "examples" / "All_Cards_Cross_Faction_Showcase_1.44.w2trig.json")
        self.assertEqual(418, len(showcase.cards))
        self.assertEqual([], showcase.validate())


if __name__ == "__main__":
    unittest.main()
