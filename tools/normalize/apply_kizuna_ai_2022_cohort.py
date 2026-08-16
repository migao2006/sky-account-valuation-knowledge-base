#!/usr/bin/env python3
"""Replay the bounded, offline FAQ 879 Kizuna AI 2022 evidence cohort."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.normalize.apply_moomintroll_accessory_set_cohort import (
    chash, evidence, read, safe, sha, vendor, write,
)

OFFICIAL_SOURCE = "source_tgc_faq_879_kizuna_ai_2022"
SECONDARY_SOURCE = "source_skygame_data_1_3_4"
OFFICIAL_LINEAGE = "lineage_tgc_support_faq_879"
SECONDARY_LINEAGE = "lineage_skygame_data_1_3_4"
OFFICIAL_PATH = "data/source/research/tgc-faq-879-kizuna-ai-2022.json"
SECONDARY_PATH = "data/source/vendor/skygame-data-1.3.4-items.json"
OFFICIAL_SNAPSHOT_SHA256 = "1AEC78EF2CC7FD41843BA70341D431FB3F1F1B57B62E8EAF49510A9B0B2882FD"
SECONDARY_SNAPSHOT_SHA256 = "21CCAD77006C425B27EE9314870BB5BB77E8436459C6DA214ABCB2B0D8329BBB"
AS_OF = "2026-08-17"
SET_ID = "set_kizuna_ai_2022_iap"
RETIRED_ALIAS_IDS = frozenset({"alias_68b82ab9fde5ccbf592d", "alias_a4b7d91fce311e72a71b"})
ITEMS = (
    ("item_kizuna_ai_hair", 1909, "Kizuna AI Hair", "Hair"),
    ("item_kizuna_ai_bow", 1910, "Kizuna AI Bow", "HairAccessory"),
    ("item_kizuna_ai_cape", 1911, "Kizuna AI Cape", "Cape"),
)


class KizunaEvidenceError(ValueError):
    pass


def registry_contract() -> dict[str, object]:
    return {"cohort_id": "canonical_cohort_kizuna_ai_2022", "evidence_path": "data/review/kizuna-ai-2022-canonical-evidence.jsonl", "snapshot_paths": [OFFICIAL_PATH, SECONDARY_PATH], "source_ids": [SECONDARY_SOURCE, OFFICIAL_SOURCE], "target_item_ids": sorted(item_id for item_id, *_ in ITEMS), "target_set_ids": [SET_ID]}


def item_row(item_id: str, name: str, category: str) -> dict[str, Any]:
    return {"item_id": item_id, "canonical_name_zh_tw": f"待確認（{name}）", "canonical_name_en": name, "aliases": [], "item_category": category, "item_subcategory": "collaboration_iap", "source_type": "collaboration", "source_id": OFFICIAL_SOURCE, "season_id": None, "event_id": None, "ancestor_id": None, "set_ids": [SET_ID], "free_or_premium": "unknown", "pass_required": "unknown", "ultimate_reward": False, "collaboration": True, "permanent_account_item": "unknown", "consumable": False, "original_currency": "USD", "original_cost": "bundle_only", "availability_status": "unknown", "first_release_date": None, "availability_event_ids": ["availability_kizuna_ai_faq879_" + item_id.removeprefix("item_kizuna_ai_")], "visual_reference_ids": [], "valuation_role": "collection_structure", "source_ids": [OFFICIAL_SOURCE, SECONDARY_SOURCE], "last_verified_at": AS_OF, "verification_status": "verified", "evidence_tier": "official_with_secondary", "model_feature_status": "excluded_pending_verification", "notes": "FAQ 879 establishes this historical Kizuna AI 2022 component, pack-level USD price, Secret Area context, and event window only. The pinned vendor snapshot supplies the exact English title and vendor type. The pack price is not allocated to an individual item; current availability, return policy, permanent-account property, formal Traditional Chinese name, visual identity, and individual acquisition classification remain unknown or unasserted."}


def build(root: Path) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    root = root.resolve()
    official_bytes, secondary_bytes = safe(root, OFFICIAL_PATH).read_bytes(), safe(root, SECONDARY_PATH).read_bytes()
    if sha(official_bytes) != OFFICIAL_SNAPSHOT_SHA256 or sha(secondary_bytes) != SECONDARY_SNAPSHOT_SHA256:
        raise KizunaEvidenceError("official or secondary snapshot hash mismatch")
    official, secondary = json.loads(official_bytes), json.loads(secondary_bytes)
    facts = official.get("facts", {})
    expected_descriptions = {item_id: description for item_id, description in (("item_kizuna_ai_hair", "hairstyle"), ("item_kizuna_ai_bow", "bow"), ("item_kizuna_ai_cape", "cape"))}
    if official.get("source_id") != OFFICIAL_SOURCE or facts.get("included_component_descriptions_en") != expected_descriptions or facts.get("historical_price_usd") != 19.99 or (facts.get("historical_window_start_date"), facts.get("historical_window_end_date")) != ("2022-02-25", "2022-03-10") or facts.get("historical_location_en") != "Secret Area" or facts.get("bow_free_spell") != "The bow is available as a free spell.":
        raise KizunaEvidenceError("official FAQ 879 contract changed")
    targets = {name: read(root / path) for name, path in (("items", "knowledge/items/items.jsonl"), ("sets", "knowledge/sets/item-sets.jsonl"), ("sources", "knowledge/sources/sources.jsonl"), ("aliases", "knowledge/aliases/item-aliases.jsonl"))}
    by_source = {row["source_id"]: row for row in targets["sources"]}
    for source, source_type, lineage in ((OFFICIAL_SOURCE, "official_support", OFFICIAL_LINEAGE), (SECONDARY_SOURCE, "community_database", SECONDARY_LINEAGE)):
        row = by_source.get(source)
        if row is None or row.get("source_type") != source_type or row.get("source_lineage_id") != lineage:
            raise KizunaEvidenceError(f"source registry or lineage mismatch: {source}")
    if SET_ID not in {row["set_id"] for row in targets["sets"]}:
        raise KizunaEvidenceError("canonical Kizuna set missing")
    result: list[dict[str, Any]] = []
    categories = {"item_kizuna_ai_hair": "hair", "item_kizuna_ai_bow": "accessory", "item_kizuna_ai_cape": "cape"}
    for item_id, vendor_id, name, vendor_type in ITEMS:
        index, vrow = vendor(secondary, vendor_id)
        if vrow.get("name") != name or vrow.get("type") != vendor_type:
            raise KizunaEvidenceError(f"secondary identity changed: {vendor_id}")
        desc, locator = facts["included_component_descriptions_en"][item_id], f"/facts/included_component_descriptions_en/{item_id}"
        result.extend((
            evidence("item", item_id, "identity_description", desc, OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, locator, "independent_field", "Official component description; not an exact vendor-aligned title."),
            evidence("item", item_id, "set_membership", desc, OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, locator, "independent_field"),
            evidence("item", item_id, "availability_history", facts["historical_window_start_date"], OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, "/facts/historical_window_start_date", "independent_field", "Historical window start only; current availability stays unknown."),
            evidence("item", item_id, "availability_history", facts["historical_window_end_date"], OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, "/facts/historical_window_end_date", "independent_field", "Historical window end only; current availability stays unknown."),
            evidence("item", item_id, "canonical_name_en", name, SECONDARY_SOURCE, SECONDARY_LINEAGE, "secondary_reference", SECONDARY_PATH, secondary_bytes, f"/items/{index}/name", "secondary_field"),
            evidence("item", item_id, "vendor_item_type", vendor_type, SECONDARY_SOURCE, SECONDARY_LINEAGE, "secondary_reference", SECONDARY_PATH, secondary_bytes, f"/items/{index}/type", "secondary_field"),
        ))
    result.extend((
        evidence("set", SET_ID, "scope_definition", facts["included_component_values"], OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, "/facts/included_component_values", "independent_field"),
        evidence("set", SET_ID, "historical_pack_price_usd", facts["historical_price_usd"], OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, "/facts/historical_price_usd", "independent_field", "Historical pack price; it is not allocated to individual items."),
        evidence("set", SET_ID, "availability_history", facts["historical_location_en"], OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, "/facts/historical_location_en", "independent_field", "Historical location context only."),
        evidence("item", "item_kizuna_ai_bow", "identity_description", facts["bow_free_spell"], OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, "/facts/bow_free_spell", "independent_field", "Spell availability is not an ownership, price, or current-availability assertion."),
    ))
    result.sort(key=lambda row: (row["target_type"], row["target_id"], row["field_path"], row["source_id"], row["claim_locator"]))
    return targets, result


def apply_targets(targets: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    items = {row["item_id"]: dict(row) for row in targets["items"]}
    categories = {"item_kizuna_ai_hair": "hair", "item_kizuna_ai_bow": "accessory", "item_kizuna_ai_cape": "cape"}
    for item_id, _vendor_id, name, _type in ITEMS:
        items[item_id] = item_row(item_id, name, categories[item_id])
    sets = {row["set_id"]: dict(row) for row in targets["sets"]}
    sets[SET_ID] = {"set_id": SET_ID, "canonical_name_zh_tw": "待確認（Kizuna AI 2022 FAQ 879 範圍）", "canonical_name_en": "Kizuna AI 2022 FAQ 879 scope", "set_type": "collaboration", "required_item_ids": [item_id for item_id, *_ in ITEMS], "optional_item_ids": [], "source_ids": [OFFICIAL_SOURCE, SECONDARY_SOURCE], "last_verified_at": AS_OF, "verification_status": "verified"}
    ordered_item_ids = [row["item_id"] for row in targets["items"]]
    ordered_item_ids.extend(item_id for item_id, *_ in ITEMS if item_id not in ordered_item_ids)
    ordered_set_ids = [row["set_id"] for row in targets["sets"]]
    if SET_ID not in ordered_set_ids: ordered_set_ids.append(SET_ID)
    aliases = [row for row in targets["aliases"] if row.get("alias_id") not in RETIRED_ALIAS_IDS]
    return {"items": [items[item_id] for item_id in ordered_item_ids], "sets": [sets[set_id] for set_id in ordered_set_ids], "sources": targets["sources"], "aliases": aliases}


def availability_rows() -> list[dict[str, Any]]:
    return [{"availability_id": "availability_kizuna_ai_faq879_" + item_id.removeprefix("item_kizuna_ai_"), "item_id": item_id, "availability_status": "limited_time", "start_date": "2022-02-25", "end_date": "2022-03-10", "event_id": None, "source_ids": [OFFICIAL_SOURCE], "last_verified_at": AS_OF, "verification_status": "needs_review"} for item_id, *_ in ITEMS]


def verify(root: Path, require_applied: bool = True) -> list[str]:
    targets, ledger = build(root)
    expected = apply_targets(targets)
    problems: list[str] = []
    if require_applied:
        for relative, rows in (("knowledge/items/items.jsonl", expected["items"]), ("knowledge/sets/item-sets.jsonl", expected["sets"]), ("knowledge/aliases/item-aliases.jsonl", expected["aliases"])):
            if read(root / relative) != rows: problems.append(f"committed target differs from replayable apply contract: {relative}")
        available = {row["availability_id"]: row for row in read(root / "knowledge/acquisition/availability-events.jsonl")}
        for row in availability_rows():
            if available.get(row["availability_id"]) != row: problems.append(f"availability differs: {row['availability_id']}")
        path = root / "data/review/kizuna-ai-2022-canonical-evidence.jsonl"
        if not path.is_file() or read(path) != ledger: problems.append("canonical field evidence differs from replayable source claims")
        for item_id, *_ in ITEMS:
            item = next(row for row in expected["items"] if row["item_id"] == item_id)
            if item["availability_status"] != "unknown" or item["permanent_account_item"] != "unknown" or item["original_cost"] != "bundle_only" or item["first_release_date"] is not None or item["model_feature_status"] != "excluded_pending_verification": problems.append("unsupported availability, permanence, price allocation, first-release, or model promotion"); break
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2]); parser.add_argument("--apply", action="store_true"); args = parser.parse_args(); root = args.root.resolve()
    if args.apply:
        targets, ledger = build(root); expected = apply_targets(targets)
        write(root / "knowledge/items/items.jsonl", expected["items"]); write(root / "knowledge/sets/item-sets.jsonl", expected["sets"]); write(root / "knowledge/aliases/item-aliases.jsonl", expected["aliases"])
        available = {row["availability_id"]: row for row in read(root / "knowledge/acquisition/availability-events.jsonl")}; available.update({row["availability_id"]: row for row in availability_rows()}); write(root / "knowledge/acquisition/availability-events.jsonl", sorted(available.values(), key=lambda row: row["availability_id"]))
        write(root / "data/review/kizuna-ai-2022-canonical-evidence.jsonl", ledger)
    problems = verify(root); print(json.dumps({"applied": args.apply, "valid": not problems, "problems": problems, "model_feature_status": "excluded_pending_verification"}, ensure_ascii=False, sort_keys=True)); raise SystemExit(bool(problems))


if __name__ == "__main__": main()
