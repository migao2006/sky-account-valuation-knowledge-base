#!/usr/bin/env python3
"""Build conservative official historical acquisition-cost references.

The output deliberately keeps bundle prices at the bundle level.  It has no
resale-value semantics and must not be consumed as a model feature.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.validate.canonical_evidence_registry import load_registry, validate_registry

DEFAULT_OUTPUT = "data/derived/official-historical-cost-references.jsonl"
IN_GAME_CURRENCIES = frozenset({"candle", "candles", "heart", "hearts", "ascended candle", "ascended candles", "event_currency"})
# A generic official statement can establish context, but it must never be
# treated as the price of a particular canonical item or bundle.
OFFICIAL_COST_TIERS = frozenset({"official_item_specific"})


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _unique(rows: list[dict[str, Any]], field: str) -> list[Any]:
    values: dict[str, Any] = {}
    for row in rows:
        value = row.get(field)
        values[canonical_json(value)] = value
    return [values[key] for key in sorted(values)]


def _provenance(rows: list[dict[str, Any]]) -> tuple[list[str], list[str], str]:
    return (
        sorted({str(row["evidence_id"]) for row in rows}),
        sorted({str(row["source_id"]) for row in rows}),
        max(str(row["reviewed_at"]) for row in rows),
    )


def _unknown(item_id: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    evidence_ids, source_ids, as_of_date = _provenance(rows)
    return {
        "schema_version": "1.0", "item_id": item_id, "reference_kind": "unknown",
        "item_amount": None, "item_currency": None, "bundle_set_id": None,
        "bundle_amount": None, "bundle_currency": None,
        "evidence_ids": evidence_ids, "source_ids": source_ids, "as_of_date": as_of_date,
        "historical_scope": "no_approved_historical_cost_reference", "model_feature": False,
        "resale_value_effect": "not_inferred",
        "notes": "No approved item-level historical cost or unambiguous linked historical bundle price is available.",
    }


def build(root: Path) -> list[dict[str, Any]]:
    """Build rows from every active cohort registered in the formal registry."""
    items = {row["item_id"]: row for row in read_jsonl(root / "knowledge/items/items.jsonl")}
    sets = {row["set_id"]: row for row in read_jsonl(root / "knowledge/sets/item-sets.jsonl")}
    sources = {row["source_id"]: row for row in read_jsonl(root / "knowledge/sources/sources.jsonl")}
    problems, ledgers = validate_registry(root, items, sets, sources)
    if problems:
        raise ValueError("canonical evidence registry is not replayable: " + "; ".join(problems))

    rows: list[dict[str, Any]] = []
    for cohort in sorted(load_registry(root), key=lambda row: str(row["cohort_id"])):
        ledger = ledgers.get(str(cohort["cohort_id"]))
        if ledger is None:
            continue
        target_item_ids = sorted(str(item_id) for item_id in cohort["target_item_ids"])
        target_set_ids = {str(set_id) for set_id in cohort["target_set_ids"]}
        by_target: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for evidence in ledger:
            by_target[(str(evidence["target_type"]), str(evidence["target_id"]))].append(evidence)
        set_price_rows = {
            set_id: [
                row for row in by_target[("set", set_id)]
                if row.get("field_path") == "historical_pack_price_usd" and row.get("source_tier") in OFFICIAL_COST_TIERS
            ]
            for set_id in target_set_ids
        }
        for item_id in target_item_ids:
            item = items[item_id]
            if item.get("verification_status") != "verified":
                continue
            item_rows = by_target[("item", item_id)]
            cost_rows = [
                row for row in item_rows
                if row.get("field_path") == "original_cost" and row.get("source_tier") in OFFICIAL_COST_TIERS
            ]
            costs = _unique(cost_rows, "claim_value")
            currency = item.get("original_currency")
            if len(costs) == 1 and isinstance(costs[0], (int, float)) and not isinstance(costs[0], bool) and isinstance(currency, str) and currency:
                evidence_ids, source_ids, as_of_date = _provenance(item_rows)
                in_game = currency.casefold() in IN_GAME_CURRENCIES
                rows.append({
                    "schema_version": "1.0", "item_id": item_id,
                    "reference_kind": "in_game_currency" if in_game else "exact_historical_item_price",
                    "item_amount": costs[0], "item_currency": currency,
                    "bundle_set_id": None, "bundle_amount": None, "bundle_currency": None,
                    "evidence_ids": evidence_ids, "source_ids": source_ids, "as_of_date": as_of_date,
                    "historical_scope": "official_in_game_currency_cost" if in_game else "official_item_cost",
                    "model_feature": False, "resale_value_effect": "not_inferred",
                    "notes": "Approved canonical evidence records a historical acquisition cost; it is not a resale value.",
                })
                continue

            linked_set_ids = sorted(set(item.get("set_ids", [])) & target_set_ids)
            bundle_candidates: list[tuple[str, float]] = []
            for set_id in linked_set_ids:
                prices = _unique(set_price_rows[set_id], "claim_value")
                if len(prices) == 1 and isinstance(prices[0], (int, float)) and not isinstance(prices[0], bool):
                    bundle_candidates.append((set_id, prices[0]))
            if item.get("original_cost") == "bundle_only" and len(bundle_candidates) == 1:
                set_id, price = bundle_candidates[0]
                relevant = item_rows + by_target[("set", set_id)]
                evidence_ids, source_ids, as_of_date = _provenance(relevant)
                rows.append({
                    "schema_version": "1.0", "item_id": item_id, "reference_kind": "bundle_only",
                    "item_amount": None, "item_currency": None, "bundle_set_id": set_id,
                    "bundle_amount": price, "bundle_currency": "USD",
                    "evidence_ids": evidence_ids, "source_ids": source_ids, "as_of_date": as_of_date,
                    "historical_scope": "official_bundle_price_no_item_allocation", "model_feature": False,
                    "resale_value_effect": "not_inferred",
                    "notes": "Approved evidence records a historical bundle price only. No amount is allocated to this individual item.",
                })
            else:
                rows.append(_unknown(item_id, item_rows))
    return sorted(rows, key=lambda row: row["item_id"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.output or root / DEFAULT_OUTPUT
    if not output.is_absolute():
        output = root / output
    output.parent.mkdir(parents=True, exist_ok=True)
    records = build(root)
    output.write_text("".join(canonical_json(row) + "\n" for row in records), encoding="utf-8", newline="\n")
    print(f"wrote {len(records)} official historical cost references to {output}")


if __name__ == "__main__":
    main()
