#!/usr/bin/env python3
"""Deterministic, non-model audit of parser knowledge coverage.

This report deliberately separates three kinds of facts: canonical catalog
verification, parser token verification, and per-account observations.  The
lexical review sidecar is never ownership evidence and cannot promote an item
to a known state or a model feature.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _require_unique(rows: list[dict[str, Any]], key: str, label: str) -> None:
    values = [row.get(key) for row in rows]
    if any(not isinstance(value, str) or not value for value in values) or len(values) != len(set(values)):
        raise ValueError(f"{label} must have unique non-empty {key}")


def _unknown_ids(rows: list[dict[str, Any]], known: set[str], key: str) -> set[str]:
    return {str(row.get(key)) for row in rows if row.get(key) not in known}


def audit(
    items: list[dict[str, Any]], aliases: list[dict[str, Any]], vectors: list[dict[str, Any]],
    sidecar: list[dict[str, Any]], costs: list[dict[str, Any]],
) -> dict[str, Any]:
    """Produce an item-by-item, fail-closed coverage audit from formal inputs.

    Invalid references are rejected rather than silently omitted.  This makes
    a changed parser input observable and prevents review-only output from
    becoming an ownership backchannel.
    """
    _require_unique(items, "item_id", "canonical items")
    known = {row["item_id"] for row in items}
    _require_unique(vectors, "account_id", "vectors")
    _require_unique(sidecar, "account_id", "review sidecar")
    _require_unique(costs, "item_id", "historical cost references")

    item_aliases: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for alias in aliases:
        if alias.get("target_type") == "item":
            target = alias.get("target_id")
            if target not in known:
                raise ValueError(f"alias references unknown canonical item: {target}")
            item_aliases[target].append(alias)

    for cost in costs:
        item_id = cost.get("item_id")
        if item_id not in known:
            raise ValueError(f"historical cost reference has unknown canonical item: {item_id}")
        if cost.get("model_feature") is not False or cost.get("resale_value_effect") != "not_inferred":
            raise ValueError(f"historical cost reference is not non-model: {item_id}")

    states: dict[str, Counter[str]] = defaultdict(Counter)
    for vector in vectors:
        for state in vector.get("item_states", []):
            item_id = state.get("item_id")
            if item_id not in known:
                raise ValueError(f"vector references unknown canonical item: {item_id}")
            value = state.get("state")
            if value not in {"owned", "confirmed_missing", "unknown"}:
                raise ValueError(f"invalid vector item state for {item_id}: {value}")
            states[item_id][value] += 1

    polarities: dict[str, Counter[str]] = defaultdict(Counter)
    forbidden_sidecar_fields = {"ownership_state", "owned", "confirmed_missing", "state", "model_eligible"}
    for row in sidecar:
        if row.get("review_only") is not True or row.get("model_feature") is not False:
            raise ValueError(f"review sidecar must remain non-model for {row.get('account_id')}")
        for match in row.get("matches", []):
            if any(field in match for field in forbidden_sidecar_fields):
                raise ValueError("review sidecar must not carry ownership or model promotion fields")
            if match.get("review_only") is not True or match.get("model_feature") is not False:
                raise ValueError("review sidecar match must remain non-model")
            # The query-index uses ``canonical_item`` for catalog items.
            # Keep accepting the older ``item`` spelling for replaying a
            # historical sidecar, while ignoring season/set review matches.
            if match.get("query_entity_type") not in {"item", "canonical_item"}:
                continue
            item_id = match.get("query_entity_id")
            if item_id not in known:
                raise ValueError(f"review sidecar references unknown canonical item: {item_id}")
            assertion = match.get("assertion")
            if assertion not in {"positive", "negative", "conflict"}:
                raise ValueError(f"invalid review sidecar assertion for {item_id}: {assertion}")
            polarities[item_id][assertion] += 1

    cost_by_item = {row["item_id"]: row["reference_kind"] for row in costs}
    rows: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda row: row["item_id"]):
        item_id = item["item_id"]
        alias_rows = item_aliases[item_id]
        verified_aliases = sum(row.get("verification_status") == "verified" for row in alias_rows)
        item_states = states[item_id]
        sidecar_counts = polarities[item_id]
        rows.append({
            "item_id": item_id,
            "canonical_verification_status": item.get("verification_status"),
            "canonical_model_feature_status": item.get("model_feature_status"),
            "verified_observation_token_available": verified_aliases > 0,
            "alias_count": len(alias_rows),
            "verified_alias_count": verified_aliases,
            "alias_verification_gap_count": len(alias_rows) - verified_aliases,
            "known_owned_count": item_states["owned"],
            "known_missing_count": item_states["confirmed_missing"],
            "unknown_state_count": item_states["unknown"],
            "review_only_positive_count": sidecar_counts["positive"],
            "review_only_negative_count": sidecar_counts["negative"],
            "review_only_conflict_count": sidecar_counts["conflict"],
            "historical_cost_reference_kind": cost_by_item.get(item_id),
            "model_feature": False,
        })
    verification = Counter(row.get("verification_status") for row in items)
    model = Counter(row.get("model_feature_status") for row in items)
    return {
        "schema_version": "1.0-p3.1",
        "model_feature": False,
        "summary": {
            "canonical_item_count": len(rows),
            "verified_canonical_item_count": verification["verified"],
            "model_eligible_item_count": model["eligible"],
            "verified_alias_item_count": sum(row["verified_observation_token_available"] for row in rows),
            "known_owned_count": sum(row["known_owned_count"] for row in rows),
            "known_missing_count": sum(row["known_missing_count"] for row in rows),
            "known_state_count": sum(row["known_owned_count"] + row["known_missing_count"] for row in rows),
            "review_only_positive_count": sum(row["review_only_positive_count"] for row in rows),
            "review_only_negative_count": sum(row["review_only_negative_count"] for row in rows),
            "review_only_conflict_count": sum(row["review_only_conflict_count"] for row in rows),
            "historical_cost_reference_count": len(costs),
        },
        "items": rows,
    }


def build(root: Path) -> dict[str, Any]:
    root = root.resolve()
    return audit(
        read_jsonl(root / "knowledge/items/items.jsonl"),
        read_jsonl(root / "knowledge/aliases/item-aliases.jsonl"),
        read_jsonl(root / "data/modeling/account-item-vectors.jsonl"),
        read_jsonl(root / "data/review/account-catalog-resolution.jsonl"),
        read_jsonl(root / "data/derived/official-historical-cost-references.jsonl"),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a non-model parser knowledge coverage audit")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(build(args.root), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
