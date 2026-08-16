import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
from tools.modeling.clean_prices import build, clean


def row(number, **changes):
    value = {
        "history_id": f"history_test_{number:04d}", "account_id": f"account_test_{number:04d}",
        "selected_price_twd": 1000, "price_type": "asking", "currency": "TWD", "currency_verified": True,
        "server": "international", "server_verified": True, "offer_kind": "seller_listing", "entity_kind": "single_account",
        "base_account": {"account_type": "winged_or_unspecified"}, "post_date": "2026-08-01", "observed_at": "2026-08-16",
        "market_evidence_quality": "high",
    }
    value.update(changes)
    return value


class PriceCleaningTest(unittest.TestCase):
    def test_hard_market_and_transaction_rejections_have_reason_codes(self):
        cases = [
            row(1, currency="unknown", currency_verified=False),
            row(2, currency="RM"),
            row(3, server="unknown", server_verified=False),
            row(4, server="taiwan"),
            row(5, offer_kind="buyer_budget"),
            row(6, entity_kind="bundle"),
            row(7, selected_price_twd=0),
            row(8, price_type="sold_claim"),
            row(9, mixed_price=True),
        ]
        normal, urgent, excluded = clean(cases)
        self.assertEqual(normal, [])
        self.assertEqual(urgent, [])
        reasons = {item["history_id"]: set(item["reason_codes"]) for item in excluded}
        self.assertIn("currency_unverified", reasons["history_test_0001"])
        self.assertIn("currency_not_twd", reasons["history_test_0002"])
        self.assertIn("server_unverified", reasons["history_test_0003"])
        self.assertIn("server_not_international", reasons["history_test_0004"])
        self.assertIn("not_seller_listing", reasons["history_test_0005"])
        self.assertIn("not_single_account", reasons["history_test_0006"])
        self.assertIn("invalid_price", reasons["history_test_0007"])
        self.assertIn("price_type_not_training_line", reasons["history_test_0008"])
        self.assertIn("mixed_price", reasons["history_test_0009"])

    def test_normal_and_urgent_lines_are_separate_and_account_cluster_is_deduped(self):
        duplicate = row(2, account_id="account_test_0001", post_date="2026-08-02")
        normal, urgent, excluded = clean([row(1), duplicate, row(3, price_type="reduced")])
        self.assertEqual([item["history_id"] for item in normal], ["history_test_0002"])
        self.assertEqual([item["history_id"] for item in urgent], ["history_test_0003"])
        self.assertEqual(excluded[0]["history_id"], "history_test_0001")
        self.assertIn("duplicate_account_cluster", excluded[0]["reason_codes"])

    def test_modified_z_outlier_requires_ten_independent_same_type_clusters(self):
        sparse = [row(index, selected_price_twd=1000 + index * 10) for index in range(1, 9)]
        sparse.append(row(9, selected_price_twd=1_000_000))
        normal, _, excluded = clean(sparse)
        self.assertEqual(len(normal), 8)
        review = next(item for item in excluded if item["history_id"] == "history_test_0009")
        self.assertEqual(review["disposition"], "needs_review")
        self.assertEqual(review["reason_codes"], ["log_price_outlier_insufficient_group"])

        dense = [row(index, selected_price_twd=1000 + index * 10) for index in range(1, 11)]
        dense.append(row(11, selected_price_twd=1_000_000))
        normal, _, excluded = clean(dense)
        self.assertEqual(len(normal), 10)
        outlier = next(item for item in excluded if item["history_id"] == "history_test_0011")
        self.assertEqual(outlier["reason_codes"], ["log_price_modified_z_outlier"])

    def test_formal_data_is_conservatively_cleaned_without_fabricating_rows(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            summary = build(ROOT, output_dir=output)
            self.assertEqual(summary, {"input_rows": 102, "normal_listing": 3, "urgent_sale": 0, "excluded_or_review": 99})
            normal = [json.loads(line) for line in (output / "price-cleaned-normal.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual({item["history_id"] for item in normal}, {"history_0036", "history_0068", "history_0085"})
            self.assertTrue(all(item["currency"] == "TWD" and item["server"] == "international" for item in normal))
            ledger = [json.loads(line) for line in (output / "model-exclusions.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(ledger), 99)


if __name__ == "__main__":
    unittest.main()
