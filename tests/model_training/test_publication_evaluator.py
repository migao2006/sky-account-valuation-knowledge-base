import math
import sys
import unittest
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "estimate"))

from tools.modeling.publication_dataset import freeze_synthetic_for_test, split_synthetic_for_test  # noqa: E402
from tools.modeling.publication_evaluator import _gate_reasons, _runtime_replay_metrics, _sha256, build, evaluate, evaluate_synthetic_for_test  # noqa: E402
from tools.modeling.publication_runtime import PublicationRuntimeError, build_expected_artifact  # noqa: E402
from tools.modeling.catalog_provenance import catalog_provenance, read_jsonl  # noqa: E402
from tools.modeling.market_feature_contract import VERSION  # noqa: E402
from tools.estimate.model_estimator import _predict_elastic_net  # noqa: E402
from modeling.train_elastic_net import train_publication_runtime  # noqa: E402
from tools.validate.schema_validator import OfflineSchemaValidator  # noqa: E402


class PublicationEvaluatorTests(unittest.TestCase):
    def frozen_fixture(self, *, trend=False):
        rows = []
        vectors = []
        for number in range(400):
            account = f"account_{number:04d}"
            day = date(2024, 1, 1) + timedelta(days=number if number < 300 else number + 100)
            residual = -10 if number % 10 == 0 else (10 if number % 10 == 1 else 0)
            rows.append({
                "cleaned_price_id": f"clean_{number:04d}", "history_id": f"history_{number:04d}",
                "account_id": account, "cluster_id": f"cluster_{number:04d}",
                "currency": "TWD", "server": "international", "price_line": "normal_listing",
                "selected_price_twd": (5000 + number * 3 + residual) if trend else 5000 + number * 10,
                "post_date": day.isoformat() if trend else ("2025-01-01" if number < 300 else "2025-02-01"), "date_verified": True,
            })
            vectors.append({"account_id": account, "catalog_provenance": {}, "feature_groups": {"synthetic": {"signal": number}}})
        return freeze_synthetic_for_test(rows, vectors, {}, [])

    def signed_v1_fixture(self):
        manifest = self.frozen_fixture(trend=True)
        states = [{"item_id": item["item_id"], "state": "unknown", "evidence_state": "unknown", "conflict": False}
                  for item in read_jsonl(ROOT / "knowledge/items/items.jsonl")]
        platforms = [{"platform": name, "status": "unknown"} for name in
                     ("google", "apple", "game_center", "facebook", "nintendo", "playstation", "steam", "huawei", "twitter")]
        for number, row in enumerate(manifest["dataset_rows"]):
            row["feature_payload"] = {
                "account_id": row["account_id"], "catalog_provenance": catalog_provenance(ROOT),
                "feature_contract_version": VERSION,
                "feature_groups": {
                    "base_account": {"account_type": "winged" if number % 2 else "wingless", "wing_state": "winged", "special_appearance": []},
                    "season_profiles": [], "item_sets": [], "collection": {"bundle_claim_level": "unknown"},
                    "resources": {"values": {"white_candles": number, "hearts": None, "red_candles": None, "season_candles": None}},
                    "map_completion": {"standard_maps": "unknown", "second_tier_capes": "unknown"},
                    "bindings": {"risk_state": "low", "platforms": platforms}, "ownership_history": "unknown",
                }, "item_states": states,
            }
            row["row_sha256"] = _sha256({key: value for key, value in row.items() if key != "row_sha256"})
        manifest["lineage_mode"] = "production_signed"
        manifest["dataset_sha256"] = _sha256(manifest["dataset_rows"])
        return manifest

    def test_formal_report_is_replayed_and_fail_closed(self):
        report = build(ROOT)
        self.assertEqual(report["status"], "not_ready")
        self.assertIs(report["publication_ready"], False)
        self.assertIs(report["artifact_publication_fields_consulted"], False)
        self.assertIsNone(report["metrics"])
        self.assertIn("no_market_pool_meets_300_train_100_time_forward_holdout", report["blocking_reasons"])

    def test_formal_empty_publication_trainer_emits_schema_valid_insufficient_envelope(self):
        artifact = train_publication_runtime(ROOT)
        self.assertEqual(artifact["status"], "insufficient_training_data")
        validator = OfflineSchemaValidator(ROOT / "schemas")
        self.assertEqual(validator.validate(artifact, ROOT / "schemas/modeling/elastic-net-artifact.schema.json"), [])

    def test_sufficient_frozen_fixture_replays_train_only_metrics_but_cannot_publish(self):
        report = evaluate_synthetic_for_test(self.frozen_fixture())
        self.assertEqual(report["status"], "evaluation_required")
        self.assertFalse(report["publication_ready"])
        self.assertEqual(report["metrics"]["replay_kind"], "evaluator_owned_train_only_signed_account_feature_linear")
        metric = report["metrics"]["market_pools"][0]
        self.assertEqual((metric["training_row_count"], metric["holdout_row_count"]), (300, 100))
        self.assertIn("TWD:international:normal_listing:prediction_interval_coverage_outside_75_85_percent", report["blocking_reasons"])

    def test_feature_model_can_pass_replay_gates_but_cannot_unlock_runtime(self):
        report = evaluate_synthetic_for_test(self.frozen_fixture(trend=True))
        self.assertEqual(report["status"], "evaluation_required")
        self.assertFalse(report["publication_ready"])
        self.assertEqual(report["artifact_bindings"], [])
        self.assertEqual(report["blocking_reasons"], ["runtime_compatible_feature_artifact_required"])
        self.assertEqual(report["metrics"]["market_pools"][0]["model"]["model_type"], "publication_feature_linear_evaluator_only")

    def test_external_artifact_predictions_and_forged_split_are_rejected(self):
        manifest = self.frozen_fixture(trend=True)
        forged = {
            "market_pools": [{
                "currency": "TWD", "server": "international", "price_line": "normal_listing",
                "cut_date": "2025-01-01", "training_cluster_ids": ["cluster_0300"],
                "holdout_cluster_ids": ["cluster_0300"],
            }]
        }
        report = evaluate_synthetic_for_test(manifest, forged, artifact={"publication_gate": "passed"}, predictions=[{"price": 1}])
        self.assertEqual(report["status"], "failed")
        self.assertIn("submitted_split_cluster_overlap", report["blocking_reasons"])
        self.assertIn("submitted_split_date_inversion", report["blocking_reasons"])
        self.assertIn("external_model_artifact_rejected", report["blocking_reasons"])
        self.assertIn("external_predictions_rejected", report["blocking_reasons"])

    def test_underpowered_subgroup_is_explicitly_blocked(self):
        manifest = self.frozen_fixture(trend=True)
        for row in manifest["dataset_rows"][-10:]:
            row["evaluation_subgroup"] = "rare"
            payload = {key: value for key, value in row.items() if key != "row_sha256"}
            row["row_sha256"] = _sha256(payload)
        manifest["dataset_sha256"] = _sha256(manifest["dataset_rows"])
        report = evaluate_synthetic_for_test(manifest)
        self.assertEqual(report["status"], "evaluation_required")
        self.assertIn("TWD:international:normal_listing:subgroup_under_30:rare", report["blocking_reasons"])

    def test_holdout_only_subgroup_is_out_of_distribution(self):
        manifest = self.frozen_fixture(trend=True)
        for row in manifest["dataset_rows"][-100:]:
            row["evaluation_subgroup"] = "holdout_only"
            payload = {key: value for key, value in row.items() if key != "row_sha256"}
            row["row_sha256"] = _sha256(payload)
        manifest["dataset_sha256"] = _sha256(manifest["dataset_rows"])
        report = evaluate_synthetic_for_test(manifest)
        self.assertIn(
            "TWD:international:normal_listing:coverage_qualified_share_below_80_percent",
            report["blocking_reasons"],
        )

    def test_subgroup_mdape_threshold_is_enforced(self):
        manifest = self.frozen_fixture(trend=True)
        for row in manifest["dataset_rows"][-30:]:
            row["evaluation_subgroup"] = "bad_error_group"
            row["selected_price_twd"] *= 4
            payload = {key: value for key, value in row.items() if key != "row_sha256"}
            row["row_sha256"] = _sha256(payload)
        manifest["dataset_sha256"] = _sha256(manifest["dataset_rows"])
        report = evaluate_synthetic_for_test(manifest)
        self.assertIn(
            "TWD:international:normal_listing:subgroup_mdape_above_25_percent:bad_error_group",
            report["blocking_reasons"],
        )

    def test_rehashed_synthetic_target_or_subgroup_cannot_use_production_evaluator(self):
        manifest = self.frozen_fixture(trend=True)
        expected = deepcopy(manifest)
        row = manifest["dataset_rows"][-1]
        row["selected_price_twd"] = 1
        row["evaluation_subgroup"] = "forged"
        payload = {key: value for key, value in row.items() if key != "row_sha256"}
        row["row_sha256"] = _sha256(payload)
        manifest["dataset_sha256"] = _sha256(manifest["dataset_rows"])
        with patch("tools.modeling.publication_evaluator.build_publication_dataset", return_value=(expected, {})):
            with self.assertRaisesRegex(Exception, "dataset_manifest_differs_from_deterministic_root_replay"):
                evaluate(manifest, root=ROOT)

    def test_test_only_synthetic_manifest_cannot_generate_a_runtime_artifact(self):
        manifest = self.frozen_fixture(trend=True)
        split = manifest["market_pools"][0]
        with self.assertRaisesRegex(PublicationRuntimeError, "production_signed"):
            build_expected_artifact(ROOT, manifest, split)

    def test_runtime_contract_supports_urgent_sale(self):
        manifest = self.frozen_fixture(trend=True)
        manifest["lineage_mode"] = "production_signed"
        for row in manifest["dataset_rows"]:
            row["price_line"] = "urgent_sale"
            row["row_sha256"] = _sha256({key: value for key, value in row.items() if key != "row_sha256"})
        manifest["dataset_sha256"] = _sha256(manifest["dataset_rows"])
        pool = split_synthetic_for_test(manifest)["market_pools"][0]
        artifact = build_expected_artifact(ROOT, manifest, pool)
        self.assertEqual(artifact["price_line"], "urgent_sale")
        self.assertIn("verified_sale_is_evidence_only_not_estimator", artifact["limitations"])

    def test_runtime_artifact_fit_is_invariant_to_holdout_targets(self):
        # This intentionally uses the test-only shape only after changing its
        # lineage marker; it exercises the pure fitter, not publication.  A
        # holdout target may alter metrics but must never alter model bytes.
        manifest = self.frozen_fixture(trend=True)
        manifest["lineage_mode"] = "production_signed"
        pool = split_synthetic_for_test(manifest)["market_pools"][0]
        first = build_expected_artifact(ROOT, manifest, pool)
        for row in manifest["dataset_rows"]:
            if row["cluster_id"] in set(pool["holdout_cluster_ids"]):
                row["selected_price_twd"] *= 50
        second = build_expected_artifact(ROOT, manifest, pool)
        self.assertEqual(first["prediction_contract"], second["prediction_contract"])

    def test_runtime_categorical_only_fixture_is_safe(self):
        manifest = self.frozen_fixture(trend=True)
        manifest["lineage_mode"] = "production_signed"
        for number, vector in enumerate(manifest["dataset_rows"]):
            vector["feature_payload"]["feature_groups"] = {"base": {"tier": "a" if number % 2 else "b"}}
            vector["row_sha256"] = _sha256({key: value for key, value in vector.items() if key != "row_sha256"})
        manifest["dataset_sha256"] = _sha256(manifest["dataset_rows"])
        pool = split_synthetic_for_test(manifest)["market_pools"][0]
        try:
            artifact = build_expected_artifact(ROOT, manifest, pool)
        except (PublicationRuntimeError, ValueError):
            return  # explicit fail-closed is an allowed categorical-only outcome
        self.assertEqual(artifact["feature_schema"]["continuous_columns"], [])
        self.assertTrue(artifact["feature_schema"]["categorical_columns"])

    def test_runtime_interval_contract_equals_evaluator_interval(self):
        manifest = self.frozen_fixture(trend=True)
        manifest["lineage_mode"] = "production_signed"
        pool = split_synthetic_for_test(manifest)["market_pools"][0]
        for row in manifest["dataset_rows"]:
            if row["cluster_id"] in set(pool["holdout_cluster_ids"]):
                row["feature_payload"]["feature_groups"]["synthetic"]["signal"] %= 300
        rows = manifest["dataset_rows"]
        metric, artifact = _runtime_replay_metrics(ROOT, manifest, rows, pool)
        contract = artifact["artifact"]["runtime_interval_contract"]
        self.assertEqual(metric["interval"]["residual_lower_twd"], contract["residual_lower_twd"])
        self.assertEqual(metric["interval"]["residual_upper_twd"], contract["residual_upper_twd"])

    def test_runtime_ood_holdout_coverage_blocks_publication(self):
        manifest = self.frozen_fixture(trend=True)
        manifest["lineage_mode"] = "production_signed"
        pool = split_synthetic_for_test(manifest)["market_pools"][0]
        holdout_ids = set(pool["holdout_cluster_ids"])
        for number, row in enumerate(row for row in manifest["dataset_rows"] if row["cluster_id"] in holdout_ids):
            if number < 30:
                row["feature_payload"]["feature_groups"]["synthetic"]["signal"] = number
        metric, _ = _runtime_replay_metrics(ROOT, manifest, manifest["dataset_rows"], pool)
        self.assertEqual(metric["runtime_supported_case_share"], .30)
        self.assertIn("runtime_supported_holdout_share_below_80_percent", _gate_reasons(metric))

    def test_runtime_unknown_category_normalizes_to_unknown_token(self):
        manifest = self.frozen_fixture(trend=True)
        manifest["lineage_mode"] = "production_signed"
        pool = split_synthetic_for_test(manifest)["market_pools"][0]
        for row in manifest["dataset_rows"]:
            row["feature_payload"]["feature_groups"]["synthetic"]["state"] = "unknown"
        artifact = build_expected_artifact(ROOT, manifest, pool)
        self.assertEqual(artifact["feature_schema"]["runtime_domain"]["categorical"]["synthetic.state"], ["__unknown__"])

    def test_runtime_train_residuals_preserve_item_set_projection(self):
        manifest = self.frozen_fixture(trend=True)
        manifest["lineage_mode"] = "production_signed"
        pool = split_synthetic_for_test(manifest)["market_pools"][0]
        for row in manifest["dataset_rows"]:
            row["feature_payload"]["feature_groups"]["item_sets"] = [{"set_id": "set_example", "model_feature": True, "completion_ratio": .5}]
        artifact = build_expected_artifact(ROOT, manifest, pool)
        self.assertIn("item_sets.set_example.completion_ratio", artifact["prediction_contract"]["continuous"]["columns"])

    def test_signed_v1_train_evaluator_and_estimator_predict_same_contract(self):
        manifest = self.signed_v1_fixture()
        pool = split_synthetic_for_test(manifest)["market_pools"][0]
        holdout_ids = set(pool["holdout_cluster_ids"])
        for row in manifest["dataset_rows"]:
            if row["cluster_id"] in holdout_ids:
                row["feature_payload"]["feature_groups"]["resources"]["values"]["white_candles"] %= 300
                row["row_sha256"] = _sha256({key: value for key, value in row.items() if key != "row_sha256"})
        manifest["dataset_sha256"] = _sha256(manifest["dataset_rows"])
        metric, artifact = _runtime_replay_metrics(ROOT, manifest, manifest["dataset_rows"], pool)
        self.assertEqual(metric["runtime_supported_row_case_share"], 1.0)
        row = next(row for row in manifest["dataset_rows"] if row["cluster_id"] in holdout_ids)
        from tools.modeling.publication_runtime import predict_log
        runtime_log = predict_log(artifact["prediction_contract"], row, artifact["feature_schema"]["runtime_domain"], ROOT)
        account = {**row["feature_payload"], "currency": "TWD", "server": "international", "review_status": "approved",
                   "trade_conditions": {"offer_kind": "seller_listing", "entity_kind": "single_account", "price_type": "normal_listing"},
                   "evidence_quality": {"listing_text": "high"}}
        estimator_contract = {**artifact["prediction_contract"], "runtime_domain": artifact["feature_schema"]["runtime_domain"]}
        estimator_log, _, reasons = _predict_elastic_net(estimator_contract, account, {}, root=ROOT)
        self.assertEqual(reasons, [])
        self.assertTrue(math.isclose(runtime_log, estimator_log, rel_tol=0, abs_tol=1e-10))
        bad = deepcopy(account)
        bad["feature_groups"]["base_account"]["account_type"] = "unknown"
        with self.assertRaisesRegex(PublicationRuntimeError, "out_of_distribution:base_account.account_type"):
            predict_log(artifact["prediction_contract"], {"feature_payload": bad}, artifact["feature_schema"]["runtime_domain"], ROOT)
        rejected, _, reasons = _predict_elastic_net(estimator_contract, bad, {}, root=ROOT)
        self.assertIsNone(rejected)
        self.assertEqual(reasons, ["out_of_distribution:base_account.account_type"])

    def test_runtime_ood_subgroup_cannot_disappear_from_gate(self):
        manifest = self.frozen_fixture(trend=True)
        manifest["lineage_mode"] = "production_signed"
        pool = split_synthetic_for_test(manifest)["market_pools"][0]
        holdout_ids = set(pool["holdout_cluster_ids"])
        index = 0
        for row in manifest["dataset_rows"]:
            if row["cluster_id"] in holdout_ids:
                row["evaluation_subgroup"] = "rare"
                if index < 30:
                    row["feature_payload"]["feature_groups"]["synthetic"]["signal"] = index
                index += 1
        metric, _ = _runtime_replay_metrics(ROOT, manifest, manifest["dataset_rows"], pool)
        rare = next(row for row in metric["subgroups"] if row["name"] == "rare")
        self.assertEqual(rare["holdout_case_count"], 100)
        self.assertEqual(rare["runtime_supported_case_count"], 30)
        self.assertIn("subgroup_runtime_supported_share_below_80_percent:rare", _gate_reasons(metric))

    def test_duplicate_easy_rows_cannot_dominate_cluster_weighted_holdout(self):
        manifest = self.frozen_fixture(trend=True)
        manifest["lineage_mode"] = "production_signed"
        pool = split_synthetic_for_test(manifest)["market_pools"][0]
        holdout_ids = set(pool["holdout_cluster_ids"])
        easy = sorted(holdout_ids)[0]
        base = next(row for row in manifest["dataset_rows"] if row["cluster_id"] == easy)
        for row in manifest["dataset_rows"]:
            if row["cluster_id"] in holdout_ids:
                row["feature_payload"]["feature_groups"]["synthetic"]["signal"] = 0
                if row["cluster_id"] != easy: row["selected_price_twd"] = 100000
        for _ in range(1000):
            manifest["dataset_rows"].append(dict(base))
        metric, _ = _runtime_replay_metrics(ROOT, manifest, manifest["dataset_rows"], pool)
        self.assertGreater(metric["holdout_mdape"], .90)
        self.assertEqual(metric["holdout_total_case_count"], 1100)  # admission remains row-level diagnostic
        self.assertEqual(metric["runtime_supported_case_share"], 1.0)  # publication gate is cluster-weighted
        self.assertEqual(metric["coverage_qualified_share"], 1.0)

    def test_runtime_row_admission_gate_rejects_ood_duplicates_inside_supported_cluster(self):
        manifest = self.frozen_fixture(trend=True)
        manifest["lineage_mode"] = "production_signed"
        pool = split_synthetic_for_test(manifest)["market_pools"][0]
        holdout_ids = set(pool["holdout_cluster_ids"])
        for row in manifest["dataset_rows"]:
            if row["cluster_id"] in holdout_ids:
                row["feature_payload"]["feature_groups"]["synthetic"]["signal"] %= 300
        base = next(row for row in manifest["dataset_rows"] if row["cluster_id"] in holdout_ids)
        # The original row keeps this cluster runtime-supported.  Most extra
        # signed rows are deliberately outside the trained numeric domain.
        for _ in range(1000):
            duplicate = deepcopy(base)
            duplicate["feature_payload"]["feature_groups"]["synthetic"]["signal"] = 10**9
            manifest["dataset_rows"].append(duplicate)
        metric, _ = _runtime_replay_metrics(ROOT, manifest, manifest["dataset_rows"], pool)
        self.assertEqual(metric["runtime_supported_case_share"], 1.0)
        self.assertLess(metric["runtime_supported_row_case_share"], .80)
        self.assertIn("runtime_supported_holdout_row_share_below_80_percent", _gate_reasons(metric))


if __name__ == "__main__":
    unittest.main()
