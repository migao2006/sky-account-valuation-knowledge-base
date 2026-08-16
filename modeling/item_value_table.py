#!/usr/bin/env python3
"""Build a conditional-attribution Item Value Table from offline explanations.

Rows are evidence summaries in log-price contribution units, never additive
item prices.  Sparse items deliberately have no numerical attribution.
"""
from __future__ import annotations

import argparse
import json
import hashlib
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modeling.train_xgboost import read_jsonl
from modeling.explain import _verify_snapshot

MIN_OWNED = 10
MIN_CONFIRMED_MISSING = 5
MIN_DIRECTION_STABILITY = 0.80


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _formal_catalog_ids(vectors_path: Path) -> set[str] | None:
    """Return the canonical set when this is a repository vector file."""
    try:
        root = next(parent for parent in (vectors_path.parent, *vectors_path.parents) if (parent / "manifest.json").is_file())
    except StopIteration:
        return None
    catalog = root / "knowledge" / "items" / "items.jsonl"
    if not catalog.is_file() or vectors_path.resolve() != (root / "data" / "modeling" / "account-item-vectors.jsonl").resolve():
        return None
    return {str(row["item_id"]) for row in read_jsonl(catalog) if isinstance(row.get("item_id"), str)}


def _verified_provenance(vectors_path: Path, explanations_path: Path, explanations: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    """Verify one immutable XGBoost explanation provenance, or fail closed."""
    if not explanations:
        return None
    path = explanations_path.with_suffix(explanations_path.suffix + ".provenance.json")
    if not path.is_file():
        raise ValueError("nonempty explanations require a provenance sidecar")
    provenance = json.loads(path.read_text(encoding="utf-8"))
    required = ("model_type", "price_line", "artifact_path", "artifact_sha256", "model_file", "model_sha256", "input_snapshot_sha256", "explained_vector_path", "explained_vector_sha256", "explanations_sha256")
    if provenance.get("model_type") != "xgboost" or any(not isinstance(provenance.get(key), str) for key in required):
        raise ValueError("invalid explanation provenance")
    try:
        root = next(parent for parent in (vectors_path.parent, *vectors_path.parents) if (parent / "manifest.json").is_file())
        artifact_path = (root / provenance["artifact_path"]).resolve()
    except StopIteration as exc:
        raise ValueError("cannot locate repository root for explanation provenance") from exc
    if not artifact_path.is_file() or _sha256(artifact_path) != provenance["artifact_sha256"].upper():
        raise ValueError("explanation artifact hash mismatch")
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    _verify_snapshot(root, artifact)
    model_path = artifact_path.parent / provenance["model_file"]
    if not model_path.is_file() or _sha256(model_path) != provenance["model_sha256"].upper():
        raise ValueError("explanation model hash mismatch")
    training = artifact.get("training", {})
    if artifact.get("model_type") != "xgboost" or artifact.get("status") != "trained" or artifact.get("price_line") != provenance["price_line"] or artifact.get("input_snapshot_sha256", "").upper() != provenance["input_snapshot_sha256"].upper():
        raise ValueError("explanation artifact contract mismatch")
    if not isinstance(training, dict) or training.get("threshold_met") is not True or training.get("baseline_beaten") is not True or not isinstance(training.get("outer_cv_mae"), (int, float)) or not isinstance(training.get("baseline_median_mae"), (int, float)) or training["baseline_median_mae"] <= training["outer_cv_mae"] or int(training.get("group_count", 0)) < 4 or int(training.get("outer_cv_folds", 0)) < 2:
        raise ValueError("explanation artifact does not meet grouped training quality gates")
    if _sha256(vectors_path) != provenance["explained_vector_sha256"].upper() or vectors_path.resolve().relative_to(root.resolve()).as_posix() != provenance["explained_vector_path"]:
        raise ValueError("explanation vector snapshot mismatch")
    if _sha256(explanations_path) != provenance["explanations_sha256"].upper():
        raise ValueError("explanation file hash mismatch")
    for explanation in explanations.values():
        if any(explanation.get(key) != provenance[key] for key in ("model_type", "price_line", "artifact_sha256", "model_sha256", "input_snapshot_sha256")):
            raise ValueError("mixed model, price-line, or snapshot explanations are not allowed")
    return provenance


def _bootstrap_stability(values: list[float], seed: int = 20260816, draws: int = 500) -> float:
    if not values:
        return 0.0
    observed = sum(values) / len(values)
    if observed == 0:
        return 0.0
    wanted_positive = observed > 0
    rng = random.Random(seed)
    matches = 0
    for _ in range(draws):
        mean = sum(rng.choice(values) for _ in values) / len(values)
        if (mean > 0) == wanted_positive and mean != 0:
            matches += 1
    return matches / draws


def build(vectors_path: Path, explanations_path: Path, output: Path) -> list[dict[str, Any]]:
    vectors = {str(row.get("account_id")): row for row in read_jsonl(vectors_path)}
    catalog_ids = _formal_catalog_ids(vectors_path)
    explanations = {str(row.get("account_id")): row for row in read_jsonl(explanations_path)}
    provenance = _verified_provenance(vectors_path, explanations_path, explanations)
    # State counts describe the complete vector corpus.  Attribution samples
    # are intentionally a separate population because an explanation may be
    # unavailable while an ownership claim remains valid evidence.
    owned_counts: dict[str, int] = defaultdict(int)
    attribution_values: dict[str, list[float]] = defaultdict(list)
    missing: dict[str, int] = defaultdict(int)
    supported_missing: dict[str, int] = defaultdict(int)
    unknown: dict[str, int] = defaultdict(int)
    model_feature_eligible: dict[str, bool] = defaultdict(bool)
    interactions: dict[str, dict[tuple[str, str], list[float]]] = defaultdict(lambda: defaultdict(list))
    all_items: set[str] = set()
    for account_id, vector in vectors.items():
        explanation = explanations.get(account_id, {})
        effects = explanation.get("main_effects", {})
        if not isinstance(effects, dict):
            effects = {}
        raw_states = vector.get("item_states", {})
        if isinstance(raw_states, list):
            states = {str(state.get("item_id")): state.get("state", "unknown") for state in raw_states
                      if isinstance(state, dict) and isinstance(state.get("item_id"), str)}
            for state in raw_states:
                if isinstance(state, dict) and isinstance(state.get("item_id"), str):
                    item_id = str(state["item_id"])
                    model_feature_eligible[item_id] = model_feature_eligible[item_id] or (state.get("model_feature") is True and state.get("review_status") == "approved")
        elif isinstance(raw_states, dict):
            states = raw_states
        else:
            continue
        if catalog_ids is not None and set(states) != catalog_ids:
            raise ValueError("formal item vector item IDs do not exactly match canonical catalog")
        for item_id, state in states.items():
            item_id = str(item_id)
            all_items.add(item_id)
            if state == "owned":
                owned_counts[item_id] += 1
                value = effects.get(f"item:{item_id}:owned")
                if isinstance(value, (int, float)):
                    attribution_values[item_id].append(float(value))
            elif state == "confirmed_missing":
                missing[item_id] += 1
                if isinstance(raw_states, list):
                    source = next((entry for entry in raw_states if isinstance(entry, dict) and entry.get("item_id") == item_id), {})
                    if source.get("review_status") == "approved" and source.get("evidence_state") in {"profile_claim", "text_claim"} and source.get("conflict") is False:
                        supported_missing[item_id] += 1
                else:
                    supported_missing[item_id] += 1
            else:
                unknown[item_id] += 1
        for pair in explanation.get("top_interactions", []):
            if not isinstance(pair, dict) or not isinstance(pair.get("contribution_log_price"), (int, float)):
                continue
            left, right = str(pair.get("left_feature", "")), str(pair.get("right_feature", ""))
            for item_id in states:
                prefix = f"item:{item_id}:"
                if left.startswith(prefix) or right.startswith(prefix):
                    interactions[str(item_id)][(left, right)].append(float(pair["contribution_log_price"]))
    output_rows: list[dict[str, Any]] = []
    if catalog_ids is not None and all_items != catalog_ids:
        raise ValueError("item table item IDs do not exactly match canonical catalog")
    for item_id in sorted(all_items):
        values = attribution_values[item_id]
        stability = _bootstrap_stability(values)
        # Bootstrap resampling of one model does not establish refit/fold
        # stability.  Publication requires explicit multi-refit provenance;
        # normal P1 output deliberately remains fail-closed until it exists.
        # Standard P1 sidecars are deliberately unable to self-attest a
        # multi-refit study.  A future controlled builder must have a distinct
        # verifiable fold-artifact contract before this gate can open.
        refit_folds = 0
        refit_stability = None
        enough = model_feature_eligible[item_id] and owned_counts[item_id] >= MIN_OWNED and supported_missing[item_id] >= MIN_CONFIRMED_MISSING and len(values) >= MIN_OWNED and refit_folds >= 2 and isinstance(refit_stability, (int, float)) and refit_stability >= MIN_DIRECTION_STABILITY
        top_interaction = None
        if enough and interactions[item_id]:
            pair, pair_values = max(interactions[item_id].items(), key=lambda entry: abs(sum(entry[1]) / len(entry[1])))
            top_interaction = {"left_feature": pair[0], "right_feature": pair[1],
                               "mean_contribution_log_price": sum(pair_values) / len(pair_values), "sample_count": len(pair_values)}
        row: dict[str, Any] = {
            "schema_version": "3.1-p1",
            "item_id": item_id,
            "valuation_kind": "conditional_model_attribution_not_additive_item_price",
            "owned_sample_count": owned_counts[item_id],
            "attribution_sample_count": len(values),
            "confirmed_missing_sample_count": missing[item_id],
            "confirmed_missing_evidence_count": supported_missing[item_id],
            "unknown_sample_count": unknown[item_id],
            "model_feature_eligible": model_feature_eligible[item_id],
            "bootstrap_within_model_direction_stability": stability,
            "refit_fold_count": refit_folds,
            "refit_direction_stability": refit_stability if isinstance(refit_stability, (int, float)) else None,
            "explanation_provenance": {"status": "verified", "price_line": provenance["price_line"], "artifact_sha256": provenance["artifact_sha256"], "model_sha256": provenance["model_sha256"], "input_snapshot_sha256": provenance["input_snapshot_sha256"]} if provenance else {"status": "not_available", "price_line": None, "artifact_sha256": None, "model_sha256": None, "input_snapshot_sha256": None},
            "status": "eligible" if enough else "insufficient_support",
            "contribution_unit": "log_price_twd",
            "mean_conditional_attribution": (sum(values) / len(values)) if enough else None,
            "median_conditional_attribution": (sorted(values)[len(values) // 2]) if enough else None,
            "top_interaction": top_interaction,
        }
        output_rows.append(row)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for row in output_rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return output_rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an offline, non-additive conditional item attribution table.")
    parser.add_argument("--vectors", type=Path, required=True)
    parser.add_argument("--explanations", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.vectors, args.explanations, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
