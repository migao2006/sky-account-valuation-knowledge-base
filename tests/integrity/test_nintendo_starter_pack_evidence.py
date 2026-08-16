"""Bounded tests for the replayable Nintendo Starter Pack cohort."""
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

from tools.normalize.apply_nintendo_starter_pack import (  # noqa: E402
    ITEMS, NintendoEvidenceError, build, verify,
)
from tools.validate.schema_validator import OfflineSchemaValidator  # noqa: E402


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class NintendoStarterPackEvidenceTests(unittest.TestCase):
    def test_committed_cohort_replays_from_pinned_official_and_secondary_sources(self):
        self.assertEqual(verify(ROOT), [])
        _targets, evidence = build(ROOT)
        self.assertEqual(len(evidence), 18)
        validator = OfflineSchemaValidator(ROOT / "schemas")
        schema = ROOT / "schemas/review/canonical-item-field-evidence.schema.json"
        self.assertTrue(all(not validator.validate(row, schema) for row in evidence))
        names = {row["item_id"]: row["canonical_name_en"] for row in read_jsonl(ROOT / "knowledge/items/items.jsonl")}
        self.assertEqual({item_id: names[item_id] for item_id, _vendor_id, _name, _category in ITEMS}, {item_id: name for item_id, _vendor_id, name, _category in ITEMS})
        official_item_evidence = [row for row in evidence if row["target_type"] == "item" and row["source_id"] == "source_tgc_faq_823_nintendo_starter_pack"]
        self.assertTrue(official_item_evidence)
        self.assertFalse(any(row["field_path"] == "canonical_name_en" for row in official_item_evidence))
        self.assertTrue(all(row["field_path"] in {"identity_description", "set_membership"} for row in official_item_evidence))
        snapshot = json.loads((ROOT / "data/source/research/tgc-faq-823-nintendo-starter-pack.json").read_text(encoding="utf-8"))
        snapshot_text = json.dumps(snapshot, ensure_ascii=False)
        for exact_title in ("Nintendo Blue Switch Cape", "Nintendo Red Switch Cape", "Nintendo Elf Hair"):
            self.assertNotIn(exact_title, snapshot_text)
        official_set_evidence = [row for row in evidence if row["target_type"] == "set" and row["source_id"] == "source_tgc_faq_823_nintendo_starter_pack"]
        self.assertFalse(any(row["field_path"] == "canonical_name_en" for row in official_set_evidence))

    def test_no_unproven_availability_or_model_eligibility_is_promoted(self):
        items = {row["item_id"]: row for row in read_jsonl(ROOT / "knowledge/items/items.jsonl")}
        for item_id, _vendor_id, name, category in ITEMS:
            row = items[item_id]
            self.assertEqual(row["canonical_name_en"], name)
            self.assertEqual(row["item_category"], category)
            self.assertEqual(row["verification_status"], "verified")
            self.assertEqual(row["evidence_tier"], "official_with_secondary")
            self.assertEqual(row["availability_status"], "unknown")
            self.assertEqual(row["permanent_account_item"], "unknown")
            self.assertEqual(row["model_feature_status"], "excluded_pending_verification")
            self.assertIn("No formal Traditional Chinese name", row["notes"])
        visual = {row["item_id"]: row for row in read_jsonl(ROOT / "knowledge/visual-references/manifest.jsonl")}
        for item_id, *_unused in ITEMS:
            self.assertEqual(visual[item_id]["reference_mode"], "source_description")
            self.assertIn("no image asset", visual[item_id]["description"])

    def test_changed_pinned_snapshot_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for relative in ("knowledge", "data/source", "data/review"):
                shutil.copytree(ROOT / relative, root / relative)
            source = root / "data/source/research/tgc-faq-823-nintendo-starter-pack.json"
            source.write_text(source.read_text(encoding="utf-8").replace("Nintendo Switch", "Nintendo Switch Changed", 1), encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(NintendoEvidenceError, "official snapshot hash mismatch"):
                build(root)

    def test_apply_contract_is_idempotent_and_detects_unauthorized_model_promotion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for relative in ("knowledge", "data", "schemas"):
                shutil.copytree(ROOT / relative, root / relative)
            command = [sys.executable, str(ROOT / "tools/normalize/apply_nintendo_starter_pack.py"), "--root", str(root), "--apply"]
            first = subprocess.run(command, check=True, capture_output=True, text=True)
            tracked = [
                root / "knowledge/items/items.jsonl", root / "knowledge/sets/item-sets.jsonl",
                root / "knowledge/sources/sources.jsonl", root / "knowledge/acquisition/availability-events.jsonl",
                root / "knowledge/visual-references/manifest.jsonl", root / "data/review/nintendo-starter-pack-canonical-evidence.jsonl",
            ]
            first_bytes = {path: path.read_bytes() for path in tracked}
            second = subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertEqual(json.loads(first.stdout), json.loads(second.stdout))
            self.assertEqual(first_bytes, {path: path.read_bytes() for path in tracked})
            self.assertEqual(verify(root), [])
            path = root / "knowledge/items/items.jsonl"
            rows = read_jsonl(path)
            next(row for row in rows if row["item_id"] == "item_nintendo_blue_cape")["model_feature_status"] = "eligible"
            path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8", newline="\n")
            self.assertIn("committed target differs from replayable apply contract: knowledge/items/items.jsonl", verify(root))


if __name__ == "__main__":
    unittest.main()
