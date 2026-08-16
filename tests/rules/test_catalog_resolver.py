"""Rules tests for conservative catalog claim resolution."""
from __future__ import annotations
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "classify"))
from resolve_catalog_claims import resolve_catalog_claims  # noqa: E402

def index_rows():
    return [json.loads(line) for line in (ROOT / "data/normalized/catalog-query-index.jsonl").read_text(encoding="utf-8").splitlines() if line]

class CatalogResolverTests(unittest.TestCase):
    def test_current_canonical_lookup_remains_review_only_without_verified_identity(self):
        row = resolve_catalog_claims({"catalog_claims": [{"claim_id": "claim_owned", "query_entity_id": "item_anniversary_bass", "state": "owned", "evidence_state": "structured_claim"}]}, index_rows())["resolutions"][0]
        self.assertEqual(row["resolution_status"], "review_only"); self.assertEqual(row["ownership_state"], "unknown"); self.assertIsNone(row["resolved_item_id"]); self.assertFalse(row["model_feature"])

    def test_unknown_is_not_missing_and_positive_negative_conflict_fails_closed(self):
        unknown = resolve_catalog_claims({"catalog_claims": [{"claim_id": "claim_unknown", "query_entity_id": "item_anniversary_bass", "state": "unknown", "evidence_state": "unknown"}]}, index_rows())["resolutions"][0]
        self.assertEqual(unknown["ownership_state"], "unknown"); self.assertIn("unknown_claim", unknown["reasons"][0])
        conflict = resolve_catalog_claims({"catalog_claims": [{"claim_id": "claim_yes", "query_entity_id": "item_anniversary_bass", "state": "owned", "evidence_state": "structured_claim"}, {"claim_id": "claim_no", "query_entity_id": "item_anniversary_bass", "state": "confirmed_missing", "evidence_state": "structured_claim"}]}, index_rows())["resolutions"][0]
        self.assertEqual(conflict["resolution_status"], "conflict"); self.assertEqual(conflict["ownership_state"], "unknown"); self.assertFalse(conflict["model_feature"])

    def test_source_or_candidate_rows_are_not_promoted_and_unknown_ids_fail_closed(self):
        rows = index_rows(); source = next(row["query_entity_id"] for row in rows if row["query_entity_type"] == "source_reference" and row["canonical_item_ids"]); candidate = next(row["query_entity_id"] for row in rows if row["query_entity_type"] == "review_candidate")
        result = resolve_catalog_claims({"catalog_claims": [{"claim_id": "claim_source", "query_entity_id": source, "state": "owned", "evidence_state": "structured_claim"}, {"claim_id": "claim_candidate", "query_entity_id": candidate, "state": "owned", "evidence_state": "structured_claim"}, {"claim_id": "claim_missing", "query_entity_id": "item_not_in_catalog", "state": "owned", "evidence_state": "structured_claim"}]}, rows)
        self.assertEqual([row["resolution_status"] for row in result["resolutions"]], ["review_only", "unknown_reference", "review_only"]); self.assertTrue(all(row["ownership_state"] == "unknown" for row in result["resolutions"]))

    def test_unknown_evidence_cannot_assert_owned_or_missing(self):
        for state in ("owned", "confirmed_missing"):
            with self.assertRaisesRegex(ValueError, "without structured evidence"):
                resolve_catalog_claims({"catalog_claims": [{"claim_id": f"claim_{state}", "query_entity_id": "item_anniversary_bass", "state": state, "evidence_state": "unknown"}]}, index_rows())

if __name__ == "__main__": unittest.main()
