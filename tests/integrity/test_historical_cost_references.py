"""Targeted checks for the non-resale official historical cost reference layer."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.normalize import build_historical_cost_references as cost_references  # noqa: E402
from tools.normalize.build_historical_cost_references import build, canonical_json  # noqa: E402
from tools.validate.canonical_evidence_registry import load_registry, validate_registry  # noqa: E402
from tools.validate.schema_validator import OfflineSchemaValidator  # noqa: E402


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class HistoricalCostReferenceTests(unittest.TestCase):
    @staticmethod
    def canonical_context():
        return (
            {row["item_id"]: row for row in read_jsonl(ROOT / "knowledge/items/items.jsonl")},
            {row["set_id"]: row for row in read_jsonl(ROOT / "knowledge/sets/item-sets.jsonl")},
            {row["source_id"]: row for row in read_jsonl(ROOT / "knowledge/sources/sources.jsonl")},
        )

    def test_discovers_every_active_registered_verified_item_and_validates_schema(self):
        problems, ledgers = validate_registry(ROOT, *self.canonical_context())
        self.assertEqual(problems, [])
        registry = load_registry(ROOT)
        expected = {
            item_id
            for cohort in registry if cohort["cohort_id"] in ledgers
            for item_id in cohort["target_item_ids"]
            if self.canonical_context()[0][item_id]["verification_status"] == "verified"
        }
        records = build(ROOT)
        self.assertEqual({record["item_id"] for record in records}, expected)
        self.assertEqual(len(records), len(expected))
        validator = OfflineSchemaValidator(ROOT / "schemas")
        schema = ROOT / "schemas/knowledge/official-historical-cost-reference.schema.json"
        self.assertTrue(all(not validator.validate(record, schema) for record in records))
        self.assertTrue(all(record["model_feature"] is False for record in records))
        self.assertTrue(all(record["resale_value_effect"] == "not_inferred" for record in records))

    def test_exact_bundle_currency_and_unknown_are_kept_distinct(self):
        records = {row["item_id"]: row for row in build(ROOT)}
        aurora = records["item_aurora_giving_in_cape"]
        self.assertEqual((aurora["reference_kind"], aurora["item_amount"], aurora["item_currency"]), ("exact_historical_item_price", 14.99, "USD"))
        self.assertIsNone(aurora["bundle_amount"])
        currency = records["item_aurora_cure_for_me_mask"]
        self.assertEqual((currency["reference_kind"], currency["item_amount"], currency["item_currency"]), ("in_game_currency", 50, "candle"))
        bundle = records["item_journey_hair"]
        self.assertEqual((bundle["reference_kind"], bundle["bundle_set_id"], bundle["bundle_amount"]), ("bundle_only", "set_journey_pack", 24.99))
        self.assertIsNone(bundle["item_amount"])
        unknown = records["item_nintendo_blue_cape"]
        self.assertEqual(unknown["reference_kind"], "unknown")
        self.assertIsNone(unknown["item_amount"])
        self.assertIsNone(unknown["bundle_amount"])

    def test_checked_in_data_is_deterministic_builder_output(self):
        expected = "".join(canonical_json(row) + "\n" for row in build(ROOT))
        actual = (ROOT / "data/derived/official-historical-cost-references.jsonl").read_text(encoding="utf-8")
        self.assertEqual(actual, expected)
        self.assertNotIn("estimate", (ROOT / "tools/normalize/build_historical_cost_references.py").read_text(encoding="utf-8").casefold())

    def test_output_serialization_is_replayable(self):
        # The builder's deterministic canonical JSON is safe to reproduce to a
        # fresh destination without mutating any canonical evidence input.
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "references.jsonl"
            output.write_text("".join(canonical_json(row) + "\n" for row in build(ROOT)), encoding="utf-8", newline="\n")
            self.assertEqual(read_jsonl(output), build(ROOT))

    def test_official_general_cost_claim_cannot_unlock_item_or_bundle_amount(self):
        """A generic official statement is context, not item-specific pricing."""
        items = [
            {"item_id": "item_generic_exact", "verification_status": "verified", "original_cost": 9.99, "original_currency": "USD", "set_ids": []},
            {"item_id": "item_generic_bundle", "verification_status": "verified", "original_cost": "bundle_only", "original_currency": "USD", "set_ids": ["set_generic_bundle"]},
        ]
        cohorts = [
            {"cohort_id": "canonical_cohort_generic_exact", "target_item_ids": ["item_generic_exact"], "target_set_ids": []},
            {"cohort_id": "canonical_cohort_generic_bundle", "target_item_ids": ["item_generic_bundle"], "target_set_ids": ["set_generic_bundle"]},
        ]
        def evidence(evidence_id, target_type, target_id, field_path, claim_value):
            return {"evidence_id": evidence_id, "target_type": target_type, "target_id": target_id, "field_path": field_path, "claim_value": claim_value, "source_id": "source_fake", "source_tier": "official_general", "reviewed_at": "2026-08-17"}
        ledgers = {
            "canonical_cohort_generic_exact": [evidence("canonical_evidence_general_item", "item", "item_generic_exact", "original_cost", 9.99)],
            "canonical_cohort_generic_bundle": [
                evidence("canonical_evidence_general_bundle_item", "item", "item_generic_bundle", "identity_description", "generic bundle component"),
                evidence("canonical_evidence_general_bundle", "set", "set_generic_bundle", "historical_pack_price_usd", 19.99),
            ],
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path, records in (("knowledge/items/items.jsonl", items), ("knowledge/sets/item-sets.jsonl", [{"set_id": "set_generic_bundle"}]), ("knowledge/sources/sources.jsonl", [{"source_id": "source_fake"}])):
                destination = root / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8", newline="\n")
            with patch.object(cost_references, "load_registry", return_value=cohorts), patch.object(cost_references, "validate_registry", return_value=([], ledgers)):
                records = {row["item_id"]: row for row in cost_references.build(root)}
        self.assertEqual(records["item_generic_exact"]["reference_kind"], "unknown")
        self.assertIsNone(records["item_generic_exact"]["item_amount"])
        self.assertEqual(records["item_generic_bundle"]["reference_kind"], "unknown")
        self.assertIsNone(records["item_generic_bundle"]["bundle_amount"])


if __name__ == "__main__":
    unittest.main()
