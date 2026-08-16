#!/usr/bin/env python3
"""Move mechanically generated printable-template candidates out of canonical items."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

MARKER = "Generated from printable seasonal cosmetics template"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()
    item_path = root / "knowledge/items/items.jsonl"
    queue_path = root / "data/review/item-candidates.jsonl"
    items = read_jsonl(item_path)
    existing = {row["candidate_item_id"]: row for row in read_jsonl(queue_path)}
    removed = [row for row in items if MARKER in str(row.get("notes", ""))]
    kept = [row for row in items if row not in removed]
    for row in removed:
        existing[row["item_id"]] = {
            "candidate_item_id": row["item_id"], "season_id": row.get("season_id"),
            "candidate_name_en": row.get("canonical_name_en"),
            "candidate_category": row.get("item_category"), "source_ids": row.get("source_ids", []),
            "review_status": "needs_review",
            "reason": "Printable template token has not been verified as a canonical named item; excluded from valuation and canonical IDs.",
        }
    write_jsonl(item_path, kept)
    write_jsonl(queue_path, [existing[key] for key in sorted(existing)])
    item_ids = {row["item_id"] for row in kept}

    alias_path = root / "knowledge/aliases/item-aliases.jsonl"
    aliases = [row for row in read_jsonl(alias_path) if row.get("target_type") != "item" or row.get("target_id") in item_ids]

    set_path = root / "knowledge/sets/item-sets.jsonl"
    sets = read_jsonl(set_path)
    for row in sets:
        row["required_item_ids"] = [value for value in row.get("required_item_ids", []) if value in item_ids]
        row["optional_item_ids"] = [value for value in row.get("optional_item_ids", []) if value in item_ids]
    sets = [row for row in sets if row.get("required_item_ids") or row.get("optional_item_ids")]
    set_ids = {row["set_id"] for row in sets}
    aliases = [row for row in aliases if row.get("target_type") != "set" or row.get("target_id") in set_ids]
    for row in kept:
        row["set_ids"] = [value for value in row.get("set_ids", []) if value in set_ids]
    write_jsonl(item_path, kept)
    write_jsonl(set_path, sets)
    write_jsonl(alias_path, aliases)

    season_path = root / "knowledge/seasons/seasons.jsonl"
    seasons = read_jsonl(season_path)
    for row in seasons:
        row["ultimate_reward_item_ids"] = [value for value in row.get("ultimate_reward_item_ids", []) if value in item_ids and next(item for item in kept if item["item_id"] == value).get("ultimate_reward") is True]
    write_jsonl(season_path, seasons)
    print(json.dumps({"canonical_items": len(kept), "moved_candidates": len(existing), "sets": len(sets), "aliases": len(aliases)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
