#!/usr/bin/env python3
"""Replay the bounded, offline FAQ 1356 Moomintroll Accessory Set cohort.

The tool never fetches data or creates a source registry entry.  Both source
snapshots, every pointer, and every canonical write are pinned and fail closed.
FAQ 1356 supports one historical pack and season window, not current access.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

OFFICIAL_SOURCE = "source_tgc_faq_1356_moomintroll_accessory_set"
SECONDARY_SOURCE = "source_skygame_data_1_3_4"
OFFICIAL_LINEAGE = "lineage_tgc_support_faq_1356"
SECONDARY_LINEAGE = "lineage_skygame_data_1_3_4"
OFFICIAL_PATH = "data/source/research/tgc-faq-1356-moomintroll-accessory-set.json"
SECONDARY_PATH = "data/source/vendor/skygame-data-1.3.4-items.json"
OFFICIAL_SNAPSHOT_SHA256 = "9C693A39BAC07DB5D455D8A0A65E620B9518F2749AF4FD47480AA764F0F0069F"
SECONDARY_SNAPSHOT_SHA256 = "21CCAD77006C425B27EE9314870BB5BB77E8436459C6DA214ABCB2B0D8329BBB"
AS_OF = "2026-08-17"
SET_ID = "set_moomin_iap"
ITEMS = (
    ("item_moomin_ears", 2330, "Moomintroll Ears", "HairAccessory"),
    ("item_moomin_tail", 2331, "Moomintroll Tail", "Necklace"),
)


def registry_contract() -> dict[str, object]:
    return {
        "cohort_id": "canonical_cohort_moomintroll_accessory_set",
        "evidence_path": "data/review/moomintroll-accessory-set-canonical-evidence.jsonl",
        "snapshot_paths": [OFFICIAL_PATH, SECONDARY_PATH],
        "source_ids": [SECONDARY_SOURCE, OFFICIAL_SOURCE],
        "target_item_ids": sorted(item_id for item_id, *_rest in ITEMS),
        "target_set_ids": [SET_ID],
    }


class MoominEvidenceError(ValueError):
    pass


def sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode()
    return hashlib.sha256(value).hexdigest().upper()


def chash(value: Any) -> str:
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def read(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8", newline="\n")


def safe(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if root.resolve() not in path.parents or not path.is_file():
        raise MoominEvidenceError(f"snapshot unavailable or escapes root: {relative}")
    return path


def ptr(document: Any, locator: str) -> Any:
    if not locator.startswith("/"):
        raise MoominEvidenceError(f"invalid JSON pointer: {locator!r}")
    current = document
    for part in locator[1:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        try:
            current = current[int(part)] if isinstance(current, list) else current[part]
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise MoominEvidenceError(f"unresolved JSON pointer: {locator!r}") from exc
    return current


def evidence_id(target: str, field: str, source: str, locator: str, value: Any) -> str:
    seed = f"{target}\0{field}\0{source}\0{locator}\0{chash(value)}"
    return "canonical_evidence_" + hashlib.sha256(seed.encode()).hexdigest()[:24]


def evidence(target_type: str, target_id: str, field: str, value: Any, source: str, lineage: str, tier: str, path: str, raw: bytes, locator: str, role: str, notes: str = "") -> dict[str, Any]:
    found = ptr(json.loads(raw.decode("utf-8")), locator)
    if found != value:
        raise MoominEvidenceError(f"claim does not equal source locator: {target_id}:{field}")
    return {"evidence_id": evidence_id(target_id, field, source, locator, value), "target_type": target_type, "target_id": target_id, "field_path": field, "claim_value": value, "claim_hash": chash(value), "source_id": source, "source_lineage_id": lineage, "source_tier": tier, "source_snapshot_path": path, "source_snapshot_bytes": len(raw), "source_snapshot_hash": sha(raw), "claim_locator": locator, "claim_locator_hash": chash(found), "evidence_role": role, "review_status": "approved", "reviewed_at": AS_OF, "notes": notes}


def vendor(document: dict[str, Any], vendor_id: int) -> tuple[int, dict[str, Any]]:
    for index, row in enumerate(document.get("items", [])):
        if row.get("id") == vendor_id:
            return index, row
    raise MoominEvidenceError(f"pinned secondary item missing: {vendor_id}")


def item_row(item_id: str, name: str) -> dict[str, Any]:
    return {"item_id": item_id, "canonical_name_zh_tw": f"待確認（{name}）", "canonical_name_en": name, "aliases": [], "item_category": "accessory", "item_subcategory": "collaboration_iap", "source_type": "collaboration", "source_id": OFFICIAL_SOURCE, "season_id": "season_moomin", "event_id": None, "ancestor_id": None, "set_ids": [SET_ID], "free_or_premium": "premium", "pass_required": "unknown", "ultimate_reward": False, "collaboration": True, "permanent_account_item": "unknown", "consumable": False, "original_currency": "USD", "original_cost": "bundle_only", "availability_status": "unknown", "first_release_date": None, "availability_event_ids": ["availability_moomin_faq1356_" + item_id.removeprefix("item_moomin_")], "visual_reference_ids": [], "valuation_role": "collection_structure", "source_ids": [OFFICIAL_SOURCE, SECONDARY_SOURCE], "last_verified_at": AS_OF, "verification_status": "verified", "evidence_tier": "official_with_secondary", "model_feature_status": "excluded_pending_verification", "notes": "FAQ 1356 establishes this historical Moomintroll Accessory Set component, its historical season window, and a pack-level USD price only. The independent pinned vendor snapshot supplies the exact English title and vendor type. The pack price is not allocated to an individual item; current availability, return policy, permanent-account property, formal Traditional Chinese name, and visual identity remain unknown or unasserted."}


def build(root: Path) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    root = root.resolve()
    official_bytes = safe(root, OFFICIAL_PATH).read_bytes()
    secondary_bytes = safe(root, SECONDARY_PATH).read_bytes()
    if sha(official_bytes) != OFFICIAL_SNAPSHOT_SHA256:
        raise MoominEvidenceError("official snapshot hash mismatch")
    if sha(secondary_bytes) != SECONDARY_SNAPSHOT_SHA256:
        raise MoominEvidenceError("secondary snapshot hash mismatch")
    official = json.loads(official_bytes)
    secondary = json.loads(secondary_bytes)
    facts = official.get("facts", {})
    if official.get("source_id") != OFFICIAL_SOURCE or facts.get("pack_description_en") != "Moomintroll Accessory Set" or facts.get("historical_price_usd") != 11.99:
        raise MoominEvidenceError("official pack contract changed")
    descriptions = facts.get("included_component_descriptions_en")
    if descriptions != {"item_moomin_ears": "ear accessory", "item_moomin_tail": "tail accessory"}:
        raise MoominEvidenceError("official component contract changed")
    if (facts.get("historical_window_start_date"), facts.get("historical_window_end_date")) != ("2024-10-14", "2024-12-29"):
        raise MoominEvidenceError("official historical window contract changed")
    items = read(root / "knowledge/items/items.jsonl")
    sets = read(root / "knowledge/sets/item-sets.jsonl")
    sources = read(root / "knowledge/sources/sources.jsonl")
    by_source = {row["source_id"]: row for row in sources}
    for source, source_type, lineage in ((OFFICIAL_SOURCE, "official_support", OFFICIAL_LINEAGE), (SECONDARY_SOURCE, "community_database", SECONDARY_LINEAGE)):
        row = by_source.get(source)
        if row is None or row.get("source_type") != source_type or row.get("source_lineage_id") != lineage:
            raise MoominEvidenceError(f"source registry or lineage mismatch: {source}")
    if SET_ID not in {row["set_id"] for row in sets}:
        raise MoominEvidenceError("canonical Moomin set missing")
    result: list[dict[str, Any]] = []
    for item_id, vendor_id, name, vendor_type in ITEMS:
        index, vendor_row = vendor(secondary, vendor_id)
        if vendor_row.get("name") != name or vendor_row.get("type") != vendor_type:
            raise MoominEvidenceError(f"secondary identity changed: {vendor_id}")
        description = descriptions[item_id]
        description_locator = f"/facts/included_component_descriptions_en/{item_id}"
        result.extend((
            evidence("item", item_id, "identity_description", description, OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, description_locator, "independent_field", "Official component description; not an exact vendor-aligned title."),
            evidence("item", item_id, "set_membership", description, OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, description_locator, "independent_field", "Official component mapped to this canonical set member."),
            evidence("item", item_id, "availability_history", facts["historical_window_start_date"], OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, "/facts/historical_window_start_date", "independent_field", "Historical season-window start only; current availability stays unknown."),
            evidence("item", item_id, "availability_history", facts["historical_window_end_date"], OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, "/facts/historical_window_end_date", "independent_field", "Historical season-window end only; current availability stays unknown."),
            evidence("item", item_id, "canonical_name_en", name, SECONDARY_SOURCE, SECONDARY_LINEAGE, "secondary_reference", SECONDARY_PATH, secondary_bytes, f"/items/{index}/name", "secondary_field"),
            evidence("item", item_id, "vendor_item_type", vendor_type, SECONDARY_SOURCE, SECONDARY_LINEAGE, "secondary_reference", SECONDARY_PATH, secondary_bytes, f"/items/{index}/type", "secondary_field", "Vendor taxonomy is preserved verbatim; the canonical category remains the conservative generic accessory."),
        ))
    result.extend((
        evidence("set", SET_ID, "identity_description", facts["pack_description_en"], OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, "/facts/pack_description_en", "independent_field", "Historical pack label only."),
        evidence("set", SET_ID, "scope_definition", facts["included_component_values"], OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, "/facts/included_component_values", "independent_field", "Two components explicitly stated by FAQ 1356."),
        evidence("set", SET_ID, "historical_pack_price_usd", facts["historical_price_usd"], OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, "/facts/historical_price_usd", "independent_field", "Historical pack price; it is not allocated to individual items."),
    ))
    result.sort(key=lambda row: (row["target_type"], row["target_id"], row["field_path"], row["source_id"], row["claim_locator"]))
    return {"items": items, "sets": sets, "sources": sources}, result


def apply_targets(targets: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    items = {row["item_id"]: dict(row) for row in targets["items"]}
    for item_id, _vendor_id, name, _vendor_type in ITEMS:
        items[item_id] = item_row(item_id, name)
    ordered_items = [items[row["item_id"]] for row in targets["items"]]
    sets = {row["set_id"]: dict(row) for row in targets["sets"]}
    sets[SET_ID] = {"set_id": SET_ID, "canonical_name_zh_tw": "待確認（Moomintroll Accessory Set）", "canonical_name_en": "Moomintroll Accessory Set", "set_type": "collaboration", "required_item_ids": [item_id for item_id, *_rest in ITEMS], "optional_item_ids": [], "source_ids": [OFFICIAL_SOURCE, SECONDARY_SOURCE], "last_verified_at": AS_OF, "verification_status": "verified"}
    return {"items": ordered_items, "sets": [sets[row["set_id"]] for row in targets["sets"]], "sources": targets["sources"]}


def availability_rows() -> list[dict[str, Any]]:
    return [{"availability_id": "availability_moomin_faq1356_" + item_id.removeprefix("item_moomin_"), "item_id": item_id, "availability_status": "limited_time", "start_date": "2024-10-14", "end_date": "2024-12-29", "event_id": None, "source_ids": [OFFICIAL_SOURCE], "last_verified_at": AS_OF, "verification_status": "needs_review"} for item_id, *_rest in ITEMS]


def verify(root: Path, require_applied: bool = True) -> list[str]:
    targets, field_evidence = build(root)
    expected = apply_targets(targets)
    problems: list[str] = []
    if require_applied:
        for relative, rows in (("knowledge/items/items.jsonl", expected["items"]), ("knowledge/sets/item-sets.jsonl", expected["sets"]), ("knowledge/sources/sources.jsonl", expected["sources"])):
            if read(root / relative) != rows:
                problems.append(f"committed target differs from replayable apply contract: {relative}")
        available = {row["availability_id"]: row for row in read(root / "knowledge/acquisition/availability-events.jsonl")}
        for row in availability_rows():
            if available.get(row["availability_id"]) != row:
                problems.append(f"availability differs: {row['availability_id']}")
        evidence_path = root / "data/review/moomintroll-accessory-set-canonical-evidence.jsonl"
        if not evidence_path.is_file() or read(evidence_path) != field_evidence:
            problems.append("canonical field evidence differs from replayable source claims")
        by_id = {row["item_id"]: row for row in expected["items"]}
        for item_id, *_rest in ITEMS:
            row = by_id[item_id]
            if row["availability_status"] != "unknown" or row["permanent_account_item"] != "unknown" or row["original_cost"] != "bundle_only" or row["first_release_date"] is not None or row["model_feature_status"] != "excluded_pending_verification":
                problems.append("unsupported availability, permanence, price allocation, first-release, or model promotion")
                break
        set_row = next(row for row in expected["sets"] if row["set_id"] == SET_ID)
        if set_row["required_item_ids"] != [item_id for item_id, *_rest in ITEMS]:
            problems.append("Moomintroll Accessory Set required members mismatch")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    if args.apply:
        targets, field_evidence = build(root)
        expected = apply_targets(targets)
        write(root / "knowledge/items/items.jsonl", expected["items"])
        write(root / "knowledge/sets/item-sets.jsonl", expected["sets"])
        existing = {row["availability_id"]: row for row in read(root / "knowledge/acquisition/availability-events.jsonl")}
        existing.update({row["availability_id"]: row for row in availability_rows()})
        write(root / "knowledge/acquisition/availability-events.jsonl", sorted(existing.values(), key=lambda row: row["availability_id"]))
        write(root / "data/review/moomintroll-accessory-set-canonical-evidence.jsonl", field_evidence)
    problems = verify(root)
    print(json.dumps({"applied": args.apply, "valid": not problems, "problems": problems, "model_feature_status": "excluded_pending_verification"}, ensure_ascii=False, sort_keys=True))
    raise SystemExit(bool(problems))


if __name__ == "__main__":
    main()
