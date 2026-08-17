"""New completion fields must be schema- and semantic-validator reachable."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.validate.validate import validate_canonical_field_evidence  # noqa: E402
from tools.validate.schema_validator import OfflineSchemaValidator  # noqa: E402


class CanonicalFieldEvidenceContractTests(unittest.TestCase):
    def setUp(self):
        self.items = {"item_fixture": {
            "availability_status": "limited_time", "pass_required": "yes",
            "ultimate_reward": True, "set_ids": ["set_fixture"],
        }}
        self.sources = {"source_fixture": {
            "source_lineage_id": "lineage_fixture", "source_type": "official_support",
        }}

    def row(self, field_path, claim_value):
        return {
            "evidence_id": "canonical_evidence_" + field_path,
            "target_type": "item", "target_id": "item_fixture", "field_path": field_path,
            "claim_value": claim_value, "source_id": "source_fixture",
            "source_lineage_id": "lineage_fixture", "source_tier": "official_item_specific",
        }

    def schema_row(self, field_path, claim_value):
        return {
            **self.row(field_path, claim_value), "claim_hash": "A" * 64,
            "source_snapshot_path": "data/source/research/fixture.json", "source_snapshot_bytes": 1,
            "source_snapshot_hash": "B" * 64, "claim_locator": "/claim",
            "claim_locator_hash": "C" * 64, "evidence_role": "independent_field",
            "review_status": "approved", "reviewed_at": "2026-08-17",
        }

    def test_new_fields_are_semantically_accepted(self):
        rows = [
            self.row("availability_as_of", "2026-08-17"),
            self.row("pass_required", "yes"),
            self.row("ultimate_reward", True),
        ]
        self.assertEqual([], validate_canonical_field_evidence([("fixture", rows)], self.items, {}, self.sources))
        validator = OfflineSchemaValidator(ROOT / "schemas")
        for field_path, claim_value in (("availability_as_of", "2026-08-17"), ("pass_required", "yes"), ("ultimate_reward", True)):
            self.assertEqual([], validator.validate(self.schema_row(field_path, claim_value), ROOT / "schemas/review/canonical-item-field-evidence.schema.json"))

    def test_unknown_field_fails_closed(self):
        problems = validate_canonical_field_evidence([("fixture", [self.row("invented_field", "x")])], self.items, {}, self.sources)
        self.assertTrue(any("not valid for an item" in problem for problem in problems))


if __name__ == "__main__":
    unittest.main()
