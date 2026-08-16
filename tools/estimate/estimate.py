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
MIN_SIMILARITY_SCORE = 40.0
MIN_EFFECTIVE_CONTENT_DIMENSIONS = 3


class _InternalProfile(dict[str, Any]):
    """An adapted profile type that cannot be constructed by JSON input."""


def normalize_price_type(row: dict[str, Any]) -> str:
    """Map legacy history labels without promoting a claimed sale to a sale."""
    if isinstance(row, _InternalProfile):
        value = row.get("price_type")
        return value if value in PRICE_TYPES | {"unknown"} else "unknown"
    # Never trust an input marker as evidence that a profile was already
    # adapted.  A caller can supply arbitrary top-level fields, so the nested
    # transaction claim remains authoritative whenever it is present.
    sale = row.get("sale_outcome", {})
    if isinstance(sale, dict) and sale.get("verified") is True and sale.get("completed_sale_price_twd") is not None:
        return "verified_sale"
    raw = _value(row.get("trade_conditions", {}) if isinstance(row.get("trade_conditions"), dict) else row, "price_type", default=_value(row, "price_type"))
    return {"asking": "normal_listing", "normal_listing": "normal_listing", "reduced": "urgent_sale", "urgent_sale": "urgent_sale", "instant": "urgent_sale", "quick_sale": "urgent_sale", "instant_price": "urgent_sale", "reduced_or_instant": "urgent_sale", "sold_last_ask": "last_public_price", "sold_explicit": "last_public_price", "last_public_price": "last_public_price", "verified_sale": "verified_sale", "buyout": "unknown"}.get(raw, "unknown")


def adapt_profile(row: dict[str, Any]) -> dict[str, Any]:
    """Flatten the canonical nested account-profile/history contract for scoring."""
    if isinstance(row, _InternalProfile):
        return row
    result = _InternalProfile(row)
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
            list(collection.get("graduation_rewards", [])) +
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
    # Market account profiles keep these values under trade_conditions while
    # older flat fixtures/history rows expose them at the top level.  Promote
    # them once so hard-pool selection never loses the target's transaction
    # type after adaptation.
    trade_conditions = row.get("trade_conditions", {})
    if isinstance(trade_conditions, dict):
        result["offer_kind"] = trade_conditions.get("offer_kind", result.get("offer_kind", "unknown"))
        result["entity_kind"] = trade_conditions.get("entity_kind", result.get("entity_kind", "unknown"))
    evidence = row.get("evidence_quality", {})
    if isinstance(evidence, dict): result["evidence_quality"] = evidence.get("listing_text", "unknown")
    # A joined comparable's top-level price_type is the curated history fact;
    # the nested profile still carries the source listing's older claim.  For
    # user targets (no history_id), the nested structured claim remains
    # authoritative and cannot be overridden by injected top-level fields.
    if row.get("history_id") and "price_type" in row:
        result["price_type"] = normalize_price_type({"price_type": row.get("price_type"), "sale_outcome": row.get("sale_outcome", {})})
    else:
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
    # ``winged_or_unspecified`` is a migration fallback, not affirmative
    # evidence that an account is winged.  Treating two fallback values as a
    # family match would award similarity for shared missing information.
    if value == "winged":
        return "winged"
    if value in {"short_id", "special_appearance"}:
        return value
    return "unknown"


def _known_identifier(value: Any) -> str | None:
    """Return an identifier only when it is explicitly known.

    Identity fields are exclusion evidence, not similarity features.  In
    particular, two missing/``unknown`` duplicate-cluster values must never
    be interpreted as the same cluster.
    """
    if isinstance(value, str):
        value = value.strip()
        if value and value.lower() not in {"unknown", "null", "none"}:
            return value
    return None


def _known_identifier_set(value: Any) -> set[str]:
    """Return explicitly known IDs from a scalar or iterable identity field."""
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        raw_values = (value,)
    return {identifier for raw in raw_values if (identifier := _known_identifier(raw)) is not None}


def _independence_reasons(account: dict[str, Any], comparable: dict[str, Any]) -> list[str]:
    """Reject a comparable that can represent the target listing/account.

    Reusing a listing, account or deduplication cluster as a market
    comparable leaks the target into its own price pool.  Every comparison is
    fail-closed only when there is positive identity evidence; absent IDs do
    not create a match.
    """
    reasons: list[str] = []
    account_id = _known_identifier(account.get("account_id"))
    comparable_account_id = _known_identifier(comparable.get("account_id"))
    if account_id is not None and account_id == comparable_account_id:
        reasons.append("same_account_id")

    account_sources = _known_identifier_set(account.get("source_listing_ids"))
    comparable_sources = _known_identifier_set(comparable.get("source_listing_ids"))
    if account_sources & comparable_sources:
        reasons.append("source_listing_id_overlap")

    account_cluster = _known_identifier(account.get("duplicate_cluster_id"))
    comparable_cluster = _known_identifier(comparable.get("duplicate_cluster_id"))
    if account_cluster is not None and account_cluster == comparable_cluster:
        reasons.append("duplicate_cluster_id_match")
    return reasons


def _price_semantic_reasons(row: dict[str, Any], prefix: str = "") -> list[str]:
    """Return fail-closed reasons for an explicitly flagged price semantic.

    An absent review means no known price-semantic exception was imported.  A
    present review is usable only after an explicit approval, and a price that
    includes brokerage is never comparable until it is separated from the
    account price.  This applies equally to an incoming target and a market
    comparable.
    """
    review = row.get("price_semantic_review")
    if not isinstance(review, dict):
        return []
    reasons: list[str] = []
    if review.get("review_status") != "approved":
        reasons.append(f"{prefix}price_semantic_review_not_approved")
    if review.get("brokerage_included") is True:
        reasons.append(f"{prefix}brokerage_included")
    return reasons


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


def _season_entries(row: dict[str, Any]) -> dict[str, str]:
    raw = row.get("season_profile", row.get("seasons", []))
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items() if v not in (None, "unknown")}
    return {str(x.get("season_id")): str(x.get("status")) for x in raw if isinstance(x, dict) and x.get("season_id") and x.get("status") not in (None, "unknown")} if isinstance(raw, list) else {}


def _map_known(account: dict[str, Any], comparable: dict[str, Any]) -> bool:
    if _number(account, "map_completion_ratio") is not None and _number(comparable, "map_completion_ratio") is not None:
        return True
    left, right = account.get("map_completion", account), comparable.get("map_completion", comparable)
    return isinstance(left, dict) and isinstance(right, dict) and any(left.get(k) not in (None, "unknown") and right.get(k) not in (None, "unknown") for k in ("standard_maps", "second_tier_capes"))


def _resources_known(account: dict[str, Any], comparable: dict[str, Any]) -> bool:
    left, right = account.get("resources", account), comparable.get("resources", comparable)
    return isinstance(left, dict) and isinstance(right, dict) and any(_number(left, key) is not None and _number(right, key) is not None for key in ("white_candles", "hearts", "red_candles", "season_candles"))


def _bindings_known(account: dict[str, Any], comparable: dict[str, Any]) -> bool:
    left, right = account.get("bindings", {}), comparable.get("bindings", {})
    return isinstance(left, dict) and isinstance(right, dict) and any(left.get(k) not in (None, "unknown", "mentioned_unknown") and right.get(k) not in (None, "unknown", "mentioned_unknown") for k in set(left) | set(right))


def _collection_features(row: dict[str, Any]) -> set[str]:
    values: set[str] = set()
    for name in ("ultimate_reward_item_ids", "collection_ids", "graduation_reward_season_ids"):
        values.update(_list(row, name))
    return values


def score(account: dict[str, Any], comparable: dict[str, Any]) -> dict[str, Any]:
    """Return all dimension scores. Unknown evidence is never treated as a match."""
    account, comparable = adapt_profile(account), adapt_profile(comparable)
    atype, btype = _value(account, "base_account_type", "account_type"), _value(comparable, "base_account_type", "account_type")
    account_type_known = atype not in (None, "unknown", "winged_or_unspecified")
    comparable_type_known = btype not in (None, "unknown", "winged_or_unspecified")
    type_score = 1.0 if account_type_known and comparable_type_known and atype == btype else 0.6 if _account_family(atype) != "unknown" and _account_family(atype) == _account_family(btype) else 0.0
    items = _ratio(_list(account, "owned_item_ids", "item_ids"), _list(comparable, "owned_item_ids", "item_ids"))
    complete_sets = _ratio(_list(account, "complete_set_ids", "set_ids"), _list(comparable, "complete_set_ids", "set_ids"))
    mentioned_sets = _ratio(_list(account, "mentioned_set_ids"), _list(comparable, "mentioned_set_ids"))
    sets = complete_sets * 0.7 + mentioned_sets * 0.3
    map_score = _map_similarity(account, comparable)
    collection = _ratio(_collection_features(account), _collection_features(comparable))
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
    known = {
        "account_type": account_type_known and comparable_type_known,
        "seasons": bool(_season_entries(account)) and bool(_season_entries(comparable)),
        "items_sets": bool(_list(account, "owned_item_ids", "item_ids") or _list(account, "complete_set_ids", "set_ids") or _list(account, "mentioned_set_ids")) and bool(_list(comparable, "owned_item_ids", "item_ids") or _list(comparable, "complete_set_ids", "set_ids") or _list(comparable, "mentioned_set_ids")),
        "map_completion": _map_known(account, comparable),
        "collection": bool(_collection_features(account)) and bool(_collection_features(comparable)),
        "resources": _resources_known(account, comparable),
        "bindings": _bindings_known(account, comparable),
        "ownership": _value(account, "ownership_generation", "account_generation") not in (None, "unknown") and _value(comparable, "ownership_generation", "account_generation") not in (None, "unknown"),
        "date": _value(account, "valuation_date", "valuation_as_of_date", default=None) not in (None, "unknown") and _value(comparable, "post_date", "listing_date", "date", default=None) not in (None, "unknown"),
        "evidence": _value(account, "evidence_quality") not in (None, "unknown") and _value(comparable, "evidence_quality") not in (None, "unknown"),
    }
    return {"score": round(sum(weighted.values()), 4), "dimensions": weighted, "known_dimensions": known}


def hard_pool(account: dict[str, Any], comparable: dict[str, Any]) -> tuple[bool, list[str]]:
    account, comparable = adapt_profile(account), adapt_profile(comparable)
    reasons = _independence_reasons(account, comparable)
    reasons.extend(_price_semantic_reasons(account, "target_"))
    reasons.extend(_price_semantic_reasons(comparable))
    for field in ("currency", "server"):
        a, b = _value(account, field), _value(comparable, field)
        if a in ("unknown", None):
            # A target without a market cannot safely borrow a different
            # currency/server pool merely because the comparable is verified.
            reasons.append(f"target_{field}_unknown")
        elif b in ("unknown", None):
            reasons.append(f"{field}_unverified")
        elif a != b:
            reasons.append(f"{field}_mismatch")
    for field in ("currency_verified", "server_verified"):
        if comparable.get(field) is not True:
            reasons.append(f"{field}_required")
    # This estimator values a seller's single account.  Buyer budgets,
    # services, exchanges, and bundles use different price semantics.  A
    # target must explicitly claim this transaction type; missing information
    # is not treated as a compatible listing.
    if _value(account, "offer_kind") != "seller_listing":
        reasons.append("target_not_seller_listing")
    if _value(account, "entity_kind") != "single_account":
        reasons.append("target_not_single_account")
    if _value(comparable, "entity_kind") != "single_account":
        reasons.append("not_single_account")
    if _value(comparable, "offer_kind") != "seller_listing":
        reasons.append("not_seller_listing")
    account_type = _value(account, "base_account_type", "account_type")
    comparable_type = _value(comparable, "base_account_type", "account_type")
    if _account_family(account_type) != "unknown":
        if _account_family(comparable_type) == "unknown":
            reasons.append("account_type_unverified")
        elif _account_family(account_type) != _account_family(comparable_type):
            reasons.append("account_type_incompatible")
    target_type = normalize_price_type(account)
    if target_type == "unknown":
        reasons.append("target_price_type_unknown")
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


def _describe(account: dict[str, Any], row: dict[str, Any], dimensions: dict[str, float], known: dict[str, bool]) -> dict[str, list[str]]:
    same = [k for k, v in dimensions.items() if v >= WEIGHTS[k] * .75]
    # A non-overlapping inventory/season/collection usually means the listing
    # is incomplete, not that ownership is confirmed absent.  Only explicit,
    # mutually exclusive categorical states may be described as differences.
    # These dimensions have a shared, explicit observation and can therefore
    # safely describe a low score as a confirmed difference.  Collections and
    # seasons deliberately remain excluded: disjoint lists are not evidence
    # that the other account lacks the item or season.
    confirmed_mutually_exclusive = {"account_type", "map_completion", "resources", "bindings", "ownership"}
    different = [k for k, v in dimensions.items() if k in confirmed_mutually_exclusive and known[k] and v <= WEIGHTS[k] * .25]
    unknown = [k for k, v in dimensions.items() if not known[k] or (k not in confirmed_mutually_exclusive and v <= WEIGHTS[k] * .25)]
    return {"major_matches": same, "major_differences": different, "unconfirmed_dimensions": unknown}


def estimate(account: dict[str, Any], comparables: Iterable[dict[str, Any]]) -> dict[str, Any]:
    account = adapt_profile(account)
    strict, rejected, quality_rejected, selection_rejected = [], [], [], []
    for row in comparables:
        comparable = adapt_profile(row)
        ok, reasons = hard_pool(account, comparable)
        if not ok:
            rejected.append({"comparable_id": _value(comparable, "comparable_id", "history_id", default="unknown"), "reasons": reasons})
            continue
        result = score(account, comparable)
        strict.append((result["score"], comparable, result))
    stage = "strict"
    target_type = _value(account, "base_account_type", "account_type")
    chosen = [x for x in strict if _value(x[1], "base_account_type", "account_type") == target_type]
    if len(chosen) < 3:
        # Currency, server and price type are never relaxed.  The only P0
        # expansion is disclosed: retain the same base type but do not demand
        # any additional collection/season threshold beyond the score itself.
        stage = "expanded_same_account_family"
        chosen = [x for x in strict if _account_family(_value(x[1], "base_account_type", "account_type")) == _account_family(target_type)]
    selected_row_ids = {id(row) for _, row, _ in chosen}
    for _, row, _ in strict:
        if id(row) not in selected_row_ids:
            selection_rejected.append({"comparable_id": _value(row, "comparable_id", "history_id", default="unknown"), "reasons": ["account_type_not_selected"]})
    chosen.sort(key=lambda x: x[0], reverse=True)
    qualified = []
    for total, row, result in chosen:
        effective = sum(result["known_dimensions"].get(name, False) for name in ("seasons", "items_sets", "map_completion", "collection", "resources", "bindings", "ownership"))
        reasons = []
        if total < MIN_SIMILARITY_SCORE:
            reasons.append("below_minimum_similarity")
        if effective < MIN_EFFECTIVE_CONTENT_DIMENSIONS:
            reasons.append("insufficient_effective_content_dimensions")
        if reasons:
            quality_rejected.append({"comparable_id": _value(row, "comparable_id", "history_id", default="unknown"), "reasons": reasons, "similarity_score": total, "effective_content_dimensions": effective})
        else:
            qualified.append((total, row, result, effective))
    detail = []
    for total, row, result, effective in qualified[:5]:
        price = _price(row)
        detail.append({
            "comparable_id": _value(row, "comparable_id", "history_id", default="unknown"),
            "similarity_score": total, "similarity_dimensions": result["dimensions"],
            "retained_reason": f"{stage}; hard pool compatible; meets static quality thresholds", "price_type": normalize_price_type(row),
            "market_date": _value(row, "post_date", "listing_date", default="unknown"),
            "market_evidence": _value(row, "market_evidence_quality", "evidence_quality", default="unknown"),
            "price_twd": price, "effective_content_dimensions": effective,
            **_describe(account, row, result["dimensions"], result["known_dimensions"]),
        })
    for total, row, result, effective in qualified[5:]:
        selection_rejected.append({
            "comparable_id": _value(row, "comparable_id", "history_id", default="unknown"),
            "reasons": ["lower_rank_not_retained"], "similarity_score": total,
            "effective_content_dimensions": effective,
        })
    priced = [d["price_twd"] for d in detail if d["price_twd"] is not None]
    insufficiency = []
    if len(strict) < 3:
        insufficiency.append("fewer_than_three_hard_pool_compatible_comparables")
    if len(qualified) < 3:
        insufficiency.append("fewer_than_three_comparables_meet_similarity_and_content_thresholds")
    if len(priced) < 3:
        insufficiency.append("fewer_than_three_qualified_comparables_have_valid_prices")
    eligible = not insufficiency
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
        "strict_candidate_count": len(strict), "quality_candidate_count": len(qualified), "retained_count": len(detail),
        "rejected_by_hard_pool": rejected,
        "rejected_by_quality": quality_rejected,
        "rejected_by_selection": selection_rejected,
        "insufficiency_reasons": insufficiency,
        "limitations": [] if eligible else ["No price range is produced until the static hard-pool, similarity, effective-content, and valid-price thresholds are met."],
        "method": "Comparable-account selection only; no additive item pricing.",
    }


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline Sky comparable estimator")
    parser.add_argument("account", type=Path)
    parser.add_argument("comparables", type=Path, nargs="?", default=Path(__file__).resolve().parents[2] / "data" / "comparables" / "accounts.jsonl")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    comparables = _read_jsonl(args.comparables)
    if not comparables or any(not isinstance(row.get("base_account"), dict) for row in comparables):
        parser.error("comparables must be complete comparable account profiles (data/comparables/accounts.jsonl); history-only JSONL is not accepted")
    result = estimate(json.loads(args.account.read_text(encoding="utf-8")), comparables)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
