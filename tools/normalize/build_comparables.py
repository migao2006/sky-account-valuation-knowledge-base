#!/usr/bin/env python3
"""Rebuild all comparable outputs from canonical P0 profiles and histories."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8")


def build(root: Path) -> dict[str, int]:
    profiles = {row["account_id"]: row for row in read_jsonl(root / "data/normalized/account-profiles.jsonl")}
    histories = read_jsonl(root / "data/curated/histories.jsonl")
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
        accounts.append(profile)
    write_jsonl(root / "data/comparables/histories.jsonl", histories)
    write_jsonl(root / "data/comparables/accounts.jsonl", accounts)
    return {"histories": len(histories), "accounts": len(accounts)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(json.dumps(build(args.root.resolve()), ensure_ascii=False))


if __name__ == "__main__":
    main()
