"""Offline image-evidence contract helpers.

This is deliberately a storage/validation interface, not an OCR or vision
execution engine. Text OCR observations and icon/item observations are different rows.
"""
from __future__ import annotations

import hashlib
from typing import Any

IMAGE_ROLES = {"listing_post", "wardrobe", "season_progress", "resources", "bindings", "map_completion"}
UI_LANGUAGES = {"zh_tw", "zh_cn", "en", "ja", "ko", "other", "unknown"}
METHODS = {"manual", "ocr_text", "icon_match", "imported_annotation"}
EVIDENCE_STATES = {"confirmed", "claimed", "unknown", "conflicting"}
REVIEW_STATES = {"approved", "needs_review", "rejected", "unknown"}


def image_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def validate_evidence(row: dict[str, Any], canonical_item_ids: set[str] | None = None) -> list[str]:
    """Return errors; never accept OCR text or PII in an evidence row."""
    errors: list[str] = []
    required = ("case_id", "image_sha256", "image_role", "ui_language", "capture_date", "detected_item_id", "bounding_box", "recognition_method", "confidence", "evidence_state", "conflict", "review_status", "wardrobe_coverage")
    for key in required:
        if key not in row:
            errors.append(f"missing:{key}")
    digest = row.get("image_sha256", "")
    if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest.lower()):
        errors.append("invalid:image_sha256")
    if row.get("image_role") not in IMAGE_ROLES:
        errors.append("invalid:image_role")
    if row.get("ui_language") not in UI_LANGUAGES:
        errors.append("invalid:ui_language")
    if row.get("recognition_method") not in METHODS:
        errors.append("invalid:recognition_method")
    if row.get("evidence_state") not in EVIDENCE_STATES:
        errors.append("invalid:evidence_state")
    if row.get("review_status") not in REVIEW_STATES:
        errors.append("invalid:review_status")
    confidence = row.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= confidence <= 1:
        errors.append("invalid:confidence")
    item_id = row.get("detected_item_id")
    if item_id is not None:
        if not isinstance(item_id, str) or not item_id.startswith("item_"):
            errors.append("invalid:detected_item_id")
        elif canonical_item_ids is not None and item_id not in canonical_item_ids:
            errors.append("unknown:detected_item_id")
    bbox = row.get("bounding_box")
    if bbox is not None:
        if not isinstance(bbox, dict) or set(bbox) != {"x", "y", "width", "height"} or any(not isinstance(bbox[k], (int, float)) or not 0 <= bbox[k] <= 1 for k in bbox):
            errors.append("invalid:bounding_box")
        elif bbox["x"] + bbox["width"] > 1 or bbox["y"] + bbox["height"] > 1:
            errors.append("invalid:bounding_box_bounds")
    # The raw OCR transcript and identity fields are prohibited from canonical evidence.
    prohibited = {"ocr_text", "raw_ocr", "player_name", "account_name", "uid", "phone", "email", "url", "source_url", "image_path"}
    for key in prohibited & set(row):
        errors.append(f"prohibited:{key}")
    if row.get("recognition_method") == "ocr_text" and item_id:
        errors.append("invalid:ocr_text_cannot_claim_item")
    if row.get("wardrobe_coverage") not in {"complete", "partial", "unknown"}:
        errors.append("invalid:wardrobe_coverage")
    overlaps = row.get("overlaps_detection_ids", [])
    if not isinstance(overlaps, list) or any(not isinstance(value, str) or not value.startswith("detection_") for value in overlaps):
        errors.append("invalid:overlaps_detection_ids")
    return errors
