"""Replay an externally supplied, minimal-disclosure completed-sale archive.

This module deliberately has no network client and never writes the archive.
It validates only caller-injected files outside the release root.  A valid
result is an input to a future authorization evaluator; it does not itself
authorize a model row.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

NAMESPACE = "sky-verified-sale-receipt-v1"
ARCHIVE_SCHEMA = "verified-sale-receipt-archive-v1"
AUTHORITY_SCHEMA = "verified-sale-receipt-authority-bundle-v1"
SHA256 = re.compile(r"^[A-Fa-f0-9]{64}$")
OPAQUE = re.compile(r"^[a-z0-9_]{1,96}$")
PII_KEY = re.compile(r"(?:name|user|handle|social|uid|email|mail|phone|mobile|contact|login|payment|address|url|link|message|chat|receipt_image)", re.I)
EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
PHONE = re.compile(r"(?:\+\d[\d .()-]{6,}\d|\(?\d{2,4}\)?[ .-]\d{3,4}[ .-]\d{3,4})")


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _fingerprint(public_key: str) -> str | None:
    result = subprocess.run(["ssh-keygen", "-lf", "-"], input=public_key + "\n", text=True, capture_output=True, check=False)
    fields = result.stdout.strip().split()
    return fields[1] if len(fields) >= 2 else None


def _valid_time(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
        return True
    except ValueError:
        return False


def _pii(value: Any, path: str = "$") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            here = f"{path}.{key}"
            if PII_KEY.search(str(key)):
                found.append(here)
            found.extend(_pii(child, here))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_pii(child, f"{path}[{index}]"))
    elif isinstance(value, str) and (EMAIL.search(value) or PHONE.search(value) or value.startswith(("http://", "https://"))):
        found.append(path)
    return found


def signature_payload(archive_id: str, disclosure: dict[str, Any], assertion: dict[str, Any]) -> bytes:
    """The detached signature binds all sale semantics, not just a hash label."""
    fields = (
        "sale_event_id", "observation_id", "training_example_id", "training_example_digest",
        "observation_row_digest", "seller_identity_commitment_sha256", "sale_price_twd",
        "sale_completed_at", "currency", "server",
    )
    assertion_fields = ("assertion_id", "issuer_id", "evidence_class", "issued_at")
    return canonical_bytes({
        "contract": NAMESPACE, "archive_id": archive_id,
        "sale": {field: disclosure.get(field) for field in fields},
        "assertion": {field: assertion.get(field) for field in assertion_fields},
    })


def _verify_signature(authority: dict[str, Any], assertion: dict[str, Any], archive_id: str, disclosure: dict[str, Any]) -> bool:
    encoded = assertion.get("signature")
    if not isinstance(encoded, str):
        return False
    try:
        signature = base64.b64decode(encoded, validate=True)
    except ValueError:
        return False
    with tempfile.TemporaryDirectory(prefix="sky-verified-sale-receipt-") as temp:
        root = Path(temp)
        allowed = root / "allowed_signers"
        signature_file = root / "signature"
        allowed.write_text(f"{authority['issuer_id']} {authority['public_key'].strip()}\n", encoding="utf-8", newline="\n")
        signature_file.write_bytes(signature)
        result = subprocess.run(
            ["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", authority["issuer_id"], "-n", NAMESPACE, "-s", str(signature_file)],
            input=signature_payload(archive_id, disclosure, assertion), capture_output=True, check=False,
        )
    return result.returncode == 0


def _external(path_value: str | Path | None, digest: str | None, release_root: Path, label: str) -> tuple[dict[str, Any] | None, list[str]]:
    if not path_value or not digest:
        return None, [f"{label} path and SHA-256 must be injected"]
    path = Path(path_value).expanduser().resolve()
    if _inside(path, release_root):
        return None, [f"{label} must be outside the release root"]
    if not path.is_file():
        return None, [f"{label} is missing"]
    if sha256_bytes(path.read_bytes()) != str(digest).upper():
        return None, [f"{label} SHA-256 does not match injected bytes"]
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, [f"{label} is not valid JSON"]
    return (value if isinstance(value, dict) else None), ([] if isinstance(value, dict) else [f"{label} is not an object"])


@dataclass(frozen=True)
class ReceiptArchiveReplay:
    disclosures: tuple[dict[str, Any], ...]
    errors: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.errors


def disclosure_matches_authorized_sale(disclosure: dict[str, Any], expected: dict[str, Any]) -> bool:
    """Exact bridge for a future authorization factory.

    Receipt replay establishes that independent issuers signed a statement.
    The factory must still prove that statement belongs to its signed market
    observation/training example.  This helper intentionally returns false for
    missing fields, rather than accepting a partial comparison.
    """
    pairs = {
        "observation_id": "observation_id",
        "training_example_id": "training_example_id",
        "training_example_digest": "training_example_digest",
        "observation_row_digest": "observation_row_digest",
        "sale_price_twd": "price_twd",
        "currency": "currency",
        "server": "server",
        "seller_identity_commitment_sha256": "identity_mapping_commitment_sha256",
    }
    for receipt_field, expected_field in pairs.items():
        if receipt_field not in disclosure or expected_field not in expected:
            return False
        left, right = disclosure[receipt_field], expected[expected_field]
        if receipt_field.endswith("_digest") or receipt_field == "observation_row_digest":
            if not isinstance(left, str) or not isinstance(right, str) or left.upper() != right.upper():
                return False
        elif left != right:
            return False
    # A completed-sale assertion must bind an independently supplied completed
    # timestamp when the future observation contract carries one.
    completed_date = expected.get("completed_sale_date")
    if not isinstance(completed_date, str) or disclosure.get("sale_completed_at", "")[:10] != completed_date:
        return False
    return True


def verify_receipt_archive(
    release_root: Path,
    receipt_archive: str | Path | None = None,
    receipt_archive_sha256: str | None = None,
    authority_bundle: str | Path | None = None,
    authority_bundle_sha256: str | None = None,
    *, now: datetime | None = None,
) -> ReceiptArchiveReplay:
    """Verify external-only receipts and return minimal safe disclosure rows.

    No partial-success projection is returned.  One invalid disclosure blocks
    the entire archive, preventing a caller from accidentally accepting a
    hand-picked subset after a replay failure.
    """
    root = release_root.resolve()
    archive, errors = _external(receipt_archive, receipt_archive_sha256, root, "external receipt archive")
    authorities_bundle, bundle_errors = _external(authority_bundle, authority_bundle_sha256, root, "external receipt authority bundle")
    errors.extend(bundle_errors)
    if not archive or not authorities_bundle:
        return ReceiptArchiveReplay((), tuple(errors))
    if _pii(archive): errors.append("external receipt archive contains PII-like data")
    if _pii(authorities_bundle): errors.append("external receipt authority bundle contains PII-like data")
    if archive.get("schema_version") != ARCHIVE_SCHEMA: errors.append("external receipt archive has unsupported schema_version")
    if authorities_bundle.get("schema_version") != AUTHORITY_SCHEMA: errors.append("external receipt authority bundle has unsupported schema_version")
    if not isinstance(archive.get("archive_id"), str) or not OPAQUE.fullmatch(archive["archive_id"].removeprefix("archive_")) or not _valid_time(archive.get("issued_at")) or not _valid_time(archive.get("expires_at")):
        errors.append("external receipt archive identity or expiry is invalid")
    current = now or datetime.now(timezone.utc)
    try:
        if datetime.fromisoformat(str(archive.get("expires_at")).replace("Z", "+00:00")).astimezone(timezone.utc) <= current.astimezone(timezone.utc):
            errors.append("external receipt archive is expired")
    except ValueError:
        pass
    authorities: dict[str, dict[str, Any]] = {}
    authority_fingerprints: set[str] = set()
    revoked = set(authorities_bundle.get("revoked_fingerprints", []))
    raw_authorities = authorities_bundle.get("authorities")
    if not isinstance(raw_authorities, list):
        errors.append("external receipt authority bundle has no authorities array")
        raw_authorities = []
    for entry in raw_authorities:
        issuer = entry.get("issuer_id") if isinstance(entry, dict) else None
        key = entry.get("public_key") if isinstance(entry, dict) else None
        fingerprint = _fingerprint(key) if isinstance(key, str) else None
        if not isinstance(issuer, str) or issuer in authorities or fingerprint in authority_fingerprints or not isinstance(entry.get("independence_group"), str) or not OPAQUE.fullmatch(entry["independence_group"]) or fingerprint != entry.get("fingerprint") or fingerprint in revoked:
            errors.append("external receipt authority record has invalid, duplicate, or revoked identity")
            continue
        authorities[issuer] = entry
        authority_fingerprints.add(str(fingerprint))
    disclosures = archive.get("disclosures")
    if not isinstance(disclosures, list) or not disclosures:
        errors.append("external receipt archive has no disclosures")
        disclosures = []
    seen_events: set[str] = set(); seen_observations: set[str] = set(); accepted: list[dict[str, Any]] = []
    required = {"sale_event_id", "observation_id", "training_example_id", "training_example_digest", "observation_row_digest", "seller_identity_commitment_sha256", "sale_price_twd", "sale_completed_at", "currency", "server", "evidence_assertions", "disclosure_digest"}
    for position, disclosure in enumerate(disclosures, 1):
        label = f"receipt disclosure {position}"
        if not isinstance(disclosure, dict) or set(disclosure) != required:
            errors.append(f"{label}: exact disclosure allowlist violated"); continue
        digest_input = {key: value for key, value in disclosure.items() if key != "disclosure_digest"}
        if str(disclosure.get("disclosure_digest", "")).upper() != sha256_bytes(canonical_bytes(digest_input)):
            errors.append(f"{label}: disclosure digest does not bind bytes")
        sale_event = disclosure.get("sale_event_id"); observation = disclosure.get("observation_id")
        opaque_fields = ((sale_event, "sale_event_"), (observation, "observation_"), (disclosure.get("training_example_id"), "training_example_"))
        if any(not isinstance(value, str) or not value.startswith(prefix) or not OPAQUE.fullmatch(value.removeprefix(prefix)) for value, prefix in opaque_fields): errors.append(f"{label}: opaque identity is invalid")
        if sale_event in seen_events or observation in seen_observations: errors.append(f"{label}: sale event or observation is replayed")
        seen_events.add(str(sale_event)); seen_observations.add(str(observation))
        if (not isinstance(disclosure.get("sale_price_twd"), int) or isinstance(disclosure.get("sale_price_twd"), bool) or disclosure["sale_price_twd"] < 1 or not _valid_time(disclosure.get("sale_completed_at")) or disclosure.get("currency") != "TWD" or disclosure.get("server") != "international" or any(not isinstance(disclosure.get(field), str) or not SHA256.fullmatch(disclosure[field]) for field in ("training_example_digest", "observation_row_digest", "seller_identity_commitment_sha256", "disclosure_digest"))):
            errors.append(f"{label}: sale semantics are invalid")
        assertions = disclosure.get("evidence_assertions")
        if not isinstance(assertions, list) or len(assertions) < 2:
            errors.append(f"{label}: requires at least two independent evidence assertions"); continue
        issuers: set[str] = set(); groups: set[str] = set(); assertion_ids: set[str] = set(); evidence_classes: set[str] = set()
        for assertion in assertions:
            if not isinstance(assertion, dict) or set(assertion) != {"assertion_id", "issuer_id", "evidence_class", "issued_at", "payload_sha256", "signature"}:
                errors.append(f"{label}: assertion allowlist violated"); continue
            issuer = assertion.get("issuer_id"); authority = authorities.get(issuer)
            if not isinstance(assertion.get("assertion_id"), str) or not assertion["assertion_id"].startswith("assertion_") or assertion["assertion_id"] in assertion_ids or assertion.get("evidence_class") not in {"settlement_receipt", "independent_completion_attestation"} or not _valid_time(assertion.get("issued_at")) or authority is None:
                errors.append(f"{label}: assertion identity or authority invalid"); continue
            assertion_ids.add(assertion["assertion_id"]); issuers.add(issuer); groups.add(authority["independence_group"])
            evidence_classes.add(str(assertion["evidence_class"]))
            payload = signature_payload(archive["archive_id"], disclosure, assertion)
            if assertion.get("payload_sha256", "").upper() != sha256_bytes(payload) or not _verify_signature(authority, assertion, archive["archive_id"], disclosure):
                errors.append(f"{label}: assertion signature does not bind sale semantics")
        if len(issuers) < 2 or len(groups) < 2:
            errors.append(f"{label}: evidence issuers are not independent")
        if evidence_classes != {"settlement_receipt", "independent_completion_attestation"}:
            errors.append(f"{label}: requires both settlement receipt and independent completion evidence")
        if _pii(disclosure): errors.append(f"{label}: PII-like data is forbidden")
        accepted.append(disclosure)
    return ReceiptArchiveReplay(tuple(accepted) if not errors else (), tuple(errors))
