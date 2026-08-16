#!/usr/bin/env python3
"""Produce offline TreeSHAP main and pairwise interaction attributions.

XGBoost exposes exact TreeSHAP contributions through ``pred_contribs`` and
``pred_interactions``.  No SHAP package or network service is required.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modeling.train_xgboost import flatten_vector, load_model_eligible_items, read_jsonl


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _verify_snapshot(root: Path, artifact: dict[str, Any]) -> None:
    paths = artifact.get("input_snapshot_paths")
    if not isinstance(paths, list) or not paths or not all(isinstance(item, str) for item in paths):
        raise ValueError("artifact snapshot paths are invalid")
    resolved = []
    for relative in paths:
        candidate = (root / relative).resolve()
        if root.resolve() not in candidate.parents or not candidate.is_file():
            raise ValueError("artifact snapshot path is missing or outside repository")
        resolved.append(candidate)
    # P1 training has exactly vectors + optional cleaned prices.  Recompute the
    # same lower-case digest contract used by the trainer, never trusting the
    # stored aggregate alone.
    digest = hashlib.sha256()
    for relative, candidate in sorted(zip(paths, resolved), key=lambda item: item[0]):
        digest.update(relative.encode("utf-8")); digest.update(b"\0")
        digest.update(hashlib.sha256(candidate.read_bytes()).hexdigest().encode("ascii")); digest.update(b"\n")
    if digest.hexdigest().upper() != str(artifact.get("input_snapshot_sha256", "")).upper():
        raise ValueError("artifact input snapshot hash does not match")


def _load_artifact(path: Path) -> dict[str, Any]:
    artifact = json.loads(path.read_text(encoding="utf-8"))
    if artifact.get("model_type") != "xgboost" or artifact.get("status") != "trained":
        raise ValueError("XGBoost artifact is not a trained offline model")
    if not isinstance(artifact.get("model_file"), str):
        raise ValueError("trained artifact has no model_file")
    model_file = path.parent / artifact["model_file"]
    if not model_file.is_file() or not isinstance(artifact.get("model_sha256"), str) or _sha256(model_file) != artifact["model_sha256"].upper():
        raise ValueError("trained artifact model hash does not match")
    return artifact


def explain(artifact_path: Path, input_path: Path, output: Path, top_interactions: int = 10) -> int:
    artifact = _load_artifact(artifact_path)
    try:
        import numpy as np
        import xgboost as xgb
    except ImportError as exc:
        raise RuntimeError("XGBoost dependency unavailable; explanations are not generated") from exc
    features = artifact.get("feature_schema", {}).get("feature_names", [])
    if not isinstance(features, list) or not all(isinstance(x, str) for x in features):
        raise ValueError("artifact feature schema is invalid")
    model_file = artifact_path.parent / artifact["model_file"]
    if not model_file.is_file():
        raise ValueError("artifact model file is missing")
    # Explanation rows must be traceable to the exact vector snapshot that
    # trained the model.  A query vector is handled by the estimator, not this
    # catalog-attribution exporter.
    try:
        root = next(parent for parent in (artifact_path.parent, *artifact_path.parents) if (parent / "manifest.json").is_file())
    except StopIteration as exc:
        raise ValueError("cannot verify artifact snapshot outside repository") from exc
    _verify_snapshot(root, artifact)
    input_relative = input_path.resolve().relative_to(root.resolve()).as_posix()
    if input_relative not in artifact.get("input_snapshot_paths", []):
        raise ValueError("explanation input is not an artifact snapshot path")
    booster = xgb.Booster()
    booster.load_model(model_file)
    rows = read_jsonl(input_path)
    eligible_item_ids = load_model_eligible_items(input_path)
    matrix = np.array([[flatten_vector(row, eligible_item_ids)[0].get(name, float("nan")) for name in features] for row in rows], dtype=float)
    dm = xgb.DMatrix(matrix, feature_names=features)
    contributions = booster.predict(dm, pred_contribs=True, validate_features=True)
    interactions = booster.predict(dm, pred_interactions=True, validate_features=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for index, row in enumerate(rows):
            main = {name: float(contributions[index][col]) for col, name in enumerate(features)}
            pairs = []
            for left in range(len(features)):
                for right in range(left + 1, len(features)):
                    value = float(interactions[index][left][right] + interactions[index][right][left])
                    if value:
                        pairs.append({"left_feature": features[left], "right_feature": features[right], "contribution_log_price": value})
            pairs.sort(key=lambda item: abs(item["contribution_log_price"]), reverse=True)
            result = {
                "schema_version": "3.1-p1",
                "account_id": row.get("account_id", "unknown"),
                "model_type": "xgboost",
                "price_line": artifact["price_line"],
                "artifact_sha256": _sha256(artifact_path),
                "model_sha256": artifact["model_sha256"].upper(),
                "input_snapshot_sha256": artifact["input_snapshot_sha256"].upper(),
                "method": "xgboost_pred_contribs_and_pred_interactions",
                "unit": "log_price_twd",
                "conditional_attribution_only": True,
                "base_value_log_price": float(contributions[index][-1]),
                "main_effects": main,
                "top_interactions": pairs[:max(0, top_interactions)],
            }
            handle.write(json.dumps(result, ensure_ascii=False, sort_keys=True) + "\n")
    provenance = {
        "schema_version": "3.1-p1", "model_type": "xgboost", "price_line": artifact["price_line"],
        "artifact_path": artifact_path.resolve().relative_to(root.resolve()).as_posix(), "artifact_sha256": _sha256(artifact_path),
        "model_file": artifact["model_file"], "model_sha256": artifact["model_sha256"].upper(),
        "input_snapshot_paths": artifact["input_snapshot_paths"], "input_snapshot_sha256": artifact["input_snapshot_sha256"].upper(),
        "explained_vector_path": input_relative, "explained_vector_sha256": _sha256(input_path), "explanations_sha256": _sha256(output), "record_count": len(rows),
        # The standard P1 exporter has no independently reproducible refit
        # artifacts.  A sidecar may not elevate this to a publication claim.
        "refit_provenance": "not_available", "refit_fold_count": 0, "refit_direction_stability": None,
    }
    output.with_suffix(output.suffix + ".provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline TreeSHAP explanations for a trained XGBoost artifact.")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--top-interactions", type=int, default=10)
    args = parser.parse_args()
    explain(args.artifact, args.input, args.output, args.top_interactions)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
