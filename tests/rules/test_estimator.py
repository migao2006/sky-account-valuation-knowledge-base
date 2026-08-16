import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "estimate"))
sys.path.insert(0, str(ROOT / "tools" / "classify"))
from estimate import WEIGHTS, adapt_profile, estimate, normalize_price_type, score
from classify import classify


class EstimatorRulesTest(unittest.TestCase):
    def setUp(self):
        fixture = ROOT / "tests" / "fixtures"
        self.account = json.loads((fixture / "estimate-account.json").read_text(encoding="utf-8"))
        self.rows = [json.loads(x) for x in (fixture / "estimate-comparables.jsonl").read_text(encoding="utf-8").splitlines()]

    def test_weights_are_exactly_one_hundred(self):
        self.assertEqual(sum(WEIGHTS.values()), 100)

    def test_multiple_dimensions_change_similarity(self):
        baseline = score(self.account, self.rows[0])["score"]
        changed = dict(self.rows[0]); changed["owned_item_ids"] = []
        changed["season_profile"] = []
        changed["resources"] = {"white_candles": 0, "hearts": 0, "red_candles": 0}
        changed["bindings"] = {"google": "locked"}
        result = score(self.account, changed)
        self.assertLess(result["score"], baseline)
        self.assertLess(result["dimensions"]["seasons"], WEIGHTS["seasons"])
        self.assertLess(result["dimensions"]["items_sets"], WEIGHTS["items_sets"])
        self.assertLess(result["dimensions"]["resources"], WEIGHTS["resources"])
        self.assertLess(result["dimensions"]["bindings"], WEIGHTS["bindings"])

    def test_hard_server_pool_and_range(self):
        result = estimate(self.account, self.rows)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["range_twd"]["median"], 8000)
        self.assertNotIn("fixture_wrong_server", {x["comparable_id"] for x in result["comparables"]})

    def test_fewer_than_three_never_priced(self):
        result = estimate(self.account, self.rows[:2])
        self.assertFalse(result["eligible"])
        self.assertEqual(result["status"], "insufficient_comparables")
        self.assertIsNone(result["range_twd"])

    def test_canonical_nested_profile_and_history_adapter(self):
        account = {
            "base_account": {"account_type": "permanent_wingless"},
            "season_profiles": [{"season_id": "season_example", "status": "complete"}],
            "collection": {"owned_item_ids": ["item_example_a"], "item_set_profiles": [{"set_id":"set_example", "is_complete": True}]},
            "resources": {"values": {"white_candles": 100}},
            "bindings": {"platforms": [{"platform":"google", "status":"transferable"}], "risk_state":"clean"},
            "ownership_history":"first_hand", "trade_conditions":{"price_type":"asking"},
            "evidence_quality":{"listing_text":"high"}, "currency":"TWD", "server":"international"
        }
        history = {**account, "history_id":"history_fixture", "selected_price_twd":9000, "post_date":"2026-08-01"}
        flat = adapt_profile(account)
        self.assertEqual(flat["base_account_type"], "permanent_wingless")
        self.assertEqual(flat["complete_set_ids"], ["set_example"])
        self.assertEqual(flat["bindings"], {"google":"transferable"})
        self.assertEqual(normalize_price_type(history), "normal_listing")
        self.assertGreater(score(account, history)["score"], 50)

    def test_reads_official_profile_and_history_files(self):
        profile_path = ROOT / "data" / "normalized" / "account-profiles.jsonl"
        history_path = ROOT / "data" / "curated" / "histories.jsonl"
        self.assertTrue(profile_path.exists())
        self.assertTrue(history_path.exists())
        profile = json.loads(next(line for line in profile_path.read_text(encoding="utf-8").splitlines() if line.strip()))
        history = json.loads(next(line for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()))
        flat = adapt_profile(profile)
        self.assertIn("base_account_type", flat)
        self.assertIn(normalize_price_type(history), {"normal_listing", "urgent_sale", "last_public_price", "verified_sale", "unknown"})

    def test_unknown_never_matches_unknown(self):
        unknown = {"base_account":{"account_type":"unknown"}, "season_profiles":[{"season_id":"season_example","status":"unknown"}], "bindings":{"platforms":[{"platform":"google","status":"unknown"}]}, "resources":{"values":{"white_candles":None}}, "trade_conditions":{"price_type":"asking"}}
        result = score(unknown, unknown)
        self.assertEqual(result["dimensions"]["account_type"], 0)
        self.assertEqual(result["dimensions"]["seasons"], 0)
        self.assertEqual(result["dimensions"]["bindings"], 0)
        self.assertEqual(result["dimensions"]["resources"], 0)

    def test_price_type_history_mapping_is_strict(self):
        self.assertEqual(normalize_price_type({"price_type":"reduced"}), "urgent_sale")
        self.assertEqual(normalize_price_type({"price_type":"sold_last_ask"}), "last_public_price")
        self.assertEqual(normalize_price_type({"price_type":"sold_explicit"}), "last_public_price")
        self.assertEqual(normalize_price_type({"price_type":"asking", "sale_outcome":{"verified":True, "completed_sale_price_twd":999}}), "verified_sale")
        self.assertEqual(normalize_price_type({"price_type":"quick_sale"}), "urgent_sale")
        self.assertEqual(normalize_price_type({"price_type":"instant_price"}), "urgent_sale")
        self.assertEqual(normalize_price_type({"price_type":"buyout"}), "unknown")

    def test_collection_union_and_categorical_map(self):
        a = {"collection":{"graduation_rewards":["item_ultimate"],"collaboration_items":[],"bundle_item_ids":["item_bundle"],"graduation_reward_season_ids":["season_example"]},"map_completion":{"standard_maps":"complete","second_tier_capes":"partial"}}
        b = {"collection":{"graduation_rewards":["item_ultimate"],"collaboration_items":[],"bundle_item_ids":["item_bundle"],"graduation_reward_season_ids":["season_example"]},"map_completion":{"standard_maps":"complete","second_tier_capes":"partial"}}
        dimensions = score(a, b)["dimensions"]
        self.assertEqual(dimensions["collection"], WEIGHTS["collection"])
        self.assertEqual(dimensions["map_completion"], WEIGHTS["map_completion"])

    def test_unverified_market_evidence_is_hard_rejected(self):
        rows = [dict(x) for x in self.rows]
        rows[0]["currency_verified"] = False
        rows[0]["server_verified"] = False
        result = estimate(self.account, rows)
        self.assertFalse(result["eligible"])
        self.assertIn("currency_verified_required", result["rejected_by_hard_pool"][0]["reasons"])

    def test_classify_then_estimate_end_to_end(self):
        profile = classify({"account_id":"account_e2e","structured_claims":{"base_account":{"account_type":"permanent_wingless"},"season_profiles":[{"season_id":"season_example","status":"complete"}],"collection":{"owned_item_ids":["item_example_a"]},"resources":{"values":{"white_candles":100}},"bindings":{"platforms":[{"platform":"google","status":"transferable"}]},"trade_conditions":{"price_type":"asking"}}})
        profile["currency"] = "TWD"; profile["server"] = "international"; profile["valuation_date"] = "2026-08-16"
        result = estimate(profile, self.rows)
        self.assertTrue(result["eligible"])

    def test_six_dimension_ablation(self):
        baseline = score(self.account, self.rows[0])["score"]
        edits = {
            "base_account_type": "winged", "season_profile": [], "owned_item_ids": [],
            "map_completion_ratio": 0, "resources": {"white_candles": 0},
            "bindings": {"google": "locked"},
        }
        for key, value in edits.items():
            changed = dict(self.rows[0]); changed[key] = value
            self.assertLess(score(self.account, changed)["score"], baseline, key)


if __name__ == "__main__":
    unittest.main()
