#!/usr/bin/env python3
"""Run the final offline validation, tests, manifest audit, and source ZIP check."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
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
    # Run tests in a fresh interpreter. Importing the validator above adjusts
    # sys.path for its own local modules; sharing that interpreter with test
    # discovery can shadow the top-level `modeling` package and make release
    # results depend on import order.
    test_code = (
        "import io,json,unittest; "
        "suite=unittest.defaultTestLoader.discover('tests',pattern='test_*.py',top_level_dir='tests'); "
        "stream=io.StringIO(); result=unittest.TextTestRunner(stream=stream,verbosity=1).run(suite); "
        "print(json.dumps({'run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped)})); "
        "raise SystemExit(0 if result.wasSuccessful() else 1)"
    )
    test_env = dict(os.environ)
    test_env["PYTHONDONTWRITEBYTECODE"] = "1"
    test_child = subprocess.run(
        [sys.executable, "-c", test_code], cwd=root, env=test_env,
        text=True, capture_output=True, check=False,
    )
    try:
        test_summary = json.loads(test_child.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        test_summary = {"run": 0, "failures": 0, "errors": 1, "skipped": 0}
    test_success = test_child.returncode == 0 and test_summary["failures"] == test_summary["errors"] == 0

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
    required_top = {"docs", "schemas", "knowledge", "data", "tools", "modeling", "tests", "reports"}
    top_dirs = {path.name for path in root.iterdir() if path.is_dir() and path.name != "__pycache__"}
    residue = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.name == "__pycache__" or path.suffix == ".pyc"
    )
    vectors = [json.loads(line) for line in (root / "data/modeling/account-item-vectors.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    clean_normal = [json.loads(line) for line in (root / "data/modeling/price-cleaned-normal.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    clean_urgent = [json.loads(line) for line in (root / "data/modeling/price-cleaned-urgent.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    model_artifacts = [
        json.loads((root / f"modeling/artifacts/{name}").read_text(encoding="utf-8"))
        for name in (
            "elastic-net-normal_listing.json", "elastic-net-urgent_sale.json",
            "xgboost-normal_listing.json", "xgboost-urgent_sale.json",
        )
    ]
    item_values = [json.loads(line) for line in (root / "data/modeling/item-value-table.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    items = [json.loads(line) for line in (root / "knowledge/items/items.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    item_promotions = [json.loads(line) for line in (root / "data/review/item-promotion-ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    catalog_universe = [json.loads(line) for line in (root / "data/review/catalog-universe.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    market_claim_review = [json.loads(line) for line in (root / "data/review/market-claim-review.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    market_claim_gold = [json.loads(line) for line in (root / "data/review/market-claim-gold.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    market_near_miss_review = [json.loads(line) for line in (root / "data/review/market-near-miss-field-review.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    market_near_miss_evidence = [json.loads(line) for line in (root / "data/review/market-near-miss-approved-evidence.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    reference_identities = [json.loads(line) for line in (root / "data/normalized/source-scoped-item-identities.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    fandom_crosswalk = [json.loads(line) for line in (root / "data/review/fandom-seasonal-cosmetics-r107991-crosswalk.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    checks = {
        "schema_and_integrity": integrity["valid"],
        "unit_tests": test_success,
        "manifest_hashes": not mismatches,
        "source_zip_unchanged": archive["unchanged"] is True,
        "required_directory_structure": required_top <= top_dirs and "staging" not in top_dirs,
        "no_cache_or_staging_residue": not residue and not any(path.is_dir() for path in root.rglob("staging")),
        "migration_1022": migration["source_listings"] == migration["normalized_listings"] == 1022,
        "legacy_histories_102_plus_one_reviewed_recovery": migration["migrated_histories"] == 102 and migration["not_migrated_histories"] == 0 and coverage["market_migration"]["curated_histories"] == 103,
        "verified_sales_remain_zero": coverage["market_migration"]["verified_completed_sales"] == 0,
        "catalog_claim_is_partial": coverage["full_item_catalog_complete"] is False,
        "model_vectors_1022": len(vectors) == 1022,
        "strict_model_price_lines_3_and_0": len(clean_normal) == 3 and len(clean_urgent) == 0,
        "p2_vendor_evidence_fail_closed": coverage.get("p2_evidence", {}).get("candidate_field_evidence_rows") == 296 and coverage.get("p2_evidence", {}).get("canonical_promotions") == 0,
        "p2_1_catalog_universe_reconciled": len(catalog_universe) == 3266 and coverage.get("p2_1_review_infrastructure", {}).get("catalog_universe_reconciled") is True,
        "p2_1_vendor_correlation_fail_closed": len(item_promotions) == 622 and sum(row.get("decision") == "vendor_correlated_template_candidate" for row in item_promotions) == 284 and all(row.get("canonical_write") == "not_performed" and row.get("model_feature_status") == "excluded_pending_verification" and "canonical_identity" in row.get("unresolved_fields", []) for row in item_promotions if row.get("decision") == "vendor_correlated_template_candidate"),
        "p2_1_human_gold_not_fabricated": len(market_claim_review) == 200 and not market_claim_gold,
        "p2_3_source_scoped_identities_fail_closed": len(reference_identities) == 1758 and sum(row.get("link_status") == "canonical_link" for row in reference_identities) == 64 and sum(row.get("link_status") == "candidate_link" for row in reference_identities) == 296 and sum(row.get("link_status") == "unresolved" for row in reference_identities) == 1398 and all(row.get("identity_scope") == "source_snapshot_only" and row.get("canonical_identity_status") == "unverified" and row.get("promotion_eligibility") == "prohibited" and row.get("model_feature_status") == "excluded_pending_verification" for row in reference_identities),
        "p2_3_near_miss_evidence_not_fabricated": len(market_near_miss_review) == 22 and not market_near_miss_evidence,
        "p2_2_fandom_same_lineage_only": len(fandom_crosswalk) == 700 and sum(row.get("match_status") == "season_mapped_candidate_linked" for row in fandom_crosswalk) == 579 and all(row.get("source_independence") == "not_independent_same_fandom_wiki" and row.get("promotion_effect") == "none" for row in fandom_crosswalk),
        "formal_models_fail_closed": all(row.get("status") == "insufficient_training_data" for row in model_artifacts),
        "item_values_fail_closed": len(item_values) == len(items) == 94 and all(row.get("status") == "insufficient_support" and row.get("mean_conditional_attribution") is None for row in item_values),
        "no_model_eligible_items": not any(row.get("model_feature_status") == "eligible" for row in items),
    }
    fresh_checkout = None
    if args.verify_fresh_lf_checkout:
        fresh_checkout = verify_fresh_lf_checkout(root, source_zip)
        checks["fresh_lf_checkout"] = fresh_checkout["valid"] is True
    report = {
        "schema_version": "3.5-p2.3", "offline_only": True, "valid": all(checks.values()),
        "checks": checks, "schema_records_checked": integrity["schema_records_checked"],
        "schema_errors": integrity["errors"], "schema_warnings": integrity["warnings"],
        "unit_tests": test_summary,
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
