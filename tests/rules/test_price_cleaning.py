import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
from tools.modeling.clean_prices import build, clean as raw_clean


def authorized_market_data():
    return {
        "status": "authorized_model_training", "allowed_uses": ["research", "model_training", "comparable_estimation"],
        "source_snapshot": {"artifact_path": "tests/fixture.json", "sha256": "a" * 64, "captured_at": "2026-08-01", "replayable": True},
        "license_evidence": {"kind": "explicit_data_license", "evidence_id": "fixture-license", "verified": True},
        "replay_evidence": [{"evidence_id": "fixture-replay", "source_locator": "fixture://market", "content_sha256": "b" * 64, "reviewed_at": "2026-08-01"}],
        "authorization_record_id": "fixture-authorized-record",
    }


def clean(rows):
    """Unit-test price semantics with an explicitly injected authority."""
    return raw_clean(rows, authorization_evaluator=lambda row: row.get("market_data_authorization") == authorized_market_data())


def row(number, **changes):
    value = {
        "history_id": f"history_test_{number:04d}", "account_id": f"account_test_{number:04d}",
        "selected_price_twd": 1000, "price_type": "asking", "currency": "TWD", "currency_verified": True,
        "server": "international", "server_verified": True, "offer_kind": "seller_listing", "entity_kind": "single_account",
        "base_account": {"account_type": "winged_or_unspecified"}, "post_date": "2026-08-01", "observed_at": "2026-08-16",
        "market_evidence_quality": "high",
        "market_data_authorization": authorized_market_data(),
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

    def test_market_training_authorization_is_fail_closed(self):
        unauthorized = row(1, market_data_authorization={"status": "authorized_model_training", "allowed_uses": ["model_training", "comparable_estimation"]})
        legacy = row(2, market_data_authorization={
            "status": "legacy_research_only", "allowed_uses": ["research"],
            "source_snapshot": {"artifact_path": "legacy", "sha256": "a" * 64, "captured_at": "2026-08-01", "replayable": False},
            "license_evidence": {"kind": "legacy_anonymous_research", "evidence_id": "legacy", "verified": False}, "replay_evidence": [],
        })
        normal, urgent, ledger = clean([unauthorized, legacy])
        self.assertEqual((normal, urgent), ([], []))
        by_history = {entry["history_id"]: entry["reason_codes"] for entry in ledger}
        self.assertIn("market_data_replay_evidence_missing", by_history["history_test_0001"])
        self.assertIn("market_data_license_evidence_missing", by_history["history_test_0001"])
        self.assertIn("market_data_not_authorized_for_model_training", by_history["history_test_0002"])

    def test_complete_self_filled_authorization_still_requires_external_evaluator(self):
        normal, urgent, ledger = raw_clean([row(3)])
        self.assertEqual((normal, urgent), ([], []))
        self.assertIn("market_data_external_authorization_evaluator_required", ledger[0]["reason_codes"])

    def test_normal_and_urgent_lines_are_separate_and_account_cluster_is_deduped(self):
        duplicate = row(2, account_id="account_test_0001", post_date="2026-08-02")
        normal, urgent, excluded = clean([row(1), duplicate, row(3, price_type="reduced")])
        self.assertEqual([item["history_id"] for item in normal], ["history_test_0002"])
        self.assertEqual([item["history_id"] for item in urgent], ["history_test_0003"])
        self.assertEqual(excluded[0]["history_id"], "history_test_0001")
        self.assertIn("duplicate_account_cluster", excluded[0]["reason_codes"])

    def test_brokerage_included_urgent_price_is_retained_for_review_not_training(self):
        urgent = row(1, price_type="urgent_sale", price_semantic_review={
            "urgency": "urgent_sale", "brokerage_included": True,
            "evidence_state": "text_claim", "review_status": "needs_review",
            "reason_codes": ["brokerage_included_price"],
        })
        normal, urgent_rows, ledger = clean([urgent])
        self.assertEqual(normal, [])
        self.assertEqual(urgent_rows, [])
        self.assertEqual(ledger, [{
            "schema_version": "3.1-p1", "history_id": "history_test_0001", "account_id": "account_test_0001",
            "reason_codes": ["brokerage_included_price"], "disposition": "needs_review",
            "price_line": "urgent_sale", "selected_price_twd": 1000,
        }])

    def test_explicit_multi_price_terms_are_retained_for_review_not_training(self):
        account = row(1, price_semantic_review={
            "urgency": "unknown", "multi_price": True,
            "evidence_state": "text_claim", "review_status": "needs_review",
            "reason_codes": ["multiple_price_terms", "badge_inclusion_price_variants", "installment_price_variants"],
        })
        normal, urgent, ledger = clean([account])
        self.assertEqual(normal, [])
        self.assertEqual(urgent, [])
        self.assertEqual(ledger[0]["disposition"], "needs_review")
        self.assertIn("multiple_price_terms", ledger[0]["reason_codes"])

    def test_listing_0388_installment_surcharge_is_not_a_clean_price(self):
        histories = [
            json.loads(line)
            for line in (ROOT / "data" / "curated" / "histories.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        installment_listing = dict(next(row for row in histories if row["history_id"] == "history_0068"))
        # This is the semantic marker the migration/rebuild must carry from
        # listing_0388; do not choose or calculate an installment total.
        installment_listing["price_semantic_review"] = {
            "urgency": "unknown", "multi_price": True,
            "evidence_state": "text_claim", "review_status": "needs_review",
            "reason_codes": ["multiple_price_terms", "installment_price_variants"],
        }
        normal, urgent, ledger = clean([installment_listing])
        self.assertEqual(normal, [])
        self.assertEqual(urgent, [])
        self.assertEqual(ledger[0]["history_id"], "history_0068")
        self.assertEqual(ledger[0]["disposition"], "needs_review")
        self.assertIn("multiple_price_terms", ledger[0]["reason_codes"])
        self.assertIn("market_data_not_authorized_for_model_training", ledger[0]["reason_codes"])

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
            self.assertEqual(summary, {"input_rows": 103, "normal_listing": 0, "urgent_sale": 0, "excluded_or_review": 103})
            normal = [json.loads(line) for line in (output / "price-cleaned-normal.jsonl").read_text(encoding="utf-8").splitlines()]
            urgent = [json.loads(line) for line in (output / "price-cleaned-urgent.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(normal, [])
            accounts = {
                item["history_id"]: item
                for item in (json.loads(line) for line in (ROOT / "data/comparables/accounts.jsonl").read_text(encoding="utf-8").splitlines() if line)
            }
            self.assertEqual(
                {tuple(accounts[item["history_id"]]["source_listing_ids"]) for item in normal},
                set(),
            )
            self.assertEqual(urgent, [])
            self.assertTrue(all(item["currency"] == "TWD" and item["server"] == "international" for item in normal))
            ledger = [json.loads(line) for line in (output / "model-exclusions.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(ledger), 103)
            self.assertTrue(all("market_data_not_authorized_for_model_training" in item["reason_codes"] for item in ledger))
            installment = next(item for item in ledger if item["history_id"] == "history_0068")
            self.assertEqual(installment["disposition"], "needs_review")
            self.assertIn("multiple_price_terms", installment["reason_codes"])
            semantic = next(item for item in ledger if item["history_id"] == "history_0036")
            self.assertEqual(semantic["price_line"], "urgent_sale")
            self.assertEqual(semantic["disposition"], "needs_review")
            self.assertIn("brokerage_included_price", semantic["reason_codes"])
            multi_price = next(item for item in ledger if item["history_id"] == "history_0062")
            self.assertEqual(multi_price["disposition"], "needs_review")
            self.assertIn("multiple_price_terms", multi_price["reason_codes"])


if __name__ == "__main__":
    unittest.main()
