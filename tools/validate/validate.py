#!/usr/bin/env python3
"""Offline integrity validation for the P0 package (standard library only)."""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "estimate"))
from evidence import validate_evidence  # noqa: E402
from schema_validator import OfflineSchemaValidator  # noqa: E402

CANONICAL_FILES = {
    "season": "knowledge/seasons/seasons.jsonl", "event": "knowledge/events/events.jsonl",
    "item": "knowledge/items/items.jsonl", "set": "knowledge/sets/item-sets.jsonl",
    "source": "knowledge/sources/sources.jsonl",
}
SCHEMA_FILES = {
    "knowledge/seasons/seasons.jsonl": "schemas/knowledge/season.schema.json",
    "knowledge/seasons/ancestors.jsonl": "schemas/knowledge/ancestor.schema.json",
    "knowledge/events/events.jsonl": "schemas/knowledge/event.schema.json",
    "knowledge/items/items.jsonl": "schemas/knowledge/item.schema.json",
    "knowledge/sets/item-sets.jsonl": "schemas/knowledge/item-set.schema.json",
    "knowledge/aliases/item-aliases.jsonl": "schemas/knowledge/alias.schema.json",
    "knowledge/acquisition/availability-events.jsonl": "schemas/knowledge/availability-event.schema.json",
    "knowledge/sources/sources.jsonl": "schemas/knowledge/source.schema.json",
    "knowledge/visual-references/manifest.jsonl": "schemas/knowledge/visual-reference.schema.json",
    "data/source/listings.jsonl": "schemas/market/source-listing.schema.json",
    "data/normalized/listings.jsonl": "schemas/market/listing.schema.json",
    "data/normalized/account-profiles.jsonl": "schemas/market/account-profile.schema.json",
    "data/curated/histories.jsonl": "schemas/market/history.schema.json",
    "data/comparables/histories.jsonl": "schemas/market/history.schema.json",
    "data/comparables/accounts.jsonl": "schemas/market/comparable-account.schema.json",
    "data/curated/image-evidence.jsonl": "schemas/evidence/image-evidence.schema.json",
    "data/review/item-candidates.jsonl": "schemas/review/item-candidate.schema.json",
    "data/review/unmapped-item-aliases.jsonl": "schemas/review/unmapped-alias.schema.json",
    "data/review/unmapped-season-aliases.jsonl": "schemas/review/unmapped-alias.schema.json",
    "data/review/price-type-review.jsonl": "schemas/review/price-type-review.schema.json",
    "reports/coverage/unmapped-aliases.jsonl": "schemas/reports/unmapped-coverage.schema.json",
    "reports/coverage/unresolved-items.jsonl": "schemas/reports/unresolved-item.schema.json",
    "reports/migration/migration-ledger.jsonl": "schemas/reports/migration-ledger.schema.json",
}
JSON_SCHEMA_FILES = {
    "manifest.json": "schemas/package-manifest.schema.json",
    "reports/coverage/catalog-coverage.json": "schemas/reports/coverage.schema.json",
    "reports/migration/migration-summary.json": "schemas/reports/migration-summary.schema.json",
    "reports/migration/file-inventory.json": "schemas/reports/file-inventory.schema.json",
    "reports/validation/p0-validation.json": "schemas/reports/validation.schema.json",
}
REQUIRED_FORMAL_JSONL = {
    "data/source/listings.jsonl", "data/normalized/listings.jsonl", "data/normalized/account-profiles.jsonl",
    "data/curated/histories.jsonl", "data/comparables/histories.jsonl", "data/comparables/accounts.jsonl",
}
PRIVATE_KEYS = {"player_name", "account_name", "uid", "phone", "email", "payment", "login", "password", "social_handle", "source_url", "url", "raw_ocr", "ocr_text"}
PRIVATE_VALUE_PATTERNS = {
    "url": re.compile(r"https?://|www\.", re.I),
    "email": re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I),
    "taiwan_phone": re.compile(r"(?<!\d)09\d{8}(?!\d)"),
    "contact_handle": re.compile(r"(?:line\s*(?:id)?|discord|telegram|wechat|whatsapp)\s*[:：]?\s*[A-Z0-9_.-]+", re.I),
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{number} is not an object")
            records.append(value)
    return records


def validate(root: Path = ROOT) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    ids: dict[str, set[str]] = {}
    records_by_path: dict[Path, list[dict[str, Any]]] = {}
    schema_validator = OfflineSchemaValidator(root / "schemas")
    schema_checked = 0
    actual_formal_json = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix in {".json", ".jsonl"}
        and "schemas" not in path.parts
        and "tests" not in path.parts
        and "fixtures" not in path.parts
        and "__pycache__" not in path.parts
    }
    declared_formal_json = set(SCHEMA_FILES) | set(JSON_SCHEMA_FILES)
    for rel in sorted(actual_formal_json - declared_formal_json):
        errors.append(f"formal JSON/JSONL has no schema mapping: {rel}")
    for rel in sorted(declared_formal_json - actual_formal_json):
        errors.append(f"schema mapping points to missing formal data: {rel}")
    for rel, schema_rel in SCHEMA_FILES.items():
        path = root / rel
        if rel in REQUIRED_FORMAL_JSONL and not path.exists():
            errors.append(f"required formal JSONL missing: {rel}")
            continue
        try:
            rows = read_jsonl(path)
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc)); continue
        for index, row in enumerate(rows, 1):
            schema_checked += 1
            for issue in schema_validator.validate(row, root / schema_rel):
                errors.append(f"{rel}:{index}:{issue}")
    for rel, schema_rel in JSON_SCHEMA_FILES.items():
        path = root / rel
        if not path.exists():
            errors.append(f"required formal JSON missing: {rel}")
            continue
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{rel}: {exc}")
            continue
        for issue in schema_validator.validate(value, root / schema_rel):
            errors.append(f"{rel}:{issue}")
    for kind, rel in CANONICAL_FILES.items():
        path = root / rel
        try:
            rows = read_jsonl(path)
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc)); rows = []
        records_by_path[path] = rows
        seen: set[str] = set()
        for index, row in enumerate(rows, 1):
            ident = row.get(f"{kind}_id")
            if not isinstance(ident, str) or not ident.startswith(kind + "_"):
                errors.append(f"{rel}:{index}: invalid {kind}_id")
            elif ident in seen:
                errors.append(f"{rel}:{index}: duplicate {ident}")
            else:
                seen.add(ident)
        ids[kind] = seen
    # Canonical cross-references are checked only when their fields are present.
    for row in records_by_path.get(root / CANONICAL_FILES["item"], []):
        iid = row.get("item_id", "unknown")
        for field, kind in (("season_id", "season"), ("event_id", "event"), ("source_id", "source")):
            value = row.get(field)
            if value not in (None, "unknown") and value not in ids[kind]:
                errors.append(f"item:{iid}: dangling {field}={value}")
        for source_id in row.get("source_ids", []):
            if source_id not in ids["source"]:
                errors.append(f"item:{iid}: dangling source_ids={source_id}")
    for row in records_by_path.get(root / CANONICAL_FILES["set"], []):
        sid = row.get("set_id", "unknown")
        member_ids = list(row.get("required_item_ids", [])) + list(row.get("optional_item_ids", []))
        for item_id in member_ids:
            if item_id not in ids["item"]:
                errors.append(f"set:{sid}: dangling item={item_id}")
    # Complete knowledge graph references.
    seasons = {row["season_id"]: row for row in read_jsonl(root / "knowledge/seasons/seasons.jsonl")}
    events = {row["event_id"]: row for row in read_jsonl(root / "knowledge/events/events.jsonl")}
    items = {row["item_id"]: row for row in read_jsonl(root / "knowledge/items/items.jsonl")}
    sets = {row["set_id"]: row for row in read_jsonl(root / "knowledge/sets/item-sets.jsonl")}
    ancestors = {row["ancestor_id"]: row for row in read_jsonl(root / "knowledge/seasons/ancestors.jsonl")}
    sources = ids.get("source", set())
    for sid, row in seasons.items():
        for ref in row.get("related_event_ids", []):
            if ref not in events: errors.append(f"season:{sid}: dangling event={ref}")
        for ref in row.get("ultimate_reward_item_ids", []):
            if ref not in items: errors.append(f"season:{sid}: dangling ultimate item={ref}")
        for ref in row.get("source_ids", []):
            if ref not in sources: errors.append(f"season:{sid}: dangling source={ref}")
    for aid, row in ancestors.items():
        if row.get("season_id") not in seasons: errors.append(f"ancestor:{aid}: dangling season")
        for ref in row.get("source_ids", []):
            if ref not in sources: errors.append(f"ancestor:{aid}: dangling source={ref}")
    for eid, row in events.items():
        for ref in row.get("source_ids", []):
            if ref not in sources: errors.append(f"event:{eid}: dangling source={ref}")
    for iid, row in items.items():
        if row.get("ancestor_id") and row["ancestor_id"] not in ancestors: errors.append(f"item:{iid}: dangling ancestor")
        for ref in row.get("set_ids", []):
            if ref not in sets: errors.append(f"item:{iid}: dangling set={ref}")
    target_ids = {"season": set(seasons), "event": set(events), "item": set(items), "set": set(sets), "ancestor": set(ancestors)}
    alias_targets: dict[tuple[str, str], set[str]] = {}
    for row in read_jsonl(root / "knowledge/aliases/item-aliases.jsonl"):
        if row.get("target_id") not in target_ids.get(row.get("target_type"), set()):
            errors.append(f"alias:{row.get('alias_id')}: dangling target")
        for ref in row.get("source_ids", []):
            if ref not in sources: errors.append(f"alias:{row.get('alias_id')}: dangling source={ref}")
        key = (str(row.get("target_type")), str(row.get("normalized_alias")))
        alias_targets.setdefault(key, set()).add(str(row.get("target_id")))
    for (target_type, alias), targets in alias_targets.items():
        if len(targets) > 1:
            errors.append(f"alias:{target_type}:{alias}: ambiguous canonical targets={sorted(targets)}")
    for row in read_jsonl(root / "knowledge/acquisition/availability-events.jsonl"):
        ident = row.get("availability_id", "unknown")
        if row.get("item_id") and row["item_id"] not in items: errors.append(f"availability:{ident}: dangling item")
        if row.get("event_id") and row["event_id"] not in events: errors.append(f"availability:{ident}: dangling event")
        for ref in row.get("source_ids", []):
            if ref not in sources: errors.append(f"availability:{ident}: dangling source={ref}")
    for row in read_jsonl(root / "knowledge/visual-references/manifest.jsonl"):
        if row.get("item_id") not in items: errors.append(f"visual:{row.get('visual_reference_id')}: dangling item")
        for ref in row.get("source_ids", []):
            if ref not in sources: errors.append(f"visual:{row.get('visual_reference_id')}: dangling source={ref}")
    normalized_rows = read_jsonl(root / "data/normalized/listings.jsonl")
    normalized_by_id = {row["listing_id"]: row for row in normalized_rows}
    listing_ids = set(normalized_by_id)
    profiles = read_jsonl(root / "data/normalized/account-profiles.jsonl")
    account_ids: set[str] = set()
    for row in profiles:
        account_id = row.get("account_id", "unknown")
        if account_id in account_ids: errors.append(f"profile: duplicate account_id={account_id}")
        account_ids.add(account_id)
        for ref in row.get("source_listing_ids", []):
            if ref not in listing_ids: errors.append(f"profile:{account_id}: dangling listing={ref}")
        for season_profile in row.get("season_profiles", []):
            if season_profile.get("season_id") not in seasons: errors.append(f"profile:{account_id}: dangling season={season_profile.get('season_id')}")
            for field in ("owned_item_ids", "missing_item_ids"):
                for ref in season_profile.get(field, []):
                    if ref not in items: errors.append(f"profile:{account_id}: dangling {field}={ref}")
        collection = row.get("collection", {})
        for ref in collection.get("owned_item_ids", []):
            if ref not in items: errors.append(f"profile:{account_id}: dangling owned item={ref}")
        for set_profile in collection.get("item_set_profiles", []):
            if set_profile.get("set_id") not in sets: errors.append(f"profile:{account_id}: dangling set={set_profile.get('set_id')}")
    histories = read_jsonl(root / "data/curated/histories.jsonl")
    history_ids: set[str] = set()
    for row in histories:
        history_id = row.get("history_id", "unknown")
        if history_id in history_ids: errors.append(f"history: duplicate history_id={history_id}")
        history_ids.add(history_id)
        if row.get("account_id") not in account_ids: errors.append(f"history:{history_id}: dangling account")
        for ref in row.get("source_listing_ids", []):
            if ref not in listing_ids: errors.append(f"history:{history_id}: dangling listing={ref}")
        if row.get("date_verified"):
            dated_sources = [normalized_by_id[ref] for ref in row.get("source_listing_ids", []) if normalized_by_id[ref].get("date_verified")]
            if not dated_sources:
                errors.append(f"history:{history_id}: verified date has no verified normalized source")
            elif not any(source.get("post_date") == row.get("post_date") for source in dated_sources):
                errors.append(f"history:{history_id}: post_date does not match a verified normalized source")
    comparable_histories = read_jsonl(root / "data/comparables/histories.jsonl")
    curated_by_id = {row["history_id"]: row for row in histories}
    if comparable_histories != histories:
        errors.append("comparables/histories differs from curated histories")
    comparable_accounts = read_jsonl(root / "data/comparables/accounts.jsonl")
    if len(comparable_accounts) != len(histories): errors.append("comparables/accounts count differs from curated histories")
    for row in comparable_accounts:
        if row.get("history_id") not in history_ids: errors.append(f"comparable:{row.get('comparable_id')}: dangling history")
        history = curated_by_id.get(row.get("history_id"))
        if history and (row.get("date_verified") != history.get("date_verified") or row.get("post_date") != history.get("post_date")):
            errors.append(f"comparable:{row.get('comparable_id')}: date differs from curated history")
    verified_normalized = [row for row in normalized_rows if row.get("date_verified")]
    verified_histories = [row for row in histories if row.get("date_verified")]
    if len(verified_normalized) != 28:
        errors.append(f"date coverage: expected 28 verified normalized dates, found {len(verified_normalized)}")
    if len(verified_histories) != 5:
        errors.append(f"date coverage: expected 5 verified history dates, found {len(verified_histories)}")
    # Coverage reports must be reproducible from formal data, never fixture rows.
    formal_counts = {
        "source_listings": len(read_jsonl(root / "data/source/listings.jsonl")),
        "normalized_listings": len(normalized_rows), "account_profiles": len(profiles),
        "curated_histories": len(histories), "comparable_histories": len(comparable_histories),
        "comparable_accounts": len(comparable_accounts), "seasons": len(seasons), "events": len(events),
        "items": len(items), "sets": len(sets), "aliases": len(read_jsonl(root / "knowledge/aliases/item-aliases.jsonl")),
        "availability_events": len(read_jsonl(root / "knowledge/acquisition/availability-events.jsonl")), "sources": len(sources),
        "visual_references": len(read_jsonl(root / "knowledge/visual-references/manifest.jsonl")),
    }
    coverage = json.loads((root / "reports/coverage/catalog-coverage.json").read_text(encoding="utf-8"))
    reported = coverage.get("counts", {})
    reported_market = coverage.get("market_migration", {})
    for key, actual in formal_counts.items():
        report_value = reported_market.get(key) if key in {"source_listings", "normalized_listings", "account_profiles", "curated_histories", "comparable_histories", "comparable_accounts"} else reported.get(key)
        if report_value != actual:
            errors.append(f"coverage count mismatch: {key} report={report_value!r} actual={actual}")
    expected_market = {"source_listings": 1022, "normalized_listings": 1022, "account_profiles": 1022, "curated_histories": 102, "comparable_histories": 102, "comparable_accounts": 102}
    for key, expected in expected_market.items():
        if formal_counts[key] != expected:
            errors.append(f"formal market coverage: expected {key}={expected}, found {formal_counts[key]}")
    # Date invariant at every market stage.
    for rel in ("data/source/listings.jsonl", "data/normalized/listings.jsonl", "data/normalized/account-profiles.jsonl", "data/curated/histories.jsonl", "data/comparables/histories.jsonl", "data/comparables/accounts.jsonl"):
        path = root / rel
        try:
            rows = read_jsonl(path)
        except (ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc)); continue
        for index, row in enumerate(rows, 1):
            if row.get("date_verified") is True and not row.get("post_date"):
                errors.append(f"{rel}:{index}: date_verified requires post_date")
            forbidden = PRIVATE_KEYS & set(row)
            if forbidden:
                errors.append(f"{rel}:{index}: prohibited privacy keys {sorted(forbidden)}")
            serialized = json.dumps(row, ensure_ascii=False)
            for label, pattern in PRIVATE_VALUE_PATTERNS.items():
                if pattern.search(serialized):
                    errors.append(f"{rel}:{index}: prohibited privacy value ({label})")
    evidence_path = root / "data/curated/image-evidence.jsonl"
    try:
        evidence = read_jsonl(evidence_path)
        for index, row in enumerate(evidence, 1):
            for issue in validate_evidence(row, ids["item"]):
                errors.append(f"image-evidence:{index}: {issue}")
    except (ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    # No retired execution capability may enter the new tools tree.
    forbidden_terms = re.compile(r"\b(backtest|calibrat(?:e|ion)?|market[_-]?drift|follow[_-]?up|scheduler|provider|crawler)\b", re.I)
    for path in (root / "tools").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        if name.name in {"requests", "socket", "http.client", "urllib.request"}:
                            errors.append(f"{path.relative_to(root)}:{node.lineno}: forbidden network import {name.name}")
                elif isinstance(node, ast.ImportFrom) and node.module in {"requests", "socket", "http.client", "urllib.request"}:
                    errors.append(f"{path.relative_to(root)}:{node.lineno}: forbidden network import {node.module}")
        except SyntaxError as exc:
            errors.append(f"{path.relative_to(root)}: Python syntax error: {exc}")
        if path.name in {"validate.py", "build_file_inventory.py"}:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if forbidden_terms.search(line):
                errors.append(f"{path.relative_to(root)}:{number}: forbidden execution capability")
    return {"schema_version": "3.0-p0", "offline_only": True, "valid": not errors, "errors": errors, "warnings": warnings,
            "schema_records_checked": schema_checked, "formal_jsonl_coverage": {rel: (root / rel).exists() for rel in sorted(REQUIRED_FORMAL_JSONL)},
            "date_flow": {"verified_normalized_dates": len(verified_normalized), "verified_history_dates": len(verified_histories), "expected_normalized_dates": 28, "expected_history_dates": 5},
            "formal_counts": formal_counts,
            "counts": {kind: len(value) for kind, value in ids.items()}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the offline P0 package")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = validate(args.root.resolve())
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
