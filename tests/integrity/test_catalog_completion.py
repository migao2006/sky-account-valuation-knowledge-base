"""Completion must be replayed from catalog evidence, never a static flag."""
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import hashlib
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "validate"))
from schema_validator import OfflineSchemaValidator  # noqa: E402
from tools.validate.catalog_completion import REQUIRED_ITEM_EVIDENCE, build  # noqa: E402


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


class CatalogCompletionTests(unittest.TestCase):
    @staticmethod
    def png_bytes() -> bytes:
        def chunk(kind: bytes, value: bytes) -> bytes:
            return len(value).to_bytes(4, "big") + kind + value + zlib.crc32(kind + value).to_bytes(4, "big")
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + b"\x08\x00\x00\x00\x00") + chunk(b"IDAT", zlib.compress(b"\x00\x00")) + chunk(b"IEND", b"")

    def test_committed_catalog_remains_partial_under_stricter_replay(self):
        actual = build(ROOT)
        self.assertEqual(actual["catalog_status"], "partial")
        self.assertIn("catalog.unresolved_zero", actual["blocking_contract_ids"])
        self.assertIn("catalog.required_field_evidence", actual["blocking_contract_ids"])
        errors = OfflineSchemaValidator(ROOT / "schemas").validate(actual, ROOT / "schemas/reports/catalog-completion.schema.json")
        self.assertEqual(errors, [])

    def test_complete_requires_every_contract_not_a_hardcoded_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = {"item_id": "item_complete", "verification_status": "verified"}
            write_jsonl(root / "knowledge/items/items.jsonl", [item])
            write_jsonl(root / "data/review/catalog-universe.jsonl", [{"universe_id": "catalog_vendor_complete", "classification": "canonical_linked", "review_status": "approved"}])
            write_json(root / "data/review/catalog-universe-summary.json", {"expected_count": 1, "vendor_item_count": 1, "reconciliation_status": "reconciled", "needs_scope_review_count": 0})
            write_json(root / "data/normalized/source-scoped-item-identities-summary.json", {"unresolved_count": 0})
            for relative in ("data/review/item-candidates.jsonl", "reports/coverage/unresolved-items.jsonl", "reports/coverage/unmapped-aliases.jsonl", "data/review/alias-conflicts.jsonl"):
                write_jsonl(root / relative, [])
            evidence_path = "data/review/complete-evidence.jsonl"
            cohort = {"cohort_id": "canonical_cohort_complete", "evidence_path": evidence_path, "review_status": "approved", "release_required": True}
            write_jsonl(root / "data/review/canonical-evidence-cohorts.jsonl", [cohort])
            evidence = [{"target_type": "item", "target_id": "item_complete", "field_path": field, "review_status": "approved", "evidence_role": "independent_field", "source_tier": "official_item_specific"} for field in sorted(REQUIRED_ITEM_EVIDENCE)]
            next(row for row in evidence if row["field_path"] == "canonical_name_en").update({"evidence_role": "independent_identity"})
            write_jsonl(root / evidence_path, evidence)
            image_path = root / "data/curated/visual-assets/complete.png"
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(self.png_bytes())
            digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
            write_jsonl(root / "data/curated/visual-assets.jsonl", [{"asset_registry_id": "asset_complete", "asset_sha256": digest, "asset_path": "data/curated/visual-assets/complete.png", "mime_type": "image/png"}])
            write_jsonl(root / "data/curated/image-evidence.jsonl", [])
            write_jsonl(root / "knowledge/visual-references/manifest.jsonl", [{"visual_reference_id": "visual_complete", "item_id": "item_complete", "verification_status": "verified", "reference_mode": "offline_asset", "asset_registry_id": "asset_complete", "asset_sha256": digest, "source_ids": ["source_complete"]}])
            with patch("tools.validate.catalog_completion.validate_registry", return_value=([], {"canonical_cohort_complete": evidence})), patch("tools.validate.catalog_completion.load_registry", return_value=[cohort]):
                report = build(root)
            self.assertTrue(report["complete"])
            self.assertEqual(report["catalog_status"], "complete")
            self.assertEqual(report["blocking_contract_ids"], [])
            universe_schema = ROOT / "schemas/review/catalog-universe.schema.json"
            self.assertEqual(OfflineSchemaValidator(ROOT / "schemas").validate({
                "universe_id": "catalog_vendor_complete", "snapshot_id": "vendor_skygame_data_1_3_4", "source_id": "source_skygame_data_1_3_4", "snapshot_sha256": "A" * 64,
                "vendor_item_id": 1, "vendor_guid": "complete", "vendor_name": "Complete", "vendor_item_type": "Outfit", "vendor_item_subtype": None, "vendor_item_group": None,
                "classification": "canonical_linked", "crosswalk_match_status": "matched_canonical_name", "scope_disposition": "collectible_item", "disposition_reason": "vendor_type_not_type_only_excluded", "evidence_basis": "pinned_vendor_snapshot_and_crosswalk", "canonical_item_ids": ["item_complete"], "candidate_item_ids": [], "scope_approval": {"evidence_source_id": "source_independent", "evidence_snapshot_path": "data/source/research/complete.json", "evidence_snapshot_sha256": "A" * 64, "evidence_locator": "/scope", "review_status": "approved"}, "review_status": "approved"
            }, universe_schema), [])

    def test_planned_or_failed_cohort_cannot_supply_completion_field_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = {"item_id": "item_complete", "verification_status": "verified"}
            write_jsonl(root / "knowledge/items/items.jsonl", [item])
            for relative in ("data/review/catalog-universe.jsonl", "data/review/item-candidates.jsonl", "reports/coverage/unresolved-items.jsonl", "reports/coverage/unmapped-aliases.jsonl", "data/review/alias-conflicts.jsonl", "knowledge/visual-references/manifest.jsonl", "data/curated/image-evidence.jsonl", "data/curated/visual-assets.jsonl"):
                write_jsonl(root / relative, [])
            write_json(root / "data/review/catalog-universe-summary.json", {"expected_count": 0, "vendor_item_count": 0, "reconciliation_status": "reconciled"})
            write_json(root / "data/normalized/source-scoped-item-identities-summary.json", {"unresolved_count": 0})
            planned = {"cohort_id": "canonical_cohort_planned", "review_status": "planned", "release_required": False}
            write_jsonl(root / "data/review/canonical-evidence-cohorts.jsonl", [planned])
            evidence = [{"target_type": "item", "target_id": "item_complete", "field_path": field, "review_status": "approved"} for field in REQUIRED_ITEM_EVIDENCE]
            with patch("tools.validate.catalog_completion.validate_registry", return_value=([], {"canonical_cohort_planned": evidence})), patch("tools.validate.catalog_completion.load_registry", return_value=[planned]):
                report = build(root)
            self.assertIn("catalog.required_field_evidence", report["blocking_contract_ids"])

    def test_source_description_never_satisfies_actual_visual_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = {"item_id": "item_description", "verification_status": "verified"}
            write_jsonl(root / "knowledge/items/items.jsonl", [item])
            for relative in ("data/review/catalog-universe.jsonl", "data/review/item-candidates.jsonl", "reports/coverage/unresolved-items.jsonl", "reports/coverage/unmapped-aliases.jsonl", "data/review/alias-conflicts.jsonl", "data/review/canonical-evidence-cohorts.jsonl", "data/curated/image-evidence.jsonl", "data/curated/visual-assets.jsonl"):
                write_jsonl(root / relative, [])
            write_json(root / "data/review/catalog-universe-summary.json", {"expected_count": 0, "vendor_item_count": 0, "reconciliation_status": "reconciled"})
            write_json(root / "data/normalized/source-scoped-item-identities-summary.json", {"unresolved_count": 0})
            write_jsonl(root / "knowledge/visual-references/manifest.jsonl", [{"visual_reference_id": "visual_description", "item_id": "item_description", "reference_mode": "source_description", "asset_sha256": None, "source_ids": ["source_description"], "verification_status": "verified"}])
            report = build(root)
            self.assertIn("catalog.visual_state_verified", report["blocking_contract_ids"])

    def test_missing_visual_state_blocks_otherwise_complete_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_jsonl(root / "knowledge/items/items.jsonl", [{"item_id": "item_missing_visual", "verification_status": "verified"}])
            write_jsonl(root / "data/review/catalog-universe.jsonl", [{"universe_id": "catalog_vendor_visual", "classification": "canonical_linked", "review_status": "approved"}])
            write_json(root / "data/review/catalog-universe-summary.json", {"expected_count": 1, "vendor_item_count": 1, "reconciliation_status": "reconciled"})
            write_json(root / "data/normalized/source-scoped-item-identities-summary.json", {"unresolved_count": 0})
            for relative in ("data/review/item-candidates.jsonl", "reports/coverage/unresolved-items.jsonl", "reports/coverage/unmapped-aliases.jsonl", "data/review/alias-conflicts.jsonl", "data/review/canonical-evidence-cohorts.jsonl", "knowledge/visual-references/manifest.jsonl"):
                write_jsonl(root / relative, [])
            report = build(root)
            self.assertFalse(report["complete"])
            self.assertIn("catalog.visual_state_verified", report["blocking_contract_ids"])


if __name__ == "__main__":
    unittest.main()
