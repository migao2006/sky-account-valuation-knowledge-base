#!/usr/bin/env python3
"""Replay the publication inputs without trusting model artifact claims.

P3.2 deliberately stops before fitting a model.  The report advances from
``not_ready`` to ``evaluation_required`` only when a frozen market pool has a
valid 300-cluster training partition and a later 100-cluster holdout.  A
future evaluator must add deterministic training, predictions and metrics
before ``publication_ready`` can ever become true.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from .publication_dataset import build as build_publication_dataset
except ImportError:
    from publication_dataset import build as build_publication_dataset

ROOT = Path(__file__).resolve().parents[2]


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest().upper()


def build(root: Path) -> dict[str, Any]:
    manifest, split = build_publication_dataset(root.resolve())
    eligible = [
        {
            "currency": pool["currency"],
            "server": pool["server"],
            "price_line": pool["price_line"],
            "training_cluster_count": len(pool["training_cluster_ids"]),
            "holdout_cluster_count": len(pool["holdout_cluster_ids"]),
            "cut_date": pool["cut_date"],
        }
        for pool in split["market_pools"]
        if pool.get("requirements_met") is True and pool.get("cluster_overlap") is False
    ]
    reasons: list[str] = []
    if not eligible:
        reasons.append("no_market_pool_meets_300_train_100_time_forward_holdout")
    else:
        reasons.extend([
            "deterministic_train_only_model_fit_not_implemented",
            "untouched_holdout_metrics_not_computed",
            "prediction_interval_and_subgroup_gates_not_computed",
        ])
    return {
        "schema_version": "1.0-p3.2",
        "status": "evaluation_required" if eligible else "not_ready",
        "publication_ready": False,
        "artifact_publication_fields_consulted": False,
        "dataset_sha256": manifest["dataset_sha256"],
        "dataset_manifest_sha256": _sha256(manifest),
        "split_sha256": _sha256(split),
        "requirements": {"training_clusters": 300, "holdout_clusters": 100},
        "eligible_market_pools": eligible,
        "metrics": None,
        "blocking_reasons": reasons,
    }


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
