import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
from tools.modeling.parse_item_vectors import build_vector, build_vectors
from tools.validate.schema_validator import OfflineSchemaValidator


class ItemVectorTests(unittest.TestCase):
    def setUp(self):
        self.items = {
            "item_verified_cape": {"item_id": "item_verified_cape", "canonical_name_zh_tw": "測試斗篷", "canonical_name_en": "Test Cape", "aliases": ["測斗"], "verification_status": "verified"},
            "item_review_mask": {"item_id": "item_review_mask", "canonical_name_zh_tw": "測試面具", "canonical_name_en": "Test Mask", "aliases": ["測面"], "verification_status": "needs_review"},
        }
        self.aliases = {"測試斗篷": {"item_verified_cape"}, "測斗": {"item_verified_cape"}, "測試面具": {"item_review_mask"}, "測面": {"item_review_mask"}}
        self.profile = {"account_id": "account_fixture", "source_listing_ids": ["listing_fixture"], "season_profiles": [], "collection": {"owned_item_ids": [], "graduation_rewards": [], "collaboration_items": [], "bundle_item_ids": [], "event_limited_item_ids": [], "graduation_reward_season_ids": []}, "resources": {"values": {}, "evidence_state": "unknown"}, "map_completion": {"evidence_state": "unknown"}, "base_account": {"account_type": "unknown"}, "bindings": {"risk_state": "unknown"}, "ownership_history": "unknown"}

    def _vector(self, text, owned=(), missing=()):
        profile = json.loads(json.dumps(self.profile))
        profile["collection"]["owned_item_ids"] = list(owned)
        profile["season_profiles"] = [{"owned_item_ids": [], "missing_item_ids": list(missing)}]
        return build_vector(profile, {"listing_text": text}, self.items, self.aliases, ROOT)

    def test_absent_item_is_unknown_not_missing(self):
        vector = self._vector("普通帳號")
        states = {row["item_id"]: row for row in vector["item_states"]}
        self.assertEqual(states["item_verified_cape"]["state"], "unknown")
        self.assertFalse(states["item_verified_cape"]["conflict"])

    def test_alias_is_owned_and_review_item_is_sensitivity_only(self):
        vector = self._vector("有測斗與測面")
        states = {row["item_id"]: row for row in vector["item_states"]}
        self.assertEqual(states["item_verified_cape"]["state"], "owned")
        self.assertTrue(states["item_verified_cape"]["model_feature"])
        self.assertEqual(states["item_review_mask"]["state"], "owned")
        self.assertFalse(states["item_review_mask"]["model_feature"])
        self.assertTrue(states["item_review_mask"]["sensitivity_feature"])

    def test_explicit_negative_is_confirmed_missing_and_conflict_is_not_resolved(self):
        vector = self._vector("沒有測斗", owned=["item_verified_cape"])
        state = next(row for row in vector["item_states"] if row["item_id"] == "item_verified_cape")
        self.assertEqual(state["state"], "unknown")
        self.assertEqual(state["evidence_state"], "conflict")
        self.assertTrue(state["conflict"])

    def test_real_data_build_is_deterministic_and_schema_valid(self):
        first, second = build_vectors(ROOT), build_vectors(ROOT)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 1022)
        validator = OfflineSchemaValidator(ROOT / "schemas")
        self.assertEqual(validator.validate(first[0], ROOT / "schemas/modeling/item-vector.schema.json"), [])
        self.assertEqual(len(first[0]["item_states"]), len(self._catalog_ids()))

    def _catalog_ids(self):
        return [json.loads(line)["item_id"] for line in (ROOT / "knowledge/items/items.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
