"""Canonical, privacy-safe feature contract for authorized market rows.

The external supplier supplies only bounded structured account facts.  This
module is the one place where those facts become model inputs; callers must
not independently flatten the supplier payload.
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from tools.modeling.catalog_provenance import catalog_provenance, model_eligible_item_ids, read_jsonl

VERSION = "authorized-market-feature-payload-v1"
GROUPS = {"season_profiles", "item_sets", "collection", "resources", "map_completion", "base_account", "bindings", "ownership_history"}
ACCOUNT_TYPES = {"unknown", "winged_or_unspecified", "winged", "wingless"}
WING_STATES = ACCOUNT_TYPES
SEASON_STATUSES = {"complete", "partial", "owned_not_complete", "confirmed_missing", "unknown"}
YES_NO_UNKNOWN = {"yes", "no", "unknown"}
MAP_STATUS = {"complete", "partial", "unknown"}
PLATFORMS = {"google", "apple", "game_center", "facebook", "nintendo", "playstation", "steam", "huawei", "twitter"}
PLATFORM_STATUS = {"available", "unavailable", "mentioned_unknown", "unknown", "high_risk"}
RISK_STATES = {"low", "restricted", "high_risk", "unknown"}
OWNERSHIP = {"first_owner", "second_owner", "multiple_owners", "first_hand_claimed", "second_hand_or_more", "multiple_previous_owners", "unknown"}
STATE = {"owned", "confirmed_missing", "unknown"}
EVIDENCE = {"profile_claim", "text_claim", "unknown", "conflict"}


class MarketFeatureContractError(ValueError):
    pass


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise MarketFeatureContractError(reason)


def _canonical_items(root: Path) -> dict[str, dict[str, Any]]:
    return {row["item_id"]: row for row in read_jsonl(root / "knowledge/items/items.jsonl")}


def _canonical_seasons(root: Path) -> set[str]:
    return {row["season_id"] for row in read_jsonl(root / "knowledge/seasons/seasons.jsonl")}


def _expected_states(states: list[dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    items = _canonical_items(root)
    _require(len(states) == len(items), "item_states_not_exact_canonical_universe")
    ids = [row.get("item_id") for row in states if isinstance(row, dict)]
    _require(len(ids) == len(states) and len(set(ids)) == len(ids) and set(ids) == set(items), "item_states_not_exact_canonical_universe")
    result: list[dict[str, Any]] = []
    for supplied in states:
        _require(set(supplied) == {"item_id", "state", "evidence_state", "conflict"}, "item_state_has_unsupported_fields")
        item_id, state, evidence, conflict = supplied["item_id"], supplied["state"], supplied["evidence_state"], supplied["conflict"]
        _require(isinstance(item_id, str) and item_id in items, "item_state_unknown_canonical_item")
        _require(state in STATE and evidence in EVIDENCE and isinstance(conflict, bool), "item_state_value_invalid")
        item = items[item_id]
        eligible = item.get("verification_status") == "verified" and item.get("model_feature_status") == "eligible"
        review = "approved" if item.get("verification_status") == "verified" else "needs_review" if item.get("verification_status") == "needs_review" else "unknown"
        result.append({"item_id": item_id, "state": state, "evidence_state": evidence, "match_types": [], "matched_aliases": [], "matched_sources": [], "model_feature": eligible, "sensitivity_feature": not eligible, "conflict": conflict, "review_status": review})
    return sorted(result, key=lambda row: row["item_id"])


def _derive_sets(states: list[dict[str, Any]], root: Path) -> list[dict[str, Any]]:
    state_by_id = {row["item_id"]: row for row in states}
    result = []
    for entry in sorted(read_jsonl(root / "knowledge/sets/item-sets.jsonl"), key=lambda row: row["set_id"]):
        required = sorted(set(entry.get("required_item_ids", [])))
        owned = [item_id for item_id in required if state_by_id[item_id]["state"] == "owned"]
        missing = [item_id for item_id in required if state_by_id[item_id]["state"] == "confirmed_missing"]
        known = len(owned) + len(missing)
        model_feature = bool(required) and known == len(required) and all(state_by_id[item_id]["model_feature"] and not state_by_id[item_id]["conflict"] for item_id in required)
        result.append({"set_id": entry["set_id"], "owned_item_ids": owned, "confirmed_missing_item_ids": missing, "member_count": len(required), "known_member_count": known, "completion_ratio": len(owned) / len(required) if model_feature else None, "is_complete": len(owned) == len(required) if model_feature else None, "model_feature": model_feature})
    return result


def canonicalize(payload: Any, root: Path) -> dict[str, Any]:
    """Validate and materialize the exact model input from a signed payload."""
    # Intake validates the bare contract.  Generated training examples add
    # opaque account/catalog bindings outside it; accept that exact envelope
    # so authorization can replay the signed bytes without widening fields.
    if isinstance(payload, dict) and set(payload) == {"account_id", "catalog_provenance", "feature_contract_version", "feature_groups", "item_states"}:
        _require(isinstance(payload["account_id"], str) and payload["account_id"].startswith("account_"), "feature_payload_account_id_invalid")
        _require(payload["catalog_provenance"] == catalog_provenance(root), "feature_payload_catalog_provenance_stale")
        payload = {key: payload[key] for key in ("feature_contract_version", "feature_groups", "item_states")}
    _require(isinstance(payload, dict) and set(payload) == {"feature_contract_version", "feature_groups", "item_states"}, "feature_payload_has_unsupported_fields")
    _require(payload.get("feature_contract_version") == VERSION, "feature_contract_version_invalid")
    groups = payload.get("feature_groups")
    _require(isinstance(groups, dict) and set(groups) == GROUPS, "feature_groups_not_exact_contract")
    base = groups["base_account"]
    _require(isinstance(base, dict) and set(base) == {"account_type", "wing_state", "special_appearance"} and base["account_type"] in ACCOUNT_TYPES and base["wing_state"] in WING_STATES and base["special_appearance"] == [], "base_account_contract_invalid")
    seasons = groups["season_profiles"]
    _require(isinstance(seasons, list), "season_profiles_not_array")
    known_seasons = _canonical_seasons(root); normalized_seasons = []
    for row in seasons:
        _require(isinstance(row, dict) and set(row) == {"season_id", "status", "completion_ratio", "pass_owned", "ultimate_reward_owned"}, "season_profile_has_unsupported_fields")
        _require(row["season_id"] in known_seasons and row["status"] in SEASON_STATUSES and row["pass_owned"] in YES_NO_UNKNOWN and row["ultimate_reward_owned"] in YES_NO_UNKNOWN and (row["completion_ratio"] is None or isinstance(row["completion_ratio"], (int, float)) and not isinstance(row["completion_ratio"], bool) and 0 <= row["completion_ratio"] <= 1), "season_profile_value_invalid")
        normalized_seasons.append(copy.deepcopy(row))
    _require(len({row["season_id"] for row in normalized_seasons}) == len(normalized_seasons), "duplicate_season_profile")
    collection = groups["collection"]
    _require(isinstance(collection, dict) and set(collection) == {"bundle_claim_level"} and collection["bundle_claim_level"] in {"none", "partial", "complete", "unknown"}, "collection_contract_invalid")
    resources = groups["resources"]
    _require(isinstance(resources, dict) and set(resources) == {"values"} and isinstance(resources["values"], dict) and set(resources["values"]) == {"white_candles", "hearts", "red_candles", "season_candles"}, "resources_contract_invalid")
    for value in resources["values"].values(): _require(value is None or isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 1000000, "resource_value_invalid")
    maps = groups["map_completion"]
    _require(isinstance(maps, dict) and set(maps) == {"standard_maps", "second_tier_capes"} and maps["standard_maps"] in MAP_STATUS and maps["second_tier_capes"] in MAP_STATUS, "map_completion_contract_invalid")
    bindings = groups["bindings"]
    _require(isinstance(bindings, dict) and set(bindings) == {"risk_state", "platforms"} and bindings["risk_state"] in RISK_STATES and isinstance(bindings["platforms"], list), "bindings_contract_invalid")
    platforms = bindings["platforms"]
    _require(len(platforms) == len(PLATFORMS) and {row.get("platform") for row in platforms if isinstance(row, dict)} == PLATFORMS, "platforms_not_exact_contract")
    for row in platforms: _require(isinstance(row, dict) and set(row) == {"platform", "status"} and row["status"] in PLATFORM_STATUS, "platform_contract_invalid")
    _require(groups["ownership_history"] in OWNERSHIP, "ownership_history_invalid")
    # Set summaries are derived locally from item states and pinned catalog; no
    # Supplier-supplied count or eligibility flag cannot become model input.
    _require(groups["item_sets"] == [], "item_sets_must_be_empty_supplier_input")
    states = _expected_states(payload.get("item_states"), root)
    normalized_groups = {"base_account": copy.deepcopy(base), "season_profiles": sorted(normalized_seasons, key=lambda row: row["season_id"]), "collection": copy.deepcopy(collection), "resources": copy.deepcopy(resources), "map_completion": copy.deepcopy(maps), "bindings": {"risk_state": bindings["risk_state"], "platforms": sorted(copy.deepcopy(platforms), key=lambda row: row["platform"])}, "ownership_history": groups["ownership_history"], "item_sets": _derive_sets(states, root)}
    return {"feature_contract_version": VERSION, "feature_groups": normalized_groups, "item_states": states, "catalog_provenance": catalog_provenance(root)}


def feature_mapping_for_payload(payload: Any, root: Path) -> dict[str, Any]:
    """Return training/inference features through the sole authorized route."""
    normalized = canonicalize(payload, root)
    from modeling.train_elastic_net import feature_mapping
    return feature_mapping({"features": normalized["feature_groups"], "item_states": normalized["item_states"]}, model_eligible_item_ids(root))


def errors(payload: Any, root: Path) -> list[str]:
    try:
        canonicalize(payload, root)
    except (MarketFeatureContractError, OSError, KeyError, TypeError) as exc:
        return [str(exc)]
    return []
