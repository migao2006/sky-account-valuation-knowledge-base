"""Regression tests for the bounded FAQ 1330 Tournament core-four cohort."""
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
from tools.normalize.apply_tournament_of_triumph_faq1330_core_four_cohort import ITEMS, TournamentEvidenceError, build, verify  # noqa: E402
from tools.validate.schema_validator import OfflineSchemaValidator  # noqa: E402


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class TournamentOfTriumphFaq1330CoreFourEvidenceTests(unittest.TestCase):
    def test_replays_pinned_facts_and_exact_vendor_identity(self):
        self.assertEqual(verify(ROOT), [])
        _targets, ledger = build(ROOT)
        self.assertEqual(len(ledger), 32)
        self.assertEqual(sum(row["field_path"] == "vendor_item_guid" for row in ledger), 4)
        self.assertFalse(any(row["source_id"] == "source_skygame_data_1_3_4" and row["field_path"] == "canonical_name_en" for row in ledger))
        validator = OfflineSchemaValidator(ROOT / "schemas")
        self.assertTrue(all(not validator.validate(row, ROOT / "schemas/review/canonical-item-field-evidence.schema.json") for row in ledger))
        snapshot = json.loads((ROOT / "data/source/research/tgc-faq-1330-tournament-of-triumph-core-four.json").read_text(encoding="utf-8"))
        self.assertFalse(validator.validate(snapshot, ROOT / "schemas/knowledge/tournament-of-triumph-faq-1330-core-four-fact-snapshot.schema.json"))
        items = {row["item_id"]: row for row in rows(ROOT / "knowledge/items/items.jsonl")}
        self.assertEqual({item_id: items[item_id]["canonical_name_en"] for item_id, _vendor, _guid, name, *_tail in ITEMS}, {item_id: name for item_id, _vendor, _guid, name, *_tail in ITEMS})
        self.assertNotIn("item_tournament_of_triumph_headband", items)
        for item_id, *_ in ITEMS:
            item = items[item_id]
            self.assertEqual((item["availability_status"], item["permanent_account_item"], item["first_release_date"], item["model_feature_status"], item["set_ids"], item["visual_reference_ids"]), ("unknown", "unknown", None, "excluded_pending_verification", [], []))
        availability = {row["availability_id"]: row for row in rows(ROOT / "knowledge/acquisition/availability-events.jsonl")}
        for item_id, *_ in ITEMS:
            row = availability["availability_tournament_of_triumph_faq1330_" + item_id.removeprefix("item_tournament_of_triumph_")]
            self.assertEqual((row["availability_status"], row["start_date"], row["end_date"], row["verification_status"]), ("limited_time", "2024-07-29", "2024-08-18", "verified"))

    def test_tampered_snapshot_or_registered_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for relative in ("knowledge", "data/source", "data/review"):
                shutil.copytree(ROOT / relative, root / relative)
            path = root / "data/source/research/tgc-faq-1330-tournament-of-triumph-core-four.json"
            path.write_text(path.read_text(encoding="utf-8").replace("Tournament Torch", "Changed Torch", 1), encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(TournamentEvidenceError, "snapshot hash mismatch"):
                build(root)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for relative in ("knowledge", "data/source", "data/review"):
                shutil.copytree(ROOT / relative, root / relative)
            path = root / "knowledge/sources/sources.jsonl"
            path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows(path) if row["source_id"] != "source_tgc_faq_1330_tournament_of_triumph_core_four"), encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(TournamentEvidenceError, "source registry or lineage mismatch"):
                build(root)

    def test_apply_is_idempotent_and_rejects_nonclaims(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for relative in ("knowledge", "data", "schemas"):
                shutil.copytree(ROOT / relative, root / relative)
            command = [sys.executable, str(ROOT / "tools/normalize/apply_tournament_of_triumph_faq1330_core_four_cohort.py"), "--root", str(root), "--apply"]
            subprocess.run(command, check=True, capture_output=True, text=True)
            tracked = [root / "knowledge/items/items.jsonl", root / "knowledge/acquisition/availability-events.jsonl", root / "data/review/tournament-of-triumph-faq1330-core-four-canonical-evidence.jsonl"]
            before = {path: path.read_bytes() for path in tracked}
            subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertEqual(before, {path: path.read_bytes() for path in tracked})
            path = root / "knowledge/items/items.jsonl"; data = rows(path)
            row = next(row for row in data if row["item_id"] == "item_tournament_of_triumph_tunic")
            row["set_ids"] = ["set_not_real"]; row["visual_reference_ids"] = ["visual_not_claimed"]
            path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in data), encoding="utf-8", newline="\n")
            self.assertIn("committed target differs from replayable apply contract: knowledge/items/items.jsonl", verify(root))


if __name__ == "__main__":
    unittest.main()
