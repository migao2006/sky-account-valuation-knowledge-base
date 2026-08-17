"""Verify an externally-held, independently signed market identity mapping.

The mapping never enters a release.  It only permits the market authorization
factory to state that its already-signed opaque clusters were independently
reviewed.  Raw account identities, source locators, and resolver salts are
intentionally not part of this wire contract.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

NAMESPACE = "sky-market-identity-v1"
ROLES = ("identity_resolver", "identity_dedup_reviewer")
SHA256 = re.compile(r"^[A-Fa-f0-9]{64}$")
PII_KEY = re.compile(r"(?:name|user|handle|social|uid|email|mail|phone|mobile|contact|login|payment|address|url|link|salt|identity_raw)", re.I)
REQUIRED_MAPPING = {
    "mapping_id", "dataset_id", "authorization_record_id", "manifest_sha256", "observations_sha256",
    "training_example_id", "training_example_digest", "observation_id", "observation_row_digest",
    "source_snapshot_sha256", "account_id", "dedup_cluster_id", "dedup_cluster_digest",
    "identity_commitment", "identity_commitment_scheme", "review_scope", "reviewed_at",
}


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _external(path_value: str | Path | None, digest: str | None, root: Path, label: str, *, jsonl: bool = False) -> tuple[Any | None, list[str]]:
    if not path_value or not digest:
        return None, [f"{label} path and SHA-256 must be injected"]
    path = Path(path_value).expanduser().resolve()
    if _inside(path, root):
        return None, [f"{label} must be outside the release root"]
    if not path.is_file():
        return None, [f"{label} is missing"]
    raw = path.read_bytes()
    if not isinstance(digest, str) or not SHA256.fullmatch(digest) or sha256_bytes(raw) != digest.upper():
        return None, [f"{label} SHA-256 does not match injected digest"]
    try:
        if jsonl:
            value = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
        else:
            value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, [f"{label} is not valid JSON"]
    return value, []


def _fingerprint(key: Any) -> str | None:
    if not isinstance(key, str):
        return None
    result = subprocess.run(["ssh-keygen", "-lf", "-"], input=key + "\n", text=True, capture_output=True, check=False)
    fields = result.stdout.strip().split()
    return fields[1] if len(fields) >= 2 else None


def _pii(value: Any, path: str = "$") -> list[str]:
    result: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if not isinstance(key, str) or PII_KEY.search(key):
                result.append(child_path)
            result.extend(_pii(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            result.extend(_pii(child, f"{path}[{index}]"))
    elif isinstance(value, str) and ("@" in value or value.startswith(("http://", "https://", "www.")) or any(ch.isspace() for ch in value)):
        result.append(path)
    return result


def identity_attestation_payload(authority_bundle_sha256: str, mapping_sha256: str, statement: dict[str, Any], attestation: dict[str, Any]) -> bytes:
    """Canonical payload signed by each independent identity-review role."""
    claim = {key: value for key, value in statement.items() if key != "attestations"}
    receipt = {key: value for key, value in attestation.items() if key not in {"payload_sha256", "signature_file"}}
    return canonical_bytes({"contract": NAMESPACE, "authority_bundle_sha256": authority_bundle_sha256.upper(), "mapping_sha256": mapping_sha256.upper(), "statement": claim, "attestation": receipt})


def _verify_signature(authority: dict[str, Any], entry: dict[str, Any], payload: bytes, base: Path) -> bool:
    signature = base / str(entry.get("signature_file", ""))
    if not _inside(signature, base) or not signature.is_file():
        return False
    with tempfile.TemporaryDirectory(prefix="sky-market-identity-") as temporary:
        allowed = Path(temporary) / "allowed"
        allowed.write_text(f"{entry['authority_id']} {authority['public_key'].strip()}\n", encoding="utf-8", newline="\n")
        result = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", entry["authority_id"], "-n", NAMESPACE, "-s", str(signature)], input=payload, capture_output=True, check=False)
    return result.returncode == 0


def _expected_bindings(bindings: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    expected: dict[tuple[str, str], dict[str, Any]] = {}
    for binding in bindings:
        example, observation, dataset, manifest = (binding.get(name) for name in ("training_example", "observation", "dataset", "manifest"))
        if not all(isinstance(value, dict) for value in (example, observation, dataset, manifest)):
            continue
        key = (str(dataset.get("dataset_id")), str(example.get("training_example_id")))
        if key in expected:
            raise ValueError("duplicate current training-example binding")
        expected[key] = {
            "dataset_id": dataset.get("dataset_id"), "authorization_record_id": dataset.get("authorization_record_id"),
            "manifest_sha256": dataset.get("manifest_sha256"), "observations_sha256": manifest.get("observations_sha256"),
            "training_example_id": example.get("training_example_id"), "training_example_digest": example.get("training_example_digest"),
            "observation_id": observation.get("observation_id"), "observation_row_digest": sha256_bytes(canonical_bytes(observation)),
            "source_snapshot_sha256": observation.get("source_snapshot_sha256"), "account_id": example.get("account_id"),
            "dedup_cluster_id": example.get("dedup_cluster_id"), "dedup_cluster_digest": example.get("dedup_cluster_digest"),
        }
    return expected


def verify_identity_mapping(root: Path, bindings: list[dict[str, Any]], authority_bundle: str | Path | None = None, authority_bundle_sha256: str | None = None, mapping: str | Path | None = None, mapping_sha256: str | None = None, statement: str | Path | None = None, statement_sha256: str | None = None) -> tuple[list[str], dict[tuple[str, str], dict[str, Any]]]:
    """Verify a complete external mapping against exact already-authorized rows."""
    root = root.resolve()
    expected = _expected_bindings(bindings)
    if not expected:
        return [], {}
    bundle, errors = _external(authority_bundle, authority_bundle_sha256, root, "external market identity authority bundle")
    rows, row_errors = _external(mapping, mapping_sha256, root, "external market identity mapping", jsonl=True)
    claim, statement_errors = _external(statement, statement_sha256, root, "external market identity statement")
    errors.extend(row_errors + statement_errors)
    if not isinstance(bundle, dict) or not isinstance(rows, list) or not isinstance(claim, dict):
        return errors, {}
    if bundle.get("schema_version") != "market-identity-authority-bundle-v1":
        errors.append("external market identity authority bundle has unsupported schema_version")
    if claim.get("schema_version") != "market-identity-statement-v1":
        errors.append("external market identity statement has unsupported schema_version")
    authorities: dict[str, dict[str, Any]] = {}
    revoked = set(bundle.get("revoked_fingerprints", []))
    for authority in bundle.get("authorities", []) if isinstance(bundle.get("authorities"), list) else []:
        if not isinstance(authority, dict):
            errors.append("external market identity authority is not an object"); continue
        identifier, fingerprint = authority.get("authority_id"), _fingerprint(authority.get("public_key"))
        if not isinstance(identifier, str) or identifier in authorities or not isinstance(authority.get("roles"), list) or fingerprint != authority.get("fingerprint"):
            errors.append("external market identity authority has invalid identity, roles, or fingerprint"); continue
        if fingerprint in revoked:
            errors.append(f"external market identity authority {identifier} fingerprint is revoked"); continue
        authorities[identifier] = authority
    if not isinstance(bundle.get("authorities"), list):
        errors.append("external market identity authority bundle has no authorities array")
    if _pii(rows) or _pii(claim):
        errors.append("external market identity mapping or statement contains PII-like data")
    if claim.get("mapping_sha256", "").upper() != str(mapping_sha256).upper():
        errors.append("external market identity statement does not bind mapping bytes")
    try:
        if date.fromisoformat(str(claim.get("expires_at"))) < date.today():
            errors.append("external market identity statement is expired")
    except ValueError:
        errors.append("external market identity statement expiry is invalid")
    roots = claim.get("dataset_roots")
    expected_roots = {canonical_bytes({key: value[key] for key in ("dataset_id", "manifest_sha256", "observations_sha256")}) for value in expected.values()}
    actual_roots = {canonical_bytes(value) for value in roots} if isinstance(roots, list) and all(isinstance(value, dict) and set(value) == {"dataset_id", "manifest_sha256", "observations_sha256"} for value in roots) else set()
    if expected_roots != actual_roots:
        errors.append("external market identity statement dataset roots do not bind current authorized datasets")
    index: dict[tuple[str, str], dict[str, Any]] = {}
    identities: dict[str, str] = {}
    clusters: dict[str, str] = {}
    mapping_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != REQUIRED_MAPPING:
            errors.append("external market identity mapping row has unsupported or missing fields"); continue
        key = (str(row.get("dataset_id")), str(row.get("training_example_id")))
        target = expected.get(key)
        if target is None or key in index:
            errors.append("external market identity mapping has unknown or duplicate training-example binding"); continue
        if any(str(row.get(field, "")).upper() != str(value).upper() for field, value in target.items()):
            errors.append(f"external market identity mapping does not bind exact authorized bytes:{key[0]}:{key[1]}"); continue
        if not isinstance(row.get("mapping_id"), str) or not row["mapping_id"].startswith("identity_mapping_") or row["mapping_id"] in mapping_ids or not isinstance(row.get("identity_commitment"), str) or not SHA256.fullmatch(row["identity_commitment"]) or row.get("identity_commitment_scheme") != "resolver-hmac-sha256-v1" or row.get("review_scope") != "restricted-licensed-source-identity-resolution":
            errors.append("external market identity mapping row identity contract is invalid"); continue
        mapping_ids.add(row["mapping_id"])
        try:
            date.fromisoformat(str(row.get("reviewed_at")))
        except ValueError:
            errors.append("external market identity mapping reviewed_at is invalid"); continue
        identity, cluster = row["identity_commitment"].upper(), str(row["dedup_cluster_id"])
        if identity in identities and identities[identity] != cluster:
            errors.append("external market identity commitment is assigned to multiple clusters")
        if cluster in clusters and clusters[cluster] != identity:
            errors.append("external market identity cluster is assigned to multiple commitments")
        identities[identity], clusters[cluster], index[key] = cluster, identity, row
    if set(index) != set(expected):
        errors.append("external market identity mapping does not cover every authorized training example")
    attestations = claim.get("attestations")
    if not isinstance(attestations, list) or len(attestations) != 2 or {item.get("role") for item in attestations if isinstance(item, dict)} != set(ROLES):
        errors.append("external market identity statement requires exactly one attestation for each role")
    else:
        fingerprints: set[str] = set()
        # Identity resolution cannot be self-attested by a dataset's existing
        # steward/reviewer key.  The local attestations reveal fingerprints,
        # but never their restricted identity evidence.
        dataset_fingerprints: set[str] = set()
        attestations_path = root / "data/review/market-authorization/attestations.jsonl"
        if attestations_path.is_file():
            try:
                for line in attestations_path.read_text(encoding="utf-8").splitlines():
                    item = json.loads(line)
                    if isinstance(item, dict) and item.get("dataset_id") in {value["dataset_id"] for value in expected.values()} and isinstance(item.get("fingerprint"), str):
                        dataset_fingerprints.add(item["fingerprint"])
            except (OSError, json.JSONDecodeError):
                errors.append("formal market attestations are unreadable for identity-key separation")
        for entry in attestations:
            authority = authorities.get(entry.get("authority_id")) if isinstance(entry, dict) else None
            role = entry.get("role") if isinstance(entry, dict) else None
            if not authority or role not in authority.get("roles", []) or authority.get("fingerprint") != entry.get("fingerprint"):
                errors.append(f"external market identity {role}: authority does not hold role or fingerprint"); continue
            fingerprints.add(str(entry.get("fingerprint")))
            if str(entry.get("fingerprint")) in dataset_fingerprints:
                errors.append(f"external market identity {role}: identity authority fingerprint reuses a dataset attestation key")
            payload = identity_attestation_payload(str(authority_bundle_sha256), str(mapping_sha256), claim, entry)
            if entry.get("payload_sha256") != sha256_bytes(payload) or not _verify_signature(authority, entry, payload, Path(statement).expanduser().resolve().parent):
                errors.append(f"external market identity {role}: detached signature does not verify")
        if len(fingerprints) != 2:
            errors.append("external market identity roles require distinct authority fingerprints")
    return errors, index if not errors else {}
