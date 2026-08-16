import hashlib
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "estimate"))
from model_estimator import estimate_model, _predict_elastic_net
sys.path.insert(0, str(ROOT / "tools" / "validate"))
from schema_validator import OfflineSchemaValidator
from modeling.train_elastic_net import train as train_elastic_net, load_rows, classify_columns, _frame, _fit_with_inner_groups


class ModelEstimatorTest(unittest.TestCase):
    def _account(self):
        return {
            "currency": "TWD", "server": "international", "review_status": "approved",
            "trade_conditions": {"offer_kind": "seller_listing", "entity_kind": "single_account", "price_type": "normal_listing"},
            "evidence_quality": {"listing_text": "high"},
            "resources": {"values": {"white_candles": 100}},
        }

    def _artifact(self, model_type, snapshot_hash):
        contract = {"kind": "additive_log_price", "intercept": 8.0,
                    "coefficients": {"resources.values.white_candles": 0.001}}
        if model_type == "elastic_net":
            contract = {"kind": "additive_log_price", "target_transform": "log_twd_price", "unknown_handling": "missing_mask",
                        "required_feature_columns": ["resources.values.white_candles"], "intercept": 8.0,
                        "coefficients": {"numeric__resources.values.white_candles": 0.01},
                        "continuous": {"columns": ["resources.values.white_candles"], "imputation_medians": {"resources.values.white_candles": 50}, "means": {"resources.values.white_candles": 50}, "scales": {"resources.values.white_candles": 10}, "missing_mask_columns": ["resources.values.white_candles"], "missing_indicator_scaling": {"resources.values.white_candles": {"feature_name": "numeric__missingindicator_resources.values.white_candles", "mean": 0.1, "scale": 0.3}}},
                        "categorical_vocabulary": {}, "feature_order": ["numeric__resources.values.white_candles", "numeric__missingindicator_resources.values.white_candles"]}
            contract["coefficients"]["numeric__missingindicator_resources.values.white_candles"] = 0.0
        return {
            "schema_version": "3.1-p1", "status": "trained", "model_type": model_type,
            "price_line": "normal_listing", "input_snapshot_paths": ["modeling/artifacts/snapshot.jsonl"],
            "input_snapshot_sha256": snapshot_hash,
            "training": {"outer_cv_mae": 0.2, "threshold_met": True, "baseline_beaten": True, "eligible_rows": 300, "minimum_rows": 300, "group_count": 300, "folds": 3, "baseline_mae": 0.3},
            "publication_gate": {"status": "passed", "independent_training_clusters": 300, "time_forward_holdout_clusters": 100, "time_forward_holdout": True, "metrics": {"mdape": 0.18, "p90_ape": 0.35, "median_baseline_mae_improvement": 0.16, "selector_mae_improvement": 0.11, "prediction_interval_80_coverage": 0.80, "median_interval_width_ratio": 0.45, "supported_case_rate": 0.82}},
            "feature_schema": {"features": [{"name": "resources.values.white_candles", "min": 0, "max": 1000}], "baselines": {"resources.values.white_candles": 50}},
            "prediction_contract": contract,
        }

    def _write_artifacts(self, root, elastic=True, xgb=True):
        artifact_dir = root / "modeling" / "artifacts"; artifact_dir.mkdir(parents=True)
        snapshot = artifact_dir / "snapshot.jsonl"; snapshot.write_text('{"test":true}\n', encoding="utf-8")
        file_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        digest = hashlib.sha256(b"modeling/artifacts/snapshot.jsonl\0" + file_hash.encode("ascii") + b"\n").hexdigest()
        if elastic:
            (artifact_dir / "elastic-net-normal_listing.json").write_text(json.dumps(self._artifact("elastic_net", digest)), encoding="utf-8")
        if xgb:
            try:
                import xgboost as xgb_runtime
            except ImportError:
                self.skipTest("optional xgboost runtime unavailable")
            modified = self._artifact("xgboost", digest); modified["training"]["outer_cv_mae"] = 0.1
            model_path = artifact_dir / "xgboost-normal_listing.model.json"
            model = xgb_runtime.XGBRegressor(n_estimators=2, max_depth=1, random_state=1)
            model.fit([[0.0], [100.0]], [8.0, 8.1])
            model.save_model(str(model_path))
            modified["model_file"] = model_path.name
            modified["model_sha256"] = hashlib.sha256(model_path.read_bytes()).hexdigest()
            (artifact_dir / "xgboost-normal_listing.json").write_text(json.dumps(modified), encoding="utf-8")

    def test_self_reported_two_model_publication_gate_cannot_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self._write_artifacts(root)
            result = estimate_model(self._account(), root=root)
        self.assertFalse(result["eligible"])
        self.assertEqual(result["status"], "insufficient_training_data")
        self.assertIn("model_publication_disabled_in_p2_1", result["insufficiency_reasons"])
        validator = OfflineSchemaValidator(ROOT / "schemas")
        self.assertEqual(validator.validate(result, ROOT / "schemas" / "model" / "model-estimate-result.schema.json"), [])

    def test_self_reported_single_model_publication_gate_cannot_publish(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self._write_artifacts(root, xgb=False)
            result = estimate_model(self._account(), root=root)
        self.assertFalse(result["eligible"])
        self.assertIn("model_publication_disabled_in_p2_1", result["insufficiency_reasons"])

    def test_no_trained_artifacts_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            result = estimate_model(self._account(), root=Path(directory))
        self.assertFalse(result["eligible"])
        self.assertEqual(result["status"], "insufficient_training_data")
        self.assertIsNone(result["range_twd"])

    def test_unknown_feature_and_ood_do_not_impute(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self._write_artifacts(root)
            unknown = self._account(); unknown["resources"] = {"values": {}}
            unknown_result = estimate_model(unknown, root=root)
            outlier = self._account(); outlier["resources"] = {"values": {"white_candles": 1001}}
            outlier_result = estimate_model(outlier, root=root)
        self.assertFalse(unknown_result["eligible"])
        self.assertFalse(outlier_result["eligible"])
        self.assertIn("model_publication_disabled_in_p2_1", unknown_result["insufficiency_reasons"])

    def test_market_and_evidence_gates_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self._write_artifacts(root)
            account = self._account(); account["currency"] = "CNY"; account["evidence_quality"] = {"listing_text": "unknown"}
            result = estimate_model(account, root=root)
        self.assertEqual(result["status"], "ineligible_input")
        self.assertIn("currency_must_be_twd", result["insufficiency_reasons"])
        self.assertIn("listing_evidence_insufficient", result["insufficiency_reasons"])

    def test_snapshot_hash_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self._write_artifacts(root)
            (root / "modeling" / "artifacts" / "snapshot.jsonl").write_text("changed\n", encoding="utf-8")
            result = estimate_model(self._account(), root=root)
        self.assertFalse(result["eligible"])
        self.assertIn("snapshot_hash_mismatch", result["insufficiency_reasons"])

    def test_xgboost_cannot_reach_model_loading_while_publication_is_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self._write_artifacts(root, elastic=False)
            artifact_path = root / "modeling" / "artifacts" / "xgboost-normal_listing.json"
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            artifact["model_sha256"] = "0" * 64
            artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
            result = estimate_model(self._account(), root=root)
        self.assertFalse(result["eligible"])
        self.assertIn("model_publication_disabled_in_p2_1", result["insufficiency_reasons"])

    def test_xgboost_sparse_feature_is_nan_not_unknown_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self._write_artifacts(root, elastic=False)
            account = self._account(); account["resources"] = {"values": {}}
            result = estimate_model(account, root=root)
        self.assertFalse(result["eligible"])
        self.assertIn("model_publication_disabled_in_p2_1", result["insufficiency_reasons"])

    def test_trained_artifact_without_quality_evidence_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); self._write_artifacts(root, xgb=False)
            artifact_path = root / "modeling" / "artifacts" / "elastic-net-normal_listing.json"
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            artifact["training"].pop("baseline_beaten")
            artifact_path.write_text(json.dumps(artifact), encoding="utf-8")
            result = estimate_model(self._account(), root=root)
        self.assertFalse(result["eligible"])
        self.assertIn("training_baseline_not_beaten", result["insufficiency_reasons"])

    def test_trainer_elastic_artifact_runs_exact_json_preprocessing_end_to_end(self):
        # A real trainer artifact (not a hand-authored coefficient fixture) is
        # written into a miniature repository, then consumed by the estimator.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text("{}\n", encoding="utf-8")
            source = root / "data" / "modeling" / "vectors.jsonl"; source.parent.mkdir(parents=True)
            rows = []
            for index in range(100):
                features = {"tier": "a" if index % 2 else "b"}
                if index % 10:
                    features["signal"] = index
                rows.append({"account_id": f"account_{index}", "price_twd": round(1000 * (1.01 ** index), 2), "price_type": "normal_listing", "group_id": f"group_{index}", "features": features})
            source.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            artifact = train_elastic_net(source, "normal_listing")
            self.assertEqual(artifact["status"], "trained")
            artifact_dir = root / "modeling" / "artifacts"; artifact_dir.mkdir(parents=True)
            (artifact_dir / "elastic-net-normal_listing.json").write_text(json.dumps(artifact), encoding="utf-8")
            account = self._account(); account["features"] = {"signal": 55, "tier": "a"}
            result = estimate_model(account, root=root)
            # Refit the exact deterministic pipeline and compare its log
            # prediction with JSON inference for both category values and an
            # explicit missing numeric input.
            training_rows, _ = load_rows(source, "normal_listing")
            numeric, categorical = classify_columns(training_rows)
            frame = _frame(training_rows, numeric, categorical)
            import numpy as np
            pipeline = _fit_with_inner_groups(frame, np.log(np.asarray([row["price"] for row in training_rows])), [row["group"] for row in training_rows], numeric, categorical)
            for features in ({"signal": 55, "tier": "a"}, {"signal": 56, "tier": "b"}, {"tier": "b"}):
                expected = float(pipeline.predict(_frame([{"features": features}], numeric, categorical))[0])
                received, _, reasons = _predict_elastic_net(artifact["prediction_contract"], {"features": features}, {})
                self.assertEqual(reasons, [])
                self.assertTrue(math.isclose(received, expected, rel_tol=0, abs_tol=1e-10))
        self.assertFalse(result["eligible"])
        self.assertIn("model_publication_disabled_in_p2_1", result["insufficiency_reasons"])

    def test_formal_p1_artifacts_are_present_but_insufficient(self):
        result = estimate_model(self._account(), root=ROOT)
        self.assertEqual(result["status"], "insufficient_training_data")
        self.assertFalse(result["eligible"])
        self.assertIsNone(result["range_twd"])
        rejected = {Path(row["path"]).name: row["reasons"] for row in result["artifact_rejections"]}
        self.assertIn("elastic-net-normal_listing.json", rejected)
        self.assertIn("xgboost-normal_listing.json", rejected)
        self.assertTrue(all(any(reason.startswith("artifact_not_trained") for reason in reasons) for reasons in rejected.values()))

    def test_caller_cannot_self_approve_an_unverified_catalog_item(self):
        item = json.loads(next(line for line in (ROOT / "knowledge/items/items.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()))
        account = self._account()
        account["item_states"] = [{
            "item_id": item["item_id"], "state": "owned", "evidence_state": "profile_claim",
            "model_feature": True, "conflict": False, "review_status": "approved",
        }]
        result = estimate_model(account, root=ROOT)
        self.assertEqual(result["status"], "ineligible_input")
        self.assertIn(f"catalog_item_not_model_eligible:{item['item_id']}", result["insufficiency_reasons"])


if __name__ == "__main__":
    unittest.main()
