"""Integrity tests for the fixed offline SkyGame-Data catalog evidence path."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "validate"))

from tools.normalize.compare_vendor_catalog import crosswalk, verify_snapshot
from tools.normalize.import_skygame_catalog_snapshot import build_snapshot, canonical_json
from tools.validate.validate import validate_vendor_evidence_links


VENDOR = ROOT / "data/source/vendor"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class VendorCatalogImportTests(unittest.TestCase):
    def test_vendored_package_rebuilds_the_committed_field_limited_snapshot(self):
        snapshot, metadata = build_snapshot(VENDOR / "skygame-data-1.3.4.tgz")
        committed_snapshot = json.loads((VENDOR / "skygame-data-1.3.4-items.json").read_text(encoding="utf-8"))
        committed_metadata = json.loads((VENDOR / "skygame-data-1.3.4-metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot, committed_snapshot)
        self.assertEqual(metadata["record_count"], 3266)
        self.assertEqual(metadata["license"], "MIT")
        self.assertEqual(metadata["source_git_commit"], "b022d813b2e4bc09d5f2967d1bac77e49c595a75")
        self.assertEqual(metadata["everything_asset_member"], "package/assets/everything.json")
        self.assertTrue(metadata["everything_items_match"])
        self.assertEqual(hashlib.sha256(canonical_json(snapshot)).hexdigest().upper(), committed_metadata["snapshot_sha256"])

    def test_crosswalk_is_deterministic_and_does_not_promote_canonical_items(self):
        command = [sys.executable, "tools/normalize/compare_vendor_catalog.py", "--root", str(ROOT)]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            first, second = directory / "first.jsonl", directory / "second.jsonl"
            first_summary, second_summary = directory / "first-summary.json", directory / "second-summary.json"
            first_evidence, second_evidence = directory / "first-evidence.jsonl", directory / "second-evidence.jsonl"
            subprocess.run([*command, "--output", str(first), "--summary", str(first_summary), "--field-evidence", str(first_evidence)], cwd=ROOT, check=True, capture_output=True, text=True)
            subprocess.run([*command, "--output", str(second), "--summary", str(second_summary), "--field-evidence", str(second_evidence)], cwd=ROOT, check=True, capture_output=True, text=True)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_summary.read_bytes(), second_summary.read_bytes())
            self.assertEqual(first_evidence.read_bytes(), second_evidence.read_bytes())
            summary = json.loads(first_summary.read_text(encoding="utf-8"))
        self.assertEqual(summary["vendor_item_count"], 3266)
        self.assertEqual(summary["canonical_matched_count"], 67)
        self.assertEqual(summary["candidate_matched_count"], 296)
        self.assertEqual(summary["unmatched_collectible_count"], 1395)
        self.assertEqual(summary["field_evidence_count"], 296)
        self.assertEqual(summary["canonical_promotion"], "not_performed")
        canonical_ids = {row["item_id"] for row in read_jsonl(ROOT / "knowledge/items/items.jsonl")}
        rows = read_jsonl(ROOT / "data/review/skygame-data-1.3.4-crosswalk.jsonl")
        self.assertEqual(len(rows), 3266)
        self.assertEqual(len({row["vendor_item_id"] for row in rows}), len(rows))
        self.assertTrue(all(set(row["canonical_item_ids"]) <= canonical_ids for row in rows))
        candidate_ids = {row["candidate_item_id"] for row in read_jsonl(ROOT / "data/review/item-candidates.jsonl")}
        self.assertTrue(all(set(row["candidate_item_ids"]) <= candidate_ids for row in rows))
        self.assertTrue(all(row["review_status"] == "needs_review" for row in rows if row["match_status"] in {"unmatched_vendor_item", "ambiguous_canonical_match"}))
        evidence = read_jsonl(ROOT / "data/review/skygame-data-1.3.4-item-evidence.jsonl")
        self.assertEqual(len(evidence), 296)
        self.assertTrue(all(row["candidate_item_id"] in candidate_ids for row in evidence))
        self.assertTrue(all(row["canonical_promotion"] == "prohibited_without_independent_review" for row in evidence))

    def test_ambiguous_name_is_quarantined_for_review(self):
        snapshot = {"items": [{"id": 9, "guid": "vendor-guid", "name": "Same Item", "type": "Cape"}]}
        metadata = {"snapshot_id": "vendor_skygame_data_1_3_4", "source_id": "source_skygame_data_1_3_4", "snapshot_sha256": "unused"}
        items = [
            {"item_id": "item_one", "canonical_name_en": "Same Item", "aliases": []},
            {"item_id": "item_two", "canonical_name_en": "Same Item", "aliases": []},
        ]
        rows, summary, evidence = crosswalk(snapshot, metadata, items, [])
        self.assertEqual(rows[0]["match_status"], "ambiguous_canonical_match")
        self.assertEqual(rows[0]["review_status"], "needs_review")
        self.assertEqual(rows[0]["canonical_item_ids"], ["item_one", "item_two"])
        self.assertEqual(summary["canonical_promotion"], "not_performed")
        self.assertEqual(evidence, [])

    def test_candidate_name_match_is_secondary_evidence_not_a_promotion(self):
        snapshot = {"items": [{"id": 10, "guid": "candidate-guid", "name": "Candidate Cape", "type": "Cape"}]}
        metadata = {"snapshot_id": "vendor_skygame_data_1_3_4", "source_id": "source_skygame_data_1_3_4", "snapshot_sha256": "A" * 64}
        rows, summary, evidence = crosswalk(snapshot, metadata, [], [], [{"candidate_item_id": "item_candidate_cape", "candidate_name_en": "Candidate Cape"}])
        self.assertEqual(rows[0]["match_status"], "matched_candidate_name")
        self.assertEqual(rows[0]["canonical_item_ids"], [])
        self.assertEqual(rows[0]["candidate_item_ids"], ["item_candidate_cape"])
        self.assertEqual(summary["candidate_matched_count"], 1)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]["locator"], "candidate-guid")
        self.assertEqual(evidence[0]["canonical_promotion"], "prohibited_without_independent_review")

    def test_canonical_match_takes_precedence_over_same_named_candidate(self):
        snapshot = {"items": [{"id": 11, "guid": "canonical-guid", "name": "Known Cape", "type": "Cape"}]}
        metadata = {"snapshot_id": "vendor_skygame_data_1_3_4", "source_id": "source_skygame_data_1_3_4", "snapshot_sha256": "B" * 64}
        canonical = [{"item_id": "item_known_cape", "canonical_name_en": "Known Cape", "aliases": []}]
        rows, summary, evidence = crosswalk(snapshot, metadata, canonical, [], [{"candidate_item_id": "item_candidate_known_cape", "candidate_name_en": "Known Cape"}])
        self.assertEqual(rows[0]["match_status"], "matched_canonical_name")
        self.assertEqual(rows[0]["canonical_item_ids"], ["item_known_cape"])
        self.assertEqual(rows[0]["candidate_item_ids"], ["item_candidate_known_cape"])
        self.assertEqual(summary["candidate_matched_count"], 0)
        self.assertEqual(evidence, [])

    def test_hash_mismatch_is_rejected_before_matching(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "data/source/vendor").mkdir(parents=True)
            snapshot_path = root / "data/source/vendor/snapshot.json"
            tarball_path = root / "data/source/vendor/package.tgz"
            snapshot_path.write_text('{"items": []}\n', encoding="utf-8")
            tarball_path.write_bytes(b"fixed-package")
            metadata_path = root / "data/source/vendor/metadata.json"
            metadata_path.write_text(json.dumps({
                "snapshot_id": "vendor_skygame_data_1_3_4", "source_id": "source_skygame_data_1_3_4", "source_package": "skygame-data", "source_version": "1.3.4", "source_git_commit": "b022d813b2e4bc09d5f2967d1bac77e49c595a75", "license": "MIT", "tarball_path": "data/source/vendor/package.tgz", "tarball_sha256": hashlib.sha256(b"fixed-package").hexdigest().upper(), "snapshot_path": "data/source/vendor/snapshot.json", "snapshot_sha256": "0" * 64, "record_count": 0, "canonical_promotion": "prohibited_without_independent_review"
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "snapshot SHA-256 mismatch"):
                verify_snapshot(root, snapshot_path, metadata_path)

    def test_synchronized_claim_and_hash_tampering_is_rejected_against_snapshot(self):
        metadata = json.loads((VENDOR / "skygame-data-1.3.4-metadata.json").read_text(encoding="utf-8"))
        snapshot = json.loads((VENDOR / "skygame-data-1.3.4-items.json").read_text(encoding="utf-8"))
        crosswalk = read_jsonl(ROOT / "data/review/skygame-data-1.3.4-crosswalk.jsonl")
        candidates = {row["candidate_item_id"]: row for row in read_jsonl(ROOT / "data/review/item-candidates.jsonl")}
        evidence = read_jsonl(ROOT / "data/review/skygame-data-1.3.4-item-evidence.jsonl")
        self.assertEqual(validate_vendor_evidence_links(metadata, snapshot, crosswalk, candidates, evidence), [])
        tampered = deepcopy(evidence)
        tampered[0]["claim_value"] = "Synchronized Tampered Name"
        tampered[0]["claim_value_hash"] = hashlib.sha256("synchronizedtamperedname".encode("utf-8")).hexdigest().upper()
        errors = validate_vendor_evidence_links(metadata, snapshot, crosswalk, candidates, tampered)
        self.assertTrue(any("claim value differs" in error for error in errors))
        self.assertTrue(any("claim hash differs" in error for error in errors))

    def test_duplicate_or_missing_evidence_pair_is_rejected(self):
        metadata = json.loads((VENDOR / "skygame-data-1.3.4-metadata.json").read_text(encoding="utf-8"))
        snapshot = json.loads((VENDOR / "skygame-data-1.3.4-items.json").read_text(encoding="utf-8"))
        crosswalk = read_jsonl(ROOT / "data/review/skygame-data-1.3.4-crosswalk.jsonl")
        candidates = {row["candidate_item_id"]: row for row in read_jsonl(ROOT / "data/review/item-candidates.jsonl")}
        evidence = read_jsonl(ROOT / "data/review/skygame-data-1.3.4-item-evidence.jsonl")
        errors = validate_vendor_evidence_links(metadata, snapshot, crosswalk, candidates, [*evidence, deepcopy(evidence[0])])
        self.assertTrue(any("duplicate candidate evidence pair" in error for error in errors))
        missing_errors = validate_vendor_evidence_links(metadata, snapshot, crosswalk, candidates, evidence[1:])
        self.assertTrue(any("candidate crosswalk/evidence pairs differ" in error for error in missing_errors))


if __name__ == "__main__":
    unittest.main()
