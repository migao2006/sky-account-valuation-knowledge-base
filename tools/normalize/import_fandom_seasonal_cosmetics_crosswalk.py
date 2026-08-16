#!/usr/bin/env python3
"""Create a conservative, offline crosswalk for the pinned Fandom snapshot.

Matches merely show that an existing printable-template candidate occurs in the
same Fandom wiki lineage.  They are not independent corroboration and cannot
approve a canonical promotion.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:  # support both direct offline CLI execution and package-level tests
    from .import_fandom_seasonal_cosmetics_snapshot import METADATA_PATH, SNAPSHOT_PATH, SNAPSHOT_ID, SOURCE_ID
except ImportError:  # pragma: no cover - direct script path
    from import_fandom_seasonal_cosmetics_snapshot import METADATA_PATH, SNAPSHOT_PATH, SNAPSHOT_ID, SOURCE_ID


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(65536):
            digest.update(chunk)
    return digest.hexdigest().upper()


def normalized(value: str) -> str:
    return re.sub(r"[^\w]+", "", unicodedata.normalize("NFKC", value).casefold(), flags=re.UNICODE)


def season_key_variants(value: str) -> set[str]:
    """Use only explicit English season-title wrappers, never fuzzy matching."""
    key = normalized(value)
    variants = {key}
    if key.startswith("seasonof"):
        bare = key.removeprefix("seasonof")
        variants.add(bare)
        if bare.startswith("the"):
            variants.add(bare.removeprefix("the"))
    return {entry for entry in variants if entry}


def season_index(seasons: list[dict[str, Any]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for row in seasons:
        for name in [row.get("canonical_name_en"), *row.get("aliases", [])]:
            if isinstance(name, str):
                for key in season_key_variants(name):
                    result[key].add(row["season_id"])
    return result


def candidate_index(candidates: list[dict[str, Any]]) -> dict[tuple[str, str | None], set[str]]:
    result: dict[tuple[str, str | None], set[str]] = defaultdict(set)
    for row in candidates:
        name, candidate_id = row.get("candidate_name_en"), row.get("candidate_item_id")
        if isinstance(name, str) and isinstance(candidate_id, str):
            result[(normalized(name), row.get("season_id"))].add(candidate_id)
    return result


def verify_snapshot(snapshot: dict[str, Any], metadata: dict[str, Any], snapshot_path: Path) -> None:
    required = {"snapshot_id", "source_id", "snapshot_sha256", "wikitext_sha256", "record_count", "independence_status", "canonical_promotion"}
    if required - metadata.keys():
        raise ValueError("Fandom snapshot metadata is missing required provenance")
    if metadata["snapshot_id"] != SNAPSHOT_ID or metadata["source_id"] != SOURCE_ID:
        raise ValueError("unexpected Fandom snapshot identity")
    if metadata["independence_status"] != "not_independent" or metadata["canonical_promotion"] != "prohibited_without_independent_review":
        raise ValueError("Fandom source must remain non-independent and non-promoting")
    if sha256(snapshot_path) != metadata["snapshot_sha256"]:
        raise ValueError("Fandom snapshot SHA-256 mismatch")
    if snapshot.get("snapshot_id") != SNAPSHOT_ID or snapshot.get("source_id") != SOURCE_ID:
        raise ValueError("Fandom snapshot content identity mismatch")
    if len(snapshot.get("seasonal_cosmetic_templates", [])) != metadata["record_count"]:
        raise ValueError("Fandom snapshot record count mismatch")


def crosswalk(snapshot: dict[str, Any], metadata: dict[str, Any], seasons: list[dict[str, Any]], candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    seasons_by_name, candidates_by_name = season_index(seasons), candidate_index(candidates)
    rows: list[dict[str, Any]] = []
    for source in snapshot["seasonal_cosmetic_templates"]:
        season_targets: set[str] = set()
        for key in season_key_variants(source["season_label"]):
            season_targets.update(seasons_by_name.get(key, set()))
        season_ids = sorted(season_targets)
        candidate_ids: list[str] = []
        if len(season_ids) == 1:
            candidate_ids = sorted(candidates_by_name.get((normalized(f"{source['template_subject']} {source['template_slot']}"), season_ids[0]), set()))
        if len(season_ids) == 1 and len(candidate_ids) == 1:
            status = "season_mapped_candidate_linked"
        elif len(season_ids) > 1:
            status = "ambiguous_season"
        elif not season_ids:
            status = "unmapped_season"
        elif len(candidate_ids) > 1:
            status = "ambiguous_candidate"
        else:
            status = "season_mapped_no_candidate_link"
        rows.append({
            "snapshot_id": SNAPSHOT_ID,
            "source_id": SOURCE_ID,
            "source_independence": "not_independent_same_fandom_wiki",
            "source_item_key": source["source_item_key"],
            "source_locator": source["source_locator"],
            "season_label": source["season_label"],
            "template_subject": source["template_subject"],
            "template_slot": source["template_slot"],
            "season_ids": season_ids,
            "candidate_item_ids": candidate_ids,
            "match_status": status,
            "review_status": "needs_review" if status != "season_mapped_no_candidate_link" else "not_required",
            "promotion_effect": "none",
        })
    counts = Counter(row["match_status"] for row in rows)
    summary = {
        "snapshot_id": SNAPSHOT_ID,
        "source_id": SOURCE_ID,
        "snapshot_sha256": metadata["snapshot_sha256"],
        "template_record_count": len(rows),
        "status_counts": dict(sorted(counts.items())),
        "candidate_linked_count": counts["season_mapped_candidate_linked"],
        "independent_evidence_count": 0,
        "canonical_writes": 0,
        "source_independence": "not_independent_same_fandom_wiki",
        "canonical_promotion": "not_performed",
        "notes": "This is a revision-pinned same-lineage Fandom crosswalk. It records template-coordinate overlap only; it is not a second independent source and cannot approve canonical promotion.",
    }
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Crosswalk pinned Fandom printable templates without network access.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--snapshot", type=Path, default=Path(SNAPSHOT_PATH))
    parser.add_argument("--metadata", type=Path, default=Path(METADATA_PATH))
    parser.add_argument("--seasons", type=Path, default=Path("knowledge/seasons/seasons.jsonl"))
    parser.add_argument("--candidates", type=Path, default=Path("data/review/item-candidates.jsonl"))
    parser.add_argument("--output", type=Path, default=Path("data/review/fandom-seasonal-cosmetics-r107991-crosswalk.jsonl"))
    parser.add_argument("--summary", type=Path, default=Path("data/review/fandom-seasonal-cosmetics-r107991-crosswalk-summary.json"))
    args = parser.parse_args(); root = args.root.resolve()
    def local(value: Path, require_inside: bool = True) -> Path:
        path = value.resolve() if value.is_absolute() else (root / value).resolve()
        if require_inside and root not in path.parents:
            raise ValueError("path is outside repository root")
        return path
    snapshot_path, metadata_path = local(args.snapshot), local(args.metadata)
    snapshot, metadata = read_json(snapshot_path), read_json(metadata_path)
    verify_snapshot(snapshot, metadata, snapshot_path)
    rows, summary = crosswalk(snapshot, metadata, read_jsonl(local(args.seasons)), read_jsonl(local(args.candidates)))
    output, summary_path = local(args.output, require_inside=False), local(args.summary, require_inside=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8", newline="\n")
    summary_path.write_bytes(canonical_json(summary))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
