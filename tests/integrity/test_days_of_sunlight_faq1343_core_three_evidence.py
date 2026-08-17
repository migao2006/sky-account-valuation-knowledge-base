"""Regression tests for the bounded FAQ 1343 Days of Sunlight core-three cohort."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.normalize.apply_days_of_sunlight_faq1343_core_three_cohort import ITEMS, DaysOfSunlightEvidenceError, build, verify  # noqa: E402
from tools.validate.schema_validator import OfflineSchemaValidator  # noqa: E402


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class DaysOfSunlightFaq1343CoreThreeEvidenceTests(unittest.TestCase):
    def test_replays_pinned_facts_and_preserves_nonclaims(self):
        self.assertEqual(verify(ROOT), [])
        _targets, ledger = build(ROOT)
        self.assertEqual(len(ledger), 24)
        validator = OfflineSchemaValidator(ROOT / "schemas")
        self.assertTrue(all(not validator.validate(row, ROOT / "schemas/review/canonical-item-field-evidence.schema.json") for row in ledger))
        snapshot = json.loads((ROOT / "data/source/research/tgc-faq-1343-days-of-sunlight-core-three.json").read_text(encoding="utf-8"))
        self.assertFalse(validator.validate(snapshot, ROOT / "schemas/knowledge/days-of-sunlight-faq-1343-core-three-fact-snapshot.schema.json"))
        self.assertTrue(any("Sunlight Beach Shorts outfit" in claim for claim in snapshot["non_claims"]))
        self.assertFalse(any("beach_shorts" in item_id for item_id, *_ in ITEMS))
        items = {row["item_id"]: row for row in rows(ROOT / "knowledge/items/items.jsonl")}
        expected_feature_status = {
            "item_days_of_sunlight_manta_float": "eligible",
            "item_days_of_sunlight_helios_hoops": "excluded_pending_verification",
            "item_days_of_sunlight_woven_wrap": "excluded_pending_verification",
        }
        for item_id, _vendor, _guid, _vendor_name, official_name, *_tail in ITEMS:
            item = items[item_id]
            self.assertEqual(item["canonical_name_en"], official_name)
            self.assertEqual((item["availability_status"], item["permanent_account_item"], item["first_release_date"], item["model_feature_status"], item["set_ids"], item["visual_reference_ids"]), ("unknown", "unknown", None, expected_feature_status[item_id], [], []))
        availability = {row["availability_id"]: row for row in rows(ROOT / "knowledge/acquisition/availability-events.jsonl")}
        for item_id, *_ in ITEMS:
            row = availability["availability_days_of_sunlight_faq1343_" + item_id.removeprefix("item_days_of_sunlight_")]
            self.assertEqual((row["availability_status"], row["start_date"], row["end_date"], row["verification_status"]), ("limited_time", "2024-08-26", "2024-09-08", "verified"))

    def test_tampered_snapshot_or_nonclaim_promotion_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for relative in ("knowledge", "data/source", "data/review"):
                shutil.copytree(ROOT / relative, root / relative)
            path = root / "data/source/research/tgc-faq-1343-days-of-sunlight-core-three.json"
            path.write_text(path.read_text(encoding="utf-8").replace("Sunlight Manta Float", "Changed Manta Float", 1), encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(DaysOfSunlightEvidenceError, "snapshot hash mismatch"):
                build(root)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for relative in ("knowledge", "data", "schemas"):
                shutil.copytree(ROOT / relative, root / relative)
            command = [sys.executable, str(ROOT / "tools/normalize/apply_days_of_sunlight_faq1343_core_three_cohort.py"), "--root", str(root), "--apply"]
            subprocess.run(command, check=True, capture_output=True, text=True)
            tracked = [root / "knowledge/items/items.jsonl", root / "knowledge/acquisition/availability-events.jsonl", root / "data/review/days-of-sunlight-faq1343-core-three-canonical-evidence.jsonl"]
            before = {tracked_path: tracked_path.read_bytes() for tracked_path in tracked}
            subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertEqual(before, {tracked_path: tracked_path.read_bytes() for tracked_path in tracked})
            path = root / "knowledge/items/items.jsonl"; data = rows(path)
            row = next(row for row in data if row["item_id"] == "item_days_of_sunlight_helios_hoops")
            row["availability_status"] = "permanent"; row["model_feature_status"] = "eligible"
            path.write_text("".join(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n" for value in data), encoding="utf-8", newline="\n")
            self.assertIn("committed target differs from replayable apply contract: knowledge/items/items.jsonl", verify(root))


if __name__ == "__main__":
    unittest.main()
