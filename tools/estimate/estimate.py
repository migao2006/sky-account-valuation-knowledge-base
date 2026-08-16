#!/usr/bin/env python3
"""Offline-only comparable selection for Sky account profiles.

This module intentionally has no item price table and imports only the Python
standard library.  It compares account structure; it never converts a single
collectible into a fixed currency amount.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import date, datetime
from pathlib import Path
from statistics import quantiles
from typing import Any, Iterable

WEIGHTS = {
    "account_type": 15, "seasons": 22, "items_sets": 20,
    "map_completion": 10, "collection": 8, "resources": 7,
    "bindings": 6, "ownership": 4, "date": 5, "evidence": 3,
}
PRICE_TYPES = {"normal_listing", "urgent_sale", "last_public_price", "verified_sale"}
HARD_PRICE_TYPES = {"normal_listing", "urgent_sale", "last_public_price", "verified_sale"}


def normalize_price_type(row: dict[str, Any]) -> str:
    """Map legacy history labels without promoting a claimed sale to a sale."""
    sale = row.get("sale_outcome", {})
    if isinstance(sale, dict) and sale.get("verified") is True and sale.get("completed_sale_price_twd") is not None:
        return "verified_sale"
    raw = _value(row.get("trade_conditions", {}) if isinstance(row.get("trade_conditions"), dict) else row, "price_type", default=_value(row, "price_type"))
    return {"asking": "normal_listing", "normal_listing": "normal_listing", "reduced": "urgent_sale", "instant": "urgent_sale", "quick_sale": "urgent_sale", "instant_price": "urgent_sale", "reduced_or_instant": "urgent_sale", "sold_last_ask": "last_public_price", "sold_explicit": "last_public_price", "last_public_price": "last_public_price", "verified_sale": "verified_sale", "buyout": "unknown"}.get(raw, "unknown")


def adapt_profile(row: dict[str, Any]) -> dict[str, Any]:
    """Flatten the canonical nested account-profile/history contract for scoring."""
    result = dict(row)
    base = row.get("base_account", {})
    if isinstance(base, dict) and base:
        result["base_account_type"] = base.get("account_type", result.get("base_account_type", "unknown"))
    result["season_profile"] = row.get("season_profiles", row.get("season_profile", []))
    summary = row.get("season_summary", {})
    if isinstance(summary, dict): result["earliest_season_id"] = summary.get("earliest_season_id") or "unknown"
    collection = row.get("collection", {})
    if isinstance(collection, dict):
        result["owned_item_ids"] = collection.get("owned_item_ids", row.get("owned_item_ids", []))
        result["ultimate_reward_item_ids"] = collection.get("graduation_rewards", [])
        # These categories are distinct in source data but form one collection
        # feature; union so an empty collaboration list never hides bundles.
        result["collection_ids"] = list(dict.fromkeys(
            list(collection.get("collaboration_items", [])) +
            list(collection.get("bundle_item_ids", collection.get("bundle_ids", []))) +
            list(collection.get("event_limited_item_ids", []))))
        result["graduation_reward_season_ids"] = collection.get("graduation_reward_season_ids", [])
        profiles = collection.get("item_set_profiles", [])
        result["complete_set_ids"] = [x.get("set_id") for x in profiles if isinstance(x, dict) and x.get("is_complete") is True and x.get("set_id")]
        result["mentioned_set_ids"] = [x.get("set_id") for x in profiles if isinstance(x, dict) and x.get("set_id") and x.get("evidence_state") in {"text_claim", "image_confirmed"}]
    maps = row.get("map_completion", {})
    if isinstance(maps, dict): result["map_completion_ratio"] = maps.get("completion_ratio", row.get("map_completion_ratio"))
    resources = row.get("resources", {})
    if isinstance(resources, dict): result["resources"] = resources.get("values", resources)
    bindings = row.get("bindings", {})
    if isinstance(bindings, dict):
        platforms = bindings.get("platforms", bindings)
        if isinstance(platforms, list):
            result["bindings"] = {str(x.get("platform")): x.get("status") for x in platforms if isinstance(x, dict) and x.get("platform") and x.get("status") not in (None, "unknown", "mentioned_unknown")}
        result["binding_state"] = bindings.get("risk_state", result.get("binding_state", "unknown"))
    result["ownership_generation"] = row.get("ownership_history", row.get("ownership_generation", "unknown"))
    evidence = row.get("evidence_quality", {})
    if isinstance(evidence, dict): result["evidence_quality"] = evidence.get("listing_text", "unknown")
    result["price_type"] = normalize_price_type(row)
    return result


def _value(row: dict[str, Any], *names: str, default: Any = "unknown") -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return default


def _list(row: dict[str, Any], *names: str) -> set[str]:
    raw = _value(row, *names, default=[])
    if isinstance(raw, dict):
        raw = raw.keys()
    return {str(x) for x in raw if x not in (None, "unknown")}


def _ratio(a: set[str], b: set[str], unknown_score: float = 0.0) -> float:
    if not a or not b:
        return unknown_score
    return len(a & b) / len(a | b)


def _number(row: dict[str, Any], *names: str) -> float | None:
    value = _value(row, *names, default=None)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _level_similarity(a: Any, b: Any) -> float:
    if a in (None, "unknown") or b in (None, "unknown"):
        return 0.0
    if a == b:
        return 1.0
    levels = ["none", "low", "medium", "high", "very_high"]
    if a in levels and b in levels:
        return max(0.0, 1.0 - abs(levels.index(a) - levels.index(b)) / 4)
    return 0.0


def _account_family(value: Any) -> str:
    value = str(value or "unknown")
    if value in {"wingless", "permanent_wingless", "crash_wingless"}:
        return "wingless"
    if value in {"winged", "winged_or_unspecified"}:
        return "winged"
    if value in {"short_id", "special_appearance"}:
        return value
    return "unknown"


def _date_similarity(account: dict[str, Any], comparable: dict[str, Any]) -> float:
    target = _value(account, "valuation_date", "valuation_as_of_date", default=None)
    observed = _value(comparable, "post_date", "listing_date", "date", default=None)
    if not target or not observed:
        return 0.0
    try:
        delta = abs((date.fromisoformat(str(target)[:10]) - date.fromisoformat(str(observed)[:10])).days)
    except ValueError:
        return 0.0
    return max(0.0, 1.0 - min(delta, 365) / 365)


def _season_similarity(account: dict[str, Any], comparable: dict[str, Any]) -> float:
    a = account.get("season_profile", account.get("seasons", []))
    b = comparable.get("season_profile", comparable.get("seasons", comparable.get("season_tags", [])))
    def normalize(raw: Any) -> dict[str, str]:
        if isinstance(raw, dict):
            return {str(k): str(v.get("status", v)) if isinstance(v, dict) else str(v) for k, v in raw.items()}
        out: dict[str, str] = {}
        for x in raw if isinstance(raw, list) else []:
            if isinstance(x, dict) and x.get("season_id"):
                out[str(x["season_id"])] = str(x.get("status", "unknown"))
            elif isinstance(x, str):
                out[x] = "owned_not_complete"
        return out
    left, right = normalize(a), normalize(b)
    if not left or not right:
        return 0.0
    ids = set(left) | set(right)
    score = sum(1.0 if left.get(i) == right.get(i) and left.get(i) != "unknown" else 0.5 if i in left and i in right and left.get(i) != "unknown" and right.get(i) != "unknown" else 0.0 for i in ids)
    # First/continuous seasons are meaningful even where an item inventory is incomplete.
    early = _level_similarity(_value(account, "earliest_season_id"), _value(comparable, "earliest_season_id"))
    return min(1.0, (score / len(ids)) * 0.9 + early * 0.1)


def _resource_similarity(account: dict[str, Any], comparable: dict[str, Any]) -> float:
    keys = ("white_candles", "hearts", "red_candles", "season_candles")
    left, right = account.get("resources", account), comparable.get("resources", comparable)
    parts = []
    for key in keys:
        a, b = _number(left, key), _number(right, key)
        if a is not None and b is not None:
            parts.append(1.0 - min(abs(a - b) / max(a, b, 1), 1.0))
    if parts:
        return sum(parts) / len(parts)
    return _level_similarity(_value(account, "resource_level"), _value(comparable, "resource_level"))


def _map_similarity(account: dict[str, Any], comparable: dict[str, Any]) -> float:
    a, b = _number(account, "map_completion_ratio"), _number(comparable, "map_completion_ratio")
    if a is not None and b is not None:
        return max(0.0, 1 - abs(a - b))
    # P0 input often has confirmed categorical map evidence but no numeric ratio.
    pairs = [("standard_maps", "standard_maps"), ("second_tier_capes", "second_tier_capes")]
    left, right = account.get("map_completion", account), comparable.get("map_completion", comparable)
    if not isinstance(left, dict) or not isinstance(right, dict): return 0.0
    known = [(left.get(x), right.get(y)) for x, y in pairs if left.get(x) not in (None, "unknown") and right.get(y) not in (None, "unknown")]
    return sum(1.0 if x == y else 0.0 for x, y in known) / len(known) if known else 0.0


def _binding_similarity(account: dict[str, Any], comparable: dict[str, Any]) -> float:
    a, b = account.get("bindings", {}), comparable.get("bindings", {})
    if isinstance(a, dict) and isinstance(b, dict) and a and b:
        keys = set(a) | set(b)
        known = [k for k in keys if a.get(k) not in (None, "unknown", "mentioned_unknown") and b.get(k) not in (None, "unknown", "mentioned_unknown")]
        return sum(1.0 if a.get(k) == b.get(k) else 0.0 for k in known) / len(known) if known else 0.0
    return _level_similarity(_value(account, "binding_state"), _value(comparable, "binding_state"))


def score(account: dict[str, Any], comparable: dict[str, Any]) -> dict[str, Any]:
    """Return all dimension scores. Unknown evidence is never treated as a match."""
    account, comparable = adapt_profile(account), adapt_profile(comparable)
    atype, btype = _value(account, "base_account_type", "account_type"), _value(comparable, "base_account_type", "account_type")
    type_score = 1.0 if atype not in (None, "unknown") and atype == btype else 0.6 if _account_family(atype) != "unknown" and _account_family(atype) == _account_family(btype) else 0.0
    items = _ratio(_list(account, "owned_item_ids", "item_ids"), _list(comparable, "owned_item_ids", "item_ids"))
    complete_sets = _ratio(_list(account, "complete_set_ids", "set_ids"), _list(comparable, "complete_set_ids", "set_ids"))
    mentioned_sets = _ratio(_list(account, "mentioned_set_ids"), _list(comparable, "mentioned_set_ids"))
    sets = complete_sets * 0.7 + mentioned_sets * 0.3
    map_score = _map_similarity(account, comparable)
    collection_items = _ratio(_list(account, "ultimate_reward_item_ids", "collection_ids", "bundle_tags"), _list(comparable, "ultimate_reward_item_ids", "collection_ids", "bundle_tags"))
    graduation_seasons = _ratio(_list(account, "graduation_reward_season_ids"), _list(comparable, "graduation_reward_season_ids"))
    collection = (collection_items * .75 + graduation_seasons * .25) if collection_items or graduation_seasons else 0.0
    evidence = _level_similarity(_value(account, "evidence_quality"), _value(comparable, "evidence_quality"))
    dimensions = {
        "account_type": type_score, "seasons": _season_similarity(account, comparable),
        "items_sets": items * 0.75 + sets * 0.25, "map_completion": map_score,
        "collection": collection, "resources": _resource_similarity(account, comparable),
        "bindings": _binding_similarity(account, comparable),
        "ownership": _level_similarity(_value(account, "ownership_generation", "account_generation"), _value(comparable, "ownership_generation", "account_generation")),
        "date": _date_similarity(account, comparable), "evidence": evidence,
    }
    weighted = {name: round(dimensions[name] * weight, 4) for name, weight in WEIGHTS.items()}
    return {"score": round(sum(weighted.values()), 4), "dimensions": weighted}


def hard_pool(account: dict[str, Any], comparable: dict[str, Any]) -> tuple[bool, list[str]]:
    account, comparable = adapt_profile(account), adapt_profile(comparable)
    reasons: list[str] = []
    for field in ("currency", "server"):
        a, b = _value(account, field), _value(comparable, field)
        if a not in ("unknown", None):
            if b in ("unknown", None):
                reasons.append(f"{field}_unverified")
            elif a != b:
                reasons.append(f"{field}_mismatch")
    for field in ("currency_verified", "server_verified"):
        if comparable.get(field) is not True:
            reasons.append(f"{field}_required")
    if _value(comparable, "entity_kind") not in ("single_account", "unknown", None):
        reasons.append("not_single_account")
    if _value(comparable, "offer_kind") in {"buyer_budget", "service", "exchange"}:
        reasons.append("not_seller_listing")
    account_type = _value(account, "base_account_type", "account_type")
    comparable_type = _value(comparable, "base_account_type", "account_type")
    if _account_family(account_type) != "unknown":
        if _account_family(comparable_type) == "unknown":
            reasons.append("account_type_unverified")
        elif _account_family(account_type) != _account_family(comparable_type):
            reasons.append("account_type_incompatible")
    target_type = normalize_price_type(account)
    actual_type = normalize_price_type(comparable)
    if target_type in HARD_PRICE_TYPES and actual_type != target_type:
        reasons.append("price_type_mismatch")
    return not reasons, reasons


def _price(row: dict[str, Any]) -> float | None:
    for key in ("selected_price_twd", "price_twd", "asking_price_twd", "price"):
        v = _number(row, key)
        if v is not None and v >= 0:
            return v
    return None


def _describe(account: dict[str, Any], row: dict[str, Any], dimensions: dict[str, float]) -> dict[str, list[str]]:
    same = [k for k, v in dimensions.items() if v >= WEIGHTS[k] * .75]
    different = [k for k, v in dimensions.items() if v <= WEIGHTS[k] * .25]
    unknown = [k for k, v in dimensions.items() if v == 0]
    return {"major_matches": same, "major_differences": different, "unconfirmed_dimensions": unknown}


def estimate(account: dict[str, Any], comparables: Iterable[dict[str, Any]]) -> dict[str, Any]:
    account = adapt_profile(account)
    strict, rejected = [], []
    for row in comparables:
        ok, reasons = hard_pool(account, row)
        if not ok:
            rejected.append({"comparable_id": _value(row, "comparable_id", "history_id", default="unknown"), "reasons": reasons})
            continue
        result = score(account, row)
        strict.append((result["score"], row, result))
    stage = "strict"
    target_type = _value(account, "base_account_type", "account_type")
    chosen = [x for x in strict if _value(x[1], "base_account_type", "account_type") == target_type]
    if len(chosen) < 3:
        # Currency, server and price type are never relaxed.  The only P0
        # expansion is disclosed: retain the same base type but do not demand
        # any additional collection/season threshold beyond the score itself.
        stage = "expanded_same_account_family"
        chosen = [x for x in strict if _account_family(_value(x[1], "base_account_type", "account_type")) == _account_family(target_type)]
    chosen.sort(key=lambda x: x[0], reverse=True)
    detail = []
    for total, row, result in chosen[:5]:
        price = _price(row)
        detail.append({
            "comparable_id": _value(row, "comparable_id", "history_id", default="unknown"),
            "similarity_score": total, "similarity_dimensions": result["dimensions"],
            "retained_reason": f"{stage}; hard pool compatible", "price_type": _value(row, "price_type"),
            "market_date": _value(row, "post_date", "listing_date", default="unknown"),
            "market_evidence": _value(row, "market_evidence_quality", "evidence_quality", default="unknown"),
            "price_twd": price, **_describe(account, row, result["dimensions"]),
        })
    priced = [d["price_twd"] for d in detail if d["price_twd"] is not None]
    eligible = len(detail) >= 3 and len(priced) >= 3
    price_range = None
    if eligible:
        values = sorted(priced)
        price_range = {"low": values[0], "median": values[len(values)//2], "high": values[-1]}
    return {
        "schema_version": "3.0-p0", "offline_only": True,
        "price_type": normalize_price_type(account),
        "selection_stage": stage, "eligible": eligible,
        "status": "estimated" if eligible else "insufficient_comparables",
        "range_twd": price_range, "comparables": detail,
        "strict_candidate_count": len(strict), "retained_count": len(detail),
        "rejected_by_hard_pool": rejected,
        "limitations": [] if eligible else ["Less than three price-compatible comparable accounts; no price range is produced."],
        "method": "Comparable-account selection only; no additive item pricing.",
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline Sky comparable estimator")
    parser.add_argument("account", type=Path)
    parser.add_argument("comparables", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = estimate(json.loads(args.account.read_text(encoding="utf-8")), _read_jsonl(args.comparables))
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
