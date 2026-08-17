#!/usr/bin/env python3
"""Replay the bounded, offline FAQ 1330 SkyFest core-five evidence cohort.

The cohort deliberately excludes the Anniversary Headband and creates no set:
FAQ 1330 proves a five-item slice, not a complete SkyFest bundle/catalog.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.normalize.apply_moomintroll_accessory_set_cohort import chash, evidence, read, safe, sha, vendor, write

OFFICIAL_SOURCE = "source_tgc_faq_1330_skyfest_core_five"
SECONDARY_SOURCE = "source_skygame_data_1_3_4"
OFFICIAL_LINEAGE = "lineage_tgc_support_faq_1330"
SECONDARY_LINEAGE = "lineage_skygame_data_1_3_4"
OFFICIAL_PATH = "data/source/research/tgc-faq-1330-skyfest-core-five.json"
SECONDARY_PATH = "data/source/vendor/skygame-data-1.3.4-items.json"
OFFICIAL_SNAPSHOT_SHA256 = "0C92B8322133645C770EB06C5BFF8E1B05114CE53038DF97A8AFB221EBB24264"
SECONDARY_SNAPSHOT_SHA256 = "21CCAD77006C425B27EE9314870BB5BB77E8436459C6DA214ABCB2B0D8329BBB"
AS_OF = "2026-08-17"

# item id, pinned vendor id, FAQ title, vendor title, canonical category, vendor type, currency, historical cost
ITEMS = (
    ("item_skyfest_jenova_fan", 2234, "SkyFest Jenova Fan", "Skyfest Jenova Fan", "prop", "Held", "event_currency", 7),
    ("item_skyfest_5th_anniversary_tshirt", 2233, "SkyFest 5th Anniversary T-shirt", "Skyfest 5th Anniversary T-Shirt", "outfit", "Outfit", "event_currency", 10),
    ("item_skyfest_star_jar", 2232, "SkyFest Star Jar", "Skyfest Star Jar", "prop", "Prop", "event_currency", 15),
    ("item_skyfest_oreo_headband", 2230, "SkyFest Oreo Headband", "Skyfest Oreo Headband", "accessory", "HairAccessory", "USD", 4.99),
    ("item_skyfest_wireframe_cape", 2229, "SkyFest Wireframe Cape", "Skyfest Wireframe Cape", "cape", "Cape", "USD", 19.99),
)
NUMBERED_ITEM_IDS = frozenset({"item_skyfest_5th_anniversary_tshirt", "item_skyfest_wireframe_cape"})


class SkyFestEvidenceError(ValueError):
    pass


def registry_contract() -> dict[str, object]:
    return {
        "cohort_id": "canonical_cohort_skyfest_faq1330_core_five",
        "evidence_path": "data/review/skyfest-faq1330-core-five-canonical-evidence.jsonl",
        "snapshot_paths": [OFFICIAL_PATH, SECONDARY_PATH],
        "source_ids": [SECONDARY_SOURCE, OFFICIAL_SOURCE],
        "target_item_ids": sorted(item_id for item_id, *_ in ITEMS),
        "target_set_ids": [],
    }


def item_row(item_id: str, name: str, category: str, currency: str, cost: int | float) -> dict[str, Any]:
    return {
        "item_id": item_id, "canonical_name_zh_tw": f"待確認（{name}）", "canonical_name_en": name,
        "aliases": [], "item_category": category, "item_subcategory": "skyfest_2024_historical_item",
        "source_type": "event", "source_id": OFFICIAL_SOURCE, "season_id": None, "event_id": None,
        "ancestor_id": None, "set_ids": [], "free_or_premium": "unknown", "pass_required": "unknown",
        "ultimate_reward": False, "collaboration": False, "permanent_account_item": "unknown", "consumable": False,
        "original_currency": currency, "original_cost": cost, "availability_status": "unknown", "first_release_date": None,
        "availability_event_ids": ["availability_skyfest_faq1330_" + item_id.removeprefix("item_skyfest_")],
        "visual_reference_ids": [], "valuation_role": "collection_structure", "source_ids": [OFFICIAL_SOURCE, SECONDARY_SOURCE],
        "last_verified_at": AS_OF, "verification_status": "verified", "evidence_tier": "official_with_secondary",
        "model_feature_status": "excluded_pending_verification",
        "notes": "FAQ 1330 establishes this named SkyFest 2024 new item's historical cost and event window only; the pinned vendor snapshot independently supplies title spelling and vendor type. Current availability, return policy, permanent-account property, formal Traditional Chinese name, visual identity, and model eligibility remain unknown or unasserted. This is a bounded five-item FAQ slice, not a bundle or complete SkyFest catalog.",
    }


def build(root: Path) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    root = root.resolve()
    official_bytes, secondary_bytes = safe(root, OFFICIAL_PATH).read_bytes(), safe(root, SECONDARY_PATH).read_bytes()
    if sha(official_bytes) != OFFICIAL_SNAPSHOT_SHA256 or sha(secondary_bytes) != SECONDARY_SNAPSHOT_SHA256:
        raise SkyFestEvidenceError("official or secondary snapshot hash mismatch")
    official, secondary = json.loads(official_bytes), json.loads(secondary_bytes)
    expected_facts = [{"item_id": item_id, "official_name_en": name, "original_currency": currency, "original_cost": cost} for item_id, _vendor_id, name, _vendor_name, _category, _vendor_type, currency, cost in ITEMS]
    facts = official.get("facts", {})
    if (official.get("source_id") != OFFICIAL_SOURCE or facts.get("new_items") != expected_facts
            or (facts.get("historical_window_start_date"), facts.get("historical_window_end_date")) != ("2024-07-12", "2024-07-26")
            or facts.get("numbered_items_scheduled_only_this_year") != ["item_skyfest_5th_anniversary_tshirt", "item_skyfest_wireframe_cape"]):
        raise SkyFestEvidenceError("official FAQ 1330 contract changed")
    targets = {name: read(root / path) for name, path in (("items", "knowledge/items/items.jsonl"), ("sources", "knowledge/sources/sources.jsonl"))}
    sources = {row["source_id"]: row for row in targets["sources"]}
    for source_id, source_type, lineage in ((OFFICIAL_SOURCE, "official_support", OFFICIAL_LINEAGE), (SECONDARY_SOURCE, "community_database", SECONDARY_LINEAGE)):
        source = sources.get(source_id)
        if source is None or source.get("source_type") != source_type or source.get("source_lineage_id") != lineage:
            raise SkyFestEvidenceError(f"source registry or lineage mismatch: {source_id}")
    ledger: list[dict[str, Any]] = []
    for fact_index, (item_id, vendor_id, official_name, vendor_name, category, vendor_type, currency, cost) in enumerate(ITEMS):
        vendor_index, vendor_row = vendor(secondary, vendor_id)
        if vendor_row.get("name") != vendor_name or vendor_row.get("type") != vendor_type:
            raise SkyFestEvidenceError(f"secondary identity changed: {vendor_id}")
        if vendor_name.casefold() != official_name.casefold():
            raise SkyFestEvidenceError(f"official and secondary identity no longer casefold-match: {vendor_id}")
        prefix = f"/facts/new_items/{fact_index}"
        ledger.extend((
            evidence("item", item_id, "canonical_name_en", official_name, OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, prefix + "/official_name_en", "independent_identity", "FAQ 1330 exact item wording; vendor spelling is retained separately."),
            evidence("item", item_id, "original_currency", currency, OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, prefix + "/original_currency", "independent_field", "Historical FAQ currency only; no current storefront state is inferred."),
            evidence("item", item_id, "original_cost", cost, OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, prefix + "/original_cost", "independent_field", "Historical FAQ cost only; no current price is inferred."),
            evidence("item", item_id, "availability_history", facts["historical_window_start_date"], OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, "/facts/historical_window_start_date", "independent_field", "Historical SkyFest window start only; current availability stays unknown."),
            evidence("item", item_id, "availability_history", facts["historical_window_end_date"], OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, "/facts/historical_window_end_date", "independent_field", "Historical SkyFest window end only; current availability stays unknown."),
            evidence("item", item_id, "vendor_item_name", vendor_name, SECONDARY_SOURCE, SECONDARY_LINEAGE, "secondary_reference", SECONDARY_PATH, secondary_bytes, f"/items/{vendor_index}/name", "secondary_field", "Pinned vendor spelling casefold-matches the official identity; FAQ 1330 alone controls canonical title spelling."),
            evidence("item", item_id, "vendor_item_type", vendor_type, SECONDARY_SOURCE, SECONDARY_LINEAGE, "secondary_reference", SECONDARY_PATH, secondary_bytes, f"/items/{vendor_index}/type", "secondary_field", f"Apply contract maps this vendor type to canonical category {category}."),
        ))
        if item_id in NUMBERED_ITEM_IDS:
            numbered_index = facts["numbered_items_scheduled_only_this_year"].index(item_id)
            ledger.append(evidence("item", item_id, "identity_description", item_id, OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, f"/facts/numbered_items_scheduled_only_this_year/{numbered_index}", "independent_field", "FAQ historical numbered-item statement only; it does not set current availability, permanence, or return policy."))
    ledger.sort(key=lambda row: (row["target_type"], row["target_id"], row["field_path"], row["source_id"], row["claim_locator"]))
    return targets, ledger


def apply_targets(targets: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    items = {row["item_id"]: dict(row) for row in targets["items"]}
    for item_id, _vendor_id, name, _vendor_name, category, _vendor_type, currency, cost in ITEMS:
        items[item_id] = item_row(item_id, name, category, currency, cost)
    ordered_ids = [row["item_id"] for row in targets["items"]]
    ordered_ids.extend(item_id for item_id, *_ in ITEMS if item_id not in ordered_ids)
    return {"items": [items[item_id] for item_id in ordered_ids], "sources": targets["sources"]}


def availability_rows() -> list[dict[str, Any]]:
    return [{"availability_id": "availability_skyfest_faq1330_" + item_id.removeprefix("item_skyfest_"), "item_id": item_id, "availability_status": "limited_time", "start_date": "2024-07-12", "end_date": "2024-07-26", "event_id": None, "source_ids": [OFFICIAL_SOURCE], "last_verified_at": AS_OF, "verification_status": "verified"} for item_id, *_ in ITEMS]


def verify(root: Path, require_applied: bool = True) -> list[str]:
    targets, ledger = build(root)
    expected = apply_targets(targets)
    problems: list[str] = []
    if require_applied:
        if read(root / "knowledge/items/items.jsonl") != expected["items"]:
            problems.append("committed target differs from replayable apply contract: knowledge/items/items.jsonl")
        available = {row["availability_id"]: row for row in read(root / "knowledge/acquisition/availability-events.jsonl")}
        for row in availability_rows():
            if available.get(row["availability_id"]) != row:
                problems.append(f"availability differs: {row['availability_id']}")
        ledger_path = root / "data/review/skyfest-faq1330-core-five-canonical-evidence.jsonl"
        if not ledger_path.is_file() or read(ledger_path) != ledger:
            problems.append("canonical field evidence differs from replayable source claims")
        for item_id, *_ in ITEMS:
            item = next(row for row in expected["items"] if row["item_id"] == item_id)
            if item["availability_status"] != "unknown" or item["permanent_account_item"] != "unknown" or item["first_release_date"] is not None or item["model_feature_status"] != "excluded_pending_verification" or item["set_ids"]:
                problems.append("unsupported availability, permanence, first-release, model promotion, or bundle membership")
                break
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2]); parser.add_argument("--apply", action="store_true"); args = parser.parse_args(); root = args.root.resolve()
    if args.apply:
        targets, ledger = build(root); expected = apply_targets(targets)
        write(root / "knowledge/items/items.jsonl", expected["items"])
        available = {row["availability_id"]: row for row in read(root / "knowledge/acquisition/availability-events.jsonl")}; available.update({row["availability_id"]: row for row in availability_rows()})
        write(root / "knowledge/acquisition/availability-events.jsonl", sorted(available.values(), key=lambda row: row["availability_id"]))
        write(root / "data/review/skyfest-faq1330-core-five-canonical-evidence.jsonl", ledger)
    problems = verify(root); print(json.dumps({"applied": args.apply, "valid": not problems, "problems": problems, "model_feature_status": "excluded_pending_verification"}, ensure_ascii=False, sort_keys=True)); raise SystemExit(bool(problems))


if __name__ == "__main__":
    main()
