#!/usr/bin/env python3
"""Build deterministic, offline, three-state item vectors from normalized claims.

This is a dictionary matcher, not OCR or a general language model.  A missing
mention is deliberately represented as ``unknown``.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STATES = {"owned", "confirmed_missing", "unknown"}
NEGATION_PREFIXES = ("沒有", "没有", "未有", "無", "无", "不含", "不包括", "缺少", "缺", "未擁有", "未拥有")


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize_text(value: str) -> str:
    """Lowercase and remove separators while retaining CJK and alphanumeric tokens."""
    return "".join(char.lower() for char in value if char.isalnum())


def load_catalog(root: Path = ROOT) -> tuple[dict[str, dict[str, Any]], dict[str, set[str]]]:
    items = {row["item_id"]: row for row in _rows(root / "knowledge/items/items.jsonl")}
    aliases: dict[str, set[str]] = defaultdict(set)
    for item_id, item in items.items():
        for value in [item.get("canonical_name_zh_tw"), item.get("canonical_name_en"), *item.get("aliases", [])]:
            if isinstance(value, str) and len(normalize_text(value)) >= 2:
                aliases[normalize_text(value)].add(item_id)
    for row in _rows(root / "knowledge/aliases/item-aliases.jsonl"):
        if row.get("target_type") == "item" and row.get("target_id") in items:
            value = row.get("normalized_alias") or row.get("alias_text")
            if isinstance(value, str) and len(normalize_text(value)) >= 2:
                aliases[normalize_text(value)].add(row["target_id"])
    # Ambiguous spelling never identifies an item automatically.
    return items, {token: ids for token, ids in aliases.items() if len(ids) == 1}


def _profile_item_states(profile: dict[str, Any]) -> tuple[set[str], set[str]]:
    owned: set[str] = set(); missing: set[str] = set()
    collection = profile.get("collection") if isinstance(profile.get("collection"), dict) else {}
    for key in ("owned_item_ids", "graduation_rewards", "collaboration_items", "bundle_item_ids", "event_limited_item_ids"):
        owned.update(value for value in collection.get(key, []) if isinstance(value, str))
    for season in profile.get("season_profiles", []):
        if isinstance(season, dict):
            owned.update(value for value in season.get("owned_item_ids", []) if isinstance(value, str))
            missing.update(value for value in season.get("missing_item_ids", []) if isinstance(value, str))
    return owned, missing


def _text_matches(text: str, aliases: dict[str, set[str]]) -> dict[str, dict[str, Any]]:
    normalized = normalize_text(text)
    matches: dict[str, dict[str, Any]] = {}
    # Stable ordering avoids aliases of the same target changing output ordering.
    for alias in sorted(aliases, key=lambda item: (-len(item), item)):
        position = normalized.find(alias)
        if position < 0:
            continue
        item_id = next(iter(aliases[alias]))
        entry = matches.setdefault(item_id, {"aliases": set(), "negative": False, "positive": False})
        entry["aliases"].add(alias)
        before = normalized[max(0, position - 6):position]
        if any(before.endswith(prefix) for prefix in NEGATION_PREFIXES):
            entry["negative"] = True
        else:
            entry["positive"] = True
    return matches


def _item_state(item_id: str, item: dict[str, Any], owned: set[str], missing: set[str], text_matches: dict[str, dict[str, Any]]) -> dict[str, Any]:
    found = text_matches.get(item_id, {"aliases": set(), "negative": False, "positive": False})
    positive = item_id in owned or found["positive"]
    negative = item_id in missing or found["negative"]
    conflict = positive and negative
    if conflict:
        state, evidence = "unknown", "conflict"
    elif positive:
        state = "owned"; evidence = "profile_claim" if item_id in owned else "text_claim"
    elif negative:
        state = "confirmed_missing"; evidence = "profile_claim" if item_id in missing else "text_claim"
    else:
        state, evidence = "unknown", "unknown"
    match_types: list[str] = []
    if item_id in owned: match_types.append("profile_owned")
    if item_id in missing: match_types.append("profile_missing")
    if found["aliases"]:
        match_types.append("alias")
    if found["negative"]: match_types.append("explicit_negative")
    # Names are aliases by design; report canonical-name separately only when exact.
    canonical_tokens = {normalize_text(str(item.get(key, ""))) for key in ("canonical_name_zh_tw", "canonical_name_en")}
    if canonical_tokens.intersection(found["aliases"]): match_types.append("canonical_name")
    status = item.get("verification_status", "unknown")
    # Catalog policy may additionally exclude a verified non-valuation item.
    # Older fixtures without the policy field retain the verified default.
    feature_status = item.get("model_feature_status", "eligible" if status == "verified" else "excluded_pending_verification")
    model_feature = status == "verified" and feature_status == "eligible"
    return {"item_id": item_id, "state": state, "evidence_state": evidence,
            "match_types": sorted(set(match_types)), "matched_aliases": sorted(found["aliases"]),
            "model_feature": model_feature, "sensitivity_feature": not model_feature and feature_status == "excluded_pending_verification",
            "conflict": conflict, "review_status": "approved" if status == "verified" else "needs_review" if status == "needs_review" else "unknown"}


def build_vector(profile: dict[str, Any], listing: dict[str, Any], items: dict[str, dict[str, Any]], aliases: dict[str, set[str]], root: Path = ROOT) -> dict[str, Any]:
    owned, missing = _profile_item_states(profile)
    text_matches = _text_matches(str(listing.get("listing_text", "")), aliases)
    item_states = [_item_state(item_id, items[item_id], owned, missing, text_matches) for item_id in sorted(items)]
    collection = profile.get("collection") if isinstance(profile.get("collection"), dict) else {}
    sets = {row["set_id"]: row for row in _rows(root / "knowledge/sets/item-sets.jsonl")}
    set_profiles = []
    for set_id, set_data in sorted(sets.items()):
        member_ids = set(set_data.get("required_item_ids", [])) | set(set_data.get("optional_item_ids", []))
        owned_members = sorted(member_ids & {row["item_id"] for row in item_states if row["state"] == "owned"})
        set_profiles.append({"set_id": set_id, "owned_item_ids": owned_members, "member_count": len(member_ids), "completion_ratio": (len(owned_members) / len(member_ids)) if member_ids else None, "is_complete": bool(member_ids) and len(owned_members) == len(member_ids)})
    feature_groups = {
        "season_profiles": profile.get("season_profiles", []),
        "item_sets": set_profiles,
        "collection": {"graduation_rewards": sorted(set(collection.get("graduation_rewards", []))), "graduation_reward_season_ids": sorted(set(collection.get("graduation_reward_season_ids", []))), "collaboration_items": sorted(set(collection.get("collaboration_items", []))), "bundle_item_ids": sorted(set(collection.get("bundle_item_ids", []))), "event_limited_item_ids": sorted(set(collection.get("event_limited_item_ids", [])))},
        "resources": profile.get("resources", {"values": {}, "evidence_state": "unknown"}),
        "map_completion": profile.get("map_completion", {"evidence_state": "unknown"}),
        "base_account": profile.get("base_account", {}),
        "bindings": profile.get("bindings", {}),
        "ownership_history": profile.get("ownership_history", "unknown"),
    }
    return {"schema_version": "3.1-p1", "vector_id": "vector_" + profile["account_id"], "account_id": profile["account_id"], "source_listing_ids": profile["source_listing_ids"], "item_states": item_states, "feature_groups": feature_groups,
            "parser_summary": {"method": "offline_alias_rules_v1", "catalog_item_count": len(items), "approved_item_count": sum(row["model_feature"] for row in item_states), "needs_review_item_count": sum(row["sensitivity_feature"] for row in item_states), "text_matched_item_count": len(text_matches), "conflict_item_count": sum(row["conflict"] for row in item_states)},
            "review_status": "needs_review" if any(row["review_status"] != "approved" for row in item_states) else "approved"}


def build_vectors(root: Path = ROOT) -> list[dict[str, Any]]:
    items, aliases = load_catalog(root)
    listings = {row["listing_id"]: row for row in _rows(root / "data/normalized/listings.jsonl")}
    vectors = []
    for profile in sorted(_rows(root / "data/normalized/account-profiles.jsonl"), key=lambda row: row["account_id"]):
        source_ids = profile.get("source_listing_ids", [])
        if len(source_ids) != 1 or source_ids[0] not in listings:
            raise ValueError(f"{profile.get('account_id')}: exactly one known source listing is required")
        vectors.append(build_vector(profile, listings[source_ids[0]], items, aliases, root))
    return vectors


def main() -> None:
    parser = argparse.ArgumentParser(description="Build offline three-state account item vectors.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    root = args.root.resolve(); output = args.output or root / "data/modeling/account-item-vectors.jsonl"
    rows = build_vectors(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
