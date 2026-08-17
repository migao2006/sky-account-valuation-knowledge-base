#!/usr/bin/env python3
"""Replay the bounded FAQ 1374 Days of Love 2025 core-four cohort offline."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.modeling.canonical_english_eligibility import declared_model_feature_status
from tools.normalize.apply_moomintroll_accessory_set_cohort import evidence, read, safe, sha, vendor, write

OFFICIAL_SOURCE = "source_tgc_faq_1374_days_of_love_core_four"
SECONDARY_SOURCE = "source_skygame_data_1_3_4"
OFFICIAL_LINEAGE = "lineage_tgc_support_faq_1374"
SECONDARY_LINEAGE = "lineage_skygame_data_1_3_4"
OFFICIAL_PATH = "data/source/research/tgc-faq-1374-days-of-love-core-four.json"
SECONDARY_PATH = "data/source/vendor/skygame-data-1.3.4-items.json"
OFFICIAL_SHA = "99577363EA4425B809AA5D623D6E3E583BB09CE161BADC42B1304A5FD0601863"
SECONDARY_SHA = "21CCAD77006C425B27EE9314870BB5BB77E8436459C6DA214ABCB2B0D8329BBB"
AS_OF = "2026-08-17"

# Canonical id, vendor numeric id/GUID/title/type, FAQ exact title, category, cost.
ITEMS = (
    ("item_days_of_love_violet_crystal_prop", 2518, "MV5iUIEMMH", "Days Of Love Violet Crystal Prop", "Prop", "Days of Love Violet Crystal Prop", "prop", "event_currency", 14),
    ("item_days_of_love_braids", 2519, "V0Y7dn2l4H", "Days Of Love Braids", "Hair", "Days of Love Braids", "hair", "event_currency", 35),
    ("item_days_of_love_amethyst_accessory", 2517, "-ZIWymGtlX", "Days Of Love Amethyst Accessory", "HairAccessory", "Days of Love Amethyst Accessory", "accessory", "USD", 2.99),
    ("item_days_of_love_amethyst_tipped_tails", 2516, "Yxt4jz3je6", "Days Of Love Amethyst-Tipped Tails", "Hair", "Days of Love Amethyst-Tipped Tails hairstyle", "hair", "USD", 6.99),
)
SOURCE_ROW = {
    "source_id": OFFICIAL_SOURCE,
    "source_name": "thatgamecompany Help Center FAQ 1374 — Patch Notes, January 16, 2025 (Days of Love 2025)",
    "source_type": "official_support",
    "url": "https://thatgamecompany.helpshift.com/hc/en/17-sky-children-of-the-light/faq/1374-patch-notes---january-16-2025---0-28-0-308028-android-huawei-ios-playstation-steam-switch/",
    "retrieved_at": AS_OF,
    "evidence_level": "official_explicit",
    "source_lineage_id": OFFICIAL_LINEAGE,
    "notes": "Fact-limited locally pinned transcription: Days of Love 2025 historical window and four named new-item costs only. It does not establish current availability, return policy, permanent ownership, images, formal Traditional Chinese names, visual matches, first release dates, or a complete Days of Love catalog.",
}


class DaysOfLoveEvidenceError(ValueError):
    pass


def registry_contract() -> dict[str, object]:
    return {"cohort_id": "canonical_cohort_days_of_love_faq1374_core_four", "evidence_path": "data/review/days-of-love-faq1374-core-four-canonical-evidence.jsonl", "snapshot_paths": [OFFICIAL_PATH, SECONDARY_PATH], "source_ids": [SECONDARY_SOURCE, OFFICIAL_SOURCE], "target_item_ids": sorted(row[0] for row in ITEMS), "target_set_ids": []}


def source_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    indexed = {row["source_id"]: dict(row) for row in rows}
    if indexed.get(OFFICIAL_SOURCE) not in (None, SOURCE_ROW):
        raise DaysOfLoveEvidenceError("official source registry conflicts with cohort contract")
    indexed[OFFICIAL_SOURCE] = SOURCE_ROW
    ordered = [row["source_id"] for row in rows]
    if OFFICIAL_SOURCE not in ordered:
        ordered.append(OFFICIAL_SOURCE)
    return [indexed[source_id] for source_id in ordered]


def valid_title_relation(official_name: str, vendor_name: str) -> bool:
    """Only four FAQ/vendor title pairs are allowed; no generic normalization."""
    return (official_name, vendor_name) in {
        ("Days of Love Violet Crystal Prop", "Days Of Love Violet Crystal Prop"),
        ("Days of Love Braids", "Days Of Love Braids"),
        ("Days of Love Amethyst Accessory", "Days Of Love Amethyst Accessory"),
        ("Days of Love Amethyst-Tipped Tails hairstyle", "Days Of Love Amethyst-Tipped Tails"),
    }


def item_row(item_id: str, official_name: str, category: str, currency: str, cost: int | float) -> dict[str, Any]:
    return {
        "item_id": item_id, "canonical_name_zh_tw": f"待確認（{official_name}）", "canonical_name_en": official_name, "aliases": [],
        "item_category": category, "item_subcategory": "days_of_love_2025_historical_item", "source_type": "event", "source_id": OFFICIAL_SOURCE,
        "season_id": None, "event_id": None, "ancestor_id": None, "set_ids": [], "free_or_premium": "unknown", "pass_required": "unknown",
        "ultimate_reward": False, "collaboration": False, "permanent_account_item": "unknown", "consumable": False,
        "original_currency": currency, "original_cost": cost, "availability_status": "unknown", "first_release_date": None,
        "availability_event_ids": ["availability_days_of_love_faq1374_" + item_id.removeprefix("item_days_of_love_")], "visual_reference_ids": [],
        "valuation_role": "collection_structure", "source_ids": [OFFICIAL_SOURCE, SECONDARY_SOURCE], "last_verified_at": AS_OF,
        "verification_status": "verified", "evidence_tier": "official_with_secondary", "model_feature_status": declared_model_feature_status(item_id),
        "notes": "FAQ 1374 establishes this named Days of Love 2025 historical offer and event window only; the pinned vendor snapshot independently supplies exact vendor ID, GUID, title, and type. Current availability, return policy, permanent-account property, formal Traditional Chinese name, visual identity, first release date, and model eligibility remain unknown or unasserted. This is a bounded four-item FAQ slice, not a bundle or complete Days of Love catalog.",
    }


def build(root: Path) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    root = root.resolve()
    official_bytes, secondary_bytes = safe(root, OFFICIAL_PATH).read_bytes(), safe(root, SECONDARY_PATH).read_bytes()
    if sha(official_bytes) != OFFICIAL_SHA or sha(secondary_bytes) != SECONDARY_SHA:
        raise DaysOfLoveEvidenceError("official or secondary snapshot hash mismatch")
    official, secondary = json.loads(official_bytes), json.loads(secondary_bytes)
    expected_facts = [{"item_id": item_id, "official_name_en": official_name, "original_currency": currency, "original_cost": cost} for item_id, _vendor_id, _guid, _vendor_name, _vendor_type, official_name, _category, currency, cost in ITEMS]
    facts = official.get("facts", {})
    if official.get("source_id") != OFFICIAL_SOURCE or facts.get("new_items") != expected_facts or (facts.get("historical_window_start_date"), facts.get("historical_window_end_date")) != ("2025-02-10", "2025-02-23"):
        raise DaysOfLoveEvidenceError("official FAQ 1374 contract changed")
    targets = {key: read(root / path) for key, path in (("items", "knowledge/items/items.jsonl"), ("sources", "knowledge/sources/sources.jsonl"))}
    sources = {row["source_id"]: row for row in source_rows(targets["sources"])}
    for source_id, source_type, lineage in ((OFFICIAL_SOURCE, "official_support", OFFICIAL_LINEAGE), (SECONDARY_SOURCE, "community_database", SECONDARY_LINEAGE)):
        if sources.get(source_id, {}).get("source_type") != source_type or sources[source_id].get("source_lineage_id") != lineage:
            raise DaysOfLoveEvidenceError("source registry or lineage mismatch: " + source_id)
    ledger: list[dict[str, Any]] = []
    for index, (item_id, vendor_id, vendor_guid, vendor_name, vendor_type, official_name, category, currency, cost) in enumerate(ITEMS):
        vendor_index, vendor_row = vendor(secondary, vendor_id)
        if (vendor_row.get("guid"), vendor_row.get("name"), vendor_row.get("type")) != (vendor_guid, vendor_name, vendor_type):
            raise DaysOfLoveEvidenceError("secondary identity changed: " + str(vendor_id))
        if not valid_title_relation(official_name, vendor_name):
            raise DaysOfLoveEvidenceError("unsupported official/vendor title relation: " + str(vendor_id))
        path = f"/facts/new_items/{index}"
        note = "Historical FAQ cost/window only; no current availability, permanence, or model eligibility is inferred."
        ledger.extend((
            evidence("item", item_id, "canonical_name_en", official_name, OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, path + "/official_name_en", "independent_identity", "FAQ exact title; only this explicit FAQ/vendor title pair is allowed."),
            evidence("item", item_id, "original_currency", currency, OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, path + "/original_currency", "independent_field", note),
            evidence("item", item_id, "original_cost", cost, OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, path + "/original_cost", "independent_field", note),
            evidence("item", item_id, "availability_history", facts["historical_window_start_date"], OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, "/facts/historical_window_start_date", "independent_field", note),
            evidence("item", item_id, "availability_history", facts["historical_window_end_date"], OFFICIAL_SOURCE, OFFICIAL_LINEAGE, "official_item_specific", OFFICIAL_PATH, official_bytes, "/facts/historical_window_end_date", "independent_field", note),
            evidence("item", item_id, "vendor_item_name", vendor_name, SECONDARY_SOURCE, SECONDARY_LINEAGE, "secondary_reference", SECONDARY_PATH, secondary_bytes, f"/items/{vendor_index}/name", "secondary_field", "Pinned vendor spelling; title reconciliation is limited by this apply contract."),
            evidence("item", item_id, "vendor_item_type", vendor_type, SECONDARY_SOURCE, SECONDARY_LINEAGE, "secondary_reference", SECONDARY_PATH, secondary_bytes, f"/items/{vendor_index}/type", "secondary_field", f"Apply contract maps vendor type to canonical category {category}."),
            evidence("item", item_id, "vendor_item_guid", vendor_guid, SECONDARY_SOURCE, SECONDARY_LINEAGE, "secondary_reference", SECONDARY_PATH, secondary_bytes, f"/items/{vendor_index}/guid", "secondary_field", "Pinned vendor GUID is an identity guard, not a model feature."),
        ))
    ledger.sort(key=lambda row: (row["target_type"], row["target_id"], row["field_path"], row["source_id"], row["claim_locator"]))
    return targets, ledger


def apply_targets(targets: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    items = {row["item_id"]: dict(row) for row in targets["items"]}
    order = [row["item_id"] for row in targets["items"]]
    for item_id, _vendor_id, _guid, _vendor_name, _vendor_type, official_name, category, currency, cost in ITEMS:
        items[item_id] = item_row(item_id, official_name, category, currency, cost)
        if item_id not in order:
            order.append(item_id)
    return {"items": [items[item_id] for item_id in order], "sources": source_rows(targets["sources"])}


def availability_rows() -> list[dict[str, Any]]:
    return [{"availability_id": "availability_days_of_love_faq1374_" + item_id.removeprefix("item_days_of_love_"), "item_id": item_id, "availability_status": "limited_time", "start_date": "2025-02-10", "end_date": "2025-02-23", "event_id": None, "source_ids": [OFFICIAL_SOURCE], "last_verified_at": AS_OF, "verification_status": "verified"} for item_id, *_ in ITEMS]


def verify(root: Path, require_applied: bool = True) -> list[str]:
    targets, ledger = build(root); expected = apply_targets(targets); problems: list[str] = []
    if require_applied:
        for path, key in (("knowledge/items/items.jsonl", "items"), ("knowledge/sources/sources.jsonl", "sources")):
            if read(root / path) != expected[key]: problems.append("committed target differs from replayable apply contract: " + path)
        available = {row["availability_id"]: row for row in read(root / "knowledge/acquisition/availability-events.jsonl")}
        for row in availability_rows():
            if available.get(row["availability_id"]) != row: problems.append("availability differs: " + row["availability_id"])
        ledger_path = root / "data/review/days-of-love-faq1374-core-four-canonical-evidence.jsonl"
        if not ledger_path.is_file() or read(ledger_path) != ledger: problems.append("canonical field evidence differs from replayable source claims")
        for item_id, *_ in ITEMS:
            item = next(row for row in expected["items"] if row["item_id"] == item_id)
            if (item["availability_status"], item["permanent_account_item"], item["first_release_date"], item["model_feature_status"], item["set_ids"], item["visual_reference_ids"]) != ("unknown", "unknown", None, declared_model_feature_status(item_id), [], []):
                problems.append("unsupported availability, permanence, first-release, visual, model promotion, or bundle membership"); break
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, default=ROOT); parser.add_argument("--apply", action="store_true"); args = parser.parse_args(); root = args.root.resolve()
    if args.apply:
        targets, ledger = build(root); output = apply_targets(targets)
        for path, key in (("knowledge/items/items.jsonl", "items"), ("knowledge/sources/sources.jsonl", "sources")): write(root / path, output[key])
        available = {row["availability_id"]: row for row in read(root / "knowledge/acquisition/availability-events.jsonl")}; available.update({row["availability_id"]: row for row in availability_rows()}); write(root / "knowledge/acquisition/availability-events.jsonl", sorted(available.values(), key=lambda row: row["availability_id"]))
        write(root / "data/review/days-of-love-faq1374-core-four-canonical-evidence.jsonl", ledger)
    problems = verify(root); print(json.dumps({"applied": args.apply, "valid": not problems, "problems": problems}, sort_keys=True)); raise SystemExit(bool(problems))


if __name__ == "__main__":
    main()
