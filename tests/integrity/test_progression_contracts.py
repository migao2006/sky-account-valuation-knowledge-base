"""Release gates stay closed until future progression has replayable audit evidence."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "validate"))
from build_reports import derived_model_status  # noqa: E402
from release_check import (  # noqa: E402
    human_review_ledgers_release_valid,
    item_value_rows_release_valid,
    model_artifacts_release_valid,
)
from validate import formal_price_rebuild_errors  # noqa: E402


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
        problems = formal_price_rebuild_errors([], [injected], [], [])
        self.assertIn("price-cleaned-normal differs from deterministic authorized rebuild", problems)


if __name__ == "__main__":
    unittest.main()
