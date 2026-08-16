#!/usr/bin/env python3
"""Build a deterministic, review-only registry of vendor collectible records.

This consumes the already pinned SkyGame-Data snapshot and its conservative
crosswalk.  It deliberately does not create canonical items, aliases, item
vectors, or model features.  A row records a vendor-side collectible identity
and any existing exact-name link only as review evidence.
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


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def normalized_name(value: str) -> str:
    return re.sub(r"[^\w]+", "", unicodedata.normalize("NFKC", value).casefold(), flags=re.UNICODE)


def cluster_id(name_key: str) -> str:
    return "vendor_name_" + hashlib.sha256(name_key.encode("utf-8")).hexdigest()[:20]


def registry_id(vendor_guid: str) -> str:
    return "vendor_collectible_" + vendor_guid


def build_registry(snapshot: dict[str, Any], crosswalk_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return collectible-only review rows and a summary, without mutation.

    Cluster membership is calculated from every pinned vendor record, rather
    than only collectible records.  This exposes name collisions such as an
    emote with a non-collectible implementation record and keeps them in a
    fail-closed review quarantine.
    """
    vendor_rows = snapshot.get("items")
    if not isinstance(vendor_rows, list):
        raise ValueError("vendor snapshot must contain an items list")
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
        if (linked.get("vendor_item_id"), linked.get("vendor_name"), linked.get("vendor_item_type")) != (vendor["id"], vendor["name"], vendor["type"]):
            raise ValueError("crosswalk record differs from pinned vendor snapshot")

    all_clusters: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in vendor_rows:
        if not isinstance(row.get("name"), str) or not row["name"]:
            raise ValueError("vendor snapshot names must be non-empty strings")
        all_clusters[normalized_name(row["name"])].append(row)

    registry: list[dict[str, Any]] = []
    for vendor in sorted(vendor_rows, key=lambda row: (row["id"], row["guid"])):
        if vendor["type"] not in COLLECTIBLE_TYPES:
            continue
        crosswalk = by_guid[vendor["guid"]]
        name_key = normalized_name(vendor["name"])
        members = all_clusters[name_key]
        member_types = sorted({member["type"] for member in members})
        cross_type = len(member_types) > 1
        match_status = crosswalk["match_status"]
        if match_status in {"matched_canonical_name", "matched_alias"}:
            link_status = "canonical_link"
        elif match_status == "matched_candidate_name":
            link_status = "candidate_link"
        else:
            link_status = "unresolved"
        registry.append({
            "registry_id": registry_id(vendor["guid"]),
            "snapshot_id": crosswalk["snapshot_id"],
            "source_id": crosswalk["source_id"],
            "vendor_item_id": vendor["id"],
            "vendor_guid": vendor["guid"],
            "vendor_name": vendor["name"],
            "vendor_item_type": vendor["type"],
            "normalized_name": name_key,
            "name_cluster": {
                "cluster_id": cluster_id(name_key),
                "snapshot_member_count": len(members),
                "collectible_member_count": sum(member["type"] in COLLECTIBLE_TYPES for member in members),
                "vendor_item_types": member_types,
                "cross_type_conflict": cross_type,
            },
            "link_status": link_status,
            "crosswalk_match_status": match_status,
            "canonical_item_ids": crosswalk["canonical_item_ids"],
            "candidate_item_ids": crosswalk["candidate_item_ids"],
            "review_status": "quarantined_cross_type_conflict" if cross_type else "needs_review",
            "canonical_write": "not_performed",
            "model_feature_status": "excluded_pending_verification",
        })

    link_counts = Counter(row["link_status"] for row in registry)
    all_cross_type_clusters = {
        cluster_id(name_key)
        for name_key, members in all_clusters.items()
        if len({member["type"] for member in members}) > 1
    }
    collectible_conflict_clusters = {row["name_cluster"]["cluster_id"] for row in registry if row["name_cluster"]["cross_type_conflict"]}
    summary = {
        "registry_id": "vendor_skygame_data_1_3_4_collectible_registry",
        "snapshot_id": registry[0]["snapshot_id"] if registry else "vendor_skygame_data_1_3_4",
        "source_id": registry[0]["source_id"] if registry else "source_skygame_data_1_3_4",
        "vendor_item_count": len(vendor_rows),
        "collectible_type_count": len(COLLECTIBLE_TYPES),
        "collectible_types": sorted(COLLECTIBLE_TYPES),
        "collectible_record_count": len(registry),
        "excluded_non_collectible_count": len(vendor_rows) - len(registry),
        "link_status_counts": dict(sorted(link_counts.items())),
        "canonical_link_count": link_counts["canonical_link"],
        "candidate_link_count": link_counts["candidate_link"],
        "unresolved_count": link_counts["unresolved"],
        "name_cluster_count": len(all_clusters),
        # This is the full snapshot count. Five clusters currently contain no
        # collectible record, so their excluded records remain summary-only.
        "cross_type_conflict_cluster_count": len(all_cross_type_clusters),
        "cross_type_conflict_collectible_cluster_count": len(collectible_conflict_clusters),
        "cross_type_conflict_collectible_record_count": sum(row["name_cluster"]["cross_type_conflict"] for row in registry),
        "canonical_write": "not_performed",
        "model_feature_status": "excluded_pending_verification",
        "notes": "Collectible records are review-only. Exact-name links inherit the existing crosswalk and are not identity confirmation. Name clusters include all vendor types; cross-type clusters are quarantined. Excluded non-collectible rows are represented only by this summary.",
    }
    return registry, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an offline review-only vendor collectible registry.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--snapshot", type=Path, default=Path("data/source/vendor/skygame-data-1.3.4-items.json"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/review/skygame-data-1.3.4-crosswalk.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/review/vendor-collectible-registry.jsonl"))
    parser.add_argument("--summary", type=Path, default=Path("data/review/vendor-collectible-registry-summary.json"))
    args = parser.parse_args()
    root = args.root.resolve()
    def local(path: Path) -> Path:
        result = path.resolve() if path.is_absolute() else (root / path).resolve()
        if root not in result.parents and result != root:
            raise ValueError("path is outside repository root")
        return result
    rows, summary = build_registry(read_json(local(args.snapshot)), read_jsonl(local(args.crosswalk)))
    # Inputs are repository-bound; callers may direct deterministic test output
    # to a temporary directory outside the checkout.
    output = args.output.resolve() if args.output.is_absolute() else (root / args.output).resolve()
    summary_path = args.summary.resolve() if args.summary.is_absolute() else (root / args.summary).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8", newline="\n")
    summary_path.write_bytes(canonical_json(summary))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
