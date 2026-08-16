"""Regression tests for the bounded FAQ 1356 Moomintroll cohort."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "validate"))

from tools.normalize.apply_moomintroll_accessory_set_cohort import (  # noqa: E402
    ITEMS, MoominEvidenceError, build, verify,
)
from tools.validate.schema_validator import OfflineSchemaValidator  # noqa: E402


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class MoomintrollAccessorySetEvidenceTests(unittest.TestCase):
    def test_replays_fact_only_official_and_pinned_secondary_evidence(self):
        self.assertEqual(verify(ROOT), [])
        _targets, evidence = build(ROOT)
        self.assertEqual(len(evidence), 15)
        validator = OfflineSchemaValidator(ROOT / "schemas")
        evidence_schema = ROOT / "schemas/review/canonical-item-field-evidence.schema.json"
        self.assertTrue(all(not validator.validate(row, evidence_schema) for row in evidence))
        snapshot = json.loads((ROOT / "data/source/research/tgc-faq-1356-moomintroll-accessory-set.json").read_text(encoding="utf-8"))
        self.assertFalse(validator.validate(snapshot, ROOT / "schemas/knowledge/moomintroll-accessory-set-fact-snapshot.schema.json"))
        items = {row["item_id"]: row for row in rows(ROOT / "knowledge/items/items.jsonl")}
        self.assertEqual({item_id: items[item_id]["canonical_name_en"] for item_id, *_rest in ITEMS}, {item_id: name for item_id, _vendor_id, name, _vendor_type in ITEMS})
        for item_id, *_rest in ITEMS:
            item = items[item_id]
            self.assertEqual(item["item_category"], "accessory")
            self.assertEqual(item["original_cost"], "bundle_only")
            self.assertEqual(item["availability_status"], "unknown")
            self.assertEqual(item["permanent_account_item"], "unknown")
            self.assertIsNone(item["first_release_date"])
            self.assertEqual(item["model_feature_status"], "excluded_pending_verification")
        set_row = next(row for row in rows(ROOT / "knowledge/sets/item-sets.jsonl") if row["set_id"] == "set_moomin_iap")
        self.assertEqual(set_row["required_item_ids"], [item_id for item_id, *_rest in ITEMS])
        self.assertEqual(set_row["optional_item_ids"], [])
        availability = {row["availability_id"]: row for row in rows(ROOT / "knowledge/acquisition/availability-events.jsonl")}
        for item_id, *_rest in ITEMS:
            row = availability["availability_moomin_faq1356_" + item_id.removeprefix("item_moomin_")]
            self.assertEqual((row["availability_status"], row["start_date"], row["end_date"]), ("limited_time", "2024-10-14", "2024-12-29"))
            self.assertEqual(row["verification_status"], "needs_review")
        self.assertIn("historical_pack_price_usd", {row["field_path"] for row in evidence})
        self.assertFalse(any(row["field_path"] == "availability_status" for row in evidence))

    def test_changed_snapshot_and_missing_registry_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for relative in ("knowledge", "data/source", "data/review"):
                shutil.copytree(ROOT / relative, root / relative)
            path = root / "data/source/research/tgc-faq-1356-moomintroll-accessory-set.json"
            path.write_text(path.read_text(encoding="utf-8").replace("Moomintroll Accessory Set", "Changed Set", 1), encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(MoominEvidenceError, "official snapshot hash mismatch"):
                build(root)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for relative in ("knowledge", "data/source", "data/review"):
                shutil.copytree(ROOT / relative, root / relative)
            path = root / "knowledge/sources/sources.jsonl"
            path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows(path) if row["source_id"] != "source_tgc_faq_1356_moomintroll_accessory_set"), encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(MoominEvidenceError, "source registry or lineage mismatch"):
                build(root)

    def test_apply_is_idempotent_and_rejects_unsupported_promotion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for relative in ("knowledge", "data", "schemas"):
                shutil.copytree(ROOT / relative, root / relative)
            command = [sys.executable, str(ROOT / "tools/normalize/apply_moomintroll_accessory_set_cohort.py"), "--root", str(root), "--apply"]
            first = subprocess.run(command, check=True, capture_output=True, text=True)
            tracked = [root / "knowledge/items/items.jsonl", root / "knowledge/sets/item-sets.jsonl", root / "knowledge/acquisition/availability-events.jsonl", root / "data/review/moomintroll-accessory-set-canonical-evidence.jsonl"]
            before = {path: path.read_bytes() for path in tracked}
            second = subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertEqual(json.loads(first.stdout), json.loads(second.stdout))
            self.assertEqual(before, {path: path.read_bytes() for path in tracked})
            path = root / "knowledge/items/items.jsonl"
            data = rows(path)
            next(row for row in data if row["item_id"] == "item_moomin_tail")["availability_status"] = "permanent"
            path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in data), encoding="utf-8", newline="\n")
            self.assertIn("committed target differs from replayable apply contract: knowledge/items/items.jsonl", verify(root))


if __name__ == "__main__":
    unittest.main()
