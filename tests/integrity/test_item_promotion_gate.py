"""Tests for the offline, non-mutating candidate promotion gate."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
from tools.normalize.promote_items import evaluate, read_jsonl, verify_replayable_sources
from tools.normalize.build_item_evidence_bundle import build, sha
from tools.validate.schema_validator import OfflineSchemaValidator


def candidate(identifier="item_test_cape"):
    return {"candidate_item_id": identifier, "candidate_name_en": "Test Cape", "candidate_category": "cape", "season_id": "season_test", "reason": "independently collected candidate"}


def evidence(field, value, source, tier="official_item_specific"):
    from tools.normalize.promote_items import claim_hash
    return {"evidence_id": "item_evidence_" + source.replace("_", "") + field.replace("_", ""), "candidate_item_id": "item_test_cape", "proposed_canonical_item_id": "item_test_cape", "field_path": field, "claim_value": value, "claim_hash": claim_hash(value), "source_id": source, "source_tier": tier, "source_locator": "fixture://" + source + "/" + field, "source_snapshot_hash": "A" * 64, "evidence_role": "independent_identity" if field == "canonical_identity" else "independent_field", "review_status": "approved", "reviewed_at": "2026-08-17"}


class ItemPromotionGateTests(unittest.TestCase):
    def test_caller_authored_evidence_cannot_approve_strict_migration(self):
        rows = evaluate([candidate()], set(), [], [
            evidence("canonical_identity", "Test Cape", "source_official_item"),
            evidence("canonical_name_en", "Test Cape", "source_community", "maintained_community"),
            evidence("item_category", "cape", "source_community", "maintained_community"),
            evidence("season_id", "season_test", "source_community", "maintained_community"),
        ])
        self.assertEqual(rows[0]["decision"], "rejected_fail_closed")
        self.assertIn("unverified_evidence_provenance", rows[0]["reasons"])
        self.assertIn("strict_promotion_disabled_in_p2_1", rows[0]["reasons"])
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
        self.assertIn("fewer_than_two_independent_sources", rows[0]["reasons"])

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
            self.assertIn("not replayable", result.stderr)


if __name__ == "__main__":
    unittest.main()
