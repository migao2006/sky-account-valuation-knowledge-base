"""Tests for the P2.3 anonymous market near-miss field-evidence workflow."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "normalize"))

from build_market_near_miss_review import (  # noqa: E402
    SELECTION_VERSION,
    build_queue,
    is_base_candidate,
    missing_hard_evidence_groups,
    read_jsonl,
    validate_approved_evidence,
)
from tools.validate.schema_validator import OfflineSchemaValidator  # noqa: E402


def field_evidence(review: dict) -> dict:
    value = "international"
    return {
        "evidence_id": "market_near_miss_evidence_0001",
        "review_id": review["review_id"],
        "listing_id": review["listing_id"],
        "listing_text_sha256": review["listing_text_sha256"],
        "field": "server",
        "value": value,
        "reviewers": [
            {"reviewer_id": "human_one", "reviewer_kind": "human", "reviewed_at": "2026-08-17", "value": value},
            {"reviewer_id": "human_two", "reviewer_kind": "human", "reviewed_at": "2026-08-17", "value": value},
        ],
        "adjudication": {"adjudicator_id": "human_three", "adjudicator_kind": "human", "adjudicated_at": "2026-08-17", "decision": "agreement", "final_value": value},
        "review_status": "approved_human_field_evidence",
    }


class MarketNearMissReviewTests(unittest.TestCase):
    def setUp(self) -> None:
        self.validator = OfflineSchemaValidator(ROOT / "schemas")
        self.rows = read_jsonl(ROOT / "data/normalized/listings.jsonl")

    def test_committed_queue_is_deterministic_anonymous_and_one_hard_group_only(self):
        queue_path = ROOT / "data/review/market-near-miss-field-review.jsonl"
        queue = read_jsonl(queue_path)
        self.assertEqual(queue, build_queue(self.rows))
        self.assertGreater(len(queue), 0)
        self.assertEqual(len({row["listing_id"] for row in queue}), len(queue))
        self.assertNotIn("listing_0260", {row["listing_id"] for row in queue})
        rows_by_id = {row["listing_id"]: row for row in self.rows}
        for row in queue:
            self.assertEqual(row["selection_version"], SELECTION_VERSION)
            self.assertTrue(is_base_candidate(rows_by_id[row["listing_id"]]))
            self.assertEqual(len(missing_hard_evidence_groups(rows_by_id[row["listing_id"]])), 1)
            self.assertFalse(set(row) & {"listing_text", "source_url", "url", "price_twd", "server_value", "machine_value", "suggested_value"})
            self.assertEqual(self.validator.validate(row, ROOT / "schemas/review/market-near-miss-field-review.schema.json"), [])
        serialized_queue = (ROOT / "data/review/market-near-miss-field-review.jsonl").read_text(encoding="utf-8")
        self.assertFalse(any(token in serialized_queue for token in ("凜冬", "絆愛", "阿努", "多禮")))

    def test_queue_rebuild_is_byte_deterministic(self):
        command = [sys.executable, "tools/normalize/build_market_near_miss_review.py", "--root", str(ROOT)]
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "first.jsonl"
            second = Path(temporary) / "second.jsonl"
            subprocess.run([*command, "--output", str(first)], cwd=ROOT, check=True, capture_output=True, text=True)
            subprocess.run([*command, "--output", str(second)], cwd=ROOT, check=True, capture_output=True, text=True)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first.read_bytes(), (ROOT / "data/review/market-near-miss-field-review.jsonl").read_bytes())

    def test_single_hard_group_selector_supports_other_hard_field_domains(self):
        base = {
            "listing_id": "listing_9000", "listing_text": "anonymous", "offer_kind": "seller_listing", "entity_kind": "single_account",
            "currency": "TWD", "currency_verified": True, "price_twd": 1000, "server": "international", "server_verified": True,
            "price_type": "asking", "status": "active", "exclusion_reason": None, "duplicate_cluster_id": None,
        }
        unknown_price_type = {**base, "listing_id": "listing_9001", "price_type": "unknown"}
        unknown_status = {**base, "listing_id": "listing_9002", "status": "unknown"}
        known_china = {**base, "listing_id": "listing_9003", "server": "china", "server_verified": True}
        known_reduced = {**base, "listing_id": "listing_9004", "price_type": "reduced"}
        known_sold = {**base, "listing_id": "listing_9005", "status": "sold"}
        queue = build_queue([unknown_price_type, unknown_status, known_china, known_reduced, known_sold])
        self.assertEqual([row["listing_id"] for row in queue], ["listing_9001", "listing_9002"])
        self.assertEqual(queue[0]["required_fields"], ["price_type"])
        self.assertEqual(queue[1]["required_fields"], ["status"])

    def test_approved_evidence_requires_linked_double_human_adjudication(self):
        review = read_jsonl(ROOT / "data/review/market-near-miss-field-review.jsonl")[0]
        row = field_evidence(review)
        schema = ROOT / "schemas/review/market-near-miss-approved-evidence.schema.json"
        self.assertEqual(self.validator.validate(row, schema), [])
        self.assertEqual(validate_approved_evidence([review], [row]), [])
        row["reviewers"][1]["reviewer_id"] = "human_one"
        self.assertTrue(validate_approved_evidence([review], [row]))
        row["reviewers"][1]["reviewer_id"] = "human_two"
        row["adjudication"]["final_value"] = "china"
        self.assertTrue(validate_approved_evidence([review], [row]))
        row = field_evidence(review)
        row["reviewers"][1]["value"] = "china"
        self.assertTrue(any("agreement decision" in error for error in validate_approved_evidence([review], [row])))

    def test_evidence_value_domains_and_oneof_are_fail_closed(self):
        review = read_jsonl(ROOT / "data/review/market-near-miss-field-review.jsonl")[0]
        row = field_evidence(review)
        schema = ROOT / "schemas/review/market-near-miss-approved-evidence.schema.json"
        row["value"] = "https://private.example/user"
        row["reviewers"][0]["value"] = row["value"]
        row["reviewers"][1]["value"] = row["value"]
        row["adjudication"]["final_value"] = row["value"]
        self.assertTrue(self.validator.validate(row, schema))
        self.assertTrue(validate_approved_evidence([review], [row]))
        row = field_evidence(review)
        row["field"] = "server_verified"
        row["value"] = "true"
        row["reviewers"][0]["value"] = "true"
        row["reviewers"][1]["value"] = "true"
        row["adjudication"]["final_value"] = "true"
        self.assertTrue(validate_approved_evidence([review], [row]))

    def test_approved_evidence_ledger_starts_empty_and_cannot_change_formal_comparables(self):
        ledger = ROOT / "data/review/market-near-miss-approved-evidence.jsonl"
        self.assertEqual(ledger.read_text(encoding="utf-8"), "")
        self.assertEqual(len(read_jsonl(ROOT / "data/comparables/accounts.jsonl")), 103)


if __name__ == "__main__":
    unittest.main()
