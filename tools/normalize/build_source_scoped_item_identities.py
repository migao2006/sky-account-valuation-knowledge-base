#!/usr/bin/env python3
"""Build source-scoped collectible reference identities from a pinned snapshot.

This offline derived layer preserves observed vendor records without asserting
that they are canonical Sky identities.  It never writes canonical knowledge,
aliases, account item vectors, or model features.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


COLLECTIBLE_TYPES = frozenset({
    "HairAccessory", "HeadAccessory", "Hair", "Mask", "FaceAccessory",
    "Necklace", "Outfit", "Shoes", "OutfitShoes", "Cape", "Held",
    "Furniture", "Prop", "Music", "Emote", "Stance", "Call",
})


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_snapshot_bytes(snapshot_path: Path, metadata: dict[str, Any]) -> str:
    """Bind a build to the exact pinned snapshot bytes before parsing them."""
    expected = metadata.get("snapshot_sha256")
    actual = hashlib.sha256(snapshot_path.read_bytes()).hexdigest().upper()
    if not isinstance(expected, str) or actual != expected:
        raise ValueError("vendor snapshot bytes do not match metadata snapshot_sha256")
    return actual


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def normalized_name(value: str) -> str:
    return re.sub(r"[^\w]+", "", unicodedata.normalize("NFKC", value).casefold(), flags=re.UNICODE)


def cluster_id(name_key: str) -> str:
    return "vendor_name_" + hashlib.sha256(name_key.encode("utf-8")).hexdigest()[:20]


def reference_identity_id(source_id: str, snapshot_id: str, vendor_guid: str) -> str:
    """Stable source-scoped identity, intentionally not a canonical item ID."""
    material = f"{source_id}\0{snapshot_id}\0{vendor_guid}".encode("utf-8")
    return "reference_identity_" + hashlib.sha256(material).hexdigest()[:32]


def build_source_scoped_identities(snapshot: dict[str, Any], metadata: dict[str, Any], crosswalk_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    vendor_rows = snapshot.get("items")
    if not isinstance(vendor_rows, list):
        raise ValueError("vendor snapshot must contain an items list")
    required_metadata = {"source_id", "snapshot_id", "snapshot_sha256", "record_count"}
    missing = sorted(required_metadata - set(metadata))
    if missing:
        raise ValueError(f"vendor metadata missing fields: {missing}")
    if metadata["record_count"] != len(vendor_rows):
        raise ValueError("vendor metadata record count differs from snapshot")
    by_guid = {row.get("vendor_guid"): row for row in crosswalk_rows}
    if len(by_guid) != len(crosswalk_rows) or None in by_guid:
        raise ValueError("crosswalk vendor GUIDs must be unique and non-empty")
    if len({row.get("id") for row in vendor_rows}) != len(vendor_rows):
        raise ValueError("vendor snapshot item IDs must be unique")
    if len({row.get("guid") for row in vendor_rows}) != len(vendor_rows) or any(not row.get("guid") for row in vendor_rows):
        raise ValueError("vendor snapshot GUIDs must be unique and non-empty")
    if set(by_guid) != {row["guid"] for row in vendor_rows}:
        raise ValueError("crosswalk GUID set does not match vendor snapshot")
    for vendor in vendor_rows:
        linked = by_guid[vendor["guid"]]
        if (linked.get("snapshot_id"), linked.get("source_id")) != (metadata["snapshot_id"], metadata["source_id"]):
            raise ValueError("crosswalk source or snapshot differs from metadata")
        if (linked.get("vendor_item_id"), linked.get("vendor_name"), linked.get("vendor_item_type")) != (vendor["id"], vendor["name"], vendor["type"]):
            raise ValueError("crosswalk record differs from pinned vendor snapshot")

    all_clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in vendor_rows:
        if not isinstance(row.get("name"), str) or not row["name"]:
            raise ValueError("vendor snapshot names must be non-empty strings")
        all_clusters[normalized_name(row["name"])].append(row)

    rows: list[dict[str, Any]] = []
    for vendor in sorted(vendor_rows, key=lambda row: (row["id"], row["guid"])):
        if vendor["type"] not in COLLECTIBLE_TYPES:
            continue
        crosswalk = by_guid[vendor["guid"]]
        key = normalized_name(vendor["name"])
        members = all_clusters[key]
        member_types = sorted({member["type"] for member in members})
        cross_type_conflict = len(member_types) > 1
        match_status = crosswalk["match_status"]
        link_status = "canonical_link" if match_status in {"matched_canonical_name", "matched_alias"} else "candidate_link" if match_status == "matched_candidate_name" else "unresolved"
        rows.append({
            "reference_identity_id": reference_identity_id(metadata["source_id"], metadata["snapshot_id"], vendor["guid"]),
            "identity_scope": "source_snapshot_only",
            "canonical_identity_status": "unverified",
            "promotion_eligibility": "prohibited",
            "snapshot_id": metadata["snapshot_id"],
            "source_id": metadata["source_id"],
            "source_snapshot_sha256": metadata["snapshot_sha256"],
            "vendor_item_id": vendor["id"],
            "vendor_guid": vendor["guid"],
            "observed_name": vendor["name"],
            "observed_item_type": vendor["type"],
            "normalized_name": key,
            "name_cluster": {
                "cluster_id": cluster_id(key),
                "snapshot_member_count": len(members),
                "collectible_member_count": sum(member["type"] in COLLECTIBLE_TYPES for member in members),
                "observed_item_types": member_types,
                "cross_type_conflict": cross_type_conflict,
            },
            "link_status": link_status,
            "crosswalk_match_status": match_status,
            "canonical_item_ids": crosswalk["canonical_item_ids"],
            "candidate_item_ids": crosswalk["candidate_item_ids"],
            "review_status": "quarantined_cross_type_conflict" if cross_type_conflict else "needs_review",
            "model_feature_status": "excluded_pending_verification",
        })

    counts = Counter(row["link_status"] for row in rows)
    all_conflicts = {cluster_id(key) for key, members in all_clusters.items() if len({member["type"] for member in members}) > 1}
    collectible_conflicts = {row["name_cluster"]["cluster_id"] for row in rows if row["name_cluster"]["cross_type_conflict"]}
    summary = {
        "identity_scope": "source_snapshot_only",
        "canonical_identity_status": "unverified",
        "promotion_eligibility": "prohibited",
        "snapshot_id": metadata["snapshot_id"],
        "source_id": metadata["source_id"],
        "source_snapshot_sha256": metadata["snapshot_sha256"],
        "vendor_item_count": len(vendor_rows),
        "collectible_record_count": len(rows),
        "excluded_non_collectible_count": len(vendor_rows) - len(rows),
        "link_status_counts": dict(sorted(counts.items())),
        "canonical_link_count": counts["canonical_link"],
        "candidate_link_count": counts["candidate_link"],
        "unresolved_count": counts["unresolved"],
        "cross_type_conflict_cluster_count": len(all_conflicts),
        "cross_type_conflict_collectible_cluster_count": len(collectible_conflicts),
        "cross_type_conflict_collectible_record_count": sum(row["name_cluster"]["cross_type_conflict"] for row in rows),
        "model_feature_status": "excluded_pending_verification",
        "notes": "Each row is a source-scoped observation from one pinned snapshot, not a canonical item identity. Links are review evidence only; conflicts are quarantined and all rows are excluded from model features.",
    }
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build offline source-scoped collectible reference identities.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--snapshot", type=Path, default=Path("data/source/vendor/skygame-data-1.3.4-items.json"))
    parser.add_argument("--metadata", type=Path, default=Path("data/source/vendor/skygame-data-1.3.4-metadata.json"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/review/skygame-data-1.3.4-crosswalk.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/normalized/source-scoped-item-identities.jsonl"))
    parser.add_argument("--summary", type=Path, default=Path("data/normalized/source-scoped-item-identities-summary.json"))
    args = parser.parse_args()
    root = args.root.resolve()
    def local(path: Path) -> Path:
        result = path.resolve() if path.is_absolute() else (root / path).resolve()
        if root not in result.parents and result != root:
            raise ValueError("input path is outside repository root")
        return result
    snapshot_path = local(args.snapshot)
    metadata = read_json(local(args.metadata))
    verify_snapshot_bytes(snapshot_path, metadata)
    rows, summary = build_source_scoped_identities(read_json(snapshot_path), metadata, read_jsonl(local(args.crosswalk)))
    output = args.output.resolve() if args.output.is_absolute() else (root / args.output).resolve()
    summary_path = args.summary.resolve() if args.summary.is_absolute() else (root / args.summary).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8", newline="\n")
    summary_path.write_bytes(canonical_json(summary))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
