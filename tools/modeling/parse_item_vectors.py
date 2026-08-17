#!/usr/bin/env python3
"""Build deterministic, offline, three-state item vectors from normalized claims.

This is a dictionary matcher, not OCR or a general language model.  A missing
mention is deliberately represented as ``unknown``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.modeling.catalog_provenance import catalog_provenance  # noqa: E402

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
    verified_tokens: dict[str, set[str]] = defaultdict(set)
    for item_id, item in items.items():
        for value in [item.get("canonical_name_zh_tw"), item.get("canonical_name_en")]:
            if isinstance(value, str) and len(normalize_text(value)) >= 2:
                aliases[normalize_text(value)].add(item_id)
        # An entity-level verification can make its evidenced English
        # canonical identity searchable for modeling.  Localized names and
        # player aliases require their own approved alias record below.
        if item.get("verification_status") == "verified" and item.get("model_feature_status") == "eligible" and isinstance(item.get("canonical_name_en"), str):
            verified_tokens[item_id].add(normalize_text(item["canonical_name_en"]))
        for value in item.get("aliases", []):
            # Verifying the entity does not promote its unreviewed player
            # nicknames.  Short aliases require an approved alias-master row.
            if isinstance(value, str) and len(normalize_text(value)) >= 3:
                aliases[normalize_text(value)].add(item_id)
    for row in _rows(root / "knowledge/aliases/item-aliases.jsonl"):
        if row.get("target_type") == "item" and row.get("target_id") in items:
            value = row.get("normalized_alias") or row.get("alias_text")
            if isinstance(value, str) and len(normalize_text(value)) >= 2 and (
                row.get("verification_status") == "verified" or len(normalize_text(value)) >= 3
            ):
                aliases[normalize_text(value)].add(row["target_id"])
                # Exact-English eligibility intentionally does not promote an
                # alias-master row (including Chinese aliases) into a model
                # observation token.  It remains useful only for review.
    for item_id, item in items.items():
        # Runtime-only audit metadata.  It is never serialized into the
        # canonical item master or vector, but prevents an unreviewed alias
        # from turning a newly verified item into an owned model observation.
        item["_model_verified_tokens"] = sorted(token for token in verified_tokens[item_id] if token)
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


def _text_matches(text: str, aliases: dict[str, set[str]], source: str) -> dict[str, dict[str, Any]]:
    normalized = normalize_text(text)
    matches: dict[str, dict[str, Any]] = {}
    occurrences: list[tuple[int, int, str]] = []
    for alias in aliases:
        position = normalized.find(alias)
        while position >= 0:
            occurrences.append((position, position + len(alias), alias))
            position = normalized.find(alias, position + 1)
    selected: list[tuple[int, int, str]] = []
    for start, end, alias in sorted(occurrences, key=lambda row: (-(row[1] - row[0]), row[0], row[2])):
        if any(start < chosen_end and chosen_start < end for chosen_start, chosen_end, _ in selected):
            continue
        selected.append((start, end, alias))
    for position, _, alias in sorted(selected):
        item_id = next(iter(aliases[alias]))
        entry = matches.setdefault(item_id, {"aliases": set(), "negative": False, "positive": False, "sources": set()})
        entry["aliases"].add(alias)
        entry["sources"].add(source)
        before = normalized[max(0, position - 6):position]
        if any(before.endswith(prefix) for prefix in NEGATION_PREFIXES):
            entry["negative"] = True
        else:
            entry["positive"] = True
    return matches


def _item_state(item_id: str, item: dict[str, Any], owned: set[str], missing: set[str], text_matches: dict[str, dict[str, Any]]) -> dict[str, Any]:
    found = text_matches.get(item_id, {"aliases": set(), "negative": False, "positive": False, "sources": set()})
    raw_positive = item_id in owned or found["positive"]
    raw_negative = item_id in missing or found["negative"]
    status = item.get("verification_status", "unknown")
    feature_status = item.get("model_feature_status", "eligible" if status == "verified" else "excluded_pending_verification")
    catalog_model_eligible = status == "verified" and feature_status == "eligible"
    if catalog_model_eligible:
        approved_tokens = set(item.get("_model_verified_tokens", []))
        approved_match = bool(approved_tokens.intersection(found["aliases"]))
        # Migrated profile item IDs were themselves derived from legacy alias
        # matches and do not carry item-level identity evidence.  A verified
        # item becomes known only when this vector observes an approved exact
        # token; otherwise the claim remains unknown rather than inheriting a
        # possibly unreviewed alias from the profile.
        positive = found["positive"] and approved_match
        negative = found["negative"] and approved_match
        conflict = (positive and raw_negative) or (negative and raw_positive)
    else:
        positive, negative = raw_positive, raw_negative
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
    # Catalog policy may additionally exclude a verified non-valuation item.
    # ``model_feature`` denotes catalog eligibility; the state above still
    # stays unknown unless its observation token is independently approved.
    model_feature = catalog_model_eligible
    return {"item_id": item_id, "state": state, "evidence_state": evidence,
            "match_types": sorted(set(match_types)), "matched_aliases": sorted(found["aliases"]),
            "matched_sources": sorted(found["sources"]),
            "model_feature": model_feature, "sensitivity_feature": not model_feature and feature_status == "excluded_pending_verification",
            "conflict": conflict, "review_status": "approved" if status == "verified" else "needs_review" if status == "needs_review" else "unknown"}


def _set_profile(set_id: str, set_data: dict[str, Any], item_states: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Return an auditable, fail-closed aggregate for one canonical set.

    A set ratio is a derived model feature, not a substitute for unobserved
    member state.  It is therefore available only when every *required*
    member is a canonical, model-eligible item and every required member has
    an explicit owned or confirmed-missing state.  Optional members are never
    used to infer completion.  Sets with no required members are descriptive
    only and cannot produce a completion feature.
    """
    required_ids = sorted({item_id for item_id in set_data.get("required_item_ids", []) if isinstance(item_id, str)})
    state_by_id = {item_id: item_states.get(item_id) for item_id in required_ids}
    owned_ids = sorted(item_id for item_id, state in state_by_id.items() if state and state["state"] == "owned")
    missing_ids = sorted(item_id for item_id, state in state_by_id.items() if state and state["state"] == "confirmed_missing")
    known_ids = sorted(item_id for item_id, state in state_by_id.items() if state and state["state"] in {"owned", "confirmed_missing"})
    all_required_eligible = bool(required_ids) and all(
        state is not None and state["model_feature"] is True and state["review_status"] == "approved"
        for state in state_by_id.values()
    )
    all_required_known = len(known_ids) == len(required_ids)
    model_feature = all_required_eligible and all_required_known
    return {
        "set_id": set_id,
        # These IDs are audit evidence only.  Training must consult
        # ``model_feature`` before using any set-level aggregate.
        "owned_item_ids": owned_ids,
        "confirmed_missing_item_ids": missing_ids,
        "member_count": len(required_ids),
        "known_member_count": len(known_ids),
        "completion_ratio": (len(owned_ids) / len(required_ids)) if model_feature else None,
        "is_complete": (len(owned_ids) == len(required_ids)) if model_feature else None,
        "model_feature": model_feature,
    }


def build_vector(profile: dict[str, Any], listing: dict[str, Any], items: dict[str, dict[str, Any]], aliases: dict[str, set[str]], root: Path = ROOT) -> dict[str, Any]:
    owned, missing = _profile_item_states(profile)
    text_claims_allowed = listing.get("offer_kind") == "seller_listing" and listing.get("entity_kind") == "single_account"
    source_texts = {
        "listing_text": str(listing.get("listing_text", "")) if text_claims_allowed else "",
        "normalized_feature_summary": "\n".join(value for value in listing.get("feature_summary", []) if isinstance(value, str)) if text_claims_allowed else "",
    }
    text_matches: dict[str, dict[str, Any]] = {}
    for source, text in source_texts.items():
        for item_id, matched in _text_matches(text, aliases, source).items():
            entry = text_matches.setdefault(item_id, {"aliases": set(), "negative": False, "positive": False, "sources": set()})
            entry["aliases"].update(matched["aliases"])
            entry["sources"].update(matched["sources"])
            entry["negative"] = entry["negative"] or matched["negative"]
            entry["positive"] = entry["positive"] or matched["positive"]
    item_states = [_item_state(item_id, items[item_id], owned, missing, text_matches) for item_id in sorted(items)]
    collection = profile.get("collection") if isinstance(profile.get("collection"), dict) else {}
    sets = {row["set_id"]: row for row in _rows(root / "knowledge/sets/item-sets.jsonl")}
    item_states_by_id = {row["item_id"]: row for row in item_states}
    set_profiles = []
    for set_id, set_data in sorted(sets.items()):
        set_profiles.append(_set_profile(set_id, set_data, item_states_by_id))
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
    return {"schema_version": "3.1-p1", "vector_id": "vector_" + profile["account_id"], "account_id": profile["account_id"], "source_listing_ids": profile["source_listing_ids"], "catalog_provenance": catalog_provenance(root), "item_states": item_states, "feature_groups": feature_groups,
            "parser_summary": {"method": "offline_alias_rules_v1", "catalog_item_count": len(items), "approved_item_count": sum(row["model_feature"] for row in item_states), "needs_review_item_count": sum(row["sensitivity_feature"] for row in item_states), "text_matched_item_count": len(text_matches), "listing_text_matched_item_count": sum("listing_text" in row["matched_sources"] for row in item_states), "feature_summary_matched_item_count": sum("normalized_feature_summary" in row["matched_sources"] for row in item_states), "profile_owned_item_count": len(owned), "profile_missing_item_count": len(missing), "conflict_item_count": sum(row["conflict"] for row in item_states)},
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
