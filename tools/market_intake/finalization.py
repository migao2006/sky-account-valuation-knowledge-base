#!/usr/bin/env python3
"""Fail-closed importer for a fully externally authorized market candidate.

This module intentionally has no private-key, signing, scraping, or feature
derivation capability.  It imports exactly one first dataset only after the
existing formal authorization verifier can replay the copied bytes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from tools.market_authorization import (
    ATTESTATIONS_REL, REGISTRY_REL, SIGNATURES_REL, ROLES, _fingerprint,
    attestation_payload, canonical_bytes, sha256_bytes,
    verify_authorized_market_intake,
)
from tools.validate.schema_validator import OfflineSchemaValidator

ROOT = Path(__file__).resolve().parents[2]
SHA256 = re.compile(r"^[A-Fa-f0-9]{64}$")
HANDOFF_VERSION = "authorized-market-finalization-handoff-v1"
APPEND_HANDOFF_VERSION = "authorized-market-finalization-handoff-v2"
_CANDIDATE_FILES = ("observations.jsonl", "training-examples.jsonl", "manifest.json", "registry-candidate.json")
_ATTESTATION_FIELDS = {"attestation_id", "dataset_id", "role", "authority_id", "fingerprint", "statement_sha256", "manifest_sha256", "observations_sha256", "payload_sha256", "signature_file"}


class FinalizationError(ValueError):
    """Raised before a finalization can affect the release tree."""


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _external_file(value: str | Path, digest: str, root: Path, label: str) -> Path:
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        raise FinalizationError(f"{label} SHA-256 must be supplied")
    path = Path(value).expanduser().resolve()
    if _inside(path, root):
        raise FinalizationError(f"{label} must be outside the release root")
    if not path.is_file():
        raise FinalizationError(f"{label} is missing")
    if _sha(path.read_bytes()) != digest.upper():
        raise FinalizationError(f"{label} SHA-256 does not match injected digest")
    return path


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FinalizationError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise FinalizationError(f"{label} must be a JSON object")
    return value


def _jsonl(path: Path, label: str) -> list[dict[str, Any]]:
    try:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, json.JSONDecodeError) as exc:
        raise FinalizationError(f"{label} is not valid JSONL") from exc
    if not rows or any(not isinstance(row, dict) for row in rows):
        raise FinalizationError(f"{label} must contain JSON objects")
    return rows


def _require_schema(validator: OfflineSchemaValidator, value: Any, root: Path, relative: str, label: str) -> None:
    errors = validator.validate(value, root / "schemas" / relative)
    if errors:
        raise FinalizationError(f"{label} does not satisfy its formal schema: " + "; ".join(errors))


def _safe_signature_name(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,120}\.sig", value):
        raise FinalizationError("handoff signature filename is invalid")
    return value


def _verify_handoff(handoff: dict[str, Any], candidate: dict[str, Any], candidate_dir: Path,
                    bundle: dict[str, Any], statement: dict[str, Any], statement_sha: str,
                    root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[tuple[Path, str]]]:
    expected = {"schema_version", "candidate", "authority_bundle_sha256", "statement_sha256", "attestations"}
    if set(handoff) != expected or handoff.get("schema_version") != HANDOFF_VERSION:
        raise FinalizationError("external handoff has unsupported fields or schema_version")
    if handoff.get("statement_sha256", "").upper() != statement_sha:
        raise FinalizationError("handoff statement SHA-256 does not bind injected statement")
    claim = handoff.get("candidate")
    required_claim = {"dataset_id", "authorization_record_id", "manifest_sha256", "observations_sha256", "training_examples_sha256", "registry_candidate_sha256"}
    if not isinstance(claim, dict) or set(claim) != required_claim:
        raise FinalizationError("handoff candidate binding has unsupported fields")
    for key, filename in (("manifest_sha256", "manifest.json"), ("observations_sha256", "observations.jsonl"), ("training_examples_sha256", "training-examples.jsonl"), ("registry_candidate_sha256", "registry-candidate.json")):
        if not isinstance(claim[key], str) or not SHA256.fullmatch(claim[key]) or _sha((candidate_dir / filename).read_bytes()) != claim[key].upper():
            raise FinalizationError(f"handoff does not bind candidate {filename} bytes")
    manifest = candidate["manifest"]
    registry_candidate = candidate["registry"]
    if (claim["dataset_id"] != manifest.get("dataset_id") or claim["dataset_id"] != registry_candidate.get("dataset_id")
            or claim["authorization_record_id"] != registry_candidate.get("authorization_record_id")
            or registry_candidate.get("manifest_sha256", "").upper() != claim["manifest_sha256"].upper()
            or manifest.get("observations_sha256", "").upper() != claim["observations_sha256"].upper()
            or manifest.get("training_examples_sha256", "").upper() != claim["training_examples_sha256"].upper()):
        raise FinalizationError("candidate/manifest/registry bindings disagree")
    dataset_id = claim["dataset_id"]
    if not isinstance(dataset_id, str) or not re.fullmatch(r"authorized_market_[a-z0-9_]+", dataset_id):
        raise FinalizationError("candidate dataset_id is invalid")
    base = f"data/review/market-authorization/datasets/{dataset_id}"
    if (registry_candidate.get("manifest_path") != f"{base}/manifest.json"
            or manifest.get("observations_path") != f"{base}/observations.jsonl"
            or manifest.get("training_examples_path") != f"{base}/training-examples.jsonl"):
        raise FinalizationError("candidate paths do not use the fixed formal dataset directory")
    if registry_candidate.get("statement_sha256") is not None or registry_candidate.get("status") != "candidate_requires_external_statement_and_three_role_signatures":
        raise FinalizationError("candidate registry is not an unsigned candidate")
    try:
        if date.fromisoformat(str(registry_candidate.get("expires_at"))) <= date.today():
            raise ValueError
    except ValueError as exc:
        raise FinalizationError("candidate authorization is expired or invalid") from exc
    final_registry = {key: registry_candidate[key] for key in ("dataset_id", "authorization_record_id", "manifest_path", "manifest_sha256", "expires_at")}
    final_registry["statement_sha256"] = statement_sha
    if (statement.get("schema_version") != "authorized-market-statement-v1" or statement.get("dataset_id") != final_registry["dataset_id"]
            or str(statement.get("manifest_sha256", "")).upper() != final_registry["manifest_sha256"].upper()
            or str(statement.get("observations_sha256", "")).upper() != str(manifest.get("observations_sha256", "")).upper()
            or statement.get("expires_at") != final_registry["expires_at"]):
        raise FinalizationError("statement does not exactly bind candidate dataset bytes")
    if bundle.get("schema_version") != "authorized-market-authority-bundle-v1" or not isinstance(bundle.get("authorities"), list):
        raise FinalizationError("authority bundle has unsupported schema_version or authorities")
    authorities: dict[str, dict[str, Any]] = {}
    revoked = set(bundle.get("revoked_fingerprints", []))
    for authority in bundle["authorities"]:
        if not isinstance(authority, dict) or not isinstance(authority.get("authority_id"), str) or authority["authority_id"] in authorities:
            raise FinalizationError("authority bundle identity is invalid")
        fingerprint = _fingerprint(authority.get("public_key", "")) if isinstance(authority.get("public_key"), str) else None
        if not fingerprint or authority.get("fingerprint") != fingerprint or fingerprint in revoked or not isinstance(authority.get("roles"), list):
            raise FinalizationError("authority bundle key, fingerprint, roles, or revocation is invalid")
        authorities[authority["authority_id"]] = authority
    entries = handoff.get("attestations")
    if not isinstance(entries, list) or len(entries) != 3:
        raise FinalizationError("handoff requires exactly three attestation receipts")
    attestations: list[dict[str, Any]] = []
    sources: list[tuple[Path, str]] = []
    roles: set[str] = set(); fingerprints: set[str] = set(); ids: set[str] = set()
    for receipt in entries:
        if not isinstance(receipt, dict) or set(receipt) != {"attestation", "attestation_sha256", "signature_path", "signature_sha256"}:
            raise FinalizationError("handoff attestation receipt has unsupported fields")
        entry = receipt["attestation"]
        if not isinstance(entry, dict) or set(entry) != _ATTESTATION_FIELDS or _sha(canonical_bytes(entry)) != str(receipt["attestation_sha256"]).upper():
            raise FinalizationError("handoff attestation SHA-256 does not bind canonical receipt")
        signature = _external_file(receipt["signature_path"], receipt["signature_sha256"], root, "external detached signature")
        role, authority_id = entry.get("role"), entry.get("authority_id")
        name = _safe_signature_name(signature.name)
        expected_path = f"data/review/market-authorization/signatures/{name}"
        if (role not in ROLES or role in roles or not isinstance(entry.get("attestation_id"), str) or entry["attestation_id"] in ids
                or entry.get("dataset_id") != final_registry["dataset_id"] or entry.get("signature_file") != expected_path
                or str(entry.get("statement_sha256", "")).upper() != statement_sha
                or str(entry.get("manifest_sha256", "")).upper() != final_registry["manifest_sha256"].upper()
                or str(entry.get("observations_sha256", "")).upper() != str(manifest["observations_sha256"]).upper()):
            raise FinalizationError("attestation metadata does not exactly bind final dataset")
        authority = authorities.get(authority_id)
        if not authority or role not in authority["roles"] or entry.get("fingerprint") != authority["fingerprint"]:
            raise FinalizationError("attestation authority lacks its role or matching fingerprint")
        payload = attestation_payload(final_registry, manifest, statement, entry)
        if entry.get("payload_sha256") != sha256_bytes(payload):
            raise FinalizationError("attestation payload SHA-256 does not bind canonical final receipt")
        attestations.append(entry); sources.append((signature, name)); roles.add(role); fingerprints.add(authority["fingerprint"]); ids.add(entry["attestation_id"])
    if roles != set(ROLES) or len(fingerprints) != 3:
        raise FinalizationError("three roles require three distinct OpenSSH fingerprints")
    return final_registry, attestations, sources


def finalize(root: Path, candidate_dir: Path, candidate_manifest_sha256: str,
             authority_bundle: Path, authority_bundle_sha256: str, statement: Path,
             statement_sha256: str, handoff: Path, handoff_sha256: str) -> dict[str, Any]:
    """Import a first externally authorized dataset, or fail without mutation."""
    root = root.resolve()
    candidate_dir = Path(candidate_dir).expanduser().resolve()
    if _inside(candidate_dir, root) or not candidate_dir.is_dir():
        raise FinalizationError("candidate directory must be an existing directory outside the release root")
    manifest_path = _external_file(candidate_dir / "manifest.json", candidate_manifest_sha256, root, "candidate manifest")
    # Every candidate byte is pinned by the independently pinned handoff.
    for name in _CANDIDATE_FILES:
        if not (candidate_dir / name).is_file():
            raise FinalizationError(f"candidate {name} is missing")
    bundle_path = _external_file(authority_bundle, authority_bundle_sha256, root, "external authority bundle")
    statement_path = _external_file(statement, statement_sha256, root, "external authorization statement")
    handoff_path = _external_file(handoff, handoff_sha256, root, "external finalization handoff")
    registry_path, attestation_path = root / REGISTRY_REL, root / ATTESTATIONS_REL
    old_registry = registry_path.read_bytes() if registry_path.exists() else None
    old_attestations = attestation_path.read_bytes() if attestation_path.exists() else None
    if (registry_path.exists() and registry_path.read_text(encoding="utf-8").strip()) or (attestation_path.exists() and attestation_path.read_text(encoding="utf-8").strip()):
        raise FinalizationError("finalizer supports only an empty formal registry; multi-statement import is fail-closed")
    candidate = {"manifest": _load_json(manifest_path, "candidate manifest"), "registry": _load_json(candidate_dir / "registry-candidate.json", "candidate registry")}
    observations = _jsonl(candidate_dir / "observations.jsonl", "candidate observations")
    examples = _jsonl(candidate_dir / "training-examples.jsonl", "candidate training examples")
    bundle, statement_value, handoff_value = _load_json(bundle_path, "external authority bundle"), _load_json(statement_path, "external authorization statement"), _load_json(handoff_path, "external finalization handoff")
    validator = OfflineSchemaValidator(root / "schemas")
    _require_schema(validator, candidate["manifest"], root, "market/authorized-market-manifest.schema.json", "candidate manifest")
    _require_schema(validator, candidate["registry"], root, "market/authorized-market-registry-candidate.schema.json", "candidate registry")
    for row in observations:
        _require_schema(validator, row, root, "market/authorized-market-observation.schema.json", "candidate observation")
    for row in examples:
        _require_schema(validator, row, root, "market/authorized-market-training-example.schema.json", "candidate training example")
    _require_schema(validator, handoff_value, root, "market/external-market-finalization-handoff.schema.json", "external finalization handoff")
    # Preserve byte SHA rather than a canonical reserialization when binding.
    if handoff_value.get("authority_bundle_sha256", "").upper() != _sha(bundle_path.read_bytes()):
        raise FinalizationError("handoff authority bundle SHA-256 does not bind injected bytes")
    final_registry, attestations, signature_sources = _verify_handoff(handoff_value, candidate, candidate_dir, bundle, statement_value, _sha(statement_path.read_bytes()), root)
    _require_schema(validator, final_registry, root, "market/authorized-market-dataset.schema.json", "final registry row")
    for row in attestations:
        _require_schema(validator, row, root, "market/authorized-market-attestation.schema.json", "final attestation")
    dataset_dir = root / "data/review/market-authorization/datasets" / final_registry["dataset_id"]
    if dataset_dir.exists():
        raise FinalizationError("final dataset directory already exists; overwrite is forbidden")
    signatures_dir = root / SIGNATURES_REL
    targets = [signatures_dir / name for _source, name in signature_sources]
    if any(target.exists() for target in targets):
        raise FinalizationError("final signature path already exists; overwrite is forbidden")
    # Stage the exact final layout, then ask the canonical verifier to replay it.
    with tempfile.TemporaryDirectory(prefix="sky-market-finalize-", dir=root) as temp:
        staging = Path(temp)
        staged_dataset = staging / "datasets" / final_registry["dataset_id"]; staged_dataset.mkdir(parents=True)
        for name in _CANDIDATE_FILES[:3]: shutil.copyfile(candidate_dir / name, staged_dataset / name)
        staged_signatures = staging / "signatures"; staged_signatures.mkdir()
        for source, name in signature_sources: shutil.copyfile(source, staged_signatures / name)
        # Install to final paths only while verifier runs; roll back every new
        # path if it rejects anything.  Existing files were prechecked empty.
        dataset_dir.parent.mkdir(parents=True, exist_ok=True); signatures_dir.mkdir(parents=True, exist_ok=True)
        # rename is deliberately non-replacing: a path created after the
        # preflight check must make finalization fail, never be overwritten.
        os.rename(staged_dataset, dataset_dir)
        created_signatures: list[Path] = []
        try:
            registry_path.parent.mkdir(parents=True, exist_ok=True)
            registry_path.write_bytes(canonical_bytes(final_registry))
            attestation_path.write_bytes(b"".join(canonical_bytes(row) for row in attestations))
            for _source, name in signature_sources:
                target = signatures_dir / name
                # Exclusive creation closes the precheck/install race and
                # also ensures rollback never removes somebody else's file.
                with (staged_signatures / name).open("rb") as source_handle:
                    target_handle = target.open("xb")
                    created_signatures.append(target)
                    with target_handle:
                        shutil.copyfileobj(source_handle, target_handle)
            errors = verify_authorized_market_intake(root, bundle_path, _sha(bundle_path.read_bytes()), statement_path, _sha(statement_path.read_bytes()))
            if errors:
                raise FinalizationError("formal authorization replay failed: " + "; ".join(errors))
        except BaseException:
            for target in created_signatures:
                target.unlink(missing_ok=True)
            if old_registry is None:
                registry_path.unlink(missing_ok=True)
            else:
                registry_path.write_bytes(old_registry)
            if old_attestations is None:
                attestation_path.unlink(missing_ok=True)
            else:
                attestation_path.write_bytes(old_attestations)
            shutil.rmtree(dataset_dir, ignore_errors=True)
            raise
    return {"dataset_id": final_registry["dataset_id"], "manifest_sha256": final_registry["manifest_sha256"], "statement_sha256": final_registry["statement_sha256"], "attestation_count": len(attestations)}


def _append_lock(root: Path) -> tuple[Path, bytes]:
    """Acquire an intentionally simple, exclusive transaction lock.

    The lock is an advisory boundary for finalizer processes.  Every mutable
    file still gets a byte-for-byte compare immediately before replacement,
    because a non-cooperating writer must never be silently overwritten.
    """
    path = root / "data/review/market-authorization/.finalization-append.lock"
    token = os.urandom(32).hex().encode("ascii")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(token)
    except FileExistsError as exc:
        raise FinalizationError("another market finalization transaction holds the exclusive lock") from exc
    return path, token


def _release_lock(path: Path, token: bytes) -> None:
    # Do not delete a replacement file that does not belong to this process.
    try:
        if path.is_file() and path.read_bytes() == token:
            path.unlink()
    except OSError:
        pass


def _owned_dataset_dir(path: Path, expected_sha256: dict[str, str]) -> bool:
    """Only remove a rollback directory when it is exactly our staged copy."""
    expected = set(_CANDIDATE_FILES[:3])
    try:
        if not path.is_dir() or {entry.name for entry in path.iterdir()} != expected:
            return False
        return all(_sha((path / name).read_bytes()) == expected_sha256[name] for name in expected)
    except OSError:
        return False


def _rewrite_if_bytes(path: Path, expected: bytes, replacement: bytes, label: str) -> None:
    """Compare and rewrite through one open handle.

    This removes the pre-check/write gap used by a non-cooperating writer to
    replace a ledger after the transaction CAS check but before write_bytes.
    """
    try:
        handle = path.open("r+b")
    except FileNotFoundError:
        if expected:
            raise FinalizationError(f"{label} disappeared after preflight")
        handle = path.open("x+b")
    with handle:
        current = handle.read()
        if current != expected:
            raise FinalizationError(f"{label} changed after preflight")
        handle.seek(0); handle.write(replacement); handle.truncate(); handle.flush(); os.fsync(handle.fileno())


def finalize_append_v2(root: Path, candidate_dir: Path, candidate_manifest_sha256: str,
                       authority_bundle: Path, authority_bundle_sha256: str,
                       statement_bundle: Path, statement_bundle_sha256: str,
                       handoff: Path, handoff_sha256: str) -> dict[str, Any]:
    """Append one v2-authorized dataset atomically, or leave the tree intact.

    This is deliberately separate from :func:`finalize`: v1 remains an
    empty-ledger bootstrap protocol.  The v2 bundle must cover *all* existing
    datasets plus the candidate, so historic approvals are replayed before
    and after the append operation.
    """
    root = root.resolve(); candidate_dir = Path(candidate_dir).expanduser().resolve()
    if _inside(candidate_dir, root) or not candidate_dir.is_dir():
        raise FinalizationError("candidate directory must be an existing directory outside the release root")
    manifest_path = _external_file(candidate_dir / "manifest.json", candidate_manifest_sha256, root, "candidate manifest")
    for name in _CANDIDATE_FILES:
        if not (candidate_dir / name).is_file():
            raise FinalizationError(f"candidate {name} is missing")
    bundle_path = _external_file(authority_bundle, authority_bundle_sha256, root, "external authority bundle")
    statement_path = _external_file(statement_bundle, statement_bundle_sha256, root, "external authorization statement bundle")
    handoff_path = _external_file(handoff, handoff_sha256, root, "external append finalization handoff")
    candidate = {"manifest": _load_json(manifest_path, "candidate manifest"), "registry": _load_json(candidate_dir / "registry-candidate.json", "candidate registry")}
    observations = _jsonl(candidate_dir / "observations.jsonl", "candidate observations")
    examples = _jsonl(candidate_dir / "training-examples.jsonl", "candidate training examples")
    bundle, statement_value, handoff_value = _load_json(bundle_path, "external authority bundle"), _load_json(statement_path, "external authorization statement bundle"), _load_json(handoff_path, "external append finalization handoff")
    validator = OfflineSchemaValidator(root / "schemas")
    _require_schema(validator, candidate["manifest"], root, "market/authorized-market-manifest.schema.json", "candidate manifest")
    _require_schema(validator, candidate["registry"], root, "market/authorized-market-registry-candidate.schema.json", "candidate registry")
    for row in observations: _require_schema(validator, row, root, "market/authorized-market-observation.schema.json", "candidate observation")
    for row in examples: _require_schema(validator, row, root, "market/authorized-market-training-example.schema.json", "candidate training example")
    _require_schema(validator, handoff_value, root, "market/external-market-finalization-handoff-v2.schema.json", "external append finalization handoff")
    _require_schema(validator, statement_value, root, "market/external-market-authorization-statement-bundle.schema.json", "external authorization statement bundle")
    if handoff_value.get("authority_bundle_sha256", "").upper() != _sha(bundle_path.read_bytes()) or handoff_value.get("statement_bundle_sha256", "").upper() != _sha(statement_path.read_bytes()):
        raise FinalizationError("append handoff does not bind injected trust bytes")
    registry_path, attestation_path = root / REGISTRY_REL, root / ATTESTATIONS_REL
    old_registry = registry_path.read_bytes() if registry_path.exists() else b""
    old_attestations = attestation_path.read_bytes() if attestation_path.exists() else b""
    try:
        old_datasets = _jsonl(registry_path, "formal registry") if old_registry.strip() else []
        old_attestations_rows = _jsonl(attestation_path, "formal attestations") if old_attestations.strip() else []
    except FinalizationError:
        raise
    except Exception as exc:
        raise FinalizationError("existing formal ledger is unreadable") from exc
    from tools.market_authorization import _statement_claims
    expected_ids = {str(row.get("dataset_id")) for row in old_datasets} | {str(candidate["manifest"].get("dataset_id"))}
    claims, claim_errors = _statement_claims(statement_value, old_datasets + [{"dataset_id": candidate["manifest"].get("dataset_id")}], _sha(statement_path.read_bytes()))
    if claim_errors or set(claims) != expected_ids:
        raise FinalizationError("statement bundle does not exactly cover existing and candidate datasets: " + "; ".join(claim_errors))
    # The incoming bundle deliberately has one extra (candidate) claim, while
    # the current ledger must still be replayed before it changes.  Project
    # only existing claims into a temporary, outside-root transport envelope;
    # claim bytes and their per-dataset attestation digests are unchanged.
    if old_datasets:
        prior = {"schema_version": "authorized-market-statement-bundle-v2", "statements": [claims[str(row["dataset_id"])][0] for row in old_datasets]}
        with tempfile.TemporaryDirectory(prefix="sky-market-append-prior-") as prior_dir:
            prior_path = Path(prior_dir) / "statement-bundle.json"; prior_path.write_bytes(canonical_bytes(prior))
            replay_before = verify_authorized_market_intake(root, bundle_path, _sha(bundle_path.read_bytes()), prior_path, _sha(prior_path.read_bytes()))
        if replay_before:
            raise FinalizationError("existing formal authorization replay failed: " + "; ".join(replay_before))
    candidate_claim, candidate_claim_sha = claims.get(str(candidate["manifest"].get("dataset_id")), ({}, ""))
    # Reuse the exact v1 receipt verifier with the embedded claim and its
    # canonical digest; signatures bind the claim, never transport bytes.
    virtual_handoff = dict(handoff_value)
    virtual_handoff["schema_version"] = HANDOFF_VERSION
    virtual_handoff["statement_sha256"] = candidate_claim_sha
    virtual_handoff.pop("statement_bundle_sha256", None)
    final_registry, attestations, signature_sources = _verify_handoff(
        virtual_handoff, candidate, candidate_dir, bundle, candidate_claim,
        candidate_claim_sha, root,
    )
    _require_schema(validator, final_registry, root, "market/authorized-market-dataset.schema.json", "final registry row")
    for row in attestations: _require_schema(validator, row, root, "market/authorized-market-attestation.schema.json", "final attestation")
    old_dataset_ids = {str(row.get("dataset_id")) for row in old_datasets}
    old_auth_ids = {str(row.get("authorization_record_id")) for row in old_datasets}
    old_attestation_ids = {str(row.get("attestation_id")) for row in old_attestations_rows}
    old_signature_files = {str(row.get("signature_file")) for row in old_attestations_rows}
    new_signature_files = {str(row["signature_file"]) for row in attestations}
    if (final_registry["dataset_id"] in old_dataset_ids or final_registry["authorization_record_id"] in old_auth_ids
            or len({row["attestation_id"] for row in attestations}) != 3
            or {row["attestation_id"] for row in attestations} & old_attestation_ids
            or len(new_signature_files) != 3 or new_signature_files & old_signature_files):
        raise FinalizationError("append would collide with an existing dataset, authorization, attestation, or signature")
    dataset_dir = root / "data/review/market-authorization/datasets" / final_registry["dataset_id"]
    signatures_dir = root / SIGNATURES_REL
    targets = [signatures_dir / name for _source, name in signature_sources]
    if dataset_dir.exists() or any(target.exists() for target in targets):
        raise FinalizationError("append target already exists; overwrite is forbidden")
    new_registry = old_registry + (b"" if not old_registry or old_registry.endswith(b"\n") else b"\n") + canonical_bytes(final_registry)
    new_attestations = old_attestations + (b"" if not old_attestations or old_attestations.endswith(b"\n") else b"\n") + b"".join(canonical_bytes(row) for row in attestations)
    installed_hashes = {name: _sha((candidate_dir / name).read_bytes()) for name in _CANDIDATE_FILES[:3]}
    signature_hashes = {name: _sha(source.read_bytes()) for source, name in signature_sources}
    lock_path, lock_token = _append_lock(root)
    installed_dataset = False; created_signatures: list[tuple[Path, tuple[int, int]]] = []; registry_written = False; attestations_written = False
    try:
        # Re-check the immutable external input immediately before mutation.
        for path, digest, label in ((manifest_path, candidate_manifest_sha256, "candidate manifest"), (bundle_path, authority_bundle_sha256, "authority bundle"), (statement_path, statement_bundle_sha256, "statement bundle"), (handoff_path, handoff_sha256, "append handoff")):
            if _sha(path.read_bytes()) != digest.upper(): raise FinalizationError(f"{label} changed after preflight")
        if (registry_path.read_bytes() if registry_path.exists() else b"") != old_registry or (attestation_path.read_bytes() if attestation_path.exists() else b"") != old_attestations:
            raise FinalizationError("formal ledger changed after preflight")
        with tempfile.TemporaryDirectory(prefix="sky-market-append-", dir=root) as temp:
            staging = Path(temp); staged_dataset = staging / "dataset"; staged_dataset.mkdir()
            for name in _CANDIDATE_FILES[:3]: shutil.copyfile(candidate_dir / name, staged_dataset / name)
            staged_signatures = staging / "signatures"; staged_signatures.mkdir()
            for source, name in signature_sources: shutil.copyfile(source, staged_signatures / name)
            if any(_sha((staged_dataset / name).read_bytes()) != installed_hashes[name] for name in _CANDIDATE_FILES[:3]):
                raise FinalizationError("candidate dataset bytes changed after preflight")
            if any(_sha((staged_signatures / name).read_bytes()) != signature_hashes[name] for _source, name in signature_sources):
                raise FinalizationError("candidate signature bytes changed after preflight")
            dataset_dir.parent.mkdir(parents=True, exist_ok=True); signatures_dir.mkdir(parents=True, exist_ok=True)
            os.rename(staged_dataset, dataset_dir); installed_dataset = True
            _rewrite_if_bytes(registry_path, old_registry, new_registry, "formal registry"); registry_written = True
            _rewrite_if_bytes(attestation_path, old_attestations, new_attestations, "formal attestations"); attestations_written = True
            for _source, name in signature_sources:
                target = signatures_dir / name
                with (staged_signatures / name).open("rb") as source_handle:
                    with target.open("xb") as target_handle:
                        stat = os.fstat(target_handle.fileno())
                        created_signatures.append((target, (stat.st_dev, stat.st_ino)))
                        shutil.copyfileobj(source_handle, target_handle)
            errors = verify_authorized_market_intake(root, bundle_path, _sha(bundle_path.read_bytes()), statement_path, _sha(statement_path.read_bytes()))
            if errors: raise FinalizationError("formal authorization replay failed: " + "; ".join(errors))
    except BaseException:
        for target, expected_identity in created_signatures:
            try:
                stat = target.stat()
                if target.is_file() and (stat.st_dev, stat.st_ino) == expected_identity:
                    target.unlink()
            except OSError: pass
        if attestations_written:
            try: _rewrite_if_bytes(attestation_path, new_attestations, old_attestations, "formal attestations during rollback")
            except (FinalizationError, OSError): pass
        if registry_written:
            try: _rewrite_if_bytes(registry_path, new_registry, old_registry, "formal registry during rollback")
            except (FinalizationError, OSError): pass
        if installed_dataset and _owned_dataset_dir(dataset_dir, installed_hashes): shutil.rmtree(dataset_dir, ignore_errors=True)
        raise
    finally:
        _release_lock(lock_path, lock_token)
    return {"dataset_id": final_registry["dataset_id"], "manifest_sha256": final_registry["manifest_sha256"], "statement_sha256": final_registry["statement_sha256"], "attestation_count": 3, "append_protocol": "v2"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Import an externally authorized market candidate.")
    parser.add_argument("--root", type=Path, default=ROOT); parser.add_argument("--candidate-dir", type=Path, required=True)
    parser.add_argument("--candidate-manifest-sha256", required=True); parser.add_argument("--authority-bundle", type=Path, required=True); parser.add_argument("--authority-bundle-sha256", required=True)
    parser.add_argument("--statement", type=Path, required=True); parser.add_argument("--statement-sha256", required=True); parser.add_argument("--handoff", type=Path, required=True); parser.add_argument("--handoff-sha256", required=True)
    parser.add_argument("--append-v2", action="store_true", help="append under the v2 exact-coverage statement-bundle protocol")
    args = parser.parse_args()
    operation = finalize_append_v2 if args.append_v2 else finalize
    print(json.dumps(operation(args.root, args.candidate_dir, args.candidate_manifest_sha256, args.authority_bundle, args.authority_bundle_sha256, args.statement, args.statement_sha256, args.handoff, args.handoff_sha256), sort_keys=True))


if __name__ == "__main__":
    main()
