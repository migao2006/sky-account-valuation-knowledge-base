#!/usr/bin/env python3
"""Rebuild the fail-closed item-attribution coverage table.

This is a coverage projection, not an item price model.  Numerical
attributions remain unavailable until a separate replayable explanation
evaluator is implemented.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build(root: Path) -> list[dict[str, Any]]:
    items = read_jsonl(root / "knowledge/items/items.jsonl")
    counts: dict[str, Counter[str]] = {row["item_id"]: Counter() for row in items}
    vector_count = 0
    for vector in read_jsonl(root / "data/modeling/account-item-vectors.jsonl"):
        vector_count += 1
        for state in vector["item_states"]:
            counts[state["item_id"]][state["state"]] += 1
    rows = []
    for item in sorted(items, key=lambda row: row["item_id"]):
        state_counts = counts[item["item_id"]]
        rows.append({
            "attribution_sample_count": 0,
            "bootstrap_within_model_direction_stability": 0.0,
            "confirmed_missing_evidence_count": 0,
            "confirmed_missing_sample_count": state_counts["confirmed_missing"],
            "contribution_unit": "log_price_twd",
            "explanation_provenance": {"artifact_sha256": None, "input_snapshot_sha256": None, "model_sha256": None, "price_line": None, "status": "not_available"},
            "item_id": item["item_id"],
            "mean_conditional_attribution": None,
            "median_conditional_attribution": None,
            "model_feature_eligible": item.get("verification_status") == "verified" and item.get("model_feature_status") == "eligible",
            "owned_sample_count": state_counts["owned"],
            "refit_direction_stability": None,
            "refit_fold_count": 0,
            "schema_version": "3.1-p1",
            "status": "insufficient_support",
            "top_interaction": None,
            "unknown_sample_count": state_counts["unknown"] or max(0, vector_count - state_counts["owned"] - state_counts["confirmed_missing"]),
            "valuation_kind": "conditional_model_attribution_not_additive_item_price",
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild fail-closed item attribution coverage")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output or root / "data/modeling/item-value-table.jsonl"
    with output.open("w", encoding="utf-8", newline="\n") as handle:
        for row in build(root):
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    print(json.dumps({"rows": len(build(root)), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
