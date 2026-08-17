"""Verify detached OpenSSH attestations for non-empty market-review ledgers.

The authority bundle is deliberately external to a release.  A release records
only anonymous reviewer IDs, public-key fingerprints, and detached signatures;
the caller must inject both the external bundle path and its SHA-256 digest.
This prevents a contributor from making up a local ``human_*`` identity to
unlock an otherwise review-only ledger.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any


NAMESPACE = "sky-market-audit-v1"
AUTHORITY_ENV = "SKY_MARKET_AUDIT_AUTHORITY_BUNDLE"
AUTHORITY_SHA_ENV = "SKY_MARKET_AUDIT_AUTHORITY_BUNDLE_SHA256"
ATTESTATIONS_REL = Path("data/review/market-audit/attestations.jsonl")
SIGNATURES_REL = Path("data/review/market-audit/signatures")
LEDGER_KINDS = {
    "market_claim_gold": ("gold_id", ("annotator_a", "annotator_b", "adjudicator")),
    "market_near_miss_approved_evidence": ("evidence_id", ("reviewer_a", "reviewer_b", "adjudicator")),
}


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}: JSONL row is not an object")
            rows.append(value)
    return rows


def _fingerprint(public_key: str) -> str | None:
    child = subprocess.run(["ssh-keygen", "-lf", "-"], input=public_key + "\n", text=True, capture_output=True, check=False)
    if child.returncode:
        return None
    fields = child.stdout.strip().split()
    return fields[1] if len(fields) >= 2 else None


def _review_identity(row: dict[str, Any], kind: str, role: str) -> str | None:
    if kind == "market_claim_gold":
        if role == "annotator_a": return row.get("annotator_a", {}).get("annotator_id")
        if role == "annotator_b": return row.get("annotator_b", {}).get("annotator_id")
        return row.get("adjudication", {}).get("adjudicator_id")
    reviewers = row.get("reviewers", [])
    if role == "reviewer_a" and len(reviewers) == 2 and isinstance(reviewers[0], dict): return reviewers[0].get("reviewer_id")
    if role == "reviewer_b" and len(reviewers) == 2 and isinstance(reviewers[1], dict): return reviewers[1].get("reviewer_id")
    return row.get("adjudication", {}).get("adjudicator_id")


def attestation_payload(ledger_kind: str, ledger_row: dict[str, Any], queue_row: dict[str, Any], attestation: dict[str, Any]) -> bytes:
    """Return the exact signed bytes, binding all ledger and queue fields."""
    signed_attestation = {key: value for key, value in attestation.items() if key != "payload_sha256"}
    return canonical_bytes({"contract": NAMESPACE, "ledger_kind": ledger_kind, "ledger": ledger_row, "queue": queue_row, "attestation": signed_attestation})


def _external_bundle(path_value: str | Path | None, expected_sha: str | None, root: Path) -> tuple[dict[str, dict[str, Any]] | None, list[str]]:
    errors: list[str] = []
    path_value = path_value or os.environ.get(AUTHORITY_ENV)
    expected_sha = expected_sha or os.environ.get(AUTHORITY_SHA_ENV)
    if not path_value or not expected_sha:
        return None, ["external authority bundle path and SHA-256 must be injected for nonempty ledger"]
    path = Path(path_value).expanduser().resolve()
    try:
        path.relative_to(root.resolve())
        return None, ["external authority bundle must be outside the release root"]
    except ValueError:
        pass
    if not path.is_file():
        return None, ["external authority bundle is missing"]
    actual = sha256_bytes(path.read_bytes())
    if actual != str(expected_sha).upper():
        return None, ["external authority bundle SHA-256 does not match injected digest"]
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, ["external authority bundle is not valid JSON"]
    if not isinstance(bundle, dict) or bundle.get("schema_version") != "sky-market-audit-authority-bundle-v1":
        return None, ["external authority bundle has unsupported schema_version"]
    revoked = set(bundle.get("revoked_fingerprints", []))
    records = bundle.get("authorities")
    if not isinstance(records, list):
        return None, ["external authority bundle has no authorities array"]
    authorities: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            errors.append("external authority record is not an object"); continue
        authority_id, public_key, roles = record.get("authority_id"), record.get("public_key"), record.get("roles")
        if not isinstance(authority_id, str) or not isinstance(public_key, str) or not isinstance(roles, list) or authority_id in authorities:
            errors.append("external authority record has invalid identity, key, roles, or duplicate ID"); continue
        fingerprint = _fingerprint(public_key)
        if not fingerprint or record.get("fingerprint") != fingerprint:
            errors.append(f"external authority {authority_id} fingerprint does not match public key"); continue
        if fingerprint in revoked:
            errors.append(f"external authority {authority_id} fingerprint is revoked"); continue
        authorities[authority_id] = record
    return (authorities if not errors else None), errors


def audit_market_ledgers(
    root: Path,
    claim_queue: list[dict[str, Any]], claim_gold: list[dict[str, Any]], near_queue: list[dict[str, Any]], near_evidence: list[dict[str, Any]],
    authority_bundle: str | Path | None = None, authority_bundle_sha256: str | None = None,
) -> list[str]:
    """Fail closed unless every nonempty-ledger row has three valid attestations."""
    ledgers = {"market_claim_gold": (claim_queue, claim_gold), "market_near_miss_approved_evidence": (near_queue, near_evidence)}
    if not any(rows for _, rows in ledgers.values()):
        return []
    authorities, errors = _external_bundle(authority_bundle, authority_bundle_sha256, root)
    if authorities is None:
        return errors
    try:
        attestations = read_jsonl(root / ATTESTATIONS_REL)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"market audit attestation ledger is unreadable: {exc}"]
    by_target: dict[tuple[str, str], list[dict[str, Any]]] = {}
    signature_paths: set[str] = set()
    attestation_ids: set[str] = set()
    for item in attestations:
        attestation_id = item.get("attestation_id")
        if not isinstance(attestation_id, str) or attestation_id in attestation_ids:
            errors.append("market audit attestation_id is missing or duplicated")
        attestation_ids.add(str(attestation_id))
        target = (str(item.get("ledger_kind")), str(item.get("ledger_id")))
        by_target.setdefault(target, []).append(item)
        signature_path = item.get("signature_file")
        if not isinstance(signature_path, str) or signature_path in signature_paths:
            errors.append("market audit signature_file is missing or reused")
        signature_paths.add(str(signature_path))
    for kind, (queue, rows) in ledgers.items():
        id_field, expected_roles = LEDGER_KINDS[kind]
        queue_by_id = {row.get("review_id"): row for row in queue}
        for row in rows:
            ledger_id = str(row.get(id_field))
            queue_row = queue_by_id.get(row.get("review_id"))
            if not queue_row:
                errors.append(f"{kind}:{ledger_id}: queue linkage is unavailable for audit")
                continue
            entries = by_target.get((kind, ledger_id), [])
            roles = [entry.get("role") for entry in entries]
            if len(entries) != 3 or set(roles) != set(expected_roles):
                errors.append(f"{kind}:{ledger_id}: requires exactly one attestation for each review role")
                continue
            fingerprints: set[str] = set()
            for entry in entries:
                role, authority_id, fingerprint = entry.get("role"), entry.get("authority_id"), entry.get("fingerprint")
                authority = authorities.get(authority_id) if isinstance(authority_id, str) else None
                if not authority or role not in authority.get("roles", []):
                    errors.append(f"{kind}:{ledger_id}:{role}: authority is not authorized for this role"); continue
                if authority.get("fingerprint") != fingerprint or _review_identity(row, kind, str(role)) != authority_id:
                    errors.append(f"{kind}:{ledger_id}:{role}: authority does not bind the ledger reviewer identity"); continue
                fingerprints.add(str(fingerprint))
                expected_payload = attestation_payload(kind, row, queue_row, entry)
                if entry.get("payload_sha256") != sha256_bytes(expected_payload):
                    errors.append(f"{kind}:{ledger_id}:{role}: payload hash does not bind canonical queue and ledger"); continue
                signature_value = entry.get("signature_file")
                signature = root / signature_value if isinstance(signature_value, str) else root
                try:
                    signature.resolve().relative_to((root / SIGNATURES_REL).resolve())
                except ValueError:
                    errors.append(f"{kind}:{ledger_id}:{role}: signature path escapes market-audit/signatures"); continue
                if not signature.is_file():
                    errors.append(f"{kind}:{ledger_id}:{role}: detached signature is missing"); continue
                with tempfile.TemporaryDirectory(prefix="sky-market-audit-") as temporary:
                    allowed = Path(temporary) / "allowed_signers"
                    allowed.write_text(f"{authority_id} {authority['public_key'].strip()}\n", encoding="utf-8", newline="\n")
                    child = subprocess.run(
                        ["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", authority_id, "-n", NAMESPACE, "-s", str(signature)],
                        input=expected_payload, capture_output=True, check=False,
                    )
                if child.returncode != 0:
                    errors.append(f"{kind}:{ledger_id}:{role}: ssh-keygen detached signature verification failed")
            if len(fingerprints) != 3:
                errors.append(f"{kind}:{ledger_id}: three review roles require distinct authority fingerprints")
    ledger_targets = {(kind, str(row.get(LEDGER_KINDS[kind][0]))) for kind, (_, rows) in ledgers.items() for row in rows}
    if set(by_target) - ledger_targets:
        errors.append("market audit attestation ledger references an absent market ledger row")
    return errors
