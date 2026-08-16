import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "modeling"))
from evaluate import evaluate
from train_elastic_net import _fit_with_inner_groups, _frame, classify_columns, feature_mapping, minimum_rows, portable_predict_log, train


class ElasticNetModelingTest(unittest.TestCase):
    def write_rows(self, rows):
        temporary = tempfile.TemporaryDirectory(prefix="sky-model-test-", dir=ROOT.parent)
        self.addCleanup(temporary.cleanup)
        directory = Path(temporary.name)
        (directory / "manifest.json").write_text("{}\n", encoding="utf-8")
        path = directory / "vectors.jsonl"
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        return path

    def row(self, n, line="normal_listing"):
        return {
            "account_id": f"account_{n:04d}", "cluster_id": f"cluster_{n:04d}",
            "price_line": line, "price_twd": 5000 + n * 15,
            "feature_vector": {
                "base": {"account_type": "wingless" if n % 2 else "winged"},
                "resources": {"white_candles": n, "hearts": None if n % 3 == 0 else n * 2},
                "collection": {"item_sky_001": "owned" if n % 2 else "unknown"},
            },
        }

    def test_under_threshold_is_fail_closed_and_never_trains(self):
        result = train(self.write_rows([self.row(n) for n in range(3)]), "normal_listing")
        self.assertEqual(result["status"], "insufficient_training_data")
        self.assertIsNone(result["artifact"])
        self.assertEqual(result["training"]["minimum_rows"], 100)
        self.assertFalse(result["training"]["threshold_met"])
        self.assertEqual(result["input_snapshot_paths"], ["vectors.jsonl"])
        self.assertEqual(len(result["input_snapshot_sha256"]), 64)

    def test_price_lines_are_separate(self):
        result = train(self.write_rows([self.row(1), self.row(2, "urgent_sale")]), "urgent_sale")
        self.assertEqual(result["training"]["eligible_rows"], 1)
        self.assertEqual(result["price_line"], "urgent_sale")

    def test_minimum_uses_feature_groups(self):
        self.assertEqual(minimum_rows(1), 100)
        self.assertEqual(minimum_rows(14), 140)

    def test_evaluator_accepts_fail_closed_artifact(self):
        artifact = train(self.write_rows([self.row(1)]), "normal_listing")
        result = evaluate(artifact)
        self.assertTrue(result["valid"])
        self.assertEqual(result["status"], "insufficient_training_data")

    def test_grouped_nested_cv_exports_plain_json_when_threshold_is_met(self):
        artifact = train(self.write_rows([self.row(n) for n in range(100)]), "normal_listing")
        self.assertEqual(artifact["status"], "trained")
        self.assertTrue(artifact["training"]["baseline_beaten"])
        self.assertEqual(artifact["training"]["folds"], 5)
        contract = artifact["prediction_contract"]
        self.assertEqual(contract["kind"], "additive_log_price")
        self.assertIsInstance(contract["intercept"], float)
        self.assertIsInstance(contract["coefficients"], dict)
        self.assertEqual(contract["feature_order"], artifact["artifact"]["model"]["feature_order"])
        self.assertEqual(contract["continuous"], artifact["artifact"]["model"]["continuous"])
        continuous = contract["continuous"]
        self.assertEqual(set(continuous["columns"]), set(continuous["means"]))
        self.assertEqual(set(continuous["columns"]), set(continuous["scales"]))
        self.assertIn("resources.hearts", continuous["missing_indicator_scaling"])
        self.assertEqual(
            continuous["missing_indicator_means"]["resources.hearts"],
            continuous["missing_indicator_scaling"]["resources.hearts"]["mean"],
        )
        self.assertEqual(
            continuous["missing_indicator_scales"]["resources.hearts"],
            continuous["missing_indicator_scaling"]["resources.hearts"]["scale"],
        )
        self.assertNotIn("pickle", json.dumps(artifact).lower())
        self.assertTrue(evaluate(artifact)["valid"])

    def test_portable_contract_matches_sklearn_for_present_and_missing_values(self):
        # The fixture has a numeric hearts field with both present and missing
        # values, forcing SimpleImputer's indicator through StandardScaler.
        rows = [
            {"price": 5000 + n * 15, "group": f"g{n}", "features": feature_mapping(self.row(n))}
            for n in range(100)
        ]
        numeric, categorical = classify_columns(rows)
        frame = _frame(rows, numeric, categorical)
        import numpy as np
        pipe = _fit_with_inner_groups(frame, np.log(np.asarray([row["price"] for row in rows], dtype=float)), [row["group"] for row in rows], numeric, categorical)
        from train_elastic_net import _export_plain_json_model, additive_prediction_contract
        contract = additive_prediction_contract(_export_plain_json_model(pipe, numeric, categorical), numeric, categorical)
        for index in (1, 3):  # 1 is present; 3 is intentionally missing hearts.
            sklearn_value = float(pipe.predict(frame.iloc[[index]])[0])
            portable_value = portable_predict_log(contract, rows[index]["features"])
            self.assertAlmostEqual(sklearn_value, portable_value, places=10)

    def test_pure_numeric_feature_training_has_empty_categorical_vocabulary(self):
        rows = [
            {
                "account_id": f"numeric_{n:04d}", "cluster_id": f"numeric_group_{n:04d}",
                "price_line": "normal_listing", "price_twd": 5000 + n * 25,
                "feature_vector": {"resources": {"white_candles": n, "hearts": n * 2}},
            }
            for n in range(100)
        ]
        artifact = train(self.write_rows(rows), "normal_listing")
        self.assertEqual(artifact["status"], "trained")
        self.assertEqual(artifact["feature_schema"]["categorical_columns"], [])
        self.assertEqual(artifact["prediction_contract"]["categorical_vocabulary"], {})

    def test_unknown_is_not_coerced_to_numeric_zero(self):
        artifact = train(self.write_rows([self.row(1)]), "normal_listing")
        self.assertEqual(artifact["prediction_contract"]["unknown_handling"], "missing_mask")

    def test_structured_lists_use_stable_identifiers_not_dict_strings(self):
        mapped = feature_mapping({"feature_vector": {
            "bindings": {"platforms": [
                {"platform": "google", "status": "available", "evidence_state": "image_confirmed"},
                {"platform": "apple", "status": "unknown", "evidence_state": "unknown"},
            ]},
            "season_profiles": [
                {"season_id": "season_aurora", "status": "complete", "pass_owned": "yes"},
            ],
        }})
        self.assertEqual(mapped["bindings.platforms.google.status"], "available")
        self.assertEqual(mapped["season_profiles.season_aurora.status"], "complete")
        self.assertFalse(any("{'" in key or "{'" in str(value) for key, value in mapped.items()))

    def test_formal_account_0165_cannot_bypass_item_gating_through_aggregates(self):
        vectors = (ROOT / "data/modeling/account-item-vectors.jsonl").read_text(encoding="utf-8").splitlines()
        row = next(json.loads(line) for line in vectors if json.loads(line)["account_id"] == "account_0165")
        self.assertTrue(any(state["item_id"] == "item_moomin_ears" and not state["model_feature"] for state in row["item_states"]))
        mapped = feature_mapping(row)
        serialized = json.dumps(mapped, ensure_ascii=False, sort_keys=True)
        self.assertNotIn("item_moomin_ears", serialized)
        self.assertNotIn("item_days_mischief_bat_cape", serialized)
        self.assertFalse(any(key.startswith("items.item_") for key in mapped))
        # Legacy aggregate rows have no explicit eligibility verdict, so they
        # are fail-closed.  Regenerated rows may expose only model_feature=true
        # sets after every required member is canonical and explicitly known.
        self.assertFalse(any(key.startswith("item_sets.") for key in mapped))

    def test_ineligible_set_aggregate_is_not_a_training_feature(self):
        mapped = feature_mapping({"feature_vector": {"item_sets": [
            {
                "set_id": "set_sensitive", "owned_item_ids": ["item_unverified"],
                "confirmed_missing_item_ids": [], "member_count": 1,
                "known_member_count": 1, "completion_ratio": 1.0,
                "is_complete": True, "model_feature": False,
            },
            {
                "set_id": "set_verified", "owned_item_ids": ["item_verified"],
                "confirmed_missing_item_ids": [], "member_count": 1,
                "known_member_count": 1, "completion_ratio": 1.0,
                "is_complete": True, "model_feature": True,
            },
        ]}})
        self.assertFalse(any(key.startswith("item_sets.set_sensitive.") for key in mapped))
        self.assertIn("item_sets.set_verified.completion_ratio", mapped)
        self.assertNotIn("item_unverified", json.dumps(mapped, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
