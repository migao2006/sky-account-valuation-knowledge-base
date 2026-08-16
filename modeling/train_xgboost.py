#!/usr/bin/env python3
"""Train the optional offline nonlinear (XGBoost) price model.

This is research infrastructure, not a per-item pricing rule.  It consumes
pre-built item vectors and writes an explicit insufficient-data artifact until
the conservative sample threshold is met.  It never downloads packages/data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modeling.train_elastic_net import ModelingInputError, feature_mapping, input_snapshot, load_price_map, repository_root

PRICE_LINES = {"normal_listing", "urgent_sale"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def snapshot_hash(paths: list[tuple[str, Path]]) -> str:
    """Hash a deterministic, path-bound snapshot without relying on checkout name."""
    payload = b""
    for relative, path in sorted(paths, key=lambda item: item[0]):
        payload += relative.replace("\\", "/").encode("utf-8") + b"\0"
        payload += hashlib.sha256(path.read_bytes()).hexdigest().upper().encode("ascii") + b"\n"
    return hashlib.sha256(payload).hexdigest().upper()


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    return None


def load_model_eligible_items(input_path: Path) -> set[str]:
    """Read the canonical item whitelist associated with a repository input."""
    try:
        root = repository_root(input_path)
        catalog = read_jsonl(root / "knowledge/items/items.jsonl")
    except (ModelingInputError, OSError, json.JSONDecodeError):
        return set()
    return {
        row["item_id"] for row in catalog
        if isinstance(row.get("item_id"), str)
        and row.get("verification_status") == "verified"
        and row.get("model_feature_status") == "eligible"
    }


def flatten_vector(record: dict[str, Any], eligible_item_ids: set[str] | None = None) -> tuple[dict[str, float], dict[str, str]]:
    """Return numeric columns and their feature group without conflating unknown.

    Item state creates a separate known mask.  Thus unknown is neither owned
    nor confirmed missing, and models can learn missingness without treating it
    as an absence.
    """
    values: dict[str, float] = {}
    groups: dict[str, str] = {}
    # Reuse Elastic Net's canonical vector parser.  That function alone
    # decides which catalog items are approved formal features; candidates and
    # sensitivity-only items never reach this nonlinear model.
    raw_features = feature_mapping(record)
    for key, raw in raw_features.items():
        # train_elastic_net exposes its categorical item state for its own
        # one-hot pipeline.  XGBoost uses the explicit known/owned pair below
        # instead, so one item never has two semantically divergent features.
        if str(key).startswith("items."):
            continue
        group = str(key).split(".", 1)[0]
        numeric = _number(raw)
        if numeric is not None:
            values[str(key)], groups[str(key)] = numeric, group
        else:
            category = "__unknown__" if raw in (None, "unknown") else str(raw)
            name = f"{key}={category}"
            values[name], groups[name] = 1.0, group
    states = record.get("item_states", {})
    if isinstance(states, dict) and states:
        raise ModelingInputError("legacy_item_state_mapping_not_supported")
    if isinstance(states, list):
        for state in states:
            if not isinstance(state, dict) or state.get("model_feature") is not True or state.get("review_status") != "approved":
                continue
            item_id = state.get("item_id")
            if not isinstance(item_id, str):
                continue
            if eligible_item_ids is None or item_id not in eligible_item_ids:
                raise ModelingInputError(f"item_not_in_model_eligible_catalog:{item_id}")
            base = f"item:{item_id}"
            groups[f"{base}:known"] = groups[f"{base}:owned"] = "items"
            if state.get("state") == "owned":
                values[f"{base}:known"], values[f"{base}:owned"] = 1.0, 1.0
            elif state.get("state") == "confirmed_missing":
                values[f"{base}:known"], values[f"{base}:owned"] = 1.0, 0.0
            else:
                values[f"{base}:known"] = 0.0
    return values, groups


def eligible_records(records: list[dict[str, Any]], price_line: str) -> list[dict[str, Any]]:
    rows = []
    for row in records:
        price = _number(row.get("price_twd", row.get("selected_price_twd")))
        if row.get("price_type") == price_line and price is not None and price > 0:
            rows.append(row)
    return rows


def grouped_fold_indices(groups: list[str], folds: int):
    """Yield grouped outer-CV splits; one cluster never spans train/test."""
    from sklearn.model_selection import GroupKFold
    if len(set(groups)) < folds:
        raise ValueError("insufficient_unique_clusters_for_grouped_cv")
    # GroupKFold is deterministic for a fixed ordered records list; no duplicate
    # account/listing cluster may leak across an outer evaluation fold.
    return GroupKFold(n_splits=folds).split([[0]] * len(groups), groups=groups)


def artifact_base(input_paths: list[Path], output: Path, price_line: str, records: list[dict[str, Any]], features: list[str], groups: set[str]) -> dict[str, Any]:
    required = max(300, 20 * len(groups))
    # These are repository-relative (not artifact-relative), making a
    # snapshot stable across checkout directory names.
    try:
        relative_inputs, joined_hash = input_snapshot(input_paths[0], input_paths[1] if len(input_paths) > 1 else None)
    except ModelingInputError:
        # Fixtures outside a checkout still get deterministic provenance.  A
        # production artifact must use repository-relative paths and is later
        # rejected by the estimator if the snapshot cannot be verified.
        pairs = [(path.name, path) for path in input_paths]
        relative_inputs = [name for name, _ in sorted(pairs)]
        joined_hash = snapshot_hash(pairs).lower()
    return {
        "schema_version": "3.1-p1",
        "model_type": "xgboost",
        "status": "insufficient_training_data",
        "price_line": price_line,
        "input_snapshot_paths": relative_inputs,
        "input_snapshot_sha256": joined_hash.upper(),
        "feature_schema": {"version": "1", "feature_names": features, "feature_groups": sorted(groups)},
        "training": {"records": len(records), "total_eligible_records": len(records), "min_required_records": required,
                     "effective_feature_groups": len(groups), "min_effective_feature_groups": 1, "seed": 20260816,
                     "threshold_met": len(records) >= required, "baseline_beaten": False,
                     "outer_cv_mae": None, "outer_cv_folds": 0, "outer_cv_grouping": "cluster_id", "unique_clusters": 0, "group_count": 0, "baseline_median_mae": None},
        "publication_gate": {"status": "not_evaluated", "required_independent_training_clusters": 300, "required_time_forward_holdout_clusters": 100, "reason": "no_independent_time_forward_holdout"},
        "prediction_contract": {"target": "log_price_twd", "transform": "exp", "interval_supported": False,
                                "missing_feature_encoding": "NaN", "unknown_is_not_confirmed_missing": True},
        "model_file": None,
        "explanation_contract": {"method": "xgboost_pred_contribs_and_pred_interactions", "unit": "log_price_twd", "conditional_attribution_only": True},
    }


def train(input_path: Path, output: Path, price_line: str, seed: int = 20260816, prices_path: Path | None = None) -> dict[str, Any]:
    if prices_path:
        # Do not use the Elastic training row projection here: it intentionally
        # flattens away item_states.  XGBoost needs the original vector so its
        # approved three-state known/owned representation survives the price
        # join unchanged.
        price_map = load_price_map(prices_path, price_line)
        records = []
        for vector in read_jsonl(input_path):
            account_id = vector.get("account_id")
            joined_price = price_map.get(account_id)
            if not joined_price:
                continue
            record = dict(vector)
            record["price_twd"] = joined_price["price"]
            record["price_type"] = price_line
            record["cluster_id"] = joined_price["group"]
            records.append(record)
        input_paths = [input_path, prices_path]
    else:
        records = eligible_records(read_jsonl(input_path), price_line)
        input_paths = [input_path]
    eligible_item_ids = load_model_eligible_items(input_path)
    flattened = [flatten_vector(row, eligible_item_ids) for row in records]
    feature_names = sorted({name for values, _ in flattened for name in values})
    feature_groups = {group for _, mapping in flattened for group in mapping.values()}
    artifact = artifact_base(input_paths, output, price_line, records, feature_names, feature_groups)
    artifact["training"]["seed"] = seed
    cluster_ids = [str(row.get("cluster_id") or row.get("account_id") or f"row_{index}") for index, row in enumerate(records)]
    artifact["training"]["unique_clusters"] = len(set(cluster_ids))
    artifact["training"]["group_count"] = len(set(cluster_ids))
    if len(records) < artifact["training"]["min_required_records"] or not feature_names:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        return artifact
    try:
        import numpy as np
        from xgboost import XGBRegressor
    except ImportError:
        artifact["status"] = "dependency_unavailable"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        return artifact
    matrix = np.array([[values.get(name, float("nan")) for name in feature_names] for values, _ in flattened], dtype=float)
    target = np.array([math.log(float(row.get("price_twd", row.get("selected_price_twd")))) for row in records])
    folds = min(5, len(set(cluster_ids)))
    if folds < 2:
        artifact["status"] = "training_failed"
        artifact["training_failure_reason"] = "insufficient_unique_clusters_for_grouped_cv"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        return artifact
    cv_maes, baseline_maes = [], []
    for train_ix, test_ix in grouped_fold_indices(cluster_ids, folds):
        model = XGBRegressor(objective="reg:squarederror", n_estimators=120, max_depth=3, learning_rate=0.05,
                             subsample=0.85, colsample_bytree=0.85, random_state=seed, n_jobs=1, verbosity=0)
        model.fit(matrix[train_ix], target[train_ix])
        predicted = model.predict(matrix[test_ix])
        cv_maes.append(float(np.mean(np.abs(predicted - target[test_ix]))))
        baseline = float(np.median(target[train_ix]))
        baseline_maes.append(float(np.mean(np.abs(baseline - target[test_ix]))))
    artifact["training"]["outer_cv_mae"] = sum(cv_maes) / len(cv_maes)
    artifact["training"]["outer_cv_folds"] = folds
    artifact["training"]["baseline_median_mae"] = sum(baseline_maes) / len(baseline_maes)
    if artifact["training"]["outer_cv_mae"] >= artifact["training"]["baseline_median_mae"]:
        # A model that cannot beat the baseline is deliberately unavailable to
        # the estimator.  Keep the public status vocabulary small and place the
        # specific cause in training_failure_reason.
        artifact["status"] = "training_failed"
        artifact["training_failure_reason"] = "outer_cv_not_better_than_median_baseline"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        return artifact
    model = XGBRegressor(objective="reg:squarederror", n_estimators=120, max_depth=3, learning_rate=0.05,
                         subsample=0.85, colsample_bytree=0.85, random_state=seed, n_jobs=1, verbosity=0)
    model.fit(matrix, target)
    model_path = output.with_name(f"xgboost-{price_line}.model.json")
    model.save_model(model_path)
    artifact["status"] = "trained"
    artifact["training"]["baseline_beaten"] = True
    artifact["model_file"] = model_path.name
    artifact["model_sha256"] = hashlib.sha256(model_path.read_bytes()).hexdigest().upper()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline XGBoost training; fails closed for sparse data.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--price-line", choices=sorted(PRICE_LINES), required=True)
    parser.add_argument("--prices", type=Path, help="Cleaned-price JSONL joined by account_id; required for formal P1 training.")
    parser.add_argument("--seed", type=int, default=20260816)
    args = parser.parse_args()
    train(args.input, args.output, args.price_line, args.seed, args.prices)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
