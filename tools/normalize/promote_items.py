#!/usr/bin/env python3
"""Evaluate reviewed item evidence into a fail-closed promotion ledger.

This offline tool never edits ``knowledge/items/items.jsonl``.  A successful
row is a review-ready candidate-to-canonical mapping, not a canonical write.
Applying that mapping remains a separately reviewed migration step.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import Any

TEMPLATE_MARKER = "printable template"
TEMPLATE_ID_SUFFIX = re.compile(r"(?:_template|_token|_placeholder)(?:_\d+)?$")
REQUIRED_FIELDS = frozenset({"canonical_identity", "canonical_name_en", "item_category"})
MINIMUM_TIERS = {"official_item_specific"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalized(value: str) -> str:
    return re.sub(r"[^\w]+", "", unicodedata.normalize("NFKC", value).casefold(), flags=re.UNICODE)


def template_candidate(candidate: dict[str, Any], *, identity_only: bool = False) -> bool:
    # A printable source provenance alone is not an identity conflict when a
    # second pinned catalog independently agrees.  Synthetic template suffixes
    # are always a conflict; strict migration keeps the older provenance gate.
    if identity_only:
        return bool(TEMPLATE_ID_SUFFIX.search(candidate["candidate_item_id"]))
    return bool(TEMPLATE_ID_SUFFIX.search(candidate["candidate_item_id"])) or TEMPLATE_MARKER in str(candidate.get("reason", "")).casefold()


def aliases_in_conflict(candidate: dict[str, Any], conflicts: list[dict[str, Any]]) -> bool:
    name = normalized(candidate.get("candidate_name_en", ""))
    return any(
        any(target.get("target_id") == candidate["candidate_item_id"] for target in conflict.get("candidate_targets", []))
        or conflict.get("normalized_alias") == name
        for conflict in conflicts
    )


def claim_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest().upper()


def verify_replayable_sources(root: Path, evidence: list[dict[str, Any]], source_records: dict[str, dict[str, Any]]) -> set[str]:
    """Reject a ledger input whose claimed local source bytes no longer match."""
    verified: set[str] = set()
    for row in evidence:
        locator = row.get("source_locator")
        if not isinstance(locator, str) or "#" not in locator or locator.startswith("fixture://"):
            raise ValueError(f"evidence source locator is not replayable: {locator!r}")
        source = source_records.get(str(row.get("source_id")))
        if source is None:
            raise ValueError(f"evidence source_id is not canonical: {row.get('source_id')!r}")
        source_type = source.get("source_type")
        tier = row.get("source_tier")
        if tier in {"official_item_specific", "official_general"} and source_type not in {"official_site", "official_news", "official_support", "thatgamecompany"}:
            raise ValueError(f"official evidence tier disagrees with canonical source: {row.get('source_id')}")
        if tier == "maintained_community" and source_type not in {"community_wiki", "community_database"}:
            raise ValueError(f"community evidence tier disagrees with canonical source: {row.get('source_id')}")
        relative, _fragment = locator.split("#", 1)
        path = (root / relative).resolve()
        if root not in path.parents or not path.is_file():
            raise ValueError(f"evidence source locator is not a local repository file: {locator}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest().upper()
        if actual != row.get("source_snapshot_hash"):
            raise ValueError(f"evidence source snapshot hash mismatch: {locator}")
        verified.add(str(row.get("evidence_id")))
    return verified


def evaluate(candidates: list[dict[str, Any]], canonical_ids: set[str], conflicts: list[dict[str, Any]], evidence: list[dict[str, Any]], *, mode: str = "strict", verified_evidence_ids: set[str] | None = None) -> list[dict[str, Any]]:
    """Return deterministic review ledger.  Every non-approved fact rejects."""
    evidence_by_candidate: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in evidence:
        evidence_by_candidate[row.get("candidate_item_id", "")].append(row)
    rows: list[dict[str, Any]] = []
    vendor_correlation = mode == "vendor_correlation"
    verified_evidence_ids = verified_evidence_ids or set()
    for candidate in sorted(candidates, key=lambda row: row["candidate_item_id"]):
        candidate_id = candidate["candidate_item_id"]
        reasons: list[str] = []
        candidate_evidence = evidence_by_candidate[candidate_id]
        proposed_id = candidate_id
        if not vendor_correlation:
            reasons.append("strict_promotion_disabled_in_p2_1")
        if candidate_id in canonical_ids:
            reasons.append("candidate_id_already_canonical")
        if template_candidate(candidate, identity_only=vendor_correlation):
            required_template = [row for row in candidate_evidence if row.get("field_path") == "template_suffix_identity" and row.get("review_status") == "approved" and row.get("source_tier") in MINIMUM_TIERS]
            if not required_template:
                reasons.append("template_candidate_requires_official_suffix_identity_review")
        if aliases_in_conflict(candidate, conflicts):
            reasons.append("alias_conflict_requires_resolution")
        if not candidate_evidence:
            reasons.append("no_independent_item_evidence")
        evidence_ids = [str(row.get("evidence_id", "")) for row in candidate_evidence]
        if len(evidence_ids) != len(set(evidence_ids)):
            reasons.append("duplicate_evidence_id")
        if any(evidence_id not in verified_evidence_ids for evidence_id in evidence_ids):
            reasons.append("unverified_evidence_provenance")
        accepted_statuses = {"approved", "machine_correlated"} if vendor_correlation else {"approved"}
        if any(row.get("review_status") not in accepted_statuses for row in candidate_evidence):
            reasons.append("unapproved_or_unknown_evidence_present")
        if any(not isinstance(row.get("source_locator"), str) or not row["source_locator"] or not isinstance(row.get("source_snapshot_hash"), str) or len(row["source_snapshot_hash"]) != 64 or row.get("claim_hash") != claim_hash(row.get("claim_value")) for row in candidate_evidence):
            reasons.append("unreplayable_or_tampered_evidence")
        wrong_identity = [row for row in candidate_evidence if row.get("proposed_canonical_item_id") != proposed_id]
        if wrong_identity:
            reasons.append("evidence_proposed_id_mismatch")
        approved = [row for row in candidate_evidence if row.get("review_status") in accepted_statuses]
        fields = {row.get("field_path") for row in approved}
        missing_fields = sorted(REQUIRED_FIELDS - fields)
        if missing_fields:
            reasons.append("missing_required_fields:" + ",".join(missing_fields))
        accepted_tiers = {"maintained_community"} if vendor_correlation else MINIMUM_TIERS
        identity_sources = {row.get("source_id") for row in approved if row.get("field_path") == "canonical_identity" and row.get("source_tier") in accepted_tiers}
        if not identity_sources:
            reasons.append("no_vendor_identity_correlation" if vendor_correlation else "no_official_item_specific_identity")
        if any(row.get("field_path") == "canonical_identity" and normalized(str(row.get("claim_value", ""))) != normalized(candidate["candidate_name_en"]) for row in approved):
            reasons.append("canonical_identity_evidence_conflicts_with_candidate")
        independent_sources = {row.get("source_id") for row in approved if row.get("source_tier") in ({"maintained_community"} if vendor_correlation else {"official_item_specific", "official_general", "maintained_community"})}
        if not vendor_correlation and len(independent_sources) < 2:
            reasons.append("fewer_than_two_independent_sources")
        if vendor_correlation:
            for field in REQUIRED_FIELDS:
                field_tiers = {row.get("source_tier") for row in approved if row.get("field_path") == field}
                if field_tiers != {"unverified_template_seed", "maintained_community"}:
                    reasons.append("field_lacks_template_seed_and_vendor_correlation:" + field)
        if any(row.get("field_path") == "canonical_name_en" and normalized(str(row.get("claim_value", ""))) != normalized(candidate["candidate_name_en"]) for row in approved):
            reasons.append("canonical_name_evidence_conflicts_with_candidate")
        if any(row.get("field_path") == "item_category" and row.get("claim_value") != candidate["candidate_category"] for row in approved):
            reasons.append("category_evidence_conflicts_with_candidate")
        if not vendor_correlation and candidate.get("season_id") is not None:
            season_evidence = [row for row in approved if row.get("field_path") == "season_id"]
            if not season_evidence:
                reasons.append("missing_required_season_id_evidence")
            elif any(row.get("claim_value") != candidate["season_id"] for row in season_evidence):
                reasons.append("season_evidence_conflicts_with_candidate")
        decision = "vendor_correlated_template_candidate" if vendor_correlation and not reasons else "rejected_fail_closed"
        rows.append({
            "candidate_item_id": candidate_id,
            "proposed_canonical_item_id": proposed_id,
            "decision": decision,
            "reasons": sorted(reasons),
            "evidence_ids": sorted(evidence_ids),
            "canonical_write": "not_performed",
            "verification_status": "needs_review" if vendor_correlation else "unknown",
            "model_feature_status": "excluded_pending_verification",
            "unresolved_fields": ["canonical_identity", "season_id", "acquisition", "availability", "cost", "visual_reference"] if vendor_correlation else [],
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline fail-closed candidate item promotion gate.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--candidates", type=Path, default=Path("data/review/item-candidates.jsonl"))
    parser.add_argument("--canonical-items", type=Path, default=Path("knowledge/items/items.jsonl"))
    parser.add_argument("--alias-conflicts", type=Path, default=Path("data/review/alias-conflicts.jsonl"))
    parser.add_argument("--evidence", type=Path, default=Path("data/review/item-evidence.jsonl"))
    parser.add_argument("--mode", choices=["strict", "vendor_correlation"], default="strict")
    parser.add_argument("--output", type=Path, help="Optional ledger path; default is dry-run and writes nothing.")
    args = parser.parse_args()
    root = args.root.resolve()
    def path(value: Path) -> Path: return value.resolve() if value.is_absolute() else (root / value).resolve()
    candidates = read_jsonl(path(args.candidates))
    canonical_ids = {row["item_id"] for row in read_jsonl(path(args.canonical_items))}
    evidence = read_jsonl(path(args.evidence))
    source_records = {row["source_id"]: row for row in read_jsonl(root / "knowledge/sources/sources.jsonl")}
    verified_evidence_ids = verify_replayable_sources(root, evidence, source_records)
    if args.mode == "vendor_correlation":
        from build_item_evidence_bundle import build as build_identity_evidence, sha as source_sha
        expected = build_identity_evidence(candidates, read_jsonl(root / "data/review/skygame-data-1.3.4-item-evidence.jsonl"), source_sha(path(args.candidates).read_bytes()))
        if evidence != expected:
            raise SystemExit("identity-only evidence differs from deterministic pinned-source bundle")
    else:
        # P2.1 has no item-specific official source extractor.  The strict
        # reviewed-migration path therefore remains disabled rather than
        # trusting caller-authored evidence metadata.
        verified_evidence_ids = set()
    ledger = evaluate(candidates, canonical_ids, read_jsonl(path(args.alias_conflicts)), evidence, mode=args.mode, verified_evidence_ids=verified_evidence_ids)
    summary = {"dry_run": args.output is None, "mode": args.mode, "candidate_count": len(ledger), "vendor_correlated_template_candidates": sum(row["decision"] == "vendor_correlated_template_candidate" for row in ledger), "rejected_fail_closed": sum(row["decision"] == "rejected_fail_closed" for row in ledger), "canonical_writes": 0}
    if args.output:
        output = path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in ledger), encoding="utf-8", newline="\n")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
