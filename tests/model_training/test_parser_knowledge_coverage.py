from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "modeling"))
from parser_knowledge_coverage import audit, build, read_jsonl  # noqa: E402


class ParserKnowledgeCoverageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.items = read_jsonl(ROOT / "knowledge/items/items.jsonl")
        self.aliases = read_jsonl(ROOT / "knowledge/aliases/item-aliases.jsonl")
        self.vectors = read_jsonl(ROOT / "data/modeling/account-item-vectors.jsonl")
        self.sidecar = read_jsonl(ROOT / "data/review/account-catalog-resolution.jsonl")
        self.costs = read_jsonl(ROOT / "data/derived/official-historical-cost-references.jsonl")

    def test_current_report_is_dynamic_non_model_item_audit(self):
        report = build(ROOT)
        self.assertFalse(report["model_feature"])
        self.assertEqual(report["summary"]["canonical_item_count"], len(self.items))
        self.assertEqual(report["summary"]["verified_canonical_item_count"], sum(row["verification_status"] == "verified" for row in self.items))
        self.assertEqual(report["summary"]["known_state_count"], report["summary"]["known_owned_count"] + report["summary"]["known_missing_count"])
        self.assertEqual({row["item_id"] for row in report["items"]}, {row["item_id"] for row in self.items})
        self.assertTrue(all(row["model_feature"] is False for row in report["items"]))

    def test_unknown_ids_are_rejected(self):
        bad_costs = copy.deepcopy(self.costs)
        bad_costs[0]["item_id"] = "item_not_in_catalog"
        with self.assertRaisesRegex(ValueError, "unknown canonical item"):
            audit(self.items, self.aliases, self.vectors, self.sidecar, bad_costs)
        bad_vectors = copy.deepcopy(self.vectors)
        bad_vectors[0]["item_states"][0]["item_id"] = "item_not_in_catalog"
        with self.assertRaisesRegex(ValueError, "vector references unknown"):
            audit(self.items, self.aliases, bad_vectors, self.sidecar, self.costs)
        bad_sidecar = copy.deepcopy(self.sidecar)
        target = next(row for row in bad_sidecar if row["matches"])
        target["matches"][0]["query_entity_id"] = "item_not_in_catalog"
        with self.assertRaisesRegex(ValueError, "review sidecar references unknown"):
            audit(self.items, self.aliases, self.vectors, bad_sidecar, self.costs)

    def test_sidecar_cannot_promote_ownership_or_model_status(self):
        sidecar = copy.deepcopy(self.sidecar)
        target = next(row for row in sidecar if row["matches"])
        target["matches"][0]["ownership_state"] = "owned"
        with self.assertRaisesRegex(ValueError, "must not carry ownership"):
            audit(self.items, self.aliases, self.vectors, sidecar, self.costs)
        sidecar = copy.deepcopy(self.sidecar)
        sidecar[0]["model_feature"] = True
        with self.assertRaisesRegex(ValueError, "must remain non-model"):
            audit(self.items, self.aliases, self.vectors, sidecar, self.costs)


if __name__ == "__main__":
    unittest.main()
