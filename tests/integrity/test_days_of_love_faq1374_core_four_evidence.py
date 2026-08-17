"""Regression tests for the bounded FAQ 1374 Days of Love core-four cohort."""
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

from tools.modeling.canonical_english_eligibility import declared_model_feature_status
from tools.normalize.apply_days_of_love_faq1374_core_four_cohort import DaysOfLoveEvidenceError, ITEMS, build, valid_title_relation, verify
from tools.validate.schema_validator import OfflineSchemaValidator


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class DaysOfLoveFaq1374CoreFourEvidenceTests(unittest.TestCase):
    def test_replays_strictly_and_keeps_nonclaims(self):
        self.assertEqual(verify(ROOT), [])
        _targets, ledger = build(ROOT)
        self.assertEqual(len(ledger), 32)
        self.assertEqual(sum(row["field_path"] == "vendor_item_guid" for row in ledger), 4)
        validator = OfflineSchemaValidator(ROOT / "schemas")
        self.assertTrue(all(not validator.validate(row, ROOT / "schemas/review/canonical-item-field-evidence.schema.json") for row in ledger))
        snapshot = json.loads((ROOT / "data/source/research/tgc-faq-1374-days-of-love-core-four.json").read_text(encoding="utf-8"))
        self.assertFalse(validator.validate(snapshot, ROOT / "schemas/knowledge/days-of-love-faq-1374-core-four-fact-snapshot.schema.json"))
        items = {row["item_id"]: row for row in rows(ROOT / "knowledge/items/items.jsonl")}
        for item_id, *_ in ITEMS:
            self.assertEqual((items[item_id]["availability_status"], items[item_id]["permanent_account_item"], items[item_id]["first_release_date"], items[item_id]["model_feature_status"], items[item_id]["set_ids"], items[item_id]["visual_reference_ids"]), ("unknown", "unknown", None, declared_model_feature_status(item_id), [], []))
        availability = {row["availability_id"]: row for row in rows(ROOT / "knowledge/acquisition/availability-events.jsonl")}
        for item_id, *_ in ITEMS:
            row = availability["availability_days_of_love_faq1374_" + item_id.removeprefix("item_days_of_love_")]
            self.assertEqual((row["availability_status"], row["start_date"], row["end_date"]), ("limited_time", "2025-02-10", "2025-02-23"))

    def test_relation_is_enumerated_not_generic_normalization(self):
        self.assertTrue(valid_title_relation("Days of Love Amethyst-Tipped Tails hairstyle", "Days Of Love Amethyst-Tipped Tails"))
        self.assertFalse(valid_title_relation("Days of Love Other hairstyle", "Days Of Love Other"))
        self.assertFalse(valid_title_relation("Days of Love Braids", "Days Of Love Braids hair"))

    def test_tampering_and_apply_idempotence_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for rel in ("knowledge", "data/source", "data/review"):
                shutil.copytree(ROOT / rel, root / rel)
            snapshot = root / "data/source/research/tgc-faq-1374-days-of-love-core-four.json"
            snapshot.write_text(snapshot.read_text(encoding="utf-8").replace("Days of Love Braids", "Changed Braids", 1), encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(DaysOfLoveEvidenceError, "snapshot hash mismatch"):
                build(root)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for rel in ("knowledge", "data", "schemas"):
                shutil.copytree(ROOT / rel, root / rel)
            command = [sys.executable, str(ROOT / "tools/normalize/apply_days_of_love_faq1374_core_four_cohort.py"), "--root", str(root), "--apply"]
            subprocess.run(command, check=True, capture_output=True, text=True)
            tracked = [root / "knowledge/items/items.jsonl", root / "knowledge/sources/sources.jsonl", root / "knowledge/acquisition/availability-events.jsonl", root / "data/review/days-of-love-faq1374-core-four-canonical-evidence.jsonl"]
            before = {path: path.read_bytes() for path in tracked}
            subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertEqual(before, {path: path.read_bytes() for path in tracked})
            items = rows(root / "knowledge/items/items.jsonl")
            next(row for row in items if row["item_id"] == "item_days_of_love_braids")["model_feature_status"] = "eligible"
            (root / "knowledge/items/items.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in items), encoding="utf-8", newline="\n")
            self.assertIn("committed target differs from replayable apply contract: knowledge/items/items.jsonl", verify(root))


if __name__ == "__main__":
    unittest.main()
