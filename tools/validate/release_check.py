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
from canonical_evidence_registry import load_registry, validate_registry  # noqa: E402
from market_audit import audit_market_ledgers  # noqa: E402
from tools.normalize.build_historical_cost_references import build as build_historical_cost_references  # noqa: E402
from tools.modeling.publication_readiness import build as build_publication_readiness  # noqa: E402


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def write_utf8_lf(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def model_artifacts_release_valid(artifacts: list[dict[str, object]]) -> bool:
    """Fail closed until a publication evaluator can replay a trained artifact."""
    return bool(artifacts) and all(artifact.get("status") == "insufficient_training_data" for artifact in artifacts)


def item_value_rows_release_valid(rows: list[dict[str, object]], canonical_item_ids: set[str]) -> bool:
    """Fail closed until attribution provenance has a replayable evaluator."""
    if len(rows) != len({row.get("item_id") for row in rows}) or {row.get("item_id") for row in rows} != canonical_item_ids:
        return False
    for row in rows:
        status = row.get("status")
        mean, median = row.get("mean_conditional_attribution"), row.get("median_conditional_attribution")
        if status == "insufficient_support":
            if mean is not None or median is not None:
                return False
            continue
        # A schema-valid eligible row is not publication-valid merely because
        # its provenance fields contain strings.  No evaluator currently
        # replays the explanations, refits, and attribution sidecars.
        if status != "insufficient_support":
            return False
    return True


def human_review_ledgers_release_valid(
    market_claim_gold: list[dict[str, object]], near_miss_approved_evidence: list[dict[str, object]], market_audit_errors: list[str] | None = None,
) -> bool:
    """A nonempty ledger is legal only after replaying the injected trust root."""
    return (not market_claim_gold and not near_miss_approved_evidence) or (market_audit_errors == [])


def verify_fresh_lf_checkout(root: Path, source_zip: Path, authority_bundle: Path | None = None, authority_bundle_sha256: str | None = None) -> dict[str, object]:
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
        if authority_bundle is not None:
            command.extend(["--market-audit-authority-bundle", str(authority_bundle)])
        if authority_bundle_sha256 is not None:
            command.extend(["--market-audit-authority-bundle-sha256", authority_bundle_sha256])
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
    parser.add_argument("--market-audit-authority-bundle", type=Path, help="external authority-bundle JSON; required only for nonempty market review ledgers")
    parser.add_argument("--market-audit-authority-bundle-sha256", help="expected SHA-256 for the injected external authority bundle")
    args = parser.parse_args()
    root = args.root.resolve()
    integrity = validate(root, args.market_audit_authority_bundle, args.market_audit_authority_bundle_sha256)
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
    item_candidates = [json.loads(line) for line in (root / "data/review/item-candidates.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    item_promotions = [json.loads(line) for line in (root / "data/review/item-promotion-ledger.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    catalog_universe = [json.loads(line) for line in (root / "data/review/catalog-universe.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    market_claim_review = [json.loads(line) for line in (root / "data/review/market-claim-review.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    market_claim_gold = [json.loads(line) for line in (root / "data/review/market-claim-gold.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    market_near_miss_review = [json.loads(line) for line in (root / "data/review/market-near-miss-field-review.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    market_near_miss_evidence = [json.loads(line) for line in (root / "data/review/market-near-miss-approved-evidence.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    market_audit_errors = audit_market_ledgers(
        root, market_claim_review, market_claim_gold, market_near_miss_review, market_near_miss_evidence,
        args.market_audit_authority_bundle, args.market_audit_authority_bundle_sha256,
    )
    reference_identities = [json.loads(line) for line in (root / "data/normalized/source-scoped-item-identities.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    catalog_query_index = [json.loads(line) for line in (root / "data/normalized/catalog-query-index.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    catalog_query_summary = json.loads((root / "data/normalized/catalog-query-index-summary.json").read_text(encoding="utf-8"))
    account_catalog_resolution = [json.loads(line) for line in (root / "data/review/account-catalog-resolution.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    historical_cost_references = [json.loads(line) for line in (root / "data/derived/official-historical-cost-references.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    publication_readiness = json.loads((root / "reports/model-publication-readiness.json").read_text(encoding="utf-8"))
    vendor_item_evidence = [json.loads(line) for line in (root / "data/review/skygame-data-1.3.4-item-evidence.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    fandom_crosswalk = [json.loads(line) for line in (root / "data/review/fandom-seasonal-cosmetics-r107991-crosswalk.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    canonical_item_ids = {row["item_id"] for row in items}
    candidate_item_ids = {row["candidate_item_id"] for row in item_candidates}
    source_reference_ids = {row["reference_identity_id"] for row in reference_identities}
    query_ids_by_type = {
        entity_type: {row["query_entity_id"] for row in catalog_query_index if row.get("query_entity_type") == entity_type}
        for entity_type in ("canonical_item", "review_candidate", "source_reference")
    }
    verified_item_ids = {row["item_id"] for row in items if row.get("verification_status") == "verified"}
    resolved_query_ids = {row["query_entity_id"] for row in catalog_query_index if row.get("resolution_eligibility") == "canonical_resolved"}
    set_rows = [json.loads(line) for line in (root / "knowledge/sets/item-sets.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    source_rows = [json.loads(line) for line in (root / "knowledge/sources/sources.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    registry_problems, registry_ledgers = validate_registry(
        root, {row["item_id"]: row for row in items}, {row["set_id"]: row for row in set_rows}, {row["source_id"]: row for row in source_rows},
    )
    registry_rows = load_registry(root)
    release_cohorts = [row for row in registry_rows if row.get("release_required") is True]
    registry_counts = {cohort_id: len(ledger) for cohort_id, ledger in sorted(registry_ledgers.items())}
    checks = {
        "schema_and_integrity": integrity["valid"],
        "unit_tests": test_success,
        "manifest_hashes": not mismatches,
        "source_zip_unchanged": archive["unchanged"] is True,
        "required_directory_structure": required_top <= top_dirs and "staging" not in top_dirs,
        "no_cache_or_staging_residue": not residue and not any(path.is_dir() for path in root.rglob("staging")),
        "market_stage_counts_consistent": (
            migration["source_listings"] == coverage["market_migration"]["source_listings"]
            and migration["normalized_listings"] == coverage["market_migration"]["normalized_listings"]
            and len(vectors) == coverage["market_migration"]["account_profiles"]
            and coverage["market_migration"]["curated_histories"] == coverage["market_migration"]["comparable_histories"] == coverage["market_migration"]["comparable_accounts"]
            and coverage["modeling"]["clean_normal_rows"] == len(clean_normal)
            and coverage["modeling"]["clean_urgent_rows"] == len(clean_urgent)
        ),
        "migration_history_accounting_consistent": migration["migrated_histories"] + migration["not_migrated_histories"] == migration["legacy_histories"],
        "verified_sales_remain_zero": coverage["market_migration"]["verified_completed_sales"] == 0,
        "catalog_claim_is_partial": coverage["full_item_catalog_complete"] is False,
        "p2_vendor_evidence_consistent": (
            coverage.get("p2_evidence", {}).get("candidate_field_evidence_rows")
            == len(vendor_item_evidence)
            and coverage.get("p2_evidence", {}).get("canonical_promotions")
            == sum(row.get("canonical_write") not in {None, "not_performed"} for row in item_promotions)
        ),
        "p2_1_catalog_universe_reconciled": len(catalog_universe) == 3266 and coverage.get("p2_1_review_infrastructure", {}).get("catalog_universe_reconciled") is True,
        "p2_1_promotion_ledger_complete": len(item_promotions) == len(candidate_item_ids) and {row.get("candidate_item_id") for row in item_promotions} == candidate_item_ids and all(isinstance(row.get("decision"), str) and isinstance(row.get("canonical_write"), str) for row in item_promotions),
        "p2_1_human_gold_integrity": len({row.get("review_id") for row in market_claim_review}) == len(market_claim_review),
        "human_review_ledgers_externally_audited": human_review_ledgers_release_valid(market_claim_gold, market_near_miss_evidence, market_audit_errors),
        "p2_3_source_scoped_identities_fail_closed": len(reference_identities) == len(source_reference_ids) and all(row.get("link_status") in {"canonical_link", "candidate_link", "unresolved"} and row.get("identity_scope") == "source_snapshot_only" and row.get("canonical_identity_status") == "unverified" and row.get("promotion_eligibility") == "prohibited" and row.get("model_feature_status") == "excluded_pending_verification" for row in reference_identities),
        "p2_4_near_miss_evidence_integrity": len({row.get("review_id") for row in market_near_miss_review}) == len(market_near_miss_review),
        "p2_5_catalog_query_truth_layers": len(catalog_query_index) == len(canonical_item_ids) + len(candidate_item_ids) + len(source_reference_ids) and len({row.get("query_entity_id") for row in catalog_query_index}) == len(catalog_query_index) and query_ids_by_type["canonical_item"] == canonical_item_ids and query_ids_by_type["review_candidate"] == candidate_item_ids and query_ids_by_type["source_reference"] == source_reference_ids and resolved_query_ids == verified_item_ids and catalog_query_summary.get("canonical_item_count") == len(canonical_item_ids) and catalog_query_summary.get("review_candidate_count") == len(candidate_item_ids) and catalog_query_summary.get("source_reference_count") == len(source_reference_ids) and catalog_query_summary.get("query_row_count") == len(catalog_query_index),
        "p2_9_account_catalog_resolution_review_only": (
            len(account_catalog_resolution) == len(vectors)
            and len({row.get("account_id") for row in account_catalog_resolution}) == len(account_catalog_resolution)
            and all(row.get("review_only") is True and row.get("model_feature") is False and all(match.get("review_only") is True and match.get("model_feature") is False for match in row.get("matches", [])) for row in account_catalog_resolution)
            and coverage.get("p2_9_account_catalog_lexical_review", {}).get("account_rows") == len(account_catalog_resolution)
            and coverage.get("p2_9_account_catalog_lexical_review", {}).get("review_match_rows") == sum(len(row.get("matches", [])) for row in account_catalog_resolution)
            and coverage.get("p2_9_account_catalog_lexical_review", {}).get("ownership_or_model_promotions") == 0
        ),
        "canonical_evidence_registry_replayed": not registry_problems and bool(release_cohorts) and all(row.get("cohort_id") in registry_ledgers for row in release_cohorts),
        "canonical_evidence_registry_reported": coverage.get("p2_7_verified_identity_slice", {}).get("verified_cohorts") == registry_counts,
        "p2_4_catalog_scope_is_auditable": bool(catalog_universe) and all(row.get("scope_disposition") and row.get("disposition_reason") and row.get("evidence_basis") for row in catalog_universe),
        "p2_4_unknown_sets_not_model_features": all(all(set_row.get("model_feature") is False and set_row.get("completion_ratio") is None and set_row.get("is_complete") is None for set_row in vector.get("feature_groups", {}).get("item_sets", [])) for vector in vectors),
        "p2_2_fandom_same_lineage_only": len(fandom_crosswalk) == 700 and sum(row.get("match_status") == "season_mapped_candidate_linked" for row in fandom_crosswalk) == 579 and all(row.get("source_independence") == "not_independent_same_fandom_wiki" and row.get("promotion_effect") == "none" for row in fandom_crosswalk),
        "formal_models_publication_gated": model_artifacts_release_valid(model_artifacts),
        "item_values_provenance_gated": item_value_rows_release_valid(item_values, canonical_item_ids),
        "verified_identity_cohort_not_over_promoted_to_model": all(row.get("model_feature_status") != "eligible" or row.get("verification_status") == "verified" for row in items),
        "p3_official_historical_costs_replayable_and_non_valuative": (
            historical_cost_references == build_historical_cost_references(root)
            and {row.get("item_id") for row in historical_cost_references} == verified_item_ids
            and len(historical_cost_references) == len(verified_item_ids)
            and all(row.get("model_feature") is False and row.get("resale_value_effect") == "not_inferred" for row in historical_cost_references)
        ),
        "p3_publication_readiness_replayed_and_not_ready": (
            publication_readiness == build_publication_readiness(root)
            and publication_readiness.get("status") == "not_ready"
            and publication_readiness.get("artifact_publication_fields_consulted") is False
            and publication_readiness.get("trained_models_treated_as_passed") is False
        ),
    }
    fresh_checkout = None
    if args.verify_fresh_lf_checkout:
        fresh_checkout = verify_fresh_lf_checkout(root, source_zip, args.market_audit_authority_bundle, args.market_audit_authority_bundle_sha256)
        checks["fresh_lf_checkout"] = fresh_checkout["valid"] is True
    report = {
        "schema_version": "4.2-p3.0", "offline_only": True, "valid": all(checks.values()),
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
