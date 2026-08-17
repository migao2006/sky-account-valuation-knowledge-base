#!/usr/bin/env python3
"""Offline P1 model-estimator integration.

Artifacts are JSON envelopes, never pickles.  A model is usable only when its
training evidence, data snapshot hash, feature contract and prediction
contract can all be verified locally.  This module deliberately does not
invent a model, item value, or an imputation for unknown evidence.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Iterable

from estimate import estimate as comparable_estimate

SCHEMA_VERSION = "3.1-p1"
SUPPORTED_PRICE_LINES = {"normal_listing", "urgent_sale"}
SUPPORTED_MODEL_TYPES = {"elastic_net", "xgboost"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid_artifact_json:{path.name}:{exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"invalid_artifact_object:{path.name}")
    return value


def _artifact_paths(root: Path, price_line: str) -> list[Path]:
    # The first path is the canonical P1 location.  The data/ location is
    # accepted during migration only, so existing offline snapshots remain
    # usable without adding any external acquisition integration.
    directories = (root / "modeling" / "artifacts", root / "data" / "modeling" / "artifacts")
    paths: list[Path] = []
    for directory in directories:
        for model_type in ("elastic-net", "elastic_net", "xgboost"):
            path = directory / f"{model_type}-{price_line}.json"
            if path not in paths:
                paths.append(path)
    return paths


def _safe_snapshot(root: Path, artifact_path: Path, artifact: dict[str, Any]) -> tuple[bool, str]:
    """Verify the P1 multi-input snapshot contract without path traversal.

    The digest is `sorted(relative_path + NUL + file_sha256 + LF)`.  This
    binds both the bytes and the identity of each vector/price input and makes
    a trained artifact independent of the directory that held the artifact.
    """
    expected = artifact.get("input_snapshot_sha256")
    snapshots = artifact.get("input_snapshot_paths")
    if not isinstance(expected, str) or len(expected) != 64 or not isinstance(snapshots, list) or not snapshots or not all(isinstance(x, str) for x in snapshots):
        return False, "missing_snapshot_provenance"
    root_resolved = root.resolve()
    entries: list[tuple[str, Path]] = []
    for snapshot in snapshots:
        candidate = (root_resolved / snapshot).resolve()
        if root_resolved not in candidate.parents or not candidate.is_file():
            return False, "snapshot_path_invalid_or_missing"
        relative = candidate.relative_to(root_resolved).as_posix()
        entries.append((relative, candidate))
    if len({name for name, _ in entries}) != len(entries):
        return False, "duplicate_snapshot_path"
    digest = hashlib.sha256()
    for relative, candidate in sorted(entries):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(candidate).lower().encode("ascii"))
        digest.update(b"\n")
    return (digest.hexdigest().lower() == expected.lower(), "snapshot_hash_mismatch")


def _outer_mae(artifact: dict[str, Any]) -> float | None:
    training = artifact.get("training")
    value = training.get("outer_cv_mae") if isinstance(training, dict) else None
    if value is None:
        value = artifact.get("outer_cv_mae")
    if isinstance(value, dict):
        value = value.get("mean")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None


def _canonical_sha256(value: Any) -> str:
    """Hash a portable JSON model contract exactly as the evaluator does."""
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest().upper()


def _runtime_model_sha256(path: Path, artifact: dict[str, Any]) -> str | None:
    """Return the immutable bytes/model-contract digest used by publication.

    XGBoost has a separately persisted model payload.  Elastic Net inference is
    entirely the portable JSON prediction contract, so that contract is its
    model payload.  This is intentionally derived from local bytes/contracts,
    never from an artifact's self-reported publication metadata.
    """
    if artifact.get("model_type") == "xgboost":
        name = artifact.get("model_file")
        if not isinstance(name, str):
            return None
        model_path = (path.parent / name).resolve()
        if model_path.parent != path.parent.resolve() or not model_path.is_file():
            return None
        return _sha256(model_path).upper()
    contract = artifact.get("prediction_contract")
    return _canonical_sha256(contract) if isinstance(contract, dict) else None


def _publication_binding_reasons(root: Path, path: Path, artifact: dict[str, Any]) -> list[str]:
    """Require a freshly replayable, exact evaluator binding for a trained model.

    The evaluator owns metric computation.  Runtime only consumes its
    deterministic report and insists that the report is byte-for-byte the
    current replay, has passed, and contains exactly one binding for this
    artifact's observed bytes, model payload, dataset and split.
    """
    report_path = root / "reports" / "model-publication-evaluation.json"
    try:
        published = _read_json(report_path)
    except ValueError:
        return ["publication_evaluation_report_missing_or_invalid"]
    try:
        from tools.modeling.publication_evaluator import build as build_publication_evaluation
        replayed = build_publication_evaluation(root.resolve())
    except Exception as exc:
        return [f"publication_evaluation_replay_unavailable:{type(exc).__name__}"]
    if published != replayed:
        return ["publication_evaluation_report_not_replayable"]
    if published.get("status") != "passed" or published.get("publication_ready") is not True:
        return ["publication_evaluation_not_passed"]
    dataset_hashes = {
        "dataset_sha256": published.get("dataset_sha256"),
        "dataset_manifest_sha256": published.get("dataset_manifest_sha256"),
        "split_sha256": published.get("split_sha256"),
    }
    if not all(isinstance(value, str) and len(value) == 64 for value in dataset_hashes.values()):
        return ["publication_evaluation_hashes_invalid"]
    model_sha = _runtime_model_sha256(path, artifact)
    if model_sha is None:
        return ["publication_model_payload_missing_or_invalid"]
    binding = {
        "price_line": artifact.get("price_line"),
        "model_type": artifact.get("model_type"),
        **dataset_hashes,
        "model_sha256": model_sha,
        "artifact_sha256": _sha256(path).upper(),
    }
    rows = published.get("artifact_bindings")
    if not isinstance(rows, list):
        return ["publication_artifact_bindings_missing"]
    # P3.5 deliberately publishes one contract only.  Accepting a binding for
    # another model here would let it bypass its missing train-only evaluator.
    supported = {("elastic_net", "normal_listing")}
    observed = [(row.get("model_type"), row.get("price_line")) for row in rows if isinstance(row, dict)]
    if len(observed) != len(rows) or len(set(observed)) != len(observed) or set(observed) != supported:
        return ["publication_artifact_binding_set_not_exact"]
    matches = [row for row in rows if isinstance(row, dict) and all(row.get(key) == value for key, value in binding.items())]
    if len(matches) != 1:
        return ["publication_artifact_binding_missing_or_nonunique"]
    return []


def _training_quality_reasons(artifact: dict[str, Any]) -> list[str]:
    """Admission gate: a hand-written 'trained' envelope is not evidence."""
    training = artifact.get("training")
    if not isinstance(training, dict):
        return ["artifact_training_metadata_missing"]
    if (artifact.get("model_type"), artifact.get("price_line")) == ("elastic_net", "normal_listing") and training.get("publication_train_only") is True and training.get("publication_holdout_rows_excluded_from_fit") is True:
        # Holdout quality is owned by the replayed publication report, not by
        # artifact metadata.  Still require its immutable train-only minimum.
        return [] if isinstance(training.get("eligible_rows"), int) and training["eligible_rows"] >= 300 else ["publication_training_minimum_rows_not_met"]
    rows = training.get("eligible_rows", training.get("records"))
    minimum = training.get("minimum_rows", training.get("min_required_records"))
    groups = training.get("group_count", training.get("independent_group_count"))
    folds = training.get("folds", training.get("outer_cv_folds"))
    baseline = training.get("baseline_mae", training.get("baseline_median_mae"))
    mae = _outer_mae(artifact)
    reasons: list[str] = []
    if training.get("threshold_met") is not True: reasons.append("training_threshold_not_met")
    if training.get("baseline_beaten") is not True: reasons.append("training_baseline_not_beaten")
    if not isinstance(rows, int) or not isinstance(minimum, int) or rows < minimum: reasons.append("training_minimum_rows_not_met")
    if not isinstance(groups, int) or groups < 4: reasons.append("training_independent_groups_insufficient")
    if not isinstance(folds, int) or folds < 2: reasons.append("training_grouped_outer_folds_insufficient")
    if not isinstance(baseline, (int, float)) or isinstance(baseline, bool) or mae is None or mae >= float(baseline): reasons.append("training_cv_does_not_beat_baseline")
    return reasons


def _artifact_valid(root: Path, path: Path, expected_line: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        artifact = _read_json(path)
    except ValueError as exc:
        return None, [str(exc)]
    failures: list[str] = []
    if artifact.get("schema_version") != SCHEMA_VERSION:
        failures.append("artifact_schema_version_invalid")
    if artifact.get("status") != "trained":
        failures.append(f"artifact_not_trained:{artifact.get('status', 'unknown')}")
    if artifact.get("price_line") != expected_line:
        failures.append("artifact_price_line_mismatch")
    if artifact.get("model_type") not in SUPPORTED_MODEL_TYPES:
        failures.append("artifact_model_type_invalid")
    runtime_publication_artifact = (artifact.get("model_type"), artifact.get("price_line")) == ("elastic_net", "normal_listing") and artifact.get("training", {}).get("publication_train_only") is True
    if _outer_mae(artifact) is None and not runtime_publication_artifact:
        failures.append("artifact_outer_cv_mae_invalid")
    failures.extend(_training_quality_reasons(artifact))
    failures.extend(_publication_binding_reasons(root, path, artifact))
    if not isinstance(artifact.get("feature_schema"), dict):
        failures.append("artifact_feature_contract_missing")
    if not isinstance(artifact.get("prediction_contract"), dict):
        failures.append("artifact_prediction_contract_missing")
    snapshot_ok, snapshot_reason = _safe_snapshot(root, path, artifact)
    if not snapshot_ok:
        failures.append(snapshot_reason)
    return (artifact if not failures else None), failures


def load_artifacts(root: Path, price_line: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Read only locally verified artifacts for one price line."""
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for path in _artifact_paths(root, price_line):
        if not path.is_file():
            continue
        artifact, reasons = _artifact_valid(root, path, price_line)
        if artifact is None:
            rejected.append({"path": str(path), "reasons": reasons})
            continue
        artifact["_artifact_path"] = path
        accepted.append({"path": path, "artifact": artifact})
    # More than one envelope for a model type makes selection non-reproducible.
    deduplicated: dict[str, dict[str, Any]] = {}
    for entry in accepted:
        key = entry["artifact"]["model_type"]
        if key in deduplicated:
            rejected.append({"path": str(entry["path"]), "reasons": ["duplicate_model_type_artifact"]})
        else:
            deduplicated[key] = entry
    return list(deduplicated.values()), rejected


def _lookup_raw(account: dict[str, Any], name: str) -> Any:
    """Resolve raw scalar input while preserving string categories and unknown."""
    if name in account and account[name] not in (None, "unknown"):
        return account[name]
    current: Any = account
    found = True
    for segment in name.split("."):
        if not isinstance(current, dict) or segment not in current:
            found = False
            break
        current = current[segment]
    if found and current not in (None, "unknown") and isinstance(current, (str, int, float, bool)):
        return current
    # Vector producers may represent only known owned items as `item:<id> = 1`.
    # An absent item is unknown unless its vector explicitly says missing.
    vectors = account.get("item_vector")
    if isinstance(vectors, dict) and name in vectors and vectors[name] not in (None, "unknown"):
        return vectors[name]
    for vector_name in ("feature_vector", "features"):
        vector = account.get(vector_name)
        if isinstance(vector, dict) and vector.get(name) not in (None, "unknown"):
            return vector[name]
    if ":" in name:
        group, key = name.split(":", 1)
        groups = account.get("feature_groups")
        if isinstance(groups, dict) and isinstance(groups.get(group), dict):
            value = groups[group].get(key)
            if value not in (None, "unknown"):
                return value
    return None


def _lookup(account: dict[str, Any], name: str) -> float | None:
    """Numeric view of a raw lookup; strings never become a numeric value."""
    value = _lookup_raw(account, name)
    if isinstance(value, bool):
        return float(value)
    return float(value) if isinstance(value, (int, float)) else None


def _feature_contract(artifact: dict[str, Any]) -> tuple[list[str], dict[str, tuple[float | None, float | None]], dict[str, float]]:
    schema = artifact["feature_schema"]
    raw_features = schema.get("features", schema.get("feature_names", []))
    features: list[str] = []
    bounds: dict[str, tuple[float | None, float | None]] = {}
    if isinstance(raw_features, list):
        for entry in raw_features:
            if isinstance(entry, str):
                features.append(entry)
            elif isinstance(entry, dict) and isinstance(entry.get("name"), str):
                name = entry["name"]
                features.append(name)
                lo = entry.get("min") if isinstance(entry.get("min"), (int, float)) else None
                hi = entry.get("max") if isinstance(entry.get("max"), (int, float)) else None
                bounds[name] = (float(lo) if lo is not None else None, float(hi) if hi is not None else None)
    raw_bounds = schema.get("bounds", {})
    if isinstance(raw_bounds, dict):
        for name, boundary in raw_bounds.items():
            if isinstance(boundary, dict):
                lo, hi = boundary.get("min"), boundary.get("max")
                bounds[str(name)] = (float(lo) if isinstance(lo, (int, float)) else None, float(hi) if isinstance(hi, (int, float)) else None)
    runtime_numeric = schema.get("runtime_domain", {}).get("numeric", {}) if isinstance(schema.get("runtime_domain"), dict) else {}
    if isinstance(runtime_numeric, dict):
        for name, boundary in runtime_numeric.items():
            if isinstance(boundary, dict) and isinstance(boundary.get("min"), (int, float)) and isinstance(boundary.get("max"), (int, float)):
                bounds[str(name)] = (float(boundary["min"]), float(boundary["max"]))
    baselines = schema.get("baselines", {})
    return features, bounds, {str(k): float(v) for k, v in baselines.items() if isinstance(v, (int, float))}


def _predict(artifact: dict[str, Any], account: dict[str, Any]) -> tuple[float | None, list[dict[str, Any]], list[str]]:
    """Run the portable, explicitly declared additive prediction contract.

    Training code may use sklearn/XGBoost, but P1 runtime only accepts an
    exported, reviewable additive log-price contract.  Unsupported binary or
    pickle contracts fail closed rather than deserializing executable data.
    """
    if artifact.get("model_type") == "xgboost":
        return _predict_xgboost(artifact, account)
    contract = artifact["prediction_contract"]
    if contract.get("kind") != "additive_log_price":
        return None, [], ["unsupported_prediction_contract"]
    if artifact.get("model_type") == "elastic_net":
        runtime_contract = dict(contract)
        runtime_contract["runtime_domain"] = artifact.get("feature_schema", {}).get("runtime_domain", {})
        return _predict_elastic_net(runtime_contract, account, _feature_contract(artifact)[1])
    intercept = contract.get("intercept")
    coefficients = contract.get("coefficients")
    if not isinstance(intercept, (int, float)) or not isinstance(coefficients, dict):
        return None, [], ["invalid_additive_prediction_contract"]
    features, bounds, baselines = _feature_contract(artifact)
    if not features or not all(feature in coefficients and isinstance(coefficients[feature], (int, float)) for feature in features):
        return None, [], ["incomplete_feature_coefficients"]
    contributions: list[dict[str, Any]] = []
    prediction = float(intercept)
    missing: list[str] = []
    for feature in features:
        value = _lookup(account, feature)
        if value is None:
            missing.append(feature)
            continue
        lower, upper = bounds.get(feature, (None, None))
        if (lower is not None and value < lower) or (upper is not None and value > upper):
            return None, [], [f"out_of_distribution:{feature}"]
        coefficient = float(coefficients[feature])
        prediction += coefficient * value
        baseline = baselines.get(feature, 0.0)
        contributions.append({"feature": feature, "contribution_log_twd": round(coefficient * (value - baseline), 8), "method": "additive_contract_attribution"})
    if missing:
        return None, [], ["unknown_required_features:" + ",".join(sorted(missing))]
    contributions.sort(key=lambda x: abs(x["contribution_log_twd"]), reverse=True)
    return prediction, contributions[:10], []


def _predict_elastic_net(contract: dict[str, Any], account: dict[str, Any], bounds: dict[str, tuple[float | None, float | None]]) -> tuple[float | None, list[dict[str, Any]], list[str]]:
    """Exactly reproduce the trainer's JSON-exported sklearn preprocessing."""
    intercept, coefficients = contract.get("intercept"), contract.get("coefficients")
    continuous = contract.get("continuous")
    vocabulary = contract.get("categorical_vocabulary")
    feature_order = contract.get("feature_order")
    required = contract.get("required_feature_columns")
    if not isinstance(intercept, (int, float)) or not isinstance(coefficients, dict) or not isinstance(continuous, dict) or not isinstance(vocabulary, dict) or not isinstance(feature_order, list) or not isinstance(required, list):
        return None, [], ["elastic_prediction_contract_incomplete"]
    columns = continuous.get("columns")
    medians, scales, means = continuous.get("imputation_medians"), continuous.get("scales"), continuous.get("means")
    masks = continuous.get("missing_mask_columns")
    indicator_scaling = continuous.get("missing_indicator_scaling")
    if not all(isinstance(value, (list, dict)) for value in (columns, medians, scales, means, masks, indicator_scaling)):
        # `means` is mandatory: scaler centering cannot be reconstructed from
        # an imputation median and a scale.  Refuse an inexact prediction.
        return None, [], ["elastic_scaler_means_missing"]
    if any(not isinstance(name, str) or not isinstance(medians.get(name), (int, float)) or not isinstance(scales.get(name), (int, float)) or not isinstance(means.get(name), (int, float)) or float(scales[name]) == 0 for name in columns):
        return None, [], ["elastic_continuous_contract_invalid"]
    try:
        from modeling.train_elastic_net import feature_mapping
        # Runtime consumes the same flattened representation as training,
        # including structured list entries and nested feature groups.
        source = account.get("features") if isinstance(account.get("features"), dict) else account.get("feature_groups", account)
        flattened = feature_mapping({"features": source})
    except Exception as exc:
        return None, [], [f"elastic_feature_mapping_failed:{type(exc).__name__}"]
    transformed: dict[str, float] = {}
    for name in columns:
        raw = flattened.get(name)
        try:
            value = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
        except (OverflowError, ValueError):
            return None, [], [f"out_of_distribution:nonfinite:{name}"]
        is_missing = value is None
        domain = contract.get("runtime_domain", {}).get("numeric", {}).get(name) if isinstance(contract.get("runtime_domain"), dict) else None
        if is_missing and isinstance(domain, dict) and domain.get("missing_observed") is False:
            return None, [], [f"out_of_distribution:missing_unobserved:{name}"]
        lower, upper = bounds.get(name, (None, None))
        if value is not None and ((lower is not None and value < lower) or (upper is not None and value > upper)):
            return None, [], [f"out_of_distribution:{name}"]
        value = float(medians[name]) if is_missing else value
        transformed[f"numeric__{name}"] = (value - float(means[name])) / float(scales[name])
        if name in masks:
            indicator_contract = indicator_scaling.get(name)
            if not isinstance(indicator_contract, dict) or indicator_contract.get("feature_name") != f"numeric__missingindicator_{name}" or not isinstance(indicator_contract.get("mean"), (int, float)) or not isinstance(indicator_contract.get("scale"), (int, float)) or float(indicator_contract["scale"]) == 0:
                return None, [], ["elastic_missing_indicator_scaler_contract_invalid"]
            indicator = 1.0 if is_missing else 0.0
            transformed[f"numeric__missingindicator_{name}"] = (indicator - float(indicator_contract["mean"])) / float(indicator_contract["scale"])
    for name, values in vocabulary.items():
        if not isinstance(name, str) or not isinstance(values, list) or not all(isinstance(x, str) for x in values):
            return None, [], ["elastic_categorical_contract_invalid"]
        value = flattened.get(name)
        token = "__unknown__" if value in (None, "unknown") else str(value)
        domain = contract.get("runtime_domain", {}).get("categorical", {}).get(name) if isinstance(contract.get("runtime_domain"), dict) else None
        if isinstance(domain, list) and token not in domain:
            return None, [], [f"out_of_distribution:{name}"]
        # OneHotEncoder(handle_unknown='ignore') emits all zeroes for a token
        # absent from its fitted vocabulary, including unknown when no explicit
        # unknown category was observed during training.
        for category in values:
            transformed[f"categorical__{name}_{category}"] = 1.0 if token == category else 0.0
    if not all(isinstance(name, str) and name in coefficients and isinstance(coefficients[name], (int, float)) for name in feature_order):
        return None, [], ["elastic_feature_order_or_coefficients_invalid"]
    unknown_raw = [name for name in required if name not in columns and name not in vocabulary]
    if unknown_raw:
        return None, [], ["elastic_required_feature_not_declared:" + ",".join(sorted(unknown_raw))]
    prediction = float(intercept)
    drivers: list[dict[str, Any]] = []
    for name in feature_order:
        if name not in transformed:
            return None, [], [f"elastic_missing_transformed_feature:{name}"]
        contribution = float(coefficients[name]) * transformed[name]
        prediction += contribution
        drivers.append({"feature": name, "contribution_log_twd": round(contribution, 8), "method": "elastic_net_exact_preprocessing"})
    if not math.isfinite(prediction) or prediction < -700 or prediction > 700:
        return None, [], ["out_of_distribution:nonfinite_or_overflow_prediction"]
    drivers.sort(key=lambda row: abs(row["contribution_log_twd"]), reverse=True)
    return prediction, drivers[:10], []


def _predict_xgboost(artifact: dict[str, Any], account: dict[str, Any]) -> tuple[float | None, list[dict[str, Any]], list[str]]:
    """Load only a hash-verified XGBoost JSON/UBJ model when available."""
    model_file, expected = artifact.get("model_file"), artifact.get("model_sha256")
    artifact_path = artifact.get("_artifact_path")
    if not isinstance(model_file, str) or not isinstance(expected, str) or not isinstance(artifact_path, Path):
        return None, [], ["xgboost_model_provenance_missing"]
    model_path = (artifact_path.parent / model_file).resolve()
    if model_path.parent != artifact_path.parent.resolve() or not model_path.is_file() or _sha256(model_path).lower() != expected.lower():
        return None, [], ["xgboost_model_hash_mismatch"]
    features, bounds, _ = _feature_contract(artifact)
    if not features:
        return None, [], ["xgboost_feature_contract_missing"]
    repository_root = artifact_path.parents[2] if len(artifact_path.parents) >= 3 else None
    # Fixture artifact directories need not copy the immutable trainer module;
    # use this checked-in implementation only when the artifact root lacks it.
    if repository_root is None or not (repository_root / "modeling" / "train_xgboost.py").is_file():
        repository_root = Path(__file__).resolve().parents[2]
    if repository_root is None or not (repository_root / "modeling" / "train_xgboost.py").is_file():
        return None, [], ["xgboost_flatten_vector_unavailable"]
    if str(repository_root) not in sys.path:
        sys.path.insert(0, str(repository_root))
    try:
        from modeling.train_xgboost import flatten_vector, load_model_eligible_items
        flattened, _groups = flatten_vector(account, load_model_eligible_items(repository_root / "data/modeling/account-item-vectors.jsonl"))
    except Exception as exc:
        return None, [], [f"xgboost_flatten_vector_failed:{type(exc).__name__}"]
    values: list[float] = []
    for feature in features:
        value = flattened.get(feature)
        if value is None:
            # XGBoost is trained on a sparse vector and receives NaN for an
            # absent sparse feature.  This is distinct from an explicit zero
            # and matches the trainer's matrix construction exactly.
            values.append(float("nan"))
            continue
        lower, upper = bounds.get(feature, (None, None))
        if (lower is not None and value < lower) or (upper is not None and value > upper):
            return None, [], [f"out_of_distribution:{feature}"]
        values.append(value)
    try:
        import xgboost as xgb
    except ImportError:
        return None, [], ["xgboost_runtime_unavailable"]
    try:
        matrix = xgb.DMatrix([values], feature_names=features)
        booster = xgb.Booster()
        booster.load_model(str(model_path))
        prediction = float(booster.predict(matrix)[0])
        contribs = booster.predict(matrix, pred_contribs=True)[0]
    except Exception as exc:  # Model format/API mismatch must never fall back to a guess.
        return None, [], [f"xgboost_prediction_failed:{type(exc).__name__}"]
    drivers = [{"feature": feature, "contribution_log_twd": round(float(value), 8), "method": "tree_shap"} for feature, value in zip(features, contribs[:-1])]
    drivers.sort(key=lambda row: abs(row["contribution_log_twd"]), reverse=True)
    return prediction, drivers[:10], []


def _gates(account: dict[str, Any], price_line: str) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    trade = account.get("trade_conditions", {}) if isinstance(account.get("trade_conditions"), dict) else account
    market_reasons: list[str] = []
    if account.get("currency") != "TWD": market_reasons.append("currency_must_be_twd")
    if account.get("server") != "international": market_reasons.append("server_must_be_international")
    if trade.get("offer_kind", account.get("offer_kind")) != "seller_listing": market_reasons.append("target_not_seller_listing")
    if trade.get("entity_kind", account.get("entity_kind")) != "single_account": market_reasons.append("target_not_single_account")
    if trade.get("price_type", account.get("price_type")) != price_line: market_reasons.append("price_line_mismatch")
    evidence = account.get("evidence_quality", {})
    level = evidence.get("listing_text") if isinstance(evidence, dict) else evidence
    evidence_reasons: list[str] = []
    if level not in {"high", "medium"}: evidence_reasons.append("listing_evidence_insufficient")
    if account.get("review_status") not in {"approved", None}: evidence_reasons.append("profile_requires_review")
    return ({"passed": not market_reasons, "reasons": market_reasons}, {"passed": not evidence_reasons, "reasons": evidence_reasons}, market_reasons + evidence_reasons)


def _fallback(account: dict[str, Any], comparables: Iterable[dict[str, Any]] | None) -> dict[str, Any] | None:
    if comparables is None:
        return None
    return comparable_estimate(account, comparables)


def _catalog_gated_account(account: dict[str, Any], root: Path) -> tuple[dict[str, Any], list[str]]:
    """Reject caller-asserted item features that are not catalog/evidence eligible."""
    result = copy.deepcopy(account)
    states = result.get("item_states")
    if states is None:
        return result, []
    if not isinstance(states, list):
        return result, ["item_states_must_be_an_array"]
    try:
        catalog = {
            row["item_id"]: row
            for row in _read_jsonl(root / "knowledge/items/items.jsonl")
        }
    except (OSError, KeyError, json.JSONDecodeError):
        return result, ["canonical_item_catalog_unavailable"]
    reasons: list[str] = []
    seen: set[str] = set()
    for state in states:
        if not isinstance(state, dict) or not isinstance(state.get("item_id"), str):
            reasons.append("invalid_item_state")
            continue
        item_id = state["item_id"]
        if item_id in seen:
            reasons.append(f"duplicate_item_state:{item_id}")
        seen.add(item_id)
        item = catalog.get(item_id)
        if item is None:
            reasons.append(f"unknown_canonical_item:{item_id}")
            continue
        catalog_eligible = item.get("verification_status") == "verified" and item.get("model_feature_status") == "eligible"
        evidence_eligible = state.get("review_status") == "approved" and state.get("evidence_state") in {"profile_claim", "text_claim"} and state.get("conflict") is False
        if state.get("model_feature") is True and not catalog_eligible:
            reasons.append(f"catalog_item_not_model_eligible:{item_id}")
        if state.get("model_feature") is True and not evidence_eligible:
            reasons.append(f"item_evidence_not_approved:{item_id}")
        # Never upgrade a caller's false/unknown flag. A true flag survives only
        # when both independent gates above are satisfied.
        state["model_feature"] = state.get("model_feature") is True and catalog_eligible and evidence_eligible
    return result, reasons


def estimate_model(account: dict[str, Any], *, root: Path, comparables: Iterable[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Estimate from verified artifacts, otherwise return a conservative fallback."""
    trade = account.get("trade_conditions", {}) if isinstance(account.get("trade_conditions"), dict) else account
    price_line = trade.get("price_type", account.get("price_type", "unknown"))
    if price_line not in SUPPORTED_PRICE_LINES:
        fallback = _fallback(account, comparables)
        return _result("ineligible_input", str(price_line), [], {"passed": False, "reasons": ["unsupported_price_line"]}, {"passed": False, "reasons": ["not_evaluated"]}, {"passed": False, "reasons": ["not_evaluated"]}, ["unsupported_price_line"], fallback=fallback)
    model_account, item_gate_reasons = _catalog_gated_account(account, root)
    market_gate, evidence_gate, gate_reasons = _gates(account, price_line)
    if item_gate_reasons:
        evidence_gate = {"passed": False, "reasons": evidence_gate["reasons"] + item_gate_reasons}
        gate_reasons += item_gate_reasons
    if gate_reasons:
        fallback = _fallback(account, comparables)
        return _result("ineligible_input", price_line, [], market_gate, evidence_gate, {"passed": False, "reasons": ["not_evaluated"]}, gate_reasons, fallback=fallback)
    artifacts, artifact_rejections = load_artifacts(root, price_line)
    predictions: list[tuple[dict[str, Any], float, list[dict[str, Any]]]] = []
    ood_reasons: list[str] = []
    selection: list[dict[str, Any]] = []
    for entry in artifacts:
        prediction, drivers, reasons = _predict(entry["artifact"], model_account)
        model_type = entry["artifact"]["model_type"]
        if prediction is None:
            selection.append({"model_type": model_type, "used": False, "reasons": reasons})
            ood_reasons.extend(reasons)
            continue
        mae = _outer_mae(entry["artifact"])
        if mae is None and entry["artifact"].get("training", {}).get("publication_train_only") is True:
            # The evaluator's holdout MAE is the quality metric.  It has
            # already been checked by the exact binding gate above.
            mae = 1.0
        if mae is None:  # also protects inverse weighting from singular values.
            selection.append({"model_type": model_type, "used": False, "reasons": ["nonpositive_outer_cv_mae"]})
            continue
        selection.append({"model_type": model_type, "used": True, "outer_cv_mae": mae, "artifact": str(entry["path"])})
        predictions.append((entry, prediction, drivers))
    if not predictions:
        fallback = _fallback(account, comparables)
        status = "out_of_distribution" if any(reason.startswith("out_of_distribution:") for reason in ood_reasons) else "insufficient_training_data"
        reasons = ["no_verified_usable_model_artifact"] + ood_reasons + [reason for row in artifact_rejections for reason in row["reasons"]]
        return _result(status, price_line, selection, market_gate, evidence_gate, {"passed": False, "reasons": ood_reasons or ["no_usable_model"]}, reasons, artifact_rejections, fallback)
    def selection_mae(entry: dict[str, Any]) -> float:
        value = _outer_mae(entry["artifact"])
        return value if value is not None else 1.0
    weights = [1.0 / selection_mae(entry) for entry, _, _ in predictions]
    weighted_log = sum(weight * value for weight, (_, value, _) in zip(weights, predictions)) / sum(weights)
    combined_mae = sum(weight * selection_mae(entry) for weight, (entry, _, _) in zip(weights, predictions)) / sum(weights)
    point = max(1.0, math.exp(weighted_log))
    runtime_intervals = [entry["artifact"].get("artifact", {}).get("runtime_interval_contract") for entry, _, _ in predictions]
    if len(runtime_intervals) == 1 and isinstance(runtime_intervals[0], dict) and runtime_intervals[0].get("kind") == "train_residual_p10_p90_twd" and all(isinstance(runtime_intervals[0].get(key), (int, float)) for key in ("residual_lower_twd", "residual_upper_twd")):
        low = max(1.0, point + float(runtime_intervals[0]["residual_lower_twd"]))
        high = max(point, point + float(runtime_intervals[0]["residual_upper_twd"]))
        interval = {"low": round(min(low, point), 2), "point": round(point, 2), "high": round(max(high, point), 2)}
    else:
        interval = {"low": round(math.exp(weighted_log - combined_mae), 2), "point": round(point, 2), "high": round(math.exp(weighted_log + combined_mae), 2)}
    drivers = [driver for _, _, contribution in predictions for driver in contribution]
    drivers.sort(key=lambda row: abs(row["contribution_log_twd"]), reverse=True)
    fallback = _fallback(account, comparables)
    comparable_rows = fallback.get("comparables", []) if isinstance(fallback, dict) else []
    confirmed = sorted({item for row in comparable_rows for item in row.get("major_differences", [])})
    unknown = sorted({item for row in comparable_rows for item in row.get("unconfirmed_dimensions", [])})
    return {"schema_version": SCHEMA_VERSION, "offline_only": True, "status": "estimated", "price_line": price_line, "eligible": True, "range_twd": interval, "model_selection": selection, "market_gate": market_gate, "evidence_gate": evidence_gate, "ood_gate": {"passed": True, "reasons": []}, "comparables": comparable_rows, "confirmed_differences": confirmed, "unknown_dimensions": unknown, "shap_drivers": drivers[:10], "insufficiency_reasons": [], "artifact_rejections": artifact_rejections, "comparable_fallback": fallback}


def _result(status: str, price_line: str, selection: list[dict[str, Any]], market_gate: dict[str, Any], evidence_gate: dict[str, Any], ood_gate: dict[str, Any], reasons: list[str], artifact_rejections: list[dict[str, Any]] | None = None, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
    comparable_rows = fallback.get("comparables", []) if isinstance(fallback, dict) else []
    return {"schema_version": SCHEMA_VERSION, "offline_only": True, "status": status, "price_line": price_line if price_line in SUPPORTED_PRICE_LINES else "normal_listing", "eligible": False, "range_twd": None, "model_selection": selection, "market_gate": market_gate, "evidence_gate": evidence_gate, "ood_gate": ood_gate, "comparables": comparable_rows, "confirmed_differences": sorted({item for row in comparable_rows for item in row.get("major_differences", [])}), "unknown_dimensions": sorted({item for row in comparable_rows for item in row.get("unconfirmed_dimensions", [])}), "shap_drivers": [], "insufficiency_reasons": list(dict.fromkeys(reasons)), "artifact_rejections": artifact_rejections or [], "comparable_fallback": fallback}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline model-backed Sky account estimator")
    parser.add_argument("account", type=Path)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--comparables", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    comparables = _read_jsonl(args.comparables) if args.comparables else None
    result = estimate_model(json.loads(args.account.read_text(encoding="utf-8")), root=args.root, comparables=comparables)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
