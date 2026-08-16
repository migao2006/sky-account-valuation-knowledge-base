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
        return build_vector(profile, {"listing_text": text, "offer_kind": "seller_listing", "entity_kind": "single_account"}, self.items, self.aliases, ROOT)

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

    def test_feature_summary_is_a_separate_item_provenance_source(self):
        vector = build_vector(
            self.profile,
            {"listing_text": "帳號內容未展開", "feature_summary": ["含測斗"], "offer_kind": "seller_listing", "entity_kind": "single_account"},
            self.items, self.aliases, ROOT,
        )
        state = next(row for row in vector["item_states"] if row["item_id"] == "item_verified_cape")
        self.assertEqual(state["state"], "owned")
        self.assertEqual(state["matched_sources"], ["normalized_feature_summary"])
        self.assertEqual(vector["parser_summary"]["listing_text_matched_item_count"], 0)
        self.assertEqual(vector["parser_summary"]["feature_summary_matched_item_count"], 1)

    def test_positive_and_negative_across_provenance_fail_closed(self):
        vector = build_vector(
            self.profile,
            {"listing_text": "含測斗", "feature_summary": ["沒有測斗"], "offer_kind": "seller_listing", "entity_kind": "single_account"},
            self.items, self.aliases, ROOT,
        )
        state = next(row for row in vector["item_states"] if row["item_id"] == "item_verified_cape")
        self.assertEqual(state["state"], "unknown")
        self.assertTrue(state["conflict"])
        self.assertEqual(state["matched_sources"], ["listing_text", "normalized_feature_summary"])

    def test_long_item_alias_suppresses_overlapping_short_alias_for_other_item(self):
        items = {
            "item_long": {"item_id": "item_long", "canonical_name_zh_tw": "九色鹿角", "canonical_name_en": "Long", "aliases": [], "verification_status": "needs_review"},
            "item_short": {"item_id": "item_short", "canonical_name_zh_tw": "鹿角", "canonical_name_en": "Short", "aliases": [], "verification_status": "needs_review"},
        }
        vector = build_vector(self.profile, {"listing_text": "只有九色鹿角", "offer_kind": "seller_listing", "entity_kind": "single_account"}, items, {"九色鹿角": {"item_long"}, "鹿角": {"item_short"}}, ROOT)
        states = {row["item_id"]: row["state"] for row in vector["item_states"]}
        self.assertEqual(states, {"item_long": "owned", "item_short": "unknown"})

    def test_buyer_requested_item_remains_unknown(self):
        vector = build_vector(
            self.profile,
            {"listing_text": "收號，希望有測斗", "offer_kind": "buyer_budget", "entity_kind": "single_account"},
            self.items, self.aliases, ROOT,
        )
        state = next(row for row in vector["item_states"] if row["item_id"] == "item_verified_cape")
        self.assertEqual(state["state"], "unknown")
        self.assertEqual(state["matched_aliases"], [])

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

    def test_p22_provenance_fields_are_required_by_schema(self):
        vector = build_vectors(ROOT)[0]
        validator = OfflineSchemaValidator(ROOT / "schemas")
        schema = ROOT / "schemas/modeling/item-vector.schema.json"
        missing_item_source = json.loads(json.dumps(vector))
        missing_item_source["item_states"][0].pop("matched_sources")
        self.assertTrue(validator.validate(missing_item_source, schema))
        missing_counter = json.loads(json.dumps(vector))
        missing_counter["parser_summary"].pop("feature_summary_matched_item_count")
        self.assertTrue(validator.validate(missing_counter, schema))

    def test_formal_buyer_requests_do_not_become_owned_content(self):
        vectors = {row["account_id"]: row for row in build_vectors(ROOT)}
        buyer_item = next(row for row in vectors["account_0015"]["item_states"] if row["item_id"] == "item_days_mischief_bat_cape")
        self.assertEqual(buyer_item["state"], "unknown")
        self.assertEqual(vectors["account_0167"]["feature_groups"]["season_profiles"], [])

    def _catalog_ids(self):
        return [json.loads(line)["item_id"] for line in (ROOT / "knowledge/items/items.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]


if __name__ == "__main__":
    unittest.main()
