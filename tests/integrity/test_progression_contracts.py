"""Release gates stay closed until future progression has replayable audit evidence."""
from __future__ import annotations

import sys
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "validate"))
from build_reports import derived_model_status  # noqa: E402
from release_check import (  # noqa: E402
    _artifact_model_sha256,
    sha256,
    human_review_ledgers_release_valid,
    item_value_rows_release_valid,
    model_artifacts_release_valid,
)
from validate import formal_price_rebuild_errors, is_publication_train_only_elastic_artifact  # noqa: E402


def publication_gate() -> dict[str, object]:
    return {
        "status": "passed",
        "independent_training_clusters": 300,
        "time_forward_holdout_clusters": 100,
        "time_forward_holdout": True,
    }


class ProgressionContractTests(unittest.TestCase):
    def test_crafted_human_ids_cannot_unlock_review_ledgers(self):
        self.assertTrue(human_review_ledgers_release_valid([], []))
        self.assertFalse(human_review_ledgers_release_valid([{"annotator_a": {"annotator_id": "human_one"}}], []))
        self.assertFalse(human_review_ledgers_release_valid([], [{"reviewers": [{"reviewer_id": "human_one"}]}]))

    def test_crafted_trained_model_cannot_self_attest_publication(self):
        trained = {"status": "trained", "publication_gate": publication_gate()}
        self.assertFalse(model_artifacts_release_valid([trained]))
        self.assertEqual(derived_model_status([trained]), "publication_evaluator_required")

    def test_insufficient_models_remain_a_legal_fail_closed_state(self):
        artifacts = [{"status": "insufficient_training_data"}]
        self.assertTrue(model_artifacts_release_valid(artifacts))
        self.assertEqual(derived_model_status(artifacts), "insufficient_training_data")

    def test_trained_models_require_unique_exact_evaluator_binding(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "elastic-net-normal_listing.json"
            artifact = {
                "status": "trained", "model_type": "elastic_net", "price_line": "normal_listing",
                "prediction_contract": {"kind": "additive_log_price", "intercept": 8.0, "coefficients": {}},
            }
            path.write_text(json.dumps(artifact), encoding="utf-8")
            shared = {key: "A" * 64 for key in ("dataset_sha256", "dataset_manifest_sha256", "split_sha256")}
            binding = {
                "price_line": "normal_listing", "model_type": "elastic_net", **shared,
                "model_sha256": _artifact_model_sha256(artifact, path), "artifact_sha256": sha256(path),
            }
            passed = {"status": "passed", "publication_ready": True, **shared, "artifact_bindings": [binding]}
            paths = {("elastic_net", "normal_listing"): path}
            self.assertTrue(model_artifacts_release_valid([artifact], passed, paths, True))
            self.assertFalse(model_artifacts_release_valid([artifact], {**passed, "artifact_bindings": [binding, binding]}, paths, True))
            artifact["prediction_contract"]["intercept"] = 9.0
            path.write_text(json.dumps(artifact), encoding="utf-8")
            self.assertFalse(model_artifacts_release_valid([artifact], passed, paths, True))

    def test_canonical_normal_only_publication_allows_other_lines_to_remain_insufficient(self):
        """The release envelope has four slots, but P3.5 publishes one runtime.

        A forged second trained slot, stale artifact byte hash, or non-canonical
        slot must not be able to make this legal normal-only publication pass.
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "elastic-net-normal_listing.json"
            trained = {
                "status": "trained", "model_type": "elastic_net", "price_line": "normal_listing",
                "prediction_contract": {"kind": "additive_log_price", "intercept": 8.0, "coefficients": {}},
            }
            path.write_text(json.dumps(trained), encoding="utf-8")
            insufficient = [
                {"status": "insufficient_training_data", "model_type": "elastic_net", "price_line": "urgent_sale"},
                {"status": "insufficient_training_data", "model_type": "xgboost", "price_line": "normal_listing"},
                {"status": "insufficient_training_data", "model_type": "xgboost", "price_line": "urgent_sale"},
            ]
            shared = {key: "A" * 64 for key in ("dataset_sha256", "dataset_manifest_sha256", "split_sha256")}
            binding = {
                "price_line": "normal_listing", "model_type": "elastic_net", **shared,
                "model_sha256": _artifact_model_sha256(trained, path), "artifact_sha256": sha256(path),
            }
            passed = {"status": "passed", "publication_ready": True, **shared, "artifact_bindings": [binding]}
            artifacts = [trained, *insufficient]
            paths = {("elastic_net", "normal_listing"): path}
            self.assertTrue(model_artifacts_release_valid(artifacts, passed, paths, True))
            self.assertFalse(model_artifacts_release_valid(artifacts, {**passed, "artifact_bindings": [{**binding, "artifact_sha256": "B" * 64}]}, paths, True))
            forged_mixed = [{**trained}, {**insufficient[0], "status": "trained"}, *insufficient[1:]]
            self.assertFalse(model_artifacts_release_valid(forged_mixed, passed, paths, True))
            trained["prediction_contract"]["intercept"] = 9.0
            path.write_text(json.dumps(trained), encoding="utf-8")
            self.assertFalse(model_artifacts_release_valid(artifacts, passed, paths, True))

    def test_dual_elastic_price_lines_require_two_exact_bindings(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            shared = {key: "A" * 64 for key in ("dataset_sha256", "dataset_manifest_sha256", "split_sha256")}
            artifacts, paths, bindings = [], {}, []
            for price_line in ("normal_listing", "urgent_sale"):
                artifact = {"status": "trained", "model_type": "elastic_net", "price_line": price_line,
                            "prediction_contract": {"kind": "additive_log_price", "intercept": 8.0, "coefficients": {}}}
                path = base / f"elastic-net-{price_line}.json"
                path.write_text(json.dumps(artifact), encoding="utf-8")
                artifacts.append(artifact); paths[("elastic_net", price_line)] = path
                bindings.append({"price_line": price_line, "model_type": "elastic_net", **shared,
                                 "model_sha256": _artifact_model_sha256(artifact, path), "artifact_sha256": sha256(path)})
            report = {"status": "passed", "publication_ready": True, **shared, "artifact_bindings": bindings}
            self.assertTrue(model_artifacts_release_valid(artifacts, report, paths, True))
            self.assertFalse(model_artifacts_release_valid(artifacts, {**report, "artifact_bindings": bindings[:1]}, paths, True))

    def test_validator_accepts_only_the_two_replayed_elastic_price_lines(self):
        base = {"model_type": "elastic_net", "price_line": "urgent_sale",
                "training": {"publication_train_only": True, "publication_holdout_rows_excluded_from_fit": True},
                "publication_gate": {"status": "not_evaluated"}}
        self.assertTrue(is_publication_train_only_elastic_artifact(base))
        self.assertTrue(is_publication_train_only_elastic_artifact({**base, "price_line": "normal_listing"}))
        self.assertFalse(is_publication_train_only_elastic_artifact({**base, "price_line": "verified_sale"}))
        self.assertFalse(is_publication_train_only_elastic_artifact({**base, "model_type": "xgboost"}))
        self.assertFalse(is_publication_train_only_elastic_artifact({**base, "publication_gate": {"status": "passed"}}))

    def test_mixed_or_unpassed_model_release_is_rejected(self):
        trained = {"status": "trained", "model_type": "elastic_net", "price_line": "normal_listing"}
        insufficient = {"status": "insufficient_training_data"}
        self.assertFalse(model_artifacts_release_valid([trained, insufficient]))
        self.assertFalse(model_artifacts_release_valid([trained], {"status": "failed", "publication_ready": False}, {}))

    def test_crafted_eligible_item_value_cannot_self_attest_provenance(self):
        row = {
            "item_id": "item_example",
            "status": "eligible",
            "model_feature_eligible": True,
            "mean_conditional_attribution": 0.12,
            "median_conditional_attribution": 0.10,
            "explanation_provenance": {
                "status": "verified",
                "artifact_sha256": "artifact",
                "model_sha256": "model",
                "input_snapshot_sha256": "snapshot",
            },
        }
        self.assertFalse(item_value_rows_release_valid([row], {"item_example"}))

    def test_handwritten_clean_price_cannot_bypass_authorization_rebuild(self):
        injected = {
            "cleaned_price_id": "cleaned_price_forged", "history_id": "history_forged",
            "account_id": "account_forged", "cluster_id": "cluster_forged",
            "selected_price_twd": 1000.0, "price_line": "normal_listing",
        }
        problems = formal_price_rebuild_errors([], [injected], [], [], [], ROOT)
        self.assertIn("price-cleaned-normal differs from deterministic authorized rebuild", problems)


if __name__ == "__main__":
    unittest.main()
