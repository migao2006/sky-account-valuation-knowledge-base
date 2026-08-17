#!/usr/bin/env python3
"""Freeze a replayable, fail-closed candidate publication dataset and split.

This module is evidence plumbing only.  It intentionally never reads model
artifacts.  Its derived status may advance to ``ready_for_evaluation`` when a
market pool satisfies the frozen 300/100 split contract, but a separate
replayable evaluator must still decide whether a model may be released.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
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
LINEAGE_FIELDS = (
    "training_example_id", "training_example_digest", "feature_payload_sha256",
    "catalog_provenance_sha256", "dedup_cluster_digest",
)
SHA256 = re.compile(r"^[A-Fa-f0-9]{64}$")


class PublicationDatasetError(ValueError):
    """The formal inputs cannot safely form a frozen candidate dataset."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest().upper()


def _signed_payload_sha256(value: Any) -> str:
    """Match the newline-terminated canonical bytes used by signed intake."""
    return hashlib.sha256((_canonical(value) + "\n").encode("utf-8")).hexdigest().upper()


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


def _row_payload(row: dict[str, Any], *, require_signed_lineage: bool) -> dict[str, Any]:
    required_strings = ("cleaned_price_id", "history_id", "account_id", "cluster_id")
    for field in required_strings:
        if not isinstance(row.get(field), str) or not row[field]:
            raise PublicationDatasetError(f"missing_{field}")
    if row.get("currency") != "TWD" or row.get("server") != "international":
        raise PublicationDatasetError("mixed_or_nonformal_market_pool")
    if row.get("price_line") not in {"normal_listing", "urgent_sale", "verified_sale"}:
        raise PublicationDatasetError("invalid_price_line")
    if row.get("date_verified") is not True:
        raise PublicationDatasetError("date_not_verified")
    price = row.get("selected_price_twd")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or not math.isfinite(float(price)) or price <= 0:
        raise PublicationDatasetError("invalid_selected_price_twd")
    payload = {
        "cleaned_price_id": row["cleaned_price_id"], "history_id": row["history_id"],
        "account_id": row["account_id"], "cluster_id": row["cluster_id"],
        "currency": "TWD", "server": "international", "price_line": row["price_line"],
        "selected_price_twd": float(price), "post_date": _date(row.get("post_date")),
        "date_verified": True,
    }
    present = [field for field in LINEAGE_FIELDS if field in row]
    if require_signed_lineage and not present:
        raise PublicationDatasetError("unsigned_clean_row")
    if present:
        if len(present) != len(LINEAGE_FIELDS) or any(not isinstance(row.get(field), str) or not SHA256.fullmatch(row[field]) for field in LINEAGE_FIELDS[1:]) or not isinstance(row.get("training_example_id"), str) or not row["training_example_id"].startswith("training_example_"):
            raise PublicationDatasetError("incomplete_signed_feature_lineage")
        payload.update({field: row[field] for field in LINEAGE_FIELDS})
    if row.get("price_line") == "verified_sale":
        sale_fields = ("completed_sale_verified", "sale_verified", "completed_sale_date", "completion_evidence_digest", "independent_evidence_ids", "observation_row_digest")
        if (
            any(field not in row for field in sale_fields)
            or row.get("completed_sale_verified") is not True or row.get("sale_verified") is not True
            or row.get("completed_sale_date") != payload["post_date"]
            or not isinstance(row.get("independent_evidence_ids"), list) or len(row["independent_evidence_ids"]) < 2
            or len(row["independent_evidence_ids"]) != len(set(row["independent_evidence_ids"]))
            or any(not isinstance(value, str) or not value.startswith("evidence_") for value in row["independent_evidence_ids"])
            or any(not isinstance(row.get(field), str) or not SHA256.fullmatch(row[field]) for field in ("completion_evidence_digest", "observation_row_digest"))
        ):
            raise PublicationDatasetError("incomplete_verified_sale_evidence")
        payload.update({field: row[field] for field in sale_fields})
    return payload


def _snapshot(root: Path) -> list[dict[str, str]]:
    paths = (
        "data/modeling/price-cleaned-normal.jsonl", "data/modeling/price-cleaned-urgent.jsonl",
        "data/modeling/price-cleaned-verified-sales.jsonl",
        "data/modeling/account-item-vectors.jsonl",
    )
    return [{"path": path, "sha256": _file_sha256(root / path)} for path in paths]


def _registered_training_examples(root: Path) -> list[dict[str, Any]]:
    """Load only v2 example commitments kept inside the formal registry tree."""
    registry = root / "data/review/market-authorization/registry.jsonl"
    dataset_root = (root / "data/review/market-authorization/datasets").resolve()
    examples: list[dict[str, Any]] = []
    for entry in read_jsonl(registry):
        manifest_rel = entry.get("manifest_path")
        if not isinstance(manifest_rel, str):
            raise PublicationDatasetError("registered_manifest_path_missing")
        manifest_path = (root / manifest_rel).resolve()
        try:
            manifest_path.relative_to(dataset_root)
        except ValueError as error:
            raise PublicationDatasetError("registered_manifest_path_escapes_datasets") from error
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PublicationDatasetError("registered_manifest_unreadable") from error
        if manifest.get("schema_version") not in {"authorized-market-manifest-v2", "authorized-market-manifest-v3"}:
            continue
        examples_rel = manifest.get("training_examples_path")
        if not isinstance(examples_rel, str):
            raise PublicationDatasetError("registered_training_examples_path_missing")
        examples_path = (root / examples_rel).resolve()
        try:
            examples_path.relative_to(dataset_root)
        except ValueError as error:
            raise PublicationDatasetError("registered_training_examples_path_escapes_datasets") from error
        examples.extend(read_jsonl(examples_path))
    return examples


def _example_index(training_examples: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index the exact v2 commitments available to the production build."""
    result: dict[str, dict[str, Any]] = {}
    for example in training_examples:
        identifier = example.get("training_example_id")
        if not isinstance(identifier, str) or identifier in result:
            raise PublicationDatasetError("duplicate_or_missing_training_example_id")
        result[identifier] = example
    return result


def _assert_signed_lineage(
    payload: dict[str, Any], vector: dict[str, Any], provenance: dict[str, Any], examples: dict[str, dict[str, Any]],
) -> None:
    """Require one atomic v2 commitment, not merely five plausible strings."""
    example = examples.get(payload["training_example_id"])
    if example is None:
        raise PublicationDatasetError(f"signed_training_example_not_registered:{payload['training_example_id']}")
    expected = {
        "training_example_digest": example.get("training_example_digest"),
        "feature_payload_sha256": example.get("feature_payload_sha256"),
        "catalog_provenance_sha256": example.get("catalog_provenance_sha256"),
        "dedup_cluster_digest": example.get("dedup_cluster_digest"),
    }
    if any(payload[field].upper() != str(value).upper() for field, value in expected.items()):
        raise PublicationDatasetError(f"signed_training_example_commitment_mismatch:{payload['training_example_id']}")
    if payload["account_id"] != example.get("account_id") or payload["cluster_id"] != example.get("dedup_cluster_id"):
        raise PublicationDatasetError(f"signed_training_example_account_or_cluster_mismatch:{payload['account_id']}")
    if payload["feature_payload_sha256"].upper() != _signed_payload_sha256(vector).upper():
        raise PublicationDatasetError(f"signed_feature_payload_vector_mismatch:{payload['account_id']}")
    if payload["catalog_provenance_sha256"].upper() != _signed_payload_sha256(provenance).upper():
        raise PublicationDatasetError(f"signed_catalog_provenance_mismatch:{payload['account_id']}")
    if payload["dedup_cluster_digest"].upper() != _signed_payload_sha256(payload["cluster_id"]).upper():
        raise PublicationDatasetError(f"signed_dedup_cluster_mismatch:{payload['account_id']}")
    if payload["price_line"] == "verified_sale":
        if any(payload.get(field) != example.get(field) for field in ("completed_sale_verified", "sale_verified", "completed_sale_date", "completion_evidence_digest", "independent_evidence_ids", "observation_row_digest")):
            raise PublicationDatasetError(f"signed_verified_sale_commitment_mismatch:{payload['training_example_id']}")


def _evaluation_subgroup(vector: dict[str, Any]) -> str:
    """Derive the predeclared public subgroup from the signed feature vector."""
    groups = vector.get("feature_groups")
    base = groups.get("base_account") if isinstance(groups, dict) else None
    value = base.get("account_type") if isinstance(base, dict) else None
    return value if isinstance(value, str) and value else "unknown"


def _freeze(
    clean_rows: list[dict[str, Any]], vector_rows: list[dict[str, Any]], provenance: dict[str, Any], snapshots: list[dict[str, str]],
    *, require_signed_lineage: bool, training_examples: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Validate and freeze explicit formal rows into a hash-addressed dataset."""
    vectors: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for vector in vector_rows:
        account = vector.get("account_id")
        if not isinstance(account, str) or not account:
            raise PublicationDatasetError("vector_missing_account_id")
        vectors[account].append(vector)
    frozen: list[dict[str, Any]] = []
    rejected: defaultdict[str, int] = defaultdict(int)
    examples = _example_index(training_examples or [])
    ids: set[str] = set()
    histories: set[str] = set()
    for source in clean_rows:
        try:
            payload = _row_payload(source, require_signed_lineage=require_signed_lineage)
        except PublicationDatasetError as error:
            # Unsigned clean rows are evidence of a missing v2 intake, rather
            # than a reason to make a 300/100 split look real.  Keep their
            # aggregate visible while excluding every one from the dataset.
            if str(error) in {"unsigned_clean_row", "incomplete_signed_feature_lineage"}:
                rejected[str(error)] += 1
                continue
            raise
        if payload["cleaned_price_id"] in ids or payload["history_id"] in histories:
            raise PublicationDatasetError("duplicate_clean_price_or_history_id")
        matching_vectors = vectors.get(payload["account_id"], [])
        if not matching_vectors:
            raise PublicationDatasetError(f"row_missing_vector:{payload['account_id']}")
        if len(matching_vectors) != 1:
            raise PublicationDatasetError(f"duplicate_vector_account_id:{payload['account_id']}")
        if matching_vectors[0].get("catalog_provenance") != provenance:
            raise PublicationDatasetError(f"stale_or_forged_catalog_provenance:{payload['account_id']}")
        if require_signed_lineage:
            _assert_signed_lineage(payload, matching_vectors[0], provenance, examples)
        payload["evaluation_subgroup"] = _evaluation_subgroup(matching_vectors[0])
        ids.add(payload["cleaned_price_id"])
        histories.add(payload["history_id"])
        frozen.append({**payload, "row_sha256": _sha256(payload)})
    frozen.sort(key=lambda row: (row["currency"], row["server"], row["price_line"], row["post_date"], row["cluster_id"], row["cleaned_price_id"]))
    pools: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in frozen:
        pools[(row["currency"], row["server"], row["price_line"])].append(row)
    return {
        "schema_version": "1.1-p3.2", "status": "not_ready",
        "dataset_path": DATASET_PATH, "dataset_sha256": _sha256(frozen), "dataset_row_count": len(frozen),
        "input_snapshots": snapshots, "catalog_provenance": provenance,
        "market_pools": [
            {"currency": key[0], "server": key[1], "price_line": key[2], "row_count": len(rows), "rows_sha256": _sha256(rows)}
            for key, rows in sorted(pools.items())
        ],
        "rejected_clean_row_count": sum(rejected.values()),
        "rejection_counts": [
            {"reason": reason, "count": count} for reason, count in sorted(rejected.items())
        ],
        "blockers": [
            {"code": "unsigned_clean_rows_excluded", "count": rejected["unsigned_clean_row"] + rejected["incomplete_signed_feature_lineage"]}
        ] if rejected else [],
        "dataset_rows": frozen,
    }


def freeze(
    clean_rows: list[dict[str, Any]], vector_rows: list[dict[str, Any]], provenance: dict[str, Any], snapshots: list[dict[str, str]],
    training_examples: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Freeze production data; every retained row needs a registered v2 commitment."""
    return _freeze(clean_rows, vector_rows, provenance, snapshots, require_signed_lineage=True, training_examples=training_examples)


def freeze_synthetic_for_test(
    clean_rows: list[dict[str, Any]], vector_rows: list[dict[str, Any]], provenance: dict[str, Any], snapshots: list[dict[str, str]],
) -> dict[str, Any]:
    """Test-only split fixture helper; it is deliberately not a production flag."""
    return _freeze(clean_rows, vector_rows, provenance, snapshots, require_signed_lineage=False, training_examples=None)


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
    status = "ready_for_evaluation" if any(pool["requirements_met"] for pool in pools) else "not_ready"
    return {
        "schema_version": "1.1-p3.2", "status": status, "dataset_path": manifest["dataset_path"],
        "dataset_sha256": manifest["dataset_sha256"], "requirements": {"training_clusters": TRAINING_CLUSTERS_REQUIRED, "holdout_clusters": HOLDOUT_CLUSTERS_REQUIRED},
        "market_pools": pools,
    }


def build(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    root = root.resolve()
    clean_rows = (
        read_jsonl(root / "data/modeling/price-cleaned-normal.jsonl")
        + read_jsonl(root / "data/modeling/price-cleaned-urgent.jsonl")
        + read_jsonl(root / "data/modeling/price-cleaned-verified-sales.jsonl")
    )
    manifest = freeze(
        clean_rows, read_jsonl(root / "data/modeling/account-item-vectors.jsonl"), catalog_provenance(root), _snapshot(root),
        _registered_training_examples(root),
    )
    report = split(manifest)
    manifest["schema_version"] = "1.1-p3.2"
    manifest["status"] = report["status"]
    return manifest, report


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
