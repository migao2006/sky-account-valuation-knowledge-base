import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.modeling.publication_dataset import freeze_synthetic_for_test  # noqa: E402
from tools.modeling.publication_evaluator import _sha256, build, evaluate  # noqa: E402


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
                "selected_price_twd": (5000 + day.toordinal() * 3 + residual) if trend else 5000 + number * 10,
                "post_date": day.isoformat() if trend else ("2025-01-01" if number < 300 else "2025-02-01"), "date_verified": True,
            })
            vectors.append({"account_id": account, "catalog_provenance": {}})
        return freeze_synthetic_for_test(rows, vectors, {}, [])

    def test_formal_report_is_replayed_and_fail_closed(self):
        report = build(ROOT)
        self.assertEqual(report["status"], "not_ready")
        self.assertIs(report["publication_ready"], False)
        self.assertIs(report["artifact_publication_fields_consulted"], False)
        self.assertIsNone(report["metrics"])
        self.assertIn("no_market_pool_meets_300_train_100_time_forward_holdout", report["blocking_reasons"])

    def test_sufficient_frozen_fixture_replays_train_only_metrics_but_cannot_publish(self):
        report = evaluate(self.frozen_fixture())
        self.assertEqual(report["status"], "evaluation_required")
        self.assertFalse(report["publication_ready"])
        self.assertEqual(report["metrics"]["replay_kind"], "evaluator_owned_train_only_date_trend")
        metric = report["metrics"]["market_pools"][0]
        self.assertEqual((metric["training_row_count"], metric["holdout_row_count"]), (300, 100))
        self.assertIn("TWD:international:normal_listing:date_trend_requires_training_date_variation", report["blocking_reasons"])

    def test_evaluator_owned_train_only_model_can_pass_replay_gates(self):
        report = evaluate(self.frozen_fixture(trend=True))
        self.assertEqual(report["status"], "passed")
        self.assertTrue(report["publication_ready"])
        self.assertEqual(len(report["artifact_bindings"]), 1)
        self.assertEqual(report["artifact_bindings"][0]["model_type"], "publication_date_linear_regression")
        self.assertEqual(report["blocking_reasons"], [])

    def test_external_artifact_predictions_and_forged_split_are_rejected(self):
        manifest = self.frozen_fixture(trend=True)
        forged = {
            "market_pools": [{
                "currency": "TWD", "server": "international", "price_line": "normal_listing",
                "cut_date": "2025-01-01", "training_cluster_ids": ["cluster_0300"],
                "holdout_cluster_ids": ["cluster_0300"],
            }]
        }
        report = evaluate(manifest, forged, artifact={"publication_gate": "passed"}, predictions=[{"price": 1}])
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
        report = evaluate(manifest)
        self.assertEqual(report["status"], "evaluation_required")
        self.assertIn("TWD:international:normal_listing:subgroup_under_30:rare", report["blocking_reasons"])

    def test_holdout_only_subgroup_is_out_of_distribution(self):
        manifest = self.frozen_fixture(trend=True)
        for row in manifest["dataset_rows"][-100:]:
            row["evaluation_subgroup"] = "holdout_only"
            payload = {key: value for key, value in row.items() if key != "row_sha256"}
            row["row_sha256"] = _sha256(payload)
        manifest["dataset_sha256"] = _sha256(manifest["dataset_rows"])
        report = evaluate(manifest)
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
        report = evaluate(manifest)
        self.assertIn(
            "TWD:international:normal_listing:subgroup_mdape_above_25_percent:bad_error_group",
            report["blocking_reasons"],
        )


if __name__ == "__main__":
    unittest.main()
