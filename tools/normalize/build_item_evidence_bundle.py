#!/usr/bin/env python3
"""Build replayable identity-only evidence from pinned local candidate/vendor data.

The output is review data.  It never writes canonical items, candidates, or
aliases, and it performs no network access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

VENDOR_CATEGORY = {"HairAccessory": "accessory", "HeadAccessory": "accessory", "Hair": "hair", "Mask": "mask", "FaceAccessory": "accessory", "Necklace": "accessory", "Outfit": "outfit", "Shoes": "shoes", "OutfitShoes": "outfit", "Cape": "cape", "Held": "prop", "Furniture": "furniture", "Prop": "prop", "Music": "music_sheet", "Emote": "emote", "Stance": "emote", "Call": "emote"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def sha(value: bytes | str) -> str:
    if isinstance(value, str): value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest().upper()


def claim_hash(value: Any) -> str:
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def evidence_id(candidate_id: str, source_id: str, field: str) -> str:
    return "item_evidence_" + hashlib.sha256(f"{candidate_id}\0{source_id}\0{field}".encode()).hexdigest()[:24]


def row(candidate_id: str, field: str, value: Any, source_id: str, locator: str, snapshot_hash: str, source_tier: str) -> dict[str, Any]:
    return {"evidence_id": evidence_id(candidate_id, source_id, field), "candidate_item_id": candidate_id, "proposed_canonical_item_id": candidate_id, "field_path": field, "claim_value": value, "claim_hash": claim_hash(value), "source_id": source_id, "source_tier": source_tier, "source_locator": locator, "source_snapshot_hash": snapshot_hash, "evidence_role": "template_seed_identity" if source_tier == "unverified_template_seed" and field == "canonical_identity" else "template_seed_field" if source_tier == "unverified_template_seed" else "independent_identity" if field == "canonical_identity" else "independent_field", "review_status": "machine_correlated", "reviewed_at": "2026-08-17", "notes": "Deterministic vendor correlation against an unverified template seed; it is not human review, a second independent item-name source, canonical verification, or model eligibility."}


def build(candidates: list[dict[str, Any]], vendor_evidence: list[dict[str, Any]], candidate_snapshot_hash: str) -> list[dict[str, Any]]:
    vendor_by_candidate = {row["candidate_item_id"]: row for row in vendor_evidence}
    rows: list[dict[str, Any]] = []
    for candidate in sorted(candidates, key=lambda value: value["candidate_item_id"]):
        vendor = vendor_by_candidate.get(candidate["candidate_item_id"])
        if not vendor: continue
        source_id = candidate["source_ids"][0]
        locator = f"data/review/item-candidates.jsonl#{candidate['candidate_item_id']}"
        for field, value in (("canonical_identity", candidate["candidate_name_en"]), ("canonical_name_en", candidate["candidate_name_en"]), ("item_category", candidate["candidate_category"])):
            rows.append(row(candidate["candidate_item_id"], field, value, source_id, locator, candidate_snapshot_hash, "unverified_template_seed"))
        vendor_locator = f"data/source/vendor/skygame-data-1.3.4-items.json#{vendor['locator']}"
        for field, value in (("canonical_identity", vendor["claim_value"]), ("canonical_name_en", vendor["claim_value"]), ("item_category", VENDOR_CATEGORY.get(vendor["vendor_item_type"], "unknown"))):
            rows.append(row(candidate["candidate_item_id"], field, value, vendor["source_id"], vendor_locator, vendor["snapshot_sha256"], "maintained_community"))
    return sorted(rows, key=lambda value: (value["candidate_item_id"], value["source_id"], value["field_path"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Build replayable, non-canonical identity-only item evidence.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--candidates", type=Path, default=Path("data/review/item-candidates.jsonl"))
    parser.add_argument("--vendor-evidence", type=Path, default=Path("data/review/skygame-data-1.3.4-item-evidence.jsonl"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(); root = args.root.resolve()
    def path(value: Path) -> Path: return value.resolve() if value.is_absolute() else (root / value).resolve()
    candidate_path, vendor_path, output = path(args.candidates), path(args.vendor_evidence), path(args.output)
    rows = build(read_jsonl(candidate_path), read_jsonl(vendor_path), sha(candidate_path.read_bytes()))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in rows), encoding="utf-8", newline="\n")
    print(json.dumps({"evidence_count": len(rows), "candidate_count": len({value['candidate_item_id'] for value in rows}), "canonical_writes": 0}, sort_keys=True))


if __name__ == "__main__": main()
