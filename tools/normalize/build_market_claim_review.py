#!/usr/bin/env python3
"""Build the fixed, anonymous P2.1 market-claim human-review queue.

This offline tool reads only the committed normalized listing file.  It writes
listing IDs, SHA-256 digests of the existing anonymous listing text, and the
fields that human reviewers must independently label.  It does not emit source
text, proposed labels, market data, or gold annotations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


SELECTION_VERSION = "p2.1-market-claim-stratified-20"
REQUESTED_FIELDS = ["offer_kind", "entity_kind", "server", "currency", "price_type", "price_twd", "status", "date_verified"]

# Fixed IDs make the review sample reproducible.  Strata cover normal seller
# listings and deliberately excluded/ambiguous market forms without writing
# any machine suggestion into the queue itself.
FIXED_SELECTION = [
    ("listing_0260", "seller_international_twd"),
    ("listing_0388", "seller_international_twd"),
    ("listing_0708", "seller_international_twd"),
    ("listing_0792", "seller_international_twd"),
    ("listing_0864", "seller_unknown_identity"),
    ("listing_0003", "buyer_budget"),
    ("listing_0021", "service"),
    ("listing_0013", "exchange"),
    ("listing_0190", "multi_account"),
    ("listing_0002", "china_server"),
    ("listing_0480", "foreign_currency"),
    ("listing_0028", "sold_claim"),
    ("listing_0001", "unknown_market_claim"),
    ("listing_0152", "multi_account"),
    ("listing_0041", "china_server"),
    ("listing_0510", "foreign_currency"),
    ("listing_0039", "exchange"),
    ("listing_0349", "multi_account"),
    ("listing_0124", "service"),
    ("listing_0236", "buyer_budget"),
]
OPAQUE_BUCKETS = {
    name: f"market_claim_bucket_{index:02d}"
    for index, name in enumerate(dict.fromkeys(name for _, name in FIXED_SELECTION), start=1)
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def build_queue(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row.get("listing_id"): row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("normalized listing IDs must be unique")
    if len(FIXED_SELECTION) != 20 or len({entry[0] for entry in FIXED_SELECTION}) != 20:
        raise AssertionError("fixed review selection must contain exactly 20 unique listing IDs")
    queue: list[dict[str, Any]] = []
    for index, (listing_id, stratum) in enumerate(FIXED_SELECTION, start=1):
        row = by_id.get(listing_id)
        if row is None:
            raise ValueError(f"selected listing absent from normalized source: {listing_id}")
        text = row.get("listing_text")
        if not isinstance(text, str) or not text:
            raise ValueError(f"selected listing has no usable listing_text: {listing_id}")
        queue.append({
            "review_id": f"market_claim_review_{index:04d}",
            "listing_id": listing_id,
            "listing_text_sha256": text_sha256(text),
            "selection_version": SELECTION_VERSION,
            "selection_bucket": OPAQUE_BUCKETS[stratum],
            "requested_fields": REQUESTED_FIELDS,
            "review_status": "needs_human_annotation",
        })
    return queue


def validate_gold_links(queue: list[dict[str, Any]], gold_rows: list[dict[str, Any]]) -> list[str]:
    """Validate exact queue linkage and distinct pseudonymous human roles."""
    errors: list[str] = []
    queue_by_review = {row.get("review_id"): row for row in queue}
    seen_gold: set[str] = set()
    seen_listing: set[str] = set()
    for row in gold_rows:
        gold_id, listing_id = row.get("gold_id"), row.get("listing_id")
        if gold_id in seen_gold: errors.append(f"duplicate gold_id: {gold_id}")
        if listing_id in seen_listing: errors.append(f"duplicate gold listing: {listing_id}")
        seen_gold.add(str(gold_id)); seen_listing.add(str(listing_id))
        review = queue_by_review.get(row.get("review_id"))
        if review is None:
            errors.append(f"gold row is not linked to the committed review queue: {gold_id}")
        elif listing_id != review.get("listing_id") or row.get("listing_text_sha256") != review.get("listing_text_sha256"):
            errors.append(f"gold row listing/hash differs from review queue: {gold_id}")
        identities = [row.get("annotator_a", {}).get("annotator_id"), row.get("annotator_b", {}).get("annotator_id"), row.get("adjudication", {}).get("adjudicator_id")]
        if len(set(identities)) != 3:
            errors.append(f"gold row lacks two distinct annotators and a distinct adjudicator: {gold_id}")
        if row.get("adjudication", {}).get("decision") == "agreement":
            labels = [row.get("annotator_a", {}).get("labels"), row.get("annotator_b", {}).get("labels"), row.get("adjudication", {}).get("final_labels")]
            if not (labels[0] == labels[1] == labels[2]):
                errors.append(f"gold agreement labels are not identical: {gold_id}")
    return errors


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    path.write_text(payload, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--input", type=Path, default=Path("data/normalized/listings.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/review/market-claim-review.jsonl"))
    args = parser.parse_args()
    root = args.root.resolve()
    input_path = args.input if args.input.is_absolute() else root / args.input
    output_path = args.output if args.output.is_absolute() else root / args.output
    rows = build_queue(read_jsonl(input_path))
    write_jsonl(output_path, rows)
    print(json.dumps({"output": str(output_path), "count": len(rows), "selection_version": SELECTION_VERSION}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
