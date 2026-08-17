#!/usr/bin/env python3
"""Replay the catalog-completion contract from repository evidence.

This deliberately proves neither an item nor a source correct by counting it.
``complete`` is available only when the pinned universe is closed and every
remaining canonical item has both approved field evidence and a verified visual
state.  It is therefore safe for this report to remain partial for a long time.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

try:
    from .canonical_evidence_registry import load_registry, validate_registry
except ImportError:  # direct script execution
    from canonical_evidence_registry import load_registry, validate_registry
from tools.modeling.visual_evidence_coverage import DEFAULT_ASSET_REGISTRY, complete_visual_state_item_ids

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_ITEM_EVIDENCE = frozenset({
    "canonical_name_en", "item_category", "source_type", "availability_status",
    "availability_history", "availability_as_of", "free_or_premium", "pass_required",
    "ultimate_reward", "set_membership", "first_release_date", "permanent_account_item",
})
FRESHNESS_DAYS = 366
ENTITY_FILES = {
    "seasons": ("knowledge/seasons/seasons.jsonl", "season_id"),
    "events": ("knowledge/events/events.jsonl", "event_id"),
    "ancestors": ("knowledge/seasons/ancestors.jsonl", "ancestor_id"),
    "sets": ("knowledge/sets/item-sets.jsonl", "set_id"),
    "availability_events": ("knowledge/acquisition/availability-events.jsonl", "availability_id"),
    "aliases": ("knowledge/aliases/item-aliases.jsonl", "alias_id"),
}
RIGHTS_SOURCE_REGISTRY = "data/review/official-rights-source-registry.jsonl"


def _json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _check(contract_id: str, passed: bool, actual: Any, requirement: str, *paths: str) -> dict[str, Any]:
    return {"contract_id": contract_id, "passed": passed, "actual": actual,
            "requirement": requirement, "evidence_paths": list(paths)}


def _safe_review_path(root: Path, value: object) -> Path | None:
    if not isinstance(value, str) or "\\" in value:
        return None
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts or not value.startswith("data/review/"):
        return None
    path = (root / pure).resolve()
    return path if root in path.parents else None


def _evidence_rows(root: Path, items: list[dict[str, Any]], review_authority_bundle: str | Path | None = None, review_authority_bundle_sha256: str | None = None) -> tuple[list[dict[str, Any]], int]:
    """Read only successful, release-required replay cohorts.

    A planned cohort, a non-release cohort, or any failed verifier is not field
    evidence for completion.  This is stricter than merely finding a JSONL
    file at a registry-declared path.
    """
    sets = {row.get("set_id"): row for row in _jsonl(root / "knowledge/sets/item-sets.jsonl") if isinstance(row.get("set_id"), str)}
    sources = {row.get("source_id"): row for row in _jsonl(root / "knowledge/sources/sources.jsonl") if isinstance(row.get("source_id"), str)}
    item_map = {row.get("item_id"): row for row in items if isinstance(row.get("item_id"), str)}
    problems, ledgers = validate_registry(root, item_map, sets, sources, review_authority_bundle, review_authority_bundle_sha256)
    if problems:
        return [], len(problems)
    active_ids = {
        row.get("cohort_id") for row in load_registry(root)
        if row.get("review_status") == "approved" and row.get("release_required") is True
    }
    return [entry for cohort_id, ledger in ledgers.items() if cohort_id in active_ids for entry in ledger], 0


def _fresh(value: object, cutoff: date) -> bool:
    try:
        observed = date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return False
    return cutoff - timedelta(days=FRESHNESS_DAYS) <= observed <= cutoff


def _entity_checks(root: Path, sources: dict[str, dict[str, Any]], cutoff: date) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    """Validate every knowledge entity family, rather than silently checking items only."""
    entities = {name: _jsonl(root / relative) for name, (relative, _identifier) in ENTITY_FILES.items()}
    missing_files = [relative for relative, _identifier in ENTITY_FILES.values() if not (root / relative).is_file()]
    empty_families = [name for name, rows in entities.items() if not rows]
    duplicate_or_missing: dict[str, int] = {}
    non_verified: dict[str, list[str]] = {}
    bad_sources: dict[str, list[str]] = {}
    stale: dict[str, list[str]] = {}
    for name, rows in entities.items():
        _relative, identifier = ENTITY_FILES[name]
        ids = [row.get(identifier) for row in rows]
        duplicate_or_missing[name] = len(ids) - len({value for value in ids if isinstance(value, str) and value})
        non_verified[name] = [str(row.get(identifier)) for row in rows if row.get("verification_status") != "verified"]
        bad_sources[name] = []
        stale[name] = []
        for row in rows:
            entity_id = str(row.get(identifier))
            source_ids = row.get("source_ids")
            # ``last_verified_at`` is required for completion even where an
            # older storage schema made it optional (notably aliases).  A
            # missing or malformed date is therefore stale, never timeless.
            if not _fresh(row.get("last_verified_at"), cutoff):
                stale[name].append(entity_id)
            if not isinstance(source_ids, list) or not source_ids or any(source_id not in sources for source_id in source_ids):
                bad_sources[name].append(entity_id)
                continue
            # A current entity record and every source it relies on must both be
            # within the declared research-cutoff window.
            if any(not _fresh(sources[source_id].get("retrieved_at"), cutoff) for source_id in source_ids):
                stale[name].append(entity_id)
    ids = {
        "item": {row.get("item_id") for row in _jsonl(root / "knowledge/items/items.jsonl")},
        "season": {row.get("season_id") for row in entities["seasons"]},
        "event": {row.get("event_id") for row in entities["events"]},
        "ancestor": {row.get("ancestor_id") for row in entities["ancestors"]},
        "set": {row.get("set_id") for row in entities["sets"]},
    }
    closure_errors: list[str] = []
    for row in entities["ancestors"]:
        if row.get("season_id") not in ids["season"]:
            closure_errors.append(f"ancestor:{row.get('ancestor_id')}:season")
    for row in entities["sets"]:
        for item_id in [*(row.get("required_item_ids") or []), *(row.get("optional_item_ids") or [])]:
            if item_id not in ids["item"]:
                closure_errors.append(f"set:{row.get('set_id')}:item")
    for row in entities["availability_events"]:
        if row.get("item_id") is not None and row.get("item_id") not in ids["item"]:
            closure_errors.append(f"availability:{row.get('availability_id')}:item")
        if row.get("event_id") is not None and row.get("event_id") not in ids["event"]:
            closure_errors.append(f"availability:{row.get('availability_id')}:event")
    for row in entities["aliases"]:
        target_type, target_id = row.get("target_type"), row.get("target_id")
        if target_type not in ids or target_id not in ids[target_type]:
            closure_errors.append(f"alias:{row.get('alias_id')}:target")
    checks = [
        _check("catalog.knowledge_entity_inventory_closure", not missing_files and not empty_families and not any(duplicate_or_missing.values()) and not closure_errors,
               {"missing_files": missing_files, "empty_families": empty_families, "duplicate_or_missing_ids": duplicate_or_missing, "relationship_errors": closure_errors},
               "season, event, ancestor, set, availability-event and alias inventories are nonempty, unique and reference only canonical entities; an empty family needs explicit reviewed universe evidence before it can ever be exempted", *[relative for relative, _identifier in ENTITY_FILES.values()]),
        _check("catalog.knowledge_entity_verified", not any(non_verified.values()),
               {"non_verified_by_entity": {name: values for name, values in non_verified.items() if values}},
               "every recorded non-item knowledge entity and alias has an approved verification state; needs_review is never completion evidence", *[relative for relative, _identifier in ENTITY_FILES.values()]),
        _check("catalog.knowledge_entity_source_and_freshness", not any(bad_sources.values()) and not any(stale.values()),
               {"source_binding_failures": {name: values for name, values in bad_sources.items() if values}, "stale_by_entity": {name: values for name, values in stale.items() if values}, "research_cutoff_date": cutoff.isoformat(), "max_age_days": FRESHNESS_DAYS},
               "every knowledge entity is source-bound to registered, current sources and is current as of the research cutoff", "knowledge/sources/sources.jsonl", *[relative for relative, _identifier in ENTITY_FILES.values()]),
    ]
    return checks, entities


def _trusted_rights_item_ids(root: Path, visual_rows: list[dict[str, Any]], evidence: list[dict[str, Any]], sources: dict[str, dict[str, Any]]) -> set[str]:
    """Only an item-bound, replayed ledger row can establish rights-unavailable.

    This deliberately rejects a generic, hand-authored rights JSON reused for
    several items: it must be bound to the item and to the exact source
    snapshot/locator in a successful release-required cohort.
    """
    approved_rights_sources = {
        (row.get("source_id"), row.get("source_lineage_id"))
        for row in _jsonl(root / RIGHTS_SOURCE_REGISTRY)
        if row.get("review_status") == "approved" and row.get("verifier_id") == "official_item_rights_v1"
    }
    rows_by_item: dict[str, list[dict[str, Any]]] = {}
    for row in evidence:
        if row.get("target_type") == "item" and row.get("field_path") == "visual_reference" and row.get("review_status") == "approved":
            rows_by_item.setdefault(str(row.get("target_id")), []).append(row)
    accepted: set[str] = set()
    claim_uses: dict[tuple[object, ...], set[str]] = {}
    for reference in visual_rows:
        rights = reference.get("rights_evidence")
        if reference.get("reference_mode") == "unavailable" and isinstance(reference.get("item_id"), str) and isinstance(rights, dict):
            key = (rights.get("snapshot_sha256"), rights.get("claim_locator"))
            claim_uses.setdefault(key, set()).add(reference["item_id"])
    for reference in visual_rows:
        if reference.get("reference_mode") != "unavailable" or reference.get("verification_status") != "verified":
            continue
        item_id, rights = reference.get("item_id"), reference.get("rights_evidence")
        if not isinstance(item_id, str) or not isinstance(rights, dict):
            continue
        source = sources.get(rights.get("source_id"))
        if (not isinstance(source, dict) or source.get("source_type") not in {"official_site", "official_news", "official_support", "thatgamecompany"}
                or (rights.get("source_id"), source.get("source_lineage_id")) not in approved_rights_sources):
            continue
        claim_key = (rights.get("snapshot_sha256"), rights.get("claim_locator"))
        if len(claim_uses.get(claim_key, set())) != 1:
            continue
        for row in rows_by_item.get(item_id, []):
            if (row.get("source_id") == rights.get("source_id") and row.get("source_lineage_id") == source.get("source_lineage_id")
                    and row.get("source_snapshot_path") == rights.get("snapshot_path") and row.get("source_snapshot_hash") == rights.get("snapshot_sha256")
                    and row.get("claim_locator") == rights.get("claim_locator")):
                accepted.add(item_id)
                break
    return accepted


def build(root: Path, review_authority_bundle: str | Path | None = None, review_authority_bundle_sha256: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    universe = _jsonl(root / "data/review/catalog-universe.jsonl")
    universe_summary = _json(root / "data/review/catalog-universe-summary.json", {})
    items = _jsonl(root / "knowledge/items/items.jsonl")
    candidates = _jsonl(root / "data/review/item-candidates.jsonl")
    unresolved = _jsonl(root / "reports/coverage/unresolved-items.jsonl")
    unmapped = _jsonl(root / "reports/coverage/unmapped-aliases.jsonl")
    alias_conflicts = _jsonl(root / "data/review/alias-conflicts.jsonl")
    source_summary = _json(root / "data/normalized/source-scoped-item-identities-summary.json", {})
    visual_rows = _jsonl(root / "knowledge/visual-references/manifest.jsonl")
    sources = {row.get("source_id"): row for row in _jsonl(root / "knowledge/sources/sources.jsonl") if isinstance(row.get("source_id"), str)}
    package_manifest = _json(root / "manifest.json", {})
    evidence, invalid_evidence_paths = _evidence_rows(root, items, review_authority_bundle, review_authority_bundle_sha256)
    try:
        cutoff = date.fromisoformat(str(package_manifest.get("research_cutoff_date")))
    except (TypeError, ValueError):
        cutoff = date.min
    entity_checks, entities = _entity_checks(root, sources, cutoff)

    universe_ids = [row.get("universe_id") for row in universe]
    expected = universe_summary.get("expected_count", universe_summary.get("vendor_item_count"))
    closed_universe = (
        bool(universe)
        and isinstance(expected, int)
        and len(universe) == expected
        and len(universe_ids) == len(set(universe_ids))
        and universe_summary.get("reconciliation_status") == "reconciled"
        and universe_summary.get("vendor_item_count") == len(universe)
        and all(row.get("classification") in {"canonical_linked", "candidate_linked", "unmatched", "explicitly_excluded"} for row in universe)
    )
    scope_review = sum(row.get("review_status") == "needs_review" for row in universe)
    source_unresolved = source_summary.get("unresolved_count")
    if not isinstance(source_unresolved, int):
        source_unresolved = None

    canonical_ids = [row.get("item_id") for row in items]
    non_verified = sorted(str(row.get("item_id")) for row in items if row.get("verification_status") != "verified")
    all_canonical_verified = bool(items) and len(canonical_ids) == len(set(canonical_ids)) and not non_verified

    evidence_by_item: dict[str, set[str]] = {}
    official_identity_by_item: set[str] = set()
    secondary_identity: dict[str, list[dict[str, Any]]] = {}
    for row in evidence:
        if row.get("target_type") != "item" or row.get("review_status") != "approved":
            continue
        item_id, field = row.get("target_id"), row.get("field_path")
        if isinstance(item_id, str) and isinstance(field, str):
            evidence_by_item.setdefault(item_id, set()).add(field)
            if field == "canonical_name_en" and row.get("evidence_role") == "independent_identity" and row.get("source_tier") == "official_item_specific":
                official_identity_by_item.add(item_id)
            elif field == "canonical_name_en" and row.get("evidence_role") == "independent_identity" and row.get("source_tier") == "secondary_reference":
                secondary_identity.setdefault(item_id, []).append(row)
    missing_fields = {
        str(row.get("item_id")): sorted(REQUIRED_ITEM_EVIDENCE - evidence_by_item.get(str(row.get("item_id")), set()))
        for row in items
        if REQUIRED_ITEM_EVIDENCE - evidence_by_item.get(str(row.get("item_id")), set())
    }
    evidence_source_failures = 0
    for row in evidence:
        source = sources.get(row.get("source_id"))
        if (not isinstance(source, dict) or row.get("source_lineage_id") != source.get("source_lineage_id")
                or not _fresh(source.get("retrieved_at"), cutoff)):
            evidence_source_failures += 1
    secondary_identity_by_item: set[str] = set()
    for item_id, rows in secondary_identity.items():
        qualifying: dict[str, tuple[str, str]] = {}
        for row in rows:
            source = sources.get(row.get("source_id"))
            try:
                retrieved = date.fromisoformat(str(source.get("retrieved_at"))) if isinstance(source, dict) else date.min
            except ValueError:
                continue
            lineage = row.get("source_lineage_id")
            source_url = source.get("url") if isinstance(source, dict) else None
            host = urlparse(source_url).hostname.casefold() if isinstance(source_url, str) and urlparse(source_url).hostname else ""
            if (isinstance(lineage, str) and isinstance(row.get("source_id"), str) and isinstance(source, dict)
                    and source.get("source_lineage_id") == lineage and host
                    and source.get("evidence_level") == "community_cross_checked"
                    and cutoff - timedelta(days=FRESHNESS_DAYS) <= retrieved <= cutoff):
                qualifying[lineage] = (row["source_id"], host)
        if len(qualifying) >= 2 and len({value[0] for value in qualifying.values()}) >= 2 and len({value[1] for value in qualifying.values()}) >= 2:
            secondary_identity_by_item.add(item_id)
    identity_by_item = official_identity_by_item | secondary_identity_by_item
    missing_identity = sorted(str(row.get("item_id")) for row in items if row.get("item_id") not in identity_by_item)

    try:
        visual_verified_ids = complete_visual_state_item_ids(
            items, visual_rows, _jsonl(root / "data/curated/image-evidence.jsonl"),
            _jsonl(root / DEFAULT_ASSET_REGISTRY), root=root,
        )
        # The visual helper validates asset-backed references.  The completion
        # contract applies a stricter rule to rights-unavailable records: they
        # require an item-specific successful-cohort ledger binding too.
        unavailable_ids = {str(row.get("item_id")) for row in visual_rows if row.get("reference_mode") == "unavailable"}
        visual_verified_ids -= unavailable_ids - _trusted_rights_item_ids(root, visual_rows, evidence, sources)
        visual_input_errors = 0
    except (OSError, ValueError, json.JSONDecodeError):
        visual_verified_ids, visual_input_errors = set(), 1
    visual_failures = sorted(str(row.get("item_id")) for row in items if row.get("item_id") not in visual_verified_ids)

    checks = [
        _check("catalog.closed_universe", closed_universe,
               {"rows": len(universe), "expected": expected, "reconciliation_status": universe_summary.get("reconciliation_status"), "duplicate_ids": len(universe_ids) - len(set(universe_ids))},
               "a reconciled, duplicate-free universe accounts for every pinned source observation", "data/review/catalog-universe.jsonl", "data/review/catalog-universe-summary.json"),
        _check("catalog.scope_review_zero", scope_review == 0,
               {"needs_review": scope_review, "summary_needs_scope_review": universe_summary.get("needs_scope_review_count")},
               "every source-universe row has a final evidence-backed scope decision", "data/review/catalog-universe.jsonl", "data/review/catalog-universe-summary.json"),
        _check("catalog.unresolved_zero", not unresolved and source_unresolved == 0,
               {"review_scopes": len(unresolved), "source_references": source_unresolved},
               "no catalog review scope or source-scoped reference remains unresolved", "reports/coverage/unresolved-items.jsonl", "data/normalized/source-scoped-item-identities-summary.json"),
        _check("catalog.candidates_zero", not candidates, len(candidates),
               "no candidate identity remains outside the canonical catalog", "data/review/item-candidates.jsonl"),
        _check("catalog.unmapped_alias_zero", not unmapped and not alias_conflicts,
               {"unmapped": len(unmapped), "conflicts": len(alias_conflicts)},
               "no unmapped or conflicting alias remains", "reports/coverage/unmapped-aliases.jsonl", "data/review/alias-conflicts.jsonl"),
        _check("catalog.all_canonical_verified", all_canonical_verified,
               {"canonical_items": len(items), "non_verified_count": len(non_verified), "non_verified_item_ids": non_verified},
               "every canonical item is independently verified", "knowledge/items/items.jsonl"),
        _check("catalog.required_field_evidence", not missing_fields and invalid_evidence_paths == 0 and evidence_source_failures == 0,
               {"items_missing_required_fields": len(missing_fields), "missing_fields_by_item": missing_fields, "registry_replay_error_count": invalid_evidence_paths, "unregistered_or_stale_evidence_sources": evidence_source_failures, "research_cutoff_date": cutoff.isoformat()},
               "every canonical item has fresh approved evidence from a release-required cohort whose verifier replays successfully and whose registered source lineage matches the ledger", "data/review/canonical-evidence-cohorts.jsonl", "knowledge/sources/sources.jsonl"),
        _check("catalog.independent_identity_evidence", not missing_identity,
               {"items_missing_independent_identity": len(missing_identity), "official_identity_count": len(official_identity_by_item), "two_secondary_identity_count": len(secondary_identity_by_item), "item_ids": missing_identity},
               "every canonical item has official item-specific identity evidence or two independent, current, cross-checked secondary sources", "data/review/canonical-evidence-cohorts.jsonl", "knowledge/sources/sources.jsonl"),
        _check("catalog.visual_state_verified", not visual_failures,
               {"items_without_complete_visual_state": len(visual_failures), "item_ids": visual_failures, "visual_input_error_count": visual_input_errors},
               "every canonical item has actual registered visual evidence or a verified source-backed rights-unavailable state; descriptions alone never satisfy this gate", "knowledge/visual-references/manifest.jsonl", "data/curated/visual-assets.jsonl", "data/curated/image-evidence.jsonl"),
        *entity_checks,
    ]
    return {
        "schema_version": "1.5-p4.3",
        "catalog_status": "complete" if all(check["passed"] for check in checks) else "partial",
        "complete": all(check["passed"] for check in checks),
        "counts": {"universe": len(universe), "canonical_items": len(items), "candidates": len(candidates), "unresolved_review_scopes": len(unresolved), "unmapped_aliases": len(unmapped), "alias_conflicts": len(alias_conflicts), "source_scoped_unresolved": source_unresolved, "scope_review": scope_review, **{name: len(rows) for name, rows in entities.items()}},
        "checks": checks,
        "blocking_contract_ids": [check["contract_id"] for check in checks if not check["passed"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay catalog completion evidence")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--canonical-review-authority-bundle")
    parser.add_argument("--canonical-review-authority-bundle-sha256")
    args = parser.parse_args()
    payload = json.dumps(build(args.root, args.canonical_review_authority_bundle, args.canonical_review_authority_bundle_sha256), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
