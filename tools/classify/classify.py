#!/usr/bin/env python3
"""Conservative offline conversion of *structured* claims into valuation input."""
from __future__ import annotations
import argparse
import json
import re
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
KNOWN = {"complete", "partial", "owned_not_complete", "confirmed_missing", "unknown"}
EVIDENCE = {"image_confirmed", "text_claim", "unknown", "conflict"}
PASS = {"yes", "no", "unknown"}
PLATFORM = {"google", "apple", "facebook", "nintendo", "playstation", "steam", "huawei", "twitter", "other"}
PLATFORM_STATUS = {"available", "unavailable", "mentioned_unknown", "unknown", "high_risk"}
CURRENCIES = {"TWD", "CNY", "RM", "unknown"}
SERVERS = {"international", "unknown"}
OFFER_KINDS = {"seller_listing", "buyer_budget", "service", "exchange", "unknown"}
ENTITY_KINDS = {"single_account", "bundle", "service", "unknown"}
PRICE_TYPES = {"normal_listing", "urgent_sale", "last_public_price", "verified_sale", "unknown"}
PRICE_TYPE_ALIASES = {"asking": "normal_listing", "normal_listing": "normal_listing", "reduced": "urgent_sale", "instant": "urgent_sale", "quick_sale": "urgent_sale", "urgent_sale": "urgent_sale", "sold_claim": "last_public_price", "sold_last_ask": "last_public_price", "sold_explicit": "last_public_price", "last_public_price": "last_public_price"}

def _canonical_ids(kind: str) -> set[str]:
    names = {"item": "items/items.jsonl", "season": "seasons/seasons.jsonl", "set": "sets/item-sets.jsonl"}
    return {row[f"{kind}_id"] for line in (ROOT / "knowledge" / names[kind]).read_text(encoding="utf-8").splitlines() if line.strip() for row in [json.loads(line)]}

def _id_list(values: Any, kind: str, canonical: set[str], field: str) -> list[str]:
    if values is None: return []
    if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
        raise ValueError(f"{field} must be a list of canonical {kind} IDs")
    unknown = sorted(set(values) - canonical)
    if unknown: raise ValueError(f"{field} contains unknown canonical {kind} ID(s): {', '.join(unknown)}")
    return list(dict.fromkeys(values))

def _enum(value: Any, allowed: set[str], default: str = "unknown") -> str:
    return value if isinstance(value, str) and value in allowed else default

def _trade_conditions(claims: dict[str, Any]) -> dict[str, str]:
    """Normalize structured market assertions without upgrading a sale assertion."""
    raw = claims.get("trade_conditions")
    raw = raw if isinstance(raw, dict) else {}
    price = raw.get("price_type")
    # verified_sale cannot be asserted by user input; it is a market evidence outcome.
    normalized_price = PRICE_TYPE_ALIASES.get(price, price if price in PRICE_TYPES and price != "verified_sale" else "unknown")
    return {"offer_kind": _enum(raw.get("offer_kind"), OFFER_KINDS), "entity_kind": _enum(raw.get("entity_kind"), ENTITY_KINDS), "price_type": normalized_price}

def classify(source: dict[str, Any]) -> dict[str, Any]:
    """Create safe input; absent claims remain unknown and raw text is never retained."""
    if not isinstance(source, dict) or not isinstance(source.get("structured_claims"), dict):
        raise ValueError("input must contain a structured_claims object; raw posts are not accepted")
    claims = source["structured_claims"]
    market_context = claims.get("market_context") if isinstance(claims.get("market_context"), dict) else {}
    items, seasons, sets = (_canonical_ids("item"), _canonical_ids("season"), _canonical_ids("set"))
    account_id = str(source.get("account_id", "account_new"))
    if not re.fullmatch(r"account_[a-z0-9_]+", account_id): raise ValueError("account_id must match account_[a-z0-9_]+")
    base = claims.get("base_account") if isinstance(claims.get("base_account"), dict) else {}
    season_profiles = []
    for number, row in enumerate(claims.get("season_profiles", [])):
        if not isinstance(row, dict): raise ValueError(f"season_profiles[{number}] must be an object")
        season_id = row.get("season_id")
        if season_id not in seasons: raise ValueError(f"season_profiles[{number}].season_id is not a canonical season ID: {season_id!r}")
        ratio = row.get("completion_ratio")
        if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or not 0 <= ratio <= 1: ratio = None
        season_profiles.append({"season_id": season_id, "status": _enum(row.get("status"), KNOWN), "completion_ratio": ratio, "pass_owned": _enum(row.get("pass_owned"), PASS), "ultimate_reward_owned": _enum(row.get("ultimate_reward_owned"), PASS), "owned_item_ids": _id_list(row.get("owned_item_ids"), "item", items, f"season_profiles[{number}].owned_item_ids"), "missing_item_ids": _id_list(row.get("missing_item_ids"), "item", items, f"season_profiles[{number}].missing_item_ids"), "evidence_state": _enum(row.get("evidence_state"), EVIDENCE), "evidence_sources": ["structured_claim"], "capture_date": None, "review_status": "needs_review"})
    collection_claim = claims.get("collection") if isinstance(claims.get("collection"), dict) else {}
    set_profiles = []
    for number, row in enumerate(collection_claim.get("item_set_profiles", [])):
        if not isinstance(row, dict) or row.get("set_id") not in sets: raise ValueError(f"collection.item_set_profiles[{number}].set_id is not a canonical set ID")
        if not isinstance(row.get("is_complete"), bool): raise ValueError(f"collection.item_set_profiles[{number}].is_complete must be a boolean")
        set_profiles.append({"set_id": row["set_id"], "is_complete": row["is_complete"]})
    collection = {"owned_item_ids": _id_list(collection_claim.get("owned_item_ids"), "item", items, "collection.owned_item_ids"), "item_set_profiles": set_profiles, "graduation_rewards": _id_list(collection_claim.get("graduation_rewards"), "item", items, "collection.graduation_rewards"), "graduation_reward_season_ids": _id_list(collection_claim.get("graduation_reward_season_ids"), "season", seasons, "collection.graduation_reward_season_ids"), "collaboration_items": _id_list(collection_claim.get("collaboration_items"), "item", items, "collection.collaboration_items"), "bundle_item_ids": _id_list(collection_claim.get("bundle_item_ids"), "item", items, "collection.bundle_item_ids"), "event_limited_item_ids": _id_list(collection_claim.get("event_limited_item_ids"), "item", items, "collection.event_limited_item_ids"), "bundle_claim_level": _enum(collection_claim.get("bundle_claim_level"), {"none", "partial", "complete", "unknown"})}
    resources_claim = claims.get("resources") if isinstance(claims.get("resources"), dict) else {}
    values = resources_claim.get("values", resources_claim)
    bindings_claim = claims.get("bindings") if isinstance(claims.get("bindings"), dict) else {}
    platforms = [{"platform": row["platform"], "status": _enum(row.get("status"), PLATFORM_STATUS, "mentioned_unknown"), "evidence_state": _enum(row.get("evidence_state"), EVIDENCE, "text_claim")} for row in bindings_claim.get("platforms", []) if isinstance(row, dict) and row.get("platform") in PLATFORM]
    if not platforms: platforms = [{"platform": "other", "status": "unknown", "evidence_state": "unknown"}]
    map_claim = claims.get("map_completion") if isinstance(claims.get("map_completion"), dict) else {}
    source_ids = source.get("source_listing_ids", [])
    if not isinstance(source_ids, list) or any(not isinstance(value, str) or not re.fullmatch(r"listing_[a-z0-9_]+", value) for value in source_ids): raise ValueError("source_listing_ids must be an optional list of listing_[a-z0-9_]+ IDs")
    valuation_date = market_context.get("valuation_date")
    try:
        if not isinstance(valuation_date, str): raise ValueError
        date.fromisoformat(valuation_date)
    except ValueError:
        valuation_date = None
    resource_values = {key: values.get(key) if isinstance(values, dict) and isinstance(values.get(key), int) and not isinstance(values.get(key), bool) and values[key] >= 0 else None for key in ("white_candles", "hearts", "red_candles", "season_candles")}
    return {"schema_version": "3.0-p0", "account_id": account_id, "source_listing_ids": list(dict.fromkeys(source_ids)), "currency": _enum(market_context.get("currency"), CURRENCIES), "server": _enum(market_context.get("server"), SERVERS), "valuation_date": valuation_date, "post_date": None, "date_verified": False, "date_evidence_state": "unknown", "base_account": {"account_type": str(base.get("account_type", "unknown")), "wing_state": str(base.get("wing_state", "unknown")), "special_appearance": [str(value) for value in base.get("special_appearance", []) if isinstance(value, str)], "short_id": str(base.get("short_id", "unknown"))}, "season_profiles": season_profiles, "season_summary": {"earliest_season_id": None, "earliest_complete_season_id": None, "complete_count": sum(row["status"] == "complete" for row in season_profiles), "partial_count": sum(row["status"] == "partial" for row in season_profiles), "pass_not_complete_count": sum(row["status"] in {"partial", "owned_not_complete"} and row["pass_owned"] == "yes" for row in season_profiles), "continuous_segments": [], "gap_segments": [], "evidence_state": "text_claim" if season_profiles else "unknown"}, "collection": collection, "map_completion": {"standard_maps": _enum(map_claim.get("standard_maps"), {"complete", "partial", "unknown"}), "second_tier_capes": _enum(map_claim.get("second_tier_capes"), {"complete", "partial", "unknown"}), "evidence_state": _enum(map_claim.get("evidence_state"), EVIDENCE)}, "resources": {"values": resource_values, "capture_date": None, "evidence_state": "text_claim" if any(value is not None for value in resource_values.values()) else "unknown"}, "bindings": {"platforms": platforms, "risk_state": _enum(bindings_claim.get("risk_state"), {"low", "restricted", "high_risk", "unknown"})}, "ownership_history": _enum(claims.get("ownership_history"), {"first_owner", "second_owner", "multiple_owners", "first_hand_claimed", "second_hand_or_more", "multiple_previous_owners", "unknown"}), "trade_conditions": _trade_conditions(claims), "evidence_quality": {"listing_text": "low" if claims else "unknown", "image": "not_collected", "ocr": "not_collected"}, "review_status": "needs_review"}

def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("input", type=Path); parser.add_argument("--output", type=Path, required=True); args = parser.parse_args()
    try: profile = classify(json.loads(args.input.read_text(encoding="utf-8")))
    except (OSError, ValueError, json.JSONDecodeError) as exc: parser.error(str(exc))
    args.output.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__": main()
