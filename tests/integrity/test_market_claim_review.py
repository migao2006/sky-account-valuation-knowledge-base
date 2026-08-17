"""Tests for the fixed anonymous market-claim review and human-gold contract."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "normalize"))

from build_market_claim_review import OPAQUE_BUCKETS, QUEUE_SIZE, REQUESTED_FIELDS, build_queue, read_jsonl, validate_gold_links
from tools.validate.schema_validator import OfflineSchemaValidator


def human_labels() -> dict:
    return {
        "offer_kind": "seller_listing", "entity_kind": "single_account",
        "server": "international", "currency": "TWD", "price_type": "asking",
        "price_twd": 1200, "status": "active", "date_verified": False, "verified_sale": False,
    }


def human_annotation(identifier: str) -> dict:
    return {"annotator_id": identifier, "annotator_kind": "human", "annotated_at": "2026-08-17", "labels": human_labels()}


class MarketClaimReviewTests(unittest.TestCase):
    def setUp(self):
        self.validator = OfflineSchemaValidator(ROOT / "schemas")

    def test_committed_queue_is_fixed_stratified_and_anonymous(self):
        queue_path = ROOT / "data/review/market-claim-review.jsonl"
        queue = read_jsonl(queue_path)
        normalized = read_jsonl(ROOT / "data/normalized/listings.jsonl")
        self.assertEqual(len(queue), 200)
        self.assertEqual(QUEUE_SIZE, 200)
        self.assertEqual(len({row["listing_id"] for row in queue}), 200)
        self.assertEqual(len({row["selection_bucket"] for row in queue}), 20)
        self.assertTrue(all(row["selection_bucket"] in set(OPAQUE_BUCKETS) for row in queue))
        self.assertTrue(all(not any(token in row["selection_bucket"] for token in ("buyer", "seller", "service", "exchange", "sold", "currency")) for row in queue))
        self.assertTrue(all(row["requested_fields"] == REQUESTED_FIELDS for row in queue))
        self.assertTrue(all("listing_text" not in row for row in queue))
        self.assertTrue(all(not self.validator.validate(row, ROOT / "schemas/review/market-claim-review.schema.json") for row in queue))
        self.assertEqual(build_queue(normalized), queue)

    def test_queue_selection_covers_market_claim_dimensions_without_exposing_them(self):
        queue = read_jsonl(ROOT / "data/review/market-claim-review.jsonl")
        normalized = {row["listing_id"]: row for row in read_jsonl(ROOT / "data/normalized/listings.jsonl")}
        selected = [normalized[row["listing_id"]] for row in queue]
        text = "\n".join(str(row["listing_text"]) for row in selected)
        self.assertTrue(any(row["price_twd"] is not None for row in selected))
        self.assertTrue({"TWD", "HKD", "RM", "CNY"} <= {row["currency"] for row in selected})
        self.assertTrue({"international", "china", "unknown"} <= {row["server"] for row in selected})
        self.assertTrue({"seller_listing", "buyer_budget", "service", "exchange", "unknown"} <= {row["offer_kind"] for row in selected})
        self.assertTrue(any(row["entity_kind"] == "multi_account" for row in selected))
        self.assertRegex(text, r"綁|绑|Google|Apple|Facebook|Nintendo|Steam|PlayStation")
        self.assertRegex(text, r"季|畢業|毕业|極光|欧若拉|梵谷|梵高|大耳狗|耳狗|青鳥|青鸟|築巢|筑巢|歸巢|归巢")
        self.assertRegex(text, r"蠟|蜡|愛心|爱心|季蠟|季蜡|紅蠟|红蜡|红烛|白蜡")

    def test_queue_rebuild_is_deterministic(self):
        command = [sys.executable, "tools/normalize/build_market_claim_review.py", "--root", str(ROOT)]
        with tempfile.TemporaryDirectory() as temporary:
            first, second = Path(temporary) / "first.jsonl", Path(temporary) / "second.jsonl"
            subprocess.run([*command, "--output", str(first)], cwd=ROOT, check=True, capture_output=True, text=True)
            subprocess.run([*command, "--output", str(second)], cwd=ROOT, check=True, capture_output=True, text=True)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first.read_bytes(), (ROOT / "data/review/market-claim-review.jsonl").read_bytes())

    def test_gold_requires_two_humans_and_human_adjudication(self):
        gold = {
            "gold_id": "market_claim_gold_0001", "review_id": "market_claim_review_0001", "listing_id": "listing_0260", "listing_text_sha256": "A" * 64,
            "annotation_protocol": "double_independent_human_annotation",
            "annotator_a": human_annotation("human_a"), "annotator_b": human_annotation("human_b"),
            "adjudication": {"adjudicator_id": "human_adjudicator", "adjudicator_kind": "human", "adjudicated_at": "2026-08-17", "decision": "agreement", "final_labels": human_labels()},
            "review_status": "approved_human_gold",
        }
        schema = ROOT / "schemas/review/market-claim-gold.schema.json"
        self.assertEqual(self.validator.validate(gold, schema), [])
        gold["annotator_b"]["annotator_kind"] = "agent"
        self.assertTrue(self.validator.validate(gold, schema))

    def test_gold_linkage_requires_distinct_humans_and_exact_queue_hash(self):
        queue = read_jsonl(ROOT / "data/review/market-claim-review.jsonl")
        review = queue[0]
        gold = {
            "gold_id": "market_claim_gold_0001", "review_id": review["review_id"], "listing_id": review["listing_id"], "listing_text_sha256": review["listing_text_sha256"],
            "annotation_protocol": "double_independent_human_annotation",
            "annotator_a": human_annotation("human_same"), "annotator_b": human_annotation("human_same"),
            "adjudication": {"adjudicator_id": "human_same", "adjudicator_kind": "human", "adjudicated_at": "2026-08-17", "decision": "agreement", "final_labels": human_labels()},
            "review_status": "approved_human_gold",
        }
        self.assertTrue(validate_gold_links(queue, [gold]))
        gold["annotator_b"]["annotator_id"] = "human_b"
        gold["adjudication"]["adjudicator_id"] = "human_c"
        self.assertEqual(validate_gold_links(queue, [gold]), [])
        gold["listing_text_sha256"] = "F" * 64
        self.assertTrue(validate_gold_links(queue, [gold]))

    def test_gold_file_is_intentionally_empty(self):
        self.assertEqual((ROOT / "data/review/market-claim-gold.jsonl").read_text(encoding="utf-8"), "")


if __name__ == "__main__":
    unittest.main()
