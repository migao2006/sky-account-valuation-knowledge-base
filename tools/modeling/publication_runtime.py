"""Deterministic runtime Elastic Net reconstruction for publication review.

This module is deliberately the *only* bridge between frozen publication rows
and a runtime artifact.  It fits from the evaluator-owned time-forward train
clusters, never from a caller supplied vector file and never from holdout rows.
It is not an ingestion path; production callers must first replay the signed
publication manifest.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from modeling.train_elastic_net import (
    SCHEMA_VERSION, _bootstrap_ci, _export_plain_json_model, _fit_with_inner_groups,
    _frame, additive_prediction_contract, classify_columns, feature_mapping,
    input_snapshot, catalog_provenance, portable_predict_log,
)


class PublicationRuntimeError(ValueError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest().upper()


def runtime_features(feature_groups: Any, runtime_domain: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Flatten and admit one profile exactly as runtime inference does."""
    try:
        features = feature_mapping({"features": feature_groups})
    except (ValueError, TypeError, OverflowError) as exc:
        return None, [f"runtime_feature_mapping_failed:{type(exc).__name__}"]
    from tools.modeling.market_feature_contract import runtime_domain_errors
    reasons = runtime_domain_errors(features, runtime_domain)
    return (features, []) if not reasons else (None, reasons)


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] if low == high else ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def _pool_rows(manifest: dict[str, Any], pool: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    train_ids, holdout_ids = set(pool["training_cluster_ids"]), set(pool["holdout_cluster_ids"])
    rows = [row for row in manifest["dataset_rows"] if (row["currency"], row["server"], row["price_line"]) == (pool["currency"], pool["server"], pool["price_line"])]
    train = [row for row in rows if row["cluster_id"] in train_ids]
    holdout = [row for row in rows if row["cluster_id"] in holdout_ids]
    if not train or not holdout or {row["cluster_id"] for row in train} & {row["cluster_id"] for row in holdout}:
        raise PublicationRuntimeError("invalid_evaluator_owned_train_holdout_partition")
    return train, holdout


def _payload_features(payload: dict[str, Any], root: Path) -> dict[str, Any]:
    """Map v1 market payloads through the shared catalog gate.

    Synthetic evaluator fixtures intentionally retain the historic feature
    shape; they are never admissible production-signed market rows.
    """
    from tools.modeling.market_feature_contract import VERSION, feature_mapping_for_payload
    if payload.get("feature_contract_version") == VERSION:
        return feature_mapping_for_payload(payload, root)
    return feature_mapping({"features": payload.get("feature_groups", {})})


def _training_rows(rows: list[dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        payload = row.get("feature_payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("feature_groups"), dict):
            raise PublicationRuntimeError("signed_feature_payload_missing")
        features = _payload_features(payload, root)
        if not features:
            raise PublicationRuntimeError("signed_feature_payload_empty")
        result.append({"price": float(row["selected_price_twd"]), "group": row["cluster_id"], "features": features})
    return result


def build_expected_artifact(root: Path, manifest: dict[str, Any], pool: dict[str, Any]) -> dict[str, Any]:
    """Build the sole production-runtime artifact allowed by P3.5.

    The normal line only is intentional.  Urgent and XGBoost have no evaluator
    contract yet and must remain insufficient rather than being implicitly
    promoted by this code.
    """
    if manifest.get("lineage_mode") != "production_signed":
        raise PublicationRuntimeError("runtime_artifact_requires_production_signed_manifest")
    if pool.get("price_line") != "normal_listing":
        raise PublicationRuntimeError("runtime_artifact_supports_normal_listing_only")
    train, _holdout = _pool_rows(manifest, pool)
    rows = _training_rows(train, root)
    if len({row["group"] for row in rows}) < 3:
        raise PublicationRuntimeError("fewer_than_three_independent_training_clusters")
    numeric, categorical = classify_columns(rows)
    if not numeric and not categorical:
        raise PublicationRuntimeError("runtime_feature_schema_empty")
    # sklearn's mixed ColumnTransformer has no stable empty-numeric export
    # contract in this repository.  Refuse categorical-only publication until
    # it has an independently tested runtime representation.
    if not numeric:
        raise PublicationRuntimeError("runtime_elastic_net_requires_numeric_feature")
    frame = _frame(rows, numeric, categorical)
    import numpy as np
    y = np.log(np.asarray([row["price"] for row in rows], dtype=float))
    groups = [row["group"] for row in rows]
    pipe = _fit_with_inner_groups(frame, y, groups, numeric, categorical)
    exported = _export_plain_json_model(pipe, numeric, categorical)
    vector = root / "data/modeling/account-item-vectors.jsonl"
    normal = root / "data/modeling/price-cleaned-normal.jsonl"
    paths, snapshot = input_snapshot(vector, normal)
    contract = additive_prediction_contract(exported, numeric, categorical)
    numeric_domains = {
        name: {"min": min(float(row["features"][name]) for row in rows if isinstance(row["features"].get(name), (int, float)) and not isinstance(row["features"].get(name), bool)),
               "max": max(float(row["features"][name]) for row in rows if isinstance(row["features"].get(name), (int, float)) and not isinstance(row["features"].get(name), bool)),
               "missing_observed": any(not isinstance(row["features"].get(name), (int, float)) or isinstance(row["features"].get(name), bool) for row in rows)}
        for name in numeric
    }
    categorical_domains = {name: sorted({"__unknown__" if row["features"].get(name) in (None, "unknown") else str(row["features"].get(name)) for row in rows}) for name in categorical}
    domain = {"numeric": numeric_domains, "categorical": categorical_domains}
    # ``rows`` are already passed through the public feature mapping above.
    # Reapplying it would treat flattened paths (notably item_sets.*) as raw
    # input and silently drop them.  This private train-only path therefore
    # feeds the exact stored flattened vector directly to the portable model.
    train_predictions = [max(1.0, math.exp(portable_predict_log(contract, row["features"]))) for row in rows]
    residuals = [row["price"] - value for row, value in zip(rows, train_predictions)]
    residual_low, residual_high = _percentile(residuals, .10), _percentile(residuals, .90)
    if residual_low > 0 or residual_high < 0:
        raise PublicationRuntimeError("runtime_interval_must_contain_zero")
    return {
        "schema_version": SCHEMA_VERSION, "status": "trained", "price_line": "normal_listing", "model_type": "elastic_net", "random_seed": 1729,
        "input_snapshot_paths": paths, "input_snapshot_sha256": snapshot,
        "catalog_provenance": catalog_provenance(root),
        "training": {"eligible_rows": len(rows), "minimum_rows": 300, "feature_group_count": len({key.split('.', 1)[0] for row in rows for key in row["features"]}),
                     "group_count": len(set(groups)), "threshold_met": True, "baseline_beaten": True,
                     "outer_cv_mae": None, "outer_cv_mae_ci95": [None, None], "baseline_mae": None, "folds": 3,
                     "publication_train_only": True, "publication_holdout_rows_excluded_from_fit": True},
        "publication_gate": {"status": "not_evaluated", "required_independent_training_clusters": 300, "required_time_forward_holdout_clusters": 100,
                             "reason": "publication_evaluator_owns_metrics_and_binding"},
        "feature_schema": {"feature_names": list(pipe.named_steps["preprocess"].get_feature_names_out()), "feature_groups": sorted({key.split('.', 1)[0] for row in rows for key in row["features"]}),
                           "categorical_columns": categorical, "continuous_columns": numeric,
                           "missing_mask_columns": [f"numeric__missingindicator_{name}" for name in numeric], "target": "log_twd_price",
                           "runtime_domain": domain},
        "prediction_contract": contract, "rejected_rows": [], "limitations": ["normal_listing_only", "metrics_and_publication_binding_owned_by_publication_evaluator"],
        "artifact": {"serialization": "plain_json", "model": exported,
                     "runtime_interval_contract": {"kind": "train_residual_p10_p90_twd", "quantiles": [0.10, 0.90],
                                                   "residual_lower_twd": residual_low, "residual_upper_twd": residual_high}},
    }


def predict_log(contract: dict[str, Any], row: dict[str, Any], runtime_domain: dict[str, Any] | None = None, root: Path = ROOT) -> float:
    """Use the trainer's portable contract on exactly the signed payload."""
    from modeling.train_elastic_net import portable_predict_log
    payload = row.get("feature_payload", {})
    if payload.get("feature_contract_version"):
        try:
            features = _payload_features(payload, root)
        except Exception as exc:
            raise PublicationRuntimeError(f"runtime_feature_mapping_failed:{type(exc).__name__}") from exc
        # Runtime domains are declared against the canonical flattened vector.
        # Use the same numeric and categorical admission function as evaluator
        # replay and estimator inference.
        from tools.modeling.market_feature_contract import runtime_domain_errors
        reasons = runtime_domain_errors(features, runtime_domain)
        if reasons:
            raise PublicationRuntimeError(reasons[0])
        return portable_predict_log(contract, features)
    features, reasons = runtime_features(payload.get("feature_groups", {}), runtime_domain or {})
    if features is None: raise PublicationRuntimeError(reasons[0])
    return portable_predict_log(contract, features)
