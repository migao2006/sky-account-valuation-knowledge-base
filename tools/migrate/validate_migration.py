#!/usr/bin/env python3
"""Validate the P0 migration output without external dependencies or network access."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path


FORBIDDEN = {"source_group_id", "source_group_name", "source_post_key", "post_url", "profile_url", "author", "author_name", "uid", "group_id", "locator"}


def rows(path: Path):
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def keys(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from keys(child)


def valid_date(value):
    try:
        dt.date.fromisoformat(value)
        return True
    except (TypeError, ValueError):
        return False


def validate(root: Path) -> dict:
    source = rows(root / "data/source/listings.jsonl")
    normalized = rows(root / "data/normalized/listings.jsonl")
    profiles = rows(root / "data/normalized/account-profiles.jsonl")
    histories = rows(root / "data/curated/histories.jsonl")
    comparable = rows(root / "data/comparables/histories.jsonl")
    comparable_accounts = rows(root / "data/comparables/accounts.jsonl")
    price_type_review = rows(root / "data/review/price-type-review.jsonl")
    all_rows = source + normalized + profiles + histories + comparable
    forbidden = sorted({key for row in all_rows for key in keys(row) if key in FORBIDDEN})
    bad_dates = [row["listing_id"] for row in normalized if row.get("date_verified") and not valid_date(row.get("post_date"))]
    bad_history_dates = [row["history_id"] for row in histories if row.get("date_verified") and not valid_date(row.get("post_date"))]
    source_ids = {row["listing_id"] for row in normalized}
    broken_lineage = [row["history_id"] for row in histories if not set(row["source_listing_ids"]).issubset(source_ids)]
    normalized_by_id = {row["listing_id"]: row for row in normalized}
    profile_by_id = {row["account_id"]: row for row in profiles}
    source_by_id = {row["listing_id"]: row for row in source}
    # Source rows preserve only raw post-date text by contract; normalized rows
    # are the first typed-date layer.  Profiles retain date lineage by their
    # required source listing reference, not a duplicate typed date.
    source_date_breaks = [row["listing_id"] for row in source if not valid_date(row.get("observed_at"))]
    profile_date_breaks = [row["listing_id"] for row in normalized if profile_by_id.get("account_" + row["listing_id"].split("_")[-1], {}).get("source_listing_ids") != [row["listing_id"]]]
    date_history_breaks = [row["history_id"] for row in histories if row["date_verified"] and any(normalized_by_id[item].get("post_date") != row["post_date"] for item in row["source_listing_ids"])]
    sold_semantic_breaks = [row["history_id"] for row in histories if row["sale_outcome"].get("status") == "sold_claimed" and (row["sale_outcome"].get("verified") or row["sale_outcome"].get("completed_sale_price_twd") is not None)]
    profile_coverage = {
        "season_profiles": sum(bool(row.get("season_profiles")) for row in profiles),
        "map_completion_claims": sum(row.get("map_completion", {}).get("standard_maps") != "unknown" for row in profiles),
        "ownership_claims": sum(row.get("ownership_history") != "unknown" for row in profiles),
        "binding_claims": sum(any(platform.get("status") != "unknown" for platform in row.get("bindings", {}).get("platforms", [])) for row in profiles),
        "graduation_claims": sum(bool(row.get("collection", {}).get("graduation_rewards") or row.get("collection", {}).get("graduation_reward_season_ids")) for row in profiles),
    }
    same_history = histories == comparable
    result = {
        "source_listings": len(source), "normalized_listings": len(normalized), "account_profiles": len(profiles),
        "curated_histories": len(histories), "comparable_histories": len(comparable), "comparable_accounts": len(comparable_accounts),
        "verified_normalized_dates": sum(bool(row.get("date_verified")) for row in normalized),
        "verified_history_dates": sum(bool(row.get("date_verified")) for row in histories),
        "forbidden_identity_keys": forbidden, "invalid_verified_listing_dates": bad_dates,
        "invalid_verified_history_dates": bad_history_dates, "broken_history_lineage": broken_lineage,
        "source_date_breaks": source_date_breaks, "profile_date_breaks": profile_date_breaks,
        "date_history_breaks": date_history_breaks, "sold_semantic_breaks": sold_semantic_breaks,
        "price_type_review_rows": len(price_type_review), "profile_coverage": profile_coverage,
        "comparables_match_curated": same_history,
    }
    # Graduation-reward evidence may genuinely be absent; its zero count is a
    # coverage finding, not a license to fabricate ownership.  The structural
    # production coverage gate applies to dimensions that the legacy snapshot
    # actually contains.
    coverage_complete = all(profile_coverage[key] > 0 for key in ("season_profiles", "map_completion_claims", "ownership_claims", "binding_claims"))
    result["valid"] = result["source_listings"] == result["normalized_listings"] == result["account_profiles"] == 1022 and result["curated_histories"] == result["comparable_histories"] == result["comparable_accounts"] == 102 and not forbidden and not bad_dates and not bad_history_dates and not broken_lineage and not source_date_breaks and not profile_date_breaks and not date_history_breaks and not sold_semantic_breaks and result["price_type_review_rows"] > 0 and coverage_complete and same_history
    return result


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    result = validate(root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["valid"] else 1)
