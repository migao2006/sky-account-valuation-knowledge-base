#!/usr/bin/env python3
"""Build an offline, queryable index over the three catalog truth layers.

The index is derived only.  It deliberately carries IDs and minimal lookup
keys, rather than copying a second item master.  A lookup result is never
evidence that an account owns an item.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _resolve(root: Path, path: Path) -> Path:
    result = path.resolve() if path.is_absolute() else (root / path).resolve()
    if root not in result.parents and result != root:
        raise ValueError("path is outside repository root")
    return result


def _snapshot_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def _query_row(*, query_entity_type: str, query_entity_id: str, truth_level: str,
               verification_status: str, source_ids: list[str], lookup_keys: list[str],
               canonical_item_ids: list[str], candidate_item_ids: list[str],
               source_snapshot_sha256: str | None, resolution_eligibility: str,
               review_status: str, model_feature_status: str = "excluded_pending_verification") -> dict[str, Any]:
    return {
        "query_entity_type": query_entity_type,
        "query_entity_id": query_entity_id,
        "truth_level": truth_level,
        "verification_status": verification_status,
        "source_ids": sorted(source_ids),
        "lookup_keys": sorted({key for key in lookup_keys if isinstance(key, str) and key.strip()}),
        "canonical_item_ids": sorted(set(canonical_item_ids)),
        "candidate_item_ids": sorted(set(candidate_item_ids)),
        "source_snapshot_sha256": source_snapshot_sha256,
        "resolution_eligibility": resolution_eligibility,
        "review_status": review_status,
        "model_feature_status": model_feature_status,
        "ambiguous_lookup_keys": [],
        "has_lookup_key_collision": False,
    }


def build_catalog_query_index(items: list[dict[str, Any]], aliases: list[dict[str, Any]], candidates: list[dict[str, Any]],
                              references: list[dict[str, Any]], snapshot_path: Path,
                              snapshot_metadata: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build a deterministic query index without promoting any truth layer."""
    expected_hash = snapshot_metadata.get("snapshot_sha256")
    actual_hash = _snapshot_hash(snapshot_path)
    if not isinstance(expected_hash, str) or actual_hash != expected_hash:
        raise ValueError("vendor snapshot bytes do not match metadata snapshot_sha256")
    item_ids = {row.get("item_id") for row in items}
    candidate_ids = {row.get("candidate_item_id") for row in candidates}
    if len(item_ids) != len(items) or None in item_ids:
        raise ValueError("canonical items must have unique item_id values")
    if len(candidate_ids) != len(candidates) or None in candidate_ids:
        raise ValueError("review candidates must have unique candidate_item_id values")
    if item_ids & candidate_ids:
        raise ValueError("canonical and candidate IDs must be disjoint")
    aliases_by_item: dict[str, list[str]] = {item_id: [] for item_id in item_ids}
    for alias in aliases:
        if alias.get("target_type") != "item":
            continue
        target_id = alias.get("target_id")
        if target_id not in item_ids:
            raise ValueError("item alias contains an unknown canonical target")
        aliases_by_item[target_id].extend(
            value for value in (alias.get("alias_text"), alias.get("normalized_alias")) if isinstance(value, str)
        )
    reference_ids = {row.get("reference_identity_id") for row in references}
    if len(reference_ids) != len(references) or None in reference_ids:
        raise ValueError("source references must have unique reference_identity_id values")
    rows: list[dict[str, Any]] = []
    for item in items:
        verified = item.get("verification_status") == "verified"
        rows.append(_query_row(
            query_entity_type="canonical_item", query_entity_id=item["item_id"], truth_level="canonical_knowledge",
            verification_status=item.get("verification_status", "needs_review"), source_ids=item.get("source_ids", []),
            lookup_keys=[item["item_id"], item.get("canonical_name_en", ""), item.get("canonical_name_zh_tw", ""), *item.get("aliases", []), *aliases_by_item[item["item_id"]]],
            canonical_item_ids=[item["item_id"]], candidate_item_ids=[], source_snapshot_sha256=None,
            resolution_eligibility="canonical_resolved" if verified else "review_only",
            review_status="approved" if verified else "needs_review",
            model_feature_status=item.get("model_feature_status", "excluded_pending_verification")))
    for candidate in candidates:
        rows.append(_query_row(
            query_entity_type="review_candidate", query_entity_id=candidate["candidate_item_id"], truth_level="review_candidate",
            verification_status="needs_review", source_ids=candidate.get("source_ids", []),
            lookup_keys=[candidate["candidate_item_id"], candidate.get("candidate_name_en", "")],
            canonical_item_ids=[], candidate_item_ids=[candidate["candidate_item_id"]], source_snapshot_sha256=None,
            resolution_eligibility="review_only", review_status="needs_review"))
    for reference in references:
        canonical_ids = reference.get("canonical_item_ids", [])
        candidate_links = reference.get("candidate_item_ids", [])
        if not set(canonical_ids) <= item_ids or not set(candidate_links) <= candidate_ids:
            raise ValueError("source reference contains an unknown canonical or candidate target")
        unique_verified = (
            reference.get("link_status") == "canonical_link" and len(canonical_ids) == 1
            and not reference.get("name_cluster", {}).get("cross_type_conflict", True)
            and reference.get("canonical_identity_status") == "verified"
            and next(item for item in items if item["item_id"] == canonical_ids[0]).get("verification_status") == "verified"
        )
        rows.append(_query_row(
            query_entity_type="source_reference", query_entity_id=reference["reference_identity_id"], truth_level="source_snapshot_observation",
            verification_status="unverified", source_ids=[reference["source_id"]],
            lookup_keys=[reference["reference_identity_id"], reference["normalized_name"]],
            canonical_item_ids=canonical_ids, candidate_item_ids=candidate_links,
            source_snapshot_sha256=reference.get("source_snapshot_sha256"),
            resolution_eligibility="canonical_resolved" if unique_verified else "review_only",
            review_status="quarantined" if reference.get("review_status") == "quarantined_cross_type_conflict" else "needs_review"))
    rows.sort(key=lambda row: (row["query_entity_type"], row["query_entity_id"]))
    lookup_owners: dict[str, set[str]] = {}
    for row in rows:
        for key in row["lookup_keys"]:
            normalized_key = key.strip().casefold()
            if normalized_key:
                lookup_owners.setdefault(normalized_key, set()).add(row["query_entity_id"])
    collisions = {key for key, owners in lookup_owners.items() if len(owners) > 1}
    for row in rows:
        row["ambiguous_lookup_keys"] = sorted({
            key.strip().casefold() for key in row["lookup_keys"]
            if key.strip().casefold() in collisions
        })
        row["has_lookup_key_collision"] = bool(row["ambiguous_lookup_keys"])
    kinds = Counter(row["query_entity_type"] for row in rows)
    summary = {
        "index_version": "1.0", "canonical_item_count": kinds["canonical_item"],
        "review_candidate_count": kinds["review_candidate"], "source_reference_count": kinds["source_reference"],
        "query_row_count": len(rows), "source_snapshot_sha256": actual_hash,
        "canonical_resolved_eligible_count": sum(row["resolution_eligibility"] == "canonical_resolved" for row in rows),
        "ambiguous_lookup_key_count": len(collisions),
        "rows_with_lookup_key_collisions": sum(row["has_lookup_key_collision"] for row in rows),
        "model_feature_status": "mixed" if any(row["model_feature_status"] == "eligible" for row in rows) else "excluded_pending_verification",
        "notes": "Query results preserve distinct canonical, review-candidate, and source-observation truth levels. They do not establish ownership or model features.",
    }
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the offline unified catalog query index.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--items", type=Path, default=Path("knowledge/items/items.jsonl"))
    parser.add_argument("--aliases", type=Path, default=Path("knowledge/aliases/item-aliases.jsonl"))
    parser.add_argument("--candidates", type=Path, default=Path("data/review/item-candidates.jsonl"))
    parser.add_argument("--references", type=Path, default=Path("data/normalized/source-scoped-item-identities.jsonl"))
    parser.add_argument("--snapshot", type=Path, default=Path("data/source/vendor/skygame-data-1.3.4-items.json"))
    parser.add_argument("--metadata", type=Path, default=Path("data/source/vendor/skygame-data-1.3.4-metadata.json"))
    parser.add_argument("--output", type=Path, default=Path("data/normalized/catalog-query-index.jsonl"))
    parser.add_argument("--summary", type=Path, default=Path("data/normalized/catalog-query-index-summary.json"))
    args = parser.parse_args(); root = args.root.resolve()
    metadata = json.loads(_resolve(root, args.metadata).read_text(encoding="utf-8"))
    rows, summary = build_catalog_query_index(read_jsonl(_resolve(root, args.items)), read_jsonl(_resolve(root, args.aliases)), read_jsonl(_resolve(root, args.candidates)), read_jsonl(_resolve(root, args.references)), _resolve(root, args.snapshot), metadata)
    # Inputs must stay in the repository.  Deterministic derived output may be
    # directed to an external temporary directory for reproducibility tests.
    output = args.output.resolve() if args.output.is_absolute() else _resolve(root, args.output)
    summary_path = args.summary.resolve() if args.summary.is_absolute() else _resolve(root, args.summary)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8", newline="\n")
    summary_path.write_bytes(canonical_json(summary)); print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
