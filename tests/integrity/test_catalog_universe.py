"""Tests for the closed offline vendor catalog reconciliation universe."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "normalize"))

from build_catalog_universe import build_catalog_universe


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class CatalogUniverseTests(unittest.TestCase):
    def test_committed_universe_is_closed_and_one_to_one_with_snapshot(self):
        universe = read_jsonl(ROOT / "data/review/catalog-universe.jsonl")
        snapshot = json.loads((ROOT / "data/source/vendor/skygame-data-1.3.4-items.json").read_text(encoding="utf-8"))["items"]
        summary = json.loads((ROOT / "data/review/catalog-universe-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(len(universe), len(snapshot))
        self.assertEqual({(row["vendor_guid"], row["vendor_item_id"]) for row in universe}, {(row["guid"], row["id"]) for row in snapshot})
        self.assertEqual(len({row["universe_id"] for row in universe}), len(universe))
        counts = {name: sum(row["classification"] == name for row in universe) for name in ("canonical_linked", "candidate_linked", "unmatched", "explicitly_excluded")}
        self.assertEqual(counts, {"canonical_linked": 64, "candidate_linked": 296, "unmatched": 1398, "explicitly_excluded": 1508})
        self.assertEqual(summary["expected_count"], sum(counts.values()))
        self.assertEqual(summary["vendor_item_count"], len(snapshot))
        self.assertEqual(summary["reconciliation_status"], "reconciled")
        for row in universe:
            if row["classification"] == "canonical_linked":
                self.assertEqual(len(row["canonical_item_ids"]), 1)
                self.assertEqual(row["candidate_item_ids"], [])
            elif row["classification"] == "candidate_linked":
                self.assertEqual(row["canonical_item_ids"], [])
                self.assertEqual(len(row["candidate_item_ids"]), 1)
            else:
                self.assertEqual(row["canonical_item_ids"], [])
                self.assertEqual(row["candidate_item_ids"], [])

    def test_rebuild_is_deterministic(self):
        command = [sys.executable, "tools/normalize/build_catalog_universe.py", "--root", str(ROOT)]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            first, second = directory / "first.jsonl", directory / "second.jsonl"
            first_summary, second_summary = directory / "first.json", directory / "second.json"
            subprocess.run([*command, "--output", str(first), "--summary", str(first_summary)], cwd=ROOT, check=True, capture_output=True, text=True)
            subprocess.run([*command, "--output", str(second), "--summary", str(second_summary)], cwd=ROOT, check=True, capture_output=True, text=True)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_summary.read_bytes(), second_summary.read_bytes())

    def test_duplicate_or_incomplete_crosswalk_is_rejected(self):
        snapshot = {"items": [{"id": 1, "guid": "one", "name": "Cape", "type": "Cape", "subtype": None, "group": None}]}
        metadata = {"snapshot_id": "vendor_skygame_data_1_3_4", "source_id": "source_skygame_data_1_3_4", "snapshot_sha256": "A" * 64}
        with self.assertRaisesRegex(ValueError, "does not cover snapshot"):
            build_catalog_universe(snapshot, metadata, [])
        duplicate = {"snapshot_id": metadata["snapshot_id"], "source_id": metadata["source_id"], "vendor_item_id": 1, "vendor_guid": "one", "vendor_name": "Cape", "vendor_item_type": "Cape", "canonical_item_ids": ["item_cape"], "candidate_item_ids": [], "match_status": "matched_canonical_name", "review_status": "needs_review"}
        with self.assertRaisesRegex(ValueError, "duplicate vendor pair"):
            build_catalog_universe(snapshot, metadata, [duplicate, duplicate])


if __name__ == "__main__":
    unittest.main()
