import copy
import unittest
from pathlib import Path

from tools.market_intake.onboarding import feature_payload_errors
from tools.modeling.catalog_provenance import catalog_provenance, read_jsonl
from tools.modeling.market_feature_contract import (
    MarketFeatureContractError, VERSION, canonicalize, feature_mapping_for_payload,
)
from tools.modeling.publication_runtime import _payload_features


ROOT = Path(__file__).resolve().parents[2]


def payload():
    catalog = read_jsonl(ROOT / "knowledge/items/items.jsonl")
    eligible = next(row["item_id"] for row in catalog if row["verification_status"] == "verified" and row["model_feature_status"] == "eligible")
    states = [{"item_id": row["item_id"], "state": "owned" if row["item_id"] == eligible else "unknown", "evidence_state": "profile_claim", "conflict": False} for row in catalog]
    return {"feature_contract_version": VERSION, "feature_groups": {
        "base_account": {"account_type": "wingless", "wing_state": "wingless", "special_appearance": []},
        "season_profiles": [], "item_sets": [], "collection": {"bundle_claim_level": "unknown"},
        "resources": {"values": {"white_candles": 100, "hearts": 2, "red_candles": None, "season_candles": None}},
        "map_completion": {"standard_maps": "partial", "second_tier_capes": "unknown"},
        "bindings": {"risk_state": "low", "platforms": [{"platform": name, "status": "unknown"} for name in ("google", "apple", "game_center", "facebook", "nintendo", "playstation", "steam", "huawei", "twitter")]},
        "ownership_history": "first_owner"}, "item_states": states}


class AuthorizedMarketFeatureContractTest(unittest.TestCase):
    def test_full_contract_is_catalog_bound_and_runtime_mapping_is_shared(self):
        value = payload()
        normalized = canonicalize(value, ROOT)
        self.assertEqual(catalog_provenance(ROOT), normalized["catalog_provenance"])
        self.assertEqual(len(read_jsonl(ROOT / "knowledge/items/items.jsonl")), len(normalized["item_states"]))
        self.assertEqual(feature_mapping_for_payload(value, ROOT), _payload_features(value, ROOT))
        self.assertTrue(any(name.startswith("items.") for name in feature_mapping_for_payload(value, ROOT)))

    def test_extra_pii_and_forged_item_eligibility_are_rejected(self):
        value = payload(); value["feature_groups"]["base_account"]["short_id"] = "AliceSecret"
        self.assertTrue(feature_payload_errors(value, ROOT))
        value = payload(); value["feature_groups"]["bindings"]["platforms"][0]["url"] = "https://example.test"
        self.assertTrue(feature_payload_errors(value, ROOT))
        value = payload(); value["item_states"][0]["model_feature"] = True
        self.assertTrue(feature_payload_errors(value, ROOT))

    def test_missing_duplicate_and_stale_catalog_are_rejected(self):
        value = payload(); value["item_states"].pop()
        self.assertIn("item_states_not_exact_canonical_universe", feature_payload_errors(value, ROOT))
        value = payload(); value["item_states"][-1]["item_id"] = value["item_states"][0]["item_id"]
        self.assertIn("item_states_not_exact_canonical_universe", feature_payload_errors(value, ROOT))
        value = payload(); wrapped = {"account_id": "account_fixture", "catalog_provenance": {"forged": True}, **value}
        with self.assertRaisesRegex(MarketFeatureContractError, "catalog_provenance_stale"):
            canonicalize(wrapped, ROOT)

    def test_canonicalization_is_deterministic_and_derives_sets(self):
        value = payload(); reversed_value = copy.deepcopy(value)
        reversed_value["item_states"].reverse(); reversed_value["feature_groups"]["bindings"]["platforms"].reverse()
        first, second = canonicalize(value, ROOT), canonicalize(reversed_value, ROOT)
        self.assertEqual(first, second)
        self.assertTrue(first["feature_groups"]["item_sets"])

    def test_signed_payload_with_estimator_metadata_keeps_exact_feature_surface(self):
        value = payload()
        canonical = canonicalize(value, ROOT)
        # A signed training payload is replayed at estimate time alongside
        # market/evidence metadata.  Those fields are not model inputs.
        replay = {**canonical, "currency": "TWD", "server": "international",
                  "trade_conditions": {"price_type": "normal_listing"},
                  "evidence_quality": {"listing_text": "high"}}
        self.assertEqual(feature_mapping_for_payload(canonical, ROOT), feature_mapping_for_payload(replay, ROOT))

    def test_unknown_conflicting_or_forged_derived_item_cannot_enter_model(self):
        value = payload()
        item = next(row for row in read_jsonl(ROOT / "knowledge/items/items.jsonl")
                    if row["verification_status"] == "verified" and row["model_feature_status"] == "eligible")
        state = next(row for row in value["item_states"] if row["item_id"] == item["item_id"])
        state.update({"state": "owned", "evidence_state": "profile_claim", "conflict": False})
        trusted = canonicalize(value, ROOT)
        self.assertTrue(next(row for row in trusted["item_states"] if row["item_id"] == item["item_id"])["model_feature"])
        unknown = copy.deepcopy(value)
        next(row for row in unknown["item_states"] if row["item_id"] == item["item_id"])["state"] = "unknown"
        self.assertFalse(next(row for row in canonicalize(unknown, ROOT)["item_states"] if row["item_id"] == item["item_id"])["model_feature"])
        forged = copy.deepcopy(unknown)
        forged_state = next(row for row in canonicalize(forged, ROOT)["item_states"] if row["item_id"] == item["item_id"])
        forged_state["model_feature"] = True
        with self.assertRaisesRegex(MarketFeatureContractError, "model_feature_not_catalog_and_evidence_eligible"):
            canonicalize({**canonicalize(forged, ROOT), "item_states": [forged_state if row["item_id"] == item["item_id"] else row for row in canonicalize(forged, ROOT)["item_states"]]}, ROOT)


if __name__ == "__main__":
    unittest.main()
