#!/usr/bin/env python3
"""Rebuild comparable outputs and conservatively recover omitted strict listings.

The legacy 102 history records remain immutable migration evidence.  A small,
fully deterministic recovery pass may add an *additional* history only when a
normalized listing is demonstrably a normal seller listing for one account in
the confirmed TWD/international market pool.  This prevents a missing legacy
history join from silently discarding a usable price observation, while still
failing closed for unknown transaction types and editorially excluded rows.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8", newline="\n")


def price_semantic_review(listing: dict[str, Any], history: dict[str, Any]) -> dict[str, Any] | None:
    """Return an offline review gate for an amount that includes brokerage.

    No brokerage amount is inferred.  The marker merely prevents a mixed
    account-plus-brokerage observation from entering a model training line.
    """
    if "含仲" not in str(listing.get("listing_text", "")):
        return None
    return {
        "urgency": "urgent_sale" if history.get("price_type") == "urgent_sale" else "unknown",
        "brokerage_included": True,
        "evidence_state": "text_claim",
        "review_status": "needs_review",
        "reason_codes": ["brokerage_included_price"],
    }


def strict_recovery_predicates(listing: dict[str, Any], used_listing_ids: set[str]) -> list[str] | None:
    """Return documented strict predicates, or ``None`` when fail-closed.

    The recovery source is the normalized layer rather than an inferred market
    fact.  Therefore every predicate is explicit and no unknown value is ever
    treated as a match.  A non-empty editorial exclusion reason is also a hard
    stop: the recovery mechanism must not override a prior manual exclusion.
    """
    if listing.get("listing_id") in used_listing_ids:
        return None
    if listing.get("offer_kind") != "seller_listing" or listing.get("entity_kind") != "single_account":
        return None
    if listing.get("currency") != "TWD" or listing.get("currency_verified") is not True:
        return None
    if listing.get("server") != "international" or listing.get("server_verified") is not True:
        return None
    if listing.get("price_type") not in {"asking", "normal_listing"}:
        return None
    price = listing.get("price_twd")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0:
        return None
    if listing.get("status") != "active":
        return None
    if str(listing.get("exclusion_reason") or "").strip():
        return None
    # A known duplicate cluster is always disqualifying.  An absent automated
    # cluster is not evidence of uniqueness; a separate manual review is
    # required below before this predicate can be admitted.
    if listing.get("duplicate_cluster_id") is not None:
        return None
    return [
        "missing_from_legacy_curated_histories",
        "seller_listing",
        "single_account",
        "twd_verified",
        "international_server_verified",
        "active_normal_listing",
        "positive_asking_price",
        "no_editorial_exclusion",
        "no_known_duplicate_after_review",
    ]


def reviewed_facts(listing: dict[str, Any]) -> dict[str, Any]:
    """Return the canonical market facts a recovery reviewer actually approved.

    This deliberately binds source lineage as well as eligibility values.  It
    is not a content fingerprint and contains no player identity or post URL.
    """
    listing_id = str(listing.get("listing_id", ""))
    return {
        "listing_id": listing_id,
        "account_id": "account_" + listing_id.removeprefix("listing_"),
        "normalized_legacy_key": listing.get("legacy_key"),
        "price_twd": listing.get("price_twd"),
        "price_type": listing.get("price_type"),
        "status": listing.get("status"),
        "currency": listing.get("currency"),
        "currency_verified": listing.get("currency_verified"),
        "server": listing.get("server"),
        "server_verified": listing.get("server_verified"),
        "offer_kind": listing.get("offer_kind"),
        "entity_kind": listing.get("entity_kind"),
        "exclusion_reason": listing.get("exclusion_reason"),
        "duplicate_cluster_id": listing.get("duplicate_cluster_id"),
        "source_layer": "data/normalized/listings.jsonl",
        "legacy_history_match": "none",
    }


def deduplication_is_approved(value: Any) -> bool:
    return isinstance(value, dict) and value.get("method") == "manual_listing_lineage_review_v1" and value.get("result") == "no_known_duplicate" and isinstance(value.get("evidence"), str) and bool(value["evidence"].strip())


def predicate_hash(listing: dict[str, Any], predicates: list[str], deduplication: dict[str, Any]) -> str:
    """Bind approval to exact predicates *and* all canonical reviewed facts."""
    payload = json.dumps(
        {"predicate_version": "strict_normalized_listing_recovery_v1", "predicates": predicates, "reviewed_facts": reviewed_facts(listing), "deduplication": deduplication},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest().upper()


def recovered_history(listing: dict[str, Any], profile: dict[str, Any], predicates: list[str]) -> dict[str, Any]:
    """Create a traceable history without promoting sale or date evidence."""
    suffix = listing["listing_id"].removeprefix("listing_")
    return {
        "schema_version": "3.0-p0",
        "history_id": f"history_recovered_{suffix}",
        "legacy_key": f"recovery_{listing['legacy_key']}",
        "source_listing_ids": [listing["listing_id"]],
        "account_id": profile["account_id"],
        "selected_price_twd": listing["price_twd"],
        "price_history_twd": [listing["price_twd"]],
        "price_type": "normal_listing",
        "status": "active",
        "post_date": listing.get("post_date"),
        "observed_at": listing["observed_at"],
        "date_verified": listing.get("date_verified") is True,
        "date_evidence_state": "verified" if listing.get("date_verified") is True else "unknown",
        "currency": "TWD",
        "currency_verified": True,
        "server": "international",
        "server_verified": True,
        "offer_kind": "seller_listing",
        "entity_kind": "single_account",
        "market_pool": "strict_recovered_normal_listing",
        "legacy_features": list(listing.get("feature_summary") or []),
        "legacy_risks": list(listing.get("risk_summary") or []),
        "evidence_quality": listing.get("evidence_quality", "unknown"),
        "sale_outcome": {"status": "not_observed", "completed_sale_price_twd": None, "verified": False},
        "recovery": {
            "method": "strict_normalized_listing_recovery_v1",
            "reason": "Normalized listing met every strict normal-listing predicate but has no legacy curated history.",
            "source_layer": "data/normalized/listings.jsonl",
            "source_listing_id": listing["listing_id"],
            "legacy_history_match": "none",
            "predicates": predicates,
        },
    }


def recover_histories(root: Path, histories: list[dict[str, Any]], profiles: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Append only review-approved strict listings missing from legacy histories.

    Strict predicates are an eligibility gate, never an automatic promotion.
    Each recovered row requires a matching offline review decision whose stored
    predicate hash still agrees with the current normalized source.
    """
    legacy_histories = [row for row in histories if "recovery" not in row]
    used_listing_ids = {listing_id for history in legacy_histories for listing_id in history["source_listing_ids"]}
    decisions = {row["listing_id"]: row for row in read_jsonl(root / "data/review/strict-listing-recovery.jsonl")}
    recovered: list[dict[str, Any]] = []
    for listing in sorted(read_jsonl(root / "data/normalized/listings.jsonl"), key=lambda row: row["listing_id"]):
        decision = decisions.get(listing["listing_id"])
        if not decision or decision.get("review_status") != "approved":
            continue
        predicates = strict_recovery_predicates(listing, used_listing_ids)
        facts = reviewed_facts(listing)
        deduplication = decision.get("deduplication")
        if predicates is None or decision.get("predicates") != predicates or decision.get("reviewed_facts") != facts:
            continue
        if not deduplication_is_approved(deduplication):
            continue
        if decision.get("predicate_hash") != predicate_hash(listing, predicates, deduplication):
            continue
        account_id = "account_" + listing["listing_id"].removeprefix("listing_")
        profile = profiles.get(account_id)
        if profile is None or profile.get("source_listing_ids") != [listing["listing_id"]]:
            raise ValueError(f"strict recovery has no matching account profile: {listing['listing_id']}")
        recovered.append(recovered_history(listing, profile, predicates))
    return legacy_histories + recovered


def build(root: Path) -> dict[str, int]:
    profiles = {row["account_id"]: row for row in read_jsonl(root / "data/normalized/account-profiles.jsonl")}
    existing_histories = read_jsonl(root / "data/curated/histories.jsonl")
    legacy_histories = [row for row in existing_histories if "recovery" not in row]
    histories = recover_histories(root, existing_histories, profiles)
    listings = {row["listing_id"]: row for row in read_jsonl(root / "data/normalized/listings.jsonl")}
    for history in histories:
        source_ids = history.get("source_listing_ids", [])
        listing = listings.get(source_ids[0]) if isinstance(source_ids, list) and len(source_ids) == 1 else None
        semantic_review = price_semantic_review(listing, history) if listing is not None else None
        if semantic_review is not None:
            history["price_semantic_review"] = semantic_review
        else:
            history.pop("price_semantic_review", None)
    # The curated file is canonical for both legacy and recovered histories;
    # rewrites are deterministic and preserve all legacy rows byte-for-record.
    write_jsonl(root / "data/curated/histories.jsonl", histories)
    accounts = []
    for history in histories:
        if history["account_id"] not in profiles:
            raise ValueError(f"history has no account profile: {history['history_id']}")
        profile = dict(profiles[history["account_id"]])
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
        if "price_semantic_review" in history:
            profile["price_semantic_review"] = history["price_semantic_review"]
        accounts.append(profile)
    write_jsonl(root / "data/comparables/histories.jsonl", histories)
    write_jsonl(root / "data/comparables/accounts.jsonl", accounts)
    return {"legacy_histories": len(legacy_histories), "recovered_histories": len(histories) - len(legacy_histories), "histories": len(histories), "accounts": len(accounts)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(json.dumps(build(args.root.resolve()), ensure_ascii=False))


if __name__ == "__main__":
    main()
