#!/usr/bin/env python3
"""Freeze a replayable, fail-closed candidate publication dataset and split.

This module is evidence plumbing only.  It intentionally never reads model
artifacts and its status is permanently ``not_ready``; a later, separately
approved publication gate must decide whether a model may be released.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

try:
    from .catalog_provenance import catalog_provenance, read_jsonl
except ImportError:
    from catalog_provenance import catalog_provenance, read_jsonl


ROOT = Path(__file__).resolve().parents[2]
TRAINING_CLUSTERS_REQUIRED = 300
HOLDOUT_CLUSTERS_REQUIRED = 100
DATASET_PATH = "reports/model-publication-dataset-manifest.json#dataset_rows"


class PublicationDatasetError(ValueError):
    """The formal inputs cannot safely form a frozen candidate dataset."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest().upper()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _date(value: Any) -> str:
    if not isinstance(value, str):
        raise PublicationDatasetError("date_missing_or_not_string")
    try:
        date.fromisoformat(value)
    except ValueError as error:
        raise PublicationDatasetError("date_not_iso8601") from error
    return value


def _row_payload(row: dict[str, Any]) -> dict[str, Any]:
    required_strings = ("cleaned_price_id", "history_id", "account_id", "cluster_id")
    for field in required_strings:
        if not isinstance(row.get(field), str) or not row[field]:
            raise PublicationDatasetError(f"missing_{field}")
    if row.get("currency") != "TWD" or row.get("server") != "international":
        raise PublicationDatasetError("mixed_or_nonformal_market_pool")
    if row.get("price_line") not in {"normal_listing", "urgent_sale"}:
        raise PublicationDatasetError("invalid_price_line")
    if row.get("date_verified") is not True:
        raise PublicationDatasetError("date_not_verified")
    price = row.get("selected_price_twd")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or not math.isfinite(float(price)) or price <= 0:
        raise PublicationDatasetError("invalid_selected_price_twd")
    return {
        "cleaned_price_id": row["cleaned_price_id"], "history_id": row["history_id"],
        "account_id": row["account_id"], "cluster_id": row["cluster_id"],
        "currency": "TWD", "server": "international", "price_line": row["price_line"],
        "selected_price_twd": float(price), "post_date": _date(row.get("post_date")),
        "date_verified": True,
    }


def _snapshot(root: Path) -> list[dict[str, str]]:
    paths = (
        "data/modeling/price-cleaned-normal.jsonl", "data/modeling/price-cleaned-urgent.jsonl",
        "data/modeling/account-item-vectors.jsonl",
    )
    return [{"path": path, "sha256": _file_sha256(root / path)} for path in paths]


def freeze(clean_rows: list[dict[str, Any]], vector_rows: list[dict[str, Any]], provenance: dict[str, Any], snapshots: list[dict[str, str]]) -> dict[str, Any]:
    """Validate and freeze explicit formal rows into a hash-addressed dataset."""
    vectors: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for vector in vector_rows:
        account = vector.get("account_id")
        if not isinstance(account, str) or not account:
            raise PublicationDatasetError("vector_missing_account_id")
        vectors[account].append(vector)
    frozen: list[dict[str, Any]] = []
    ids: set[str] = set()
    histories: set[str] = set()
    for source in clean_rows:
        payload = _row_payload(source)
        if payload["cleaned_price_id"] in ids or payload["history_id"] in histories:
            raise PublicationDatasetError("duplicate_clean_price_or_history_id")
        matching_vectors = vectors.get(payload["account_id"], [])
        if not matching_vectors:
            raise PublicationDatasetError(f"row_missing_vector:{payload['account_id']}")
        if len(matching_vectors) != 1:
            raise PublicationDatasetError(f"duplicate_vector_account_id:{payload['account_id']}")
        if matching_vectors[0].get("catalog_provenance") != provenance:
            raise PublicationDatasetError(f"stale_or_forged_catalog_provenance:{payload['account_id']}")
        ids.add(payload["cleaned_price_id"])
        histories.add(payload["history_id"])
        frozen.append({**payload, "row_sha256": _sha256(payload)})
    frozen.sort(key=lambda row: (row["currency"], row["server"], row["price_line"], row["post_date"], row["cluster_id"], row["cleaned_price_id"]))
    pools: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in frozen:
        pools[(row["currency"], row["server"], row["price_line"])].append(row)
    return {
        "schema_version": "1.0-p3.1", "status": "not_ready",
        "dataset_path": DATASET_PATH, "dataset_sha256": _sha256(frozen), "dataset_row_count": len(frozen),
        "input_snapshots": snapshots, "catalog_provenance": provenance,
        "market_pools": [
            {"currency": key[0], "server": key[1], "price_line": key[2], "row_count": len(rows), "rows_sha256": _sha256(rows)}
            for key, rows in sorted(pools.items())
        ],
        "dataset_rows": frozen,
    }


def _best_split(rows: list[dict[str, Any]]) -> dict[str, Any]:
    accounts: dict[str, str] = {}
    dates: dict[str, list[date]] = defaultdict(list)
    for row in rows:
        cluster, account = row["cluster_id"], row["account_id"]
        if cluster in accounts and accounts[cluster] != account:
            raise PublicationDatasetError(f"cluster_maps_to_multiple_accounts:{cluster}")
        accounts[cluster] = account
        dates[cluster].append(date.fromisoformat(row["post_date"]))
    intervals = {cluster: (min(values), max(values)) for cluster, values in dates.items()}
    candidates: list[tuple[int, int, date, list[str], list[str], list[str]]] = []
    for cut in sorted({begin for begin, _ in intervals.values()}):
        train = sorted(cluster for cluster, (_begin, end) in intervals.items() if end < cut)
        holdout = sorted(cluster for cluster, (begin, _end) in intervals.items() if begin >= cut)
        spanning = sorted(cluster for cluster, (begin, end) in intervals.items() if begin < cut <= end)
        if train and holdout:
            score = min(len(train), TRAINING_CLUSTERS_REQUIRED) + min(len(holdout), HOLDOUT_CLUSTERS_REQUIRED)
            candidates.append((score, len(holdout), cut, train, holdout, spanning))
    if not candidates:
        return {"cut_date": None, "training_cluster_ids": [], "holdout_cluster_ids": [], "excluded_spanning_cluster_ids": [], "cluster_overlap": False, "requirements_met": False}
    _score, _holdout, cut, train, holdout, spanning = max(candidates, key=lambda item: (item[0], item[1], -item[2].toordinal()))
    return {"cut_date": cut.isoformat(), "training_cluster_ids": train, "holdout_cluster_ids": holdout, "excluded_spanning_cluster_ids": spanning, "cluster_overlap": bool(set(train) & set(holdout)), "requirements_met": len(train) >= TRAINING_CLUSTERS_REQUIRED and len(holdout) >= HOLDOUT_CLUSTERS_REQUIRED}


def split(manifest: dict[str, Any]) -> dict[str, Any]:
    """Derive a cluster-exclusive time-forward split from a frozen manifest."""
    if manifest.get("dataset_path") != DATASET_PATH or manifest.get("dataset_sha256") != _sha256(manifest.get("dataset_rows")):
        raise PublicationDatasetError("dataset_manifest_hash_mismatch")
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in manifest["dataset_rows"]:
        payload = {key: row[key] for key in row if key != "row_sha256"}
        if row.get("row_sha256") != _sha256(payload):
            raise PublicationDatasetError("dataset_row_hash_mismatch")
        grouped[(row["currency"], row["server"], row["price_line"])].append(row)
    pools = []
    for key, rows in sorted(grouped.items()):
        result = _best_split(rows)
        result.update({"currency": key[0], "server": key[1], "price_line": key[2], "row_count": len(rows)})
        pools.append(result)
    return {
        "schema_version": "1.0-p3.1", "status": "not_ready", "dataset_path": manifest["dataset_path"],
        "dataset_sha256": manifest["dataset_sha256"], "requirements": {"training_clusters": TRAINING_CLUSTERS_REQUIRED, "holdout_clusters": HOLDOUT_CLUSTERS_REQUIRED},
        "market_pools": pools,
    }


def build(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    root = root.resolve()
    clean_rows = read_jsonl(root / "data/modeling/price-cleaned-normal.jsonl") + read_jsonl(root / "data/modeling/price-cleaned-urgent.jsonl")
    manifest = freeze(clean_rows, read_jsonl(root / "data/modeling/account-item-vectors.jsonl"), catalog_provenance(root), _snapshot(root))
    return manifest, split(manifest)


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze deterministic publication dataset and cluster split")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--split-output", type=Path)
    args = parser.parse_args()
    manifest, report = build(args.root)
    if args.manifest_output:
        args.manifest_output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    if args.split_output:
        args.split_output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    if not args.manifest_output and not args.split_output:
        print(json.dumps({"manifest": manifest, "split": report}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
