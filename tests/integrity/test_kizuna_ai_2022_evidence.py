"""Regression tests for the bounded FAQ 879 Kizuna AI 2022 cohort."""
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
from tools.normalize.apply_kizuna_ai_2022_cohort import ITEMS, KizunaEvidenceError, build, verify  # noqa: E402
from tools.validate.schema_validator import OfflineSchemaValidator  # noqa: E402


def rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class KizunaAi2022EvidenceTests(unittest.TestCase):
    def test_replays_fact_only_official_and_secondary_evidence(self):
        self.assertEqual(verify(ROOT), [])
        _targets, ledger = build(ROOT)
        self.assertEqual(len(ledger), 22)
        validator = OfflineSchemaValidator(ROOT / "schemas")
        self.assertTrue(all(not validator.validate(row, ROOT / "schemas/review/canonical-item-field-evidence.schema.json") for row in ledger))
        snapshot = json.loads((ROOT / "data/source/research/tgc-faq-879-kizuna-ai-2022.json").read_text(encoding="utf-8"))
        self.assertFalse(validator.validate(snapshot, ROOT / "schemas/knowledge/kizuna-ai-2022-fact-snapshot.schema.json"))
        items = {row["item_id"]: row for row in rows(ROOT / "knowledge/items/items.jsonl")}
        self.assertEqual({item_id: items[item_id]["canonical_name_en"] for item_id, *_ in ITEMS}, {item_id: name for item_id, _vendor_id, name, _vendor_type in ITEMS})
        for item_id, *_ in ITEMS:
            item = items[item_id]
            self.assertEqual((item["original_cost"], item["availability_status"], item["permanent_account_item"], item["first_release_date"], item["model_feature_status"]), ("bundle_only", "unknown", "unknown", None, "excluded_pending_verification"))
        for legacy in ("item_kizuna_ai_hair_bow", "item_kizuna_ai_headphones"):
            self.assertEqual(items[legacy]["verification_status"], "needs_review")
            self.assertNotIn("set_kizuna_ai_2022_iap", items[legacy]["set_ids"])
        self.assertFalse(any("三件套" in alias or "套組" in alias for alias in items["item_kizuna_ai_bow"]["aliases"]))
        alias_master = rows(ROOT / "knowledge/aliases/item-aliases.jsonl")
        self.assertFalse(any(row["alias_text"] in {"絆愛三件套", "絆愛套組"} or row["alias_id"] in {"alias_68b82ab9fde5ccbf592d", "alias_a4b7d91fce311e72a71b"} for row in alias_master))
        set_row = next(row for row in rows(ROOT / "knowledge/sets/item-sets.jsonl") if row["set_id"] == "set_kizuna_ai_2022_iap")
        self.assertEqual(set_row["required_item_ids"], [item_id for item_id, *_ in ITEMS])
        availability = {row["availability_id"]: row for row in rows(ROOT / "knowledge/acquisition/availability-events.jsonl")}
        for item_id, *_ in ITEMS:
            row = availability["availability_kizuna_ai_faq879_" + item_id.removeprefix("item_kizuna_ai_")]
            self.assertEqual((row["availability_status"], row["start_date"], row["end_date"], row["verification_status"]), ("limited_time", "2022-02-25", "2022-03-10", "needs_review"))

    def test_changed_snapshot_and_source_registry_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for relative in ("knowledge", "data/source", "data/review"):
                shutil.copytree(ROOT / relative, root / relative)
            path = root / "data/source/research/tgc-faq-879-kizuna-ai-2022.json"
            path.write_text(path.read_text(encoding="utf-8").replace("Secret Area", "Changed Area", 1), encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(KizunaEvidenceError, "snapshot hash mismatch"):
                build(root)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for relative in ("knowledge", "data/source", "data/review"):
                shutil.copytree(ROOT / relative, root / relative)
            path = root / "knowledge/sources/sources.jsonl"
            path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows(path) if row["source_id"] != "source_tgc_faq_879_kizuna_ai_2022"), encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(KizunaEvidenceError, "source registry or lineage mismatch"):
                build(root)

    def test_apply_is_idempotent_and_rejects_unsupported_promotion(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "repo"
            for relative in ("knowledge", "data", "schemas"):
                shutil.copytree(ROOT / relative, root / relative)
            command = [sys.executable, str(ROOT / "tools/normalize/apply_kizuna_ai_2022_cohort.py"), "--root", str(root), "--apply"]
            subprocess.run(command, check=True, capture_output=True, text=True)
            tracked = [root / "knowledge/items/items.jsonl", root / "knowledge/sets/item-sets.jsonl", root / "knowledge/aliases/item-aliases.jsonl", root / "knowledge/acquisition/availability-events.jsonl", root / "data/review/kizuna-ai-2022-canonical-evidence.jsonl"]
            before = {path: path.read_bytes() for path in tracked}
            subprocess.run(command, check=True, capture_output=True, text=True)
            self.assertEqual(before, {path: path.read_bytes() for path in tracked})
            path = root / "knowledge/items/items.jsonl"; data = rows(path)
            next(row for row in data if row["item_id"] == "item_kizuna_ai_cape")["availability_status"] = "permanent"
            path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in data), encoding="utf-8", newline="\n")
            self.assertIn("committed target differs from replayable apply contract: knowledge/items/items.jsonl", verify(root))


if __name__ == "__main__":
    unittest.main()
