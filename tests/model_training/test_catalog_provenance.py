"""Negative tests for catalog-bound vectors and offline model artifacts."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from modeling.train_elastic_net import ModelingInputError, feature_mapping, input_snapshot, train
from modeling.train_xgboost import flatten_vector
from tools.modeling.catalog_provenance import CatalogProvenanceError, catalog_provenance, validate_artifact_catalog_provenance, validate_vector_catalog_provenance


class CatalogProvenanceTests(unittest.TestCase):
    def _repository(self) -> tuple[tempfile.TemporaryDirectory, Path]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "manifest.json").write_text("{}\n", encoding="utf-8")
        items = root / "knowledge/items/items.jsonl"; items.parent.mkdir(parents=True)
        items.write_text(json.dumps({"item_id": "item_verified", "verification_status": "verified", "model_feature_status": "eligible"}) + "\n" + json.dumps({"item_id": "item_review", "verification_status": "needs_review", "model_feature_status": "excluded_pending_verification"}) + "\n", encoding="utf-8")
        aliases = root / "knowledge/aliases/item-aliases.jsonl"; aliases.parent.mkdir(parents=True)
        aliases.write_text("", encoding="utf-8")
        sets = root / "knowledge/sets/item-sets.jsonl"; sets.parent.mkdir(parents=True)
        sets.write_text("", encoding="utf-8")
        return temporary, root

    def _vector(self, root: Path) -> dict:
        return {
            "account_id": "account_fixture",
            "price_type": "normal_listing",
            "price_twd": 1000,
            "feature_groups": {"resources": {"white": 1}, "item_sets": []},
            "catalog_provenance": catalog_provenance(root),
            "item_states": [
                {"item_id": "item_verified", "state": "owned", "evidence_state": "profile_claim", "conflict": False, "model_feature": True, "review_status": "approved"},
                {"item_id": "item_review", "state": "unknown", "evidence_state": "unknown", "conflict": False, "model_feature": False, "review_status": "needs_review"},
            ],
        }

    def test_formal_snapshot_directly_includes_catalog_files_and_binding(self):
        _, root = self._repository()
        vectors = root / "data/modeling/vectors.jsonl"; vectors.parent.mkdir(parents=True)
        vectors.write_text(json.dumps(self._vector(root)) + "\n", encoding="utf-8")
        paths, _ = input_snapshot(vectors, None)
        self.assertEqual(paths, ["data/modeling/vectors.jsonl", "knowledge/aliases/item-aliases.jsonl", "knowledge/items/items.jsonl", "knowledge/sets/item-sets.jsonl"])
        artifact = train(vectors, "normal_listing")
        self.assertEqual(artifact["status"], "insufficient_training_data")
        self.assertEqual(artifact["catalog_provenance"], catalog_provenance(root))
        self.assertTrue(set(catalog_provenance(root)["pinned_catalog_paths"]).issubset(artifact["input_snapshot_paths"]))

    def test_stale_catalog_vector_is_rejected_before_training(self):
        _, root = self._repository()
        vector = self._vector(root)
        # Alter one pinned catalog file after vector construction.
        (root / "knowledge/aliases/item-aliases.jsonl").write_text('{"changed":true}\n', encoding="utf-8")
        vectors = root / "vectors.jsonl"; vectors.write_text(json.dumps(vector) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ModelingInputError, "stale_catalog_provenance"):
            train(vectors, "normal_listing")

    def test_stale_catalog_artifact_is_rejected(self):
        _, root = self._repository()
        artifact = {
            "catalog_provenance": catalog_provenance(root),
            "input_snapshot_paths": ["vectors.jsonl", *catalog_provenance(root)["pinned_catalog_paths"]],
        }
        validate_artifact_catalog_provenance(artifact, root)
        (root / "knowledge/sets/item-sets.jsonl").write_text('{"changed":true}\n', encoding="utf-8")
        with self.assertRaisesRegex(CatalogProvenanceError, "artifact_catalog_provenance_mismatch"):
            validate_artifact_catalog_provenance(artifact, root)

    def test_forged_model_feature_is_rejected_by_both_model_mappings(self):
        vector = {"feature_groups": {}, "item_states": [{"item_id": "item_forged", "state": "owned", "model_feature": True, "review_status": "approved"}]}
        with self.assertRaisesRegex(ModelingInputError, "item_not_in_model_eligible_catalog"):
            feature_mapping(vector, {"item_verified"})
        with self.assertRaisesRegex(ModelingInputError, "item_not_in_model_eligible_catalog"):
            flatten_vector(vector, {"item_verified"})

    def test_forged_set_aggregate_is_rejected_before_model_mapping(self):
        _, root = self._repository()
        (root / "knowledge/sets/item-sets.jsonl").write_text(
            json.dumps({"set_id": "set_verified", "required_item_ids": ["item_verified"]}) + "\n",
            encoding="utf-8",
        )
        vector = self._vector(root)
        vector["feature_groups"]["item_sets"] = [{
            "set_id": "set_verified", "owned_item_ids": ["item_verified"],
            "confirmed_missing_item_ids": [], "member_count": 1,
            "known_member_count": 1, "completion_ratio": 0.5,
            "is_complete": True, "model_feature": True,
        }]
        with self.assertRaisesRegex(CatalogProvenanceError, "set_profile_policy_mismatch"):
            validate_vector_catalog_provenance(vector, root)


if __name__ == "__main__":
    unittest.main()
