#!/usr/bin/env python3
"""Build a fail-closed lexical catalog review sidecar for account listings.

This deliberately is *not* an ownership resolver.  It emits one anonymous,
review-only row per account, and only scans a listing where both the listing
and its profile independently say it is a seller's single-account offer.
Raw text, matched aliases, locations, and URLs never enter the output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

MATCHER_VERSION = "p2.9-cjk-longest-leftmost-review-only-v1"
_NEGATIVE_PREFIX = re.compile(r"(?:沒有|無|未有|缺少|缺|不含|不帶|未包含)$")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _is_cjk(char: str) -> bool:
    return "CJK" in unicodedata.name(char, "") or "HIRAGANA" in unicodedata.name(char, "") or "KATAKANA" in unicodedata.name(char, "")


def normalize_key(value: str) -> str:
    return "".join(char.casefold() for char in value if char.isalnum())


def is_eligible_cjk_key(value: str) -> bool:
    normalized = normalize_key(value)
    return len(normalized) >= 3 and all(_is_cjk(char) for char in normalized)


def _merge_assertions(values: set[str]) -> str:
    return "conflict" if values == {"positive", "negative"} else next(iter(values))


def _occurrence_assertion(text: str, start: int) -> str:
    # A deliberately narrow local rule.  It supplies a review label only and
    # never converts a lexical occurrence into ownership or confirmed absence.
    prefix = normalize_key(text[max(0, start - 4):start])
    return "negative" if _NEGATIVE_PREFIX.search(prefix) else "positive"


def _matching_keys(index_rows: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    owners: dict[str, set[str]] = defaultdict(set)
    all_keys: list[tuple[str, dict[str, Any]]] = []
    for row in index_rows:
        for value in row.get("lookup_keys", []):
            if not isinstance(value, str) or not is_eligible_cjk_key(value):
                continue
            key = normalize_key(value)
            owners[key].add(str(row["query_entity_id"]))
            all_keys.append((key, row))
    collisions = {key for key, entity_ids in owners.items() if len(entity_ids) > 1}
    # Query-index collision data is authoritative too, including collisions
    # that originated from a non-CJK lookup representation.
    collisions.update(
        normalize_key(key)
        for row in index_rows for key in row.get("ambiguous_lookup_keys", [])
        if isinstance(key, str) and normalize_key(key)
    )
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for key, row in all_keys:
        if key not in collisions:
            unique[(key, str(row["query_entity_id"]))] = row
    return [(key, row) for (key, _), row in unique.items()]


def _scan(text: str, keys: list[tuple[str, dict[str, Any]]]) -> dict[str, set[str]]:
    normalized = normalize_key(text)
    candidates: list[tuple[int, int, str, dict[str, Any]]] = []
    for key, row in keys:
        start = normalized.find(key)
        while start >= 0:
            candidates.append((start, start + len(key), key, row))
            start = normalized.find(key, start + 1)
    # Longest then entity ID makes overlaps deterministic.  The final sweep is
    # leftmost non-overlap across all query entities, rather than per entity.
    candidates.sort(key=lambda entry: (entry[0], -(entry[1] - entry[0]), entry[2], entry[3]["query_entity_id"]))
    selected: list[tuple[int, int, str, dict[str, Any]]] = []
    cursor = -1
    for candidate in candidates:
        if candidate[0] >= cursor:
            selected.append(candidate); cursor = candidate[1]
    assertions: dict[str, set[str]] = defaultdict(set)
    for start, _end, _key, row in selected:
        assertions[str(row["query_entity_id"])].add(_occurrence_assertion(normalized, start))
    return assertions


def build_account_catalog_resolution(accounts: list[dict[str, Any]], listings: list[dict[str, Any]], index_rows: list[dict[str, Any]], *, index_sha256: str) -> list[dict[str, Any]]:
    """Return one deterministic, review-only row for every account profile."""
    listing_by_id = {row.get("listing_id"): row for row in listings}
    if len(listing_by_id) != len(listings) or None in listing_by_id:
        raise ValueError("normalized listings must have unique listing_id values")
    if len({row.get("account_id") for row in accounts}) != len(accounts):
        raise ValueError("account profiles must have unique account_id values")
    if len({row.get("query_entity_id") for row in index_rows}) != len(index_rows):
        raise ValueError("catalog query index must have unique query_entity_id values")
    by_id = {str(row["query_entity_id"]): row for row in index_rows}
    keys = _matching_keys(index_rows)
    rows: list[dict[str, Any]] = []
    for account in sorted(accounts, key=lambda value: str(value["account_id"])):
        source_ids = account.get("source_listing_ids", [])
        listing = listing_by_id.get(source_ids[0]) if len(source_ids) == 1 else None
        consistent = bool(
            listing and account.get("trade_conditions", {}).get("offer_kind") == listing.get("offer_kind")
            and account.get("trade_conditions", {}).get("entity_kind") == listing.get("entity_kind")
        )
        eligible = bool(consistent and listing.get("offer_kind") == "seller_listing" and listing.get("entity_kind") == "single_account")
        listing_id = source_ids[0] if len(source_ids) == 1 else None
        listing_text = listing.get("listing_text", "") if listing else ""
        summary = listing.get("feature_summary", []) if listing else []
        row: dict[str, Any] = {
            "schema_version": "1.0-p2.9", "account_id": account["account_id"], "listing_id": listing_id,
            "matching_eligibility": "eligible" if eligible else "suppressed_not_seller_single_account",
            "matcher_version": MATCHER_VERSION, "catalog_query_index_sha256": index_sha256,
            "listing_text_sha256": sha256_bytes(listing_text.encode("utf-8")),
            "normalized_feature_summary_sha256": sha256_bytes(canonical_json(summary)),
            "review_only": True, "model_feature": False, "matches": [],
        }
        if eligible:
            assertions = _scan(listing_text, keys)
            # The normalized feature summary is a separately derived input;
            # merge its lexical assertions without retaining the phrases.
            for entity_id, values in _scan("\n".join(value for value in summary if isinstance(value, str)), keys).items():
                assertions.setdefault(entity_id, set()).update(values)
            for entity_id, values in sorted(assertions.items()):
                source = by_id[entity_id]
                row["matches"].append({
                    "query_entity_id": entity_id, "query_entity_type": source["query_entity_type"],
                    "truth_level": source["truth_level"], "verification_status": source["verification_status"],
                    "review_status": source["review_status"], "assertion": _merge_assertions(values),
                    "review_only": True, "model_feature": False,
                })
        rows.append(row)
    return rows


def _resolve(root: Path, path: Path) -> Path:
    resolved = path.resolve() if path.is_absolute() else (root / path).resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError("path is outside repository root")
    return resolved


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the P2.9 account catalog lexical review sidecar.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--accounts", type=Path, default=Path("data/normalized/account-profiles.jsonl"))
    parser.add_argument("--listings", type=Path, default=Path("data/normalized/listings.jsonl"))
    parser.add_argument("--index", type=Path, default=Path("data/normalized/catalog-query-index.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/review/account-catalog-resolution.jsonl"))
    args = parser.parse_args(); root = args.root.resolve()
    index_path = _resolve(root, args.index)
    rows = build_account_catalog_resolution(read_jsonl(_resolve(root, args.accounts)), read_jsonl(_resolve(root, args.listings)), read_jsonl(index_path), index_sha256=sha256_bytes(index_path.read_bytes()))
    output = args.output.resolve() if args.output.is_absolute() else _resolve(root, args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8", newline="\n")
    print(json.dumps({"account_count": len(rows), "eligible_count": sum(row["matching_eligibility"] == "eligible" for row in rows), "accounts_with_matches": sum(bool(row["matches"]) for row in rows), "match_count": sum(len(row["matches"]) for row in rows)}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
