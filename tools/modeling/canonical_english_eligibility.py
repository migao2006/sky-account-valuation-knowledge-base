"""Fail-closed eligibility for exact English canonical observations.

This is intentionally narrower than identity verification.  A model feature is
allowed only where the exact canonical English spelling is independently
replayed from both an official item-specific claim and a secondary identity
claim.  Chinese canonical labels and every alias remain discovery/review
tokens, never approved observation tokens under this policy.
"""
from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, Iterable

POLICY_VERSION = "canonical-exact-english-v1"
APPROVED_ITEM_IDS = frozenset({
    "item_aurora_cure_for_me_mask", "item_aurora_cure_for_me_outfit", "item_aurora_giving_in_cape", "item_aurora_to_the_love_outfit", "item_aurora_voice", "item_aurora_wings",
    "item_days_of_color_dark_rainbow_mask", "item_days_of_color_color_glam_cut",
    "item_days_of_color_color_bubble_machine",
    "item_days_of_sunlight_manta_float",
    "item_skyfest_jenova_fan", "item_skyfest_5th_anniversary_tshirt", "item_skyfest_star_jar", "item_skyfest_oreo_headband", "item_skyfest_wireframe_cape",
    "item_tournament_of_triumph_curls", "item_tournament_of_triumph_torch",
    "item_tournament_of_triumph_golden_garland", "item_tournament_of_triumph_tunic",
})
_SECONDARY_NAME_FIELDS = frozenset({"canonical_name_en", "vendor_item_name"})


def _parser_token(value: object) -> str:
    """The parser's canonical English comparison, without accepting aliases."""
    return re.sub(r"[^A-Za-z0-9]+", "", value.casefold()) if isinstance(value, str) else ""


def declared_model_feature_status(item_id: str) -> str:
    """Return the only status an apply contract may assign for this policy."""
    return "eligible" if item_id in APPROVED_ITEM_IDS else "excluded_pending_verification"


def evaluate(items: dict[str, dict[str, Any]], evidence_groups: Iterable[tuple[str, list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    """Return auditable decisions for the bounded policy declaration.

    The declaration is not self-attesting: every approved ID must have two
    distinct approved source lineages and byte-replayable ledger claims whose
    values exactly equal the catalog's English canonical spelling.
    """
    evidence_by_item: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for _cohort_id, rows in evidence_groups:
        for row in rows:
            if row.get("target_type") == "item":
                evidence_by_item[str(row.get("target_id"))].append(row)
    decisions: list[dict[str, Any]] = []
    for item_id in sorted(APPROVED_ITEM_IDS):
        item = items.get(item_id)
        reasons: list[str] = []
        name = item.get("canonical_name_en") if item else None
        if not item or item.get("verification_status") != "verified" or item.get("evidence_tier") != "official_with_secondary":
            reasons.append("catalog_item_not_verified_official_with_secondary")
        if not isinstance(name, str) or not name or not name.isascii():
            reasons.append("canonical_english_name_missing_or_non_ascii")
        rows = evidence_by_item.get(item_id, [])
        official = [row for row in rows if row.get("review_status") == "approved" and row.get("source_tier") == "official_item_specific" and row.get("field_path") == "canonical_name_en" and row.get("claim_value") == name]
        secondary = [row for row in rows if row.get("review_status") == "approved" and row.get("source_tier") == "secondary_reference" and row.get("field_path") in _SECONDARY_NAME_FIELDS and _parser_token(row.get("claim_value")) == _parser_token(name)]
        if not official:
            reasons.append("official_exact_canonical_english_evidence_missing")
        if not secondary:
            reasons.append("secondary_exact_canonical_english_evidence_missing")
        lineages = {row.get("source_lineage_id") for row in official + secondary if isinstance(row.get("source_lineage_id"), str)}
        if len(lineages) < 2:
            reasons.append("independent_source_lineages_missing")
        evidence_ids = sorted({str(row["evidence_id"]) for row in official + secondary if isinstance(row.get("evidence_id"), str)})
        decisions.append({
            "schema_version": POLICY_VERSION, "item_id": item_id,
            "canonical_name_en": name, "approved_observation_token": name if not reasons else None,
            "evidence_ids": evidence_ids, "source_lineage_ids": sorted(lineages),
            "decision": "eligible" if not reasons else "excluded_pending_verification",
            "reasons": sorted(reasons),
        })
    return decisions


def eligible_item_ids(items: dict[str, dict[str, Any]], evidence_groups: Iterable[tuple[str, list[dict[str, Any]]]]) -> set[str]:
    return {row["item_id"] for row in evaluate(items, evidence_groups) if row["decision"] == "eligible"}
