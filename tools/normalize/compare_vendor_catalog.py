#!/usr/bin/env python3
"""Offline, conservative crosswalk of a pinned vendor catalog to canonical items.

Exact normalized-name matches are evidence for human review only.  This tool
never modifies canonical knowledge, aliases, candidates, or model eligibility.
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


COLLECTIBLE_TYPES = frozenset({"HairAccessory", "HeadAccessory", "Hair", "Mask", "FaceAccessory", "Necklace", "Outfit", "Shoes", "OutfitShoes", "Cape", "Held", "Furniture", "Prop", "Music", "Emote", "Stance", "Call"})


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest().upper()


def normalized(value: str) -> str:
    """Stable comparison key, intentionally not fuzzy matching."""
    return re.sub(r"[^\w]+", "", unicodedata.normalize("NFKC", value).casefold(), flags=re.UNICODE)


def resolve_relative(root: Path, value: str) -> Path:
    candidate = (root / value).resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("snapshot path is outside repository root")
    return candidate


def verify_snapshot(root: Path, snapshot_path: Path, metadata_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata = read_json(metadata_path)
    required = {"snapshot_id", "source_id", "source_package", "source_version", "source_git_commit", "license", "tarball_path", "tarball_sha256", "snapshot_path", "snapshot_sha256", "record_count", "canonical_promotion"}
    missing = required - metadata.keys()
    if missing:
        raise ValueError(f"vendor metadata missing fields: {sorted(missing)}")
    if metadata["canonical_promotion"] != "prohibited_without_independent_review":
        raise ValueError("vendor metadata must prohibit automatic canonical promotion")
    if snapshot_path.resolve() != resolve_relative(root, metadata["snapshot_path"]):
        raise ValueError("snapshot CLI path does not match metadata")
    if sha256(snapshot_path) != metadata["snapshot_sha256"].upper():
        raise ValueError("vendor snapshot SHA-256 mismatch")
    tarball = resolve_relative(root, metadata["tarball_path"])
    if not tarball.is_file() or sha256(tarball) != metadata["tarball_sha256"].upper():
        raise ValueError("vendor package SHA-256 mismatch")
    snapshot = read_json(snapshot_path)
    if snapshot.get("source_package") != metadata["source_package"] or snapshot.get("source_version") != metadata["source_version"] or snapshot.get("source_git_commit") != metadata["source_git_commit"]:
        raise ValueError("vendor snapshot identity does not match metadata")
    if not isinstance(snapshot.get("items"), list) or len(snapshot["items"]) != metadata["record_count"]:
        raise ValueError("vendor snapshot item count does not match metadata")
    return snapshot, metadata


def build_index(items: list[dict[str, Any]], aliases: list[dict[str, Any]]) -> dict[str, set[tuple[str, str]]]:
    index: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for item in items:
        item_id = item["item_id"]
        for name in [item.get("canonical_name_en", ""), *item.get("aliases", [])]:
            if isinstance(name, str) and (key := normalized(name)):
                index[key].add((item_id, "canonical_name" if name == item.get("canonical_name_en") else "embedded_alias"))
    for alias in aliases:
        if alias.get("target_type") == "item" and alias.get("language") == "en" and isinstance(alias.get("alias_text"), str):
            if key := normalized(alias["alias_text"]):
                index[key].add((alias["target_id"], "alias"))
    return index


def build_candidate_index(candidates: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Candidate names are secondary evidence, never a canonical identity."""
    index: dict[str, set[str]] = defaultdict(set)
    for candidate in candidates:
        name = candidate.get("candidate_name_en")
        candidate_id = candidate.get("candidate_item_id")
        if isinstance(name, str) and isinstance(candidate_id, str) and (key := normalized(name)):
            index[key].add(candidate_id)
    return index


def evidence_id(candidate_id: str, vendor_guid: str) -> str:
    material = f"vendor_skygame_data_1_3_4\0{candidate_id}\0{vendor_guid}\0candidate_name_en".encode("utf-8")
    return "evidence_vendor_" + hashlib.sha256(material).hexdigest()[:24]


def crosswalk(snapshot: dict[str, Any], metadata: dict[str, Any], items: list[dict[str, Any]], aliases: list[dict[str, Any]], candidates: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    index = build_index(items, aliases)
    candidate_index = build_candidate_index(candidates or [])
    rows: list[dict[str, Any]] = []
    evidence_rows: list[dict[str, Any]] = []
    for vendor in sorted(snapshot["items"], key=lambda row: (row["id"], row["guid"])):
        targets = index.get(normalized(vendor["name"]), set())
        canonical_ids = sorted({target_id for target_id, _ in targets})
        candidate_ids = sorted(candidate_index.get(normalized(vendor["name"]), set()))
        base = {"snapshot_id": metadata["snapshot_id"], "source_id": metadata["source_id"], "vendor_item_id": vendor["id"], "vendor_guid": vendor["guid"], "vendor_name": vendor["name"], "vendor_item_type": vendor["type"], "canonical_item_ids": canonical_ids, "candidate_item_ids": candidate_ids}
        if vendor["type"] not in COLLECTIBLE_TYPES:
            row = {**base, "match_status": "excluded_non_collectible", "match_methods": [], "review_status": "not_required"}
        elif len(canonical_ids) == 1:
            methods = sorted({method for _, method in targets})
            status = "matched_canonical_name" if "canonical_name" in methods else "matched_alias"
            row = {**base, "match_status": status, "match_methods": methods, "review_status": "needs_review"}
        elif len(canonical_ids) > 1:
            row = {**base, "match_status": "ambiguous_canonical_match", "match_methods": sorted({method for _, method in targets}), "review_status": "needs_review"}
        elif len(candidate_ids) == 1:
            row = {**base, "match_status": "matched_candidate_name", "match_methods": ["candidate_name"], "review_status": "needs_review"}
            candidate_id = candidate_ids[0]
            evidence_rows.append({
                "evidence_id": evidence_id(candidate_id, vendor["guid"]),
                "candidate_item_id": candidate_id,
                "field_path": "candidate_name_en",
                "claim_value": vendor["name"],
                "claim_value_hash": hashlib.sha256(normalized(vendor["name"]).encode("utf-8")).hexdigest().upper(),
                "source_id": metadata["source_id"],
                "snapshot_id": metadata["snapshot_id"],
                "snapshot_sha256": metadata["snapshot_sha256"],
                "locator": vendor["guid"],
                "vendor_item_id": vendor["id"],
                "vendor_item_type": vendor["type"],
                "evidence_role": "secondary_exact_normalized_name",
                "review_status": "needs_review",
                "canonical_promotion": "prohibited_without_independent_review",
            })
        elif len(candidate_ids) > 1:
            row = {**base, "match_status": "ambiguous_candidate_match", "match_methods": ["candidate_name"], "review_status": "needs_review"}
        else:
            row = {**base, "match_status": "unmatched_vendor_item", "match_methods": [], "review_status": "needs_review"}
        rows.append(row)
    counts = Counter(row["match_status"] for row in rows)
    canonical_matches = counts["matched_canonical_name"] + counts["matched_alias"]
    candidate_matches = counts["matched_candidate_name"]
    summary = {"snapshot_id": metadata["snapshot_id"], "source_id": metadata["source_id"], "snapshot_sha256": metadata["snapshot_sha256"], "canonical_item_count": len(items), "candidate_item_count": len(candidates or []), "vendor_item_count": len(rows), "status_counts": dict(sorted(counts.items())), "canonical_matched_count": canonical_matches, "candidate_matched_count": candidate_matches, "matched_count": canonical_matches + candidate_matches, "unmatched_collectible_count": counts["unmatched_vendor_item"], "review_count": sum(1 for row in rows if row["review_status"] == "needs_review"), "field_evidence_count": len(evidence_rows), "canonical_promotion": "not_performed", "matching_policy": "exact_normalized_name_only_canonical_then_candidate", "notes": "Canonical names and aliases take precedence. Candidate-name matches are secondary evidence only; unmatched and ambiguous rows require review and no vendor row is a canonical item."}
    return rows, summary, evidence_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare a fixed vendor catalog with canonical Sky item names without networking.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--snapshot", type=Path, default=Path("data/source/vendor/skygame-data-1.3.4-items.json"))
    parser.add_argument("--metadata", type=Path, default=Path("data/source/vendor/skygame-data-1.3.4-metadata.json"))
    parser.add_argument("--canonical-items", type=Path, default=Path("knowledge/items/items.jsonl"))
    parser.add_argument("--canonical-aliases", type=Path, default=Path("knowledge/aliases/item-aliases.jsonl"))
    parser.add_argument("--candidates", type=Path, default=Path("data/review/item-candidates.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/review/skygame-data-1.3.4-crosswalk.jsonl"))
    parser.add_argument("--summary", type=Path, default=Path("data/review/skygame-data-1.3.4-crosswalk-summary.json"))
    parser.add_argument("--field-evidence", type=Path, default=Path("data/review/skygame-data-1.3.4-item-evidence.jsonl"))
    args = parser.parse_args()
    root = args.root.resolve()
    def in_root(path: Path) -> Path:
        return path.resolve() if path.is_absolute() else (root / path).resolve()
    snapshot_path, metadata_path = in_root(args.snapshot), in_root(args.metadata)
    snapshot, metadata = verify_snapshot(root, snapshot_path, metadata_path)
    rows, summary, evidence_rows = crosswalk(snapshot, metadata, read_jsonl(in_root(args.canonical_items)), read_jsonl(in_root(args.canonical_aliases)), read_jsonl(in_root(args.candidates)))
    output, summary_path, evidence_path = in_root(args.output), in_root(args.summary), in_root(args.field_evidence)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8", newline="\n")
    summary_path.write_bytes(canonical_json(summary))
    evidence_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in evidence_rows), encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
