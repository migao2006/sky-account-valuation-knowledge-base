#!/usr/bin/env python3
"""Build the fixed, anonymous P2.2 market-claim human-review queue.

This offline tool reads only the committed normalized listing file.  It writes
listing IDs, SHA-256 digests of the existing anonymous listing text, and the
fields that human reviewers must independently label.  It does not emit source
text, proposed labels, market data, or gold annotations.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable


SELECTION_VERSION = "p2.2-market-claim-stratified-200"
REQUESTED_FIELDS = ["offer_kind", "entity_kind", "server", "currency", "price_type", "price_twd", "status", "date_verified", "verified_sale"]

# These predicates are used only to make a balanced sample from the existing
# normalized corpus.  The emitted queue contains neither a predicate name nor
# a normalized value: reviewers see only an opaque bucket ID.  Keeping the
# selection rules and sort order here makes the 200-row sample reproducible.
Predicate = Callable[[dict[str, Any]], bool]
STRATA: list[tuple[Predicate, int]] = [
    (lambda row: row.get("server") == "china", 10),
    (lambda row: row.get("date_verified") is True, 10),
    (lambda row: row.get("currency") == "CNY", 10),
    (lambda row: row.get("currency") == "RM", 10),
    (lambda row: row.get("currency") == "HKD", 10),
    (lambda row: row.get("currency") == "TWD", 10),
    (lambda row: row.get("server") == "international", 10),
    (lambda row: row.get("offer_kind") == "buyer_budget", 10),
    (lambda row: row.get("offer_kind") == "service", 10),
    (lambda row: row.get("offer_kind") == "exchange", 10),
    (lambda row: row.get("entity_kind") == "multi_account", 10),
    (lambda row: row.get("price_twd") is not None, 10),
    (lambda row: row.get("status") in {"sold", "sold_claimed", "reported_sold"}, 10),
    (lambda row: bool(re.search(r"綁|绑|Google|Apple|Facebook|Nintendo|Steam|PlayStation", str(row.get("listing_text", "")), re.IGNORECASE)), 10),
    (lambda row: bool(re.search(r"季|畢業|毕业|極光|欧若拉|梵谷|梵高|大耳狗|耳狗|青鳥|青鸟|築巢|筑巢|歸巢|归巢", str(row.get("listing_text", "")))), 10),
    (lambda row: bool(re.search(r"蠟|蜡|愛心|爱心|季蠟|季蜡|紅蠟|红蜡|红烛|白蜡", str(row.get("listing_text", "")))), 10),
    (lambda row: row.get("price_type") == "unknown", 10),
    (lambda row: row.get("currency") == "unknown", 10),
    (lambda row: row.get("server") == "unknown", 10),
    (lambda row: row.get("offer_kind") == "unknown", 10),
]
QUEUE_SIZE = sum(quota for _, quota in STRATA)
OPAQUE_BUCKETS = tuple(f"market_claim_bucket_{index:02d}" for index in range(1, len(STRATA) + 1))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def build_queue(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row.get("listing_id"): row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("normalized listing IDs must be unique")
    ordered_rows = sorted(rows, key=lambda row: str(row["listing_id"]))
    selected_ids: set[str] = set()
    queue: list[dict[str, Any]] = []
    for bucket_index, ((predicate, quota), opaque_bucket) in enumerate(zip(STRATA, OPAQUE_BUCKETS), start=1):
        candidates = [row for row in ordered_rows if row["listing_id"] not in selected_ids and predicate(row)]
        if len(candidates) < quota:
            raise ValueError(f"review bucket {bucket_index:02d} has {len(candidates)} unique candidates; needs {quota}")
        for row in candidates[:quota]:
            listing_id = row["listing_id"]
            text = row.get("listing_text")
            if not isinstance(text, str) or not text:
                raise ValueError(f"selected listing has no usable listing_text: {listing_id}")
            selected_ids.add(listing_id)
            queue.append({
                "review_id": f"market_claim_review_{len(queue) + 1:04d}",
                "listing_id": listing_id,
                "listing_text_sha256": text_sha256(text),
                "selection_version": SELECTION_VERSION,
                "selection_bucket": opaque_bucket,
                "requested_fields": REQUESTED_FIELDS,
                "review_status": "needs_human_annotation",
            })
    if len(queue) != QUEUE_SIZE or len(selected_ids) != QUEUE_SIZE:
        raise AssertionError("review queue must contain exactly the configured number of unique listings")
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
