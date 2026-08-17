#!/usr/bin/env python3
"""Create and verify privacy-preserving external parser-review cohorts.

This tool never writes raw replay inputs into the release root and never writes
formal gold.  It freezes an anonymous queue manifest in the repository and
writes the corresponding review packets only to a caller-supplied external
directory.  A separate verifier checks independent A/B commitments and permits
an adjudication only when those commitments disagree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import hmac
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_STRATA = ("account_type", "era", "season", "collaboration", "set_context")
STRATUM_VALUE_PATTERN = re.compile(r"bucket_[0-9]{1,2}")
QUEUE_SIZE = 200
SPLIT_SIZE = QUEUE_SIZE // 2
COMMITMENT_NAMESPACE = "sky-parser-review-commitment-v1"
KEYED_PROTOCOL = "sky-parser-review-keyed-hmac-v1"
KEYED_CONTRACT_NAMESPACE = "sky-parser-review-keyed-custodian-v2"
KEYED_AUTHORITY_BUNDLE_VERSION = "sky-parser-keyed-custodian-authority-bundle-v1"
KEYED_CUSTODIAN_ROLE = "keyed_custodian_contract"
KEYED_QUEUE_SIZE = 200
KEYED_SPLIT_COUNTS = {"development": 100, "heldout": 100}
_KEYED_HEX = re.compile(r"[A-F0-9]{64}")
_KEYED_ASSIGNMENT_ID = re.compile(r"assignment_annotator_[ab]_[a-f0-9]{32}")


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def keyed_commitment_merkle_root(commitments: list[str]) -> str:
    """Canonical Merkle root for opaque HMAC commitment leaves.

    Ordering is intentionally by commitment, never by raw input or split, so
    the published root cannot reveal the private assignment mapping.
    """
    if not commitments or len(commitments) != len(set(commitments)) or any(not isinstance(value, str) or not _KEYED_HEX.fullmatch(value) for value in commitments):
        raise ValueError("keyed commitment leaves must be unique SHA-256 values")
    level = [bytes.fromhex(value) for value in sorted(commitments)]
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [hashlib.sha256(level[index] + level[index + 1]).digest() for index in range(0, len(level), 2)]
    return level[0].hex().upper()


def keyed_split_commitment(rows: list[dict[str, Any]]) -> str:
    """Commit to the exact opaque cohort-to-split assignment.

    Unlike an arbitrary declaration, this canonical digest is recomputable by
    an external evaluator from the custodian binding.  Sorting by opaque leaf
    keeps raw inputs and their order out of the public protocol.
    """
    pairs: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) - {"gold_id", "input_sha256", "keyed_commitment", "split"} or not isinstance(row.get("keyed_commitment"), str) or not _KEYED_HEX.fullmatch(row["keyed_commitment"]) or row.get("split") not in KEYED_SPLIT_COUNTS:
            raise ValueError("keyed split commitment rows are invalid")
        pairs.append({"keyed_commitment": row["keyed_commitment"], "split": str(row["split"])})
    if len(pairs) != KEYED_QUEUE_SIZE or len({pair["keyed_commitment"] for pair in pairs}) != KEYED_QUEUE_SIZE or Counter(pair["split"] for pair in pairs) != KEYED_SPLIT_COUNTS:
        raise ValueError("keyed split commitment must cover exactly the fixed 200/100 cohort")
    return digest(canonical_bytes(sorted(pairs, key=lambda pair: pair["keyed_commitment"])))


def input_sha256(profile: dict[str, Any], listing: dict[str, Any]) -> str:
    return digest(canonical_bytes({"listing": listing, "profile": profile}))


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Replay the public queue commitment without needing restricted inputs."""
    if manifest == {
        "schema_version": "1.0-p3.4", "status": "not_ready", "queue_size": 0,
        "reason": "No external replay inputs have been supplied; no queue or formal gold exists.",
    }:
        return []
    if isinstance(manifest, dict) and manifest.get("schema_version") == "1.0-p3.7":
        try:
            _validate_keyed_public_manifest(manifest)
        except ValueError as exc:
            return [str(exc)]
        return []
    try:
        _validate_frozen_manifest(manifest)
    except ValueError as exc:
        return [str(exc)]
    return []


def _validate_keyed_public_manifest(manifest: dict[str, Any]) -> None:
    """Validate only the non-linkable public surface of a P3.7 cohort.

    Detached custodian signature validation is deliberately separate because
    its contract lives outside the release root.  This guard rejects any old
    per-input/split field before a future release validator consumes it.
    """
    required = {
        "schema_version", "status", "cohort_id", "keyed_protocol", "queue_size", "split_counts",
        "required_strata", "strata_distinct_value_counts", "commitment_merkle_root", "split_commitment",
        "packet_sha256", "assignment_ledger_sha256", "custodian_id", "custodian_authority_id", "custodian_fingerprint",
        "custodian_contract_sha256", "manifest_sha256",
    }
    forbidden = {"queue", "input_sha256", "input_commitment", "source_sha256", "queue_id", "split", "profile", "listing"}
    if not isinstance(manifest, dict) or set(manifest) != required or any(key in manifest for key in forbidden):
        raise ValueError("keyed public manifest contains unsupported or linkable fields")
    if manifest.get("schema_version") != "1.0-p3.7" or manifest.get("status") != "keyed_frozen_pending_external_decisions" or manifest.get("keyed_protocol") != KEYED_PROTOCOL:
        raise ValueError("keyed public manifest protocol/version is invalid")
    if not isinstance(manifest.get("cohort_id"), str) or not re.fullmatch(r"parser_keyed_[a-z0-9_]{8,64}", manifest["cohort_id"]):
        raise ValueError("keyed public manifest cohort ID is invalid")
    if manifest.get("queue_size") != KEYED_QUEUE_SIZE or manifest.get("split_counts") != KEYED_SPLIT_COUNTS or manifest.get("required_strata") != list(REQUIRED_STRATA):
        raise ValueError("keyed public manifest weakens 200/100 policy")
    coverage = manifest.get("strata_distinct_value_counts")
    if not isinstance(coverage, dict) or set(coverage) != set(REQUIRED_STRATA) or any(not isinstance(value, int) or value < 2 for value in coverage.values()):
        raise ValueError("keyed public manifest strata coverage is invalid")
    if any(not isinstance(manifest.get(key), str) or not _KEYED_HEX.fullmatch(manifest[key]) for key in ("commitment_merkle_root", "split_commitment", "assignment_ledger_sha256", "custodian_contract_sha256")):
        raise ValueError("keyed public manifest commitment digest is invalid")
    packets = manifest.get("packet_sha256")
    if not isinstance(packets, dict) or set(packets) != {"annotator_a", "annotator_b"} or any(not isinstance(value, str) or not _KEYED_HEX.fullmatch(value) for value in packets.values()):
        raise ValueError("keyed public manifest packet commitments are invalid")
    if not isinstance(manifest.get("custodian_id"), str) or not re.fullmatch(r"parser_custodian_[a-z0-9_]{3,64}", manifest["custodian_id"]) or not isinstance(manifest.get("custodian_fingerprint"), str) or not manifest["custodian_fingerprint"]:
        raise ValueError("keyed public manifest custodian identity is invalid")
    if not isinstance(manifest.get("custodian_authority_id"), str) or not re.fullmatch(r"parser_custodian_authority_[a-z0-9_]{3,64}", manifest["custodian_authority_id"]):
        raise ValueError("keyed public manifest custodian authority identity is invalid")
    if manifest.get("manifest_sha256") != digest(canonical_bytes({key: value for key, value in manifest.items() if key != "manifest_sha256"})):
        raise ValueError("keyed public manifest digest does not bind its contents")


def _outside_root(path: Path, root: Path, purpose: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return resolved
    raise ValueError(f"{purpose} must be outside the release root")


def _safe_workflow_output(path: Path, root: Path, purpose: str) -> Path:
    """P3.5 handoff artifacts are external-only and cannot impersonate gold."""
    resolved = _outside_root(path, root, purpose)
    if resolved.name.lower() in {"claims.jsonl", "claims.json", "formal-gold.json", "parser-gold.json"}:
        raise ValueError(f"{purpose} may not use a reserved formal-gold filename")
    return resolved


def _safe_queue_manifest_output(path: Path, root: Path) -> Path:
    """The only allowed in-root queue artifact is the anonymous manifest."""
    resolved = path.expanduser().resolve(); allowed = (root.resolve() / "data/review/parser-gold/review-queue-manifest.json").resolve()
    if resolved == allowed:
        return resolved
    return _safe_workflow_output(resolved, root, "queue manifest output")


def _verify_openssh_payload(payload: dict[str, Any], *, public_key: str, fingerprint: str, signature: Path, identity: str, namespace: str) -> None:
    """Verify an external authority's detached OpenSSH signature.

    The key and signature authenticate a public contract only.  In particular,
    this helper never receives an HMAC key, source input, or split mapping.
    """
    actual = _fingerprint(public_key)
    if not actual or actual != fingerprint:
        raise ValueError("custodian public key fingerprint is invalid")
    with tempfile.TemporaryDirectory(prefix="parser-keyed-review-") as temporary:
        allowed = Path(temporary) / "allowed_signers"
        allowed.write_text(f"{identity} {public_key.strip()}\n", encoding="utf-8")
        result = subprocess.run(
            ["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", identity,
             "-n", namespace, "-s", str(signature)],
            input=canonical_bytes(payload), capture_output=True, check=False,
        )
    if result.returncode:
        raise ValueError("custodian detached signature verification failed")


def load_keyed_custodian_authorities(path_value: str | Path | None, expected_sha: str | None, root: Path) -> dict[str, dict[str, Any]]:
    """Load the injected, revocable trust root for a keyed custodian.

    The signed contract carries an authority reference only.  It must never
    carry the public key that validates itself.
    """
    if path_value is None or not expected_sha:
        raise ValueError("external keyed custodian authority bundle path and SHA-256 must be injected")
    path = _outside_root(Path(path_value), root, "keyed custodian authority bundle")
    if not path.is_file():
        raise ValueError("external keyed custodian authority bundle is missing")
    if digest(path.read_bytes()) != str(expected_sha).upper():
        raise ValueError("external keyed custodian authority bundle SHA-256 does not match injected digest")
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("external keyed custodian authority bundle is not valid JSON") from exc
    if not isinstance(bundle, dict) or set(bundle) != {"schema_version", "authorities", "revoked_fingerprints"} or bundle.get("schema_version") != KEYED_AUTHORITY_BUNDLE_VERSION:
        raise ValueError("external keyed custodian authority bundle has unsupported schema")
    records, revoked = bundle.get("authorities"), bundle.get("revoked_fingerprints")
    if not isinstance(records, list) or not isinstance(revoked, list) or any(not isinstance(value, str) for value in revoked):
        raise ValueError("external keyed custodian authority bundle is malformed")
    authorities: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict) or set(record) != {"authority_id", "public_key", "fingerprint", "roles"}:
            raise ValueError("external keyed custodian authority has unsupported fields")
        authority_id, public_key, fingerprint, roles = record.get("authority_id"), record.get("public_key"), record.get("fingerprint"), record.get("roles")
        actual = _fingerprint(public_key) if isinstance(public_key, str) else None
        if (not isinstance(authority_id, str) or not re.fullmatch(r"parser_custodian_authority_[a-z0-9_]{3,64}", authority_id)
                or authority_id in authorities or not actual or fingerprint != actual
                or not isinstance(roles, list) or len(roles) != len(set(roles))
                or any(not isinstance(role, str) for role in roles) or KEYED_CUSTODIAN_ROLE not in roles):
            raise ValueError("external keyed custodian authority identity, key, role, or fingerprint is invalid")
        if fingerprint in revoked:
            raise ValueError(f"external keyed custodian authority {authority_id} fingerprint is revoked")
        authorities[authority_id] = record
    if not authorities:
        raise ValueError("external keyed custodian authority bundle has no active authorities")
    return authorities


def _keyed_contract_payload(contract: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in contract.items() if key not in {"signature_file", "contract_sha256"}}


def validate_keyed_custodian_contract(contract: dict[str, Any], contract_path: Path, root: Path, authority_bundle: str | Path | None = None, authority_bundle_sha256: str | None = None) -> dict[str, Any]:
    """Validate a P3.7 external custodian contract without seeing its secrets.

    A custodian creates the keyed HMAC commitments and private raw-input/split
    map outside the repository.  The public issuer may only act on this signed,
    fixed-size contract; callers cannot supply a blind secret or an ad-hoc map.
    """
    contract_path = _outside_root(contract_path, root, "keyed custodian contract")
    required = {
        "schema_version", "contract_type", "cohort_id", "keyed_protocol",
        "queue_size", "split_counts", "required_strata", "strata_distinct_value_counts",
        "commitment_merkle_root", "split_commitment", "packet_sha256",
        "assignment_ledger_sha256", "custodian_id", "authority_id", "fingerprint",
        "signature_file", "contract_sha256",
    }
    if not isinstance(contract, dict) or set(contract) != required:
        raise ValueError("keyed custodian contract has unsupported fields")
    if contract.get("schema_version") != "1.0-p3.7" or contract.get("contract_type") != "parser_review_keyed_custodian_contract" or contract.get("keyed_protocol") != KEYED_PROTOCOL:
        raise ValueError("keyed custodian contract protocol/version is invalid")
    if not isinstance(contract.get("cohort_id"), str) or not re.fullmatch(r"parser_keyed_[a-z0-9_]{8,64}", contract["cohort_id"]):
        raise ValueError("keyed custodian cohort ID is invalid")
    if contract.get("queue_size") != KEYED_QUEUE_SIZE or contract.get("split_counts") != KEYED_SPLIT_COUNTS or contract.get("required_strata") != list(REQUIRED_STRATA):
        raise ValueError("keyed custodian contract weakens the fixed 200/100 policy")
    if not isinstance(contract.get("strata_distinct_value_counts"), dict) or set(contract["strata_distinct_value_counts"]) != set(REQUIRED_STRATA) or any(not isinstance(value, int) or value < 2 for value in contract["strata_distinct_value_counts"].values()):
        raise ValueError("keyed custodian contract strata coverage is invalid")
    if any(not isinstance(contract.get(name), str) or not _KEYED_HEX.fullmatch(contract[name]) for name in ("commitment_merkle_root", "split_commitment", "assignment_ledger_sha256")):
        raise ValueError("keyed custodian commitment digest is invalid")
    packets = contract.get("packet_sha256")
    if not isinstance(packets, dict) or set(packets) != {"annotator_a", "annotator_b"} or any(not isinstance(value, str) or not _KEYED_HEX.fullmatch(value) for value in packets.values()):
        raise ValueError("keyed custodian packet commitments are invalid")
    if not isinstance(contract.get("custodian_id"), str) or not re.fullmatch(r"parser_custodian_[a-z0-9_]{3,64}", contract["custodian_id"]):
        raise ValueError("keyed custodian ID is invalid")
    authorities = load_keyed_custodian_authorities(authority_bundle, authority_bundle_sha256, root)
    authority_id = contract.get("authority_id")
    authority = authorities.get(authority_id) if isinstance(authority_id, str) else None
    if authority is None or authority.get("fingerprint") != contract.get("fingerprint") or KEYED_CUSTODIAN_ROLE not in authority.get("roles", []):
        raise ValueError("keyed custodian contract authority is missing, revoked, or unauthorized")
    if contract.get("contract_sha256") != digest(canonical_bytes(_keyed_contract_payload(contract))):
        raise ValueError("keyed custodian contract digest does not bind its payload")
    signature_name = contract.get("signature_file")
    if not isinstance(signature_name, str) or Path(signature_name).name != signature_name:
        raise ValueError("keyed custodian signature path is invalid")
    _verify_openssh_payload(
        _keyed_contract_payload(contract), public_key=str(authority["public_key"]), fingerprint=str(authority["fingerprint"]),
        signature=contract_path.parent / signature_name, identity=contract["custodian_id"], namespace=KEYED_CONTRACT_NAMESPACE,
    )
    return contract


def _read_keyed_assignment_ledger(path: Path, contract: dict[str, Any], root: Path) -> list[dict[str, Any]]:
    """Read safe opaque assignment IDs; the raw-to-split mapping stays private."""
    path = _outside_root(path, root, "keyed assignment ledger")
    rows = _read_jsonl(path)
    if digest(b"".join(canonical_bytes(row) for row in rows)) != contract["assignment_ledger_sha256"]:
        raise ValueError("keyed assignment ledger digest does not match custodian contract")
    if len(rows) != 400 or len({row.get("assignment_id") for row in rows if isinstance(row, dict)}) != 400:
        raise ValueError("keyed assignment ledger must contain exactly 400 unique assignments")
    counts = {"annotator_a": 0, "annotator_b": 0}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"assignment_id", "reviewer"} or not isinstance(row.get("assignment_id"), str) or not _KEYED_ASSIGNMENT_ID.fullmatch(row["assignment_id"]) or row.get("reviewer") not in counts:
            raise ValueError("keyed assignment ledger exposes or contains invalid fields")
        counts[row["reviewer"]] += 1
    if counts != {"annotator_a": 200, "annotator_b": 200}:
        raise ValueError("each keyed reviewer must receive exactly 200 assignments")
    return rows


def issue_keyed_blind_packages(contract_path: Path, assignment_ledger_path: Path, packet_dir: Path, output_dir: Path, root: Path, authority_bundle: str | Path | None = None, authority_bundle_sha256: str | None = None) -> dict[str, Any]:
    """Validate and copy custodian-issued blind packets outside the release root.

    It deliberately cannot construct packets from source input.  Only a signed
    external custodian contract may authorize this public handoff.
    """
    contract_path = _outside_root(contract_path, root, "keyed custodian contract")
    packet_dir = _outside_root(packet_dir, root, "keyed restricted packet directory")
    output_dir = _outside_root(output_dir, root, "keyed blind package output")
    contract = validate_keyed_custodian_contract(json.loads(contract_path.read_text(encoding="utf-8")), contract_path, root, authority_bundle, authority_bundle_sha256)
    assignments = _read_keyed_assignment_ledger(assignment_ledger_path, contract, root)
    by_reviewer = {reviewer: {row["assignment_id"] for row in assignments if row["reviewer"] == reviewer} for reviewer in ("annotator_a", "annotator_b")}
    output_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for reviewer in ("annotator_a", "annotator_b"):
        path = packet_dir / f"parser-review-{reviewer}-blind.jsonl"
        content = path.read_bytes()
        if digest(content) != contract["packet_sha256"][reviewer]:
            raise ValueError(f"{reviewer} blind packet digest does not match custodian contract")
        rows = _read_jsonl(path)
        if len(rows) != 200:
            raise ValueError(f"{reviewer} blind packet must contain exactly 200 rows")
        ids: set[str] = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"assignment_id", "profile", "listing", "strata"}:
                raise ValueError("keyed blind packet has unsupported/linkable fields")
            if not isinstance(row.get("assignment_id"), str) or row["assignment_id"] not in by_reviewer[reviewer] or row["assignment_id"] in ids:
                raise ValueError("keyed blind packet assignment coverage is invalid")
            if not isinstance(row.get("profile"), dict) or not isinstance(row.get("listing"), dict):
                raise ValueError("keyed blind packet profile/listing is invalid")
            _strata(row.get("strata")); ids.add(row["assignment_id"])
        if ids != by_reviewer[reviewer]:
            raise ValueError("keyed blind packet does not exactly cover issued assignments")
        destination = output_dir / path.name
        destination.write_bytes(content)
        written[reviewer] = digest(content)
    return {"schema_version": "1.0-p3.6", "status": "external_keyed_blind_packets_issued", "cohort_id": contract["cohort_id"], "contract_sha256": contract["contract_sha256"], "packet_sha256": written, "formal_gold_written": False}


def publish_keyed_queue_manifest(contract_path: Path, manifest_out: Path, root: Path, authority_bundle: str | Path | None = None, authority_bundle_sha256: str | None = None) -> dict[str, Any]:
    """Publish only the signed public commitment surface of a keyed cohort."""
    contract_path = _outside_root(contract_path, root, "keyed custodian contract")
    manifest_out = _safe_queue_manifest_output(manifest_out, root)
    contract = validate_keyed_custodian_contract(json.loads(contract_path.read_text(encoding="utf-8")), contract_path, root, authority_bundle, authority_bundle_sha256)
    manifest = {
        "schema_version": "1.0-p3.7", "status": "keyed_frozen_pending_external_decisions",
        "cohort_id": contract["cohort_id"], "keyed_protocol": contract["keyed_protocol"],
        "queue_size": contract["queue_size"], "split_counts": contract["split_counts"],
        "required_strata": contract["required_strata"], "strata_distinct_value_counts": contract["strata_distinct_value_counts"],
        "commitment_merkle_root": contract["commitment_merkle_root"], "split_commitment": contract["split_commitment"],
        "packet_sha256": contract["packet_sha256"], "assignment_ledger_sha256": contract["assignment_ledger_sha256"],
        "custodian_id": contract["custodian_id"], "custodian_authority_id": contract["authority_id"], "custodian_fingerprint": contract["fingerprint"],
        "custodian_contract_sha256": contract["contract_sha256"],
    }
    manifest["manifest_sha256"] = digest(canonical_bytes(manifest))
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    manifest_out.write_bytes(canonical_bytes(manifest))
    return manifest


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("JSONL rows must be objects")
            rows.append(value)
    return rows


def _strata(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != set(REQUIRED_STRATA):
        raise ValueError("review source rows require exactly the five approved strata")
    if any(not isinstance(value[key], str) or not STRATUM_VALUE_PATTERN.fullmatch(value[key]) for key in REQUIRED_STRATA):
        raise ValueError("review strata values must be approved low-cardinality opaque buckets")
    return {key: value[key] for key in REQUIRED_STRATA}


def _queue_row(profile: dict[str, Any], listing: dict[str, Any], strata: dict[str, str]) -> dict[str, Any]:
    sha = input_sha256(profile, listing)
    return {"queue_id": "parser_review_" + sha[:20].lower(), "input_sha256": sha, "strata": strata}


def _validate_frozen_manifest(manifest: dict[str, Any]) -> None:
    """Reject malformed or weakened frozen queue contracts before import."""
    required = {"schema_version", "status", "queue_size", "split_counts", "required_strata", "source_sha256", "queue", "strata_distinct_value_counts", "restricted_packet_sha256", "development_freeze_sha256", "heldout_blindness", "manifest_sha256"}
    if not isinstance(manifest, dict) or set(manifest) != required or manifest.get("schema_version") != "1.0-p3.4" or manifest.get("status") != "frozen_pending_external_decisions":
        raise ValueError("queue manifest has unsupported fields or is not a frozen pending contract")
    if manifest.get("manifest_sha256") != digest(canonical_bytes({key: value for key, value in manifest.items() if key != "manifest_sha256"})):
        raise ValueError("queue manifest digest does not bind its contents")
    if manifest.get("queue_size") != QUEUE_SIZE or manifest.get("split_counts") != {"development": SPLIT_SIZE, "heldout": SPLIT_SIZE} or manifest.get("required_strata") != list(REQUIRED_STRATA):
        raise ValueError("queue manifest weakens fixed cohort or split/strata policy")
    if not isinstance(manifest.get("source_sha256"), str) or not re.fullmatch(r"[A-F0-9]{64}", manifest["source_sha256"]): raise ValueError("queue manifest source hash is invalid")
    packet_hashes = manifest.get("restricted_packet_sha256")
    if not isinstance(packet_hashes, dict) or set(packet_hashes) != {"development", "heldout"} or any(not isinstance(value, str) or not re.fullmatch(r"[A-F0-9]{64}", value) for value in packet_hashes.values()): raise ValueError("queue manifest restricted packet hashes are invalid")
    queue = manifest.get("queue")
    if not isinstance(queue, list) or len(queue) != QUEUE_SIZE: raise ValueError("queue manifest must contain exactly 200 rows")
    ids, hashes, split_rows = set(), set(), {"development": [], "heldout": []}
    for row in queue:
        if not isinstance(row, dict) or set(row) != {"queue_id", "input_sha256", "strata", "split"}: raise ValueError("queue row contains unsupported fields")
        sha, qid, split = row.get("input_sha256"), row.get("queue_id"), row.get("split")
        if not isinstance(sha, str) or not re.fullmatch(r"[A-F0-9]{64}", sha) or qid != "parser_review_" + str(sha)[:20].lower() or qid in ids or sha in hashes or split not in split_rows: raise ValueError("queue row ID, hash, uniqueness, or split is invalid")
        _strata(row.get("strata")); ids.add(qid); hashes.add(sha); split_rows[split].append(row)
    if any(len(rows) != SPLIT_SIZE for rows in split_rows.values()): raise ValueError("queue manifest must have exactly 100 rows per split")
    expected_coverage = {split: {key: len({row["strata"][key] for row in rows}) for key in REQUIRED_STRATA} for split, rows in split_rows.items()}
    if manifest.get("strata_distinct_value_counts") != expected_coverage or any(count < 2 for values in expected_coverage.values() for count in values.values()): raise ValueError("queue manifest strata coverage is invalid")
    if manifest.get("development_freeze_sha256") != digest(canonical_bytes(split_rows["development"])): raise ValueError("queue manifest development freeze digest is invalid")


def build_queue(root: Path, source: Path, source_sha256: str, manifest_out: Path, packet_dir: Path) -> dict[str, Any]:
    """Freeze exactly 100 development and 100 held-out anonymous queue rows."""
    source = _outside_root(source, root, "review source")
    packet_dir = _outside_root(packet_dir, root, "restricted review packet directory")
    manifest_out = _safe_queue_manifest_output(manifest_out, root)
    if digest(source.read_bytes()) != source_sha256.upper():
        raise ValueError("review source SHA-256 does not match injected digest")
    candidates: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, str]]] = {}
    for row in _read_jsonl(source):
        if set(row) != {"profile", "listing", "strata"} or not isinstance(row["profile"], dict) or not isinstance(row["listing"], dict):
            raise ValueError("review source rows may contain only profile, listing, and approved strata")
        item = _queue_row(row["profile"], row["listing"], _strata(row["strata"]))
        if item["input_sha256"] in candidates:
            raise ValueError("review source contains duplicate parser inputs")
        candidates[item["input_sha256"]] = (row["profile"], row["listing"], item["strata"])
    if len(candidates) < QUEUE_SIZE:
        raise ValueError("review source must provide at least 200 unique inputs")
    # A digest sort is stable across machines and does not expose the source's
    # original order or identifiers.
    selected = sorted(candidates)[:QUEUE_SIZE]
    queue = []
    packets = {"development": [], "heldout": []}
    for index, sha in enumerate(selected):
        profile, listing, strata = candidates[sha]
        split = "development" if index < SPLIT_SIZE else "heldout"
        row = _queue_row(profile, listing, strata) | {"split": split}
        queue.append(row)
        packets[split].append(row | {"profile": profile, "listing": listing})
    coverage = {split: {key: len({row["strata"][key] for row in queue if row["split"] == split}) for key in REQUIRED_STRATA} for split in packets}
    if any(count < 2 for split in coverage.values() for count in split.values()):
        raise ValueError("each frozen split must contain at least two values for every required stratum")
    packet_dir.mkdir(parents=True, exist_ok=True)
    packet_hashes = {}
    for split, rows in packets.items():
        content = b"".join(canonical_bytes(row) for row in rows)
        path = packet_dir / f"parser-review-{split}-restricted.jsonl"
        path.write_bytes(content)
        packet_hashes[split] = digest(content)
    manifest = {
        "schema_version": "1.0-p3.4", "status": "frozen_pending_external_decisions", "queue_size": QUEUE_SIZE,
        "split_counts": {"development": SPLIT_SIZE, "heldout": SPLIT_SIZE}, "required_strata": list(REQUIRED_STRATA),
        "source_sha256": source_sha256.upper(), "queue": queue, "strata_distinct_value_counts": coverage,
        "restricted_packet_sha256": packet_hashes,
        "development_freeze_sha256": digest(canonical_bytes([row for row in queue if row["split"] == "development"])),
        "heldout_blindness": "heldout packet is separate; no heldout decision may inform the development manifest",
    }
    manifest["manifest_sha256"] = digest(canonical_bytes(manifest))
    manifest_out.write_bytes(canonical_bytes(manifest))
    return manifest


def _decision_payload(row: dict[str, Any]) -> dict[str, Any]:
    allowed = {"decision_id", "queue_id", "input_sha256", "reviewer", "expected_canonical_item_ids", "expected_polarity", "decision_commitment_sha256"}
    if set(row) != allowed:
        raise ValueError("decision contains unsupported fields")
    payload = {key: row[key] for key in allowed - {"decision_commitment_sha256"}}
    if not isinstance(payload["decision_id"], str) or not re.fullmatch(r"(?:receipt|annotator_[ab])_[a-z0-9_]{1,64}", payload["decision_id"]):
        raise ValueError("decision ID is invalid")
    if not isinstance(payload["queue_id"], str) or not re.fullmatch(r"parser_review_[a-f0-9]{20}", payload["queue_id"]) or not isinstance(payload["input_sha256"], str) or not re.fullmatch(r"[A-F0-9]{64}", payload["input_sha256"]):
        raise ValueError("decision queue or input hash is invalid")
    if payload["reviewer"] not in {"annotator_a", "annotator_b"}:
        raise ValueError("decision reviewer is invalid")
    if not isinstance(payload["expected_canonical_item_ids"], list) or not payload["expected_canonical_item_ids"] or len(payload["expected_canonical_item_ids"]) != len(set(payload["expected_canonical_item_ids"])) or any(not isinstance(item, str) or not re.fullmatch(r"item_[a-z0-9_]+", item) for item in payload["expected_canonical_item_ids"]):
        raise ValueError("decision requires unique canonical item IDs")
    if payload["expected_polarity"] not in {"owned", "confirmed_missing", "unknown"}:
        raise ValueError("decision has unsupported polarity")
    return payload


def _fingerprint(public_key: str) -> str | None:
    result = subprocess.run(["ssh-keygen", "-lf", "-"], input=public_key + "\n", text=True, capture_output=True, check=False)
    fields = result.stdout.strip().split()
    return fields[1] if result.returncode == 0 and len(fields) >= 2 else None


def _verify_decision_ledger(path: Path, reviewer: str, root: Path, queue_manifest_sha256: str) -> list[dict[str, Any]]:
    path = _outside_root(path, root, f"reviewer {reviewer} decisions")
    rows = _read_jsonl(path); sidecar = path.with_suffix(path.suffix + ".commitment.json")
    try: commitment = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise ValueError(f"{reviewer} signed decision commitment is missing: {exc}") from exc
    allowed = {"schema_version", "reviewer", "queue_manifest_sha256", "decision_ledger_sha256", "public_key", "fingerprint", "signature_file"}
    if not isinstance(commitment, dict) or set(commitment) != allowed or commitment.get("schema_version") != "1.0-p3.5" or commitment.get("reviewer") != reviewer or commitment.get("queue_manifest_sha256") != queue_manifest_sha256 or commitment.get("decision_ledger_sha256") != digest(b"".join(canonical_bytes(row) for row in rows)):
        raise ValueError(f"{reviewer} signed decision commitment does not bind its ledger")
    public_key = commitment.get("public_key"); fingerprint = _fingerprint(public_key) if isinstance(public_key, str) else None
    if not fingerprint or commitment.get("fingerprint") != fingerprint: raise ValueError(f"{reviewer} decision signer key is invalid")
    signature_name = commitment.get("signature_file")
    if not isinstance(signature_name, str) or Path(signature_name).name != signature_name: raise ValueError(f"{reviewer} decision signature path is invalid")
    signature = sidecar.parent / signature_name
    with tempfile.TemporaryDirectory(prefix="parser-review-") as temporary:
        allowed_signers = Path(temporary) / "allowed_signers"; allowed_signers.write_text(f"{reviewer} {public_key.strip()}\n", encoding="utf-8")
        result = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", str(allowed_signers), "-I", reviewer, "-n", COMMITMENT_NAMESPACE, "-s", str(signature)], input=canonical_bytes({key: value for key, value in commitment.items() if key != "signature_file"}), capture_output=True, check=False)
    if result.returncode: raise ValueError(f"{reviewer} signed decision commitment verification failed")
    return rows


def _verify_adjudication_ledger(path: Path, root: Path, queue_manifest_sha256: str) -> tuple[list[dict[str, Any]], str]:
    """Verify a third-party OpenSSH signature over the final adjudications."""
    path = _outside_root(path, root, "adjudications")
    rows = _read_jsonl(path); sidecar = path.with_suffix(path.suffix + ".commitment.json")
    try:
        commitment = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"adjudicator signed receipt is missing: {exc}") from exc
    allowed = {"schema_version", "reviewer", "queue_manifest_sha256", "adjudication_ledger_sha256", "public_key", "fingerprint", "signature_file"}
    if not isinstance(commitment, dict) or set(commitment) != allowed or commitment.get("schema_version") != "1.0-p3.5" or commitment.get("reviewer") != "adjudicator" or commitment.get("queue_manifest_sha256") != queue_manifest_sha256 or commitment.get("adjudication_ledger_sha256") != digest(b"".join(canonical_bytes(row) for row in rows)):
        raise ValueError("adjudicator signed receipt does not bind its ledger")
    public_key = commitment.get("public_key"); fingerprint = _fingerprint(public_key) if isinstance(public_key, str) else None
    if not fingerprint or commitment.get("fingerprint") != fingerprint:
        raise ValueError("adjudicator signer key is invalid")
    signature_name = commitment.get("signature_file")
    if not isinstance(signature_name, str) or Path(signature_name).name != signature_name:
        raise ValueError("adjudicator signature path is invalid")
    with tempfile.TemporaryDirectory(prefix="parser-review-") as temporary:
        allowed_signers = Path(temporary) / "allowed_signers"; allowed_signers.write_text(f"adjudicator {public_key.strip()}\n", encoding="utf-8")
        result = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", str(allowed_signers), "-I", "adjudicator", "-n", COMMITMENT_NAMESPACE, "-s", str(sidecar.parent / signature_name)], input=canonical_bytes({key: value for key, value in commitment.items() if key != "signature_file"}), capture_output=True, check=False)
    if result.returncode:
        raise ValueError("adjudicator signed receipt verification failed")
    return rows, fingerprint


def verify_decision_commitments(manifest: dict[str, Any], decisions_a: Path, decisions_b: Path, adjudications: Path | None, root: Path) -> dict[str, Any]:
    """Verify reviewer independence; returns candidates only, never formal gold."""
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("invalid queue manifest: " + "; ".join(errors))
    queue = manifest["queue"]
    expected = {row["queue_id"]: row for row in queue}
    def load(path: Path, reviewer: str) -> dict[str, dict[str, Any]]:
        result = {}
        for row in _verify_decision_ledger(path, reviewer, root, manifest["manifest_sha256"]):
            payload = _decision_payload(row)
            if payload["reviewer"] != reviewer or row["decision_commitment_sha256"] != digest(canonical_bytes(payload)):
                raise ValueError(f"{reviewer} decision commitment is invalid")
            queued = expected.get(payload["queue_id"])
            if not queued or queued["input_sha256"] != payload["input_sha256"] or payload["queue_id"] in result:
                raise ValueError(f"{reviewer} decisions do not exactly bind the frozen queue")
            result[payload["queue_id"]] = row
        if set(result) != set(expected): raise ValueError(f"{reviewer} decisions must cover every frozen queue row exactly once")
        return result
    a, b = load(decisions_a, "annotator_a"), load(decisions_b, "annotator_b")
    # Distinct reviewer roles must not be asserted by one signing key.
    def signer(path: Path) -> str: return json.loads(path.with_suffix(path.suffix + ".commitment.json").read_text(encoding="utf-8"))["fingerprint"]
    if signer(decisions_a) == signer(decisions_b): raise ValueError("annotator A and B require independent signing keys")
    def comparable(row: dict[str, Any]) -> tuple[Any, ...]:
        value = _decision_payload(row)
        return (tuple(value["expected_canonical_item_ids"]), value["expected_polarity"])
    disagreements = {qid for qid in expected if comparable(a[qid]) != comparable(b[qid])}
    adj: dict[str, dict[str, Any]] = {}
    if adjudications is not None:
        rows, adjudicator_fingerprint = _verify_adjudication_ledger(adjudications, root, manifest["manifest_sha256"])
        if adjudicator_fingerprint in {signer(decisions_a), signer(decisions_b)}:
            raise ValueError("adjudicator requires a third independent signing key")
        for row in rows:
            allowed = {"adjudication_id", "queue_id", "input_sha256", "annotator_a_commitment_sha256", "annotator_b_commitment_sha256", "final_canonical_item_ids", "final_polarity", "adjudicator_receipt_sha256"}
            if set(row) != allowed or not isinstance(row.get("adjudication_id"), str) or not re.fullmatch(r"adjudication_[a-z0-9_]{1,64}", row["adjudication_id"]) or not isinstance(row.get("queue_id"), str) or row["queue_id"] in adj:
                raise ValueError("adjudication has unsupported fields or duplicate queue ID")
            qid = row["queue_id"]
            payload = {key: value for key, value in row.items() if key != "adjudicator_receipt_sha256"}
            if qid not in expected or row["input_sha256"] != expected[qid]["input_sha256"] or row["annotator_a_commitment_sha256"] != a[qid]["decision_commitment_sha256"] or row["annotator_b_commitment_sha256"] != b[qid]["decision_commitment_sha256"]:
                raise ValueError("adjudication must link the two immutable A/B commitments")
            if row["adjudicator_receipt_sha256"] != digest(canonical_bytes(payload)) or not isinstance(row["final_canonical_item_ids"], list) or not row["final_canonical_item_ids"] or len(row["final_canonical_item_ids"]) != len(set(row["final_canonical_item_ids"])) or any(not isinstance(item, str) or not re.fullmatch(r"item_[a-z0-9_]+", item) for item in row["final_canonical_item_ids"]) or row["final_polarity"] not in {"owned", "confirmed_missing", "unknown"}:
                raise ValueError("adjudication requires a signed final result receipt")
            adj[qid] = row
    if set(adj) != disagreements:
        raise ValueError("adjudications must exist only and exactly for A/B disagreements")
    return {"status": "candidate_labels_only", "queue_manifest_sha256": manifest["manifest_sha256"], "agreement_count": len(expected) - len(disagreements), "disagreement_count": len(disagreements), "formal_gold_written": False}


def _assignment_id(reviewer: str, queue_id: str, blind_secret: str) -> str:
    """Stable external-only opaque handle; never derive it from a public ID alone."""
    if not blind_secret or len(blind_secret) < 16:
        raise ValueError("blind assignment secret must contain at least 16 characters")
    token = hmac.new(blind_secret.encode("utf-8"), f"{reviewer}:{queue_id}".encode("utf-8"), hashlib.sha256).hexdigest()
    return f"assignment_{reviewer}_{token[:24]}"


def _load_verified_restricted_packets(manifest: dict[str, Any], packet_dir: Path, root: Path) -> dict[str, dict[str, Any]]:
    """Replay every restricted row against the frozen queue, not just file hashes."""
    packet_dir = _outside_root(packet_dir, root, "restricted review packet directory")
    raw: dict[str, dict[str, Any]] = {}
    frozen_rows = {queue["queue_id"]: queue for queue in manifest["queue"]}
    for split in ("development", "heldout"):
        path = packet_dir / f"parser-review-{split}-restricted.jsonl"; content = path.read_bytes()
        if digest(content) != manifest["restricted_packet_sha256"][split]:
            raise ValueError(f"restricted {split} packet digest does not match frozen manifest")
        for row in _read_jsonl(path):
            if set(row) != {"queue_id", "input_sha256", "strata", "split", "profile", "listing"}:
                raise ValueError("restricted packet has unsupported fields")
            if input_sha256(row["profile"], row["listing"]) != row["input_sha256"]:
                raise ValueError("restricted packet input hash does not replay profile/listing")
            frozen = frozen_rows.get(row["queue_id"])
            if not frozen or row["input_sha256"] != frozen["input_sha256"] or row["split"] != split or row["split"] != frozen["split"] or row["strata"] != frozen["strata"]:
                raise ValueError("restricted packet does not exactly match frozen queue split/strata/input")
            if row["queue_id"] in raw:
                raise ValueError("restricted packets contain duplicate queue IDs")
            raw[row["queue_id"]] = row
    if set(raw) != set(frozen_rows):
        raise ValueError("restricted packets do not exactly cover frozen queue")
    return raw


def build_blind_packages(manifest: dict[str, Any], packet_dir: Path, output_dir: Path, blind_secret: str, root: Path) -> dict[str, Any]:
    """Issue separate A/B packets outside the release root.

    Packets retain restricted replay data, while their returned/reportable ledger
    contains only opaque assignment IDs and cryptographic bindings.  Split and
    queue identifiers are intentionally absent from reviewer packets.
    """
    # The public queue currently exposes unsalted input_sha256 plus split.  A
    # reviewer can recompute that hash from this packet's profile/listing and
    # join it back to the held-out mapping.  Do not issue a falsely "blind"
    # packet until an external keyed commitment/mapping protocol replaces it.
    raise ValueError("blind package issuance is disabled: public unsalted input hashes make held-out assignments linkable; require external keyed commitments and split mapping")


def _quarantined_unissuable_blind_packet_implementation(manifest: dict[str, Any], packet_dir: Path, output_dir: Path, blind_secret: str, root: Path) -> dict[str, Any]:
    """Removed issuer retained as an explicit fail-closed compatibility stub."""
    raise ValueError("unsafe blind packet issuer was removed; external keyed commitments and split mapping are required")


def _validate_issued_assignment(assignment: dict[str, Any], ledger: dict[str, Any]) -> None:
    required = {"schema_version", "status", "queue_manifest_sha256", "assignment_count", "assignments", "formal_gold_written", "ledger_sha256"}
    if not isinstance(ledger, dict) or set(ledger) != required or ledger.get("schema_version") != "1.0-p3.5" or ledger.get("status") != "external_blind_packets_issued" or ledger.get("formal_gold_written") is not False or ledger.get("assignment_count") != 400:
        raise ValueError("issued assignment ledger is malformed")
    if ledger.get("ledger_sha256") != digest(canonical_bytes({key: value for key, value in ledger.items() if key != "ledger_sha256"})):
        raise ValueError("issued assignment ledger digest is invalid")
    assignments = ledger.get("assignments")
    if not isinstance(assignments, list) or len(assignments) != 400 or len({row.get("assignment_id") for row in assignments if isinstance(row, dict)}) != 400:
        raise ValueError("issued assignment ledger assignment count or IDs are invalid")
    for row in assignments:
        if not isinstance(row, dict) or set(row) != {"assignment_id", "reviewer", "input_sha256"} or not isinstance(row.get("assignment_id"), str) or not re.fullmatch(r"assignment_annotator_[ab]_[a-f0-9]{24}", row["assignment_id"]) or row.get("reviewer") not in {"annotator_a", "annotator_b"} or not isinstance(row.get("input_sha256"), str) or not re.fullmatch(r"[A-F0-9]{64}", row["input_sha256"]):
            raise ValueError("issued assignment ledger contains invalid assignment fields")
    if set(assignment) != {"assignment_id", "reviewer", "input_sha256"} or assignment not in ledger["assignments"]:
        raise ValueError("receipt assignment is not present in issued assignment ledger")


def canonical_decision_receipt_payload(assignment: dict[str, Any], decision: dict[str, Any], queue_id: str, issued_assignment_ledger: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    """Convert an opaque assignment into the verifier-compatible signed row.

    The queue ID is resolved only by the controlled receipt consumer, after the
    reviewer has submitted an opaque assignment; it is never in blind packets.
    """
    _validate_issued_assignment(assignment, issued_assignment_ledger)
    manifest_errors = validate_manifest(manifest)
    if manifest_errors or issued_assignment_ledger["queue_manifest_sha256"] != manifest.get("manifest_sha256"):
        raise ValueError("receipt does not bind a valid frozen queue manifest")
    if queue_id not in {row["queue_id"] for row in manifest["queue"]}:
        raise ValueError("receipt queue ID is not in frozen manifest")
    allowed = {"expected_canonical_item_ids", "expected_polarity"}
    if set(decision) != allowed:
        raise ValueError("receipt decision has unsupported fields")
    items, polarity = decision["expected_canonical_item_ids"], decision["expected_polarity"]
    if not isinstance(items, list) or not items or len(items) != len(set(items)) or any(not isinstance(item, str) or not re.fullmatch(r"item_[a-z0-9_]+", item) for item in items):
        raise ValueError("receipt requires unique canonical item IDs")
    if polarity not in {"owned", "confirmed_missing", "unknown"}:
        raise ValueError("receipt polarity is invalid")
    if not isinstance(queue_id, str) or not re.fullmatch(r"parser_review_[a-f0-9]{20}", queue_id):
        raise ValueError("receipt queue ID is invalid")
    payload = {"decision_id": "receipt_" + digest(assignment["assignment_id"].encode("utf-8"))[:20].lower(), "queue_id": queue_id, "input_sha256": assignment["input_sha256"], "reviewer": assignment["reviewer"], "expected_canonical_item_ids": items, "expected_polarity": polarity}
    return payload | {"decision_commitment_sha256": digest(canonical_bytes(payload))}


def build_conflict_packet(manifest: dict[str, Any], decisions_a: Path, decisions_b: Path, output: Path, root: Path) -> dict[str, Any]:
    """Create a minimal adjudication packet for precisely the A/B conflicts."""
    # We deliberately do not call the verifier above: it rejects a missing
    # adjudication by design.  Load and compare signed ledgers using its same
    # strict parsers, then export no raw replay data.
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("invalid queue manifest: " + "; ".join(errors))
    a = {row["queue_id"]: row for row in _verify_decision_ledger(decisions_a, "annotator_a", root, manifest["manifest_sha256"])}
    b = {row["queue_id"]: row for row in _verify_decision_ledger(decisions_b, "annotator_b", root, manifest["manifest_sha256"])}
    def signer(path: Path) -> str:
        return json.loads(path.with_suffix(path.suffix + ".commitment.json").read_text(encoding="utf-8"))["fingerprint"]
    if signer(decisions_a) == signer(decisions_b):
        raise ValueError("annotator A and B require independent signing keys")
    expected = {row["queue_id"]: row for row in manifest.get("queue", [])}
    if set(a) != set(expected) or set(b) != set(expected):
        raise ValueError("both reviewer ledgers must cover the frozen queue before adjudication")
    for reviewer, ledger in (("annotator_a", a), ("annotator_b", b)):
        for qid, row in ledger.items():
            payload = _decision_payload(row)
            if payload["reviewer"] != reviewer or row["decision_commitment_sha256"] != digest(canonical_bytes(payload)) or payload["input_sha256"] != expected[qid]["input_sha256"]:
                raise ValueError("conflict packet decisions do not exactly bind frozen queue inputs")
    conflicts = []
    for qid in sorted(expected):
        left, right = _decision_payload(a[qid]), _decision_payload(b[qid])
        if a[qid].get("decision_commitment_sha256") != digest(canonical_bytes(left)) or b[qid].get("decision_commitment_sha256") != digest(canonical_bytes(right)):
            raise ValueError("conflict packet requires immutable decision commitments")
        if (left["expected_canonical_item_ids"], left["expected_polarity"]) != (right["expected_canonical_item_ids"], right["expected_polarity"]):
            conflicts.append({"conflict_id": "conflict_" + digest(qid.encode("utf-8"))[:20].lower(), "queue_id": qid, "input_sha256": expected[qid]["input_sha256"], "annotator_a_commitment_sha256": a[qid]["decision_commitment_sha256"], "annotator_b_commitment_sha256": b[qid]["decision_commitment_sha256"]})
    output = _safe_workflow_output(output, root, "adjudication packet")
    packet = {"schema_version": "1.0-p3.5", "status": "external_conflict_only_adjudication", "queue_manifest_sha256": manifest.get("manifest_sha256"), "conflict_count": len(conflicts), "conflicts": conflicts, "formal_gold_written": False}
    packet["packet_sha256"] = digest(canonical_bytes(packet))
    output.write_bytes(canonical_bytes(packet))
    return packet


def preflight_report(manifest: dict[str, Any], packet_dir: Path, root: Path) -> dict[str, Any]:
    """Safe report: verifies readiness without exposing restricted content."""
    errors = validate_manifest(manifest)
    if not errors:
        try:
            _load_verified_restricted_packets(manifest, packet_dir, root)
        except (OSError, ValueError) as exc:
            errors.append(f"restricted packet verification failed: {exc}")
    errors.append("blind issuance disabled: public unsalted input hashes make held-out assignments linkable; external keyed commitments and split mapping are required")
    return {"schema_version": "1.0-p3.5", "status": "ready_for_external_review" if not errors else "not_ready", "queue_manifest_sha256": manifest.get("manifest_sha256"), "queue_size": manifest.get("queue_size"), "errors": errors, "formal_gold_written": False}


def import_candidate_ledger(manifest: dict[str, Any], decisions_a: Path, decisions_b: Path, adjudications: Path | None, output: Path, root: Path) -> dict[str, Any]:
    """Import verified external decisions into a non-gold, hash-only candidate ledger."""
    output = _safe_workflow_output(output, root, "candidate import output")
    summary = verify_decision_commitments(manifest, decisions_a, decisions_b, adjudications, root)
    a = {row["queue_id"]: row for row in _verify_decision_ledger(decisions_a, "annotator_a", root, manifest["manifest_sha256"])}
    b = {row["queue_id"]: row for row in _verify_decision_ledger(decisions_b, "annotator_b", root, manifest["manifest_sha256"])}
    candidates = []
    for queue in manifest["queue"]:
        qid = queue["queue_id"]
        left, right = _decision_payload(a[qid]), _decision_payload(b[qid])
        if (left["expected_canonical_item_ids"], left["expected_polarity"]) == (right["expected_canonical_item_ids"], right["expected_polarity"]):
            candidates.append({"candidate_id": "candidate_" + digest(qid.encode("utf-8"))[:20].lower(), "input_sha256": queue["input_sha256"], "expected_canonical_item_ids": left["expected_canonical_item_ids"], "expected_polarity": left["expected_polarity"], "source": "independent_ab_agreement"})
    ledger = {"schema_version": "1.0-p3.5", "status": "candidate_labels_only", "queue_manifest_sha256": manifest["manifest_sha256"], "candidate_count": len(candidates), "conflict_count": summary["disagreement_count"], "candidates": candidates, "formal_gold_written": False}
    ledger["ledger_sha256"] = digest(canonical_bytes(ledger))
    output.write_bytes(canonical_bytes(ledger))
    return ledger


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze parser review packets outside the release root.")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-queue"); build.add_argument("--source", type=Path, required=True); build.add_argument("--source-sha256", required=True); build.add_argument("--manifest-out", type=Path, required=True); build.add_argument("--packet-dir", type=Path, required=True); build.add_argument("--root", type=Path, default=ROOT)
    keyed_publish = sub.add_parser("publish-keyed-manifest", help="publish a signed custodian's non-linkable keyed cohort manifest")
    keyed_publish.add_argument("--custodian-contract", type=Path, required=True); keyed_publish.add_argument("--custodian-authority-bundle", type=Path, required=True); keyed_publish.add_argument("--custodian-authority-bundle-sha256", required=True); keyed_publish.add_argument("--manifest-out", type=Path, required=True); keyed_publish.add_argument("--root", type=Path, default=ROOT)
    keyed_issue = sub.add_parser("issue-keyed-blind-packages", help="copy only contract-bound, already-issued custodian blind packets")
    keyed_issue.add_argument("--custodian-contract", type=Path, required=True); keyed_issue.add_argument("--custodian-authority-bundle", type=Path, required=True); keyed_issue.add_argument("--custodian-authority-bundle-sha256", required=True); keyed_issue.add_argument("--assignment-ledger", type=Path, required=True); keyed_issue.add_argument("--packet-dir", type=Path, required=True); keyed_issue.add_argument("--output-dir", type=Path, required=True); keyed_issue.add_argument("--root", type=Path, default=ROOT)
    packages = sub.add_parser("build-blind-packages"); packages.add_argument("--manifest", type=Path, required=True); packages.add_argument("--packet-dir", type=Path, required=True); packages.add_argument("--output-dir", type=Path, required=True); packages.add_argument("--blind-secret", required=True); packages.add_argument("--root", type=Path, default=ROOT)
    receipt = sub.add_parser("decision-receipt-payload"); receipt.add_argument("--assignment", type=Path, required=True); receipt.add_argument("--assignment-ledger", type=Path, required=True); receipt.add_argument("--decision", type=Path, required=True); receipt.add_argument("--manifest", type=Path, required=True); receipt.add_argument("--output", type=Path, required=True); receipt.add_argument("--root", type=Path, default=ROOT)
    conflict = sub.add_parser("build-conflict-packet"); conflict.add_argument("--manifest", type=Path, required=True); conflict.add_argument("--decisions-a", type=Path, required=True); conflict.add_argument("--decisions-b", type=Path, required=True); conflict.add_argument("--output", type=Path, required=True); conflict.add_argument("--root", type=Path, default=ROOT)
    preflight = sub.add_parser("preflight"); preflight.add_argument("--manifest", type=Path, required=True); preflight.add_argument("--packet-dir", type=Path, required=True); preflight.add_argument("--output", type=Path, required=True); preflight.add_argument("--root", type=Path, default=ROOT)
    importer = sub.add_parser("import-candidate-ledger"); importer.add_argument("--manifest", type=Path, required=True); importer.add_argument("--decisions-a", type=Path, required=True); importer.add_argument("--decisions-b", type=Path, required=True); importer.add_argument("--adjudications", type=Path); importer.add_argument("--output", type=Path, required=True); importer.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    if args.command == "build-queue": build_queue(args.root.resolve(), args.source, args.source_sha256, args.manifest_out.resolve(), args.packet_dir)
    elif args.command == "publish-keyed-manifest":
        publish_keyed_queue_manifest(args.custodian_contract, args.manifest_out, args.root.resolve(), args.custodian_authority_bundle, args.custodian_authority_bundle_sha256)
    elif args.command == "issue-keyed-blind-packages":
        issue_keyed_blind_packages(args.custodian_contract, args.assignment_ledger, args.packet_dir, args.output_dir, args.root.resolve(), args.custodian_authority_bundle, args.custodian_authority_bundle_sha256)
    elif args.command == "build-blind-packages":
        manifest = json.loads(args.manifest.read_text(encoding="utf-8")); build_blind_packages(manifest, args.packet_dir, args.output_dir, args.blind_secret, args.root.resolve())
    elif args.command == "decision-receipt-payload":
        output = _safe_workflow_output(args.output, args.root.resolve(), "decision receipt payload")
        assignment = json.loads(args.assignment.read_text(encoding="utf-8")); manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        issued_ledger = json.loads(args.assignment_ledger.read_text(encoding="utf-8")); _validate_issued_assignment(assignment, issued_ledger)
        if issued_ledger["queue_manifest_sha256"] != manifest.get("manifest_sha256"):
            raise ValueError("issued assignment ledger does not bind this queue manifest")
        matches = [row["queue_id"] for row in manifest.get("queue", []) if row["input_sha256"] == assignment.get("input_sha256")]
        if len(matches) != 1: raise ValueError("assignment does not resolve to exactly one frozen queue row")
        output.write_bytes(canonical_bytes(canonical_decision_receipt_payload(assignment, json.loads(args.decision.read_text(encoding="utf-8")), matches[0], issued_ledger, manifest)))
    elif args.command == "build-conflict-packet":
        build_conflict_packet(json.loads(args.manifest.read_text(encoding="utf-8")), args.decisions_a, args.decisions_b, args.output, args.root.resolve())
    elif args.command == "preflight":
        _safe_workflow_output(args.output, args.root.resolve(), "preflight output").write_bytes(canonical_bytes(preflight_report(json.loads(args.manifest.read_text(encoding="utf-8")), args.packet_dir, args.root.resolve())))
    elif args.command == "import-candidate-ledger":
        import_candidate_ledger(json.loads(args.manifest.read_text(encoding="utf-8")), args.decisions_a, args.decisions_b, args.adjudications, args.output, args.root.resolve())


if __name__ == "__main__": main()
