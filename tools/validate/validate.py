#!/usr/bin/env python3
"""Offline integrity validation for the P0 package (standard library only)."""
from __future__ import annotations

import argparse
import ast
import collections
import hashlib
import json
import math
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "validate"))
from tools.modeling.catalog_provenance import (  # noqa: E402
    CatalogProvenanceError,
    catalog_provenance,
    validate_artifact_catalog_provenance,
    validate_vector_catalog_provenance,
)
sys.path.insert(0, str(ROOT / "tools" / "estimate"))
from evidence import validate_evidence  # noqa: E402
from schema_validator import OfflineSchemaValidator  # noqa: E402
sys.path.insert(0, str(ROOT / "tools" / "normalize"))
from build_comparables import deduplication_is_approved, predicate_hash, strict_recovery_predicates  # noqa: E402
from build_catalog_universe import build_catalog_universe  # noqa: E402
from build_catalog_query_index import build_catalog_query_index  # noqa: E402
from tools.classify.build_account_catalog_resolution import build_account_catalog_resolution, canonical_json, sha256_bytes  # noqa: E402
from build_item_evidence_bundle import build as build_item_evidence, sha as item_evidence_sha  # noqa: E402
from build_market_claim_review import build_queue as build_market_claim_queue, validate_gold_links  # noqa: E402
from build_market_near_miss_review import build_queue as build_market_near_miss_queue, validate_approved_evidence  # noqa: E402
from build_source_scoped_item_identities import build_source_scoped_identities  # noqa: E402
from canonical_evidence_registry import load_registry, validate_registry  # noqa: E402
from market_audit import audit_market_ledgers  # noqa: E402
from promote_items import evaluate as evaluate_item_promotions, verify_replayable_sources  # noqa: E402
from tools.normalize.build_historical_cost_references import build as build_historical_cost_references  # noqa: E402
from tools.modeling.publication_readiness import build as build_publication_readiness  # noqa: E402
from tools.modeling.publication_dataset import build as build_publication_dataset  # noqa: E402
from tools.modeling.publication_evaluator import build as build_publication_evaluation  # noqa: E402
from tools.modeling.parser_knowledge_coverage import build as build_parser_knowledge_coverage  # noqa: E402
from tools.modeling.parser_gold_evaluator import audit_gold as audit_parser_gold, build as build_parser_gold_evaluation  # noqa: E402
from tools.modeling.market_gold_evaluator import build as build_market_gold_evaluation  # noqa: E402
from tools.modeling.visual_evidence_coverage import build as build_visual_evidence_coverage  # noqa: E402
from tools.modeling.canonical_english_eligibility import evaluate as evaluate_exact_english_eligibility  # noqa: E402
from tools.modeling.clean_prices import clean_authorized_with_verified_sales as clean_model_prices  # noqa: E402
from tools.market_authorization import verify_authorized_market_intake  # noqa: E402
from tools.validate.build_completion_status import build as build_completion_status  # noqa: E402
from tools.validate.catalog_completion import build as build_catalog_completion  # noqa: E402
from tools.parser_review.onboarding import validate_manifest as validate_parser_review_manifest  # noqa: E402

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
    "data/modeling/account-item-vectors.jsonl": "schemas/modeling/item-vector.schema.json",
    "data/modeling/price-cleaned-normal.jsonl": "schemas/modeling/cleaned-price.schema.json",
    "data/modeling/price-cleaned-urgent.jsonl": "schemas/modeling/cleaned-price.schema.json",
    "data/modeling/price-cleaned-verified-sales.jsonl": "schemas/modeling/cleaned-price.schema.json",
    "data/modeling/model-exclusions.jsonl": "schemas/modeling/price-exclusion.schema.json",
    "data/modeling/item-value-table.jsonl": "schemas/modeling/item-value-table.schema.json",
    "data/derived/official-historical-cost-references.jsonl": "schemas/knowledge/official-historical-cost-reference.schema.json",
    "data/curated/image-evidence.jsonl": "schemas/evidence/image-evidence.schema.json",
    "data/review/item-candidates.jsonl": "schemas/review/item-candidate.schema.json",
    "data/review/alias-conflicts.jsonl": "schemas/review/alias-conflict.schema.json",
    "data/review/unmapped-item-aliases.jsonl": "schemas/review/unmapped-alias.schema.json",
    "data/review/unmapped-season-aliases.jsonl": "schemas/review/unmapped-alias.schema.json",
    "data/review/price-type-review.jsonl": "schemas/review/price-type-review.schema.json",
    "data/review/strict-listing-recovery.jsonl": "schemas/review/strict-listing-recovery.schema.json",
    "data/review/skygame-data-1.3.4-crosswalk.jsonl": "schemas/review/vendor-catalog-crosswalk.schema.json",
    "data/review/skygame-data-1.3.4-item-evidence.jsonl": "schemas/review/vendor-catalog-item-evidence.schema.json",
    "data/review/catalog-universe.jsonl": "schemas/review/catalog-universe.schema.json",
    "data/review/catalog-scope-decisions.jsonl": "schemas/review/catalog-scope-decision.schema.json",
    "data/review/item-evidence.jsonl": "schemas/review/item-evidence.schema.json",
    "data/review/item-promotion-ledger.jsonl": "schemas/review/item-promotion-ledger.schema.json",
    "data/review/canonical-evidence-cohorts.jsonl": "schemas/review/canonical-evidence-cohort.schema.json",
    "data/review/market-claim-review.jsonl": "schemas/review/market-claim-review.schema.json",
    "data/review/market-claim-gold.jsonl": "schemas/review/market-claim-gold.schema.json",
    "data/review/market-near-miss-field-review.jsonl": "schemas/review/market-near-miss-field-review.schema.json",
    "data/review/market-near-miss-approved-evidence.jsonl": "schemas/review/market-near-miss-approved-evidence.schema.json",
    "data/review/market-audit/attestations.jsonl": "schemas/review/market-audit-attestation.schema.json",
    "data/review/parser-gold/claims.jsonl": "schemas/review/parser-gold.schema.json",
    "data/review/parser-gold/attestations.jsonl": "schemas/review/parser-gold-attestation.schema.json",
    "data/review/market-authorization/registry.jsonl": "schemas/market/authorized-market-dataset.schema.json",
    "data/review/market-authorization/attestations.jsonl": "schemas/market/authorized-market-attestation.schema.json",
    "data/review/account-catalog-resolution.jsonl": "schemas/review/account-catalog-resolution.schema.json",
    "data/review/fandom-seasonal-cosmetics-r107991-crosswalk.jsonl": "schemas/review/fandom-seasonal-cosmetics-crosswalk.schema.json",
    "data/normalized/source-scoped-item-identities.jsonl": "schemas/normalized/source-scoped-item-identity.schema.json",
    "data/normalized/catalog-query-index.jsonl": "schemas/normalized/catalog-query-index.schema.json",
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
    "reports/model-publication-readiness.json": "schemas/modeling/publication-readiness.schema.json",
    "reports/model-publication-dataset-manifest.json": "schemas/modeling/publication-dataset-manifest.schema.json",
    "reports/model-publication-split.json": "schemas/modeling/publication-split.schema.json",
    "reports/model-publication-evaluation.json": "schemas/modeling/publication-evaluation.schema.json",
    "reports/parser-knowledge-coverage.json": "schemas/modeling/parser-knowledge-coverage.schema.json",
    "reports/parser-gold-evaluation.json": "schemas/modeling/parser-gold-evaluation.schema.json",
    "reports/market-gold-evaluation.json": "schemas/review/market-gold-evaluation.schema.json",
    "reports/catalog-completion.json": "schemas/reports/catalog-completion.schema.json",
    "reports/coverage/visual-evidence-capability.json": "schemas/reports/visual-evidence-capability.schema.json",
    "data/review/parser-gold/review-queue-manifest.json": "schemas/review/parser-review-queue.schema.json",
    "reports/completion-status.json": "schemas/reports/completion-status.schema.json",
    "modeling/artifacts/elastic-net-normal_listing.json": "schemas/modeling/elastic-net-artifact.schema.json",
    "modeling/artifacts/elastic-net-urgent_sale.json": "schemas/modeling/elastic-net-artifact.schema.json",
    "modeling/artifacts/xgboost-normal_listing.json": "schemas/modeling/xgboost-artifact.schema.json",
    "modeling/artifacts/xgboost-urgent_sale.json": "schemas/modeling/xgboost-artifact.schema.json",
    "data/source/vendor/skygame-data-1.3.4-items.json": "schemas/knowledge/vendor-catalog-snapshot.schema.json",
    "data/source/vendor/skygame-data-1.3.4-metadata.json": "schemas/knowledge/vendor-catalog-metadata.schema.json",
    "data/review/skygame-data-1.3.4-crosswalk-summary.json": "schemas/review/vendor-catalog-summary.schema.json",
    "data/review/catalog-universe-summary.json": "schemas/review/catalog-universe-summary.schema.json",
    "data/source/vendor/fandom-seasonal-cosmetics-r107991-snapshot.json": "schemas/review/fandom-seasonal-cosmetics-snapshot.schema.json",
    "data/review/parser-gold/rule-development-manifest.json": "schemas/review/parser-gold-rule-development-manifest.schema.json",
    "data/source/vendor/fandom-seasonal-cosmetics-r107991-metadata.json": "schemas/review/fandom-seasonal-cosmetics-metadata.schema.json",
    "data/review/fandom-seasonal-cosmetics-r107991-crosswalk-summary.json": "schemas/review/fandom-seasonal-cosmetics-crosswalk-summary.schema.json",
    "data/normalized/source-scoped-item-identities-summary.json": "schemas/normalized/source-scoped-item-identities-summary.schema.json",
    "data/normalized/catalog-query-index-summary.json": "schemas/normalized/catalog-query-index-summary.schema.json",
    "data/source/research/tgc-faq-823-nintendo-starter-pack.json": "schemas/knowledge/official-item-fact-snapshot.schema.json",
    "data/source/research/tgc-faq-968-aurora-remaining-iap.json": "schemas/knowledge/aurora-faq-968-fact-snapshot.schema.json",
    "data/source/research/tgc-faq-1308-journey-pack.json": "schemas/knowledge/journey-pack-fact-snapshot.schema.json",
    "data/source/research/tgc-faq-1356-moomintroll-accessory-set.json": "schemas/knowledge/moomintroll-accessory-set-fact-snapshot.schema.json",
    "data/source/research/tgc-faq-879-kizuna-ai-2022.json": "schemas/knowledge/kizuna-ai-2022-fact-snapshot.schema.json",
    "data/source/research/tgc-faq-1330-skyfest-core-five.json": "schemas/knowledge/skyfest-faq-1330-core-five-fact-snapshot.schema.json",
    "data/source/research/tgc-faq-1330-tournament-of-triumph-core-four.json": "schemas/knowledge/tournament-of-triumph-faq-1330-core-four-fact-snapshot.schema.json",
    "data/source/research/tgc-faq-1323-days-of-color-core-three.json": "schemas/knowledge/days-of-color-faq-1323-core-three-fact-snapshot.schema.json",
    "data/source/research/tgc-faq-1343-days-of-sunlight-core-three.json": "schemas/knowledge/days-of-sunlight-faq-1343-core-three-fact-snapshot.schema.json",
    "data/source/research/tgc-faq-1308-cinnamoroll-popup-cafe.json": "schemas/knowledge/cinnamoroll-popup-cafe-faq-1308-fact-snapshot.schema.json",
}


def authorized_market_schema_files(root: Path) -> tuple[dict[str, str], dict[str, str]]:
    """Discover signed dataset files from the registry/manifest trust chain."""
    jsonl_files: dict[str, str] = {}
    json_files: dict[str, str] = {}
    registry = root / "data/review/market-authorization/registry.jsonl"
    if not registry.is_file():
        return jsonl_files, json_files
    try:
        datasets = read_jsonl(registry)
    except (ValueError, json.JSONDecodeError):
        return jsonl_files, json_files
    for dataset in datasets:
        manifest_rel = dataset.get("manifest_path")
        if not isinstance(manifest_rel, str):
            continue
        json_files[manifest_rel] = "schemas/market/authorized-market-manifest.schema.json"
        manifest_path = root / manifest_rel
        if not manifest_path.is_file():
            continue
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        observations_rel = manifest.get("observations_path")
        if isinstance(observations_rel, str):
            jsonl_files[observations_rel] = "schemas/market/authorized-market-observation.schema.json"
        training_rel = manifest.get("training_examples_path")
        if isinstance(training_rel, str):
            jsonl_files[training_rel] = "schemas/market/authorized-market-training-example.schema.json"
    return jsonl_files, json_files
REQUIRED_FORMAL_JSONL = {
    "data/source/listings.jsonl", "data/normalized/listings.jsonl", "data/normalized/account-profiles.jsonl",
    "data/curated/histories.jsonl", "data/comparables/histories.jsonl", "data/comparables/accounts.jsonl",
    "data/modeling/account-item-vectors.jsonl", "data/modeling/price-cleaned-normal.jsonl",
    "data/modeling/price-cleaned-urgent.jsonl", "data/modeling/model-exclusions.jsonl",
    "data/modeling/price-cleaned-verified-sales.jsonl",
    "data/modeling/item-value-table.jsonl",
    "data/derived/official-historical-cost-references.jsonl",
    "data/review/account-catalog-resolution.jsonl",
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


def formal_price_rebuild_errors(
    comparable_accounts: list[dict[str, Any]],
    actual_normal: list[dict[str, Any]],
    actual_urgent: list[dict[str, Any]],
    actual_verified_sales: list[dict[str, Any]],
    actual_exclusions: list[dict[str, Any]],
    root: Path,
    authority_bundle: str | Path | None = None, authority_bundle_sha256: str | None = None,
    statement: str | Path | None = None, statement_sha256: str | None = None,
) -> list[str]:
    """Reject any formal model-price row not produced by the authorization gate."""
    expected_normal, expected_urgent, expected_verified_sales, expected_exclusions = clean_model_prices(
        comparable_accounts, root, authority_bundle, authority_bundle_sha256, statement, statement_sha256,
    )
    problems: list[str] = []
    if actual_normal != expected_normal:
        problems.append("price-cleaned-normal differs from deterministic authorized rebuild")
    if actual_urgent != expected_urgent:
        problems.append("price-cleaned-urgent differs from deterministic authorized rebuild")
    if actual_verified_sales != expected_verified_sales:
        problems.append("price-cleaned-verified-sales differs from deterministic authorized rebuild")
    if actual_exclusions != expected_exclusions:
        problems.append("model-exclusions differs from deterministic authorized rebuild")
    return problems


def validate_canonical_field_evidence(
    evidence_groups: list[tuple[str, list[dict[str, Any]]]],
    items: dict[str, dict[str, Any]],
    sets: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
) -> list[str]:
    """Validate target, source-lineage, value-type, and canonical agreement."""
    problems: list[str] = []
    seen: set[str] = set()
    item_fields = {
        "canonical_name_en", "identity_description", "item_category", "vendor_item_name", "vendor_item_type", "vendor_item_guid", "source_type",
        "set_membership", "availability_status", "availability_history", "original_cost",
        "original_currency", "first_release_date", "free_or_premium",
        "permanent_account_item", "collaboration", "visual_reference",
    }
    set_fields = {"identity_description", "source_type", "set_required_item_ids", "scope_definition", "historical_pack_price_usd", "platform_access_history", "availability_history"}
    string_fields = item_fields - {"original_cost", "collaboration"}
    official_source_types = {"official_site", "official_news", "official_support", "thatgamecompany"}
    for label, rows in evidence_groups:
        for row in rows:
            evidence_id = str(row.get("evidence_id", "unknown"))
            prefix = f"canonical-evidence:{label}:{evidence_id}"
            if evidence_id in seen:
                problems.append(f"{prefix}: duplicate evidence_id across cohorts")
            seen.add(evidence_id)
            target_type, target_id = row.get("target_type"), row.get("target_id")
            field, value = row.get("field_path"), row.get("claim_value")
            if target_type == "item":
                if not isinstance(target_id, str) or not target_id.startswith("item_") or target_id not in items:
                    problems.append(f"{prefix}: item target is not a canonical item")
                if field not in item_fields:
                    problems.append(f"{prefix}: field {field!r} is not valid for an item")
            elif target_type == "set":
                if not isinstance(target_id, str) or not target_id.startswith("set_") or target_id not in sets:
                    problems.append(f"{prefix}: set target is not a canonical set")
                if field not in set_fields:
                    problems.append(f"{prefix}: field {field!r} is not valid for a set")
            source = sources.get(row.get("source_id"))
            if source is None:
                problems.append(f"{prefix}: source_id is not registered")
            else:
                if source.get("source_lineage_id") != row.get("source_lineage_id"):
                    problems.append(f"{prefix}: source lineage differs from source registry")
                is_official = source.get("source_type") in official_source_types
                tier = row.get("source_tier")
                if tier in {"official_item_specific", "official_general"} and not is_official:
                    problems.append(f"{prefix}: non-official source claims an official tier")
                if tier == "secondary_reference" and is_official:
                    problems.append(f"{prefix}: official source is mislabeled as secondary")
            if field in string_fields and not isinstance(value, str):
                problems.append(f"{prefix}: {field} claim must be a string")
            if field == "original_cost" and (isinstance(value, bool) or not isinstance(value, (int, float))):
                problems.append(f"{prefix}: original_cost claim must be numeric")
            if field == "collaboration" and not isinstance(value, bool):
                problems.append(f"{prefix}: collaboration claim must be boolean")
            if field in {"set_required_item_ids", "scope_definition"} and not isinstance(value, list):
                problems.append(f"{prefix}: {field} claim must be an array")
            target = items.get(target_id) if target_type == "item" else sets.get(target_id)
            if target is not None and field in {"canonical_name_en", "original_cost"} and target.get(field) != value:
                problems.append(f"{prefix}: approved claim differs from canonical {field}")
            if target is not None and field == "item_category" and str(target.get(field, "")).casefold() != str(value).casefold():
                problems.append(f"{prefix}: approved category differs from canonical item_category")
    return problems


def _vendor_claim_key(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"[^\w]+", "", unicodedata.normalize("NFKC", value).casefold(), flags=re.UNICODE)


def validate_vendor_evidence_links(vendor_metadata: dict[str, Any], vendor_snapshot: dict[str, Any], crosswalk: list[dict[str, Any]], candidates: dict[str, dict[str, Any]], evidence_rows: list[dict[str, Any]]) -> list[str]:
    """Fail closed unless secondary candidate evidence is exactly source-bound."""
    errors: list[str] = []
    snapshot_by_pair = {(row.get("guid"), row.get("id")): row for row in vendor_snapshot.get("items", [])}
    crosswalk_by_pair: dict[tuple[Any, Any], dict[str, Any]] = {}
    candidate_match_pairs: set[tuple[Any, Any]] = set()
    for row in crosswalk:
        pair = (row.get("vendor_guid"), row.get("vendor_item_id"))
        source = snapshot_by_pair.get(pair)
        if pair in crosswalk_by_pair:
            errors.append(f"vendor-catalog:{pair}: duplicate crosswalk row")
            continue
        crosswalk_by_pair[pair] = row
        if not source:
            continue
        if row.get("vendor_name") != source.get("name") or row.get("vendor_item_type") != source.get("type"):
            errors.append(f"vendor-catalog:{pair}: crosswalk name or type differs from snapshot")
        if row.get("match_status") == "matched_candidate_name":
            if row.get("canonical_item_ids") or len(row.get("candidate_item_ids", [])) != 1:
                errors.append(f"vendor-catalog:{pair}: candidate match violates canonical-priority gate")
            else:
                candidate_match_pairs.add(pair)

    evidence_pairs: set[tuple[Any, Any]] = set()
    evidence_ids: set[str] = set()
    for row in evidence_rows:
        evidence_id = row.get("evidence_id")
        pair = (row.get("locator"), row.get("vendor_item_id"))
        if evidence_id in evidence_ids:
            errors.append(f"vendor-evidence: duplicate evidence_id={evidence_id}")
        evidence_ids.add(str(evidence_id))
        if pair in evidence_pairs:
            errors.append(f"vendor-evidence:{evidence_id}: duplicate candidate evidence pair={pair}")
        evidence_pairs.add(pair)
        source, linked = snapshot_by_pair.get(pair), crosswalk_by_pair.get(pair)
        candidate_id = row.get("candidate_item_id")
        if candidate_id not in candidates:
            errors.append(f"vendor-evidence:{evidence_id}: dangling candidate")
        if row.get("source_id") != vendor_metadata.get("source_id") or row.get("snapshot_id") != vendor_metadata.get("snapshot_id") or row.get("snapshot_sha256") != vendor_metadata.get("snapshot_sha256"):
            errors.append(f"vendor-evidence:{evidence_id}: source or snapshot mismatch")
        if not source or not linked:
            errors.append(f"vendor-evidence:{evidence_id}: locator pair is not a snapshot/crosswalk pair")
            continue
        if linked.get("match_status") != "matched_candidate_name" or linked.get("candidate_item_ids") != [candidate_id]:
            errors.append(f"vendor-evidence:{evidence_id}: missing exact candidate crosswalk linkage")
        if row.get("claim_value") != linked.get("vendor_name") or row.get("claim_value") != source.get("name"):
            errors.append(f"vendor-evidence:{evidence_id}: claim value differs from crosswalk or snapshot")
        if row.get("vendor_item_type") != linked.get("vendor_item_type") or row.get("vendor_item_type") != source.get("type"):
            errors.append(f"vendor-evidence:{evidence_id}: vendor item type differs from crosswalk or snapshot")
        expected_hash = hashlib.sha256(_vendor_claim_key(source.get("name")).encode("utf-8")).hexdigest().upper()
        if row.get("claim_value_hash") != expected_hash:
            errors.append(f"vendor-evidence:{evidence_id}: claim hash differs from snapshot claim")
        expected_id = "evidence_vendor_" + hashlib.sha256(f"vendor_skygame_data_1_3_4\0{candidate_id}\0{row.get('locator')}\0candidate_name_en".encode("utf-8")).hexdigest()[:24]
        if evidence_id != expected_id:
            errors.append(f"vendor-evidence:{evidence_id}: evidence ID is not deterministic for its candidate and locator")
    if evidence_pairs != candidate_match_pairs:
        errors.append(f"vendor-evidence: candidate crosswalk/evidence pairs differ missing={sorted(candidate_match_pairs - evidence_pairs)!r} extra={sorted(evidence_pairs - candidate_match_pairs)!r}")
    return errors


def validate(
    root: Path = ROOT, market_audit_authority_bundle: str | Path | None = None,
    market_audit_authority_bundle_sha256: str | None = None,
    market_authorization_authority_bundle: str | Path | None = None,
    market_authorization_authority_bundle_sha256: str | None = None,
    market_authorization_statement: str | Path | None = None,
    market_authorization_statement_sha256: str | None = None,
    parser_gold_authority_bundle: str | Path | None = None,
    parser_gold_authority_bundle_sha256: str | None = None,
    parser_gold_replay_inputs: Path | None = None,
    parser_gold_replay_inputs_sha256: str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    authorization_errors = verify_authorized_market_intake(
        root, market_authorization_authority_bundle,
        market_authorization_authority_bundle_sha256,
        market_authorization_statement, market_authorization_statement_sha256,
    )
    errors.extend(f"authorized-market-intake: {issue}" for issue in authorization_errors)
    ids: dict[str, set[str]] = {}
    records_by_path: dict[Path, list[dict[str, Any]]] = {}
    schema_validator = OfflineSchemaValidator(root / "schemas")
    schema_checked = 0
    cohort_schema_files = {
        str(row["evidence_path"]): "schemas/review/canonical-item-field-evidence.schema.json"
        for row in load_registry(root)
        if isinstance(row.get("evidence_path"), str) and (root / row["evidence_path"]).is_file()
    }
    authorized_jsonl_files, authorized_json_files = authorized_market_schema_files(root)
    schema_files = {**SCHEMA_FILES, **cohort_schema_files, **authorized_jsonl_files}
    json_schema_files = {**JSON_SCHEMA_FILES, **authorized_json_files}
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
    declared_formal_json = set(schema_files) | set(json_schema_files)
    for rel in sorted(actual_formal_json - declared_formal_json):
        errors.append(f"formal JSON/JSONL has no schema mapping: {rel}")
    for rel in sorted(declared_formal_json - actual_formal_json):
        errors.append(f"schema mapping points to missing formal data: {rel}")
    for rel, schema_rel in schema_files.items():
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
    for rel, schema_rel in json_schema_files.items():
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
    alias_targets: dict[str, set[tuple[str, str]]] = {}
    alias_ids: set[str] = set()
    for row in read_jsonl(root / "knowledge/aliases/item-aliases.jsonl"):
        if row.get("target_id") not in target_ids.get(row.get("target_type"), set()):
            errors.append(f"alias:{row.get('alias_id')}: dangling target")
        for ref in row.get("source_ids", []):
            if ref not in sources: errors.append(f"alias:{row.get('alias_id')}: dangling source={ref}")
        alias_ids.add(str(row.get("alias_id")))
        key = str(row.get("normalized_alias"))
        alias_targets.setdefault(key, set()).add((str(row.get("target_type")), str(row.get("target_id"))))
    for alias, targets in alias_targets.items():
        if len(targets) > 1:
            errors.append(f"alias:{alias}: ambiguous canonical targets={sorted(targets)}")
    for row in read_jsonl(root / "data/review/alias-conflicts.jsonl"):
        for candidate in row.get("candidate_targets", []):
            target_type, target_id = candidate.get("target_type"), candidate.get("target_id")
            if target_id not in target_ids.get(target_type, set()):
                errors.append(f"alias-conflict:{row.get('normalized_alias')}: dangling candidate target={target_id}")
        for alias_id in row.get("source_alias_ids", []):
            if alias_id in alias_ids:
                errors.append(f"alias-conflict:{row.get('normalized_alias')}: unresolved alias remains canonical={alias_id}")
    vendor_metadata = json.loads((root / "data/source/vendor/skygame-data-1.3.4-metadata.json").read_text(encoding="utf-8"))
    if vendor_metadata.get("source_id") not in sources:
        errors.append("vendor-catalog: metadata source_id is not canonical")

    fandom_metadata = json.loads((root / "data/source/vendor/fandom-seasonal-cosmetics-r107991-metadata.json").read_text(encoding="utf-8"))
    if fandom_metadata.get("source_id") not in sources:
        errors.append("fandom-snapshot: metadata source_id is not canonical")
    for source_id in fandom_metadata.get("not_independent_of_source_ids", []):
        if source_id not in sources:
            errors.append(f"fandom-snapshot: dangling related source_id={source_id}")
    for row in read_jsonl(root / "data/review/fandom-seasonal-cosmetics-r107991-crosswalk.jsonl"):
        if row.get("source_id") != fandom_metadata.get("source_id"):
            errors.append(f"fandom-snapshot:{row.get('crosswalk_id')}: source_id does not match metadata")
    vendor_snapshot_path = root / "data/source/vendor/skygame-data-1.3.4-items.json"
    vendor_tarball_path = root / "data/source/vendor/skygame-data-1.3.4.tgz"
    vendor_snapshot = json.loads(vendor_snapshot_path.read_text(encoding="utf-8"))
    if hashlib.sha256(vendor_snapshot_path.read_bytes()).hexdigest().upper() != vendor_metadata.get("snapshot_sha256"):
        errors.append("vendor-catalog: snapshot SHA-256 mismatch")
    if hashlib.sha256(vendor_tarball_path.read_bytes()).hexdigest().upper() != vendor_metadata.get("tarball_sha256"):
        errors.append("vendor-catalog: tarball SHA-256 mismatch")
    vendor_pairs = {(row.get("guid"), row.get("id")) for row in vendor_snapshot.get("items", [])}
    vendor_guids = {guid for guid, _ in vendor_pairs}
    vendor_ids = {item_id for _, item_id in vendor_pairs}
    if len(vendor_guids) != len(vendor_snapshot.get("items", [])) or len(vendor_ids) != len(vendor_snapshot.get("items", [])):
        errors.append("vendor-catalog: snapshot IDs or GUIDs are not unique")
    crosswalk = read_jsonl(root / "data/review/skygame-data-1.3.4-crosswalk.jsonl")
    if len(crosswalk) != len(vendor_snapshot.get("items", [])):
        errors.append("vendor-catalog: crosswalk does not cover the exact snapshot")
    candidates = {row.get("candidate_item_id"): row for row in read_jsonl(root / "data/review/item-candidates.jsonl")}
    crosswalk_pairs: dict[tuple[Any, Any], dict[str, Any]] = {}
    for row in crosswalk:
        pair = (row.get("vendor_guid"), row.get("vendor_item_id"))
        if pair in crosswalk_pairs:
            errors.append(f"vendor-catalog:{pair}: duplicate crosswalk row")
        crosswalk_pairs[pair] = row
        if row.get("source_id") not in sources:
            errors.append(f"vendor-catalog:{row.get('vendor_guid')}: dangling source")
        if pair not in vendor_pairs:
            errors.append(f"vendor-catalog:{row.get('vendor_guid')}: row not present in snapshot")
        for item_id in row.get("canonical_item_ids", []):
            if item_id not in items:
                errors.append(f"vendor-catalog:{row.get('vendor_guid')}: dangling canonical item={item_id}")
        for candidate_id in row.get("candidate_item_ids", []):
            if candidate_id not in candidates:
                errors.append(f"vendor-catalog:{row.get('vendor_guid')}: dangling candidate item={candidate_id}")
        if row.get("match_status") == "matched_candidate_name" and (row.get("canonical_item_ids") or len(row.get("candidate_item_ids", [])) != 1):
            errors.append(f"vendor-catalog:{row.get('vendor_guid')}: candidate match violates canonical-priority gate")
    source_scoped_identities = read_jsonl(root / "data/normalized/source-scoped-item-identities.jsonl")
    source_scoped_summary = json.loads((root / "data/normalized/source-scoped-item-identities-summary.json").read_text(encoding="utf-8"))
    try:
        expected_source_scoped_identities, expected_source_scoped_summary = build_source_scoped_identities(vendor_snapshot, vendor_metadata, crosswalk)
    except ValueError as exc:
        errors.append(f"source-scoped-identities: cannot rebuild: {exc}")
    else:
        if source_scoped_identities != expected_source_scoped_identities:
            errors.append("source-scoped-identities: committed rows differ from deterministic snapshot/crosswalk rebuild")
        if source_scoped_summary != expected_source_scoped_summary:
            errors.append("source-scoped-identities: committed summary differs from deterministic rebuild")
    reference_ids: set[str] = set()
    for row in source_scoped_identities:
        reference_id = row.get("reference_identity_id")
        if reference_id in reference_ids:
            errors.append(f"source-scoped-identities: duplicate reference_identity_id={reference_id}")
        reference_ids.add(str(reference_id))
        if row.get("source_id") not in sources:
            errors.append(f"source-scoped-identities:{reference_id}: dangling source_id")
        if row.get("source_id") != vendor_metadata.get("source_id") or row.get("snapshot_id") != vendor_metadata.get("snapshot_id") or row.get("source_snapshot_sha256") != vendor_metadata.get("snapshot_sha256"):
            errors.append(f"source-scoped-identities:{reference_id}: source/snapshot hash mismatch")
        if (row.get("vendor_guid"), row.get("vendor_item_id")) not in vendor_pairs:
            errors.append(f"source-scoped-identities:{reference_id}: dangling vendor observation")
        for item_id in row.get("canonical_item_ids", []):
            if item_id not in items:
                errors.append(f"source-scoped-identities:{reference_id}: dangling canonical item={item_id}")
        for candidate_id in row.get("candidate_item_ids", []):
            if candidate_id not in candidates:
                errors.append(f"source-scoped-identities:{reference_id}: dangling candidate item={candidate_id}")
        if row.get("model_feature_status") != "excluded_pending_verification" or row.get("promotion_eligibility") != "prohibited":
            errors.append(f"source-scoped-identities:{reference_id}: attempted model or canonical promotion")
    evidence_rows = read_jsonl(root / "data/review/skygame-data-1.3.4-item-evidence.jsonl")
    evidence_ids: set[str] = set()
    for row in evidence_rows:
        evidence_id = row.get("evidence_id")
        if evidence_id in evidence_ids:
            errors.append(f"vendor-evidence: duplicate evidence_id={evidence_id}")
        evidence_ids.add(str(evidence_id))
        pair = (row.get("locator"), row.get("vendor_item_id"))
        linked = crosswalk_pairs.get(pair)
        if row.get("candidate_item_id") not in candidates:
            errors.append(f"vendor-evidence:{evidence_id}: dangling candidate")
        if row.get("source_id") != vendor_metadata.get("source_id") or row.get("snapshot_sha256") != vendor_metadata.get("snapshot_sha256"):
            errors.append(f"vendor-evidence:{evidence_id}: source or snapshot mismatch")
        claim = row.get("claim_value")
        normalized_claim = "".join(char.casefold() for char in claim if char.isalnum()) if isinstance(claim, str) else ""
        if not isinstance(claim, str) or hashlib.sha256(normalized_claim.encode("utf-8")).hexdigest().upper() != row.get("claim_value_hash"):
            errors.append(f"vendor-evidence:{evidence_id}: claim hash mismatch")
        if not linked or linked.get("match_status") != "matched_candidate_name" or linked.get("candidate_item_ids") != [row.get("candidate_item_id")]:
            errors.append(f"vendor-evidence:{evidence_id}: missing exact candidate crosswalk linkage")
    errors.extend(validate_vendor_evidence_links(vendor_metadata, vendor_snapshot, crosswalk, candidates, evidence_rows))
    summary = json.loads((root / "data/review/skygame-data-1.3.4-crosswalk-summary.json").read_text(encoding="utf-8"))
    status_counts = dict(sorted(collections.Counter(str(row.get("match_status")) for row in crosswalk).items()))
    expected_summary = {
        "vendor_item_count": len(vendor_pairs),
        "canonical_matched_count": status_counts.get("matched_canonical_name", 0) + status_counts.get("matched_alias", 0),
        "candidate_matched_count": status_counts.get("matched_candidate_name", 0),
        "unmatched_collectible_count": status_counts.get("unmatched_vendor_item", 0),
        "field_evidence_count": len(evidence_rows),
        "status_counts": status_counts,
    }
    for key, expected in expected_summary.items():
        if summary.get(key) != expected:
            errors.append(f"vendor-catalog: summary {key} mismatch expected={expected!r} actual={summary.get(key)!r}")
    universe = read_jsonl(root / "data/review/catalog-universe.jsonl")
    universe_summary = json.loads((root / "data/review/catalog-universe-summary.json").read_text(encoding="utf-8"))
    try:
        scope_decisions = read_jsonl(root / "data/review/catalog-scope-decisions.jsonl")
        expected_universe, expected_universe_summary = build_catalog_universe(vendor_snapshot, vendor_metadata, crosswalk, scope_decisions, root=root, sources=sources)
    except ValueError as exc:
        errors.append(f"catalog-universe: cannot reconcile snapshot/crosswalk: {exc}")
    else:
        if universe != expected_universe:
            errors.append("catalog-universe: committed rows differ from deterministic snapshot/crosswalk reconciliation")
        if universe_summary != expected_universe_summary:
            errors.append("catalog-universe: committed summary differs from deterministic reconciliation")
    query_index = read_jsonl(root / "data/normalized/catalog-query-index.jsonl")
    query_summary = json.loads((root / "data/normalized/catalog-query-index-summary.json").read_text(encoding="utf-8"))
    try:
        expected_query_index, expected_query_summary = build_catalog_query_index(
            list(items.values()), read_jsonl(root / "knowledge/aliases/item-aliases.jsonl"),
            list(candidates.values()), read_jsonl(root / "data/normalized/source-scoped-item-identities.jsonl"),
            root / "data/source/vendor/skygame-data-1.3.4-items.json", vendor_metadata,
        )
    except ValueError as exc:
        errors.append(f"catalog-query-index: cannot rebuild: {exc}")
    else:
        if query_index != expected_query_index:
            errors.append("catalog-query-index: committed rows differ from deterministic rebuild")
        if query_summary != expected_query_summary:
            errors.append("catalog-query-index: committed summary differs from deterministic rebuild")
    resolution_path = root / "data/review/account-catalog-resolution.jsonl"
    account_catalog_resolution = read_jsonl(resolution_path)
    resolution_profiles = read_jsonl(root / "data/normalized/account-profiles.jsonl")
    resolution_listings = read_jsonl(root / "data/normalized/listings.jsonl")
    try:
        expected_account_catalog_resolution = build_account_catalog_resolution(
            resolution_profiles, resolution_listings, query_index,
            index_sha256=sha256_bytes((root / "data/normalized/catalog-query-index.jsonl").read_bytes()),
        )
    except ValueError as exc:
        errors.append(f"account-catalog-resolution: cannot rebuild: {exc}")
    else:
        if account_catalog_resolution != expected_account_catalog_resolution:
            errors.append("account-catalog-resolution: committed rows differ from deterministic rebuild")
    profile_by_id = {row.get("account_id"): row for row in resolution_profiles}
    resolution_listing_by_id = {row.get("listing_id"): row for row in resolution_listings}
    index_by_id = {row.get("query_entity_id"): row for row in query_index}
    if len(account_catalog_resolution) != len(resolution_profiles) or {row.get("account_id") for row in account_catalog_resolution} != set(profile_by_id):
        errors.append("account-catalog-resolution: exact account coverage/linkage mismatch")
    forbidden_resolution_keys = {"ownership_state", "resolved_item_id", "state", "raw", "listing_text", "alias", "span", "url", "source_url"}
    for row in account_catalog_resolution:
        account = profile_by_id.get(row.get("account_id"))
        listing_id = row.get("listing_id")
        listing = resolution_listing_by_id.get(listing_id)
        expected_eligible = bool(
            account and listing and account.get("source_listing_ids") == [listing_id]
            and account.get("trade_conditions", {}).get("offer_kind") == listing.get("offer_kind")
            and account.get("trade_conditions", {}).get("entity_kind") == listing.get("entity_kind")
            and listing.get("offer_kind") == "seller_listing" and listing.get("entity_kind") == "single_account"
        )
        if (row.get("matching_eligibility") == "eligible") != expected_eligible:
            errors.append(f"account-catalog-resolution:{row.get('account_id')}: seller/single-account gate mismatch")
        if row.get("catalog_query_index_sha256") != sha256_bytes((root / "data/normalized/catalog-query-index.jsonl").read_bytes()):
            errors.append(f"account-catalog-resolution:{row.get('account_id')}: index hash mismatch")
        if listing:
            if row.get("listing_text_sha256") != sha256_bytes(str(listing.get("listing_text", "")).encode("utf-8")):
                errors.append(f"account-catalog-resolution:{row.get('account_id')}: listing input hash mismatch")
            if row.get("normalized_feature_summary_sha256") != sha256_bytes(canonical_json(listing.get("feature_summary", []))):
                errors.append(f"account-catalog-resolution:{row.get('account_id')}: feature-summary input hash mismatch")
        if not expected_eligible and row.get("matches"):
            errors.append(f"account-catalog-resolution:{row.get('account_id')}: suppressed account has matches")
        for match in row.get("matches", []):
            source = index_by_id.get(match.get("query_entity_id"))
            if not source or any(match.get(key) != source.get(key) for key in ("query_entity_type", "truth_level", "verification_status", "review_status")):
                errors.append(f"account-catalog-resolution:{row.get('account_id')}: query-index linkage mismatch")
            if match.get("review_only") is not True or match.get("model_feature") is not False:
                errors.append(f"account-catalog-resolution:{row.get('account_id')}: attempted ownership/model promotion")
        def keys(value: Any) -> set[str]:
            if isinstance(value, dict):
                return set(value) | set().union(*(keys(child) for child in value.values())) if value else set()
            if isinstance(value, list):
                return set().union(*(keys(child) for child in value)) if value else set()
            return set()
        prohibited = forbidden_resolution_keys & keys(row)
        if prohibited:
            errors.append(f"account-catalog-resolution:{row.get('account_id')}: prohibited output keys {sorted(prohibited)}")
    item_evidence = read_jsonl(root / "data/review/item-evidence.jsonl")
    expected_item_evidence = build_item_evidence(
        list(candidates.values()), evidence_rows,
        item_evidence_sha((root / "data/review/item-candidates.jsonl").read_bytes()),
    )
    if item_evidence != expected_item_evidence:
        errors.append("item-evidence: committed rows differ from deterministic pinned-source correlation")
    try:
        source_records = {row["source_id"]: row for row in read_jsonl(root / "knowledge/sources/sources.jsonl")}
        verified_item_evidence_ids = verify_replayable_sources(root, item_evidence, source_records)
    except ValueError as exc:
        errors.append(f"item-evidence: {exc}")
        verified_item_evidence_ids = set()
    promotion_ledger = read_jsonl(root / "data/review/item-promotion-ledger.jsonl")
    expected_promotions = evaluate_item_promotions(
        list(candidates.values()), set(items), read_jsonl(root / "data/review/alias-conflicts.jsonl"),
        item_evidence, mode="vendor_correlation", verified_evidence_ids=verified_item_evidence_ids,
    )
    if promotion_ledger != expected_promotions:
        errors.append("item-promotion: committed ledger differs from deterministic fail-closed evaluation")
    if any(row.get("canonical_write") != "not_performed" or row.get("model_feature_status") != "excluded_pending_verification" for row in promotion_ledger):
        errors.append("item-promotion: identity-only ledger attempted canonical/model promotion")
    source_records = {row["source_id"]: row for row in read_jsonl(root / "knowledge/sources/sources.jsonl")}
    registry_problems, registry_evidence = validate_registry(root, items, sets, source_records)
    errors.extend(registry_problems)
    evidence_groups = list(registry_evidence.items())
    errors.extend(validate_canonical_field_evidence(evidence_groups, items, sets, source_records))
    exact_english_decisions = evaluate_exact_english_eligibility(items, evidence_groups)
    for decision in exact_english_decisions:
        for issue in schema_validator.validate(decision, root / "schemas/review/canonical-exact-english-eligibility.schema.json"):
            errors.append(f"canonical-exact-english-eligibility:{decision['item_id']}:{issue}")
    expected_exact_english_ids = {row["item_id"] for row in exact_english_decisions if row["decision"] == "eligible"}
    actual_eligible_ids = {item_id for item_id, row in items.items() if row.get("model_feature_status") == "eligible"}
    if actual_eligible_ids != expected_exact_english_ids:
        errors.append("canonical-exact-english-eligibility: catalog eligible IDs differ from replayed exact-English evidence")
    market_claim_queue = read_jsonl(root / "data/review/market-claim-review.jsonl")
    expected_market_claim_queue = build_market_claim_queue(read_jsonl(root / "data/normalized/listings.jsonl"))
    if market_claim_queue != expected_market_claim_queue:
        errors.append("market-claim-review: committed queue differs from deterministic fixed selection")
    market_claim_gold = read_jsonl(root / "data/review/market-claim-gold.jsonl")
    errors.extend(f"market-claim-gold: {issue}" for issue in validate_gold_links(market_claim_queue, market_claim_gold))
    near_miss_queue = read_jsonl(root / "data/review/market-near-miss-field-review.jsonl")
    expected_near_miss_queue = build_market_near_miss_queue(read_jsonl(root / "data/normalized/listings.jsonl"))
    if near_miss_queue != expected_near_miss_queue:
        errors.append("market-near-miss: committed queue differs from deterministic single-hard-evidence selection")
    near_miss_evidence = read_jsonl(root / "data/review/market-near-miss-approved-evidence.jsonl")
    errors.extend(f"market-near-miss: {issue}" for issue in validate_approved_evidence(near_miss_queue, near_miss_evidence))
    errors.extend(
        f"market-audit: {issue}"
        for issue in audit_market_ledgers(
            root, market_claim_queue, market_claim_gold, near_miss_queue, near_miss_evidence,
            market_audit_authority_bundle, market_audit_authority_bundle_sha256,
        )
    )
    errors.extend(f"parser-gold: {issue}" for issue in audit_parser_gold(root, read_jsonl(root / "data/review/parser-gold/claims.jsonl"), parser_gold_authority_bundle, parser_gold_authority_bundle_sha256))
    for iid, row in items.items():
        eligible = row.get("model_feature_status") == "eligible"
        if eligible and (row.get("verification_status") != "verified" or row.get("evidence_tier") not in {"official_item_specific", "official_with_secondary"}):
            errors.append(f"item:{iid}: model eligible item lacks item-level verified evidence")
        if not eligible and row.get("model_feature_status") not in {"excluded_pending_verification", "excluded_non_valuation"}:
            errors.append(f"item:{iid}: invalid model feature status")
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
    legacy_history_rows = [row for row in read_jsonl(root / "data/curated/histories.jsonl") if "recovery" not in row]
    used_listing_ids = {listing_id for history in legacy_history_rows for listing_id in history.get("source_listing_ids", [])}
    recovery_decisions = read_jsonl(root / "data/review/strict-listing-recovery.jsonl")
    if len({row.get("listing_id") for row in recovery_decisions}) != len(recovery_decisions):
        errors.append("strict-recovery: duplicate listing decision")
    for decision in recovery_decisions:
        listing = normalized_by_id.get(decision.get("listing_id"))
        if listing is None:
            errors.append(f"strict-recovery:{decision.get('listing_id')}: dangling listing")
            continue
        predicates = strict_recovery_predicates(listing, used_listing_ids)
        if decision.get("review_status") == "approved":
            if predicates is None or decision.get("predicates") != predicates:
                errors.append(f"strict-recovery:{decision.get('listing_id')}: approved predicates no longer hold")
            elif not deduplication_is_approved(decision.get("deduplication")):
                errors.append(f"strict-recovery:{decision.get('listing_id')}: deduplication review missing or unapproved")
            elif decision.get("predicate_hash") != predicate_hash(listing, predicates, decision["deduplication"]):
                errors.append(f"strict-recovery:{decision.get('listing_id')}: predicate hash mismatch")
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
    # Modeling vectors are derived from the complete canonical item catalog.
    # A vector must not silently turn a missing mention into confirmed absence.
    vector_rows = read_jsonl(root / "data/modeling/account-item-vectors.jsonl")
    try:
        expected_catalog_provenance = catalog_provenance(root)
    except CatalogProvenanceError as exc:
        errors.append(f"item-vector: cannot build catalog provenance: {exc}")
        expected_catalog_provenance = None
    vectors_by_account: dict[str, dict[str, Any]] = {}
    for vector in vector_rows:
        account_id = vector.get("account_id", "unknown")
        if account_id in vectors_by_account:
            errors.append(f"item-vector: duplicate account_id={account_id}")
        vectors_by_account[account_id] = vector
        if expected_catalog_provenance is not None:
            try:
                validate_vector_catalog_provenance(vector, root)
            except CatalogProvenanceError as exc:
                errors.append(f"item-vector:{account_id}: {exc}")
        if vector.get("vector_id") != f"vector_{account_id}":
            errors.append(f"item-vector:{account_id}: invalid vector_id")
        state_rows = vector.get("item_states", [])
        item_ids = [state.get("item_id") for state in state_rows if isinstance(state, dict)]
        if len(item_ids) != len(set(item_ids)) or set(item_ids) != set(items):
            errors.append(f"item-vector:{account_id}: item states are not an exact canonical catalog")
        for state in state_rows:
            if not isinstance(state, dict):
                continue
            item = items.get(state.get("item_id"))
            if not item:
                continue
            eligible = item.get("model_feature_status") == "eligible" and item.get("verification_status") == "verified"
            if state.get("model_feature") != eligible:
                errors.append(f"item-vector:{account_id}:{state.get('item_id')}: model feature policy mismatch")
            if state.get("state") == "confirmed_missing" and state.get("evidence_state") == "unknown":
                errors.append(f"item-vector:{account_id}:{state.get('item_id')}: unknown cannot be confirmed missing")
    if set(vectors_by_account) != account_ids:
        errors.append("item-vector: account coverage differs from normalized profiles")
    # Formal price inputs are not hand-authored.  Rebuild all three outputs
    # with the production authorization evaluator intentionally absent; any
    # injected row, stale authorization, or edited exclusion must fail closed.
    actual_normal = read_jsonl(root / "data/modeling/price-cleaned-normal.jsonl")
    actual_urgent = read_jsonl(root / "data/modeling/price-cleaned-urgent.jsonl")
    actual_verified_sales = read_jsonl(root / "data/modeling/price-cleaned-verified-sales.jsonl")
    actual_exclusions = read_jsonl(root / "data/modeling/model-exclusions.jsonl")
    errors.extend(formal_price_rebuild_errors(
        read_jsonl(root / "data/comparables/accounts.jsonl"),
        actual_normal, actual_urgent, actual_verified_sales, actual_exclusions,
        root, market_authorization_authority_bundle, market_authorization_authority_bundle_sha256,
        market_authorization_statement, market_authorization_statement_sha256,
    ))
    # Clean model prices must be a strict, reproducible subset of vectors.
    for relative, expected_line in (
        ("data/modeling/price-cleaned-normal.jsonl", "normal_listing"),
        ("data/modeling/price-cleaned-urgent.jsonl", "urgent_sale"),
        ("data/modeling/price-cleaned-verified-sales.jsonl", "verified_sale"),
    ):
        seen_cleaned: set[str] = set()
        for row in read_jsonl(root / relative):
            cleaned_id = row.get("cleaned_price_id", "unknown")
            if cleaned_id in seen_cleaned:
                errors.append(f"{relative}: duplicate cleaned_price_id={cleaned_id}")
            seen_cleaned.add(cleaned_id)
            if row.get("account_id") not in vectors_by_account:
                errors.append(f"{relative}:{cleaned_id}: missing account item vector")
            if row.get("price_line") != expected_line or row.get("normalized_price_type") != expected_line:
                errors.append(f"{relative}:{cleaned_id}: price line mismatch")
            price, logged = row.get("selected_price_twd"), row.get("log_price_twd")
            if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 0 or not isinstance(logged, (int, float)) or abs(math.log(float(price)) - float(logged)) > 1e-9:
                errors.append(f"{relative}:{cleaned_id}: invalid price/log-price pair")
            if row.get("currency") != "TWD" or row.get("server") != "international":
                errors.append(f"{relative}:{cleaned_id}: non-TWD or non-international row")
    item_value_rows = read_jsonl(root / "data/modeling/item-value-table.jsonl")
    value_item_ids = [row.get("item_id") for row in item_value_rows]
    if len(value_item_ids) != len(set(value_item_ids)) or set(value_item_ids) != set(items):
        errors.append("item-value-table: item IDs are not an exact unique canonical catalog")
    for row in item_value_rows:
        item_id = row.get("item_id", "unknown")
        status = row.get("status")
        mean = row.get("mean_conditional_attribution")
        median = row.get("median_conditional_attribution")
        if status == "insufficient_support":
            if mean is not None or median is not None:
                errors.append(f"item-value-table:{item_id}: unsupported row has numeric attribution")
            continue
        if status != "eligible":
            errors.append(f"item-value-table:{item_id}: invalid attribution status")
            continue
        # Hash-shaped strings are not replayable attribution provenance.  A
        # future evaluator must verify explanations and fold refits before an
        # eligible conditional value can enter a formal release.
        errors.append(f"item-value-table:{item_id}: eligible attribution requires a replayable publication evaluator")
        if row.get("model_feature_eligible") is not True:
            errors.append(f"item-value-table:{item_id}: eligible attribution requires an eligible model feature")
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value)) for value in (mean, median)):
            errors.append(f"item-value-table:{item_id}: eligible attribution requires finite numerical estimates")
        provenance = row.get("explanation_provenance")
        if not isinstance(provenance, dict) or provenance.get("status") != "verified":
            errors.append(f"item-value-table:{item_id}: eligible attribution requires verified provenance")
        elif not all(isinstance(provenance.get(key), str) and provenance[key] for key in ("artifact_sha256", "model_sha256", "input_snapshot_sha256")):
            errors.append(f"item-value-table:{item_id}: eligible attribution has incomplete provenance hashes")
    # Model envelopes bind to exact local inputs. A trained status is accepted
    # only with the same conservative sample, grouped-CV and baseline gates used
    # by the runtime estimator.
    for relative in (
        "modeling/artifacts/elastic-net-normal_listing.json",
        "modeling/artifacts/elastic-net-urgent_sale.json",
        "modeling/artifacts/xgboost-normal_listing.json",
        "modeling/artifacts/xgboost-urgent_sale.json",
    ):
        artifact_path = root / relative
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        if expected_catalog_provenance is not None:
            try:
                validate_artifact_catalog_provenance(artifact, root)
            except CatalogProvenanceError as exc:
                errors.append(f"{relative}: {exc}")
        digest = hashlib.sha256()
        snapshot_valid = True
        for snapshot in sorted(artifact.get("input_snapshot_paths", [])):
            if not isinstance(snapshot, str):
                snapshot_valid = False; break
            candidate = (root / snapshot).resolve()
            if root.resolve() not in candidate.parents or not candidate.is_file():
                snapshot_valid = False; break
            name = candidate.relative_to(root.resolve()).as_posix()
            digest.update(name.encode("utf-8") + b"\0")
            digest.update(hashlib.sha256(candidate.read_bytes()).hexdigest().encode("ascii") + b"\n")
        expected_snapshot = artifact.get("input_snapshot_sha256")
        if not snapshot_valid or not isinstance(expected_snapshot, str) or digest.hexdigest().lower() != expected_snapshot.lower():
            errors.append(f"{relative}: input snapshot hash mismatch")
        if artifact.get("status") == "trained":
            training = artifact.get("training", {})
            rows = training.get("eligible_rows", training.get("records"))
            minimum = training.get("minimum_rows", training.get("min_required_records"))
            groups = training.get("group_count", training.get("unique_clusters"))
            folds = training.get("folds", training.get("outer_cv_folds"))
            mae = training.get("outer_cv_mae")
            baseline = training.get("baseline_mae", training.get("baseline_median_mae"))
            quality_ok = (
                training.get("threshold_met") is True and training.get("baseline_beaten") is True
                and isinstance(rows, int) and isinstance(minimum, int) and rows >= minimum
                and isinstance(groups, int) and groups >= 4 and isinstance(folds, int) and folds >= 2
                and isinstance(mae, (int, float)) and isinstance(baseline, (int, float)) and 0 < mae < baseline
            )
            if not quality_ok:
                errors.append(f"{relative}: trained artifact does not meet quality gates")
            publication = artifact.get("publication_gate", {})
            if publication.get("status") != "passed" or publication.get("independent_training_clusters", 0) < 300 or publication.get("time_forward_holdout_clusters", 0) < 100 or publication.get("time_forward_holdout") is not True:
                errors.append(f"{relative}: trained artifact has not passed the public time-forward holdout gate")
            if artifact.get("model_type") == "elastic_net":
                contract = artifact.get("prediction_contract", {})
                if contract.get("kind") != "additive_log_price" or not isinstance(contract.get("continuous", {}).get("means"), dict):
                    errors.append(f"{relative}: incomplete portable Elastic contract")
            elif artifact.get("model_type") == "xgboost":
                model_name, model_hash = artifact.get("model_file"), artifact.get("model_sha256")
                model_path = artifact_path.parent / model_name if isinstance(model_name, str) else None
                if not model_path or not model_path.is_file() or not isinstance(model_hash, str) or hashlib.sha256(model_path.read_bytes()).hexdigest().lower() != model_hash.lower():
                    errors.append(f"{relative}: XGBoost model hash mismatch")
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
    migration_summary = json.loads((root / "reports/migration/migration-summary.json").read_text(encoding="utf-8"))
    if len(verified_normalized) != migration_summary.get("verified_dates_in_normalized"):
        errors.append("date coverage: normalized verified-date count differs from migration summary")
    if len(verified_histories) != migration_summary.get("verified_dates_repaired_in_histories"):
        errors.append("date coverage: history verified-date count differs from migration summary")
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
    for key in ("source_listings", "normalized_listings"):
        if migration_summary.get(key) != formal_counts[key]:
            errors.append(f"migration summary mismatch: {key} summary={migration_summary.get(key)!r} actual={formal_counts[key]}")
    if migration_summary.get("migrated_histories", 0) + migration_summary.get("not_migrated_histories", 0) != migration_summary.get("legacy_histories"):
            errors.append("migration summary mismatch: migrated and unmigrated histories do not account for legacy histories")
    # P3.0 derived knowledge and publication-readiness reports are formal,
    # deterministic views over the canonical evidence and modeling inputs.
    # Reject hand-edited or stale copies rather than trusting their claims.
    historical_cost_path = root / "data/derived/official-historical-cost-references.jsonl"
    try:
        actual_historical_costs = read_jsonl(historical_cost_path)
        expected_historical_costs = build_historical_cost_references(root)
        if actual_historical_costs != expected_historical_costs:
            errors.append("historical cost references differ from deterministic rebuild")
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        errors.append(f"historical cost references: {exc}")
    publication_readiness_path = root / "reports/model-publication-readiness.json"
    try:
        actual_publication_readiness = json.loads(publication_readiness_path.read_text(encoding="utf-8"))
        expected_publication_readiness = build_publication_readiness(root)
        if actual_publication_readiness != expected_publication_readiness:
            errors.append("model publication readiness differs from deterministic rebuild")
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        errors.append(f"model publication readiness: {exc}")
    try:
        actual_dataset = json.loads((root / "reports/model-publication-dataset-manifest.json").read_text(encoding="utf-8"))
        actual_split = json.loads((root / "reports/model-publication-split.json").read_text(encoding="utf-8"))
        expected_dataset, expected_split = build_publication_dataset(root)
        if actual_dataset != expected_dataset:
            errors.append("model publication dataset manifest differs from deterministic rebuild")
        if actual_split != expected_split:
            errors.append("model publication split differs from deterministic rebuild")
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        errors.append(f"model publication dataset: {exc}")
    try:
        actual_evaluation = json.loads((root / "reports/model-publication-evaluation.json").read_text(encoding="utf-8"))
        if actual_evaluation != build_publication_evaluation(root):
            errors.append("model publication evaluation differs from deterministic rebuild")
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        errors.append(f"model publication evaluation: {exc}")
    try:
        actual_parser_coverage = json.loads((root / "reports/parser-knowledge-coverage.json").read_text(encoding="utf-8"))
        if actual_parser_coverage != build_parser_knowledge_coverage(root):
            errors.append("parser knowledge coverage differs from deterministic rebuild")
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        errors.append(f"parser knowledge coverage: {exc}")
    try:
        actual_parser_gold = json.loads((root / "reports/parser-gold-evaluation.json").read_text(encoding="utf-8"))
        expected_parser_gold = build_parser_gold_evaluation(root, parser_gold_replay_inputs, parser_gold_replay_inputs_sha256, parser_gold_authority_bundle, parser_gold_authority_bundle_sha256)
        if actual_parser_gold != expected_parser_gold:
            errors.append("parser gold evaluation differs from deterministic rebuild")
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        errors.append(f"parser gold evaluation: {exc}")
    for relative, builder, label in (
        ("reports/market-gold-evaluation.json", lambda: build_market_gold_evaluation(root, market_audit_authority_bundle, market_audit_authority_bundle_sha256), "market gold evaluation"),
        ("reports/catalog-completion.json", lambda: build_catalog_completion(root), "catalog completion"),
        ("reports/coverage/visual-evidence-capability.json", lambda: build_visual_evidence_coverage(root), "visual evidence capability"),
    ):
        try:
            actual = json.loads((root / relative).read_text(encoding="utf-8"))
            if actual != builder():
                errors.append(f"{label} differs from deterministic rebuild")
        except (ValueError, json.JSONDecodeError, OSError) as exc:
            errors.append(f"{label}: {exc}")
    try:
        parser_review_manifest = json.loads((root / "data/review/parser-gold/review-queue-manifest.json").read_text(encoding="utf-8"))
        errors.extend(f"parser review queue: {error}" for error in validate_parser_review_manifest(parser_review_manifest))
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        errors.append(f"parser review queue: {exc}")
    try:
        actual_completion = json.loads((root / "reports/completion-status.json").read_text(encoding="utf-8"))
        if actual_completion != build_completion_status(
            root,
            market_audit_authority_bundle,
            market_audit_authority_bundle_sha256,
        ):
            errors.append("completion status differs from deterministic rebuild")
    except (ValueError, json.JSONDecodeError, OSError) as exc:
        errors.append(f"completion status: {exc}")
    # Date invariant at every market stage.
    for rel in ("data/source/listings.jsonl", "data/normalized/listings.jsonl", "data/normalized/account-profiles.jsonl", "data/curated/histories.jsonl", "data/comparables/histories.jsonl", "data/comparables/accounts.jsonl", "data/review/market-near-miss-approved-evidence.jsonl"):
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
    executable_python = list((root / "tools").rglob("*.py")) + list((root / "modeling").rglob("*.py"))
    for path in executable_python:
        text = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        if name.name in {"requests", "socket", "http.client", "urllib.request", "aiohttp", "httpx"} or name.name.startswith(("requests.", "aiohttp.", "httpx.")):
                            errors.append(f"{path.relative_to(root)}:{node.lineno}: forbidden network import {name.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    imported = {name.name for name in node.names}
                    forbidden_from = module in {"requests", "socket", "http.client", "urllib.request", "aiohttp", "httpx"} or module.startswith(("requests.", "aiohttp.", "httpx.")) or (module == "urllib" and "request" in imported)
                    if forbidden_from:
                        errors.append(f"{path.relative_to(root)}:{node.lineno}: forbidden network import {module}:{sorted(imported)}")
        except SyntaxError as exc:
            errors.append(f"{path.relative_to(root)}: Python syntax error: {exc}")
        if path.name in {"validate.py", "build_file_inventory.py"}:
            continue
        for number, line in enumerate(text.splitlines(), 1):
            if forbidden_terms.search(line):
                errors.append(f"{path.relative_to(root)}:{number}: forbidden execution capability")
    return {"schema_version": "4.6-p3.4", "offline_only": True, "valid": not errors, "errors": errors, "warnings": warnings,
            "schema_records_checked": schema_checked, "formal_jsonl_coverage": {rel: (root / rel).exists() for rel in sorted(REQUIRED_FORMAL_JSONL)},
            "date_flow": {"verified_normalized_dates": len(verified_normalized), "verified_history_dates": len(verified_histories), "expected_normalized_dates": 28, "expected_history_dates": 5},
            "formal_counts": formal_counts,
            "counts": {kind: len(value) for kind, value in ids.items()}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate the offline P0 package")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--market-audit-authority-bundle", type=Path, help="external authority-bundle JSON; required only for nonempty market review ledgers")
    parser.add_argument("--market-audit-authority-bundle-sha256", help="expected SHA-256 for the injected external authority bundle")
    parser.add_argument("--market-authorization-authority-bundle", type=Path)
    parser.add_argument("--market-authorization-authority-bundle-sha256")
    parser.add_argument("--market-authorization-statement", type=Path)
    parser.add_argument("--market-authorization-statement-sha256")
    parser.add_argument("--parser-gold-authority-bundle", type=Path)
    parser.add_argument("--parser-gold-authority-bundle-sha256")
    parser.add_argument("--parser-gold-replay-inputs", type=Path)
    parser.add_argument("--parser-gold-replay-inputs-sha256")
    args = parser.parse_args()
    result = validate(
        args.root.resolve(), args.market_audit_authority_bundle, args.market_audit_authority_bundle_sha256,
        args.market_authorization_authority_bundle, args.market_authorization_authority_bundle_sha256,
        args.market_authorization_statement, args.market_authorization_statement_sha256,
        args.parser_gold_authority_bundle, args.parser_gold_authority_bundle_sha256,
        args.parser_gold_replay_inputs, args.parser_gold_replay_inputs_sha256,
    )
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    raise SystemExit(0 if result["valid"] else 1)


if __name__ == "__main__":
    main()
