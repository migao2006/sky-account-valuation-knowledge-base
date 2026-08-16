#!/usr/bin/env python3
"""Build the deterministic, anonymous P2.3 market near-miss review queue.

This is deliberately an *evidence collection* instrument.  It finds a narrow
set of seller, single-account, positive-price, verified-TWD listings that are
otherwise suitable for the strict international normal-listing pool but fail
exactly one remaining hard-evidence group.  Queue records never contain the
source text, a URL, a proposed value, or an automatic admission decision.

Approved human field evidence is intentionally consumed by no production
builder.  A separately reviewed migration must explicitly change canonical
normalized data before a listing can ever reach formal comparables.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Any


SELECTION_VERSION = "p2.3-market-near-miss-single-hard-evidence-v1"
NORMAL_PRICE_TYPES = {"asking", "normal_listing"}
FIELD_VALUES: dict[str, set[Any]] = {
    "server": {"international", "china", "unknown"},
    "server_verified": {True, False},
    "price_type": {"asking", "normal_listing", "reduced", "instant", "urgent_sale", "quick_sale", "unknown"},
    "status": {"active", "sold", "sold_claimed", "reported_sold", "wanted", "unknown"},
}
HUMAN_REVIEWER_ID = re.compile(r"^human_[a-z0-9_]+$")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)
    path.write_text(payload, encoding="utf-8", newline="\n")


def text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest().upper()


def has_positive_price(row: dict[str, Any]) -> bool:
    value = row.get("price_twd")
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def has_disqualifying_price_semantics(row: dict[str, Any]) -> bool:
    review = row.get("price_semantic_review")
    if isinstance(review, dict) and (
        review.get("review_status") != "approved"
        or review.get("brokerage_included") is True
        or review.get("multi_price") is True
    ):
        return True
    text = str(row.get("listing_text") or "")
    brokerage = "含仲" in text or "仲介費" in text
    badge_variants = "含勳章" in text and "不含勳章" in text
    installment_variants = "分期" in text and bool(re.search(r"\d+(?:\.\d+)?\s*(?:至|到|~|～|-|—)\s*\d+(?:\.\d+)?", text))
    return brokerage or badge_variants or installment_variants


def is_base_candidate(row: dict[str, Any]) -> bool:
    """Apply all eligibility facts that are not under near-miss review."""
    return (
        row.get("offer_kind") == "seller_listing"
        and row.get("entity_kind") == "single_account"
        and row.get("currency") == "TWD"
        and row.get("currency_verified") is True
        and has_positive_price(row)
        and not str(row.get("exclusion_reason") or "").strip()
        and row.get("duplicate_cluster_id") is None
        # Brokerage and multiple price terms are not correctable missing
        # fields, so they must never enter this single-hard-gap workflow.
        and not has_disqualifying_price_semantics(row)
    )


def missing_hard_evidence_groups(row: dict[str, Any]) -> list[tuple[str, list[str]]] | None:
    """Return opaque review field names for every remaining failed group.

    A group may contain the value and its verification flag; it is still one
    hard-evidence domain.  The returned names intentionally do not reveal the
    normalized values that caused selection.
    """
    missing: list[tuple[str, list[str]]] = []
    server = row.get("server")
    if server == "international":
        if row.get("server_verified") is not True:
            missing.append(("international_server_evidence", ["server", "server_verified"]))
    elif server in {None, "unknown"}:
        missing.append(("international_server_evidence", ["server", "server_verified"]))
    else:
        return None
    price_type = row.get("price_type")
    if price_type in NORMAL_PRICE_TYPES:
        pass
    elif price_type in {None, "unknown"}:
        missing.append(("normal_listing_price_type_evidence", ["price_type"]))
    else:
        return None
    status = row.get("status")
    if status == "active":
        pass
    elif status in {None, "unknown"}:
        missing.append(("active_listing_status_evidence", ["status"]))
    else:
        return None
    return missing


def build_queue(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ids = [row.get("listing_id") for row in rows]
    if len(ids) != len(set(ids)) or not all(isinstance(value, str) for value in ids):
        raise ValueError("normalized listing IDs must be unique strings")
    selected: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda record: record["listing_id"]):
        if not is_base_candidate(row):
            continue
        missing = missing_hard_evidence_groups(row)
        if missing is None or len(missing) != 1:
            continue
        text = row.get("listing_text")
        if not isinstance(text, str) or not text:
            raise ValueError(f"near-miss listing has no usable listing_text: {row['listing_id']}")
        group, required_fields = missing[0]
        selected.append({
            "review_id": f"market_near_miss_review_{len(selected) + 1:04d}",
            "listing_id": row["listing_id"],
            "listing_text_sha256": text_sha256(text),
            "selection_version": SELECTION_VERSION,
            "required_fields": required_fields,
            "review_status": "needs_human_field_evidence",
            # This is an opaque group identifier for workflow routing, not a
            # proposed field value or an admission recommendation.
            "evidence_domain": group,
        })
    return selected


def validate_approved_evidence(queue: list[dict[str, Any]], evidence_rows: list[dict[str, Any]]) -> list[str]:
    """Check linkage and human double-review rules; never promote evidence."""
    errors: list[str] = []
    queue_by_review = {row["review_id"]: row for row in queue}
    seen_ids: set[str] = set()

    def valid_field_value(field: Any, value: Any) -> bool:
        allowed = FIELD_VALUES.get(field)
        if allowed is None:
            return False
        if field == "server_verified":
            return isinstance(value, bool)
        return isinstance(value, str) and value in allowed

    def valid_date(value: Any) -> bool:
        try:
            return isinstance(value, str) and date.fromisoformat(value).isoformat() == value
        except ValueError:
            return False

    for row in evidence_rows:
        evidence_id = str(row.get("evidence_id"))
        if evidence_id in seen_ids:
            errors.append(f"duplicate evidence_id: {evidence_id}")
        seen_ids.add(evidence_id)
        review = queue_by_review.get(row.get("review_id"))
        if review is None:
            errors.append(f"evidence is not linked to committed near-miss queue: {evidence_id}")
            continue
        if row.get("listing_id") != review.get("listing_id") or row.get("listing_text_sha256") != review.get("listing_text_sha256"):
            errors.append(f"evidence listing/hash differs from near-miss queue: {evidence_id}")
        field = row.get("field")
        if field not in review.get("required_fields", []):
            errors.append(f"evidence field was not requested by near-miss queue: {evidence_id}")
        if not valid_field_value(field, row.get("value")):
            errors.append(f"evidence value is invalid for field {field!r}: {evidence_id}")
        reviewers = row.get("reviewers")
        adjudication = row.get("adjudication")
        reviewer_ids = [entry.get("reviewer_id") for entry in reviewers] if isinstance(reviewers, list) else []
        adjudicator_id = adjudication.get("adjudicator_id") if isinstance(adjudication, dict) else None
        if len(reviewer_ids) != 2 or len(set(reviewer_ids)) != 2 or adjudicator_id in reviewer_ids:
            errors.append(f"evidence lacks two distinct reviewers and a distinct adjudicator: {evidence_id}")
        if isinstance(reviewers, list):
            for entry in reviewers:
                if not isinstance(entry, dict) or entry.get("reviewer_kind") != "human" or not isinstance(entry.get("reviewer_id"), str) or not HUMAN_REVIEWER_ID.fullmatch(entry["reviewer_id"]):
                    errors.append(f"evidence has invalid human reviewer identity: {evidence_id}")
                    continue
                if not valid_date(entry.get("reviewed_at")) or not valid_field_value(field, entry.get("value")):
                    errors.append(f"evidence has invalid reviewer value or date: {evidence_id}")
        if not isinstance(adjudication, dict) or adjudication.get("adjudicator_kind") != "human" or not isinstance(adjudicator_id, str) or not HUMAN_REVIEWER_ID.fullmatch(adjudicator_id):
            errors.append(f"evidence has invalid human adjudicator identity: {evidence_id}")
        elif not valid_date(adjudication.get("adjudicated_at")) or not valid_field_value(field, adjudication.get("final_value")):
            errors.append(f"evidence has invalid adjudicated value or date: {evidence_id}")
        if isinstance(reviewers, list) and len(reviewers) == 2 and isinstance(adjudication, dict):
            reviewer_values = [entry.get("value") for entry in reviewers if isinstance(entry, dict)]
            decision = adjudication.get("decision")
            if decision == "agreement" and (len(reviewer_values) != 2 or reviewer_values[0] != reviewer_values[1]):
                errors.append(f"agreement decision has disagreeing reviewer values: {evidence_id}")
            if decision == "resolved_disagreement" and len(reviewer_values) == 2 and reviewer_values[0] == reviewer_values[1]:
                errors.append(f"resolved_disagreement has identical reviewer values: {evidence_id}")
        if isinstance(adjudication, dict) and adjudication.get("final_value") != row.get("value"):
            errors.append(f"evidence value differs from adjudicated value: {evidence_id}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--input", type=Path, default=Path("data/normalized/listings.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/review/market-near-miss-field-review.jsonl"))
    args = parser.parse_args()
    root = args.root.resolve()
    input_path = args.input if args.input.is_absolute() else root / args.input
    output_path = args.output if args.output.is_absolute() else root / args.output
    queue = build_queue(read_jsonl(input_path))
    write_jsonl(output_path, queue)
    print(json.dumps({"output": str(output_path), "count": len(queue), "selection_version": SELECTION_VERSION}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
