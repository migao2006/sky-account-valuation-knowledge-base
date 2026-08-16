#!/usr/bin/env python3
"""Run the final offline validation, tests, manifest audit, and source ZIP check."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "validate"))
from validate import validate  # noqa: E402
from release_files import HASH_EXCLUSIONS, lf_violations, release_files  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def write_utf8_lf(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def verify_fresh_lf_checkout(root: Path, source_zip: Path) -> dict[str, object]:
    """Validate a clean Git checkout, where .gitattributes supplies actual LF bytes."""
    status = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"], text=True, capture_output=True, check=False
    )
    if status.returncode:
        return {"checked": False, "valid": False, "reason": "git_status_failed"}
    if status.stdout.strip():
        return {"checked": False, "valid": False, "reason": "working_tree_not_clean"}
    with tempfile.TemporaryDirectory(prefix="sky-valuation-lf-") as temporary:
        checkout = Path(temporary) / "checkout"
        clone = subprocess.run(
            ["git", "clone", "--no-local", "--depth", "1", str(root), str(checkout)],
            text=True, capture_output=True, check=False,
        )
        if clone.returncode:
            return {"checked": True, "valid": False, "reason": "git_clone_failed"}
        command = [sys.executable, str(checkout / "tools/validate/release_check.py"), "--root", str(checkout), "--source-zip", str(source_zip)]
        child = subprocess.run(command, text=True, capture_output=True, check=False)
        output = child.stdout.strip().splitlines()
        return {
            "checked": True,
            "valid": child.returncode == 0,
            "commit": subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True, capture_output=True, check=False).stdout.strip(),
            "result": output[-1] if output else "",
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--source-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-fresh-lf-checkout", action="store_true", help="also validate an actual clean Git LF checkout")
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
    expected_exclusions = HASH_EXCLUSIONS
    if declared_exclusions != expected_exclusions:
        mismatches.append({"path": "manifest.json", "reason": "invalid_hash_exclusions"})
    actual_files = {path.relative_to(root).as_posix() for path in release_files(root)}
    declared_files = set(manifest.get("file_hashes", {})) | declared_exclusions
    for relative in sorted(actual_files - declared_files):
        mismatches.append({"path": relative, "reason": "undeclared_release_file"})
    for relative in sorted(declared_files - actual_files):
        mismatches.append({"path": relative, "reason": "declared_but_missing"})
    for relative in lf_violations(root):
        mismatches.append({"path": relative, "reason": "non_lf_text_file"})

    archive = {"checked": True, "unchanged": False, "expected_sha256": manifest["source_archive"]["sha256"]}
    source_zip = args.source_zip.resolve()
    actual = sha256(source_zip)
    archive.update({"path_identity": source_zip.name, "actual_sha256": actual, "unchanged": actual == archive["expected_sha256"]})

    migration = json.loads((root / "reports/migration/migration-summary.json").read_text(encoding="utf-8"))
    coverage = json.loads((root / "reports/coverage/catalog-coverage.json").read_text(encoding="utf-8"))
    required_top = {"docs", "schemas", "knowledge", "data", "tools", "tests", "reports"}
    top_dirs = {path.name for path in root.iterdir() if path.is_dir() and path.name != "__pycache__"}
    residue = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.name == "__pycache__" or path.suffix == ".pyc"
    )
    checks = {
        "schema_and_integrity": integrity["valid"],
        "unit_tests": test_result.wasSuccessful(),
        "manifest_hashes": not mismatches,
        "source_zip_unchanged": archive["unchanged"] is True,
        "required_directory_structure": required_top <= top_dirs and "staging" not in top_dirs,
        "no_cache_or_staging_residue": not residue and not any(path.is_dir() for path in root.rglob("staging")),
        "migration_1022": migration["source_listings"] == migration["normalized_listings"] == 1022,
        "histories_102": migration["migrated_histories"] == 102 and migration["not_migrated_histories"] == 0,
        "verified_sales_remain_zero": coverage["market_migration"]["verified_completed_sales"] == 0,
        "catalog_claim_is_partial": coverage["full_item_catalog_complete"] is False,
    }
    fresh_checkout = None
    if args.verify_fresh_lf_checkout:
        fresh_checkout = verify_fresh_lf_checkout(root, source_zip)
        checks["fresh_lf_checkout"] = fresh_checkout["valid"] is True
    report = {
        "schema_version": "3.0-p0", "offline_only": True, "valid": all(checks.values()),
        "checks": checks, "schema_records_checked": integrity["schema_records_checked"],
        "schema_errors": integrity["errors"], "schema_warnings": integrity["warnings"],
        "unit_tests": {"run": test_result.testsRun, "failures": len(test_result.failures), "errors": len(test_result.errors), "skipped": len(test_result.skipped)},
        "manifest": {"hashed_files": len(manifest.get("file_hashes", {})), "mismatches": mismatches},
        "release_residue": residue,
        "source_archive": archive,
        "migration": migration,
        "catalog_counts": coverage["counts"],
        "known_limitations": coverage["known_limitations"],
    }
    if fresh_checkout is not None:
        report["fresh_lf_checkout"] = fresh_checkout
    default_output = (root / "reports/validation/p0-validation.json").resolve()
    output = (args.output or default_output).resolve()
    if output != default_output and root in output.parents:
        raise SystemExit("custom release-check output must be outside the release root")
    write_utf8_lf(output, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"valid": report["valid"], "tests": report["unit_tests"], "manifest_mismatches": len(mismatches), "source_zip_unchanged": archive["unchanged"]}, ensure_ascii=False))
    raise SystemExit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
