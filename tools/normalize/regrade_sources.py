"""Offline knowledge-metadata regrade.

This intentionally changes only verification metadata in season/event JSONL
records. It never fetches a URL and never alters catalogue identities/items.
"""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "knowledge" / "sources" / "sources.jsonl"
TARGETS = (
    ROOT / "knowledge" / "seasons" / "seasons.jsonl",
    ROOT / "knowledge" / "events" / "events.jsonl",
    ROOT / "knowledge" / "items" / "items.jsonl",
    ROOT / "knowledge" / "sets" / "item-sets.jsonl",
    ROOT / "knowledge" / "aliases" / "item-aliases.jsonl",
    ROOT / "knowledge" / "acquisition" / "availability-events.jsonl",
)
VAN_GOGH_SOURCE = "source_tgc_july_2026"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8", newline="\n")


OFFICIAL_TYPES = {"official", "official_site", "official_news", "official_support", "thatgamecompany"}


def lacks_official_source(record: dict, sources: dict[str, dict]) -> bool:
    ids = list(dict.fromkeys(record.get("source_ids", [])))
    return not any(sources.get(source_id, {}).get("source_type") in OFFICIAL_TYPES for source_id in ids)


def main() -> None:
    sources = {row["source_id"]: row for row in read_jsonl(SOURCES)}
    if VAN_GOGH_SOURCE not in sources:
        raise SystemExit(f"missing required official source: {VAN_GOGH_SOURCE}")
    changed = 0
    downgraded = 0
    for target in TARGETS:
        rows = read_jsonl(target)
        for row in rows:
            if row.get("season_id") == "season_dear_van_gogh" or row.get("event_id") == "event_collab_van_gogh":
                if row.get("end_date") != "2026-10-01":
                    row["end_date"] = "2026-10-01"; changed += 1
                if VAN_GOGH_SOURCE not in row.setdefault("source_ids", []):
                    row["source_ids"].append(VAN_GOGH_SOURCE); changed += 1
                if row.get("verification_status") != "verified":
                    row["verification_status"] = "verified"; changed += 1
            if row.get("verification_status") == "verified" and lacks_official_source(row, sources):
                row["verification_status"] = "needs_review"
                marker = "[regrade: no official source; independent corroboration required]"
                if marker not in row.get("notes", ""):
                    row["notes"] = (row.get("notes", "") + " " + marker).strip()
                changed += 1; downgraded += 1
        write_jsonl(target, rows)
    print(json.dumps({"changed_fields": changed, "downgraded_single_community_records": downgraded}, ensure_ascii=False))


if __name__ == "__main__":
    main()
