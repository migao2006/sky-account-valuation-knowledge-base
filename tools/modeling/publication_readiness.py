#!/usr/bin/env python3
"""Replayable evidence audit for model-publication readiness.

This is deliberately *not* a model evaluator.  It derives sample and split
capacity exclusively from the checked-in clean price lines, vectors, catalog,
and formal comparable history.  In particular, it never reads a model
artifact or trusts a ``publication_gate`` supplied by one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

try:  # Package import for integration callers (``tools.modeling...``).
    from .catalog_provenance import catalog_provenance, read_jsonl
except ImportError:  # Direct script execution from ``tools/modeling``.
    from catalog_provenance import catalog_provenance, read_jsonl


ROOT = Path(__file__).resolve().parents[2]
TRAINING_CLUSTERS_REQUIRED = 300
HOLDOUT_CLUSTERS_REQUIRED = 100


def _read_date(value: Any) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def verified_date(row: dict[str, Any]) -> date | None:
    """Return only a documented listing/transaction event date.

    ``observed_at`` records when this repository collected a source.  It can
    be identical for arbitrarily old listings and therefore cannot establish
    time-forward ordering.  A missing or malformed ``post_date`` is unknown,
    not a fallback opportunity.
    """
    if row.get("date_verified") is not True:
        return None
    return _read_date(row.get("post_date"))


def _pool_name(row: dict[str, Any]) -> str:
    return f"{row.get('currency')}:{row.get('server')}:{row.get('price_line')}"


def _best_time_forward_split(cluster_dates: dict[str, tuple[date, date]]) -> dict[str, Any]:
    """Select the best strict date split without ever splitting a cluster.

    A cluster with observations spanning a cut is omitted from that candidate;
    this is conservative and makes date/cluster overlap impossible.  Tied
    dates remain on one side of the cut because training uses ``end < cut``.
    """
    boundaries = sorted({start for start, _end in cluster_dates.values()})
    candidates: list[tuple[int, int, date, list[str], list[str], int]] = []
    for boundary in boundaries:
        train = sorted(cluster for cluster, (_start, end) in cluster_dates.items() if end < boundary)
        holdout = sorted(cluster for cluster, (start, _end) in cluster_dates.items() if start >= boundary)
        spanning = sum(1 for start, end in cluster_dates.values() if start < boundary <= end)
        if train and holdout:
            # First maximize how much of the explicit 300/100 contract is met;
            # then prefer more holdout clusters, then the earliest reproducible
            # boundary.  The last key keeps selection stable.
            score = min(len(train), TRAINING_CLUSTERS_REQUIRED) + min(len(holdout), HOLDOUT_CLUSTERS_REQUIRED)
            candidates.append((score, len(holdout), boundary, train, holdout, spanning))
    if not candidates:
        return {
            "available": False, "cut_date": None, "training_clusters": 0,
            "holdout_clusters": 0, "excluded_spanning_clusters": 0,
            "cluster_overlap": False,
        }
    _score, _holdout, boundary, train, holdout, spanning = max(candidates, key=lambda entry: (entry[0], entry[1], -entry[2].toordinal()))
    return {
        "available": len(train) >= TRAINING_CLUSTERS_REQUIRED and len(holdout) >= HOLDOUT_CLUSTERS_REQUIRED,
        "cut_date": boundary.isoformat(), "training_clusters": len(train),
        "holdout_clusters": len(holdout), "excluded_spanning_clusters": spanning,
        # Explicitly derive this from sets so future edits cannot silently
        # claim a grouped split while leaking a cluster across it.
        "cluster_overlap": bool(set(train) & set(holdout)),
    }


def audit(
    clean_rows: list[dict[str, Any]],
    vector_rows: list[dict[str, Any]],
    catalog_rows: list[dict[str, Any]],
    comparable_rows: list[dict[str, Any]],
    expected_provenance: dict[str, Any] | None = None,
    registered_training_examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a deterministic readiness report from explicit formal inputs."""
    vectors = {row.get("account_id"): row for row in vector_rows if isinstance(row.get("account_id"), str)}
    eligible_vectors = {
        account_id for account_id, row in vectors.items()
        if expected_provenance is None or row.get("catalog_provenance") == expected_provenance
    }
    invalid_vector_accounts = sorted(set(vectors) - eligible_vectors)
    expected_provenance_sha256 = (
        hashlib.sha256((json.dumps(expected_provenance, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")).hexdigest().upper()
        if expected_provenance is not None else None
    )
    registered_examples = {
        str(row.get("training_example_id")): row
        for row in (registered_training_examples or [])
        if isinstance(row, dict) and isinstance(row.get("training_example_id"), str)
    }
    registered_accounts: set[str] = set()
    pools: dict[str, list[dict[str, Any]]] = defaultdict(list)
    invalid_market_rows = 0
    missing_vector_rows = 0
    for row in clean_rows:
        if row.get("currency") != "TWD" or row.get("server") != "international" or row.get("price_line") not in {"normal_listing", "urgent_sale", "verified_sale"}:
            invalid_market_rows += 1
            continue
        example = registered_examples.get(str(row.get("training_example_id")))
        signed_input_valid = bool(
            example
            and example.get("account_id") == row.get("account_id")
            and example.get("feature_payload_sha256") == row.get("feature_payload_sha256")
            and example.get("catalog_provenance_sha256") == row.get("catalog_provenance_sha256")
            and (expected_provenance is None or example.get("catalog_provenance") == expected_provenance)
            and (expected_provenance_sha256 is None or str(row.get("catalog_provenance_sha256", "")).upper() == expected_provenance_sha256)
        )
        if signed_input_valid:
            registered_accounts.add(str(row.get("account_id")))
        elif row.get("account_id") not in eligible_vectors:
            missing_vector_rows += 1
        # Pool capacity is a market-data fact.  Keep it visible even when a
        # later catalog revision has made vectors stale; that separate defect
        # is reported globally and must still block any actual model input.
        pools[_pool_name(row)].append(row)

    pool_reports: list[dict[str, Any]] = []
    for market_pool in sorted(pools):
        rows = pools[market_pool]
        dated: dict[str, list[date]] = defaultdict(list)
        all_clusters = {str(row.get("cluster_id")) for row in rows if isinstance(row.get("cluster_id"), str) and row.get("cluster_id")}
        for row in rows:
            cluster = row.get("cluster_id")
            row_date = verified_date(row)
            if isinstance(cluster, str) and cluster and row_date is not None:
                dated[cluster].append(row_date)
        intervals = {cluster: (min(dates), max(dates)) for cluster, dates in dated.items()}
        split = _best_time_forward_split(intervals)
        train_gap = max(0, TRAINING_CLUSTERS_REQUIRED - split["training_clusters"])
        holdout_gap = max(0, HOLDOUT_CLUSTERS_REQUIRED - split["holdout_clusters"])
        reasons: list[str] = []
        if len(all_clusters) < TRAINING_CLUSTERS_REQUIRED:
            reasons.append("independent_training_clusters_insufficient")
        if len(intervals) < len(all_clusters):
            reasons.append("clusters_missing_verified_dates")
        if not split["available"]:
            reasons.append("time_forward_holdout_unavailable")
        if train_gap:
            reasons.append("time_forward_training_clusters_insufficient")
        if holdout_gap:
            reasons.append("time_forward_holdout_clusters_insufficient")
        if split["cluster_overlap"]:
            reasons.append("time_forward_cluster_overlap")
        pool_reports.append({
            "market_pool": market_pool, "clean_price_rows": len(rows),
            "independent_cluster_count": len(all_clusters),
            "dated_cluster_count": len(intervals),
            "verified_date_count": len({item for dates in dated.values() for item in dates}),
            "time_forward_split": split,
            "training_cluster_gap": train_gap, "holdout_cluster_gap": holdout_gap,
            "blocking_reasons": reasons,
        })

    model_eligible = sum(
        row.get("verification_status") == "verified" and row.get("model_feature_status") == "eligible"
        for row in catalog_rows
    )
    verified_sales = sum(
        (
            row.get("price_line") == "verified_sale"
            and row.get("completed_sale_verified") is True
            and row.get("sale_verified") is True
        )
        or (
            isinstance(row.get("sale_outcome"), dict)
            and row["sale_outcome"].get("verified") is True
        )
        for row in comparable_rows
    )
    global_reasons: list[str] = []
    if not pool_reports:
        global_reasons.append("no_formal_clean_price_pool")
    if missing_vector_rows:
        global_reasons.append("clean_price_rows_missing_valid_vectors")
    if invalid_market_rows:
        global_reasons.append("clean_price_rows_outside_formal_market_pool")
    if invalid_vector_accounts:
        global_reasons.append("vectors_with_stale_catalog_provenance")
    if model_eligible == 0:
        global_reasons.append("no_model_eligible_catalog_items")
    if verified_sales == 0:
        global_reasons.append("no_verified_completed_sales")
    for pool in pool_reports:
        global_reasons.extend(f"{pool['market_pool']}:{reason}" for reason in pool["blocking_reasons"])
    status = "ready_for_evaluation" if not global_reasons else "not_ready"
    return {
        "schema_version": "1.2-p3.7", "status": status,
        "artifact_publication_fields_consulted": False,
        "trained_models_treated_as_passed": False,
        "requirements": {"independent_training_clusters": TRAINING_CLUSTERS_REQUIRED, "time_forward_holdout_clusters": HOLDOUT_CLUSTERS_REQUIRED},
        "formal_clean_price_rows": len(clean_rows), "valid_vector_accounts": len(eligible_vectors | registered_accounts),
        "model_eligible_item_count": model_eligible, "verified_completed_sale_count": verified_sales,
        "market_pools": pool_reports, "blocking_reasons": sorted(set(global_reasons)),
    }


def build(root: Path) -> dict[str, Any]:
    root = root.resolve()
    clean_paths = [
        root / "data/modeling/price-cleaned-normal.jsonl",
        root / "data/modeling/price-cleaned-urgent.jsonl",
        root / "data/modeling/price-cleaned-verified-sales.jsonl",
    ]
    clean_rows = [row for path in clean_paths for row in read_jsonl(path)]
    try:
        from .publication_dataset import _registered_training_examples
    except ImportError:
        from publication_dataset import _registered_training_examples
    return audit(
        clean_rows, read_jsonl(root / "data/modeling/account-item-vectors.jsonl"),
        read_jsonl(root / "knowledge/items/items.jsonl"),
        read_jsonl(root / "data/modeling/price-cleaned-verified-sales.jsonl"),
        catalog_provenance(root),
        _registered_training_examples(root),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Derive model-publication readiness from formal offline evidence")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build(args.root)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
