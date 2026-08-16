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
        # Flat legacy fixtures must state the same transaction contract as a
        # formal valuation input; the estimator never infers it from absence.
        self.account.update({"offer_kind": "seller_listing", "entity_kind": "single_account"})
        for row in self.rows:
            row.update({"offer_kind": "seller_listing", "entity_kind": "single_account"})

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

    def test_comparable_independence_rejects_all_positive_identity_matches(self):
        target = dict(self.account)
        target.update({
            "account_id": "account_target",
            "source_listing_ids": ["listing_target"],
            "duplicate_cluster_id": "cluster_target",
        })
        cases = (
            ("same_account_id", {"account_id": "account_target"}),
            ("source_listing_id_overlap", {"account_id": "account_other", "source_listing_ids": ["listing_target"]}),
            ("duplicate_cluster_id_match", {"account_id": "account_other", "source_listing_ids": ["listing_other"], "duplicate_cluster_id": "cluster_target"}),
        )
        for expected_reason, identity in cases:
            with self.subTest(reason=expected_reason):
                comparable = dict(self.rows[0])
                comparable.update(identity)
                accepted, reasons = hard_pool(target, comparable)
                self.assertFalse(accepted)
                self.assertIn(expected_reason, reasons)

    def test_comparable_independence_does_not_treat_distinct_or_unknown_ids_as_same(self):
        target = dict(self.account)
        target.update({
            "account_id": "account_target",
            "source_listing_ids": ["listing_target"],
            "duplicate_cluster_id": "unknown",
        })
        comparable = dict(self.rows[0])
        comparable.update({
            "account_id": "account_other",
            "source_listing_ids": ["listing_other"],
            "duplicate_cluster_id": "unknown",
        })
        accepted, reasons = hard_pool(target, comparable)
        self.assertTrue(accepted)
        self.assertFalse({"same_account_id", "source_listing_id_overlap", "duplicate_cluster_id_match"} & set(reasons))

    def test_price_semantic_review_and_brokerage_are_hard_rejected_for_target(self):
        target = dict(self.account)
        target["price_semantic_review"] = {
            "review_status": "needs_review",
            "brokerage_included": True,
        }
        accepted, reasons = hard_pool(target, self.rows[0])
        self.assertFalse(accepted)
        self.assertIn("target_price_semantic_review_not_approved", reasons)
        self.assertIn("target_brokerage_included", reasons)

    def test_official_history_0036_brokerage_price_is_hard_rejected(self):
        rows = [json.loads(line) for line in (ROOT / "data" / "comparables" / "accounts.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        comparable = next(row for row in rows if row["history_id"] == "history_0036")
        target = {
            "base_account": {"account_type": "winged_or_unspecified"},
            "currency": "TWD",
            "server": "international",
            "trade_conditions": {"offer_kind": "seller_listing", "entity_kind": "single_account", "price_type": "asking"},
        }
        accepted, reasons = hard_pool(target, comparable)
        self.assertFalse(accepted)
        self.assertIn("price_semantic_review_not_approved", reasons)
        self.assertIn("brokerage_included", reasons)

    def test_listing_0388_installment_surcharge_is_hard_rejected(self):
        rows = [json.loads(line) for line in (ROOT / "data" / "comparables" / "accounts.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        comparable = dict(next(row for row in rows if row["history_id"] == "history_0068"))
        comparable["price_semantic_review"] = {
            "urgency": "unknown", "multi_price": True,
            "evidence_state": "text_claim", "review_status": "needs_review",
            "reason_codes": ["multiple_price_terms", "installment_price_variants"],
        }
        target = {
            "base_account": {"account_type": "winged_or_unspecified"},
            "currency": "TWD",
            "server": "international",
            "trade_conditions": {"offer_kind": "seller_listing", "entity_kind": "single_account", "price_type": "asking"},
        }
        accepted, reasons = hard_pool(target, comparable)
        self.assertFalse(accepted)
        self.assertIn("price_semantic_review_not_approved", reasons)
        self.assertIn("multi_price", reasons)

    def test_identity_rejections_are_covered_by_estimate_output_accounting(self):
        target = dict(self.account)
        target.update({
            "account_id": "account_target",
            "source_listing_ids": ["listing_target"],
            "duplicate_cluster_id": "cluster_target",
        })
        rows = []
        for index, (field, value, expected_reason) in enumerate((
            ("account_id", "account_target", "same_account_id"),
            ("source_listing_ids", ["listing_target"], "source_listing_id_overlap"),
            ("duplicate_cluster_id", "cluster_target", "duplicate_cluster_id_match"),
        ), 1):
            row = dict(self.rows[index - 1])
            row["comparable_id"] = f"identity_{index}"
            row["account_id"] = "account_other"
            row["source_listing_ids"] = [f"listing_other_{index}"]
            row["duplicate_cluster_id"] = f"cluster_other_{index}"
            row[field] = value
            row["expected_identity_rejection"] = expected_reason
            rows.append(row)
        result = estimate(target, rows)
        rejected = {row["comparable_id"]: row["reasons"] for row in result["rejected_by_hard_pool"]}
        self.assertEqual(set(rejected), {row["comparable_id"] for row in rows})
        for row in rows:
            self.assertIn(row["expected_identity_rejection"], rejected[row["comparable_id"]])
        tracked = set()
        for key in ("comparables", "rejected_by_hard_pool", "rejected_by_quality", "rejected_by_selection"):
            tracked.update(row["comparable_id"] for row in result[key])
        self.assertEqual(tracked, {row["comparable_id"] for row in rows})

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

    def test_target_must_explicitly_be_a_seller_single_account_listing(self):
        for field, invalid_values, expected_reason in (
            ("offer_kind", ("unknown", "buyer_budget", "service", "exchange"), "target_not_seller_listing"),
            ("entity_kind", ("unknown", "bundle", "service"), "target_not_single_account"),
        ):
            for value in invalid_values:
                with self.subTest(field=field, value=value):
                    target = dict(self.account)
                    target[field] = value
                    result = estimate(target, self.rows)
                    self.assertFalse(result["eligible"])
                    self.assertEqual(result["strict_candidate_count"], 0)
                    self.assertTrue(all(expected_reason in row["reasons"] for row in result["rejected_by_hard_pool"]))

    def test_external_adapter_marker_cannot_override_nested_target_trade_conditions(self):
        target = dict(self.account)
        target["_estimator_internal"] = True
        target["trade_conditions"] = {"offer_kind": "buyer_budget", "entity_kind": "bundle", "price_type": "asking"}
        result = estimate(target, self.rows)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["strict_candidate_count"], 0)
        self.assertTrue(all("target_not_seller_listing" in row["reasons"] for row in result["rejected_by_hard_pool"]))
        self.assertTrue(all("target_not_single_account" in row["reasons"] for row in result["rejected_by_hard_pool"]))

    def test_unknown_comparable_trade_conditions_are_not_admitted(self):
        rows = []
        for index, source in enumerate(self.rows[:3], 1):
            row = dict(source)
            row["comparable_id"] = f"unknown_trade_{index}"
            row["offer_kind"] = "unknown"
            row["entity_kind"] = "unknown"
            rows.append(row)
        result = estimate(self.account, rows)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["strict_candidate_count"], 0)
        for row in result["rejected_by_hard_pool"]:
            self.assertIn("not_seller_listing", row["reasons"])
            self.assertIn("not_single_account", row["reasons"])

    def test_nested_trade_conditions_are_promoted_before_target_hard_pool(self):
        target = {
            "base_account": {"account_type": "permanent_wingless"},
            "currency": "TWD", "server": "international",
            "trade_conditions": {"offer_kind": "seller_listing", "entity_kind": "single_account", "price_type": "asking"},
        }
        flat = adapt_profile(target)
        self.assertIs(adapt_profile(flat), flat)
        self.assertEqual(flat["offer_kind"], "seller_listing")
        self.assertEqual(flat["entity_kind"], "single_account")
        self.assertTrue(hard_pool(target, self.rows[0])[0])

    def test_canonical_nested_profile_and_history_adapter(self):
        account = {
            "base_account": {"account_type": "permanent_wingless"},
            "season_profiles": [{"season_id": "season_example", "status": "complete"}],
            "collection": {"owned_item_ids": ["item_example_a"], "item_set_profiles": [{"set_id":"set_example", "is_complete": True}]},
            "resources": {"values": {"white_candles": 100}},
            "bindings": {"platforms": [{"platform":"google", "status":"transferable"}], "risk_state":"clean"},
            "ownership_history":"first_hand", "trade_conditions":{"offer_kind":"seller_listing", "entity_kind":"single_account", "price_type":"asking"},
            "evidence_quality":{"listing_text":"high"}, "currency":"TWD", "server":"international"
        }
        history = {**account, "history_id":"history_fixture", "selected_price_twd":9000, "post_date":"2026-08-01"}
        flat = adapt_profile(account)
        self.assertEqual(flat["base_account_type"], "permanent_wingless")
        self.assertEqual(flat["complete_set_ids"], ["set_example"])
        self.assertEqual(flat["bindings"], {"google":"transferable"})
        self.assertEqual(flat["offer_kind"], "seller_listing")
        self.assertEqual(flat["entity_kind"], "single_account")
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
            self.assertEqual(normalize_price_type({"_estimator_internal": True, "price_type": value, "trade_conditions": {"price_type": "buyout"}}), "unknown")

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
        profile = classify({"account_id":"account_e2e","structured_claims":{"market_context":{"currency":"TWD","server":"international","valuation_date":"2026-08-16"},"base_account":{"account_type":"permanent_wingless"},"season_profiles":[{"season_id":"season_gratitude","status":"complete"}],"collection":{"owned_item_ids":["item_anniversary_bass"]},"resources":{"values":{"white_candles":100}},"bindings":{"platforms":[{"platform":"google","status":"transferable"}]},"trade_conditions":{"offer_kind":"seller_listing","entity_kind":"single_account","price_type":"asking"}}})
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
            "currency": "TWD", "server": "international", "trade_conditions": {"offer_kind": "seller_listing", "entity_kind": "single_account", "price_type": "asking"},
            "evidence_quality": {"listing_text": "high"}, "valuation_date": "2026-08-16",
        }
        hard = [row for row in rows if hard_pool(target, row)[0]]
        self.assertEqual(len(hard), 2)
        result = estimate(target, rows)
        self.assertEqual(result["strict_candidate_count"], 2)
        self.assertFalse(result["eligible"])
        self.assertIn("fewer_than_three_comparables_meet_similarity_and_content_thresholds", result["insufficiency_reasons"])
        self.assertIn("fewer_than_three_hard_pool_compatible_comparables", result["insufficiency_reasons"])

    def test_winged_or_unspecified_is_unknown_not_a_similarity_match(self):
        target = {"base_account": {"account_type": "winged_or_unspecified"}}
        comparable = {"base_account": {"account_type": "winged_or_unspecified"}}
        result = score(target, comparable)
        self.assertEqual(result["dimensions"]["account_type"], 0.0)
        self.assertFalse(result["known_dimensions"]["account_type"])

    def test_formal_three_do_not_gain_shared_unknown_account_type_points(self):
        rows = [json.loads(line) for line in (ROOT / "data" / "comparables" / "accounts.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        strict_ids = {"history_0068", "history_0085", "history_recovered_0792"}
        strict_rows = [row for row in rows if row.get("history_id") in strict_ids]
        self.assertEqual(len(strict_rows), 3)
        for left in strict_rows:
            for right in strict_rows:
                if left is right:
                    continue
                result = score(left, right)
                self.assertEqual(result["dimensions"]["account_type"], 0.0)
                self.assertFalse(result["known_dimensions"]["account_type"])

    def test_formal_history_0068_approximate_resources_are_not_numeric_evidence(self):
        rows = [json.loads(line) for line in (ROOT / "data" / "comparables" / "accounts.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        approximate = next(row for row in rows if row["history_id"] == "history_0068")
        target = {
            "resources": {"values": dict(approximate["resources"]["values"])},
            "field_evidence": {
                f"resources.values.{key}": {"claim_kind": "exact"}
                for key in approximate["resources"]["values"]
            },
        }
        result = score(target, approximate)
        self.assertEqual(result["dimensions"]["resources"], 0.0)
        self.assertFalse(result["known_dimensions"]["resources"])

    def test_explicit_exact_resources_remain_numeric_similarity_evidence(self):
        values = {"white_candles": 100, "hearts": 20, "red_candles": 3, "season_candles": 5}
        evidence = {f"resources.values.{key}": {"claim_kind": "exact"} for key in values}
        result = score(
            {"resources": {"values": values}, "field_evidence": evidence},
            {"resources": {"values": dict(values)}, "field_evidence": dict(evidence)},
        )
        self.assertEqual(result["dimensions"]["resources"], WEIGHTS["resources"])
        self.assertTrue(result["known_dimensions"]["resources"])

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
