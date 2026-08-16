import json
import hashlib
import tempfile
import subprocess
import unittest
from pathlib import Path

from modeling.item_value_table import build
from modeling.train_xgboost import flatten_vector, grouped_fold_indices, train


class XGBoostAndItemTableTests(unittest.TestCase):
    def test_unknown_item_is_not_encoded_as_confirmed_missing(self):
        values, _ = flatten_vector({"item_states": [{"item_id": "item_example", "state": "unknown", "model_feature": True, "review_status": "approved"}]}, {"item_example"})
        self.assertEqual(values["item:item_example:known"], 0.0)
        self.assertNotIn("item:item_example:owned", values)

    def test_xgboost_item_features_require_canonical_whitelist(self):
        with self.assertRaisesRegex(Exception, "legacy_item_state_mapping_not_supported"):
            flatten_vector({"item_states": {"item_fabricated": "owned"}}, set())
        with self.assertRaisesRegex(Exception, "item_not_in_model_eligible_catalog"):
            flatten_vector({"item_states": [{"item_id": "item_fabricated", "state": "owned", "model_feature": True, "review_status": "approved"}]}, set())

    def test_sparse_training_fails_closed_at_xgboost_threshold(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, artifact = root / "vectors.jsonl", root / "artifact.json"
            source.write_text(json.dumps({"account_id": "account_a", "price_twd": 1000, "price_type": "normal_listing", "feature_groups": {"seasons": {"complete": 1}}}) + "\n", encoding="utf-8")
            actual = train(source, artifact, "normal_listing")
            self.assertEqual(actual["status"], "insufficient_training_data")
            self.assertEqual(actual["training"]["min_required_records"], 300)
            self.assertIsNone(actual["model_file"])

    def test_formal_price_join_preserves_approved_item_state_feature(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "manifest.json").write_text("{}\n", encoding="utf-8")
            catalog = root / "knowledge" / "items" / "items.jsonl"; catalog.parent.mkdir(parents=True)
            catalog.write_text(json.dumps({"item_id": "item_approved", "verification_status": "verified", "model_feature_status": "eligible"}) + "\n", encoding="utf-8")
            vectors, prices, artifact = root / "vectors.jsonl", root / "prices.jsonl", root / "artifact.json"
            vectors.write_text(json.dumps({
                "account_id": "account_a", "feature_groups": {"resources": {"white": 3}},
                "item_states": [{"item_id": "item_approved", "state": "owned", "model_feature": True, "review_status": "approved"}],
            }) + "\n", encoding="utf-8")
            prices.write_text(json.dumps({"account_id": "account_a", "selected_price_twd": 1000, "price_line": "normal_listing", "cluster_id": "cluster_a"}) + "\n", encoding="utf-8")
            actual = train(vectors, artifact, "normal_listing", prices_path=prices)
            names = actual["feature_schema"]["feature_names"]
            self.assertIn("item:item_approved:known", names)
            self.assertIn("item:item_approved:owned", names)
            self.assertFalse(any(name.startswith("items.item_approved") for name in names))
            self.assertEqual(actual["prediction_contract"]["missing_feature_encoding"], "NaN")

    def test_item_table_never_emits_sparse_item_number(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vectors, explanations, table = root / "vectors.jsonl", root / "explanations.jsonl", root / "table.jsonl"
            vectors.write_text(json.dumps({"account_id": "account_a", "item_states": {"item_example": "owned"}}) + "\n", encoding="utf-8")
            explanations.write_text("", encoding="utf-8")
            rows = build(vectors, explanations, table)
            self.assertEqual(rows[0]["status"], "insufficient_support")
            self.assertIsNone(rows[0]["mean_conditional_attribution"])
            self.assertEqual(rows[0]["valuation_kind"], "conditional_model_attribution_not_additive_item_price")

    def test_formal_vectors_with_empty_explanations_still_list_catalog_items(self):
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as temporary:
            empty, table = Path(temporary) / "empty.jsonl", Path(temporary) / "table.jsonl"
            empty.write_text("", encoding="utf-8")
            rows = build(root / "data/modeling/account-item-vectors.jsonl", empty, table)
        canonical_ids = {
            row["item_id"]
            for row in (json.loads(line) for line in (root / "knowledge/items/items.jsonl").read_text(encoding="utf-8").splitlines() if line.strip())
        }
        self.assertEqual({row["item_id"] for row in rows}, canonical_ids)
        self.assertEqual(len(rows), len(canonical_ids))
        self.assertTrue(all(row["status"] == "insufficient_support" for row in rows))
        self.assertTrue(all(row["mean_conditional_attribution"] is None for row in rows))
        self.assertTrue(all(row["owned_sample_count"] + row["confirmed_missing_sample_count"] + row["unknown_sample_count"] == 1022 for row in rows))

    def test_direct_cli_modules_are_importable(self):
        root = Path(__file__).resolve().parents[2]
        for filename in ("train_xgboost.py", "explain.py", "item_value_table.py"):
            completed = subprocess.run(["python", str(root / "modeling" / filename), "--help"], cwd=root, capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_grouped_outer_cv_never_splits_one_cluster_across_folds(self):
        groups = ["cluster_a", "cluster_a", "cluster_b", "cluster_b", "cluster_c", "cluster_c", "cluster_d", "cluster_d"]
        for train_indices, test_indices in grouped_fold_indices(groups, 4):
            train_groups = {groups[index] for index in train_indices}
            test_groups = {groups[index] for index in test_indices}
            self.assertFalse(train_groups.intersection(test_groups))

    def test_nonempty_explanations_without_verified_provenance_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            vectors, explanations, table = root / "vectors.jsonl", root / "explanations.jsonl", root / "table.jsonl"
            vectors.write_text(json.dumps({"account_id": "account_a", "item_states": {"item_example": "owned"}}) + "\n", encoding="utf-8")
            explanations.write_text(json.dumps({"account_id": "account_a", "main_effects": {}}) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "provenance"):
                build(vectors, explanations, table)

    def test_forged_single_model_refit_claim_cannot_publish_ten_plus_five_item(self):
        """Even valid hashes cannot turn one handcrafted model into refit evidence."""
        root = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(dir=root) as temporary:
            directory = Path(temporary); rel = directory.relative_to(root).as_posix()
            vectors, explanations, model, artifact, table = (directory / name for name in ("vectors.jsonl", "explanations.jsonl", "model.json", "artifact.json", "table.jsonl"))
            vector_rows = []
            for index in range(15):
                vector_rows.append({"account_id": f"account_{index}", "item_states": [{"item_id": "item_example", "state": "owned" if index < 10 else "confirmed_missing", "model_feature": True, "review_status": "approved", "evidence_state": "profile_claim", "conflict": False}]})
            vectors.write_text("\n".join(json.dumps(row) for row in vector_rows) + "\n", encoding="utf-8")
            model.write_text("safe-json-placeholder", encoding="utf-8")
            vector_hash = hashlib.sha256(vectors.read_bytes()).hexdigest()
            snapshot_digest = hashlib.sha256(f"{rel}/vectors.jsonl\0{vector_hash}\n".encode()).hexdigest()
            payload = {"schema_version": "3.1-p1", "model_type": "xgboost", "status": "trained", "price_line": "normal_listing", "input_snapshot_paths": [f"{rel}/vectors.jsonl"], "input_snapshot_sha256": snapshot_digest, "model_file": "model.json", "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(), "training": {"threshold_met": True, "baseline_beaten": True, "outer_cv_mae": 0.1, "baseline_median_mae": 0.2, "group_count": 4, "outer_cv_folds": 2}}
            artifact.write_text(json.dumps(payload), encoding="utf-8")
            artifact_hash = hashlib.sha256(artifact.read_bytes()).hexdigest()
            explanation_rows = [{"account_id": row["account_id"], "model_type": "xgboost", "price_line": "normal_listing", "artifact_sha256": artifact_hash.upper(), "model_sha256": payload["model_sha256"].upper(), "input_snapshot_sha256": snapshot_digest.upper(), "main_effects": {"item:item_example:owned": 0.3}, "top_interactions": []} for row in vector_rows]
            explanations.write_text("\n".join(json.dumps(row) for row in explanation_rows) + "\n", encoding="utf-8")
            sidecar = {"model_type": "xgboost", "price_line": "normal_listing", "artifact_path": f"{rel}/artifact.json", "artifact_sha256": artifact_hash.upper(), "model_file": "model.json", "model_sha256": payload["model_sha256"].upper(), "input_snapshot_sha256": snapshot_digest.upper(), "explained_vector_path": f"{rel}/vectors.jsonl", "explained_vector_sha256": vector_hash.upper(), "explanations_sha256": hashlib.sha256(explanations.read_bytes()).hexdigest().upper(), "refit_fold_count": 99, "refit_direction_stability": 1.0}
            explanations.with_suffix(".jsonl.provenance.json").write_text(json.dumps(sidecar), encoding="utf-8")
            rows = build(vectors, explanations, table)
        self.assertEqual(rows[0]["status"], "insufficient_support")
        self.assertIsNone(rows[0]["mean_conditional_attribution"])


if __name__ == "__main__":
    unittest.main()
