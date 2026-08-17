#!/usr/bin/env python3
"""Fail-closed keyed-custodian handoff for market human review.

The release-side process only verifies artifacts produced by an external
custodian.  It never accepts a secret, creates an assignment map, creates
packets, labels, signatures, or formal market gold.  The one publishable
artifact is a deliberately non-linkable aggregate commitment manifest.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
QUEUE_SIZE = 200
ASSIGNMENT_SIZE = 400
ROLES = ("annotator_a", "annotator_b")
PROTOCOL = "sky-market-review-keyed-custodian-v1"
AUTHORITY_VERSION = "sky-market-keyed-custodian-authority-bundle-v1"
CONTRACT_NAMESPACE = "sky-market-keyed-custodian-contract-v1"
CONTRACT_ROLE = "keyed_market_custodian_contract"
HEX = re.compile(r"[A-F0-9]{64}")
ASSIGNMENT = re.compile(r"market_assignment_annotator_[ab]_[a-f0-9]{32}")
FORBIDDEN_PUBLIC = {"listing_id", "listing_hash", "review_id", "input", "input_sha256", "split", "queue", "assignment_ledger"}
RESERVED = {"market-claim-gold.jsonl", "market-claim-gold.json", "claims.jsonl", "formal-gold.json", "formal-gold.jsonl"}


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def digest(value: bytes) -> str: return hashlib.sha256(value).hexdigest().upper()


def _outside(path: str | Path, root: Path, purpose: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    try: resolved.relative_to(root.resolve())
    except ValueError:
        if resolved.name.lower() in RESERVED: raise ValueError(f"{purpose} may not use a reserved formal-gold filename")
        return resolved
    raise ValueError(f"{purpose} must be outside the release root")


def _fingerprint(public_key: str) -> str | None:
    result = subprocess.run(["ssh-keygen", "-lf", "-"], input=public_key + "\n", text=True, capture_output=True, check=False)
    fields = result.stdout.strip().split()
    return fields[1] if result.returncode == 0 and len(fields) >= 2 else None


def _verify(payload: dict[str, Any], public_key: str, fingerprint: str, signature: Path, identity: str) -> None:
    if _fingerprint(public_key) != fingerprint: raise ValueError("keyed custodian public key fingerprint is invalid")
    if not signature.is_file(): raise ValueError("keyed custodian detached signature is missing")
    with tempfile.TemporaryDirectory(prefix="market-keyed-custodian-") as temporary:
        allowed = Path(temporary) / "allowed_signers"; allowed.write_text(f"{identity} {public_key.strip()}\n", encoding="utf-8")
        result = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", identity, "-n", CONTRACT_NAMESPACE, "-s", str(signature)], input=canonical_bytes(payload), capture_output=True, check=False)
    if result.returncode: raise ValueError("keyed custodian detached signature verification failed")


def _contract_payload(contract: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in contract.items() if key not in {"signature_file", "contract_sha256"}}


def load_authorities(path_value: str | Path | None, expected_sha: str | None, root: Path) -> dict[str, dict[str, Any]]:
    if path_value is None or not expected_sha: raise ValueError("external keyed market custodian authority bundle path and SHA-256 must be injected")
    path = _outside(path_value, root, "keyed market custodian authority bundle")
    if not path.is_file() or digest(path.read_bytes()) != str(expected_sha).upper(): raise ValueError("external keyed market custodian authority bundle SHA-256 does not match injected digest")
    try: bundle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise ValueError("external keyed market custodian authority bundle is not valid JSON") from exc
    if not isinstance(bundle, dict) or set(bundle) != {"schema_version", "authorities", "revoked_fingerprints"} or bundle.get("schema_version") != AUTHORITY_VERSION: raise ValueError("external keyed market custodian authority bundle has unsupported schema")
    rows, revoked = bundle.get("authorities"), bundle.get("revoked_fingerprints")
    if not isinstance(rows, list) or not isinstance(revoked, list) or any(not isinstance(value, str) for value in revoked): raise ValueError("external keyed market custodian authority bundle is malformed")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"authority_id", "public_key", "fingerprint", "roles"}: raise ValueError("external keyed market custodian authority has unsupported fields")
        authority_id, key, fp, roles = row.get("authority_id"), row.get("public_key"), row.get("fingerprint"), row.get("roles")
        if (not isinstance(authority_id, str) or not re.fullmatch(r"market_custodian_authority_[a-z0-9_]{3,64}", authority_id) or authority_id in result or not isinstance(key, str) or _fingerprint(key) != fp or fp in revoked or not isinstance(roles, list) or len(roles) != len(set(roles)) or CONTRACT_ROLE not in roles): raise ValueError("external keyed market custodian authority identity, key, role, or fingerprint is invalid")
        result[authority_id] = row
    if not result: raise ValueError("external keyed market custodian authority bundle has no active authorities")
    return result


def validate_contract(contract: dict[str, Any], contract_path: str | Path, root: Path = ROOT, authority_bundle: str | Path | None = None, authority_bundle_sha256: str | None = None) -> dict[str, Any]:
    path = _outside(contract_path, root, "keyed market custodian contract")
    required = {"schema_version", "contract_type", "cohort_id", "keyed_protocol", "queue_size", "assignment_count", "packet_counts", "commitment_merkle_root", "split_commitment", "packet_sha256", "assignment_ledger_sha256", "custodian_id", "authority_id", "fingerprint", "signature_file", "contract_sha256"}
    if not isinstance(contract, dict) or set(contract) != required: raise ValueError("keyed market custodian contract has unsupported fields")
    if contract.get("schema_version") != "1.0-p4.1" or contract.get("contract_type") != "market_review_keyed_custodian_contract" or contract.get("keyed_protocol") != PROTOCOL: raise ValueError("keyed market custodian contract protocol/version is invalid")
    if not isinstance(contract.get("cohort_id"), str) or not re.fullmatch(r"market_keyed_[a-z0-9_]{8,64}", contract["cohort_id"]): raise ValueError("keyed market custodian cohort ID is invalid")
    if contract.get("queue_size") != QUEUE_SIZE or contract.get("assignment_count") != ASSIGNMENT_SIZE or contract.get("packet_counts") != {"annotator_a": 200, "annotator_b": 200}: raise ValueError("keyed market custodian contract weakens fixed 200/400 policy")
    if any(not isinstance(contract.get(name), str) or not HEX.fullmatch(contract[name]) for name in ("commitment_merkle_root", "split_commitment", "assignment_ledger_sha256")): raise ValueError("keyed market custodian commitment digest is invalid")
    packets = contract.get("packet_sha256")
    if not isinstance(packets, dict) or set(packets) != set(ROLES) or any(not isinstance(value, str) or not HEX.fullmatch(value) for value in packets.values()): raise ValueError("keyed market custodian packet commitments are invalid")
    if not isinstance(contract.get("custodian_id"), str) or not re.fullmatch(r"market_custodian_[a-z0-9_]{3,64}", contract["custodian_id"]): raise ValueError("keyed market custodian identity is invalid")
    authorities = load_authorities(authority_bundle, authority_bundle_sha256, root); authority = authorities.get(contract.get("authority_id"))
    if authority is None or authority["fingerprint"] != contract.get("fingerprint"): raise ValueError("keyed market custodian authority is missing, revoked, or unauthorized")
    if contract.get("contract_sha256") != digest(canonical_bytes(_contract_payload(contract))): raise ValueError("keyed market custodian contract digest does not bind payload")
    signature = contract.get("signature_file")
    if not isinstance(signature, str) or not re.fullmatch(r"[A-Za-z0-9._-]+\.sig", signature): raise ValueError("keyed market custodian signature path is invalid")
    _verify(_contract_payload(contract), authority["public_key"], authority["fingerprint"], path.parent / signature, contract["custodian_id"])
    return contract


def _jsonl(path: Path) -> list[dict[str, Any]]:
    try: rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc: raise ValueError("external keyed market JSONL is invalid") from exc
    if any(not isinstance(row, dict) for row in rows): raise ValueError("external keyed market JSONL rows must be objects")
    return rows


def _read_assignments(path_value: str | Path, contract: dict[str, Any], root: Path) -> dict[str, set[str]]:
    path = _outside(path_value, root, "keyed market assignment ledger"); raw = path.read_bytes()
    if digest(raw) != contract["assignment_ledger_sha256"]: raise ValueError("keyed market assignment ledger digest does not match contract")
    rows = _jsonl(path)
    if len(rows) != ASSIGNMENT_SIZE or any(set(row) != {"assignment_id", "reviewer"} for row in rows): raise ValueError("keyed market assignment ledger exposes unsupported fields")
    assigned = {role: set() for role in ROLES}
    for row in rows:
        identity, role = row.get("assignment_id"), row.get("reviewer")
        if not isinstance(identity, str) or not ASSIGNMENT.fullmatch(identity) or role not in assigned or f"market_assignment_{role}_" not in identity or identity in assigned[role]: raise ValueError("keyed market assignment ledger is invalid")
        assigned[role].add(identity)
    if any(len(assigned[role]) != 200 for role in ROLES) or assigned["annotator_a"] & assigned["annotator_b"] or len(assigned["annotator_a"] | assigned["annotator_b"]) != ASSIGNMENT_SIZE: raise ValueError("keyed market assignment ledger must contain 400 unique opaque assignments")
    return assigned


def _packet_forbidden(value: Any) -> bool:
    if isinstance(value, dict): return any(key in FORBIDDEN_PUBLIC or _packet_forbidden(item) for key, item in value.items())
    if isinstance(value, list): return any(_packet_forbidden(item) for item in value)
    return False


def issue_existing_packets(contract_path: str | Path, assignment_ledger_path: str | Path, packet_dir: str | Path, output_dir: str | Path, root: Path = ROOT, *, authority_bundle: str | Path | None = None, authority_bundle_sha256: str | None = None) -> dict[str, Any]:
    """Verify/copy custodian-existing packets; this is not a packet issuer."""
    contract_path = _outside(contract_path, root, "keyed market custodian contract"); packet_dir = _outside(packet_dir, root, "keyed restricted packet directory"); output = _outside(output_dir, root, "keyed packet output")
    contract = validate_contract(json.loads(contract_path.read_text(encoding="utf-8")), contract_path, root, authority_bundle, authority_bundle_sha256)
    assignments = _read_assignments(assignment_ledger_path, contract, root)
    if output.exists(): raise ValueError("keyed packet output must not overwrite an existing path")
    verified: dict[str, tuple[Path, bytes]] = {}
    for role in ROLES:
        packet = packet_dir / f"market-review-{role}-restricted.jsonl"; content = packet.read_bytes()
        if digest(content) != contract["packet_sha256"][role]: raise ValueError(f"{role} restricted packet digest does not match contract")
        rows = _jsonl(packet)
        if len(rows) != 200 or any(set(row) != {"assignment_id", "review_payload"} or _packet_forbidden(row) or not isinstance(row.get("review_payload"), dict) for row in rows): raise ValueError("keyed market restricted packet exposes linkable fields")
        ids = [row.get("assignment_id") for row in rows]
        if set(ids) != assignments[role] or len(ids) != len(set(ids)): raise ValueError("keyed market restricted packet assignment coverage is invalid")
        verified[role] = (packet, content)
    output.mkdir(parents=True)
    copied = {}; created: list[tuple[Path, tuple[int, int]]] = []
    try:
        for role in ROLES:
            packet, content = verified[role]; destination = output / packet.name
            with destination.open("xb") as handle:
                stat = os.fstat(handle.fileno()); created.append((destination, (stat.st_dev, stat.st_ino)))
                handle.write(content)
            copied[role] = digest(content)
    except BaseException:
        for destination, expected_identity in created:
            try:
                stat = destination.stat()
                if destination.is_file() and (stat.st_dev, stat.st_ino) == expected_identity: destination.unlink()
            except OSError: pass
        try: output.rmdir()
        except OSError: pass
        raise
    return {"schema_version": "1.0-p4.1", "status": "external_keyed_restricted_packets_verified", "cohort_id": contract["cohort_id"], "contract_sha256": contract["contract_sha256"], "packet_sha256": copied, "formal_gold_written": False}


def publish_manifest(contract_path: str | Path, manifest_out: str | Path, root: Path = ROOT, *, authority_bundle: str | Path | None = None, authority_bundle_sha256: str | None = None) -> dict[str, Any]:
    """Publish aggregate commitments only; never identifiers or linkage fields."""
    contract_path = _outside(contract_path, root, "keyed market custodian contract")
    allowed = (root.resolve() / "data/review/market-keyed-queue-manifest.json").resolve(); output = Path(manifest_out).expanduser().resolve()
    if output != allowed: raise ValueError("keyed market public manifest output must use the approved release-root path")
    contract = validate_contract(json.loads(contract_path.read_text(encoding="utf-8")), contract_path, root, authority_bundle, authority_bundle_sha256)
    manifest = {"schema_version": "1.0-p4.1", "status": "keyed_frozen_pending_external_decisions", "cohort_id": contract["cohort_id"], "keyed_protocol": PROTOCOL, "queue_size": QUEUE_SIZE, "assignment_count": ASSIGNMENT_SIZE, "packet_counts": contract["packet_counts"], "commitment_merkle_root": contract["commitment_merkle_root"], "split_commitment": contract["split_commitment"], "packet_sha256": contract["packet_sha256"], "custodian_id": contract["custodian_id"], "custodian_authority_id": contract["authority_id"], "custodian_fingerprint": contract["fingerprint"], "custodian_contract_sha256": contract["contract_sha256"]}
    manifest["manifest_sha256"] = digest(canonical_bytes(manifest)); output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("xb") as handle: handle.write(canonical_bytes(manifest))
    except FileExistsError as exc: raise ValueError("keyed market public manifest must not overwrite an existing release artifact") from exc
    return manifest
