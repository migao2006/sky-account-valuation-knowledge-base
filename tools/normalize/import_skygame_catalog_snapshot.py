#!/usr/bin/env python3
"""Import a fixed, already-downloaded SkyGame-Data package without networking.

This tool deliberately accepts only a local ``.tgz`` package.  It writes a
field-limited snapshot for catalog comparison and provenance metadata; it does
not create or modify canonical Sky item records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
from pathlib import Path
from typing import Any


PACKAGE_NAME = "skygame-data"
PACKAGE_VERSION = "1.3.4"
PACKAGE_COMMIT = "b022d813b2e4bc09d5f2967d1bac77e49c595a75"
PACKAGE_LICENSE = "MIT"
NPM_TARBALL_SHA1 = "e5a59f91fd987bdfad69e6d4696162255a985607"
NPM_INTEGRITY_SHA512 = "LTtPv7/jhgNPM8OcCkFNMBIhPBLeYcF2B2u64Uqiphs9bdVAHG8o42cBMcL03xL48WTwupvBrA+HriiS2NrUyg=="
ASSET_MEMBER = "package/assets/items.json"
EVERYTHING_MEMBER = "package/assets/everything.json"
LICENSE_MEMBER = "package/LICENSE"
RESEARCH_SNAPSHOT_DATE = "2026-08-17"


def digest_bytes(value: bytes, algorithm: str = "sha256") -> str:
    return hashlib.new(algorithm, value).hexdigest().upper()


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def read_member(package_path: Path, member: str) -> bytes:
    with tarfile.open(package_path, "r:gz") as archive:
        found = archive.getmember(member)
        handle = archive.extractfile(found)
        if handle is None:
            raise ValueError(f"missing package member: {member}")
        return handle.read()


def build_snapshot(package_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw_tarball = package_path.read_bytes()
    if digest_bytes(raw_tarball, "sha1").lower() != NPM_TARBALL_SHA1:
        raise ValueError("package SHA-1 does not match the pinned npm package")
    payload = json.loads(read_member(package_path, ASSET_MEMBER).decode("utf-8"))
    everything = json.loads(read_member(package_path, EVERYTHING_MEMBER).decode("utf-8"))
    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("assets/items.json has no items array")
    if everything.get("items", {}).get("items") != raw_items:
        raise ValueError("assets/everything.json items component differs from assets/items.json")
    items: list[dict[str, Any]] = []
    for row in raw_items:
        if not isinstance(row, dict) or not isinstance(row.get("id"), int) or not isinstance(row.get("guid"), str) or not isinstance(row.get("name"), str) or not isinstance(row.get("type"), str):
            raise ValueError("vendor item lacks a stable ID, guid, name, or type")
        items.append({key: row.get(key) for key in ("id", "guid", "name", "type", "subtype", "group")})
    items.sort(key=lambda row: (row["id"], row["guid"]))
    if len({row["id"] for row in items}) != len(items) or len({row["guid"] for row in items}) != len(items):
        raise ValueError("vendor item IDs or GUIDs are not unique")
    snapshot = {
        "snapshot_format": "skygame-data-items-v1",
        "source_package": PACKAGE_NAME,
        "source_version": PACKAGE_VERSION,
        "source_git_commit": PACKAGE_COMMIT,
        "items": items,
    }
    metadata = {
        "snapshot_id": "vendor_skygame_data_1_3_4",
        "source_id": "source_skygame_data_1_3_4",
        "source_name": "SkyGame-Data fixed package snapshot",
        "source_type": "community_database",
        "upstream_repository": "https://github.com/Silverfeelin/SkyGame-Data",
        "source_package": PACKAGE_NAME,
        "source_version": PACKAGE_VERSION,
        "source_git_commit": PACKAGE_COMMIT,
        "license": PACKAGE_LICENSE,
        "npm_tarball_sha1": NPM_TARBALL_SHA1.upper(),
        "npm_integrity_sha512": NPM_INTEGRITY_SHA512,
        "tarball_path": "data/source/vendor/skygame-data-1.3.4.tgz",
        "tarball_sha256": digest_bytes(raw_tarball),
        "license_member": LICENSE_MEMBER,
        "license_sha256": digest_bytes(read_member(package_path, LICENSE_MEMBER)),
        "original_asset_member": ASSET_MEMBER,
        "everything_asset_member": EVERYTHING_MEMBER,
        "everything_items_match": True,
        "record_count": len(items),
        "imported_at": RESEARCH_SNAPSHOT_DATE,
        "evidence_level": "single_secondary_needs_review",
        "canonical_promotion": "prohibited_without_independent_review",
        "notes": "Field-limited offline snapshot. Image URLs, wiki URLs and user data are intentionally excluded.",
    }
    return snapshot, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an offline SkyGame-Data item snapshot from a pinned local package.")
    parser.add_argument("--package", required=True, type=Path, help="Locally downloaded skygame-data-1.3.4.tgz")
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--metadata", required=True, type=Path)
    args = parser.parse_args()
    snapshot, metadata = build_snapshot(args.package.resolve())
    snapshot_bytes = canonical_json(snapshot)
    metadata["snapshot_path"] = args.snapshot.as_posix()
    metadata["snapshot_sha256"] = digest_bytes(snapshot_bytes)
    for path, content in ((args.snapshot, snapshot_bytes), (args.metadata, canonical_json(metadata))):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    print(json.dumps({"snapshot_id": metadata["snapshot_id"], "record_count": metadata["record_count"], "snapshot_sha256": metadata["snapshot_sha256"], "tarball_sha256": metadata["tarball_sha256"]}, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
