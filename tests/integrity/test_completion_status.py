import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.validate.build_completion_status import build  # noqa: E402


class CompletionStatusTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
