import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.modeling.publication_evaluator import build  # noqa: E402


class PublicationEvaluatorTests(unittest.TestCase):
    def test_formal_report_is_replayed_and_fail_closed(self):
        report = build(ROOT)
        self.assertEqual(report["status"], "not_ready")
        self.assertIs(report["publication_ready"], False)
        self.assertIs(report["artifact_publication_fields_consulted"], False)
        self.assertIsNone(report["metrics"])
        self.assertIn("no_market_pool_meets_300_train_100_time_forward_holdout", report["blocking_reasons"])


if __name__ == "__main__":
    unittest.main()
