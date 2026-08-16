"""Offline, fail-closed hedonic Elastic Net training for account item vectors.

This module deliberately contains no package installation, HTTP, or automated
automatic-update logic.  Artifacts are plain JSON so inference can be audited.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SEED = 1729
SCHEMA_VERSION = "3.1-p1"
METADATA_KEYS = {
    "account_id", "comparable_id", "history_id", "source_listing_ids", "price_twd",
    "selected_price_twd", "price_line", "price_type", "group_id", "cluster_id",
    "currency", "currency_verified", "server", "server_verified", "post_date",
    "observed_at", "status", "schema_version", "review_status", "features",
    "feature_vector",
}


class ModelingInputError(ValueError):
    pass


def dependency_error():
    try:
        import numpy as np  # noqa: F401
        import pandas as pd  # noqa: F401
        import sklearn  # noqa: F401
    except ImportError as exc:
        return "missing_optional_modeling_dependency: " + str(exc)
    return None


def repository_root(path: Path) -> Path:
    resolved = path.resolve()
    for candidate in (resolved.parent, *resolved.parents):
        if (candidate / "manifest.json").is_file():
            return candidate
    raise ModelingInputError("cannot_find_repository_root_for_input_snapshot")


def input_snapshot(vector_path: Path, prices_path: Path | None) -> tuple[list[str], str]:
    """Hash a path-independent ordered list of input file hashes."""
    root = repository_root(vector_path)
    entries = []
    for path in (vector_path, prices_path):
        if path and path.is_file():
            rel = path.resolve().relative_to(root).as_posix()
            entries.append((rel, hashlib.sha256(path.read_bytes()).hexdigest()))
    entries.sort(key=lambda entry: entry[0])
    digest = hashlib.sha256()
    for relative, file_hash in entries:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return [relative for relative, _ in entries], digest.hexdigest()


def _flatten(value, prefix=""):
    """Produce stable scalar modelling fields while preserving unknown explicitly."""
    if isinstance(value, dict):
        result = {}
        for key in sorted(value):
            name = f"{prefix}.{key}" if prefix else str(key)
            result.update(_flatten(value[key], name))
        return result
    if isinstance(value, list):
        if not value:
            return {f"{prefix}.__empty__": True}
        if all(isinstance(entry, dict) for entry in value):
            # Scope repeated records by a stable canonical identifier.  Stringifying
            # whole dicts would create one category per account and allow memorizing
            # composite records instead of learning their individual dimensions.
            identifiers = ("item_id", "season_id", "set_id", "platform", "map_id", "event_id")
            result = {}
            for entry in value:
                identity_key = next(
                    (key for key in identifiers if isinstance(entry.get(key), str) and entry.get(key)),
                    None,
                )
                if identity_key is None:
                    raise ModelingInputError(f"structured_list_missing_stable_identifier:{prefix}")
                identity = entry[identity_key]
                scoped = f"{prefix}.{identity}" if prefix else identity
                for key in sorted(entry):
                    if key != identity_key:
                        result.update(_flatten(entry[key], f"{scoped}.{key}"))
            return result
        if all(isinstance(entry, str) for entry in value):
            return {f"{prefix}.{entry}": True for entry in sorted(set(value))}
        raise ModelingInputError(f"unsupported_list_feature_shape:{prefix}")
    return {prefix: value}


_DROP_ITEM_IDENTITY = object()


def _without_item_identities(value):
    """Remove item IDs from untrusted aggregate feature groups.

    ``feature_groups`` contains collection/set evidence for auditability, but
    may also carry raw item IDs.  Those IDs cannot become training columns:
    item identity is admitted only by the approved ``item_states`` loop below.
    Set IDs and non-identity aggregate fields (completion ratio, counts and
    flags) are intentionally retained.
    """
    if isinstance(value, str):
        return _DROP_ITEM_IDENTITY if value.startswith("item_") else value
    if isinstance(value, list):
        kept = []
        for entry in value:
            sanitized = _without_item_identities(entry)
            if sanitized is not _DROP_ITEM_IDENTITY:
                kept.append(sanitized)
        return kept
    if isinstance(value, dict):
        kept = {}
        for key, entry in value.items():
            # Both the canonical ID field and item-ID collection fields are
            # identity-bearing even when currently empty.
            if key == "item_id" or key.endswith("_item_ids") or key in {
                "graduation_rewards", "collaboration_items", "event_limited_items",
            } or (str(key).startswith("item_") and key != "item_sets"):
                continue
            sanitized = _without_item_identities(entry)
            if sanitized is not _DROP_ITEM_IDENTITY:
                kept[key] = sanitized
        return kept
    return value


def feature_mapping(row: dict) -> dict:
    raw = row.get("feature_vector", row.get("features", row.get("feature_groups")))
    if raw is None:
        raw = {key: value for key, value in row.items() if key not in METADATA_KEYS}
    if not isinstance(raw, dict):
        raise ModelingInputError("feature_vector_or_features_must_be_an_object")
    # Never flatten raw collection/item-set identities.  This is deliberately
    # performed before flattening so paths such as
    # ``collection.collaboration_items.item_x`` cannot bypass item gating.
    result = _flatten(_without_item_identities(raw))
    # Only catalog-approved item states are formal model features.  A vector's
    # sensitivity-only / review candidates remain deliberately out of training.
    for state in row.get("item_states", []):
        if isinstance(state, dict) and state.get("model_feature") is True and state.get("review_status") == "approved":
            item_id = state.get("item_id")
            if isinstance(item_id, str):
                result[f"items.{item_id}"] = state.get("state", "unknown")
    return result


def normalize_price_line(value):
    aliases = {"asking": "normal_listing", "normal": "normal_listing", "reduced": "normal_listing", "urgent": "urgent_sale"}
    return aliases.get(value, value)


def load_price_map(path: Path, price_line: str):
    prices = {}
    if not path or not path.is_file():
        return prices
    for text in path.read_text(encoding="utf-8").splitlines():
        if not text.strip():
            continue
        row = json.loads(text)
        if normalize_price_line(row.get("price_line", row.get("normalized_price_type"))) != price_line:
            continue
        account_id = row.get("account_id")
        price = row.get("price_twd", row.get("selected_price_twd"))
        if isinstance(account_id, str) and isinstance(price, (int, float)) and not isinstance(price, bool) and price > 0:
            prices[account_id] = {"price": float(price), "group": row.get("cluster_id") or account_id}
    return prices


def load_rows(path: Path, price_line: str, prices_path: Path | None = None):
    rows, rejected = [], []
    price_map = load_price_map(prices_path, price_line)
    for line_number, text in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not text.strip():
            continue
        try:
            row = json.loads(text)
            line = normalize_price_line(row.get("price_line", row.get("price_type")))
            joined = price_map.get(row.get("account_id"), {})
            if line is None and joined:
                line = price_line
            price = row.get("price_twd", row.get("selected_price_twd", joined.get("price")))
            if line != price_line:
                continue
            if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
                rejected.append({"line": line_number, "reason": "invalid_or_missing_positive_twd_price"})
                continue
            features = feature_mapping(row)
            if not features:
                rejected.append({"line": line_number, "reason": "empty_feature_vector"})
                continue
            group = joined.get("group") or row.get("cluster_id") or row.get("group_id") or row.get("account_id") or row.get("comparable_id")
            if not isinstance(group, str) or not group:
                rejected.append({"line": line_number, "reason": "missing_group_identifier"})
                continue
            rows.append({"price": float(price), "group": group, "features": features})
        except (json.JSONDecodeError, ModelingInputError) as exc:
            rejected.append({"line": line_number, "reason": str(exc)})
    return rows, rejected


def classify_columns(rows):
    keys = sorted({key for row in rows for key in row["features"]})
    numeric, categorical = [], []
    for key in keys:
        values = [row["features"].get(key) for row in rows]
        present = [value for value in values if value is not None and value != "unknown"]
        if present and all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in present):
            numeric.append(key)
        else:
            categorical.append(key)
    return numeric, categorical


def feature_group_count(rows) -> int:
    # A namespace before the first dot is a semantic feature group.
    return len({key.split(".", 1)[0] for row in rows for key in row["features"]})


def minimum_rows(groups: int) -> int:
    return max(100, 10 * max(groups, 1))


def _frame(rows, numeric, categorical):
    import pandas as pd
    records = []
    for row in rows:
        record = {}
        for key in numeric:
            value = row["features"].get(key)
            record[key] = value if isinstance(value, (int, float)) and not isinstance(value, bool) else float("nan")
        for key in categorical:
            value = row["features"].get(key, "unknown")
            record[key] = "__unknown__" if value is None or value == "unknown" else str(value)
        records.append(record)
    return pd.DataFrame(records, columns=numeric + categorical)


def _pipeline(numeric, categorical, alpha_grid=None):
    from sklearn.compose import ColumnTransformer
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import ElasticNetCV
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    # Numeric missingness is separately encoded; unknown categorical state is an
    # explicit category and cannot collapse into an owned/missing claim.
    numeric_pipe = Pipeline([
        ("impute", SimpleImputer(strategy="median", add_indicator=True)),
        ("scale", StandardScaler()),
    ])
    categorical_pipe = OneHotEncoder(handle_unknown="ignore")
    prep = ColumnTransformer([
        ("numeric", numeric_pipe, numeric),
        ("categorical", categorical_pipe, categorical),
    ], remainder="drop")
    model = ElasticNetCV(
        l1_ratio=[0.1, 0.5, 0.9],
        alphas=alpha_grid or [0.01, 0.03, 0.1, 0.3, 1.0],
        cv=3,
        max_iter=20000,
        random_state=SEED,
        n_jobs=1,
    )
    return Pipeline([("preprocess", prep), ("model", model)])


def _fit_with_inner_groups(X, y, groups, numeric, categorical):
    from sklearn.model_selection import GroupKFold
    unique = len(set(groups))
    if unique < 3:
        raise ModelingInputError("fewer_than_three_independent_groups")
    pipe = _pipeline(numeric, categorical)
    # ElasticNetCV needs a grouped inner splitter to prevent clustered duplicates
    # crossing the train/validation boundary.
    splitter = GroupKFold(n_splits=min(3, unique))
    # ElasticNetCV does not accept a `groups` fit parameter.  Passing concrete
    # group-aware index splits is therefore the portable, explicit API.
    pipe.named_steps["model"].cv = list(splitter.split(X, y, groups))
    pipe.fit(X, y)
    return pipe


def nested_cv(X, y, groups, numeric, categorical):
    from sklearn.model_selection import GroupKFold
    unique = len(set(groups))
    if unique < 4:
        raise ModelingInputError("fewer_than_four_independent_groups_for_nested_cv")
    outer = GroupKFold(n_splits=min(5, unique))
    errors, baseline_errors = [], []
    for train, test in outer.split(X, y, groups):
        inner_groups = [groups[index] for index in train]
        pipe = _fit_with_inner_groups(X.iloc[train], y[train], inner_groups, numeric, categorical)
        predictions = pipe.predict(X.iloc[test])
        actual = y[test]
        errors.extend(abs(float(a) - float(b)) for a, b in zip(actual, predictions))
        median = float(statistics.median(y[train]))
        baseline_errors.extend(abs(float(a) - median) for a in actual)
    return errors, baseline_errors, outer.get_n_splits()


def _bootstrap_ci(values, iterations=400):
    import numpy as np
    if not values:
        return [None, None]
    rng = np.random.default_rng(SEED)
    values = np.asarray(values, dtype=float)
    means = [float(rng.choice(values, size=len(values), replace=True).mean()) for _ in range(iterations)]
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def _export_plain_json_model(pipe, numeric, categorical):
    prep = pipe.named_steps["preprocess"]
    model = pipe.named_steps["model"]
    names = list(prep.get_feature_names_out())
    coefficients = {name: float(value) for name, value in zip(names, model.coef_)}
    numeric_pipe = prep.named_transformers_["numeric"]
    imputer = numeric_pipe.named_steps["impute"]
    scaler = numeric_pipe.named_steps["scale"]
    # A ColumnTransformer skips the OneHotEncoder fitting path entirely when
    # there are no categorical columns, so never inspect its fitted attributes
    # in that valid pure-numeric modelling case.
    if categorical:
        categorical_encoder = prep.named_transformers_["categorical"]
        vocab = {column: [str(value) for value in values] for column, values in zip(categorical, categorical_encoder.categories_)}
    else:
        vocab = {}
    # SimpleImputer indicators occupy columns after numeric input columns.
    indicator_names = [numeric[index] for index in getattr(imputer.indicator_, "features_", [])]
    indicator_scaling = {
        raw_name: {
            "feature_name": names[len(numeric) + index],
            "mean": float(scaler.mean_[len(numeric) + index]),
            "scale": float(scaler.scale_[len(numeric) + index]),
        }
        for index, raw_name in enumerate(indicator_names)
    }
    return {
        "intercept": float(model.intercept_),
        "coefficients": coefficients,
        "continuous": {
            "columns": numeric,
            "imputation_medians": {key: float(value) for key, value in zip(numeric, imputer.statistics_)},
            # The scaler runs after median imputation. These first N entries are
            # exactly aligned with `columns`, allowing controlled JSON inference
            # to reproduce `(imputed_value - mean) / scale`.
            "means": {key: float(value) for key, value in zip(numeric, scaler.mean_[:len(numeric)])},
            "scales": {key: float(value) for key, value in zip(numeric, scaler.scale_[:len(numeric)])},
            "missing_mask_columns": indicator_names,
            "missing_indicator_scaling": indicator_scaling,
            # Redundant keyed maps are retained for the portable estimator
            # contract; they are exact projections of the audited entries above.
            "missing_indicator_means": {key: value["mean"] for key, value in indicator_scaling.items()},
            "missing_indicator_scales": {key: value["scale"] for key, value in indicator_scaling.items()},
        },
        "categorical_vocabulary": vocab,
        "feature_order": names,
        "alpha": float(model.alpha_),
        "l1_ratio": float(model.l1_ratio_),
    }


def additive_prediction_contract(model_export, numeric, categorical):
    """Portable inference contract for a strictly additive model on log price.

    Coefficient names exactly match `feature_order`. Continuous preprocessing is
    fully specified, and unknown categorical values are represented by the
    explicit `__unknown__` category when it existed during training (otherwise
    the one-hot contribution is zero, as declared by the vocabulary).
    """
    return {
        "kind": "additive_log_price",
        "target_transform": "log_twd_price",
        "unknown_handling": "missing_mask",
        "required_feature_columns": sorted(numeric + categorical),
        "intercept": model_export["intercept"],
        "coefficients": model_export["coefficients"],
        "continuous": model_export["continuous"],
        "categorical_vocabulary": model_export["categorical_vocabulary"],
        "feature_order": model_export["feature_order"],
    }


def portable_predict_log(prediction_contract: dict, features: dict) -> float:
    """Compute an additive JSON-contract prediction without sklearn.

    ``features`` is the already flattened feature mapping for one account. This
    function is intentionally small and deterministic so downstream consumers
    can reproduce the stored contract rather than deserialize a model object.
    """
    if prediction_contract.get("kind") != "additive_log_price":
        raise ModelingInputError("prediction_contract_is_not_additive_log_price")
    coefficients = prediction_contract["coefficients"]
    total = float(prediction_contract["intercept"])
    continuous = prediction_contract["continuous"]
    for column in continuous["columns"]:
        value = features.get(column)
        missing = not isinstance(value, (int, float)) or isinstance(value, bool)
        imputed = float(continuous["imputation_medians"][column]) if missing else float(value)
        scale = float(continuous["scales"][column])
        if scale == 0:
            raise ModelingInputError(f"zero_continuous_scale:{column}")
        transformed_name = f"numeric__{column}"
        total += float(coefficients.get(transformed_name, 0.0)) * ((imputed - float(continuous["means"][column])) / scale)
        if column in continuous["missing_indicator_scaling"]:
            indicator = continuous["missing_indicator_scaling"][column]
            indicator_scale = float(indicator["scale"])
            if indicator_scale == 0:
                raise ModelingInputError(f"zero_missing_indicator_scale:{column}")
            total += float(coefficients.get(indicator["feature_name"], 0.0)) * ((float(missing) - float(indicator["mean"])) / indicator_scale)
    for column, vocabulary in prediction_contract["categorical_vocabulary"].items():
        value = features.get(column, "__unknown__")
        category = "__unknown__" if value is None or value == "unknown" else str(value)
        if category in vocabulary:
            total += float(coefficients.get(f"categorical__{column}_{category}", 0.0))
    return total


def insufficient_artifact(price_line, source_paths, source_hash, groups, minimum, rows, rejected, reason):
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "insufficient_training_data",
        "price_line": price_line,
        "model_type": "elastic_net",
        "random_seed": SEED,
        "input_snapshot_paths": source_paths,
        "input_snapshot_sha256": source_hash,
        "training": {"eligible_rows": len(rows), "minimum_rows": minimum, "feature_group_count": groups, "group_count": len({r["group"] for r in rows}), "threshold_met": False, "baseline_beaten": False, "outer_cv_mae": None, "outer_cv_mae_ci95": [None, None], "baseline_mae": None, "folds": 0},
        "publication_gate": {"status": "not_evaluated", "required_independent_training_clusters": 300, "required_time_forward_holdout_clusters": 100, "reason": "no_independent_time_forward_holdout"},
        "feature_schema": {"feature_names": [], "feature_groups": [], "categorical_columns": [], "continuous_columns": [], "missing_mask_columns": [], "target": "log_twd_price"},
        "prediction_contract": {"kind": "unavailable", "required_feature_columns": [], "unknown_handling": "missing_mask", "target_transform": "log_twd_price"},
        "rejected_rows": rejected,
        "limitations": [reason],
        "artifact": None,
    }


def train(input_path: Path, price_line: str, prices_path: Path | None = None):
    source_paths, source_hash = input_snapshot(input_path, prices_path)
    dependency = dependency_error()
    if dependency:
        return {**insufficient_artifact(price_line, source_paths, source_hash, 0, 100, [], [], dependency), "status": "dependency_unavailable"}
    rows, rejected = load_rows(input_path, price_line, prices_path)
    groups = feature_group_count(rows)
    minimum = minimum_rows(groups)
    if len(rows) < minimum:
        return insufficient_artifact(price_line, source_paths, source_hash, groups, minimum, rows, rejected, "fewer_than_minimum_training_rows")
    numeric, categorical = classify_columns(rows)
    X = _frame(rows, numeric, categorical)
    import numpy as np
    y = np.log(np.asarray([row["price"] for row in rows], dtype=float))
    group_ids = [row["group"] for row in rows]
    try:
        errors, baseline_errors, folds = nested_cv(X, y, group_ids, numeric, categorical)
        mae, baseline = float(statistics.mean(errors)), float(statistics.mean(baseline_errors))
        if not math.isfinite(mae) or mae >= baseline:
            return insufficient_artifact(price_line, source_paths, source_hash, groups, minimum, rows, rejected, "model_does_not_beat_grouped_median_baseline")
        pipe = _fit_with_inner_groups(X, y, group_ids, numeric, categorical)
    except (ValueError, ModelingInputError) as exc:
        return insufficient_artifact(price_line, source_paths, source_hash, groups, minimum, rows, rejected, str(exc))
    feature_names = list(pipe.named_steps["preprocess"].get_feature_names_out())
    model_export = _export_plain_json_model(pipe, numeric, categorical)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "trained",
        "price_line": price_line,
        "model_type": "elastic_net",
        "random_seed": SEED,
        "input_snapshot_paths": source_paths,
        "input_snapshot_sha256": source_hash,
        "training": {"eligible_rows": len(rows), "minimum_rows": minimum, "feature_group_count": groups, "group_count": len(set(group_ids)), "threshold_met": True, "baseline_beaten": True, "outer_cv_mae": mae, "outer_cv_mae_ci95": _bootstrap_ci(errors), "baseline_mae": baseline, "folds": folds},
        "publication_gate": {"status": "not_evaluated", "required_independent_training_clusters": 300, "required_time_forward_holdout_clusters": 100, "reason": "trainer_performs_grouped_cv_but_not_independent_time_forward_publication_holdout"},
        "feature_schema": {"feature_names": feature_names, "feature_groups": sorted({name.split(".", 1)[0] for name in feature_names}), "categorical_columns": categorical, "continuous_columns": numeric, "missing_mask_columns": [f"numeric__missingindicator_{name}" for name in numeric], "target": "log_twd_price"},
        "prediction_contract": additive_prediction_contract(model_export, numeric, categorical),
        "rejected_rows": rejected,
        "limitations": [],
        "artifact": {"serialization": "plain_json", "model": model_export},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline grouped-nested-CV Elastic Net trainer")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--price-line", required=True, choices=("normal_listing", "urgent_sale"))
    parser.add_argument("--prices", type=Path, help="optional cleaned-price JSONL joined by account_id")
    args = parser.parse_args(argv)
    if not args.input.is_file():
        parser.error(f"input does not exist: {args.input}")
    price_path = args.prices
    if price_path is None:
        candidate = args.input.parent / f"price-cleaned-{'normal' if args.price_line == 'normal_listing' else 'urgent'}.jsonl"
        price_path = candidate if candidate.is_file() else None
    result = train(args.input, args.price_line, price_path)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"elastic-net-{args.price_line}.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": result["status"], "output": str(output)}, ensure_ascii=False))
    return 0 if result["status"] in {"trained", "insufficient_training_data", "dependency_unavailable"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
