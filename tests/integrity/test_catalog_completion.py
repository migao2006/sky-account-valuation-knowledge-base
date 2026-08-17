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
from tools.validate.catalog_completion import REQUIRED_ITEM_EVIDENCE, _trusted_rights_item_ids, build  # noqa: E402


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
            write_json(root / "manifest.json", {"research_cutoff_date": "2026-08-17"})
            write_jsonl(root / "knowledge/sources/sources.jsonl", [{"source_id": "source_complete", "source_lineage_id": "lineage_complete", "retrieved_at": "2026-08-17"}])
            write_jsonl(root / "data/review/catalog-universe.jsonl", [{"universe_id": "catalog_vendor_complete", "classification": "canonical_linked", "review_status": "approved"}])
            write_json(root / "data/review/catalog-universe-summary.json", {"expected_count": 1, "vendor_item_count": 1, "reconciliation_status": "reconciled", "needs_scope_review_count": 0})
            write_json(root / "data/normalized/source-scoped-item-identities-summary.json", {"unresolved_count": 0})
            for relative in ("data/review/item-candidates.jsonl", "reports/coverage/unresolved-items.jsonl", "reports/coverage/unmapped-aliases.jsonl", "data/review/alias-conflicts.jsonl"):
                write_jsonl(root / relative, [])
            entity_source = ["source_complete"]
            write_jsonl(root / "knowledge/seasons/seasons.jsonl", [{"season_id": "season_complete", "source_ids": entity_source, "last_verified_at": "2026-08-17", "verification_status": "verified"}])
            write_jsonl(root / "knowledge/events/events.jsonl", [{"event_id": "event_complete", "source_ids": entity_source, "last_verified_at": "2026-08-17", "verification_status": "verified"}])
            write_jsonl(root / "knowledge/seasons/ancestors.jsonl", [{"ancestor_id": "ancestor_complete", "season_id": "season_complete", "source_ids": entity_source, "last_verified_at": "2026-08-17", "verification_status": "verified"}])
            write_jsonl(root / "knowledge/sets/item-sets.jsonl", [{"set_id": "set_complete", "required_item_ids": ["item_complete"], "optional_item_ids": [], "source_ids": entity_source, "last_verified_at": "2026-08-17", "verification_status": "verified"}])
            write_jsonl(root / "knowledge/acquisition/availability-events.jsonl", [{"availability_id": "availability_complete", "item_id": "item_complete", "event_id": "event_complete", "source_ids": entity_source, "last_verified_at": "2026-08-17", "verification_status": "verified"}])
            write_jsonl(root / "knowledge/aliases/item-aliases.jsonl", [{"alias_id": "alias_complete", "target_type": "item", "target_id": "item_complete", "source_ids": entity_source, "last_verified_at": "2026-08-17", "verification_status": "verified"}])
            evidence_path = "data/review/complete-evidence.jsonl"
            cohort = {"cohort_id": "canonical_cohort_complete", "evidence_path": evidence_path, "review_status": "approved", "release_required": True}
            write_jsonl(root / "data/review/canonical-evidence-cohorts.jsonl", [cohort])
            evidence = [{"target_type": "item", "target_id": "item_complete", "field_path": field, "review_status": "approved", "evidence_role": "independent_field", "source_tier": "official_item_specific", "source_id": "source_complete", "source_lineage_id": "lineage_complete"} for field in sorted(REQUIRED_ITEM_EVIDENCE)]
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

    def test_verified_rights_unavailable_state_satisfies_visual_coverage_without_claiming_an_asset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_jsonl(root / "knowledge/items/items.jsonl", [{"item_id": "item_unavailable", "verification_status": "verified"}])
            for relative in ("data/review/catalog-universe.jsonl", "data/review/item-candidates.jsonl", "reports/coverage/unresolved-items.jsonl", "reports/coverage/unmapped-aliases.jsonl", "data/review/alias-conflicts.jsonl", "data/review/canonical-evidence-cohorts.jsonl", "data/curated/image-evidence.jsonl", "data/curated/visual-assets.jsonl"):
                write_jsonl(root / relative, [])
            write_json(root / "data/review/catalog-universe-summary.json", {"expected_count": 0, "vendor_item_count": 0, "reconciliation_status": "reconciled"})
            write_json(root / "data/normalized/source-scoped-item-identities-summary.json", {"unresolved_count": 0})
            write_json(root / "manifest.json", {"research_cutoff_date": "2026-08-17"})
            write_jsonl(root / "knowledge/sources/sources.jsonl", [{"source_id": "source_rights_record", "source_lineage_id": "lineage_rights", "source_type": "official_support", "retrieved_at": "2026-08-17"}])
            snapshot = root / "data/source/research/rights-record.json"
            write_json(snapshot, {"rights": {"item_id": "item_unavailable", "redistribution": "rights_not_granted_for_redistribution"}})
            rights = {"source_id": "source_rights_record", "snapshot_path": "data/source/research/rights-record.json", "snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest().upper(), "claim_locator": "/rights", "claim_value": "rights_not_granted_for_redistribution", "item_id": "item_unavailable"}
            reference = {"visual_reference_id": "visual_unavailable", "item_id": "item_unavailable", "reference_mode": "unavailable", "asset_sha256": None, "asset_registry_id": None, "detection_ids": [], "description": "The licensed source identifies the item, but redistribution rights for its image were not granted.", "unavailable_reason": "rights_not_granted_for_redistribution", "rights_evidence": rights, "source_ids": ["source_rights_record"], "verification_status": "verified"}
            write_jsonl(root / "knowledge/visual-references/manifest.jsonl", [reference])
            # A well-formed source JSON alone is not a completion exception.
            self.assertIn("catalog.visual_state_verified", build(root)["blocking_contract_ids"])
            generic_rights = {key: value for key, value in rights.items() if key != "item_id"}
            self.assertTrue(OfflineSchemaValidator(ROOT / "schemas").validate({**reference, "rights_evidence": generic_rights}, ROOT / "schemas/knowledge/visual-reference.schema.json"))
            cohort = {"cohort_id": "canonical_cohort_rights", "review_status": "approved", "release_required": True}
            evidence = [{"target_type": "item", "target_id": "item_unavailable", "field_path": "visual_reference", "review_status": "approved", "source_id": "source_rights_record", "source_lineage_id": "lineage_rights", "source_snapshot_path": "data/source/research/rights-record.json", "source_snapshot_hash": rights["snapshot_sha256"], "claim_locator": "/rights"}]
            write_jsonl(root / "data/review/canonical-evidence-cohorts.jsonl", [cohort])
            write_jsonl(root / "data/review/official-rights-source-registry.jsonl", [{"source_id": "source_rights_record", "source_lineage_id": "lineage_rights", "verifier_id": "official_item_rights_v1", "review_status": "approved"}])
            with patch("tools.validate.catalog_completion.validate_registry", return_value=([], {"canonical_cohort_rights": evidence})), patch("tools.validate.catalog_completion.load_registry", return_value=[cohort]):
                report = build(root)
            self.assertNotIn("catalog.visual_state_verified", report["blocking_contract_ids"])
            self.assertEqual([], OfflineSchemaValidator(ROOT / "schemas").validate(reference, ROOT / "schemas/knowledge/visual-reference.schema.json"))
            snapshot.unlink()
            with patch("tools.validate.catalog_completion.validate_registry", return_value=([], {"canonical_cohort_rights": evidence})), patch("tools.validate.catalog_completion.load_registry", return_value=[cohort]):
                self.assertIn("catalog.visual_state_verified", build(root)["blocking_contract_ids"])

    def test_two_current_independent_secondary_sources_satisfy_identity_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            item = {"item_id": "item_secondary", "verification_status": "verified"}
            write_jsonl(root / "knowledge/items/items.jsonl", [item])
            for relative in ("data/review/catalog-universe.jsonl", "data/review/item-candidates.jsonl", "reports/coverage/unresolved-items.jsonl", "reports/coverage/unmapped-aliases.jsonl", "data/review/alias-conflicts.jsonl", "data/curated/image-evidence.jsonl", "data/curated/visual-assets.jsonl", "knowledge/visual-references/manifest.jsonl"):
                write_jsonl(root / relative, [])
            write_json(root / "data/review/catalog-universe-summary.json", {"expected_count": 0, "vendor_item_count": 0, "reconciliation_status": "reconciled"})
            write_json(root / "data/normalized/source-scoped-item-identities-summary.json", {"unresolved_count": 0})
            write_json(root / "manifest.json", {"research_cutoff_date": "2026-08-17"})
            sources = [
                {"source_id": "source_secondary_a", "source_lineage_id": "lineage_secondary_a", "url": "https://one.example/items", "evidence_level": "community_cross_checked", "retrieved_at": "2026-08-01"},
                {"source_id": "source_secondary_b", "source_lineage_id": "lineage_secondary_b", "url": "https://two.example/items", "evidence_level": "community_cross_checked", "retrieved_at": "2026-08-02"},
            ]
            write_jsonl(root / "knowledge/sources/sources.jsonl", sources)
            evidence = [
                {"target_type": "item", "target_id": "item_secondary", "field_path": "canonical_name_en", "review_status": "approved", "evidence_role": "independent_identity", "source_tier": "secondary_reference", "source_id": "source_secondary_a", "source_lineage_id": "lineage_secondary_a"},
                {"target_type": "item", "target_id": "item_secondary", "field_path": "canonical_name_en", "review_status": "approved", "evidence_role": "independent_identity", "source_tier": "secondary_reference", "source_id": "source_secondary_b", "source_lineage_id": "lineage_secondary_b"},
            ]
            cohort = {"cohort_id": "canonical_cohort_secondary", "review_status": "approved", "release_required": True}
            write_jsonl(root / "data/review/canonical-evidence-cohorts.jsonl", [cohort])
            with patch("tools.validate.catalog_completion.validate_registry", return_value=([], {"canonical_cohort_secondary": evidence})), patch("tools.validate.catalog_completion.load_registry", return_value=[cohort]):
                report = build(root)
            identity = next(row for row in report["checks"] if row["contract_id"] == "catalog.independent_identity_evidence")
            self.assertTrue(identity["passed"])
            self.assertEqual(1, identity["actual"]["two_secondary_identity_count"])
            sources[1].pop("source_lineage_id")
            write_jsonl(root / "knowledge/sources/sources.jsonl", sources)
            with patch("tools.validate.catalog_completion.validate_registry", return_value=([], {"canonical_cohort_secondary": evidence})), patch("tools.validate.catalog_completion.load_registry", return_value=[cohort]):
                missing_lineage = build(root)
            identity = next(row for row in missing_lineage["checks"] if row["contract_id"] == "catalog.independent_identity_evidence")
            self.assertFalse(identity["passed"])

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

    def test_any_needs_review_knowledge_entity_blocks_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "manifest.json", {"research_cutoff_date": "2026-08-17"})
            write_jsonl(root / "knowledge/sources/sources.jsonl", [{"source_id": "source_current", "retrieved_at": "2026-08-17"}])
            for relative in ("knowledge/items/items.jsonl", "knowledge/seasons/ancestors.jsonl", "knowledge/sets/item-sets.jsonl", "knowledge/acquisition/availability-events.jsonl", "knowledge/aliases/item-aliases.jsonl"):
                write_jsonl(root / relative, [])
            write_jsonl(root / "knowledge/events/events.jsonl", [{"event_id": "event_review", "source_ids": ["source_current"], "last_verified_at": "2026-08-17", "verification_status": "needs_review"}])
            report = build(root)
            self.assertIn("catalog.knowledge_entity_verified", report["blocking_contract_ids"])

    def test_stale_or_lineage_mismatched_field_evidence_never_completes_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "manifest.json", {"research_cutoff_date": "2026-08-17"})
            write_jsonl(root / "knowledge/items/items.jsonl", [{"item_id": "item_stale", "verification_status": "verified"}])
            write_jsonl(root / "knowledge/sources/sources.jsonl", [{"source_id": "source_stale", "source_lineage_id": "lineage_registered", "retrieved_at": "2020-01-01"}])
            cohort = {"cohort_id": "canonical_cohort_stale", "review_status": "approved", "release_required": True}
            evidence = [{"target_type": "item", "target_id": "item_stale", "field_path": field, "review_status": "approved", "source_id": "source_stale", "source_lineage_id": "lineage_forged"} for field in REQUIRED_ITEM_EVIDENCE]
            with patch("tools.validate.catalog_completion.validate_registry", return_value=([], {"canonical_cohort_stale": evidence})), patch("tools.validate.catalog_completion.load_registry", return_value=[cohort]):
                report = build(root)
            self.assertIn("catalog.required_field_evidence", report["blocking_contract_ids"])

    def test_one_rights_claim_cannot_complete_multiple_items(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_jsonl(root / "data/review/official-rights-source-registry.jsonl", [{"source_id": "source_official_a", "source_lineage_id": "lineage_official_a", "verifier_id": "official_item_rights_v1", "review_status": "approved"}, {"source_id": "source_official_b", "source_lineage_id": "lineage_official_b", "verifier_id": "official_item_rights_v1", "review_status": "approved"}])
            rights = {"source_id": "source_official_a", "snapshot_path": "data/source/research/rights.json", "snapshot_sha256": "A" * 64, "claim_locator": "/rights", "item_id": "item_one"}
            references = [
                {"item_id": "item_one", "reference_mode": "unavailable", "verification_status": "verified", "rights_evidence": rights},
                {"item_id": "item_two", "reference_mode": "unavailable", "verification_status": "verified", "rights_evidence": {**rights, "source_id": "source_official_b", "item_id": "item_two"}},
            ]
            evidence = [{"target_type": "item", "target_id": "item_one", "field_path": "visual_reference", "review_status": "approved", "source_id": "source_official_a", "source_lineage_id": "lineage_official_a", "source_snapshot_path": rights["snapshot_path"], "source_snapshot_hash": rights["snapshot_sha256"], "claim_locator": rights["claim_locator"]}, {"target_type": "item", "target_id": "item_two", "field_path": "visual_reference", "review_status": "approved", "source_id": "source_official_b", "source_lineage_id": "lineage_official_b", "source_snapshot_path": rights["snapshot_path"], "source_snapshot_hash": rights["snapshot_sha256"], "claim_locator": rights["claim_locator"]}]
            sources = {"source_official_a": {"source_type": "official_support", "source_lineage_id": "lineage_official_a"}, "source_official_b": {"source_type": "official_support", "source_lineage_id": "lineage_official_b"}}
            self.assertEqual(set(), _trusted_rights_item_ids(root, references, evidence, sources))

    def test_empty_knowledge_family_never_vacuously_closes_catalog(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in ("knowledge/items/items.jsonl", "knowledge/seasons/seasons.jsonl", "knowledge/events/events.jsonl", "knowledge/seasons/ancestors.jsonl", "knowledge/sets/item-sets.jsonl", "knowledge/acquisition/availability-events.jsonl", "knowledge/aliases/item-aliases.jsonl"):
                write_jsonl(root / relative, [])
            report = build(root)
            closure = next(check for check in report["checks"] if check["contract_id"] == "catalog.knowledge_entity_inventory_closure")
            self.assertFalse(closure["passed"])
            self.assertEqual({"aliases", "ancestors", "availability_events", "events", "seasons", "sets"}, set(closure["actual"]["empty_families"]))

    def test_missing_last_verified_date_is_stale_not_timeless(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "manifest.json", {"research_cutoff_date": "2026-08-17"})
            write_jsonl(root / "knowledge/sources/sources.jsonl", [{"source_id": "source_current", "retrieved_at": "2026-08-17"}])
            write_jsonl(root / "knowledge/events/events.jsonl", [{"event_id": "event_missing_date", "source_ids": ["source_current"], "verification_status": "verified"}])
            for relative in ("knowledge/items/items.jsonl", "knowledge/seasons/seasons.jsonl", "knowledge/seasons/ancestors.jsonl", "knowledge/sets/item-sets.jsonl", "knowledge/acquisition/availability-events.jsonl", "knowledge/aliases/item-aliases.jsonl"):
                write_jsonl(root / relative, [])
            report = build(root)
            freshness = next(check for check in report["checks"] if check["contract_id"] == "catalog.knowledge_entity_source_and_freshness")
            self.assertFalse(freshness["passed"])
            self.assertEqual(["event_missing_date"], freshness["actual"]["stale_by_entity"]["events"])


if __name__ == "__main__":
    unittest.main()
