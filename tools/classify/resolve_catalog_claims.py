#!/usr/bin/env python3
"""Resolve identifier-only catalog claims through the offline query index.

This tool neither accepts nor writes raw post text.  It treats a query result
as lookup/review evidence only; ownership is emitted only for a unique,
verified canonical resolution.  Conflicting positive/negative assertions fail
closed and unknown is never converted to absence.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any


ID_RE = re.compile(r"^(item_[a-z0-9_]+|reference_identity_[a-f0-9]{32})$")
CLAIM_RE = re.compile(r"^claim_[a-z0-9_]+$")
STATES = {"owned", "confirmed_missing", "unknown"}
EVIDENCE = {"structured_claim", "unknown"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _validate_input(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, dict) or not isinstance(value.get("catalog_claims"), list) or not value["catalog_claims"]:
        raise ValueError("input must contain a non-empty catalog_claims list")
    claims: list[dict[str, str]] = []
    claim_ids: set[str] = set()
    for number, claim in enumerate(value["catalog_claims"]):
        if not isinstance(claim, dict) or set(claim) != {"claim_id", "query_entity_id", "state", "evidence_state"}:
            raise ValueError(f"catalog_claims[{number}] must contain only claim_id, query_entity_id, state, evidence_state")
        if not isinstance(claim["claim_id"], str) or not CLAIM_RE.fullmatch(claim["claim_id"]):
            raise ValueError(f"catalog_claims[{number}].claim_id is invalid")
        if claim["claim_id"] in claim_ids:
            raise ValueError("catalog claim IDs must be unique")
        if not isinstance(claim["query_entity_id"], str) or not ID_RE.fullmatch(claim["query_entity_id"]):
            raise ValueError(f"catalog_claims[{number}].query_entity_id is invalid")
        if claim["state"] not in STATES or claim["evidence_state"] not in EVIDENCE:
            raise ValueError(f"catalog_claims[{number}] has an unsupported state or evidence state")
        if claim["state"] != "unknown" and claim["evidence_state"] != "structured_claim":
            raise ValueError(f"catalog_claims[{number}] cannot assert ownership or absence without structured evidence")
        claim_ids.add(claim["claim_id"]); claims.append(claim)
    return claims


def resolve_catalog_claims(value: Any, index_rows: list[dict[str, Any]]) -> dict[str, Any]:
    claims = _validate_input(value)
    by_id = {row.get("query_entity_id"): row for row in index_rows}
    if len(by_id) != len(index_rows) or None in by_id:
        raise ValueError("catalog query index has duplicate or missing query entity IDs")
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for claim in claims: grouped[claim["query_entity_id"]].append(claim)
    resolutions: list[dict[str, Any]] = []
    for entity_id, grouped_claims in sorted(grouped.items()):
        claim_ids = sorted(claim["claim_id"] for claim in grouped_claims)
        states = {claim["state"] for claim in grouped_claims}
        row = by_id.get(entity_id)
        if row is None:
            resolutions.append({"claim_ids": claim_ids, "query_entity_id": entity_id, "truth_level": "unknown", "claimed_state": "conflict" if {"owned", "confirmed_missing"} <= states else next(iter(states)), "ownership_state": "unknown", "resolution_status": "unknown_reference", "resolved_item_id": None, "proposed_canonical_item_ids": [], "candidate_item_ids": [], "model_feature": False, "review_status": "unknown", "reasons": ["query_entity_id_is_not_present_in_the_offline_catalog_index"]})
            continue
        if {"owned", "confirmed_missing"} <= states:
            resolutions.append({"claim_ids": claim_ids, "query_entity_id": entity_id, "truth_level": row["truth_level"], "claimed_state": "conflict", "ownership_state": "unknown", "resolution_status": "conflict", "resolved_item_id": None, "proposed_canonical_item_ids": row["canonical_item_ids"], "candidate_item_ids": row["candidate_item_ids"], "model_feature": False, "review_status": "needs_review", "reasons": ["positive_and_negative_claims_conflict;_ownership_is_fail_closed"]})
            continue
        claimed_state = next(iter(states)) if len(states) == 1 else "unknown"
        eligible = row["resolution_eligibility"] == "canonical_resolved" and len(row["canonical_item_ids"]) == 1
        if eligible:
            resolutions.append({"claim_ids": claim_ids, "query_entity_id": entity_id, "truth_level": row["truth_level"], "claimed_state": claimed_state, "ownership_state": claimed_state, "resolution_status": "canonical_resolved", "resolved_item_id": row["canonical_item_ids"][0], "proposed_canonical_item_ids": row["canonical_item_ids"], "candidate_item_ids": [], "model_feature": False, "review_status": "approved", "reasons": ["unique_verified_canonical_exact_mapping", "model_features_remain_out_of_scope_for_this_resolver"]})
        else:
            status = "ambiguous" if len(row["canonical_item_ids"]) + len(row["candidate_item_ids"]) > 1 or row["review_status"] == "quarantined" else "review_only"
            reason = "unknown_claim_is_not_confirmed_missing" if claimed_state == "unknown" else "catalog_identity_is_not_a_unique_verified_canonical_exact_mapping"
            resolutions.append({"claim_ids": claim_ids, "query_entity_id": entity_id, "truth_level": row["truth_level"], "claimed_state": claimed_state, "ownership_state": "unknown", "resolution_status": status, "resolved_item_id": None, "proposed_canonical_item_ids": row["canonical_item_ids"], "candidate_item_ids": row["candidate_item_ids"], "model_feature": False, "review_status": row["review_status"], "reasons": [reason, "ownership_and_model_feature_are_withheld_pending_review"]})
    return {"schema_version": "1.0", "resolutions": resolutions}


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve identifier-only catalog claims offline.")
    parser.add_argument("input", type=Path); parser.add_argument("--index", type=Path, default=Path(__file__).resolve().parents[2] / "data/normalized/catalog-query-index.jsonl"); parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = resolve_catalog_claims(json.loads(args.input.read_text(encoding="utf-8")), read_jsonl(args.index))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
