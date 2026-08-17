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
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from .canonical_evidence_registry import load_registry, validate_registry
except ImportError:  # direct script execution
    from canonical_evidence_registry import load_registry, validate_registry
from tools.modeling.visual_evidence_coverage import DEFAULT_ASSET_REGISTRY, actual_visual_item_ids

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_ITEM_EVIDENCE = frozenset({
    "canonical_name_en", "item_category", "source_type", "availability_status",
    "free_or_premium", "permanent_account_item",
})


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


def _evidence_rows(root: Path, items: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Read only successful, release-required replay cohorts.

    A planned cohort, a non-release cohort, or any failed verifier is not field
    evidence for completion.  This is stricter than merely finding a JSONL
    file at a registry-declared path.
    """
    sets = {row.get("set_id"): row for row in _jsonl(root / "knowledge/sets/item-sets.jsonl") if isinstance(row.get("set_id"), str)}
    sources = {row.get("source_id"): row for row in _jsonl(root / "knowledge/sources/sources.jsonl") if isinstance(row.get("source_id"), str)}
    item_map = {row.get("item_id"): row for row in items if isinstance(row.get("item_id"), str)}
    problems, ledgers = validate_registry(root, item_map, sets, sources)
    if problems:
        return [], len(problems)
    active_ids = {
        row.get("cohort_id") for row in load_registry(root)
        if row.get("review_status") == "approved" and row.get("release_required") is True
    }
    return [entry for cohort_id, ledger in ledgers.items() if cohort_id in active_ids for entry in ledger], 0


def build(root: Path) -> dict[str, Any]:
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
    evidence, invalid_evidence_paths = _evidence_rows(root, items)

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
    identity_by_item: set[str] = set()
    for row in evidence:
        if row.get("target_type") != "item" or row.get("review_status") != "approved":
            continue
        item_id, field = row.get("target_id"), row.get("field_path")
        if isinstance(item_id, str) and isinstance(field, str):
            evidence_by_item.setdefault(item_id, set()).add(field)
            if field == "canonical_name_en" and row.get("evidence_role") == "independent_identity" and row.get("source_tier") == "official_item_specific":
                identity_by_item.add(item_id)
    missing_fields = {
        str(row.get("item_id")): sorted(REQUIRED_ITEM_EVIDENCE - evidence_by_item.get(str(row.get("item_id")), set()))
        for row in items
        if REQUIRED_ITEM_EVIDENCE - evidence_by_item.get(str(row.get("item_id")), set())
    }
    missing_identity = sorted(str(row.get("item_id")) for row in items if row.get("item_id") not in identity_by_item)

    try:
        visual_verified_ids = actual_visual_item_ids(
            items, visual_rows, _jsonl(root / "data/curated/image-evidence.jsonl"),
            _jsonl(root / DEFAULT_ASSET_REGISTRY), root=root,
        )
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
        _check("catalog.required_field_evidence", not missing_fields and invalid_evidence_paths == 0,
               {"items_missing_required_fields": len(missing_fields), "missing_fields_by_item": missing_fields, "registry_replay_error_count": invalid_evidence_paths},
               "every canonical item has approved evidence from a release-required cohort whose verifier replays successfully", "data/review/canonical-evidence-cohorts.jsonl"),
        _check("catalog.independent_identity_evidence", not missing_identity,
               {"items_missing_official_identity": len(missing_identity), "item_ids": missing_identity},
               "every canonical item has approved official item-specific independent identity evidence", "data/review/canonical-evidence-cohorts.jsonl"),
        _check("catalog.visual_state_verified", not visual_failures,
               {"items_without_actual_visual_evidence": len(visual_failures), "item_ids": visual_failures, "visual_input_error_count": visual_input_errors},
               "every canonical item has a verified registered image asset or approved registry-backed detection; descriptions never satisfy this gate", "knowledge/visual-references/manifest.jsonl", "data/curated/visual-assets.jsonl", "data/curated/image-evidence.jsonl"),
    ]
    return {
        "schema_version": "1.0-p3.4",
        "catalog_status": "complete" if all(check["passed"] for check in checks) else "partial",
        "complete": all(check["passed"] for check in checks),
        "counts": {"universe": len(universe), "canonical_items": len(items), "candidates": len(candidates), "unresolved_review_scopes": len(unresolved), "unmapped_aliases": len(unmapped), "alias_conflicts": len(alias_conflicts), "source_scoped_unresolved": source_unresolved, "scope_review": scope_review},
        "checks": checks,
        "blocking_contract_ids": [check["contract_id"] for check in checks if not check["passed"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay catalog completion evidence")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(build(args.root), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
