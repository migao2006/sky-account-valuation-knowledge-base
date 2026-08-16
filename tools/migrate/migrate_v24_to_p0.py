#!/usr/bin/env python3
"""Offline, repeatable migration from the v2.4 snapshot into P0 data layers.

This program deliberately reads the legacy project as an input only.  It never
imports providers, does not use the network, and removes source-group identity
and post locators before writing P0 records.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "3.0-p0"
FORBIDDEN_KEYS = {
    "source_group_id", "source_group_name", "source_post_key", "post_url",
    "profile_url", "author", "author_name", "uid", "group_id", "locator",
}
SEASON_RE = re.compile(
    r"感恩|追光|歸屬|归属|音韻|音韵|魔法|聖島|圣岛|預言|预言|夢想|梦想|重組|重组|"
    r"小王子|風行|风行|深淵|深渊|表演|破曉|破晓|歐若拉|欧若拉|極光|极光|追憶|追忆|"
    r"緬懷|缅怀|夜行|拾光|九色鹿|築巢|筑巢|巢穴|二重奏|姆明|彩染|遷徙|迁徙|"
    r"青鳥|青鸟|雙星|双星|織光|织光|狂歡|狂欢|梵高|梵谷|梵谷季|歸巢|归巢"
)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def pseudo(prefix: str, legacy_value: str) -> str:
    digest = hashlib.sha256(legacy_value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def safe_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def clean(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in FORBIDDEN_KEYS}


def sanitize_market_text(value: Any, source_names: set[str]) -> str:
    text = str(value or "")
    for name in sorted(source_names, key=len, reverse=True):
        # Group names such as 「光遇交易」 are four CJK codepoints; a length
        # threshold would silently leak them.  Keep only the bare game title
        # untouched because it is normal listing content rather than identity.
        if name and name.casefold() not in {"光遇", "sky光遇", "sky光·遇"}:
            text = text.replace(name, "[來源名稱已移除]")
    return text


def legacy_root(default_v3: Path) -> Path:
    return default_v3.parent / "sky-valuation"


def catalog_aliases(v3_root: Path) -> dict[str, str]:
    """Read only canonical knowledge files when they are already available."""
    index: dict[str, str] = {}
    candidates = [
        v3_root / "knowledge" / "aliases" / "item-aliases.jsonl",
        v3_root / "knowledge" / "seasons" / "seasons.jsonl",
    ]
    for path in candidates:
        if not path.exists():
            continue
        for row in read_jsonl(path):
            if row.get("target_type") not in (None, "season"):
                continue
            season_id = row.get("season_id") or row.get("canonical_id") or row.get("target_id")
            if not isinstance(season_id, str):
                continue
            values = row.get("aliases", [])
            if isinstance(row.get("alias"), str):
                values = list(values) + [row["alias"]]
            if isinstance(row.get("alias_text"), str):
                values = list(values) + [row["alias_text"]]
            for value in values:
                if isinstance(value, str):
                    index[value.casefold()] = season_id
            for name_key in ("canonical_name_zh_tw", "canonical_name_en"):
                value = row.get(name_key)
                if isinstance(value, str):
                    index[value.casefold()] = season_id
    return index


def item_aliases(v3_root: Path) -> dict[str, str]:
    """Load the canonical item alias index when the knowledge layer is present."""
    index: dict[str, str] = {}
    path = v3_root / "knowledge" / "aliases" / "item-aliases.jsonl"
    if not path.exists():
        return index
    for row in read_jsonl(path):
        if row.get("target_type") not in (None, "item"):
            continue
        item_id = row.get("item_id") or row.get("canonical_id") or row.get("target_id")
        alias = row.get("alias") or row.get("alias_text")
        if isinstance(item_id, str) and isinstance(alias, str):
            index[alias.casefold()] = item_id
    return index


def collection_aliases(v3_root: Path) -> dict[str, tuple[str, str]]:
    """Return only aliases that resolve to exactly one item or set target."""
    candidates: dict[str, set[tuple[str, str]]] = {}
    path = v3_root / "knowledge" / "aliases" / "item-aliases.jsonl"
    if not path.exists():
        return {}
    for row in read_jsonl(path):
        target_type = row.get("target_type")
        target_id = row.get("target_id")
        alias = row.get("alias_text")
        if target_type in {"item", "set"} and isinstance(target_id, str) and isinstance(alias, str) and len(alias.strip()) >= 2:
            candidates.setdefault(alias.casefold(), set()).add((target_type, target_id))
    return {alias: next(iter(targets)) for alias, targets in candidates.items() if len(targets) == 1}


def mentioned_without_negation(text: str, alias: str) -> bool:
    for match in re.finditer(re.escape(alias), text, flags=re.I):
        context = text[max(0, match.start() - 5): min(len(text), match.end() + 5)]
        if not re.search(r"(?:缺|無|无|沒有|没有|不含|未有|未擁有|未拥有).{0,4}" + re.escape(alias), context, flags=re.I):
            return True
    return False


def season_terms(text: str) -> list[str]:
    return list(dict.fromkeys(match.group(0) for match in SEASON_RE.finditer(text)))


def season_profile(text: str, aliases: dict[str, str], order: dict[str, int]) -> tuple[list[dict[str, Any]], list[str]]:
    matches = [match for match in SEASON_RE.finditer(text)]
    profiles_by_id: dict[str, dict[str, Any]] = {}
    unresolved: list[str] = []
    terms_by_id: dict[str, str] = {}
    positions: list[tuple[re.Match[str], str]] = []
    for match in matches:
        term = match.group(0)
        season_id = aliases.get(term.casefold())
        if not season_id:
            unresolved.append(term)
            continue
        if season_id not in terms_by_id:
            terms_by_id[season_id] = term
        positions.append((match, season_id))

    def make_profile(season_id: str, status: str, evidence_state: str = "text_claim") -> dict[str, Any]:
        return {
            "season_id": season_id, "status": status, "completion_ratio": None,
            "pass_owned": "unknown", "ultimate_reward_owned": "unknown",
            "owned_item_ids": [], "missing_item_ids": [], "evidence_state": evidence_state,
            "evidence_sources": ["listing_text"] if evidence_state != "unknown" else [],
            "capture_date": None, "review_status": "needs_review",
        }

    for season_id, term in terms_by_id.items():
        escaped = re.escape(term)
        complete = re.search(rf"{escaped}.{{0,8}}(?:畢業|毕业)|(?:畢業|毕业).{{0,8}}{escaped}", text)
        partial = re.search(rf"{escaped}.{{0,8}}(?:半畢|半毕|[1-9]\s*/\s*[2-9]|進度|进度)|(?:半畢|半毕|[1-9]\s*/\s*[2-9]).{{0,8}}{escaped}", text)
        missing = re.search(rf"(?:缺|缺少|斷|断)\s*{escaped}|{escaped}\s*(?:缺|缺少|斷季|断季)", text)
        status = "confirmed_missing" if missing else "complete" if complete else "partial" if partial else "owned_not_complete"
        profile = make_profile(season_id, status)
        if re.search(rf"{escaped}.{{0,5}}(?:季卡|有卡|卡有)|(?:季卡|有卡).{{0,5}}{escaped}", text):
            profile["pass_owned"] = "yes"
        profiles_by_id[season_id] = profile

    by_order = {value: key for key, value in order.items()}
    for (left_match, left_id), (right_match, right_id) in zip(positions, positions[1:]):
        connector = text[left_match.end():right_match.start()]
        if not re.fullmatch(r"\s*(?:～|~|至|到|—|-)\s*", connector):
            continue
        if left_id not in order or right_id not in order:
            continue
        start, end = sorted((order[left_id], order[right_id]))
        snippet = text[left_match.start(): min(len(text), right_match.end() + 12)]
        if re.search(r"(?:全畢|全毕|皆畢|皆毕)", snippet):
            inferred_status, evidence = "complete", "text_claim"
        elif re.search(r"(?:無斷|无断|不斷|不断)", snippet):
            inferred_status, evidence = "owned_not_complete", "text_claim"
        else:
            inferred_status, evidence = "unknown", "unknown"
        for position in range(start, end + 1):
            season_id = by_order.get(position)
            if season_id and season_id not in profiles_by_id:
                profiles_by_id[season_id] = make_profile(season_id, inferred_status, evidence)
        if inferred_status in {"complete", "owned_not_complete"}:
            for endpoint in (left_id, right_id):
                if endpoint in profiles_by_id and profiles_by_id[endpoint]["status"] == "owned_not_complete":
                    profiles_by_id[endpoint]["status"] = inferred_status

    profiles = sorted(profiles_by_id.values(), key=lambda row: order.get(row["season_id"], 10_000))
    return profiles, list(dict.fromkeys(unresolved))


def season_summary(profiles: list[dict[str, Any]], order: dict[str, int]) -> dict[str, Any]:
    owned_statuses = {"complete", "partial", "owned_not_complete"}
    owned = [row for row in profiles if row["status"] in owned_statuses]
    complete = [row for row in profiles if row["status"] == "complete"]

    def segments(statuses: set[str]) -> list[dict[str, Any]]:
        positions = sorted((order[row["season_id"]], row["season_id"]) for row in profiles if row["status"] in statuses and row["season_id"] in order)
        groups: list[list[tuple[int, str]]] = []
        for value in positions:
            if not groups or value[0] != groups[-1][-1][0] + 1:
                groups.append([value])
            else:
                groups[-1].append(value)
        return [{"start_season_id": group[0][1], "end_season_id": group[-1][1], "season_ids": [value[1] for value in group]} for group in groups]

    return {
        "earliest_season_id": min(owned, key=lambda row: order.get(row["season_id"], 10_000))["season_id"] if owned else None,
        "earliest_complete_season_id": min(complete, key=lambda row: order.get(row["season_id"], 10_000))["season_id"] if complete else None,
        "complete_count": len(complete), "partial_count": sum(row["status"] == "partial" for row in profiles),
        "pass_not_complete_count": sum(row["pass_owned"] == "yes" and row["status"] != "complete" for row in profiles),
        "continuous_segments": segments(owned_statuses), "gap_segments": segments({"confirmed_missing"}),
        "evidence_state": "unknown" if not profiles else "text_claim",
    }


def resource_vector(text: str) -> dict[str, Any]:
    labels = {"white_candles": r"(?:白蠟|白蜡)(?:燭|烛)?", "hearts": r"(?:愛心|爱心)", "red_candles": r"(?:紅蠟|红蜡)(?:燭|烛)?", "season_candles": r"(?:季蠟|季蜡)(?:燭|烛)?"}
    values: dict[str, Any] = {}
    for key, label in labels.items():
        match = re.search(rf"{label}\s*[:：]?\s*(\d+)", text)
        values[key] = int(match.group(1)) if match else None
    return {"values": values, "capture_date": None, "evidence_state": "text_claim" if any(v is not None for v in values.values()) else "unknown"}


def binding_matrix(record: dict[str, Any], text: str) -> dict[str, Any]:
    known = {item.get("platform"): item.get("status", "unknown") for item in record.get("bindings", []) if isinstance(item, dict) and isinstance(item.get("platform"), str)}
    platforms = ["google", "apple", "facebook", "nintendo", "playstation", "steam", "huawei", "twitter"]
    labels = {"google": r"Google|GG", "apple": r"Apple|蘋果|苹果", "facebook": r"Facebook|FB", "nintendo": r"Nintendo|任天堂", "playstation": r"PlayStation|PSN|PS", "steam": r"Steam", "huawei": r"Huawei|華為|华为", "twitter": r"Twitter|推特"}
    results = []
    for platform in platforms:
        status = known.get(platform, "unknown")
        evidence = "text_claim" if platform in known else "unknown"
        match = re.search(labels[platform], text, re.I)
        if match:
            context = text[max(0, match.start() - 8): min(len(text), match.end() + 12)]
            if re.search(r"未綁|未绑|空綁|空绑|可綁|可绑", context): status = "available"
            elif re.search(r"可換綁|可换绑|可改綁|可改绑", context): status = "available"
            elif re.search(r"死綁|死绑|不出|遺失|遗失", context): status = "high_risk"
            elif re.search(r"同出", context): status = "available"
            elif status == "unknown": status = "mentioned_unknown"
            evidence = "text_claim"
        status = {"restricted": "high_risk", "included": "available", "transferable": "available", "unbound": "available"}.get(status, status)
        results.append({"platform": platform, "status": status, "evidence_state": evidence})
    risk_state = record.get("binding_details", {}).get("state", "unknown")
    risk_state = {"partial_or_unknown": "unknown", "clean_claimed": "low", "restricted": "restricted"}.get(risk_state, risk_state)
    if risk_state not in {"low", "restricted", "high_risk", "unknown"}:
        risk_state = "unknown"
    return {
        "platforms": results,
        "risk_state": risk_state,
    }


def map_completion(text: str) -> dict[str, Any]:
    standard = "complete" if re.search(r"(?:全圖|全图|全地圖|全地图).{0,3}(?:畢|毕)", text) else "partial" if re.search(r"(?:幾乎|几乎|近|大部分).{0,4}(?:全圖|全图|地圖|地图).{0,3}(?:畢|毕)", text) else "unknown"
    second = "complete" if re.search(r"(?:全二級斗|全二级斗|二級斗全|二级斗全)", text) else "partial" if re.search(r"二級斗|二级斗", text) else "unknown"
    return {"standard_maps": standard, "second_tier_capes": second, "evidence_state": "text_claim" if standard != "unknown" or second != "unknown" else "unknown"}


def ownership_history(text: str) -> str:
    if re.search(r"(?:三手|四手|五手|多任|多手)", text): return "multiple_owners"
    if re.search(r"二手|前號主|前号主", text): return "second_owner"
    if re.search(r"一手|自創|自创", text): return "first_owner"
    return "unknown"


def graduation_claims(text: str, aliases: dict[str, str]) -> list[str]:
    result = set()
    for match in SEASON_RE.finditer(text):
        season_id = aliases.get(match.group(0).casefold())
        context = text[max(0, match.start() - 6): min(len(text), match.end() + 8)]
        if season_id and re.search(r"畢業禮|毕业礼", context): result.add(season_id)
    return sorted(result)


def base_profile(record: dict[str, Any], account_id: str, aliases: dict[str, str], order: dict[str, int], graduation_items: dict[str, list[str]]) -> tuple[dict[str, Any], list[str]]:
    text = str(record.get("listing_text", ""))
    seasons, unresolved = season_profile(text, aliases, order)
    account_type = record.get("account_type_primary", "unknown")
    wing_state = record.get("wing_state", "unknown")
    graduation_seasons = graduation_claims(text, aliases)
    return ({
        "schema_version": SCHEMA_VERSION,
        "account_id": account_id,
        "source_listing_ids": [record["listing_id"]],
        "base_account": {"account_type": account_type, "wing_state": wing_state, "special_appearance": [], "short_id": "unknown"},
        "season_profiles": seasons,
        "season_summary": season_summary(seasons, order),
        "collection": {"owned_item_ids": [], "item_set_profiles": [], "graduation_rewards": sorted({item for season in graduation_seasons for item in graduation_items.get(season, [])}), "graduation_reward_season_ids": graduation_seasons, "collaboration_items": [], "bundle_claim_level": "unknown"},
        "map_completion": map_completion(text),
        "resources": resource_vector(text),
        "bindings": binding_matrix(record, text),
        "ownership_history": ownership_history(text),
        "trade_conditions": {"offer_kind": record.get("offer_kind", "unknown"), "entity_kind": record.get("entity_kind", "unknown"), "price_type": record.get("price_type", "unknown")},
        "evidence_quality": {"listing_text": record.get("evidence_quality", "unknown"), "image": "not_collected", "ocr": "not_collected"},
        "review_status": "needs_review" if unresolved else "unknown",
    }, unresolved)


def migrate(v3_root: Path, old_root: Path) -> dict[str, Any]:
    legacy_data = old_root / "data"
    batches = sorted(legacy_data.glob("batch-*.jsonl"))
    if len(batches) != 71:
        raise RuntimeError(f"expected 71 legacy batches, found {len(batches)}")
    raw_rows = [row for batch in batches for row in read_jsonl(batch)]
    normalized = read_jsonl(legacy_data / "v2.2" / "normalized-listings.jsonl")
    source_names = {str(row.get("source_group_name")) for row in normalized if row.get("source_group_name")}
    histories = read_jsonl(legacy_data / "v2" / "curated-listing-histories.jsonl")
    comparables = read_jsonl(legacy_data / "v2.4" / "market-comparables.jsonl")
    if len(raw_rows) != 1022 or len(normalized) != 1022 or len(histories) != 102 or len(comparables) != 102:
        raise RuntimeError("legacy counts do not match required 1022/102 contract")

    old_to_new: dict[str, str] = {}
    post_to_new: dict[str, str] = {}
    source_out: list[dict[str, Any]] = []
    for index, row in enumerate(raw_rows, 1):
        key = str(row.get("post_key", f"raw-{index}"))
        listing_id = f"listing_{index:04d}"
        post_to_new[key] = listing_id
        source_out.append({
            "schema_version": SCHEMA_VERSION,
            "listing_id": listing_id,
            "legacy_key": pseudo("legacy", key),
            "observed_at": safe_date(row.get("observed_date")),
            "post_date": None,
            "date_verified": False,
            "date_evidence_state": "unknown",
            "post_date_text": row.get("post_date_text") or "unknown",
            "listing_text": sanitize_market_text(row.get("listing_text", ""), source_names),
            "price_twd": row.get("price_twd"),
            "price_type": row.get("price_type", "unknown"),
            "status": row.get("status", "unknown"),
            "account_features": sanitize_market_text(row.get("account_features", ""), source_names),
            "risk_features": sanitize_market_text(row.get("risk_features", ""), source_names),
            "evidence_quality": row.get("evidence_quality", "unknown"),
            "exclusion_reason": row.get("exclusion_reason"),
        })

    normalized_out: list[dict[str, Any]] = []
    for index, row in enumerate(normalized, 1):
        old_id = str(row["listing_id"])
        new_id = post_to_new.get(str(row.get("source_post_key")), f"listing_{index:04d}")
        old_to_new[old_id] = new_id
        result = clean(row)
        result.update({
            "schema_version": SCHEMA_VERSION,
            "listing_id": new_id,
            "legacy_key": pseudo("legacy", str(row.get("source_post_key", old_id))),
            "post_date": safe_date(row.get("post_date_iso")),
            "observed_at": safe_date(row.get("observed_date")),
            "date_verified": bool(row.get("date_verified")),
        })
        result["listing_text"] = sanitize_market_text(result.get("listing_text", ""), source_names)
        result["feature_summary"] = [sanitize_market_text(value, source_names) for value in result.get("feature_summary", [])]
        result["risk_summary"] = [sanitize_market_text(value, source_names) for value in result.get("risk_summary", [])]
        if result["date_verified"] and not result["post_date"]:
            raise RuntimeError(f"verified date missing for {old_id}")
        result.pop("post_date_iso", None)
        normalized_out.append(result)
    normalized_by_listing = {row["listing_id"]: row for row in normalized_out}
    for source in source_out:
        normalized_row = normalized_by_listing[source["listing_id"]]
        source["post_date"] = normalized_row.get("post_date")
        source["date_verified"] = bool(normalized_row.get("date_verified"))
        source["date_evidence_state"] = "verified" if source["date_verified"] else "unknown"
    aliases = catalog_aliases(v3_root)
    season_order = {row["season_id"]: int(row["order_index"]) for row in read_jsonl(v3_root / "knowledge/seasons/seasons.jsonl")}
    item_index = item_aliases(v3_root)
    collection_index = collection_aliases(v3_root)
    items = read_jsonl(v3_root / "knowledge/items/items.jsonl")
    collaboration_item_ids = {row["item_id"] for row in items if row.get("collaboration") is True}
    ultimate_item_ids = {row["item_id"] for row in items if row.get("ultimate_reward") is True}
    graduation_items: dict[str, list[str]] = {}
    for item in items:
        if item.get("ultimate_reward") is True and isinstance(item.get("season_id"), str):
            graduation_items.setdefault(item["season_id"], []).append(item["item_id"])
    profiles: list[dict[str, Any]] = []
    unresolved_seasons: Counter[str] = Counter()
    for row in normalized_out:
        profile, unresolved = base_profile(row, f"account_{row['listing_id'].split('_')[1]}", aliases, season_order, graduation_items)
        profile["post_date"] = row.get("post_date")
        profile["date_verified"] = bool(row.get("date_verified"))
        profile["date_evidence_state"] = "verified" if profile["date_verified"] else "unknown"
        profiles.append(profile)
        unresolved_seasons.update(unresolved)

    comparable_by_id = {str(row["comparable_id"]): row for row in comparables}
    history_out: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    for history in histories:
        history_id = str(history["curated_v2_id"])
        comp = comparable_by_id.get(history_id)
        source_ids = [old_to_new.get(str(value)) for value in history.get("source_listing_ids", [])]
        if not comp or not all(source_ids):
            ledger.append({"legacy_history_id": history_id, "migration_status": "not_migrated", "reason": "missing comparable or normalized lineage"})
            continue
        primary = normalized_out[int(source_ids[0].split("_")[1]) - 1]
        post_date = primary.get("post_date")
        date_verified = bool(history.get("date_verified"))
        if date_verified and not post_date:
            ledger.append({"legacy_history_id": history_id, "migration_status": "not_migrated", "reason": "verified history has no traceable post_date"})
            continue
        sold_claimed = history.get("status") in {"sold", "sold_claimed", "reported_sold"} or history.get("price_type") in {"sold_explicit", "sold_last_ask"}
        legacy_price_type = str(history.get("price_type", "unknown"))
        price_type = {"asking": "asking", "reduced": "reduced", "instant": "instant", "instant_price": "instant", "quick_sale": "urgent_sale", "buyout": "normal_listing", "sold_explicit": "sold_claim", "sold_last_ask": "sold_claim"}.get(legacy_price_type, "unknown")
        legacy_status = str(history.get("status", "unknown"))
        status = {"sold": "sold_claimed", "sold_claimed": "sold_claimed", "reported_sold": "sold_claimed", "active": "active"}.get(legacy_status, "unknown")
        history_out.append({
            "schema_version": SCHEMA_VERSION,
            "history_id": f"history_{history_id.split('-')[-1]}",
            "legacy_key": pseudo("legacy_history", history_id),
            "source_listing_ids": source_ids,
            "account_id": f"account_{source_ids[0].split('_')[1]}",
            "selected_price_twd": history.get("selected_price_twd"),
            "price_history_twd": history.get("price_history_twd", []),
            "price_type": price_type,
            "status": status,
            "post_date": post_date,
            "observed_at": primary.get("observed_at"),
            "date_verified": date_verified,
            "date_evidence_state": "verified" if date_verified else "unverified",
            "currency": history.get("currency", "unknown"),
            "currency_verified": bool(history.get("currency_verified")),
            "server": history.get("server", "unknown"),
            "server_verified": bool(history.get("server_verified")),
            "offer_kind": history.get("offer_kind", "unknown"),
            "entity_kind": history.get("entity_kind", "unknown"),
            "market_pool": comp.get("pool", "unknown"),
            "legacy_features": [sanitize_market_text(value, source_names) for value in comp.get("feature_summary", [])],
            "legacy_risks": [sanitize_market_text(value, source_names) for value in comp.get("risk_summary", [])],
            "evidence_quality": history.get("evidence_quality", "unknown"),
            "sale_outcome": {
                "status": "sold_claimed" if sold_claimed else "not_observed",
                "completed_sale_price_twd": None,
                "verified": False,
            },
        })
        if history.get("entity_kind") == "single_account":
            profile = profiles[int(source_ids[0].split("_")[1]) - 1]
            evidence_text = " ".join(
                [str(primary.get("listing_text", ""))]
                + [str(value) for value in comp.get("feature_summary", [])]
                + [str(value) for value in comp.get("bundle_tags", [])]
            )
            owned_items = set(profile["collection"]["owned_item_ids"])
            set_claims = {row["set_id"]: row for row in profile["collection"]["item_set_profiles"]}
            for alias, (target_type, target_id) in collection_index.items():
                if not mentioned_without_negation(evidence_text.casefold(), alias):
                    continue
                if target_type == "item":
                    owned_items.add(target_id)
                else:
                    set_claims[target_id] = {
                        "set_id": target_id, "status": "mentioned_unverified",
                        "completion_ratio": None, "is_complete": None,
                        "owned_item_ids": [], "missing_item_ids": [],
                        "evidence_state": "text_claim", "review_status": "needs_review",
                    }
            profile["collection"]["owned_item_ids"] = sorted(owned_items)
            profile["collection"]["collaboration_items"] = sorted(owned_items & collaboration_item_ids)
            profile["collection"]["graduation_rewards"] = sorted(owned_items & ultimate_item_ids)
            profile["collection"]["item_set_profiles"] = [set_claims[key] for key in sorted(set_claims)]
        ledger.append({"legacy_history_id": history_id, "history_id": f"history_{history_id.split('-')[-1]}", "migration_status": "migrated", "source_listing_ids": source_ids, "date_repaired": date_verified, "post_date": post_date})

    review_rows = [{"term": term, "kind": "season_alias", "count": count, "review_status": "needs_review", "reason": "canonical season alias catalog unavailable or no mapping"} for term, count in sorted(unresolved_seasons.items())]
    unresolved_items: Counter[str] = Counter()
    for comparable in comparables:
        for term in comparable.get("bundle_tags", []):
            if isinstance(term, str) and term.casefold() not in collection_index:
                unresolved_items[term] += 1
    item_review_rows = [{"term": term, "kind": "item_alias", "count": count, "review_status": "needs_review", "reason": "legacy bundle tag has no canonical item alias mapping"} for term, count in sorted(unresolved_items.items())]
    canonical_price_types = {"asking", "reduced", "instant", "instant_price", "buyout", "quick_sale", "sold_explicit", "sold_last_ask"}
    price_types = Counter(str(row.get("price_type", "unknown")) for row in normalized_out)
    price_review_rows = [
        {"price_type": price_type, "count": count, "review_status": "needs_review", "reason": "non-canonical market price type; must not enter a normal single-account asking pool without explicit review"}
        for price_type, count in sorted(price_types.items()) if price_type not in canonical_price_types
    ]
    protected_group_names = {name for name in source_names if name and name.casefold() not in {"光遇", "sky光遇", "sky光·遇"}}
    serialized_output = "\n".join(json.dumps(row, ensure_ascii=False) for row in source_out + normalized_out + history_out)
    leaked_group_names = sorted(name for name in protected_group_names if name in serialized_output)
    if leaked_group_names:
        raise RuntimeError("legacy group-name sanitizer leak detected")
    write_jsonl(v3_root / "data" / "source" / "listings.jsonl", source_out)
    write_jsonl(v3_root / "data" / "normalized" / "listings.jsonl", normalized_out)
    write_jsonl(v3_root / "data" / "normalized" / "account-profiles.jsonl", profiles)
    write_jsonl(v3_root / "data" / "curated" / "histories.jsonl", history_out)
    write_jsonl(v3_root / "data" / "comparables" / "histories.jsonl", history_out)
    profile_by_id = {row["account_id"]: row for row in profiles}
    comparable_accounts = []
    for history in history_out:
        profile = dict(profile_by_id[history["account_id"]])
        profile.update({
            "comparable_id": history["history_id"], "history_id": history["history_id"],
            "selected_price_twd": history["selected_price_twd"], "price_history_twd": history["price_history_twd"],
            "price_type": history["price_type"], "status": history["status"], "post_date": history["post_date"],
            "observed_at": history["observed_at"], "date_verified": history["date_verified"],
            "currency": history["currency"], "currency_verified": history["currency_verified"],
            "server": history["server"], "server_verified": history["server_verified"],
            "offer_kind": history["offer_kind"], "entity_kind": history["entity_kind"],
            "market_pool": history["market_pool"], "market_evidence_quality": history["evidence_quality"],
            "sale_outcome": history["sale_outcome"],
        })
        comparable_accounts.append(profile)
    write_jsonl(v3_root / "data" / "comparables" / "accounts.jsonl", comparable_accounts)
    write_jsonl(v3_root / "data" / "review" / "unmapped-season-aliases.jsonl", review_rows)
    write_jsonl(v3_root / "data" / "review" / "unmapped-item-aliases.jsonl", item_review_rows)
    write_jsonl(v3_root / "data" / "review" / "price-type-review.jsonl", price_review_rows)
    write_jsonl(v3_root / "reports" / "migration" / "migration-ledger.jsonl", ledger)
    summary = {
        "schema_version": SCHEMA_VERSION, "legacy_batches": len(batches), "source_listings": len(source_out),
        "normalized_listings": len(normalized_out), "legacy_histories": len(histories), "migrated_histories": len(history_out),
        "not_migrated_histories": len(histories) - len(history_out), "verified_dates_in_normalized": sum(1 for row in normalized_out if row["date_verified"]),
        "verified_dates_repaired_in_histories": sum(1 for row in history_out if row["date_verified"]), "unmapped_season_terms": len(review_rows), "unmapped_item_terms": len(item_review_rows), "price_type_review_terms": len(price_review_rows),
        "legacy_group_names_sanitized": len(protected_group_names), "offline_only": True, "privacy": "source-group identity and locators removed; legacy keys are SHA-256 pseudonyms",
    }
    write_json(v3_root / "reports" / "migration" / "migration-summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline v2.4 to v3 P0 migration")
    parser.add_argument("--v3-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--legacy-root", type=Path)
    args = parser.parse_args()
    v3_root = args.v3_root.resolve()
    old_root = (args.legacy_root or legacy_root(v3_root)).resolve()
    print(json.dumps(migrate(v3_root, old_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
