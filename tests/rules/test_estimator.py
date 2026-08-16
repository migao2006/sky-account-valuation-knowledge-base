import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "estimate"))
sys.path.insert(0, str(ROOT / "tools" / "classify"))
from estimate import WEIGHTS, adapt_profile, estimate, hard_pool, normalize_price_type, score
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

    def test_unknown_target_market_is_never_cross_market_estimated(self):
        target = dict(self.account)
        target["currency"] = "unknown"
        target["server"] = "unknown"
        result = estimate(target, self.rows)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["strict_candidate_count"], 0)
        self.assertIn("fewer_than_three_hard_pool_compatible_comparables", result["insufficiency_reasons"])
        self.assertTrue(all("target_currency_unknown" in row["reasons"] and "target_server_unknown" in row["reasons"] for row in result["rejected_by_hard_pool"]))

    def test_unknown_target_price_type_rejects_all_market_price_pools(self):
        target = dict(self.account)
        target["price_type"] = "unknown"
        rows = []
        for index, price_type in enumerate(("normal_listing", "urgent_sale", "last_public_price"), 1):
            row = dict(self.rows[index - 1])
            row["comparable_id"] = f"price_pool_{index}"
            row["price_type"] = price_type
            rows.append(row)
        result = estimate(target, rows)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["strict_candidate_count"], 0)
        self.assertEqual({row["comparable_id"] for row in result["rejected_by_hard_pool"]}, {"price_pool_1", "price_pool_2", "price_pool_3"})
        self.assertTrue(all("target_price_type_unknown" in row["reasons"] for row in result["rejected_by_hard_pool"]))

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
        for value in ("normal_listing", "urgent_sale", "last_public_price", "verified_sale"):
            self.assertEqual(normalize_price_type({"_estimator_internal": True, "price_type": value, "trade_conditions": {"price_type": "buyout"}}), value)

    def test_urgent_target_does_not_mix_normal_or_last_public_prices(self):
        target = dict(self.account)
        target["price_type"] = "urgent_sale"
        rows = []
        for index, price_type in enumerate(("urgent_sale", "urgent_sale", "urgent_sale", "normal_listing", "last_public_price"), 1):
            row = dict(self.rows[(index - 1) % 3])
            row["comparable_id"] = f"urgent_{index}"
            row["price_type"] = price_type
            rows.append(row)
        result = estimate(target, rows)
        self.assertTrue(result["eligible"])
        self.assertEqual({row["price_type"] for row in result["comparables"]}, {"urgent_sale"})
        rejected = {row["comparable_id"]: row["reasons"] for row in result["rejected_by_hard_pool"]}
        self.assertIn("price_type_mismatch", rejected["urgent_4"])
        self.assertIn("price_type_mismatch", rejected["urgent_5"])

    def test_collection_union_and_categorical_map(self):
        a = {"collection":{"graduation_rewards":["item_ultimate"],"collaboration_items":["item_collab"],"bundle_item_ids":["item_bundle"],"event_limited_item_ids":["item_event"],"graduation_reward_season_ids":["season_example"]},"map_completion":{"standard_maps":"complete","second_tier_capes":"partial"}}
        b = {"collection":{"graduation_rewards":["item_ultimate"],"collaboration_items":["item_collab"],"bundle_item_ids":["item_bundle"],"event_limited_item_ids":["item_event"],"graduation_reward_season_ids":["season_example"]},"map_completion":{"standard_maps":"complete","second_tier_capes":"partial"}}
        dimensions = score(a, b)["dimensions"]
        self.assertEqual(dimensions["collection"], WEIGHTS["collection"])
        self.assertEqual(dimensions["map_completion"], WEIGHTS["map_completion"])
        for category in ("graduation_rewards", "collaboration_items", "bundle_item_ids", "event_limited_item_ids"):
            changed = json.loads(json.dumps(b))
            changed["collection"][category] = []
            self.assertLess(score(a, changed)["dimensions"]["collection"], WEIGHTS["collection"], category)

    def test_unverified_market_evidence_is_hard_rejected(self):
        rows = [dict(x) for x in self.rows]
        rows[0]["currency_verified"] = False
        rows[0]["server_verified"] = False
        result = estimate(self.account, rows)
        self.assertFalse(result["eligible"])
        self.assertIn("currency_verified_required", result["rejected_by_hard_pool"][0]["reasons"])

    def test_classify_then_estimate_end_to_end(self):
        profile = classify({"account_id":"account_e2e","structured_claims":{"market_context":{"currency":"TWD","server":"international","valuation_date":"2026-08-16"},"base_account":{"account_type":"permanent_wingless"},"season_profiles":[{"season_id":"season_gratitude","status":"complete"}],"collection":{"owned_item_ids":["item_anniversary_bass"]},"resources":{"values":{"white_candles":100}},"bindings":{"platforms":[{"platform":"google","status":"transferable"}]},"trade_conditions":{"price_type":"asking"}}})
        result = estimate(profile, self.rows)
        self.assertEqual(result["strict_candidate_count"], 3)
        self.assertEqual(result["status"], "insufficient_comparables")

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

    def test_official_nested_accounts_form_hard_pool_but_fail_sparse_quality_gate(self):
        rows = [json.loads(line) for line in (ROOT / "data" / "comparables" / "accounts.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        target = {
            "base_account": {"account_type": "winged_or_unspecified"},
            "currency": "TWD", "server": "international", "trade_conditions": {"price_type": "asking"},
            "evidence_quality": {"listing_text": "high"}, "valuation_date": "2026-08-16",
        }
        hard = [row for row in rows if hard_pool(target, row)[0]]
        self.assertEqual(len(hard), 3)
        result = estimate(target, rows)
        self.assertEqual(result["strict_candidate_count"], 3)
        self.assertFalse(result["eligible"])
        self.assertIn("fewer_than_three_comparables_meet_similarity_and_content_thresholds", result["insufficiency_reasons"])
        self.assertNotIn("fewer_than_three_hard_pool_compatible_comparables", result["insufficiency_reasons"])

    def test_confirmed_differences_are_not_reported_as_unknown(self):
        comparable = dict(self.rows[0])
        comparable["ownership_generation"] = "second_hand"
        details = estimate(self.account, [comparable, self.rows[1], self.rows[2]])["comparables"]
        detail = next(row for row in details if row["comparable_id"] == "fixture_1")
        self.assertIn("ownership", detail["major_differences"])
        self.assertNotIn("ownership", detail["unconfirmed_dimensions"])

    def test_inventory_season_and_collection_low_scores_are_not_confirmed_differences(self):
        target = dict(self.account)
        target["collection"] = {"collaboration_items": ["item_target_collab"]}
        rows = []
        for index, source in enumerate(self.rows[:3], 1):
            row = dict(source)
            row["comparable_id"] = f"sparse_{index}"
            row["owned_item_ids"] = [f"item_other_{index}"]
            row["season_profile"] = [{"season_id": f"season_other_{index}", "status": "complete"}]
            row["complete_set_ids"] = ["set_example"]  # matching set must not make the composite a confirmed difference
            row["collection"] = {"collaboration_items": [f"item_other_collab_{index}"]}
            rows.append(row)
        detail = next(row for row in estimate(target, rows)["comparables"] if row["comparable_id"] == "sparse_1")
        for dimension in ("seasons", "items_sets", "collection"):
            self.assertNotIn(dimension, detail["major_differences"])
            self.assertIn(dimension, detail["unconfirmed_dimensions"])

    def test_shared_map_binding_and_resource_evidence_reports_confirmed_differences(self):
        rows = []
        for index, source in enumerate(self.rows[:3], 1):
            row = dict(source)
            row["comparable_id"] = f"confirmed_{index}"
            row["map_completion_ratio"] = 0.0
            row["bindings"] = {"google": "locked", "apple": "locked"}
            row["resources"] = {"white_candles": 0, "hearts": 0, "red_candles": 0}
            rows.append(row)
        detail = next(row for row in estimate(self.account, rows)["comparables"] if row["comparable_id"] == "confirmed_1")
        for dimension in ("map_completion", "bindings", "resources"):
            self.assertIn(dimension, detail["major_differences"])
            self.assertNotIn(dimension, detail["unconfirmed_dimensions"])

    def test_every_input_row_is_retained_or_has_a_selection_or_rejection_reason(self):
        rows = []
        for index in range(7):
            row = dict(self.rows[0])
            row["comparable_id"] = f"ranked_{index}"
            rows.append(row)
        type_excluded = dict(self.rows[0])
        type_excluded["comparable_id"] = "account_type_excluded"
        type_excluded["base_account_type"] = "wingless"
        rows.append(type_excluded)
        result = estimate(self.account, rows)
        tracked = set()
        for key in ("comparables", "rejected_by_hard_pool", "rejected_by_quality", "rejected_by_selection"):
            tracked.update(row["comparable_id"] for row in result[key])
        self.assertEqual(tracked, {row["comparable_id"] for row in rows})
        reasons = {row["comparable_id"]: row["reasons"] for row in result["rejected_by_selection"]}
        self.assertIn("account_type_not_selected", reasons["account_type_excluded"])
        self.assertEqual(sum("lower_rank_not_retained" in value for value in reasons.values()), 2)

    def test_history_only_cli_input_is_rejected(self):
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "estimate" / "estimate.py"), str(ROOT / "tests" / "fixtures" / "estimate-account.json"), str(ROOT / "data" / "comparables" / "histories.jsonl")],
            cwd=ROOT, text=True, capture_output=True, check=False,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("history-only JSONL is not accepted", proc.stderr)


if __name__ == "__main__":
    unittest.main()
