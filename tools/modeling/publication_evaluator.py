#!/usr/bin/env python3
"""Replay a frozen publication split without trusting a model artifact.

The evaluator owns the split: callers may *submit* a split for comparison,
but it is never used to select training or holdout rows.  Likewise it never
accepts a vector of claimed predictions.  The implemented scorer is a fixed,
train-only verified-date linear regression with evaluator-owned model bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

try:
    from .publication_dataset import PublicationDatasetError, build as build_publication_dataset, split as derive_split
except ImportError:
    from publication_dataset import PublicationDatasetError, build as build_publication_dataset, split as derive_split

ROOT = Path(__file__).resolve().parents[2]
TRAINING_CLUSTERS_REQUIRED = 300
HOLDOUT_CLUSTERS_REQUIRED = 100
MINIMUM_SUBGROUP_HOLDOUT_CASES = 30


class PublicationEvaluationError(ValueError):
    """An alleged frozen input cannot be independently replayed."""


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest().upper()


def _pool_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return row["currency"], row["server"], row["price_line"]


def _ape(actual: float, prediction: float) -> float:
    return abs(actual - prediction) / actual


def _percentile(values: list[float], fraction: float) -> float:
    """Dependency-free linear percentile with a deterministic singleton rule."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _submitted_split_reasons(manifest: dict[str, Any], submitted: dict[str, Any], replayed: dict[str, Any]) -> list[str]:
    """Explain bad submitted splits while still refusing to consume them."""
    reasons: list[str] = []
    rows_by_pool: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in manifest["dataset_rows"]:
        rows_by_pool[_pool_key(row)].append(row)
    for pool in submitted.get("market_pools", []) if isinstance(submitted, dict) else []:
        try:
            key = pool["currency"], pool["server"], pool["price_line"]
            cut = date.fromisoformat(pool["cut_date"])
            train = set(pool["training_cluster_ids"])
            holdout = set(pool["holdout_cluster_ids"])
        except (KeyError, TypeError, ValueError):
            reasons.append("submitted_split_malformed")
            continue
        if train & holdout:
            reasons.append("submitted_split_cluster_overlap")
        intervals: dict[str, list[date]] = defaultdict(list)
        for row in rows_by_pool.get(key, []):
            intervals[row["cluster_id"]].append(date.fromisoformat(row["post_date"]))
        if any(max(intervals[cluster]) >= cut for cluster in train if cluster in intervals) or any(min(intervals[cluster]) < cut for cluster in holdout if cluster in intervals):
            reasons.append("submitted_split_date_inversion")
    if _sha256(submitted) != _sha256(replayed):
        reasons.append("submitted_split_does_not_match_recomputed_split")
    return sorted(set(reasons))


def _fit_date_trend(train: list[dict[str, Any]]) -> dict[str, float] | None:
    """Fit a deterministic, train-only least-squares trend on verified dates."""
    origin = min(date.fromisoformat(row["post_date"]).toordinal() for row in train)
    points = [(date.fromisoformat(row["post_date"]).toordinal() - origin, float(row["selected_price_twd"])) for row in train]
    mean_x = statistics.mean(point[0] for point in points)
    mean_y = statistics.mean(point[1] for point in points)
    denominator = sum((x - mean_x) ** 2 for x, _y in points)
    if denominator == 0:
        return None
    slope = sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator
    return {"origin_ordinal": float(origin), "intercept": mean_y - slope * mean_x, "slope_per_day": slope}


def _predict_date_trend(model: dict[str, float], row: dict[str, Any]) -> float:
    x = date.fromisoformat(row["post_date"]).toordinal() - model["origin_ordinal"]
    return max(1.0, model["intercept"] + model["slope_per_day"] * x)


def _replay_metrics(rows: list[dict[str, Any]], pool: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Fit a fixed train-only date model and score the untouched holdout.

    This minimal evaluator-owned model exists to prove the full data-to-metric
    path.  It is intentionally narrow: it uses only the verified post date,
    has no external model/prediction input, and can therefore be replayed from
    the frozen manifest bytes alone.
    """
    train_ids = set(pool["training_cluster_ids"])
    holdout_ids = set(pool["holdout_cluster_ids"])
    train = [row for row in rows if row["cluster_id"] in train_ids]
    holdout = [row for row in rows if row["cluster_id"] in holdout_ids]
    if not train or not holdout:
        raise PublicationEvaluationError("recomputed_split_has_no_train_or_holdout_rows")
    train_prices = [float(row["selected_price_twd"]) for row in train]
    median_point = statistics.median(train_prices)
    model = _fit_date_trend(train)
    if model is None:
        return ({"scorer": "date_trend_unavailable", "training_row_count": len(train), "holdout_row_count": len(holdout)}, None)
    train_residuals = [float(row["selected_price_twd"]) - _predict_date_trend(model, row) for row in train]
    residual_low, residual_high = _percentile(train_residuals, 0.10), _percentile(train_residuals, 0.90)
    predictions = [_predict_date_trend(model, row) for row in holdout]
    apes = [_ape(float(row["selected_price_twd"]), prediction) for row, prediction in zip(holdout, predictions)]
    errors = [abs(float(row["selected_price_twd"]) - prediction) for row, prediction in zip(holdout, predictions)]
    baseline_errors = [abs(float(row["selected_price_twd"]) - median_point) for row in holdout]
    # A deterministic comparable selector: closest earlier listing date only.
    selector_errors = []
    for row in holdout:
        row_date = date.fromisoformat(row["post_date"])
        closest = min(train, key=lambda item: (abs((row_date - date.fromisoformat(item["post_date"])).days), item["cleaned_price_id"]))
        selector_errors.append(abs(float(row["selected_price_twd"]) - float(closest["selected_price_twd"])))
    subgroup_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    training_subgroup_counts: dict[str, int] = defaultdict(int)
    for row in train:
        subgroup = row.get("evaluation_subgroup", "unknown")
        training_subgroup_counts[subgroup if isinstance(subgroup, str) and subgroup else "unknown"] += 1
    for row in holdout:
        subgroup = row.get("evaluation_subgroup", "all")
        subgroup_rows[subgroup if isinstance(subgroup, str) and subgroup else "unknown"].append(row)
    subgroups = []
    underpowered = []
    for name in sorted(subgroup_rows):
        group = subgroup_rows[name]
        group_apes = [_ape(float(row["selected_price_twd"]), _predict_date_trend(model, row)) for row in group]
        subgroups.append({"name": name, "holdout_case_count": len(group), "mdape": statistics.median(group_apes)})
        if len(group) < MINIMUM_SUBGROUP_HOLDOUT_CASES:
            underpowered.append(name)
    coverage = sum(prediction + residual_low <= float(row["selected_price_twd"]) <= prediction + residual_high for row, prediction in zip(holdout, predictions)) / len(holdout)
    median_width_ratio = statistics.median((residual_high - residual_low) / prediction for prediction in predictions)
    baseline_mae, selector_mae, candidate_mae = statistics.mean(baseline_errors), statistics.mean(selector_errors), statistics.mean(errors)
    baseline_improvement = None if baseline_mae == 0 else 1 - candidate_mae / baseline_mae
    selector_improvement = None if selector_mae == 0 else 1 - candidate_mae / selector_mae
    metric = {
        "scorer": "train_only_verified_date_linear_regression", "training_row_count": len(train), "holdout_row_count": len(holdout),
        "model": model, "holdout_mdape": statistics.median(apes), "holdout_p90_ape": _percentile(apes, 0.90),
        "holdout_mae_twd": candidate_mae, "median_baseline_mae_twd": baseline_mae,
        "median_baseline_mae_improvement": baseline_improvement, "comparable_selector_mae_twd": selector_mae,
        "comparable_selector_mae_improvement": selector_improvement,
        "interval": {"kind": "train_residual_p10_p90", "residual_lower_twd": residual_low, "residual_upper_twd": residual_high,
                     "coverage": coverage, "median_width_ratio": median_width_ratio},
        "subgroups": subgroups, "underpowered_subgroups": underpowered,
        "coverage_qualified_share": sum(
            training_subgroup_counts.get(
                row.get("evaluation_subgroup") if isinstance(row.get("evaluation_subgroup"), str) else "unknown", 0
            ) >= MINIMUM_SUBGROUP_HOLDOUT_CASES
            for row in holdout
        ) / len(holdout),
    }
    return metric, model


def _gate_reasons(metric: dict[str, Any]) -> list[str]:
    if metric["scorer"] == "date_trend_unavailable":
        return ["date_trend_requires_training_date_variation"]
    reasons = []
    if metric["holdout_mdape"] > 0.20:
        reasons.append("holdout_mdape_above_20_percent")
    if metric["holdout_p90_ape"] > 0.40:
        reasons.append("holdout_p90_ape_above_40_percent")
    if metric["median_baseline_mae_improvement"] is None or metric["median_baseline_mae_improvement"] < 0.15:
        reasons.append("median_baseline_mae_improvement_below_15_percent")
    if metric["comparable_selector_mae_improvement"] is None or metric["comparable_selector_mae_improvement"] < 0.10:
        reasons.append("comparable_selector_mae_improvement_below_10_percent")
    interval = metric["interval"]
    if not 0.75 <= interval["coverage"] <= 0.85:
        reasons.append("prediction_interval_coverage_outside_75_85_percent")
    if interval["median_width_ratio"] > 0.50:
        reasons.append("prediction_interval_width_above_50_percent")
    reasons.extend(f"subgroup_under_30:{name}" for name in metric["underpowered_subgroups"])
    reasons.extend(
        f"subgroup_mdape_above_25_percent:{row['name']}"
        for row in metric["subgroups"] if row["mdape"] > 0.25
    )
    if metric["coverage_qualified_share"] < 0.80:
        reasons.append("coverage_qualified_share_below_80_percent")
    return reasons


def evaluator_artifact_binding(price_line: str, model: dict[str, Any], dataset_sha256: str, dataset_manifest_sha256: str, split_sha256: str) -> dict[str, str]:
    """Hash evaluator-owned model/artifact bytes for a passed replay only.

    There is no external model file for this deliberately stdlib evaluator.
    Its stable canonical JSON bytes are its model and artifact bytes.  Other
    model types must use their own raw-file contract and must not reuse this
    helper to bless a self-supplied artifact.
    """
    model_sha256 = _sha256(model)
    artifact = {"schema_version": "1.1-p3.3", "model_type": "publication_date_linear_regression",
                "price_line": price_line, "model": model, "dataset_sha256": dataset_sha256,
                "dataset_manifest_sha256": dataset_manifest_sha256, "split_sha256": split_sha256}
    return {"price_line": price_line, "model_type": artifact["model_type"], "dataset_sha256": dataset_sha256,
            "dataset_manifest_sha256": dataset_manifest_sha256, "split_sha256": split_sha256,
            "model_sha256": model_sha256, "artifact_sha256": _sha256(artifact)}


def evaluate(manifest: dict[str, Any], submitted_split: dict[str, Any] | None = None, *, artifact: Any = None, predictions: Any = None) -> dict[str, Any]:
    """Recompute a report from a frozen manifest and reject external claims.

    ``artifact`` and ``predictions`` exist solely to make the trust boundary
    explicit to integrations and tests: any non-``None`` value is rejected.
    A future model evaluator must instead implement a versioned train-only
    fitting contract inside this module (or an explicitly imported helper).
    """
    try:
        replayed = derive_split(manifest)
    except (PublicationDatasetError, KeyError, TypeError, ValueError) as error:
        raise PublicationEvaluationError(str(error)) from error
    submitted_reasons = _submitted_split_reasons(manifest, submitted_split, replayed) if submitted_split is not None else []
    input_reasons = list(submitted_reasons)
    if artifact is not None:
        input_reasons.append("external_model_artifact_rejected")
    if predictions is not None:
        input_reasons.append("external_predictions_rejected")
    eligible = [pool for pool in replayed["market_pools"] if pool["requirements_met"] is True and pool["cluster_overlap"] is False]
    common = {
        "schema_version": "1.1-p3.3", "publication_ready": False,
        "artifact_publication_fields_consulted": False,
        "dataset_sha256": manifest["dataset_sha256"], "dataset_manifest_sha256": _sha256(manifest),
        "split_sha256": _sha256(replayed),
        "artifact_bindings": [],
        "requirements": {"training_clusters": TRAINING_CLUSTERS_REQUIRED, "holdout_clusters": HOLDOUT_CLUSTERS_REQUIRED,
                         "minimum_subgroup_holdout_cases": MINIMUM_SUBGROUP_HOLDOUT_CASES},
    }
    if input_reasons:
        return {**common, "status": "failed", "eligible_market_pools": [], "metrics": None,
                "blocking_reasons": sorted(set(input_reasons))}
    if not eligible:
        return {**common, "status": "not_ready", "eligible_market_pools": [], "metrics": None,
                "blocking_reasons": ["no_market_pool_meets_300_train_100_time_forward_holdout"]}
    rows_by_pool: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in manifest["dataset_rows"]:
        rows_by_pool[_pool_key(row)].append(row)
    pool_metrics = []
    pool_summary = []
    for pool in eligible:
        metric, model = _replay_metrics(rows_by_pool[(pool["currency"], pool["server"], pool["price_line"])], pool)
        pool_metrics.append({"currency": pool["currency"], "server": pool["server"], "price_line": pool["price_line"], **metric})
        pool_summary.append({"currency": pool["currency"], "server": pool["server"], "price_line": pool["price_line"],
                             "training_cluster_count": len(pool["training_cluster_ids"]),
                             "holdout_cluster_count": len(pool["holdout_cluster_ids"]), "cut_date": pool["cut_date"]})
    pool_reasons = {f"{metric['currency']}:{metric['server']}:{metric['price_line']}": _gate_reasons(metric) for metric in pool_metrics}
    failed = [f"{name}:{reason}" for name, reasons in pool_reasons.items() for reason in reasons]
    metrics = {"replay_kind": "evaluator_owned_train_only_date_trend", "market_pools": pool_metrics}
    if failed:
        return {**common, "status": "evaluation_required", "eligible_market_pools": pool_summary, "metrics": metrics,
                "blocking_reasons": sorted(set(failed))}
    bindings = [evaluator_artifact_binding(metric["price_line"], metric["model"], common["dataset_sha256"], common["dataset_manifest_sha256"], common["split_sha256"])
                for metric in pool_metrics]
    return {**common, "status": "passed", "publication_ready": True, "artifact_bindings": bindings,
            "eligible_market_pools": pool_summary, "metrics": metrics, "blocking_reasons": []}


def build(root: Path) -> dict[str, Any]:
    manifest, _split = build_publication_dataset(root.resolve())
    return evaluate(manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay fail-closed model publication evaluation inputs")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build(args.root)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
