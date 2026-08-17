#!/usr/bin/env python3
"""Build factual P0 coverage/migration/quality reports and refresh manifest hashes."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "validate"))

from release_files import HASH_EXCLUSIONS, release_files
from canonical_evidence_registry import load_registry, validate_registry
from market_audit import audit_market_ledgers
from tools.market_authorization import verify_authorized_market_intake
from tools.modeling.clean_prices import clean_authorized_with_verified_sales as clean_model_prices
from tools.modeling.publication_dataset import build as build_publication_dataset
from tools.modeling.publication_evaluator import build as build_publication_evaluation
from tools.modeling.parser_knowledge_coverage import build as build_parser_knowledge_coverage
from tools.modeling.parser_gold_evaluator import audit_gold as audit_parser_gold, build as build_parser_gold_evaluation
from tools.modeling.market_gold_evaluator import build as build_market_gold_evaluation
from tools.modeling.visual_evidence_coverage import build as build_visual_evidence_coverage
from tools.validate.catalog_completion import build as build_catalog_completion
from tools.validate.build_completion_status import build as build_completion_status

BUILT_AT = "2026-08-17T00:00:00+08:00"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def count(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    values = collections.Counter(str(row.get(key, "unknown")) for row in rows)
    return dict(sorted(values.items()))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def write_utf8_lf(path: Path, content: str) -> None:
    """Avoid Windows text-mode conversion so manifest bytes are platform-stable."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def derived_model_status(artifacts: list[dict[str, Any]], publication_evaluation: dict[str, Any] | None = None) -> str:
    """Describe the published model state without trusting self-attested publication fields."""
    if artifacts and all(artifact.get("status") == "insufficient_training_data" for artifact in artifacts):
        return "insufficient_training_data"
    trained = [artifact for artifact in artifacts if artifact.get("status") == "trained"]
    canonical = {("elastic_net", "normal_listing"), ("elastic_net", "urgent_sale"), ("xgboost", "normal_listing"), ("xgboost", "urgent_sale")}
    tuples = [(artifact.get("model_type"), artifact.get("price_line")) for artifact in artifacts]
    bindings = publication_evaluation.get("artifact_bindings") if isinstance(publication_evaluation, dict) else None
    exact_normal_binding = isinstance(bindings, list) and len(bindings) == 1 and isinstance(bindings[0], dict) and (bindings[0].get("model_type"), bindings[0].get("price_line")) == ("elastic_net", "normal_listing")
    if len(trained) == 1 and len(artifacts) == 4 and len(set(tuples)) == 4 and set(tuples) == canonical and len(trained) + sum(artifact.get("status") == "insufficient_training_data" for artifact in artifacts) == len(artifacts) and (trained[0].get("model_type"), trained[0].get("price_line")) == ("elastic_net", "normal_listing") and isinstance(publication_evaluation, dict) and publication_evaluation.get("status") == "passed" and publication_evaluation.get("publication_ready") is True and exact_normal_binding:
        return "published_runtime_elastic_net_normal_listing"
    return "publication_evaluator_required"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--market-audit-authority-bundle", type=Path, help="external authority-bundle JSON; required only for nonempty market review ledgers")
    parser.add_argument("--market-audit-authority-bundle-sha256", help="expected SHA-256 for the injected external authority bundle")
    parser.add_argument("--market-authorization-authority-bundle", type=Path)
    parser.add_argument("--market-authorization-authority-bundle-sha256")
    parser.add_argument("--market-authorization-statement", type=Path)
    parser.add_argument("--market-authorization-statement-sha256")
    parser.add_argument("--market-identity-authority-bundle", type=Path)
    parser.add_argument("--market-identity-authority-bundle-sha256")
    parser.add_argument("--market-identity-mapping", type=Path)
    parser.add_argument("--market-identity-mapping-sha256")
    parser.add_argument("--market-identity-statement", type=Path)
    parser.add_argument("--market-identity-statement-sha256")
    parser.add_argument("--market-receipt-archive", type=Path)
    parser.add_argument("--market-receipt-archive-sha256")
    parser.add_argument("--market-receipt-authority-bundle", type=Path)
    parser.add_argument("--market-receipt-authority-bundle-sha256")
    parser.add_argument("--parser-gold-authority-bundle", type=Path)
    parser.add_argument("--parser-gold-authority-bundle-sha256")
    parser.add_argument("--parser-gold-replay-inputs", type=Path)
    parser.add_argument("--parser-gold-replay-inputs-sha256")
    parser.add_argument("--parser-keyed-custodian-authority-bundle", type=Path)
    parser.add_argument("--parser-keyed-custodian-authority-bundle-sha256")
    parser.add_argument("--parser-keyed-custodian-contract", type=Path)
    parser.add_argument("--parser-keyed-custodian-contract-sha256")
    parser.add_argument("--parser-keyed-replay-binding", type=Path)
    parser.add_argument("--parser-keyed-replay-binding-sha256")
    parser.add_argument("--canonical-review-authority-bundle", type=Path)
    parser.add_argument("--canonical-review-authority-bundle-sha256")
    args = parser.parse_args()
    root = args.root.resolve()

    paths = {
        "seasons": root / "knowledge/seasons/seasons.jsonl",
        "events": root / "knowledge/events/events.jsonl",
        "ancestors": root / "knowledge/seasons/ancestors.jsonl",
        "items": root / "knowledge/items/items.jsonl",
        "sets": root / "knowledge/sets/item-sets.jsonl",
        "aliases": root / "knowledge/aliases/item-aliases.jsonl",
        "availability_events": root / "knowledge/acquisition/availability-events.jsonl",
        "sources": root / "knowledge/sources/sources.jsonl",
        "visual_references": root / "knowledge/visual-references/manifest.jsonl",
        "source_listings": root / "data/source/listings.jsonl",
        "normalized_listings": root / "data/normalized/listings.jsonl",
        "account_profiles": root / "data/normalized/account-profiles.jsonl",
        "curated_histories": root / "data/curated/histories.jsonl",
        "comparable_histories": root / "data/comparables/histories.jsonl",
        "comparable_accounts": root / "data/comparables/accounts.jsonl",
        "image_evidence": root / "data/curated/image-evidence.jsonl",
        "unresolved": root / "reports/coverage/unresolved-items.jsonl",
        "unmapped": root / "reports/coverage/unmapped-aliases.jsonl",
        "item_candidates": root / "data/review/item-candidates.jsonl",
        "alias_conflicts": root / "data/review/alias-conflicts.jsonl",
        "item_vectors": root / "data/modeling/account-item-vectors.jsonl",
        "clean_normal": root / "data/modeling/price-cleaned-normal.jsonl",
        "clean_urgent": root / "data/modeling/price-cleaned-urgent.jsonl",
        "clean_verified_sales": root / "data/modeling/price-cleaned-verified-sales.jsonl",
        "model_exclusions": root / "data/modeling/model-exclusions.jsonl",
        "item_value_table": root / "data/modeling/item-value-table.jsonl",
        "vendor_crosswalk": root / "data/review/skygame-data-1.3.4-crosswalk.jsonl",
        "vendor_item_evidence": root / "data/review/skygame-data-1.3.4-item-evidence.jsonl",
        "strict_recovery_reviews": root / "data/review/strict-listing-recovery.jsonl",
        "catalog_universe": root / "data/review/catalog-universe.jsonl",
        "item_identity_evidence": root / "data/review/item-evidence.jsonl",
        "item_promotion_ledger": root / "data/review/item-promotion-ledger.jsonl",
        "canonical_evidence_registry": root / "data/review/canonical-evidence-cohorts.jsonl",
        "market_claim_review": root / "data/review/market-claim-review.jsonl",
        "market_claim_gold": root / "data/review/market-claim-gold.jsonl",
        "market_near_miss_review": root / "data/review/market-near-miss-field-review.jsonl",
        "market_near_miss_evidence": root / "data/review/market-near-miss-approved-evidence.jsonl",
        "market_audit_attestations": root / "data/review/market-audit/attestations.jsonl",
        "fandom_crosswalk": root / "data/review/fandom-seasonal-cosmetics-r107991-crosswalk.jsonl",
        "source_scoped_item_identities": root / "data/normalized/source-scoped-item-identities.jsonl",
        "catalog_query_index": root / "data/normalized/catalog-query-index.jsonl",
        "account_catalog_resolution": root / "data/review/account-catalog-resolution.jsonl",
        "historical_cost_references": root / "data/derived/official-historical-cost-references.jsonl",
        "authorized_market_registry": root / "data/review/market-authorization/registry.jsonl",
        "authorized_market_attestations": root / "data/review/market-authorization/attestations.jsonl",
    }
    migration_aliases = read_jsonl(root / "data/review/unmapped-season-aliases.jsonl") + read_jsonl(root / "data/review/unmapped-item-aliases.jsonl")
    unmapped_rows = [
        {
            "review_id": f"unmapped_{index:04d}", "term": row.get("term"),
            "kind": row.get("kind", "unknown"), "occurrences": row.get("count"),
            "status": "needs_review",
        }
        for index, row in enumerate(migration_aliases, 1)
    ]
    write_utf8_lf(paths["unmapped"], "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in unmapped_rows))
    rows = {name: read_jsonl(path) for name, path in paths.items()}
    market_audit_errors = audit_market_ledgers(
        root, rows["market_claim_review"], rows["market_claim_gold"], rows["market_near_miss_review"], rows["market_near_miss_evidence"],
        args.market_audit_authority_bundle, args.market_audit_authority_bundle_sha256,
    )
    if market_audit_errors:
        raise RuntimeError(f"market audit contract is invalid: {market_audit_errors}")
    parser_gold_errors = audit_parser_gold(root, read_jsonl(root / "data/review/parser-gold/claims.jsonl"), args.parser_gold_authority_bundle, args.parser_gold_authority_bundle_sha256, args.parser_keyed_custodian_authority_bundle, args.parser_keyed_custodian_authority_bundle_sha256, args.parser_keyed_custodian_contract, args.parser_keyed_custodian_contract_sha256, args.parser_keyed_replay_binding, args.parser_keyed_replay_binding_sha256)
    if parser_gold_errors:
        raise RuntimeError(f"parser-gold contract is invalid: {parser_gold_errors}")
    authorization_errors = verify_authorized_market_intake(
        root, args.market_authorization_authority_bundle,
        args.market_authorization_authority_bundle_sha256,
        args.market_authorization_statement, args.market_authorization_statement_sha256,
    )
    if authorization_errors:
        raise RuntimeError(f"authorized market intake is invalid: {authorization_errors}")
    expected_normal, expected_urgent, expected_verified_sales, expected_exclusions = clean_model_prices(
        rows["comparable_accounts"], root,
        args.market_authorization_authority_bundle, args.market_authorization_authority_bundle_sha256,
        args.market_authorization_statement, args.market_authorization_statement_sha256,
        args.market_identity_authority_bundle, args.market_identity_authority_bundle_sha256,
        args.market_identity_mapping, args.market_identity_mapping_sha256,
        args.market_identity_statement, args.market_identity_statement_sha256,
        args.market_receipt_archive, args.market_receipt_archive_sha256,
        args.market_receipt_authority_bundle, args.market_receipt_authority_bundle_sha256,
    )
    if rows["clean_normal"] != expected_normal or rows["clean_urgent"] != expected_urgent or rows["clean_verified_sales"] != expected_verified_sales or rows["model_exclusions"] != expected_exclusions:
        raise RuntimeError("formal clean prices differ from deterministic feature-lineage-gated rebuild")
    publication_dataset, publication_split = build_publication_dataset(root)
    publication_evaluation = build_publication_evaluation(root)
    parser_coverage = build_parser_knowledge_coverage(root)
    parser_gold_evaluation = build_parser_gold_evaluation(root, args.parser_gold_replay_inputs, args.parser_gold_replay_inputs_sha256, args.parser_gold_authority_bundle, args.parser_gold_authority_bundle_sha256, args.parser_keyed_custodian_authority_bundle, args.parser_keyed_custodian_authority_bundle_sha256, args.parser_keyed_custodian_contract, args.parser_keyed_custodian_contract_sha256, args.parser_keyed_replay_binding, args.parser_keyed_replay_binding_sha256)
    market_gold_evaluation = build_market_gold_evaluation(
        root, args.market_audit_authority_bundle, args.market_audit_authority_bundle_sha256,
    )
    catalog_completion = build_catalog_completion(root, args.canonical_review_authority_bundle, args.canonical_review_authority_bundle_sha256)
    visual_evidence_coverage = build_visual_evidence_coverage(root)
    for relative, expected in (
        ("reports/model-publication-dataset-manifest.json", publication_dataset),
        ("reports/model-publication-split.json", publication_split),
        ("reports/model-publication-evaluation.json", publication_evaluation),
        ("reports/parser-knowledge-coverage.json", parser_coverage),
        ("reports/parser-gold-evaluation.json", parser_gold_evaluation),
        ("reports/market-gold-evaluation.json", market_gold_evaluation),
        ("reports/catalog-completion.json", catalog_completion),
        ("reports/coverage/visual-evidence-capability.json", visual_evidence_coverage),
    ):
        actual = json.loads((root / relative).read_text(encoding="utf-8"))
        if actual != expected:
            raise RuntimeError(f"{relative} differs from deterministic rebuild")
    cohorts = load_registry(root)
    registry_problems, cohort_evidence = validate_registry(
        root,
        {row["item_id"]: row for row in rows["items"]},
        {row["set_id"]: row for row in rows["sets"]},
        {row["source_id"]: row for row in rows["sources"]},
        args.canonical_review_authority_bundle, args.canonical_review_authority_bundle_sha256,
    )
    if registry_problems:
        raise RuntimeError(f"canonical evidence registry is invalid: {registry_problems}")
    active_cohorts = [row for row in cohorts if row.get("cohort_id") in cohort_evidence]
    model_artifacts = [
        json.loads((root / "modeling/artifacts" / name).read_text(encoding="utf-8"))
        for name in (
            "elastic-net-normal_listing.json", "elastic-net-urgent_sale.json",
            "xgboost-normal_listing.json", "xgboost-urgent_sale.json",
        )
    ]
    canonical_promotions = sum(
        row.get("canonical_write") not in {None, "not_performed"}
        for row in rows["item_promotion_ledger"]
    )
    migration = json.loads((root / "reports/migration/migration-summary.json").read_text(encoding="utf-8"))
    inventory = json.loads((root / "reports/migration/file-inventory.json").read_text(encoding="utf-8"))

    verified_sales = len(rows["clean_verified_sales"])
    source_type_counts = count(rows["sources"], "source_type")
    official_types = {"official_site", "official_news", "official_support", "thatgamecompany"}
    canonical_entities = ("seasons", "events", "items", "sets", "aliases", "availability_events")
    canonical_needs_review = {
        name: sum(row.get("verification_status") == "needs_review" for row in rows[name])
        for name in canonical_entities
    }
    coverage = {
        "schema_version": "5.3-p4.1",
        "as_of_date": "2026-08-17",
        "catalog_claim": "complete_verified_catalog" if catalog_completion["complete"] else "partial_verified_catalog",
        "full_item_catalog_complete": catalog_completion["complete"],
        "counts": {name: len(rows[name]) for name in (
            "seasons", "events", "ancestors", "items", "sets", "aliases",
            "availability_events", "sources", "visual_references", "unresolved", "unmapped", "item_candidates", "alias_conflicts"
        )},
        "review_state": {
            "canonical_needs_review_by_entity": canonical_needs_review,
            "canonical_needs_review_total": sum(canonical_needs_review.values()),
            "unresolved_queue_records": len(rows["unresolved"]),
            "item_candidate_records": len(rows["item_candidates"]),
            "alias_conflict_records": len(rows["alias_conflicts"]),
            "unmapped_terms": len(rows["unmapped"]),
            "overlap_note": "各欄分開計數，可能描述同一知識缺口，不直接相加為唯一項目數。",
        },
        "item_coverage": {
            "by_category": count(rows["items"], "item_category"),
            "by_source_type": count(rows["items"], "source_type"),
            "by_verification_status": count(rows["items"], "verification_status"),
            "by_evidence_tier": count(rows["items"], "evidence_tier"),
            "by_model_feature_status": count(rows["items"], "model_feature_status"),
            "model_eligible_items": sum(row.get("model_feature_status") == "eligible" for row in rows["items"]),
            "by_availability_status": count(rows["items"], "availability_status"),
            "with_visual_reference": sum(bool(row.get("visual_reference_ids")) for row in rows["items"]),
            "with_canonical_zh_tw_name_confirmed": sum(
                row.get("verification_status") == "verified"
                and bool(row.get("canonical_name_zh_tw"))
                and not str(row.get("canonical_name_zh_tw")).startswith("待確認（")
                for row in rows["items"]
            ),
        },
        "season_coverage": {
            "total": len(rows["seasons"]),
            "with_one_or_more_items": sum(
                any(item.get("season_id") == season["season_id"] for item in rows["items"])
                for season in rows["seasons"]
            ),
            "without_items": [
                season["season_id"] for season in rows["seasons"]
                if not any(item.get("season_id") == season["season_id"] for item in rows["items"])
            ],
        },
        "source_coverage": {
            "by_type": source_type_counts,
            "official_source_records": sum(value for key, value in source_type_counts.items() if key in official_types),
            "community_or_other_source_records": sum(value for key, value in source_type_counts.items() if key not in official_types),
        },
        "market_migration": {
            "source_listings": len(rows["source_listings"]),
            "normalized_listings": len(rows["normalized_listings"]),
            "account_profiles": len(rows["account_profiles"]),
            "curated_histories": len(rows["curated_histories"]),
            "comparable_histories": len(rows["comparable_histories"]),
            "comparable_accounts": len(rows["comparable_accounts"]),
            "unmigrated_histories": migration["not_migrated_histories"],
            "verified_normalized_dates": migration["verified_dates_in_normalized"],
            "verified_history_dates_repaired": migration["verified_dates_repaired_in_histories"],
            "verified_completed_sales": verified_sales,
            "image_evidence_records": len(rows["image_evidence"]),
            "profiles_with_mapped_items": sum(bool(row.get("collection", {}).get("owned_item_ids")) for row in rows["account_profiles"]),
            "profiles_with_set_claims": sum(bool(row.get("collection", {}).get("item_set_profiles")) for row in rows["account_profiles"]),
        },
        "modeling": {
            "account_item_vectors": len(rows["item_vectors"]),
            "canonical_items_per_vector": len(rows["items"]),
            "model_eligible_items": sum(row.get("model_feature_status") == "eligible" for row in rows["items"]),
            "clean_normal_rows": len(rows["clean_normal"]),
            "clean_urgent_rows": len(rows["clean_urgent"]),
            "clean_verified_sale_rows": len(rows["clean_verified_sales"]),
            "excluded_or_review_rows": len(rows["model_exclusions"]),
            "item_value_rows": len(rows["item_value_table"]),
            "eligible_item_value_rows": sum(row.get("status") == "eligible" for row in rows["item_value_table"]),
            "model_status": derived_model_status(model_artifacts, publication_evaluation),
        },
        "p2_evidence": {
            "vendor_snapshot_items": 3266,
            "vendor_crosswalk_rows": len(rows["vendor_crosswalk"]),
            "canonical_exact_name_matches": sum(row.get("match_status") == "matched_canonical_name" for row in rows["vendor_crosswalk"]),
            "candidate_exact_name_matches": sum(row.get("match_status") == "matched_candidate_name" for row in rows["vendor_crosswalk"]),
            "candidate_field_evidence_rows": len(rows["vendor_item_evidence"]),
            "approved_strict_listing_recoveries": sum(row.get("review_status") == "approved" for row in rows["strict_recovery_reviews"]),
            "canonical_promotions": canonical_promotions,
        },
        "p2_1_review_infrastructure": {
            "catalog_universe_rows": len(rows["catalog_universe"]),
            "catalog_universe_reconciled": len(rows["catalog_universe"]) == 3266,
            "identity_evidence_rows": len(rows["item_identity_evidence"]),
            "vendor_correlated_template_candidates": sum(row.get("decision") == "vendor_correlated_template_candidate" for row in rows["item_promotion_ledger"]),
            "identity_rejected_fail_closed": sum(row.get("decision") == "rejected_fail_closed" for row in rows["item_promotion_ledger"]),
            "canonical_writes": sum(row.get("canonical_write") != "not_performed" for row in rows["item_promotion_ledger"]),
            "market_claim_review_queue": len(rows["market_claim_review"]),
            "human_gold_rows": len(rows["market_claim_gold"]),
        },
        "p2_2_evidence": {
            "fandom_template_records": len(rows["fandom_crosswalk"]),
            "fandom_candidate_links": sum(row.get("match_status") == "season_mapped_candidate_linked" for row in rows["fandom_crosswalk"]),
            "fandom_independent_evidence": sum(row.get("source_independence") != "not_independent_same_fandom_wiki" for row in rows["fandom_crosswalk"]),
            "market_claim_review_queue": len(rows["market_claim_review"]),
            "human_gold_rows": len(rows["market_claim_gold"]),
        },
        "p2_3_reference_identities": {
            "source_scoped_identity_rows": len(rows["source_scoped_item_identities"]),
            "canonical_relation_rows": sum(row.get("link_status") == "canonical_link" for row in rows["source_scoped_item_identities"]),
            "candidate_relation_rows": sum(row.get("link_status") == "candidate_link" for row in rows["source_scoped_item_identities"]),
            "unresolved_rows": sum(row.get("link_status") == "unresolved" for row in rows["source_scoped_item_identities"]),
            "quarantined_rows": sum(row.get("review_status") == "quarantined_cross_type_conflict" for row in rows["source_scoped_item_identities"]),
            "model_eligible_rows": sum(row.get("model_feature_status") == "eligible" for row in rows["source_scoped_item_identities"]),
            "market_near_miss_review_rows": len(rows["market_near_miss_review"]),
            "market_near_miss_approved_evidence_rows": len(rows["market_near_miss_evidence"]),
            "market_audit_attestation_rows": len(rows["market_audit_attestations"]),
        },
        "p2_4_catalog_resolution": {
            "query_index_rows": len(rows["catalog_query_index"]),
            "canonical_rows": sum(row.get("query_entity_type") == "canonical_item" for row in rows["catalog_query_index"]),
            "candidate_rows": sum(row.get("query_entity_type") == "review_candidate" for row in rows["catalog_query_index"]),
            "source_reference_rows": sum(row.get("query_entity_type") == "source_reference" for row in rows["catalog_query_index"]),
            "canonical_resolved_eligible_rows": sum(row.get("resolution_eligibility") == "canonical_resolved" for row in rows["catalog_query_index"]),
            "catalog_scope_needs_review_rows": sum(row.get("review_status") != "approved" for row in rows["catalog_universe"]),
        },
        "p2_5_verified_identity_slice": {
            "verified_canonical_items": sum(row.get("verification_status") == "verified" for row in rows["items"]),
            "field_evidence_rows": sum(len(evidence) for evidence in cohort_evidence.values()),
            "visual_source_descriptions": sum(row.get("reference_mode") == "source_description" for row in rows["visual_references"]),
            "model_eligible_items": sum(row.get("model_feature_status") == "eligible" for row in rows["items"]),
        },
        "p2_7_verified_identity_slice": {
            "verified_canonical_items": sum(row.get("verification_status") == "verified" for row in rows["items"]),
            "verified_cohorts": {cohort_id: len(evidence) for cohort_id, evidence in sorted(cohort_evidence.items())},
            "field_evidence_rows": sum(len(evidence) for evidence in cohort_evidence.values()),
            "model_eligible_items": sum(row.get("model_feature_status") == "eligible" for row in rows["items"]),
        },
        "p2_9_account_catalog_lexical_review": {
            "account_rows": len(rows["account_catalog_resolution"]),
            "eligible_account_rows": sum(row.get("matching_eligibility") == "eligible" for row in rows["account_catalog_resolution"]),
            "suppressed_account_rows": sum(row.get("matching_eligibility") != "eligible" for row in rows["account_catalog_resolution"]),
            "accounts_with_review_matches": sum(bool(row.get("matches")) for row in rows["account_catalog_resolution"]),
            "review_match_rows": sum(len(row.get("matches", [])) for row in rows["account_catalog_resolution"]),
            "ownership_or_model_promotions": sum(
                (not row.get("review_only") or row.get("model_feature") is not False)
                + sum((not match.get("review_only") or match.get("model_feature") is not False) for match in row.get("matches", []))
                for row in rows["account_catalog_resolution"]
            ),
        },
        "p3_0_authorized_evidence_and_cost_reference": {
            "authorized_clean_normal_rows": len(rows["clean_normal"]),
            "authorized_clean_urgent_rows": len(rows["clean_urgent"]),
            "authorized_clean_verified_sale_rows": len(rows["clean_verified_sales"]),
            "historical_cost_reference_rows": len(rows["historical_cost_references"]),
            "historical_cost_model_features": sum(row.get("model_feature") is True for row in rows["historical_cost_references"]),
            "resale_value_inferences": sum(row.get("resale_value_effect") != "not_inferred" for row in rows["historical_cost_references"]),
        },
        "p3_1_authorized_intake_and_publication_dataset": {
            "authorized_dataset_records": len(rows["authorized_market_registry"]),
            "authorization_attestation_rows": len(rows["authorized_market_attestations"]),
            "frozen_publication_rows": publication_dataset["dataset_row_count"],
            "publication_market_pools": len(publication_dataset["market_pools"]),
            "publication_split_requirements_met": any(pool.get("requirements_met") is True for pool in publication_split["market_pools"]),
            "parser_verified_observation_token_items": parser_coverage["summary"]["verified_alias_item_count"],
            "parser_known_states": parser_coverage["summary"]["known_state_count"],
            "parser_review_only_claims": parser_coverage["summary"]["review_only_positive_count"] + parser_coverage["summary"]["review_only_negative_count"] + parser_coverage["summary"]["review_only_conflict_count"],
        },
        "p3_4_completion_evidence": {
            "catalog_status": catalog_completion["catalog_status"],
            "catalog_blocking_contracts": len(catalog_completion["blocking_contract_ids"]),
            "market_gold_status": market_gold_evaluation["status"],
            "market_gold_rows": market_gold_evaluation["gold_row_count"],
            "parser_review_queue_status": json.loads((root / "data/review/parser-gold/review-queue-manifest.json").read_text(encoding="utf-8"))["status"],
            "visual_actual_assets": visual_evidence_coverage["counts"]["all"]["actual_content_addressed_assets"],
            "visual_approved_detections": visual_evidence_coverage["counts"]["all"]["approved_detections"],
            "visual_source_descriptions": visual_evidence_coverage["counts"]["all"]["source_description_only_refs"],
        },
        "known_limitations": [
            "全物品主檔尚未完成；未確認類別保留在 unresolved-items.jsonl，未逐項查證的列印頁候選隔離於 data/review/item-candidates.jsonl，不參與 canonical 辨識或估價。",
            "P3.5 新增 Days of Fortune FAQ 1264 core-five 的受限官方 identity 與歷史取得成本證據；所有 cohort 未證實的正式繁中名稱、目前供應、永久性、視覺身份與模型辨識仍維持 unknown／excluded。",
            "真實圖片資產與核准 detection 目前為零；10 筆 visual reference 只是來源文字描述，不宣稱具備圖示辨識準確率。",
            "可驗證成交價與獲外部授權的市場訓練列均為零；正式估價器維持 fail closed，不輸出轉售價格。",
            "P3.5 將供應者自證的 account／dedup cluster 視為未確認獨立性；在外部簽署 identity→cluster mapping 完成前，即使 price、feature 與 catalog provenance 的 bytes 綁定通過，也不會進入訓練。verified-sale 仍因沒有可重播成交證據 archive 而 fail closed。",
            "部分季節節點的免費／季卡、成本及正式繁中名稱仍需逐頁查證。",
            "Vendored 社群資料只提供二級交叉證據；296 個候選名稱命中仍需獨立審核，沒有自動升級 canonical item。",
            "P2.1 封閉對帳 3,266 筆 vendor 宇宙；284 個候選只有單一獨立 vendor 對未驗證 template seed 的 correlation，canonical identity 與 season／取得／availability／成本／visual reference 仍未確認，且沒有 canonical write 或模型白名單提升。",
            "P2.3 將 1,758 筆 vendor collectible observations 正式化為唯一 source-scoped identity 層；它不是 1,758 個 canonical items，所有 promotion 均禁止、模型白名單提升為 0。",
            "固定 Fandom revision 只有同一 Wiki lineage 的可重播 template coordinate，不能算第二獨立來源或升級 canonical identity。",
            "市場 claim 人工金標仍為 0；200 筆固定匿名 review queue 尚待兩位獨立人類標註與人工裁決。",
            f"P3.1 保留 {len(rows['market_near_miss_review'])} 筆匿名 near-miss；只有外部信任根驗證的三方 OpenSSH attestations 才可接受非空人工 ledger，且不會自動取得市場訓練授權。",
            f"P3.1 的 {len(rows['catalog_query_index'])} 筆離線 Catalog 查詢索引仍嚴格區分 canonical、候選與來源觀測；verified canonical resolution 為 {sum(row.get('resolution_eligibility') == 'canonical_resolved' for row in rows['catalog_query_index'])}，model eligible 仍為 {sum(row.get('model_feature_status') == 'eligible' for row in rows['items'])}。",
            f"P3.1 保留帳號 lexical catalog sidecar 供人工複核：{len(rows['account_catalog_resolution'])} 個帳號中有 {sum(bool(row.get('matches')) for row in rows['account_catalog_resolution'])} 個出現保守詞彙命中；不會輸出 ownership 或 model feature。",
            f"P3.1 的 {len(rows['historical_cost_references'])} 筆官方歷史取得成本參考只描述當時的 IAP／遊戲幣／bundle 條件；全部 model_feature=false，且不推論帳號轉售價。",
            "Catalog scope 已逐列附處置理由，但 1,508 筆 WingBuff／Spell／Quest／Special 類型仍需人工範圍審查，不能把 type-only 排除當作全物品完成。",
            "套組完整度只有 required 成員皆經 canonical model eligibility 且狀態已知時才成為模型特徵；unknown 不再輸出 0 或 false。",
        ],
    }
    coverage_path = root / "reports/coverage/catalog-coverage.json"
    write_utf8_lf(coverage_path, json.dumps(coverage, ensure_ascii=False, indent=2) + "\n")
    completion_status = build_completion_status(
        root,
        args.market_audit_authority_bundle,
        args.market_audit_authority_bundle_sha256,
        args.parser_gold_replay_inputs,
        args.parser_gold_replay_inputs_sha256,
        args.parser_gold_authority_bundle,
        args.parser_gold_authority_bundle_sha256,
        args.parser_keyed_custodian_authority_bundle,
        args.parser_keyed_custodian_authority_bundle_sha256,
        args.parser_keyed_custodian_contract,
        args.parser_keyed_custodian_contract_sha256,
        args.parser_keyed_replay_binding,
        args.parser_keyed_replay_binding_sha256,
        args.canonical_review_authority_bundle,
        args.canonical_review_authority_bundle_sha256,
    )
    write_utf8_lf(root / "reports/completion-status.json", json.dumps(completion_status, ensure_ascii=False, indent=2) + "\n")

    migration_md = f"""# P0 遷移報告

## 實際結果

- 原始 ZIP：`{inventory['source_zip']}`，SHA-256 `{inventory['source_zip_sha256']}`；本次未改寫。
- 原始 ZIP 檔案：{inventory['source_file_count']}；盤點分類為 migrate {inventory['counts']['migrate']}、replace {inventory['counts']['replace']}、remove {inventory['counts']['remove']}、keep {inventory['counts']['keep']}。
- 71 個舊批次共遷移 {len(rows['source_listings'])} 筆匿名來源列，正規化 {len(rows['normalized_listings'])} 筆，建立 {len(rows['account_profiles'])} 筆帳號 profile。
- 既有 102 筆 legacy 可比歷程已全部遷移；另有 {len(rows['curated_histories']) - migration['migrated_histories']} 筆 normalized listing 經明示人工 review 與可重算 predicate hash 恢復，正式歷程共 {len(rows['curated_histories'])} 筆；無法遷移 {migration['not_migrated_histories']} 筆。
- {len(rows['curated_histories'])} 筆歷程已與 profile 合併成 {len(rows['comparable_accounts'])} 筆多維可比帳號；其中 {sum(bool(row.get('collection', {}).get('owned_item_ids')) for row in rows['account_profiles'])} 個 profile 有保守文字映射物品，{sum(bool(row.get('collection', {}).get('item_set_profiles')) for row in rows['account_profiles'])} 個有套組聲稱；模糊詞未映射。
- 正規化資料有 {migration['verified_dates_in_normalized']} 筆可驗證貼文日期；其中 {migration['verified_dates_repaired_in_histories']} 筆舊可比歷程已回接實際日期。
- 未映射季節詞 {migration['unmapped_season_terms']}；未映射物品詞 {migration['unmapped_item_terms']}，均在 review／coverage 檔中保留。
- 可驗證成交價仍為 {verified_sales} 筆；重構沒有把已售聲稱或最後公開價升級成成交。

## 資料流與替換

舊版只作外部不可變來源。新版本只有一套正式來源：`data/source/listings.jsonl` → `data/normalized/*` → `data/curated/histories.jsonl`；`data/comparables/histories.jsonl` 是可重建衍生檔。遊戲知識則只由 `knowledge/` canonical 主檔提供。

逐檔 keep／migrate／replace／remove 清單見 `file-inventory.json`；被移除的執行能力見 `removed-features.md`。
"""
    write_utf8_lf(root / "reports/migration/P0-MIGRATION-REPORT.md", migration_md)

    quality_md = f"""# P0 資料品質與限制

## 已確認

- 季節 {len(rows['seasons'])}、活動 {len(rows['events'])}、物品 {len(rows['items'])}、套組 {len(rows['sets'])}、別名 {len(rows['aliases'])}、來源 {len(rows['sources'])}。
- 1,022 筆來源與正規化資料、102 筆 legacy 歷程均已遷移，另有 1 筆明示覆核恢復歷程；`date_verified=true` 必須同時存在有效貼文日期。
- 季節／活動／物品／套組／來源／別名使用唯一 canonical ID，跨檔參照由離線驗證器檢查。
- 大耳狗／耳狗映射至同一套組；歸巢與築巢是不同季節；極光／歐若拉、梵谷／梵高各自映射到單一季節 ID。
- 估價相似度總分 100，季節 22、物品與套組 20，另含帳型、地圖、收藏、資源、綁定、任次、日期與證據品質；沒有單品固定加價。

## 資料推論

舊市場文字只能保守抽取季節、物品與風險聲稱。沒有圖片支持的欄位維持文字聲稱或 unknown；沒有提供資料不等於確認缺少。刊登價、急售價、最後公開價與驗證成交價分池處理。

## 尚未確認

- canonical needs_review 分布為 {json.dumps(canonical_needs_review, ensure_ascii=False)}；另有類別缺口 queue {len(rows['unresolved'])} 筆、隔離物品候選 {len(rows['item_candidates'])} 筆、unmapped alias {len(rows['unmapped'])} 筆、alias conflict {len(rows['alias_conflicts'])} 筆。這些集合可能重疊，不直接相加成唯一項目數。
- 全物品 catalog 未完成。現有 {len(rows['items'])} 筆是可追溯種子與節點目錄，不代表遊戲全部物品。
- 已將 3,266 筆固定 vendor snapshot 全量分類；其中 {sum(row.get('decision') == 'vendor_correlated_template_candidate' for row in rows['item_promotion_ledger'])} 筆候選只有單一 vendor correlation，canonical identity 仍 unresolved，沒有寫入 canonical 或模型特徵。
- 物品 evidence tier：{json.dumps(count(rows['items'], 'evidence_tier'), ensure_ascii=False)}；模型白名單物品 {sum(row.get('model_feature_status') == 'eligible' for row in rows['items'])} 筆。needs_review、候選與衝突別名均不得進入正式 Item Vector。
- visual reference {len(rows['visual_references'])}、真實 image evidence {len(rows['image_evidence'])}、可驗證成交 {verified_sales}；因此不宣稱圖示辨識準確率或成交價模型。
- 季節節點的繁中正式名、免費／季卡屬性、成本與取得狀態仍有 needs_review 記錄。
"""
    write_utf8_lf(root / "reports/validation/data-quality.md", quality_md)

    # The final release report is produced by release_check.py.  Advance the
    # derived report contract before the validator reads the previous run, so
    # a version bump is reproducible without hand-editing report numbers.
    validation_path = root / "reports/validation/p0-validation.json"
    previous_validation = json.loads(validation_path.read_text(encoding="utf-8"))
    previous_validation["schema_version"] = "5.3-p4.1"
    write_utf8_lf(validation_path, json.dumps(previous_validation, ensure_ascii=False, indent=2) + "\n")

    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["package_id"] = "sky-valuation-v5-p41"
    manifest["package_version"] = "5.3.0-p4.1"
    manifest["research_cutoff_date"] = "2026-08-17"
    manifest["statistics"] = {
        "seasons": len(rows["seasons"]), "events": len(rows["events"]), "ancestors": len(rows["ancestors"]),
        "items": len(rows["items"]), "sets": len(rows["sets"]), "aliases": len(rows["aliases"]),
        "availability_events": len(rows["availability_events"]), "sources": len(rows["sources"]),
        "visual_references": len(rows["visual_references"]),
        "canonical_needs_review_by_entity": canonical_needs_review,
        "unresolved_queue_records": len(rows["unresolved"]),
        "item_candidate_records": len(rows["item_candidates"]),
        "alias_conflict_records": len(rows["alias_conflicts"]),
        "unmapped_aliases": len(rows["unmapped"]),
        "source_listings": len(rows["source_listings"]), "normalized_listings": len(rows["normalized_listings"]),
        "curated_histories": len(rows["curated_histories"]), "verified_completed_sales": verified_sales,
        "comparable_accounts": len(rows["comparable_accounts"]),
        "image_evidence_records": len(rows["image_evidence"]),
        "account_item_vectors": len(rows["item_vectors"]),
        "model_eligible_items": sum(row.get("model_feature_status") == "eligible" for row in rows["items"]),
        "clean_normal_rows": len(rows["clean_normal"]),
        "clean_urgent_rows": len(rows["clean_urgent"]),
        "clean_verified_sale_rows": len(rows["clean_verified_sales"]),
        "model_exclusion_rows": len(rows["model_exclusions"]),
        "item_value_rows": len(rows["item_value_table"]),
        "eligible_item_value_rows": sum(row.get("status") == "eligible" for row in rows["item_value_table"]),
        "vendor_snapshot_items": 3266,
        "vendor_candidate_name_matches": sum(row.get("match_status") == "matched_candidate_name" for row in rows["vendor_crosswalk"]),
        "vendor_item_evidence_rows": len(rows["vendor_item_evidence"]),
        "approved_strict_listing_recoveries": sum(row.get("review_status") == "approved" for row in rows["strict_recovery_reviews"]),
        "catalog_universe_rows": len(rows["catalog_universe"]),
        "identity_evidence_rows": len(rows["item_identity_evidence"]),
        "vendor_correlated_template_candidates": sum(row.get("decision") == "vendor_correlated_template_candidate" for row in rows["item_promotion_ledger"]),
        "identity_rejected_fail_closed": sum(row.get("decision") == "rejected_fail_closed" for row in rows["item_promotion_ledger"]),
        "market_claim_review_rows": len(rows["market_claim_review"]),
        "human_gold_rows": len(rows["market_claim_gold"]),
        "market_near_miss_review_rows": len(rows["market_near_miss_review"]),
        "market_near_miss_approved_evidence_rows": len(rows["market_near_miss_evidence"]),
        "source_scoped_item_identity_rows": len(rows["source_scoped_item_identities"]),
        "source_scoped_identity_unresolved": sum(row.get("link_status") == "unresolved" for row in rows["source_scoped_item_identities"]),
        "fandom_template_records": len(rows["fandom_crosswalk"]),
        "fandom_candidate_links": sum(row.get("match_status") == "season_mapped_candidate_linked" for row in rows["fandom_crosswalk"]),
        "catalog_query_index_rows": len(rows["catalog_query_index"]),
        "verified_canonical_items": sum(row.get("verification_status") == "verified" for row in rows["items"]),
        "canonical_evidence_cohort_rows": len(active_cohorts),
        "canonical_field_evidence_rows": sum(len(evidence) for evidence in cohort_evidence.values()),
        "historical_cost_reference_rows": len(rows["historical_cost_references"]),
        "catalog_scope_needs_review_rows": sum(row.get("review_status") != "approved" for row in rows["catalog_universe"]),
        "authorized_market_dataset_records": len(rows["authorized_market_registry"]),
        "authorized_market_attestation_rows": len(rows["authorized_market_attestations"]),
        "frozen_publication_rows": publication_dataset["dataset_row_count"],
        "parser_known_states": parser_coverage["summary"]["known_state_count"],
        "market_gold_rows": market_gold_evaluation["gold_row_count"],
        "catalog_completion_blockers": len(catalog_completion["blocking_contract_ids"]),
        "visual_actual_assets": visual_evidence_coverage["counts"]["all"]["actual_content_addressed_assets"],
        "visual_approved_detections": visual_evidence_coverage["counts"]["all"]["approved_detections"],
    }
    manifest["derived_paths"] = [
        "data/comparables/histories.jsonl", "data/comparables/accounts.jsonl",
        "data/modeling/account-item-vectors.jsonl", "data/modeling/price-cleaned-normal.jsonl",
        "data/modeling/price-cleaned-urgent.jsonl", "data/modeling/model-exclusions.jsonl",
        "data/modeling/item-value-table.jsonl",
        "data/derived/official-historical-cost-references.jsonl",
        "data/review/catalog-universe.jsonl", "data/review/catalog-universe-summary.json",
        "data/review/item-evidence.jsonl", "data/review/item-promotion-ledger.jsonl",
        "data/review/market-claim-review.jsonl",
        "data/review/market-near-miss-field-review.jsonl",
        "data/review/fandom-seasonal-cosmetics-r107991-crosswalk.jsonl",
        "data/normalized/source-scoped-item-identities.jsonl", "data/normalized/source-scoped-item-identities-summary.json",
        "data/normalized/catalog-query-index.jsonl", "data/normalized/catalog-query-index-summary.json",
        "modeling/artifacts/elastic-net-normal_listing.json", "modeling/artifacts/elastic-net-urgent_sale.json",
        "modeling/artifacts/xgboost-normal_listing.json", "modeling/artifacts/xgboost-urgent_sale.json",
        "reports/coverage/catalog-coverage.json", "reports/model-publication-readiness.json",
        "reports/model-publication-dataset-manifest.json", "reports/model-publication-split.json",
        "reports/model-publication-evaluation.json",
        "reports/catalog-completion.json",
        "reports/market-gold-evaluation.json",
        "reports/coverage/visual-evidence-capability.json",
        "reports/completion-status.json",
        "reports/parser-knowledge-coverage.json",
        "reports/validation/p0-validation.json",
    ]
    # Human decisions are curated inputs. They are never implied to be
    # reproducible derived output merely because the ledger currently starts empty.
    manifest["human_review_paths"] = [
        *(row["evidence_path"] for row in active_cohorts if isinstance(row.get("evidence_path"), str)),
        "data/review/market-claim-gold.jsonl",
        "data/review/market-near-miss-approved-evidence.jsonl",
        "data/review/market-authorization/attestations.jsonl",
    ]
    manifest["generated_at"] = BUILT_AT
    manifest["catalog_status"] = coverage["catalog_claim"]
    manifest["hash_exclusions"] = sorted(HASH_EXCLUSIONS)
    manifest["file_hashes"] = {
        path.relative_to(root).as_posix(): sha256(path)
        for path in release_files(root)
        if path.relative_to(root).as_posix() not in HASH_EXCLUSIONS
    }
    write_utf8_lf(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    print(json.dumps({"coverage": coverage["counts"], "migration": coverage["market_migration"], "manifest_hashes": len(manifest["file_hashes"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
