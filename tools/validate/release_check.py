#!/usr/bin/env python3
"""Run the final offline validation, tests, manifest audit, and source ZIP check."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "validate"))
from validate import validate  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()

    integrity = validate(root)
    suite = unittest.defaultTestLoader.discover(str(root / "tests"), pattern="test_*.py", top_level_dir=str(root / "tests"))
    stream = io.StringIO()
    test_result = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)

    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    mismatches = []
    for relative, expected in manifest.get("file_hashes", {}).items():
        path = root / relative
        if not path.is_file():
            mismatches.append({"path": relative, "reason": "missing"})
        elif sha256(path) != expected:
            mismatches.append({"path": relative, "reason": "sha256_mismatch"})

    declared_exclusions = set(manifest.get("hash_exclusions", []))
    expected_exclusions = {"manifest.json", "reports/validation/p0-validation.json"}
    if declared_exclusions != expected_exclusions:
        mismatches.append({"path": "manifest.json", "reason": "invalid_hash_exclusions"})
    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.parts and "__pycache__" not in path.parts and path.suffix != ".pyc" and "staging" not in path.parts
    }
    declared_files = set(manifest.get("file_hashes", {})) | declared_exclusions
    for relative in sorted(actual_files - declared_files):
        mismatches.append({"path": relative, "reason": "undeclared_release_file"})
    for relative in sorted(declared_files - actual_files):
        mismatches.append({"path": relative, "reason": "declared_but_missing"})

    archive = {"checked": True, "unchanged": False, "expected_sha256": manifest["source_archive"]["sha256"]}
    source_zip = args.source_zip.resolve()
    actual = sha256(source_zip)
    archive.update({"path_identity": source_zip.name, "actual_sha256": actual, "unchanged": actual == archive["expected_sha256"]})

    migration = json.loads((root / "reports/migration/migration-summary.json").read_text(encoding="utf-8"))
    coverage = json.loads((root / "reports/coverage/catalog-coverage.json").read_text(encoding="utf-8"))
    required_top = {"docs", "schemas", "knowledge", "data", "tools", "tests", "reports"}
    top_dirs = {path.name for path in root.iterdir() if path.is_dir() and path.name != "__pycache__"}
    checks = {
        "schema_and_integrity": integrity["valid"],
        "unit_tests": test_result.wasSuccessful(),
        "manifest_hashes": not mismatches,
        "source_zip_unchanged": archive["unchanged"] is True,
        "required_directory_structure": required_top <= top_dirs and "staging" not in top_dirs,
        "migration_1022": migration["source_listings"] == migration["normalized_listings"] == 1022,
        "histories_102": migration["migrated_histories"] == 102 and migration["not_migrated_histories"] == 0,
        "verified_sales_remain_zero": coverage["market_migration"]["verified_completed_sales"] == 0,
        "catalog_claim_is_partial": coverage["full_item_catalog_complete"] is False,
    }
    report = {
        "schema_version": "3.0-p0", "offline_only": True, "valid": all(checks.values()),
        "checks": checks, "schema_records_checked": integrity["schema_records_checked"],
        "schema_errors": integrity["errors"], "schema_warnings": integrity["warnings"],
        "unit_tests": {"run": test_result.testsRun, "failures": len(test_result.failures), "errors": len(test_result.errors), "skipped": len(test_result.skipped)},
        "manifest": {"hashed_files": len(manifest.get("file_hashes", {})), "mismatches": mismatches},
        "source_archive": archive,
        "migration": migration,
        "catalog_counts": coverage["counts"],
        "known_limitations": coverage["known_limitations"],
    }
    output = (args.output or root / "reports/validation/p0-validation.json").resolve()
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"valid": report["valid"], "tests": report["unit_tests"], "manifest_mismatches": len(mismatches), "source_zip_unchanged": archive["unchanged"]}, ensure_ascii=False))
    raise SystemExit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
