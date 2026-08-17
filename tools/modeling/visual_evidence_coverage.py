#!/usr/bin/env python3
"""Build a deterministic, fail-closed visual evidence capability report.

The report is intentionally an audit of what is actually stored.  A source
description is a catalog locator, not an image asset or a detection.  Image
hashes are counted as content-addressed assets only when an offline registry
row points at a local file whose bytes match the declared SHA-256.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import zlib
from datetime import date
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ASSET_REGISTRY = Path("data/curated/visual-assets.jsonl")
ASSET_DIRECTORY = Path("data/curated/visual-assets")
SHA256_RE = re.compile(r"^[A-Fa-f0-9]{64}$")


def _json_pointer(document: Any, pointer: object) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise ValueError("rights evidence claim locator must be an RFC6901 pointer")
    current = document
    for encoded in pointer[1:].split("/"):
        part = encoded.replace("~1", "/").replace("~0", "~")
        try:
            current = current[int(part)] if isinstance(current, list) else current[part]
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise ValueError("rights evidence claim locator does not resolve") from exc
    return current


def _validate_rights_evidence(row: dict[str, Any], root: Path) -> None:
    evidence = row.get("rights_evidence")
    required = {"source_id", "snapshot_path", "snapshot_sha256", "claim_locator", "claim_value"}
    if not isinstance(evidence, dict) or set(evidence) != required:
        raise ValueError("unavailable visual reference lacks replayable rights evidence")
    if evidence.get("source_id") not in row.get("source_ids", []):
        raise ValueError("rights evidence source is not bound by the visual reference")
    registered = {entry.get("source_id") for entry in read_jsonl(root / "knowledge/sources/sources.jsonl")}
    if evidence.get("source_id") not in registered:
        raise ValueError("rights evidence source is not registered")
    relative = evidence.get("snapshot_path")
    if not isinstance(relative, str) or "\\" in relative or not relative.startswith("data/source/") or not relative.endswith(".json") or ".." in Path(relative).parts:
        raise ValueError("rights evidence snapshot path is invalid")
    snapshot = (root / relative).resolve()
    if root.resolve() not in snapshot.parents or not snapshot.is_file():
        raise ValueError("rights evidence snapshot is missing")
    if not isinstance(evidence.get("snapshot_sha256"), str) or _sha256(snapshot).upper() != evidence["snapshot_sha256"].upper():
        raise ValueError("rights evidence snapshot SHA-256 mismatch")
    document = json.loads(snapshot.read_text(encoding="utf-8"))
    if _json_pointer(document, evidence.get("claim_locator")) != evidence.get("claim_value") or evidence.get("claim_value") != "rights_not_granted_for_redistribution":
        raise ValueError("rights evidence claim does not establish redistribution unavailability")


def _validate_png(path: Path) -> None:
    """Accept only structurally decodable PNG assets without a GUI dependency."""
    data = path.read_bytes()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError(f"visual asset has PNG MIME but invalid magic: {path.as_posix()}")
    position, seen_ihdr, seen_iend, idat = 8, False, False, bytearray()
    while position < len(data):
        if position + 12 > len(data):
            raise ValueError(f"visual asset has truncated PNG chunk: {path.as_posix()}")
        length = struct.unpack(">I", data[position:position + 4])[0]
        chunk_type = data[position + 4:position + 8]
        end = position + 12 + length
        if end > len(data):
            raise ValueError(f"visual asset has oversized PNG chunk: {path.as_posix()}")
        payload, crc = data[position + 8:position + 8 + length], data[position + 8 + length:end]
        if zlib.crc32(chunk_type + payload).to_bytes(4, "big") != crc:
            raise ValueError(f"visual asset has invalid PNG CRC: {path.as_posix()}")
        if chunk_type == b"IHDR":
            if seen_ihdr or length != 13:
                raise ValueError(f"visual asset has invalid PNG IHDR: {path.as_posix()}")
            width, height = struct.unpack(">II", payload[:8])
            if width < 1 or height < 1:
                raise ValueError(f"visual asset has invalid PNG dimensions: {path.as_posix()}")
            seen_ihdr = True
        elif chunk_type == b"IDAT":
            idat.extend(payload)
        elif chunk_type == b"IEND":
            if length != 0 or end != len(data):
                raise ValueError(f"visual asset has invalid PNG end: {path.as_posix()}")
            seen_iend = True
            break
        position = end
    if not seen_ihdr or not seen_iend or not idat:
        raise ValueError(f"visual asset is not a decodable PNG: {path.as_posix()}")
    try:
        zlib.decompress(bytes(idat))
    except zlib.error as exc:
        raise ValueError(f"visual asset has undecodable PNG pixels: {path.as_posix()}") from exc


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read a JSONL file, preserving input order for deterministic checks."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: expected a JSON object")
        rows.append(value)
    return rows


def _require_unique(rows: Iterable[dict[str, Any]], key: str, label: str) -> None:
    values = [row.get(key) for row in rows]
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError(f"{label} must have non-empty {key}")
    if len(values) != len(set(values)):
        raise ValueError(f"{label} must have unique {key}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _validate_asset_registry(rows: list[dict[str, Any]], root: Path) -> dict[str, dict[str, Any]]:
    """Validate and replay local content-addressed asset registry rows."""
    _require_unique(rows, "asset_registry_id", "visual asset registry")
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        registry_id = row.get("asset_registry_id")
        digest = row.get("asset_sha256")
        asset_path = row.get("asset_path")
        mime_type = row.get("mime_type")
        if not isinstance(registry_id, str) or not re.fullmatch(r"asset_[a-z0-9_]+", registry_id):
            raise ValueError(f"asset registry has invalid asset_registry_id: {registry_id!r}")
        if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
            raise ValueError(f"asset registry has invalid asset_sha256: {registry_id}")
        if not isinstance(asset_path, str) or not asset_path:
            raise ValueError(f"asset registry has invalid asset_path: {registry_id}")
        if mime_type != "image/png":
            raise ValueError(f"asset registry has unsupported or missing MIME type: {registry_id}")
        candidate = Path(asset_path)
        if candidate.is_absolute() or ".." in candidate.parts or candidate.suffix.lower() != ".png" or not candidate.is_relative_to(ASSET_DIRECTORY):
            raise ValueError(f"asset registry path must be under {ASSET_DIRECTORY.as_posix()}: {registry_id}")
        resolved = (root / candidate).resolve()
        if root.resolve() not in resolved.parents or not resolved.is_file():
            raise ValueError(f"asset registry file is missing: {registry_id}")
        actual = _sha256(resolved)
        if actual.casefold() != digest.casefold():
            raise ValueError(f"asset registry SHA-256 mismatch: {registry_id}")
        _validate_png(resolved)
        by_id[registry_id] = {**row, "asset_sha256": digest.casefold(), "asset_path": candidate.as_posix()}
    return by_id


def _validate_inputs(
    items: list[dict[str, Any]],
    visual_references: list[dict[str, Any]],
    image_evidence: list[dict[str, Any]],
    assets: dict[str, dict[str, Any]],
    root: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    _require_unique(items, "item_id", "canonical items")
    item_by_id = {row["item_id"]: row for row in items}
    _require_unique(visual_references, "visual_reference_id", "visual references")
    detection_values = [row.get("detection_id") for row in image_evidence if row.get("detection_id") is not None]
    if any(not isinstance(value, str) or not value for value in detection_values):
        raise ValueError("image evidence has invalid detection_id")
    if len(detection_values) != len(set(detection_values)):
        raise ValueError("image evidence must have unique non-null detection_id values")

    for row in visual_references:
        visual_id = row.get("visual_reference_id")
        item_id = row.get("item_id")
        mode = row.get("reference_mode")
        if item_id not in item_by_id:
            raise ValueError(f"visual reference has dangling item: {visual_id}")
        if mode != "unavailable" and row.get("unavailable_reason") is not None:
            raise ValueError(f"only unavailable visual references may carry an unavailable reason: {visual_id}")
        if mode != "unavailable" and row.get("rights_evidence") is not None:
            raise ValueError(f"only unavailable visual references may carry rights evidence: {visual_id}")
        if mode == "offline_asset":
            registry_id = row.get("asset_registry_id")
            digest = row.get("asset_sha256")
            if registry_id not in assets:
                raise ValueError(f"offline visual reference has no registry binding: {visual_id}")
            if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
                raise ValueError(f"offline visual reference has invalid asset hash: {visual_id}")
            if digest.casefold() != assets[registry_id]["asset_sha256"]:
                raise ValueError(f"offline visual reference hash disagrees with registry: {visual_id}")
        elif mode == "source_description":
            if row.get("asset_sha256") is not None:
                raise ValueError(f"source-description reference cannot carry an asset hash: {visual_id}")
            if row.get("asset_registry_id") is not None:
                raise ValueError(f"source-description reference cannot bind an asset: {visual_id}")
            if row.get("detection_ids"):
                raise ValueError(f"source-description reference cannot be a detection: {visual_id}")
        elif mode == "unavailable":
            if row.get("asset_sha256") is not None or row.get("asset_registry_id") is not None:
                raise ValueError(f"unavailable visual reference cannot carry an asset: {visual_id}")
            if row.get("detection_ids"):
                raise ValueError(f"unavailable visual reference cannot be a detection: {visual_id}")
            if row.get("unavailable_reason") != "rights_not_granted_for_redistribution" or not isinstance(row.get("description"), str) or not row["description"].strip() or not isinstance(row.get("source_ids"), list) or not row["source_ids"]:
                raise ValueError(f"unavailable visual reference lacks a verified rights/source explanation: {visual_id}")
            _validate_rights_evidence(row, root)
        else:
            raise ValueError(f"visual reference has invalid reference_mode: {visual_id}")

    detection_ids: set[str] = set()
    approved: list[dict[str, Any]] = []
    asset_hashes = {row["asset_sha256"] for row in assets.values()}
    for row in image_evidence:
        detection_id = row.get("detection_id")
        if detection_id is not None:
            if not isinstance(detection_id, str) or not detection_id:
                raise ValueError("image evidence has invalid detection_id")
            if detection_id in detection_ids:
                raise ValueError(f"image evidence has duplicate detection_id: {detection_id}")
            detection_ids.add(detection_id)
        is_approved = row.get("review_status") == "approved" and row.get("evidence_state") == "confirmed"
        if not is_approved:
            continue
        item_id = row.get("detected_item_id")
        image_hash = row.get("image_sha256")
        if not detection_id or item_id not in item_by_id:
            raise ValueError(f"approved detection is missing a canonical item or detection ID: {detection_id}")
        if not isinstance(image_hash, str) or image_hash.casefold() not in asset_hashes:
            raise ValueError(f"approved detection is not backed by a registered asset: {detection_id}")
        approved.append(row)
    return item_by_id, approved


def actual_visual_item_ids(
    items: list[dict[str, Any]], visual_references: list[dict[str, Any]],
    image_evidence: list[dict[str, Any]], asset_registry: list[dict[str, Any]], *, root: Path,
) -> set[str]:
    """Return only items with an approved asset-backed visual fact.

    A description is deliberately absent here.  A verified offline asset or an
    approved, registry-backed detection is the minimum usable visual evidence.
    """
    assets = _validate_asset_registry(asset_registry, root.resolve())
    _item_by_id, approved = _validate_inputs(items, visual_references, image_evidence, assets, root)
    approved_items = {str(row["detected_item_id"]) for row in approved}
    asset_items = {
        str(row["item_id"])
        for row in visual_references
        if row.get("reference_mode") == "offline_asset"
        and row.get("verification_status") == "verified"
        and row.get("asset_registry_id") in assets
        and str(row.get("asset_sha256", "")).casefold() == assets[row["asset_registry_id"]]["asset_sha256"]
    }
    return approved_items | asset_items


def complete_visual_state_item_ids(
    items: list[dict[str, Any]], visual_references: list[dict[str, Any]],
    image_evidence: list[dict[str, Any]], asset_registry: list[dict[str, Any]], *, root: Path,
) -> set[str]:
    """Return items whose visual state is complete without inventing an image.

    Asset-backed facts remain the only actual visual evidence.  A separately
    verified ``unavailable`` record satisfies catalog state coverage only when
    redistribution rights are explicitly absent and a source-backed textual
    locator is retained, as required by the completion contract.
    """
    assets = _validate_asset_registry(asset_registry, root.resolve())
    _validate_inputs(items, visual_references, image_evidence, assets, root)
    return actual_visual_item_ids(items, visual_references, image_evidence, asset_registry, root=root) | {
        str(row["item_id"])
        for row in visual_references
        if row.get("reference_mode") == "unavailable"
        and row.get("verification_status") == "verified"
        and row.get("unavailable_reason") == "rights_not_granted_for_redistribution"
    }


def _as_of_date(items: list[dict[str, Any]]) -> str:
    dates = [row.get("last_verified_at") for row in items if isinstance(row.get("last_verified_at"), str)]
    if not dates:
        return "1970-01-01"
    for value in dates:
        date.fromisoformat(value)
    return max(dates)


def audit(
    items: list[dict[str, Any]],
    visual_references: list[dict[str, Any]],
    image_evidence: list[dict[str, Any]],
    asset_registry: list[dict[str, Any]],
    *,
    root: Path,
    as_of_date: str | None = None,
    input_paths: dict[str, str] | None = None,
    asset_registry_present: bool | None = None,
) -> dict[str, Any]:
    """Return visual evidence coverage without creating or inferring evidence."""
    root = root.resolve()
    assets = _validate_asset_registry(asset_registry, root)
    item_by_id, approved_detections = _validate_inputs(items, visual_references, image_evidence, assets, root)
    approved_ids = {row["detection_id"] for row in approved_detections}
    approved_by_item: dict[str, set[str]] = {}
    for row in approved_detections:
        approved_by_item.setdefault(row["detected_item_id"], set()).add(row["detection_id"])

    scope_predicates = {
        "all": lambda row: True,
        "verified": lambda row: row.get("verification_status") == "verified",
        "eligible": lambda row: row.get("model_feature_status") == "eligible",
    }
    counts: dict[str, dict[str, int]] = {}
    for scope_name, predicate in scope_predicates.items():
        scope_item_ids = {item_id for item_id, row in item_by_id.items() if predicate(row)}
        refs = [row for row in visual_references if row.get("item_id") in scope_item_ids]
        assets_for_scope = {
            row["asset_sha256"].casefold()
            for row in refs
            if row.get("reference_mode") == "offline_asset" and row.get("asset_sha256")
        }
        detection_for_scope = {
            detection_id
            for item_id in scope_item_ids
            for detection_id in approved_by_item.get(item_id, set())
        }
        counts[scope_name] = {
            "catalog_items": len(scope_item_ids),
            "catalog_identity_locators": len({row["item_id"] for row in refs}),
            "actual_content_addressed_assets": len(assets_for_scope),
            "asset_backed_refs": sum(row.get("reference_mode") == "offline_asset" for row in refs),
            "approved_detections": len(detection_for_scope),
            "source_description_only_refs": sum(row.get("reference_mode") == "source_description" for row in refs),
        }

    hashes = [row["asset_sha256"] for row in assets.values()]
    duplicate_hash_count = len(hashes) - len(set(hashes))
    limitations = [
        "Catalog identity locators are canonical item links in visual-reference rows; they do not assert a visual match.",
        "Source-description references are text-only locators and are never counted as assets or detections.",
        "Approved detections require confirmed review and a registry-backed image hash; no recognition accuracy is inferred.",
    ]
    registry_present = bool(asset_registry) if asset_registry_present is None else asset_registry_present
    if not registry_present:
        limitations.insert(0, "No visual asset registry is present; actual content-addressed asset and asset-backed reference counts are zero.")
    elif not asset_registry:
        limitations.insert(0, "The visual asset registry is present but contains no rows; actual content-addressed asset and asset-backed reference counts are zero.")
    if not image_evidence:
        limitations.insert(1 if not asset_registry else 0, "The image-evidence ledger is empty; approved detection counts are zero.")
    paths = input_paths or {
        "items": "knowledge/items/items.jsonl",
        "visual_references": "knowledge/visual-references/manifest.jsonl",
        "image_evidence": "data/curated/image-evidence.jsonl",
        "asset_registry": DEFAULT_ASSET_REGISTRY.as_posix(),
    }
    return {
        "schema_version": "1.1-p3.7",
        "as_of_date": as_of_date or _as_of_date(items),
        "offline_only": True,
        "inputs": {
            **paths,
            "asset_registry_present": bool(asset_registry) if asset_registry_present is None else asset_registry_present,
        },
        "scope_definitions": {
            "all": "All canonical item rows in knowledge/items/items.jsonl.",
            "verified": "Canonical items with verification_status=verified.",
            "eligible": "Canonical items with model_feature_status=eligible.",
        },
        "metric_definitions": {
            "catalog_items": "Count of canonical items in the scope.",
            "catalog_identity_locators": "Count of distinct canonical item IDs linked by visual-reference rows in the scope.",
            "actual_content_addressed_assets": "Count of distinct SHA-256 assets referenced by registry-bound offline_asset rows in the scope.",
            "asset_backed_refs": "Count of visual-reference rows in offline_asset mode with a matching registry binding.",
            "approved_detections": "Count of distinct detection IDs with approved review, confirmed evidence, a canonical item, and a registry-backed image hash.",
            "source_description_only_refs": "Count of visual-reference rows in source_description mode; these remain non-visual text locators.",
        },
        "counts": counts,
        "asset_registry_summary": {
            "row_count": len(asset_registry),
            "unique_content_addressed_asset_count": len(set(hashes)),
            "duplicate_hash_count": duplicate_hash_count,
        },
        "detection_summary": {
            "image_evidence_row_count": len(image_evidence),
            "approved_detection_count": len(approved_ids),
            "unapproved_detection_count": len({row["detection_id"] for row in image_evidence if row.get("detection_id")} - approved_ids),
        },
        "limitations": limitations,
    }


def build(root: Path, asset_registry: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    registry_path = asset_registry or DEFAULT_ASSET_REGISTRY
    if not registry_path.is_absolute():
        registry_path = root / registry_path
    required_paths = [
        root / "knowledge/items/items.jsonl",
        root / "knowledge/visual-references/manifest.jsonl",
        root / "data/curated/image-evidence.jsonl",
    ]
    missing = [str(path) for path in required_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("visual coverage input missing: " + ", ".join(missing))
    return audit(
        read_jsonl(root / "knowledge/items/items.jsonl"),
        read_jsonl(root / "knowledge/visual-references/manifest.jsonl"),
        read_jsonl(root / "data/curated/image-evidence.jsonl"),
        read_jsonl(registry_path),
        root=root,
        input_paths={
            "items": _relative_path(root / "knowledge/items/items.jsonl", root),
            "visual_references": _relative_path(root / "knowledge/visual-references/manifest.jsonl", root),
            "image_evidence": _relative_path(root / "data/curated/image-evidence.jsonl", root),
            "asset_registry": _relative_path(registry_path, root),
        },
        asset_registry_present=registry_path.is_file(),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Build deterministic visual evidence capability coverage")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--asset-registry", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(build(args.root, args.asset_registry), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
