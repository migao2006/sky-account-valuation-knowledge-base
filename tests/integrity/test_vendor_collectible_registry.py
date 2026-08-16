"""Integrity tests for source-scoped vendor reference identities."""
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

from tools.normalize.build_source_scoped_item_identities import (  # noqa: E402
    COLLECTIBLE_TYPES,
    build_source_scoped_identities,
    normalized_name,
    reference_identity_id,
    verify_snapshot_bytes,
)


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class SourceScopedItemIdentityTests(unittest.TestCase):
    def test_builder_is_deterministic_and_has_the_audited_partition(self):
        command = [sys.executable, "tools/normalize/build_source_scoped_item_identities.py", "--root", str(ROOT)]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            first, second = directory / "first.jsonl", directory / "second.jsonl"
            first_summary, second_summary = directory / "first.json", directory / "second.json"
            subprocess.run([*command, "--output", str(first), "--summary", str(first_summary)], cwd=ROOT, check=True, capture_output=True, text=True)
            subprocess.run([*command, "--output", str(second), "--summary", str(second_summary)], cwd=ROOT, check=True, capture_output=True, text=True)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_summary.read_bytes(), second_summary.read_bytes())
            summary = json.loads(first_summary.read_text(encoding="utf-8"))
        self.assertEqual(summary["collectible_record_count"], 1758)
        self.assertEqual(summary["excluded_non_collectible_count"], 1508)
        self.assertEqual(summary["candidate_link_count"], 296)
        self.assertEqual(summary["canonical_link_count"] + summary["candidate_link_count"] + summary["unresolved_count"], 1758)
        self.assertEqual(summary["cross_type_conflict_cluster_count"], 16)
        self.assertEqual(summary["promotion_eligibility"], "prohibited")

    def test_committed_rows_are_source_scoped_and_quarantine_conflicts(self):
        rows = read_jsonl(ROOT / "data/normalized/source-scoped-item-identities.jsonl")
        summary = json.loads((ROOT / "data/normalized/source-scoped-item-identities-summary.json").read_text(encoding="utf-8"))
        metadata = json.loads((ROOT / "data/source/vendor/skygame-data-1.3.4-metadata.json").read_text(encoding="utf-8"))
        canonical_sources = {row["source_id"] for row in read_jsonl(ROOT / "knowledge/sources/sources.jsonl")}
        self.assertEqual(len(rows), 1758)
        self.assertEqual(len({row["vendor_guid"] for row in rows}), len(rows))
        self.assertEqual(len({row["vendor_item_id"] for row in rows}), len(rows))
        self.assertEqual(len({row["reference_identity_id"] for row in rows}), len(rows))
        self.assertTrue(all(row["observed_item_type"] in COLLECTIBLE_TYPES for row in rows))
        self.assertTrue(all(row["identity_scope"] == "source_snapshot_only" for row in rows))
        self.assertTrue(all(row["canonical_identity_status"] == "unverified" for row in rows))
        self.assertTrue(all(row["promotion_eligibility"] == "prohibited" for row in rows))
        self.assertTrue(all(row["model_feature_status"] == "excluded_pending_verification" for row in rows))
        self.assertTrue(all(row["reference_identity_id"] == reference_identity_id(row["source_id"], row["snapshot_id"], row["vendor_guid"]) for row in rows))
        self.assertEqual(Counter(row["link_status"] for row in rows), Counter({"unresolved": summary["unresolved_count"], "candidate_link": summary["candidate_link_count"], "canonical_link": summary["canonical_link_count"]}))
        conflicts = [row for row in rows if row["name_cluster"]["cross_type_conflict"]]
        self.assertEqual({row["name_cluster"]["cluster_id"] for row in conflicts}.__len__(), 11)
        self.assertEqual(summary["cross_type_conflict_cluster_count"], 16)
        self.assertEqual(summary["cross_type_conflict_collectible_cluster_count"], 11)
        self.assertEqual(len(conflicts), summary["cross_type_conflict_collectible_record_count"])
        self.assertTrue(all(row["review_status"] == "quarantined_cross_type_conflict" for row in conflicts))
        self.assertTrue(all(row["source_snapshot_sha256"] == summary["source_snapshot_sha256"] for row in rows))
        self.assertIn(summary["source_id"], canonical_sources)
        self.assertEqual(summary["source_id"], metadata["source_id"])
        self.assertEqual(summary["snapshot_id"], metadata["snapshot_id"])
        self.assertEqual(summary["source_snapshot_sha256"], metadata["snapshot_sha256"])

    def test_cross_type_cluster_uses_all_vendor_records_not_only_collectibles(self):
        snapshot = {"items": [
            {"id": 1, "guid": "emote-guid", "name": "Shared Name", "type": "Emote"},
            {"id": 2, "guid": "special-guid", "name": "Shared Name", "type": "Special"},
        ]}
        crosswalk = [
            {"snapshot_id": "vendor_skygame_data_1_3_4", "source_id": "source_skygame_data_1_3_4", "vendor_guid": "emote-guid", "vendor_item_id": 1, "vendor_name": "Shared Name", "vendor_item_type": "Emote", "match_status": "unmatched_vendor_item", "canonical_item_ids": [], "candidate_item_ids": []},
            {"snapshot_id": "vendor_skygame_data_1_3_4", "source_id": "source_skygame_data_1_3_4", "vendor_guid": "special-guid", "vendor_item_id": 2, "vendor_name": "Shared Name", "vendor_item_type": "Special", "match_status": "excluded_non_collectible", "canonical_item_ids": [], "candidate_item_ids": []},
        ]
        metadata = {"snapshot_id": "vendor_skygame_data_1_3_4", "source_id": "source_skygame_data_1_3_4", "snapshot_sha256": "A" * 64, "record_count": 2}
        rows, summary = build_source_scoped_identities(snapshot, metadata, crosswalk)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["normalized_name"], normalized_name("Shared Name"))
        self.assertTrue(rows[0]["name_cluster"]["cross_type_conflict"])
        self.assertEqual(rows[0]["review_status"], "quarantined_cross_type_conflict")
        self.assertEqual(summary["cross_type_conflict_cluster_count"], 1)

    def test_crosswalk_snapshot_identity_mismatch_is_rejected(self):
        snapshot = {"items": [{"id": 1, "guid": "guid", "name": "Cape", "type": "Cape"}]}
        crosswalk = [{"snapshot_id": "vendor_skygame_data_1_3_4", "source_id": "source_skygame_data_1_3_4", "vendor_guid": "guid", "vendor_item_id": 1, "vendor_name": "Changed", "vendor_item_type": "Cape", "match_status": "unmatched_vendor_item", "canonical_item_ids": [], "candidate_item_ids": []}]
        metadata = {"snapshot_id": "vendor_skygame_data_1_3_4", "source_id": "source_skygame_data_1_3_4", "snapshot_sha256": "A" * 64, "record_count": 1}
        with self.assertRaisesRegex(ValueError, "differs from pinned vendor snapshot"):
            build_source_scoped_identities(snapshot, metadata, crosswalk)

    def test_snapshot_bytes_must_match_pinned_metadata_before_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            snapshot_path = Path(temporary) / "snapshot.json"
            snapshot_path.write_text('{"items":[]}', encoding="utf-8")
            metadata = {"snapshot_sha256": "A" * 64}
            with self.assertRaisesRegex(ValueError, "snapshot bytes"):
                verify_snapshot_bytes(snapshot_path, metadata)


if __name__ == "__main__":
    unittest.main()
