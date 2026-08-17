import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
