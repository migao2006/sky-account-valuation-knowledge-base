"""Integrity tests for the review-only vendor collectible registry."""
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

from tools.normalize.build_vendor_collectible_registry import (  # noqa: E402
    COLLECTIBLE_TYPES,
    build_registry,
    normalized_name,
)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class VendorCollectibleRegistryTests(unittest.TestCase):
    def test_registry_is_deterministic_and_has_the_audited_partition(self):
        command = [sys.executable, "tools/normalize/build_vendor_collectible_registry.py", "--root", str(ROOT)]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            first, second = directory / "first.jsonl", directory / "second.jsonl"
            first_summary, second_summary = directory / "first.json", directory / "second.json"
            subprocess.run([*command, "--output", str(first), "--summary", str(first_summary)], cwd=ROOT, check=True, capture_output=True, text=True)
            subprocess.run([*command, "--output", str(second), "--summary", str(second_summary)], cwd=ROOT, check=True, capture_output=True, text=True)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_summary.read_bytes(), second_summary.read_bytes())
            summary = json.loads(first_summary.read_text(encoding="utf-8"))
        self.assertEqual(summary["collectible_type_count"], 17)
        self.assertEqual(summary["collectible_record_count"], 1758)
        self.assertEqual(summary["excluded_non_collectible_count"], 1508)
        self.assertEqual(summary["canonical_link_count"], 64)
        self.assertEqual(summary["candidate_link_count"], 296)
        self.assertEqual(summary["unresolved_count"], 1398)
        self.assertEqual(summary["cross_type_conflict_cluster_count"], 16)
        self.assertEqual(summary["canonical_write"], "not_performed")

    def test_committed_registry_has_unique_vendor_identity_and_quarantines_conflicts(self):
        rows = read_jsonl(ROOT / "data/review/vendor-collectible-registry.jsonl")
        summary = json.loads((ROOT / "data/review/vendor-collectible-registry-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 1758)
        self.assertEqual(len({row["vendor_guid"] for row in rows}), len(rows))
        self.assertEqual(len({row["vendor_item_id"] for row in rows}), len(rows))
        self.assertTrue(all(row["vendor_item_type"] in COLLECTIBLE_TYPES for row in rows))
        self.assertEqual(Counter(row["link_status"] for row in rows), Counter({"unresolved": 1398, "candidate_link": 296, "canonical_link": 64}))
        conflicts = [row for row in rows if row["name_cluster"]["cross_type_conflict"]]
        self.assertEqual({row["name_cluster"]["cluster_id"] for row in conflicts}.__len__(), 11)
        self.assertEqual(summary["cross_type_conflict_cluster_count"], 16)
        self.assertEqual(summary["cross_type_conflict_collectible_cluster_count"], 11)
        self.assertEqual(len(conflicts), summary["cross_type_conflict_collectible_record_count"])
        self.assertTrue(all(row["review_status"] == "quarantined_cross_type_conflict" for row in conflicts))
        self.assertTrue(all(row["canonical_write"] == "not_performed" for row in rows))
        self.assertTrue(all(row["model_feature_status"] == "excluded_pending_verification" for row in rows))

    def test_cross_type_cluster_uses_all_vendor_records_not_only_collectibles(self):
        snapshot = {"items": [
            {"id": 1, "guid": "emote-guid", "name": "Shared Name", "type": "Emote"},
            {"id": 2, "guid": "special-guid", "name": "Shared Name", "type": "Special"},
        ]}
        crosswalk = [
            {"snapshot_id": "vendor_skygame_data_1_3_4", "source_id": "source_skygame_data_1_3_4", "vendor_guid": "emote-guid", "vendor_item_id": 1, "vendor_name": "Shared Name", "vendor_item_type": "Emote", "match_status": "unmatched_vendor_item", "canonical_item_ids": [], "candidate_item_ids": []},
            {"snapshot_id": "vendor_skygame_data_1_3_4", "source_id": "source_skygame_data_1_3_4", "vendor_guid": "special-guid", "vendor_item_id": 2, "vendor_name": "Shared Name", "vendor_item_type": "Special", "match_status": "excluded_non_collectible", "canonical_item_ids": [], "candidate_item_ids": []},
        ]
        rows, summary = build_registry(snapshot, crosswalk)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["normalized_name"], normalized_name("Shared Name"))
        self.assertTrue(rows[0]["name_cluster"]["cross_type_conflict"])
        self.assertEqual(rows[0]["review_status"], "quarantined_cross_type_conflict")
        self.assertEqual(summary["cross_type_conflict_cluster_count"], 1)

    def test_crosswalk_snapshot_identity_mismatch_is_rejected(self):
        snapshot = {"items": [{"id": 1, "guid": "guid", "name": "Cape", "type": "Cape"}]}
        crosswalk = [{"snapshot_id": "vendor_skygame_data_1_3_4", "source_id": "source_skygame_data_1_3_4", "vendor_guid": "guid", "vendor_item_id": 1, "vendor_name": "Changed", "vendor_item_type": "Cape", "match_status": "unmatched_vendor_item", "canonical_item_ids": [], "candidate_item_ids": []}]
        with self.assertRaisesRegex(ValueError, "differs from pinned vendor snapshot"):
            build_registry(snapshot, crosswalk)


if __name__ == "__main__":
    unittest.main()
