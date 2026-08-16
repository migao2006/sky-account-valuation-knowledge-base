"""Integrity tests for the derived, offline catalog query index."""
from __future__ import annotations
import json
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.normalize.build_catalog_query_index import build_catalog_query_index, read_jsonl  # noqa: E402

class CatalogQueryIndexTests(unittest.TestCase):
    def test_committed_index_has_closed_truth_layers_and_no_premature_promotion(self):
        rows = read_jsonl(ROOT / "data/normalized/catalog-query-index.jsonl")
        summary = json.loads((ROOT / "data/normalized/catalog-query-index-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 2474); self.assertEqual(len({row["query_entity_id"] for row in rows}), len(rows))
        self.assertEqual(Counter(row["query_entity_type"] for row in rows), Counter({"source_reference": 1758, "review_candidate": 622, "canonical_item": 94}))
        self.assertEqual(summary["canonical_resolved_eligible_count"], 0)
        self.assertTrue(all(row["model_feature_status"] == "excluded_pending_verification" for row in rows))
        self.assertTrue(all(row["resolution_eligibility"] == "review_only" for row in rows))
        self.assertTrue(all(row["truth_level"] != "canonical_knowledge" or row["verification_status"] == "needs_review" for row in rows))
        collided = {key for row in rows for key in row["ambiguous_lookup_keys"]}
        self.assertEqual(summary["ambiguous_lookup_key_count"], len(collided))
        self.assertEqual(summary["rows_with_lookup_key_collisions"], sum(row["has_lookup_key_collision"] for row in rows))
        self.assertGreater(summary["ambiguous_lookup_key_count"], 0)
        rain_mother = [row for row in rows if "雨媽" in row["lookup_keys"]]
        self.assertGreaterEqual(len(rain_mother), 2)
        self.assertTrue(all("雨媽".casefold() in row["ambiguous_lookup_keys"] for row in rain_mother))

    def test_builder_is_deterministic_and_rejects_changed_snapshot_bytes(self):
        command = [sys.executable, "tools/normalize/build_catalog_query_index.py", "--root", str(ROOT)]
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary); first = temp / "one.jsonl"; second = temp / "two.jsonl"
            subprocess.run([*command, "--output", str(first), "--summary", str(temp / "one.json")], cwd=ROOT, check=True, capture_output=True, text=True)
            subprocess.run([*command, "--output", str(second), "--summary", str(temp / "two.json")], cwd=ROOT, check=True, capture_output=True, text=True)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            changed_snapshot = temp / "snapshot.json"; changed_snapshot.write_text('{"items":[]}', encoding="utf-8")
            metadata = json.loads((ROOT / "data/source/vendor/skygame-data-1.3.4-metadata.json").read_text(encoding="utf-8"))
            with self.assertRaisesRegex(ValueError, "snapshot bytes"):
                build_catalog_query_index(read_jsonl(ROOT / "knowledge/items/items.jsonl"), read_jsonl(ROOT / "knowledge/aliases/item-aliases.jsonl"), read_jsonl(ROOT / "data/review/item-candidates.jsonl"), read_jsonl(ROOT / "data/normalized/source-scoped-item-identities.jsonl"), changed_snapshot, metadata)

    def test_canonical_alias_master_is_indexed_and_id_layers_are_disjoint(self):
        rows = read_jsonl(ROOT / "data/normalized/catalog-query-index.jsonl")
        by_id = {row["query_entity_id"]: row for row in rows}
        alias = next(
            row for row in read_jsonl(ROOT / "knowledge/aliases/item-aliases.jsonl")
            if row.get("target_type") == "item" and row.get("alias_text")
        )
        self.assertIn(alias["alias_text"], by_id[alias["target_id"]]["lookup_keys"])
        canonical_ids = {row["query_entity_id"] for row in rows if row["query_entity_type"] == "canonical_item"}
        candidate_ids = {row["query_entity_id"] for row in rows if row["query_entity_type"] == "review_candidate"}
        self.assertFalse(canonical_ids & candidate_ids)

if __name__ == "__main__": unittest.main()
