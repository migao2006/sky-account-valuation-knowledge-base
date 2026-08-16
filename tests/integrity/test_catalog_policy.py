"""Catalog evidence and model-eligibility invariants for P1."""
from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_jsonl(relative: str) -> list[dict]:
    return [json.loads(line) for line in (ROOT / relative).read_text(encoding="utf-8").splitlines() if line.strip()]


class CatalogPolicyTests(unittest.TestCase):
    def test_candidate_items_are_not_canonical_items(self):
        canonical = {row["item_id"] for row in read_jsonl("knowledge/items/items.jsonl")}
        candidates = {row["candidate_item_id"] for row in read_jsonl("data/review/item-candidates.jsonl")}
        self.assertEqual(len(canonical), 94)
        self.assertEqual(len(candidates), 622)
        self.assertFalse(canonical & candidates)

    def test_only_high_evidence_verified_items_can_be_model_eligible(self):
        items = read_jsonl("knowledge/items/items.jsonl")
        eligible = [row for row in items if row["model_feature_status"] == "eligible"]
        self.assertEqual(eligible, [])
        for row in items:
            if row["model_feature_status"] == "eligible":
                self.assertEqual(row["verification_status"], "verified")
                self.assertIn(row["evidence_tier"], {"official_item_specific", "official_with_secondary"})
            else:
                self.assertEqual(row["model_feature_status"], "excluded_pending_verification")

    def test_canonical_aliases_are_globally_unambiguous(self):
        aliases = read_jsonl("knowledge/aliases/item-aliases.jsonl")
        mappings: dict[str, set[tuple[str, str]]] = {}
        for row in aliases:
            mappings.setdefault(row["normalized_alias"], set()).add((row["target_type"], row["target_id"]))
        self.assertFalse({alias: targets for alias, targets in mappings.items() if len(targets) > 1})

    def test_alias_conflicts_are_quarantined_not_canonical(self):
        aliases = {row["alias_id"] for row in read_jsonl("knowledge/aliases/item-aliases.jsonl")}
        for conflict in read_jsonl("data/review/alias-conflicts.jsonl"):
            self.assertTrue(set(conflict["source_alias_ids"]).isdisjoint(aliases))
            self.assertGreaterEqual(len(conflict["candidate_targets"]), 2)


if __name__ == "__main__":
    unittest.main()
