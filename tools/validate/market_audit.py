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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


NAMESPACE = "sky-market-audit-v1"
V2_NAMESPACE = "sky-market-audit-v2"
AUTHORITY_ENV = "SKY_MARKET_AUDIT_AUTHORITY_BUNDLE"
AUTHORITY_SHA_ENV = "SKY_MARKET_AUDIT_AUTHORITY_BUNDLE_SHA256"
ATTESTATIONS_REL = Path("data/review/market-audit/attestations.jsonl")
SIGNATURES_REL = Path("data/review/market-audit/signatures")
LEDGER_KINDS = {
    "market_claim_gold": ("gold_id", ("annotator_a", "annotator_b", "adjudicator")),
    "market_near_miss_approved_evidence": ("evidence_id", ("reviewer_a", "reviewer_b", "adjudicator")),
}
KEYED_RECEIPT_REL = Path("data/review/market-keyed-finalization-receipt.json")


def keyed_market_finalization_errors(
    root: Path, claim_gold: list[dict[str, Any]],
    custodian_authority_bundle: str | Path | None = None, custodian_authority_bundle_sha256: str | None = None,
    review_authority_bundle: str | Path | None = None, review_authority_bundle_sha256: str | None = None,
    contract: str | Path | None = None, assignment_ledger: str | Path | None = None,
    decisions_a: str | Path | None = None, decisions_b: str | Path | None = None, adjudications: str | Path | None = None,
    resolution_map: str | Path | None = None, candidate: str | Path | None = None,
    candidate_signature: str | Path | None = None, binding_signature: str | Path | None = None,
) -> tuple[list[str], dict[str, Any] | None]:
    """Replay the external keyed finalization without exposing its private map.

    The finalizer owns protocol validation; this adapter only supplies the
    externally injected artifacts and compares the public release bytes.
    """
    required = (custodian_authority_bundle, custodian_authority_bundle_sha256, review_authority_bundle,
        review_authority_bundle_sha256, contract, assignment_ledger, decisions_a, decisions_b,
        adjudications, resolution_map, candidate, candidate_signature, binding_signature)
    if not all(required):
        return ["nonempty keyed market gold requires every external keyed finalization input"], None
    try:
        from tools.market_review.finalization import (
            BINDING_NAMESPACE, FINALIZATION_NAMESPACE, _verify, build_candidate_bundle,
            load_review_authorities, verify_finalization,
        )
        from tools.market_review.keyed_custodian import _outside, load_authorities
        labels = ("custodian contract", "assignment ledger", "annotator A decisions", "annotator B decisions",
            "adjudications", "private resolution map", "signed candidate", "candidate signature", "binding signature")
        paths = [_outside(Path(value), root, label) for value, label in zip(
            (contract, assignment_ledger, decisions_a, decisions_b, adjudications, resolution_map, candidate, candidate_signature, binding_signature), labels)]
        rows = read_jsonl(Path(resolution_map))
        verified = verify_finalization(paths[0], paths[1], paths[2], paths[3], paths[4], Path(custodian_authority_bundle), str(custodian_authority_bundle_sha256), Path(review_authority_bundle), str(review_authority_bundle_sha256), root)
        contract_value = json.loads(paths[0].read_text(encoding="utf-8"))
        rebuilt = build_candidate_bundle(verified, rows, contract_value, root)
        supplied = json.loads(paths[6].read_text(encoding="utf-8"))
        if supplied != rebuilt:
            raise ValueError("external candidate does not exactly reproduce keyed finalization")
        authority = load_authorities(custodian_authority_bundle, custodian_authority_bundle_sha256, root).get(contract_value.get("authority_id"))
        if authority is None:
            raise ValueError("contracted keyed market custodian authority is unavailable")
        _verify(supplied, authority, paths[7], contract_value["authority_id"], FINALIZATION_NAMESPACE)
        _verify(supplied["binding_payload"], authority, paths[8], contract_value["authority_id"], BINDING_NAMESPACE)
        gold_bytes = b"".join(canonical_bytes(row) for row in rebuilt["public_gold"])
        release_gold = (root / "data/review/market-claim-gold.jsonl").read_bytes()
        if release_gold != gold_bytes or claim_gold != rebuilt["public_gold"]:
            raise ValueError("public market gold does not exactly match keyed candidate")
        receipt = json.loads((root / KEYED_RECEIPT_REL).read_text(encoding="utf-8"))
        expected = {"schema_version":"1.0-p4.2", "status":"keyed_market_gold_imported", "cohort_id":contract_value["cohort_id"], "custodian_contract_sha256":contract_value["contract_sha256"], "public_gold_sha256":rebuilt["finalization"]["public_gold_sha256"], "finalization_sha256":rebuilt["finalization"]["finalization_sha256"], "candidate_sha256":rebuilt["candidate_sha256"], "binding_payload_sha256":sha256_bytes(canonical_bytes(rebuilt["binding_payload"])), "candidate_signature_sha256":sha256_bytes(paths[7].read_bytes()), "binding_signature_sha256":sha256_bytes(paths[8].read_bytes()), "formal_gold_written":True}
        expected["receipt_sha256"] = sha256_bytes(canonical_bytes(expected))
        if receipt != expected:
            raise ValueError("keyed market finalization receipt does not exactly bind candidate and signatures")
        return [], rebuilt["binding_payload"]
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [str(exc)], None


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


def queue_commitment(queue_row: dict[str, Any]) -> str:
    """Stable commitment to the anonymous review assignment."""
    return sha256_bytes(canonical_bytes(queue_row))


def annotation_commitment(ledger_kind: str, ledger_id: str, role: str, queue_hash: str, annotation: dict[str, Any]) -> str:
    """Commit a blinded individual annotation without signing the final row."""
    return sha256_bytes(canonical_bytes({"contract": V2_NAMESPACE, "ledger_kind": ledger_kind,
        "ledger_id": ledger_id, "role": role, "queue_commitment_sha256": queue_hash,
        "annotation": annotation}))


def adjudication_commitment(ledger_kind: str, ledger_id: str, queue_hash: str, adjudication: dict[str, Any]) -> str:
    return sha256_bytes(canonical_bytes({"contract": V2_NAMESPACE, "ledger_kind": ledger_kind,
        "ledger_id": ledger_id, "queue_commitment_sha256": queue_hash, "adjudication": adjudication}))


def v2_attestation_payload(attestation: dict[str, Any]) -> bytes:
    """Exact detached bytes for a blinded submission or its adjudication receipt."""
    signed = {key: value for key, value in attestation.items() if key != "payload_sha256"}
    return canonical_bytes({"contract": V2_NAMESPACE, "attestation": signed})


def v2_receipt_digest(attestation: dict[str, Any]) -> str:
    """Digest of the complete signed receipt, including its submission time."""
    return sha256_bytes(v2_attestation_payload(attestation))


def _utc_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed) else None


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
    keyed_custodian_authority_bundle: str | Path | None = None, keyed_custodian_authority_bundle_sha256: str | None = None,
    keyed_review_authority_bundle: str | Path | None = None, keyed_review_authority_bundle_sha256: str | None = None,
    keyed_contract: str | Path | None = None, keyed_assignment_ledger: str | Path | None = None,
    keyed_decisions_a: str | Path | None = None, keyed_decisions_b: str | Path | None = None, keyed_adjudications: str | Path | None = None,
    keyed_resolution_map: str | Path | None = None, keyed_candidate: str | Path | None = None,
    keyed_candidate_signature: str | Path | None = None, keyed_binding_signature: str | Path | None = None,
) -> list[str]:
    """Fail closed unless every nonempty-ledger row has three valid attestations."""
    ledgers = {"market_claim_gold": (claim_queue, claim_gold), "market_near_miss_approved_evidence": (near_queue, near_evidence)}
    keyed = (root / KEYED_RECEIPT_REL).exists()
    keyed_args = (keyed_custodian_authority_bundle, keyed_custodian_authority_bundle_sha256, keyed_review_authority_bundle, keyed_review_authority_bundle_sha256, keyed_contract, keyed_assignment_ledger, keyed_decisions_a, keyed_decisions_b, keyed_adjudications, keyed_resolution_map, keyed_candidate, keyed_candidate_signature, keyed_binding_signature)
    if not any(rows for _, rows in ledgers.values()):
        if keyed:
            errors, _ = keyed_market_finalization_errors(root, claim_gold, *keyed_args)
            return errors
        if any(keyed_args):
            return ["keyed market finalization inputs require a keyed finalization receipt"]
        return []
    if keyed:
        if near_evidence:
            return ["keyed market finalization and legacy market audit ledgers are mutually exclusive"]
        if authority_bundle or authority_bundle_sha256:
            return ["keyed market finalization and v2 market audit inputs are mutually exclusive"]
        try:
            legacy_attestations = read_jsonl(root / ATTESTATIONS_REL)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return [f"market audit attestation ledger is unreadable: {exc}"]
        signature_root = root / SIGNATURES_REL
        if legacy_attestations or (signature_root.is_dir() and any(path.is_file() for path in signature_root.rglob("*"))):
            return ["keyed market finalization and legacy market audit artifacts are mutually exclusive"]
        errors, _ = keyed_market_finalization_errors(root, claim_gold, *keyed_args)
        return errors
    if any(keyed_args):
        return ["keyed market finalization inputs require a keyed finalization receipt"]
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
        # v2 gold receipts deliberately do not sign a completed ledger row;
        # their evidence is replayed by the dedicated independence verifier.
        if item.get("schema_version") == "sky-market-audit-attestation-v2":
            continue
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
            if kind == "market_claim_gold" and any(
                entry.get("schema_version") == "sky-market-audit-attestation-v2"
                for entry in attestations
                if str(entry.get("ledger_kind")) == kind and str(entry.get("ledger_id")) == ledger_id
            ):
                # The v2 verifier below checks all three receipts, including
                # identities, distinct keys, commitments and signatures.
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
    if claim_gold:
        errors.extend(independent_blinded_decisions_errors(root, claim_queue, claim_gold, authority_bundle, authority_bundle_sha256))
    return errors


def _verify_detached(root: Path, authority: dict[str, Any], attestation: dict[str, Any], payload: bytes, errors: list[str], label: str) -> None:
    """Verify one v2 receipt, keeping the verification mechanics in one place."""
    if attestation.get("payload_sha256") != sha256_bytes(payload):
        errors.append(f"{label}: payload hash does not bind the v2 receipt")
        return
    signature_value = attestation.get("signature_file")
    signature = root / signature_value if isinstance(signature_value, str) else root
    try:
        signature.resolve().relative_to((root / SIGNATURES_REL).resolve())
    except ValueError:
        errors.append(f"{label}: signature path escapes market-audit/signatures")
        return
    if not signature.is_file():
        errors.append(f"{label}: detached signature is missing")
        return
    with tempfile.TemporaryDirectory(prefix="sky-market-audit-") as temporary:
        allowed = Path(temporary) / "allowed_signers"
        allowed.write_text(f"{attestation.get('authority_id')} {authority['public_key'].strip()}\n", encoding="utf-8", newline="\n")
        child = subprocess.run(
            ["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", str(attestation.get("authority_id")), "-n", V2_NAMESPACE, "-s", str(signature)],
            input=payload, capture_output=True, check=False,
        )
    if child.returncode != 0:
        errors.append(f"{label}: ssh-keygen detached signature verification failed")


def independent_blinded_decisions_errors(
    root: Path, claim_queue: list[dict[str, Any]], claim_gold: list[dict[str, Any]],
    authority_bundle: str | Path | None = None, authority_bundle_sha256: str | None = None,
) -> list[str]:
    """Replay v2 independent blinded-submission evidence for every gold row.

    A v1 signature over a completed row is intentionally not accepted here.
    This function makes the evaluator's independence result evidence-based while
    allowing an empty formal ledger to remain valid without a trust-root input.
    """
    if not claim_gold:
        return []
    authorities, errors = _external_bundle(authority_bundle, authority_bundle_sha256, root)
    if authorities is None:
        return errors
    try:
        attestations = read_jsonl(root / ATTESTATIONS_REL)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"market audit attestation ledger is unreadable: {exc}"]
    queue_by_id = {row.get("review_id"): row for row in claim_queue}
    by_target: dict[tuple[str, str], list[dict[str, Any]]] = {}
    ids: set[str] = set()
    signatures: set[str] = set()
    for entry in attestations:
        if entry.get("schema_version") != "sky-market-audit-attestation-v2":
            continue
        identity = entry.get("attestation_id")
        signature = entry.get("signature_file")
        if not isinstance(identity, str) or identity in ids:
            errors.append("market v2 attestation_id is missing or duplicated")
        ids.add(str(identity))
        if not isinstance(signature, str) or signature in signatures:
            errors.append("market v2 signature_file is missing or reused")
        signatures.add(str(signature))
        by_target.setdefault((str(entry.get("ledger_kind")), str(entry.get("ledger_id"))), []).append(entry)
    targets = {("market_claim_gold", str(row.get("gold_id"))) for row in claim_gold}
    if set(by_target) - targets:
        errors.append("market v2 attestation ledger references an absent market gold row")
    for row in claim_gold:
        ledger_id = str(row.get("gold_id")); label = f"market_claim_gold:{ledger_id}"
        queue = queue_by_id.get(row.get("review_id"))
        if not queue:
            errors.append(f"{label}: queue linkage is unavailable for blinded audit")
            continue
        queue_hash = queue_commitment(queue)
        entries = by_target.get(("market_claim_gold", ledger_id), [])
        roles = {entry.get("role"): entry for entry in entries}
        if len(entries) != 3 or set(roles) != {"annotator_a", "annotator_b", "adjudicator"}:
            errors.append(f"{label}: requires exactly two v2 blinded submissions and one v2 adjudication receipt")
            continue
        fingerprints: set[str] = set()
        annotations: dict[str, dict[str, Any]] = {}
        for role in ("annotator_a", "annotator_b"):
            entry = roles[role]; authority_id = entry.get("authority_id")
            authority = authorities.get(authority_id) if isinstance(authority_id, str) else None
            if (entry.get("receipt_type") != "blinded_annotation_submission" or not authority or
                    role not in authority.get("roles", []) or authority.get("fingerprint") != entry.get("fingerprint") or
                    _review_identity(row, "market_claim_gold", role) != authority_id):
                errors.append(f"{label}:{role}: authority or blinded-submission role binding is invalid")
                continue
            fingerprints.add(str(entry.get("fingerprint")))
            annotation = row.get(role)
            expected = annotation_commitment("market_claim_gold", ledger_id, role, queue_hash, annotation if isinstance(annotation, dict) else {})
            if entry.get("review_id") != row.get("review_id") or entry.get("queue_commitment_sha256") != queue_hash or entry.get("annotation_commitment_sha256") != expected:
                errors.append(f"{label}:{role}: blinded annotation or queue commitment does not replay")
            _verify_detached(root, authority, entry, v2_attestation_payload(entry), errors, f"{label}:{role}")
            annotations[role] = entry
        adjudicator = roles["adjudicator"]; authority_id = adjudicator.get("authority_id")
        authority = authorities.get(authority_id) if isinstance(authority_id, str) else None
        if (adjudicator.get("receipt_type") != "adjudication" or not authority or "adjudicator" not in authority.get("roles", []) or
                authority.get("fingerprint") != adjudicator.get("fingerprint") or _review_identity(row, "market_claim_gold", "adjudicator") != authority_id):
            errors.append(f"{label}:adjudicator: authority or adjudication role binding is invalid")
        else:
            fingerprints.add(str(adjudicator.get("fingerprint")))
            final = row.get("adjudication")
            expected_final = adjudication_commitment("market_claim_gold", ledger_id, queue_hash, final if isinstance(final, dict) else {})
            a, b = annotations.get("annotator_a", {}), annotations.get("annotator_b", {})
            linked = (adjudicator.get("review_id") == row.get("review_id") and adjudicator.get("queue_commitment_sha256") == queue_hash and
                adjudicator.get("annotator_a_attestation_id") == a.get("attestation_id") and adjudicator.get("annotator_b_attestation_id") == b.get("attestation_id") and
                adjudicator.get("annotator_a_annotation_commitment_sha256") == a.get("annotation_commitment_sha256") and adjudicator.get("annotator_b_annotation_commitment_sha256") == b.get("annotation_commitment_sha256") and
                adjudicator.get("annotator_a_receipt_sha256") == v2_receipt_digest(a) and adjudicator.get("annotator_b_receipt_sha256") == v2_receipt_digest(b) and
                adjudicator.get("final_adjudication_commitment_sha256") == expected_final)
            if not linked:
                errors.append(f"{label}:adjudicator: receipt does not link both verified blinded commitments and final adjudication")
            submitted = [_utc_timestamp(a.get("submitted_at")), _utc_timestamp(b.get("submitted_at"))]
            adjudicated = _utc_timestamp(adjudicator.get("adjudicated_at"))
            if adjudicated is None or any(value is None or value >= adjudicated for value in submitted):
                errors.append(f"{label}:adjudicator: both blinded submissions must be timestamped before adjudication")
            _verify_detached(root, authority, adjudicator, v2_attestation_payload(adjudicator), errors, f"{label}:adjudicator")
        if len(fingerprints) != 3:
            errors.append(f"{label}: v2 reviewer roles require three distinct authority fingerprints")
    return errors
