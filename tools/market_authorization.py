"""Fail-closed authorization checks for market-model use."""
from __future__ import annotations

from typing import Any


def model_training_authorization_reasons(row: dict[str, Any], external_evaluator: Any = None) -> list[str]:
    """Explain why a market row cannot be used for modeling or estimation.

    This is intentionally stricter than JSON-schema shape validation.  A row
    must positively grant both model and comparable-estimation uses and bind
    them to replayable source and license evidence.
    """
    value = row.get("market_data_authorization")
    if not isinstance(value, dict):
        return ["market_data_authorization_missing"]
    reasons: list[str] = []
    if value.get("status") != "authorized_model_training":
        reasons.append("market_data_not_authorized_for_model_training")
    uses = value.get("allowed_uses")
    if not isinstance(uses, list) or not {"model_training", "comparable_estimation"}.issubset(uses):
        reasons.append("market_data_authorized_uses_incomplete")
    snapshot = value.get("source_snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("replayable") is not True or not isinstance(snapshot.get("sha256"), str) or len(snapshot["sha256"]) != 64:
        reasons.append("market_data_replay_evidence_missing")
    replay = value.get("replay_evidence")
    if not isinstance(replay, list) or not replay or any(not isinstance(item, dict) or not item.get("source_locator") or not isinstance(item.get("content_sha256"), str) or len(item["content_sha256"]) != 64 for item in replay):
        if "market_data_replay_evidence_missing" not in reasons:
            reasons.append("market_data_replay_evidence_missing")
    license_evidence = value.get("license_evidence")
    if not isinstance(license_evidence, dict) or license_evidence.get("verified") is not True or license_evidence.get("kind") not in {"explicit_data_license", "documented_data_consent"}:
        reasons.append("market_data_license_evidence_missing")
    if not value.get("authorization_record_id"):
        reasons.append("market_data_authorization_record_missing")
    # A syntactically complete JSON object is not a trust root.  P3.0 ships
    # no external authority bundle or detached authorization evaluator for
    # market-data licenses, so even a fully self-filled authorization remains
    # unusable.  This is deliberately independent of schema validation: the
    # release must not unlock training merely because a contributor typed
    # hashes, a locator, and ``verified: true`` into a record.
    externally_authorized = callable(external_evaluator) and external_evaluator(row) is True
    if value.get("status") == "authorized_model_training" and not externally_authorized:
        reasons.append("market_data_external_authorization_evaluator_required")
    return reasons
