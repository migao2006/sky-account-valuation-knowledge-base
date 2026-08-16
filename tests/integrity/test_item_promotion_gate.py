"""Tests for the offline, non-mutating candidate promotion gate."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
from tools.normalize.promote_items import claim_hash, evaluate, read_jsonl, verify_replayable_sources
from tools.normalize.build_item_evidence_bundle import build, sha
from tools.validate.schema_validator import OfflineSchemaValidator


def candidate(identifier="item_test_cape"):
    return {"candidate_item_id": identifier, "candidate_name_en": "Test Cape", "candidate_category": "cape", "season_id": "season_test", "reason": "independently collected candidate"}


def evidence(field, value, source, tier="official_item_specific"):
    from tools.normalize.promote_items import claim_hash
    return {"evidence_id": "item_evidence_" + source.replace("_", "") + field.replace("_", ""), "candidate_item_id": "item_test_cape", "proposed_canonical_item_id": "item_test_cape", "field_path": field, "claim_value": value, "claim_hash": claim_hash(value), "source_id": source, "source_tier": tier, "source_locator": "fixture://" + source + "/" + field, "source_snapshot_hash": "A" * 64, "evidence_role": "independent_identity" if field == "canonical_identity" else "independent_field", "review_status": "approved", "reviewed_at": "2026-08-17"}


class ItemPromotionGateTests(unittest.TestCase):
    def test_unpinned_caller_authored_evidence_cannot_approve_strict_migration(self):
        rows = evaluate([candidate()], set(), [], [
            evidence("canonical_identity", "Test Cape", "source_official_item"),
            evidence("canonical_name_en", "Test Cape", "source_community", "maintained_community"),
            evidence("item_category", "cape", "source_community", "maintained_community"),
            evidence("season_id", "season_test", "source_community", "maintained_community"),
        ])
        self.assertEqual(rows[0]["decision"], "rejected_fail_closed")
        self.assertIn("unverified_evidence_provenance", rows[0]["reasons"])
        self.assertIn("fewer_than_two_independent_source_lineages", rows[0]["reasons"])
        self.assertEqual(rows[0]["canonical_write"], "not_performed")

    def test_unknown_or_single_secondary_evidence_fails_closed(self):
        rows = evaluate([candidate()], set(), [], [
            evidence("canonical_identity", "Test Cape", "source_one", "secondary_reference"),
            evidence("canonical_name_en", "Test Cape", "source_one", "secondary_reference"),
            evidence("item_category", "cape", "source_one", "secondary_reference"),
            evidence("season_id", "season_test", "source_one", "secondary_reference"),
        ])
        self.assertEqual(rows[0]["decision"], "rejected_fail_closed")
        self.assertIn("no_official_item_specific_identity", rows[0]["reasons"])
        self.assertIn("fewer_than_two_independent_source_lineages", rows[0]["reasons"])

    def test_alias_conflict_template_and_identity_conflict_reject(self):
        template = candidate("item_test_template")
        template["reason"] = "Printable template token has not been verified"
        conflict = {"normalized_alias": "testcape", "candidate_targets": []}
        rows = evaluate([template], set(), [conflict], [])
        self.assertEqual(rows[0]["decision"], "rejected_fail_closed")
        self.assertIn("template_candidate_requires_official_suffix_identity_review", rows[0]["reasons"])
        self.assertIn("alias_conflict_requires_resolution", rows[0]["reasons"])

    def test_dry_run_is_idempotent_and_does_not_write(self):
        before = (ROOT / "knowledge/items/items.jsonl").read_bytes()
        first = evaluate([candidate()], set(), [], [])
        second = evaluate([candidate()], set(), [], [])
        self.assertEqual(first, second)
        with tempfile.TemporaryDirectory() as temporary:
            result = subprocess.run([sys.executable, "tools/normalize/promote_items.py", "--root", str(ROOT), "--evidence", str(Path(temporary) / "missing.jsonl")], cwd=ROOT, check=True, capture_output=True, text=True)
            self.assertTrue(json.loads(result.stdout)["dry_run"])
        self.assertEqual(before, (ROOT / "knowledge/items/items.jsonl").read_bytes())

    def test_schema_accepts_a_reviewed_claim_and_rejects_unrecognized_field(self):
        validator = OfflineSchemaValidator(ROOT / "schemas")
        row = evidence("canonical_identity", "Test Cape", "source_official_item")
        self.assertEqual(validator.validate(row, ROOT / "schemas/review/item-evidence.schema.json"), [])
        row["field_path"] = "price_adjustment"
        self.assertTrue(validator.validate(row, ROOT / "schemas/review/item-evidence.schema.json"))

    def test_vendor_correlation_keeps_template_identity_and_other_fields_unresolved(self):
        candidates = [json.loads(line) for line in (ROOT / "data/review/item-candidates.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        vendor = [json.loads(line) for line in (ROOT / "data/review/skygame-data-1.3.4-item-evidence.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        candidate_path = ROOT / "data/review/item-candidates.jsonl"
        bundle = build(candidates, vendor, sha(candidate_path.read_bytes()))
        self.assertEqual(len(bundle), 296 * 6)
        self.assertTrue(all(row["review_status"] == "machine_correlated" for row in bundle))
        sources = {row["source_id"]: row for row in read_jsonl(ROOT / "knowledge/sources/sources.jsonl")}
        verified = verify_replayable_sources(ROOT, bundle, sources)
        rows = evaluate(candidates, set(), [], bundle, mode="vendor_correlation", verified_evidence_ids=verified)
        approved = [row for row in rows if row["decision"] == "vendor_correlated_template_candidate"]
        self.assertLessEqual(len(approved), 296)
        self.assertEqual(len(approved), 284)
        self.assertTrue(all(row["verification_status"] == "needs_review" for row in approved))
        self.assertTrue(all(row["model_feature_status"] == "excluded_pending_verification" for row in approved))
        self.assertTrue(all("canonical_identity" in row["unresolved_fields"] for row in approved))
        self.assertTrue(all("season_id" in row["unresolved_fields"] for row in approved))
        self.assertTrue(all(row["canonical_write"] == "not_performed" for row in rows))
        self.assertEqual(verified, {row["evidence_id"] for row in bundle})

    def test_production_cli_rejects_fixture_locator(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence_path = Path(temporary) / "evidence.jsonl"
            evidence_path.write_text(json.dumps(evidence("canonical_identity", "Test Cape", "source_official_item")) + "\n", encoding="utf-8")
            result = subprocess.run([sys.executable, "tools/normalize/promote_items.py", "--root", str(ROOT), "--evidence", str(evidence_path)], cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue("not canonical" in result.stderr or "not replayable" in result.stderr)

    def _strict_evidence(self, root, source_id, lineage, field, value):
        snapshot = root / "data/source/pinned.json"
        document = {"identity": "Test Cape", "name": "Test Cape", "category": "cape", "season": "season_test"}
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(json.dumps(document, ensure_ascii=False, sort_keys=True), encoding="utf-8", newline="\n")
        key = {"canonical_identity": "identity", "canonical_name_en": "name", "item_category": "category", "season_id": "season"}[field]
        snapshot_bytes = snapshot.read_bytes()
        return {
            "evidence_id": f"item_evidence_{source_id}_{field}", "candidate_item_id": "item_test_cape", "proposed_canonical_item_id": "item_test_cape",
            "field_path": field, "claim_value": value, "claim_hash": claim_hash(value),
            "source_id": source_id, "source_lineage_id": lineage, "source_tier": "official_item_specific" if source_id.endswith("official") else "maintained_community",
            "source_snapshot_path": "data/source/pinned.json", "source_snapshot_bytes": len(snapshot_bytes),
            "source_snapshot_hash": __import__("hashlib").sha256(snapshot_bytes).hexdigest().upper(),
            "claim_locator": "/" + key, "claim_locator_hash": claim_hash(document[key]),
            "evidence_role": "independent_identity" if field == "canonical_identity" else "independent_field", "review_status": "approved", "reviewed_at": "2026-08-17",
        }

    def test_strict_pinned_sources_create_replayable_promotion_ready_ledger_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = {
                "source_official": {"source_id": "source_official", "source_type": "official_site", "source_lineage_id": "lineage_official"},
                "source_crosscheck": {"source_id": "source_crosscheck", "source_type": "community_database", "source_lineage_id": "lineage_crosscheck"},
            }
            evidence_rows = []
            for field, value in (("canonical_identity", "Test Cape"), ("canonical_name_en", "Test Cape"), ("item_category", "cape"), ("season_id", "season_test")):
                evidence_rows.append(self._strict_evidence(root, "source_official", "lineage_official", field, value))
                evidence_rows.append(self._strict_evidence(root, "source_crosscheck", "lineage_crosscheck", field, value))
            validator = OfflineSchemaValidator(ROOT / "schemas")
            self.assertEqual(validator.validate(evidence_rows[0], ROOT / "schemas/review/item-promotion-evidence.schema.json"), [])
            invalid = dict(evidence_rows[0]); invalid.pop("claim_locator_hash")
            self.assertTrue(validator.validate(invalid, ROOT / "schemas/review/item-promotion-evidence.schema.json"))
            verified = verify_replayable_sources(root, evidence_rows, sources, strict_contract=True)
            rows = evaluate([candidate()], set(), [], evidence_rows, verified_evidence_ids=verified, source_records=sources)
            self.assertEqual(rows[0]["decision"], "approved_for_canonical_promotion")
            self.assertTrue(rows[0]["promotion_ready"])
            self.assertEqual(rows[0]["canonical_write"], "not_performed")
            self.assertEqual(rows[0]["source_lineage_ids"], ["lineage_crosscheck", "lineage_official"])
            self.assertEqual(rows[0]["replay_status"], "verified")
            self.assertEqual(rows[0]["field_coverage"]["season_id"], ["source_crosscheck", "source_official"])
            self.assertEqual(rows, evaluate([candidate()], set(), [], evidence_rows, verified_evidence_ids=verified, source_records=sources))

    def test_strict_promotion_rejects_tampered_locator_and_single_lineage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = {"source_official": {"source_id": "source_official", "source_type": "official_site", "source_lineage_id": "lineage_one"}}
            evidence_rows = [self._strict_evidence(root, "source_official", "lineage_one", field, value) for field, value in (("canonical_identity", "Test Cape"), ("canonical_name_en", "Test Cape"), ("item_category", "cape"), ("season_id", "season_test"))]
            verified = verify_replayable_sources(root, evidence_rows, sources, strict_contract=True)
            rows = evaluate([candidate()], set(), [], evidence_rows, verified_evidence_ids=verified, source_records=sources)
            self.assertEqual(rows[0]["decision"], "rejected_fail_closed")
            self.assertIn("fewer_than_two_independent_source_lineages", rows[0]["reasons"])
            evidence_rows[0]["claim_locator_hash"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "locator hash mismatch"):
                verify_replayable_sources(root, evidence_rows, sources, strict_contract=True)


if __name__ == "__main__":
    unittest.main()
