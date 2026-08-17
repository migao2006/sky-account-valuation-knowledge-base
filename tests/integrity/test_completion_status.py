import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.validate.build_completion_status import build, _published_capacity_ready  # noqa: E402


class CompletionStatusTests(unittest.TestCase):
    def test_capacity_requires_every_published_pool_not_any_ready_pool(self):
        ready_normal = {"market_pool": "TWD:international:normal_listing", "time_forward_split": {"available": True, "training_clusters": 300, "holdout_clusters": 100, "cluster_overlap": False}}
        readiness = {"market_pools": [ready_normal]}
        self.assertTrue(_published_capacity_ready(readiness, [{"price_line": "normal_listing"}]))
        self.assertFalse(_published_capacity_ready(readiness, [{"price_line": "normal_listing"}, {"price_line": "urgent_sale"}]))
        self.assertFalse(_published_capacity_ready(readiness, []))

    def test_formal_goal_state_is_explicit_and_evidence_backed(self):
        report = build(ROOT)
        self.assertEqual(report["status"], "incomplete")
        self.assertIs(report["complete"], False)
        self.assertIn("model.replayable_publication_passed", report["blocking_contract_ids"])
        self.assertIn("market.train_holdout_capacity", report["blocking_contract_ids"])
        self.assertEqual(len(report["checks"]), len({row["contract_id"] for row in report["checks"]}))

    def test_external_market_authority_is_forwarded_to_completion_replay(self):
        from tools.validate import build_completion_status as completion_module

        actual_json = completion_module._json
        ready_market_report = {
            "publication_ready": True,
            "status": "evaluated",
            "gold_row_count": 200,
            "heldout_minimum_annotator_field_accuracy": 1.0,
            "heldout_verified_sale_false_positive_count": 0,
            "independent_blinded_decisions_proven": True,
        }

        def report_override(path):
            if path.name == "market-gold-evaluation.json":
                return ready_market_report
            return actual_json(path)

        with (
            patch.object(completion_module, "_json", side_effect=report_override),
            patch("tools.modeling.market_gold_evaluator.build", return_value=ready_market_report) as replay,
        ):
            report = completion_module.build(ROOT, "external-authority.json", "A" * 64)

        replay.assert_called_once_with(ROOT.resolve(), "external-authority.json", "A" * 64)
        market_check = next(row for row in report["checks"] if row["contract_id"] == "market.human_gold_evaluation_passed")
        self.assertTrue(market_check["passed"])

    def test_model_completion_uses_exact_replayed_binding_not_four_trained_count(self):
        """P3.5 supports one bound normal Elastic runtime, not four runtimes."""
        from tools.validate import build_completion_status as completion_module

        evaluation = {
            "status": "passed", "publication_ready": True,
            "artifact_bindings": [{"model_type": "elastic_net", "price_line": "normal_listing"}],
        }
        actual_json = completion_module._json

        def report_override(path):
            if path.name == "model-publication-evaluation.json":
                return evaluation
            return actual_json(path)

        with (
            patch.object(completion_module, "_json", side_effect=report_override),
            patch("tools.modeling.publication_evaluator.build", return_value=evaluation),
            # The helper itself is integration-tested with canonical four-slot
            # envelopes in test_progression_contracts.  This isolates the
            # completion gate from the obsolete all-trained count.
            patch("tools.validate.release_check.model_artifacts_release_valid", return_value=True),
        ):
            report = completion_module.build(ROOT)

        model_check = next(row for row in report["checks"] if row["contract_id"] == "model.replayable_publication_passed")
        self.assertTrue(model_check["passed"])


if __name__ == "__main__":
    unittest.main()
