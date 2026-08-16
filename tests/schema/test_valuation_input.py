import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "classify"))
sys.path.insert(0, str(ROOT / "tools" / "validate"))
sys.path.insert(0, str(ROOT / "tools" / "estimate"))
from classify import classify
from estimate import estimate
from schema_validator import OfflineSchemaValidator


def canonical(path, key):
    return json.loads(next(line for line in (ROOT / path).read_text(encoding="utf-8").splitlines() if line.strip()))[key]


class ValuationInputContractTest(unittest.TestCase):
    def setUp(self):
        self.item = canonical(Path("knowledge/items/items.jsonl"), "item_id")
        self.season = canonical(Path("knowledge/seasons/seasons.jsonl"), "season_id")
        self.set_id = canonical(Path("knowledge/sets/item-sets.jsonl"), "set_id")
        self.validator = OfflineSchemaValidator(ROOT / "schemas")

    def claims(self):
        return {"account_id": "account_valuation_input", "structured_claims": {"market_context": {"currency": "TWD", "server": "international", "valuation_date": "2026-08-16"}, "base_account": {"account_type": "winged_or_unspecified"}, "season_profiles": [{"season_id": self.season, "status": "complete", "owned_item_ids": [self.item]}], "collection": {"owned_item_ids": [self.item], "item_set_profiles": [{"set_id": self.set_id, "is_complete": True}], "graduation_rewards": [self.item], "graduation_reward_season_ids": [self.season], "collaboration_items": [self.item], "bundle_item_ids": [self.item], "event_limited_item_ids": [self.item]}, "bindings": {"platforms": [{"platform": "google", "status": "available"}]}, "trade_conditions": {"offer_kind": "seller_listing", "entity_kind": "single_account", "price_type": "asking"}}}

    def test_classifier_output_is_a_listing_free_valuation_input(self):
        profile = classify(self.claims())
        self.assertEqual(profile["source_listing_ids"], [])
        self.assertIsNone(profile["post_date"])
        self.assertFalse(profile["date_verified"])
        self.assertEqual(profile["date_evidence_state"], "unknown")
        self.assertEqual((profile["currency"], profile["server"], profile["valuation_date"]), ("TWD", "international", "2026-08-16"))
        self.assertEqual(profile["trade_conditions"], {"offer_kind": "seller_listing", "entity_kind": "single_account", "price_type": "normal_listing"})
        self.assertEqual(profile["collection"]["graduation_reward_season_ids"], [self.season])
        self.assertEqual(self.validator.validate(profile, ROOT / "schemas/input/valuation-account.schema.json"), [])

    def test_unknown_canonical_id_is_rejected(self):
        data = self.claims(); data["structured_claims"]["collection"]["owned_item_ids"] = ["item_not_in_canonical"]
        with self.assertRaisesRegex(ValueError, "unknown canonical item"): classify(data)

    def test_event_limited_unknown_canonical_id_is_rejected(self):
        data = self.claims(); data["structured_claims"]["collection"]["event_limited_item_ids"] = ["item_not_in_canonical"]
        with self.assertRaisesRegex(ValueError, "unknown canonical item"): classify(data)

    def test_item_set_completion_must_be_a_boolean(self):
        data = self.claims(); data["structured_claims"]["collection"]["item_set_profiles"][0]["is_complete"] = "false"
        with self.assertRaisesRegex(ValueError, "is_complete must be a boolean"): classify(data)

    def test_missing_resources_stay_unknown_and_partial_owned_pass_is_counted(self):
        data = self.claims()
        data["structured_claims"].pop("resources", None)
        data["structured_claims"]["season_profiles"] = [{"season_id": self.season, "status": "partial", "pass_owned": "yes"}]
        profile = classify(data)
        self.assertEqual(profile["resources"]["evidence_state"], "unknown")
        self.assertEqual(profile["season_summary"]["pass_not_complete_count"], 1)
        self.assertEqual(self.validator.validate(profile, ROOT / "schemas/input/valuation-account.schema.json"), [])

    def test_raw_post_is_not_an_input_format(self):
        with self.assertRaisesRegex(ValueError, "structured_claims"): classify({"account_id": "account_raw", "post_text": "not retained"})

    def test_missing_context_and_partial_trade_conditions_stay_schema_valid(self):
        data = self.claims(); data["structured_claims"].pop("market_context"); data["structured_claims"]["trade_conditions"] = {"price_type": "verified_sale", "extra": "ignored"}
        profile = classify(data)
        self.assertEqual((profile["currency"], profile["server"], profile["valuation_date"]), ("unknown", "unknown", None))
        self.assertEqual(profile["trade_conditions"], {"offer_kind": "unknown", "entity_kind": "unknown", "price_type": "unknown"})
        self.assertEqual(self.validator.validate(profile, ROOT / "schemas/input/valuation-account.schema.json"), [])

    def test_classify_schema_estimate_end_to_end_without_schema_mutation(self):
        profile = classify(self.claims())
        self.assertEqual(self.validator.validate(profile, ROOT / "schemas/input/valuation-account.schema.json"), [])
        comparables = [json.loads(line) for line in (ROOT / "data/comparables/accounts.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        result = estimate(profile, comparables)
        self.assertEqual(result["strict_candidate_count"], 3)
        self.assertEqual(result["status"], "insufficient_comparables")

    def test_market_profile_schema_can_express_all_collection_union_categories(self):
        profile = json.loads(next(line for line in (ROOT / "data/normalized/account-profiles.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()))
        collection = profile["collection"]
        collection["graduation_rewards"] = [self.item]
        collection["collaboration_items"] = [self.item]
        collection["bundle_item_ids"] = [self.item]
        collection["event_limited_item_ids"] = [self.item]
        self.assertEqual(self.validator.validate(profile, ROOT / "schemas/market/account-profile.schema.json"), [])

    def test_official_nested_comparable_schema_is_constrained_by_profile_contract(self):
        comparable = json.loads(next(line for line in (ROOT / "data/comparables/accounts.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()))
        self.assertEqual(self.validator.validate(comparable, ROOT / "schemas/market/comparable-account.schema.json"), [])

    def test_model_estimator_input_can_carry_reviewed_item_states(self):
        profile = classify(self.claims())
        profile["item_states"] = [{
            "item_id": self.item, "state": "owned", "evidence_state": "profile_claim",
            "model_feature": False, "conflict": False, "review_status": "needs_review",
        }]
        self.assertEqual(self.validator.validate(profile, ROOT / "schemas/input/valuation-account.schema.json"), [])


if __name__ == "__main__": unittest.main()
