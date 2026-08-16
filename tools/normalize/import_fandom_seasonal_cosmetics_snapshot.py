#!/usr/bin/env python3
"""Build a fixed, offline Fandom seasonal-cosmetics snapshot from local wikitext.

The downloader used during research is deliberately not part of this repository.
This command only reads a pinned local revision and never changes canonical data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


SNAPSHOT_ID = "fandom_printable_seasonal_cosmetics_r107991"
SOURCE_ID = "source_fandom_printable_seasonal_cosmetics_r107991"
PAGE_ID = 17690
REVISION_ID = 107991
REVISION_TIMESTAMP = "2026-06-13T11:43:55Z"
PAGE_TITLE = "Sky Children of the Light Wiki:Printable Seasonal Cosmetics"
WIKITEXT_PATH = "data/source/vendor/fandom-seasonal-cosmetics-r107991.wikitext"
SNAPSHOT_PATH = "data/source/vendor/fandom-seasonal-cosmetics-r107991-snapshot.json"
METADATA_PATH = "data/source/vendor/fandom-seasonal-cosmetics-r107991-metadata.json"
PAGE_URL = "https://sky-children-of-the-light.fandom.com/wiki/Sky_Children_of_the_Light_Wiki:Printable_Seasonal_Cosmetics?oldid=107991"
API_REVISION_URL = "https://sky-children-of-the-light.fandom.com/api.php?action=query&prop=revisions&revids=107991&rvprop=ids%7Ctimestamp%7Ccontent&rvslots=main&format=json&formatversion=2"
RESEARCH_DATE = "2026-08-17"

SPIRIT_ITEM = re.compile(r"\{\{Spirit Item\s*\|\s*([^|{}]+?)\s*\|\s*([^|{}]+?)\s*\|", re.IGNORECASE)


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256(value: bytes) -> str:
    # Feed bounded chunks: this also makes the byte-level procedure explicit.
    digest = hashlib.sha256()
    for offset in range(0, len(value), 65536):
        digest.update(value[offset:offset + 65536])
    return digest.hexdigest().upper()


def clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def parse_snapshot(wikitext: str) -> list[dict[str, Any]]:
    """Extract only stable template coordinates, never inferred display item names."""
    matches = list(SPIRIT_ITEM.finditer(wikitext))
    headers = [match for match in matches if clean(match.group(2)).casefold() == "necklace_u"]
    if len(headers) < 20:
        raise ValueError("pinned printable page has too few seasonal headers")
    records: list[dict[str, Any]] = []
    for season_index, header in enumerate(headers):
        end = headers[season_index + 1].start() if season_index + 1 < len(headers) else len(wikitext)
        season_label = clean(header.group(1))
        ordinal = 0
        for item in SPIRIT_ITEM.finditer(wikitext, header.start(), end):
            ordinal += 1
            subject, slot = clean(item.group(1)), clean(item.group(2))
            records.append({
                "source_item_key": f"{season_label}|{subject}|{slot}|{ordinal}",
                "season_label": season_label,
                "template_subject": subject,
                "template_slot": slot,
                "ordinal_in_season": ordinal,
                "source_locator": f"revision:{REVISION_ID}:season:{season_label}:template:{ordinal}",
            })
    if not records:
        raise ValueError("pinned printable page contains no Spirit Item templates")
    return records


def build_snapshot(wikitext_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = wikitext_path.read_bytes()
    try:
        wikitext = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("pinned wikitext must be UTF-8") from exc
    snapshot = {
        "snapshot_format": "fandom-printable-seasonal-cosmetics-v1",
        "snapshot_id": SNAPSHOT_ID,
        "source_id": SOURCE_ID,
        "page_id": PAGE_ID,
        "page_title": PAGE_TITLE,
        "revision_id": REVISION_ID,
        "revision_timestamp": REVISION_TIMESTAMP,
        "extraction_policy": "template_coordinates_only_no_display_name_inference",
        "seasonal_cosmetic_templates": parse_snapshot(wikitext),
    }
    metadata = {
        "snapshot_id": SNAPSHOT_ID,
        "source_id": SOURCE_ID,
        "source_name": "Sky: Children of the Light Wiki — Printable Seasonal Cosmetics (fixed revision)",
        "source_type": "community_wiki",
        "source_relationship": "same_community_source_as_existing_printable_catalog",
        "not_independent_of_source_ids": ["source_sky_wiki_printable_seasonal_cosmetics_2026", "source_skywiki_printable_cosmetics_2026"],
        "independence_status": "not_independent",
        "canonical_promotion": "prohibited_without_independent_review",
        "page_id": PAGE_ID,
        "page_title": PAGE_TITLE,
        "revision_id": REVISION_ID,
        "revision_timestamp": REVISION_TIMESTAMP,
        "page_url": PAGE_URL,
        "api_revision_url": API_REVISION_URL,
        "wikitext_path": WIKITEXT_PATH,
        "wikitext_sha256": sha256(raw),
        "snapshot_path": SNAPSHOT_PATH,
        "snapshot_sha256": sha256(canonical_json(snapshot)),
        "record_count": len(snapshot["seasonal_cosmetic_templates"]),
        "retrieved_at": RESEARCH_DATE,
        "license_notice": "Fandom community-content CC-BY-SA notice recorded for attribution; downstream redistribution permission remains needs_review.",
        "license_verification_status": "needs_review",
        "notes": "A fixed text-only revision saved for offline reproducibility. Template subjects and slots are evidence coordinates, not official item names or canonical identities.",
    }
    return snapshot, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an offline Fandom printable-cosmetics snapshot from pinned local wikitext.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--wikitext", type=Path, default=Path(WIKITEXT_PATH))
    parser.add_argument("--snapshot", type=Path, default=Path(SNAPSHOT_PATH))
    parser.add_argument("--metadata", type=Path, default=Path(METADATA_PATH))
    args = parser.parse_args()
    root = args.root.resolve()
    def local(value: Path) -> Path:
        path = value.resolve() if value.is_absolute() else (root / value).resolve()
        if root not in path.parents:
            raise ValueError("path is outside repository root")
        return path
    snapshot, metadata = build_snapshot(local(args.wikitext))
    for path, content in ((local(args.snapshot), canonical_json(snapshot)), (local(args.metadata), canonical_json(metadata))):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    print(json.dumps({"snapshot_id": SNAPSHOT_ID, "record_count": metadata["record_count"], "snapshot_sha256": metadata["snapshot_sha256"], "canonical_writes": 0}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
