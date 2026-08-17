#!/usr/bin/env python3
"""Build a closed, offline reconciliation universe for the vendored catalog.

This is an accounting layer over the pinned vendor snapshot and its conservative
crosswalk.  It never promotes or edits canonical items or review candidates.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
from typing import Any

from compare_vendor_catalog import read_json, read_jsonl, verify_snapshot


CLASSIFICATION_BY_CROSSWALK = {
    "matched_canonical_name": "canonical_linked",
    "matched_alias": "canonical_linked",
    "matched_candidate_name": "candidate_linked",
    "ambiguous_canonical_match": "unmatched",
    "ambiguous_candidate_match": "unmatched",
    "unmatched_vendor_item": "unmatched",
    "excluded_non_collectible": "explicitly_excluded",
}

# `classification` remains the legacy reconciliation bucket so existing coverage
# counts stay comparable.  It is *not* a proof that a vendor type is outside the
# account-item scope.  `scope_disposition` is the auditable, row-level decision
# record and deliberately keeps type-only exclusions in human review.
SCOPE_BY_VENDOR_TYPE = {
    "WingBuff": (
        "progression_unlock",
        "vendor_type_wingbuff_requires_scope_review",
        "pinned_vendor_snapshot_type",
    ),
    "Spell": (
        "consumable_effect",
        "vendor_type_spell_requires_scope_review",
        "pinned_vendor_snapshot_type",
    ),
    "Quest": (
        "quest_record",
        "vendor_type_quest_requires_scope_review",
        "pinned_vendor_snapshot_type",
    ),
    "Special": (
        "vendor_special_needs_scope_review",
        "vendor_type_special_requires_scope_review",
        "pinned_vendor_snapshot_type",
    ),
}


def scope_disposition(vendor_item_type: str) -> tuple[str, str, str]:
    """Return the explicit scope account for one vendor row.

    The pinned source exposes type labels but does not contain a repository
    scope decision.  Therefore each non-collectible-looking type remains
    `needs_review`; in particular WingBuff and Spell are never silently marked
    `not_required` just because of their type.
    """
    return SCOPE_BY_VENDOR_TYPE.get(
        vendor_item_type,
        (
            "collectible_item",
            "vendor_type_not_type_only_excluded",
            "pinned_vendor_snapshot_and_crosswalk",
        ),
    )


def _pointer(document: object, locator: str) -> object:
    current = document
    for segment in locator.removeprefix("/").split("/") if locator != "/" else []:
        key = segment.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list) and key.isdigit() and int(key) < len(current):
            current = current[int(key)]
        else:
            raise ValueError("scope decision locator does not resolve")
    return current


def _valid_scope_approval(value: object, vendor_source_id: object) -> bool:
    if not isinstance(value, dict) or set(value) != {"evidence_source_id", "evidence_snapshot_path", "evidence_snapshot_sha256", "evidence_locator", "review_status"}:
        return False
    return (
        value.get("review_status") == "approved"
        and isinstance(value.get("evidence_source_id"), str)
        and value["evidence_source_id"] != vendor_source_id
        and isinstance(value.get("evidence_snapshot_path"), str)
        and value["evidence_snapshot_path"].startswith("data/source/research/")
        and ".." not in Path(value["evidence_snapshot_path"]).parts
        and isinstance(value.get("evidence_locator"), str)
        and value["evidence_locator"].startswith("/")
        and isinstance(value.get("evidence_snapshot_sha256"), str)
        and len(value["evidence_snapshot_sha256"]) == 64
    )


def validate_scope_accounting(rows: list[dict[str, Any]]) -> None:
    """Reject output that loses the reason/evidence for an excluded row."""
    required = {"scope_disposition", "disposition_reason", "evidence_basis", "review_status"}
    for row in rows:
        missing = required - set(row)
        if missing:
            raise ValueError(f"scope accounting missing {sorted(missing)!r} for {row.get('universe_id')!r}")
        if row["classification"] == "explicitly_excluded":
            if row["scope_disposition"] == "collectible_item":
                raise ValueError(f"excluded row lacks a non-collectible scope disposition: {row['universe_id']!r}")
            if not row["disposition_reason"] or not row["evidence_basis"]:
                raise ValueError(f"excluded row lacks disposition reason/evidence: {row['universe_id']!r}")
            if row["review_status"] == "approved":
                if not _valid_scope_approval(row.get("scope_approval"), row.get("source_id")):
                    raise ValueError(f"excluded row approval lacks independent scope evidence: {row['universe_id']!r}")
            elif row["review_status"] != "needs_review":
                raise ValueError(f"type-only excluded row is not reviewable: {row['universe_id']!r}")
        elif row["review_status"] == "approved" and not _valid_scope_approval(row.get("scope_approval"), row.get("source_id")):
            raise ValueError(f"approved scope lacks independent scope evidence: {row['universe_id']!r}")


def canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _resolve(root: Path, path: Path) -> Path:
    result = path.resolve() if path.is_absolute() else (root / path).resolve()
    if root not in result.parents and result != root:
        raise ValueError("path is outside repository root")
    return result


def _replay_scope_decisions(scope_decisions: list[dict[str, Any]], snapshot_by_pair: dict[tuple[Any, Any], dict[str, Any]], metadata: dict[str, Any], root: Path | None, sources: dict[str, dict[str, Any]] | None) -> dict[tuple[Any, Any], dict[str, Any]]:
    decisions_by_pair: dict[tuple[Any, Any], dict[str, Any]] = {}
    for decision in scope_decisions:
        pair = (decision.get("vendor_guid"), decision.get("vendor_item_id"))
        if pair in decisions_by_pair or pair not in snapshot_by_pair:
            raise ValueError(f"scope decision has invalid or duplicate vendor pair: {pair!r}")
        source_id, path_text = decision.get("evidence_source_id"), decision.get("evidence_snapshot_path")
        if not isinstance(source_id, str) or source_id == metadata["source_id"] or not sources or source_id not in sources:
            raise ValueError(f"scope decision lacks an independent registered source for {pair!r}")
        if not isinstance(path_text, str) or not path_text.startswith("data/source/research/") or root is None:
            raise ValueError(f"scope decision has unsafe snapshot path for {pair!r}")
        path = (root / path_text).resolve()
        if root.resolve() not in path.parents or not path.is_file():
            raise ValueError(f"scope decision snapshot is missing for {pair!r}")
        actual_hash = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        if decision.get("evidence_snapshot_sha256") != actual_hash:
            raise ValueError(f"scope decision snapshot hash mismatch for {pair!r}")
        locator = decision.get("evidence_locator")
        if not isinstance(locator, str) or not locator.startswith("/"):
            raise ValueError(f"scope decision has invalid locator for {pair!r}")
        try:
            claim = _pointer(json.loads(path.read_text(encoding="utf-8")), locator)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"scope decision locator cannot replay for {pair!r}") from exc
        if not isinstance(claim, dict) or claim.get("vendor_item_id") != pair[1] or claim.get("vendor_guid") != pair[0] or claim.get("scope_disposition") != decision.get("scope_disposition") or claim.get("review_status") != "approved":
            raise ValueError(f"scope decision locator claim does not bind vendor/disposition for {pair!r}")
        decisions_by_pair[pair] = decision
    return decisions_by_pair


def build_catalog_universe(snapshot: dict[str, Any], metadata: dict[str, Any], crosswalk: list[dict[str, Any]], scope_decisions: list[dict[str, Any]] | None = None, *, root: Path | None = None, sources: dict[str, dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return exactly one accounting row for every pinned vendor snapshot row."""
    snapshot_rows = snapshot.get("items")
    if not isinstance(snapshot_rows, list):
        raise ValueError("snapshot items must be a list")
    snapshot_by_pair = {(row.get("guid"), row.get("id")): row for row in snapshot_rows}
    if len(snapshot_by_pair) != len(snapshot_rows):
        raise ValueError("snapshot has duplicate vendor guid/item-id pairs")
    crosswalk_by_pair: dict[tuple[Any, Any], dict[str, Any]] = {}
    for row in crosswalk:
        pair = (row.get("vendor_guid"), row.get("vendor_item_id"))
        if pair in crosswalk_by_pair:
            raise ValueError(f"crosswalk has duplicate vendor pair: {pair!r}")
        if pair not in snapshot_by_pair:
            raise ValueError(f"crosswalk has a row absent from snapshot: {pair!r}")
        crosswalk_by_pair[pair] = row
    if set(crosswalk_by_pair) != set(snapshot_by_pair):
        missing = sorted(set(snapshot_by_pair) - set(crosswalk_by_pair))
        raise ValueError(f"crosswalk does not cover snapshot; missing={missing!r}")

    decisions_by_pair = _replay_scope_decisions(scope_decisions or [], snapshot_by_pair, metadata, root, sources)
    rows: list[dict[str, Any]] = []
    for pair, vendor in sorted(snapshot_by_pair.items(), key=lambda entry: (entry[1]["id"], entry[1]["guid"])):
        linked = crosswalk_by_pair[pair]
        status = linked.get("match_status")
        classification = CLASSIFICATION_BY_CROSSWALK.get(status)
        if classification is None:
            raise ValueError(f"unsupported crosswalk status for {pair!r}: {status!r}")
        if linked.get("snapshot_id") != metadata.get("snapshot_id") or linked.get("source_id") != metadata.get("source_id"):
            raise ValueError(f"crosswalk source mismatch for {pair!r}")
        if linked.get("vendor_name") != vendor.get("name") or linked.get("vendor_item_type") != vendor.get("type"):
            raise ValueError(f"crosswalk vendor fields mismatch for {pair!r}")
        canonical_ids = linked.get("canonical_item_ids", [])
        candidate_ids = linked.get("candidate_item_ids", [])
        if classification == "canonical_linked" and (len(canonical_ids) != 1 or candidate_ids):
            raise ValueError(f"canonical link is not unique for {pair!r}")
        if classification == "candidate_linked" and (len(candidate_ids) != 1 or canonical_ids):
            raise ValueError(f"candidate link is not unique for {pair!r}")
        if classification in {"unmatched", "explicitly_excluded"} and (canonical_ids or candidate_ids):
            raise ValueError(f"non-linked classification has targets for {pair!r}")
        disposition, disposition_reason, evidence_basis = scope_disposition(vendor["type"])
        decision = decisions_by_pair.get(pair)
        approved = False
        scope_approval = None
        if decision is not None:
            if decision.get("scope_disposition") != disposition:
                raise ValueError(f"scope decision disposition differs from vendor type for {pair!r}")
            scope_approval = {key: decision[key] for key in ("evidence_source_id", "evidence_snapshot_path", "evidence_snapshot_sha256", "evidence_locator", "review_status")}
            approved = _valid_scope_approval(scope_approval, metadata["source_id"])
            if not approved:
                raise ValueError(f"scope decision lacks independent approved evidence for {pair!r}")
        rows.append({
            "universe_id": f"catalog_vendor_{vendor['guid']}",
            "snapshot_id": metadata["snapshot_id"],
            "source_id": metadata["source_id"],
            "snapshot_sha256": metadata["snapshot_sha256"],
            "vendor_item_id": vendor["id"],
            "vendor_guid": vendor["guid"],
            "vendor_name": vendor["name"],
            "vendor_item_type": vendor["type"],
            "vendor_item_subtype": vendor.get("subtype"),
            "vendor_item_group": vendor.get("group"),
            "classification": classification,
            "crosswalk_match_status": status,
            "scope_disposition": disposition,
            "disposition_reason": disposition_reason,
            "evidence_basis": evidence_basis,
            "canonical_item_ids": canonical_ids,
            "candidate_item_ids": candidate_ids,
            "scope_approval": scope_approval,
            # Crosswalk matching is identity evidence, not scope evidence.  A
            # separate independent scope decision is required for approval.
            "review_status": "approved" if approved else "needs_review",
        })
        if scope_approval is None:
            rows[-1].pop("scope_approval")
    counts = collections.Counter(row["classification"] for row in rows)
    validate_scope_accounting(rows)
    type_counts = collections.Counter(row["vendor_item_type"] for row in rows)
    disposition_counts = collections.Counter(row["scope_disposition"] for row in rows)
    expected = sum(counts[key] for key in ("canonical_linked", "candidate_linked", "unmatched", "explicitly_excluded"))
    if expected != len(rows):
        raise AssertionError("catalog universe accounting is not closed")
    summary = {
        "snapshot_id": metadata["snapshot_id"],
        "source_id": metadata["source_id"],
        "snapshot_sha256": metadata["snapshot_sha256"],
        "vendor_item_count": len(rows),
        "canonical_linked_count": counts["canonical_linked"],
        "candidate_linked_count": counts["candidate_linked"],
        "unmatched_count": counts["unmatched"],
        "explicitly_excluded_count": counts["explicitly_excluded"],
        "vendor_item_type_counts": dict(sorted(type_counts.items())),
        "scope_disposition_counts": dict(sorted(disposition_counts.items())),
        "needs_scope_review_count": sum(row["review_status"] == "needs_review" for row in rows),
        "expected_count": expected,
        "reconciliation_status": "reconciled",
        "notes": "Each pinned vendor snapshot item has exactly one legacy reconciliation classification and one auditable scope disposition. Vendor type alone is not a completed scope decision: every row remains needs_review unless a separate approved decision cites an independent research snapshot. Candidate links remain review evidence and no canonical promotion is performed.",
    }
    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a closed offline reconciliation universe from a pinned vendor catalog.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--snapshot", type=Path, default=Path("data/source/vendor/skygame-data-1.3.4-items.json"))
    parser.add_argument("--metadata", type=Path, default=Path("data/source/vendor/skygame-data-1.3.4-metadata.json"))
    parser.add_argument("--crosswalk", type=Path, default=Path("data/review/skygame-data-1.3.4-crosswalk.jsonl"))
    parser.add_argument("--scope-decisions", type=Path, help="Optional independently evidenced scope decisions JSONL")
    parser.add_argument("--output", type=Path, default=Path("data/review/catalog-universe.jsonl"))
    parser.add_argument("--summary", type=Path, default=Path("data/review/catalog-universe-summary.json"))
    args = parser.parse_args()
    root = args.root.resolve()
    snapshot_path, metadata_path = _resolve(root, args.snapshot), _resolve(root, args.metadata)
    snapshot, metadata = verify_snapshot(root, snapshot_path, metadata_path)
    decision_path = _resolve(root, args.scope_decisions) if args.scope_decisions else root / "data/review/catalog-scope-decisions.jsonl"
    decisions = read_jsonl(decision_path)
    sources = {row["source_id"]: row for row in read_jsonl(root / "knowledge/sources/sources.jsonl")}
    rows, summary = build_catalog_universe(snapshot, metadata, read_jsonl(_resolve(root, args.crosswalk)), decisions, root=root, sources=sources)
    # Inputs are constrained to the repository; callers may direct deterministic
    # derived output to a temporary directory for verification.
    output = args.output.resolve() if args.output.is_absolute() else _resolve(root, args.output)
    summary_path = args.summary.resolve() if args.summary.is_absolute() else _resolve(root, args.summary)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows), encoding="utf-8", newline="\n")
    summary_path.write_bytes(canonical_json(summary))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
