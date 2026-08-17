#!/usr/bin/env python3
"""Replay a privacy-preserving, externally attested parser gold set.

The repository stores labels and a hash of a minimal parser input, never the
underlying listing/profile text.  Raw replay inputs and the authority bundle
are injected by the evaluator invocation and are intentionally not artifacts
of a release.  Development labels may document rule development; held-out
labels are rejected if they are named by the supplied rule-input manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = "sky-parser-gold-audit-v1"
GOLD_REL = Path("data/review/parser-gold/claims.jsonl")
RULE_MANIFEST_REL = Path("data/review/parser-gold/rule-development-manifest.json")
ATTESTATIONS_REL = Path("data/review/parser-gold/attestations.jsonl")
SIGNATURES_REL = Path("data/review/parser-gold/signatures")
AUTHORITY_ENV = "SKY_PARSER_GOLD_AUTHORITY_BUNDLE"
AUTHORITY_SHA_ENV = "SKY_PARSER_GOLD_AUTHORITY_BUNDLE_SHA256"
KEYED_AUTHORITY_ENV = "SKY_PARSER_KEYED_CUSTODIAN_AUTHORITY_BUNDLE"
KEYED_AUTHORITY_SHA_ENV = "SKY_PARSER_KEYED_CUSTODIAN_AUTHORITY_BUNDLE_SHA256"
KEYED_CONTRACT_ENV = "SKY_PARSER_KEYED_CUSTODIAN_CONTRACT"
KEYED_CONTRACT_SHA_ENV = "SKY_PARSER_KEYED_CUSTODIAN_CONTRACT_SHA256"
KEYED_BINDING_ENV = "SKY_PARSER_KEYED_REPLAY_BINDING"
KEYED_BINDING_SHA_ENV = "SKY_PARSER_KEYED_REPLAY_BINDING_SHA256"
KEYED_BINDING_NAMESPACE = "sky-parser-keyed-replay-binding-v2"
ROLES = ("annotator_a", "annotator_b", "adjudicator")
POLARITIES = frozenset({"owned", "confirmed_missing", "unknown"})
SPLITS = frozenset({"development", "heldout"})
REQUIRED_STRATA = ("account_type", "era", "season", "collaboration", "set_context")
MINIMUM_DISTINCT_STRATA_VALUES = 2


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def input_sha256(profile: dict[str, Any], listing: dict[str, Any]) -> str:
    """Hash only the exact structured inputs passed to the parser."""
    return sha256_bytes(canonical_bytes({"listing": listing, "profile": profile}))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}: JSONL row is not an object")
            rows.append(row)
    return rows


def _fingerprint(public_key: str) -> str | None:
    child = subprocess.run(["ssh-keygen", "-lf", "-"], input=public_key + "\n", text=True, capture_output=True, check=False)
    fields = child.stdout.strip().split()
    return fields[1] if child.returncode == 0 and len(fields) >= 2 else None


def gold_ledger_sha256(rows: list[dict[str, Any]]) -> str:
    return sha256_bytes(b"".join(canonical_bytes(row) for row in rows))


def parser_source_sha256(root: Path) -> str:
    return sha256_bytes((root / "tools/modeling/parse_item_vectors.py").read_bytes())


def parser_config_sha256() -> str:
    from tools.modeling.parse_item_vectors import NEGATION_PREFIXES, STATES
    return sha256_bytes(canonical_bytes({"negation_prefixes": list(NEGATION_PREFIXES), "states": sorted(STATES)}))


def manifest_payload(manifest: dict[str, Any]) -> bytes:
    return canonical_bytes({key: value for key, value in manifest.items() if key != "manifest_sha256"})


def attestation_payload(gold_row: dict[str, Any], manifest: dict[str, Any], attestation: dict[str, Any]) -> bytes:
    signed = {key: value for key, value in attestation.items() if key != "payload_sha256"}
    return canonical_bytes({"contract": NAMESPACE, "gold": gold_row, "rule_development_manifest": manifest, "attestation": signed})


def _outside_root(path_value: str | Path | None, root: Path, purpose: str) -> Path:
    if path_value is None:
        raise ValueError(f"{purpose} path must be injected")
    path = Path(path_value).expanduser().resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        return path
    raise ValueError(f"{purpose} must be outside the release root")


def _keyed_binding_payload(binding: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in binding.items() if key not in {"signature_file", "binding_sha256"}}


def _validate_keyed_binding_coverage(gold: list[dict[str, Any]], rows: list[dict[str, Any]], cohort_commitments: list[str]) -> None:
    """Require an injective gold-to-cohort mapping and exact coverage at threshold."""
    if len(gold) > 200:
        raise ValueError("formal parser gold cannot exceed the fixed 200-row keyed cohort")
    row_commitments = [row.get("keyed_commitment") for row in rows if isinstance(row, dict)]
    if len(row_commitments) != len(set(row_commitments)):
        raise ValueError("external keyed replay binding reuses a cohort commitment")
    if len(gold) == 200:
        if len(rows) != 200 or set(row_commitments) != set(cohort_commitments):
            raise ValueError("complete parser gold must bijectively cover all 200 keyed cohort commitments")
        split_counts = Counter(str(row.get("split")) for row in rows)
        if split_counts != {"development": 100, "heldout": 100}:
            raise ValueError("complete parser gold must preserve the fixed 100/100 keyed split")


def _verify_keyed_binding(root: Path, gold: list[dict[str, Any]], authority_bundle: str | Path | None, authority_bundle_sha256: str | None, contract_path: str | Path | None, contract_sha256: str | None, binding_path: str | Path | None, binding_sha256: str | None) -> list[str]:
    """Replay the private keyed mapping for every formal gold row.

    The mapping is injected outside the release.  Its signed rows prove that
    each public gold hash and split is an entry in the custodian's committed
    cohort, while the release manifest stays aggregate-only.
    """
    from tools.parser_review.onboarding import (
        KEYED_CUSTODIAN_ROLE, keyed_commitment_merkle_root, keyed_split_commitment,
        load_keyed_custodian_authorities,
        validate_keyed_custodian_contract,
    )
    try:
        authorities = load_keyed_custodian_authorities(authority_bundle or os.environ.get(KEYED_AUTHORITY_ENV), authority_bundle_sha256 or os.environ.get(KEYED_AUTHORITY_SHA_ENV), root)
        contract_file = _outside_root(contract_path or os.environ.get(KEYED_CONTRACT_ENV), root, "external keyed custodian contract")
        expected_contract_sha = contract_sha256 or os.environ.get(KEYED_CONTRACT_SHA_ENV)
        if not expected_contract_sha or not contract_file.is_file() or sha256_bytes(contract_file.read_bytes()) != str(expected_contract_sha).upper():
            raise ValueError("external keyed custodian contract SHA-256 does not match injected digest")
        contract = json.loads(contract_file.read_text(encoding="utf-8"))
        validate_keyed_custodian_contract(contract, contract_file, root, authority_bundle or os.environ.get(KEYED_AUTHORITY_ENV), authority_bundle_sha256 or os.environ.get(KEYED_AUTHORITY_SHA_ENV))
        manifest = json.loads((root / "data/review/parser-gold/review-queue-manifest.json").read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0-p3.7" or manifest.get("status") != "keyed_frozen_pending_external_decisions":
            raise ValueError("nonempty parser gold requires a P3.7 keyed public manifest")
        for key in ("cohort_id", "commitment_merkle_root", "split_commitment", "custodian_id", "custodian_authority_id", "custodian_fingerprint", "custodian_contract_sha256"):
            contract_key = {"custodian_authority_id": "authority_id", "custodian_fingerprint": "fingerprint", "custodian_contract_sha256": "contract_sha256"}.get(key, key)
            if manifest.get(key) != contract.get(contract_key):
                raise ValueError("keyed public manifest does not match verified custodian contract")
        binding_file = _outside_root(binding_path or os.environ.get(KEYED_BINDING_ENV), root, "external keyed replay binding")
        expected_binding_sha = binding_sha256 or os.environ.get(KEYED_BINDING_SHA_ENV)
        if not expected_binding_sha or not binding_file.is_file() or sha256_bytes(binding_file.read_bytes()) != str(expected_binding_sha).upper():
            raise ValueError("external keyed replay binding SHA-256 does not match injected digest")
        binding = json.loads(binding_file.read_text(encoding="utf-8"))
        required = {"schema_version", "contract_type", "cohort_id", "custodian_contract_sha256", "commitment_merkle_root", "split_commitment", "authority_id", "fingerprint", "cohort_keyed_commitments", "binding_rows", "decision_ledger_sha256", "adjudication_ledger_sha256", "finalization_sha256", "public_gold_sha256", "rule_manifest_sha256", "signature_file", "binding_sha256"}
        legacy_required = required - {"decision_ledger_sha256", "adjudication_ledger_sha256", "finalization_sha256", "public_gold_sha256", "rule_manifest_sha256"}
        legacy_binding = isinstance(binding, dict) and binding.get("schema_version") == "1.0-p3.7"
        if not isinstance(binding, dict) or set(binding) != (legacy_required if legacy_binding else required) or binding.get("schema_version") != ("1.0-p3.7" if legacy_binding else "2.0-p3.8") or binding.get("contract_type") != "parser_review_keyed_replay_binding":
            raise ValueError("external keyed replay binding has unsupported schema")
        for key in ("cohort_id", "custodian_contract_sha256", "commitment_merkle_root", "split_commitment"):
            if binding.get(key) != manifest.get(key):
                raise ValueError("external keyed replay binding does not bind the public keyed cohort")
        if binding.get("authority_id") != contract.get("authority_id") or binding.get("fingerprint") != contract.get("fingerprint"):
            raise ValueError("external keyed replay binding is not signed by the contracted custodian authority")
        authority = authorities.get(binding.get("authority_id"))
        if not authority or authority.get("fingerprint") != binding.get("fingerprint") or KEYED_CUSTODIAN_ROLE not in authority.get("roles", []):
            raise ValueError("external keyed replay binding authority is missing, revoked, or unauthorized")
        if binding.get("binding_sha256") != sha256_bytes(canonical_bytes(_keyed_binding_payload(binding))):
            raise ValueError("external keyed replay binding digest does not bind its payload")
        signature_name = binding.get("signature_file")
        if not isinstance(signature_name, str) or Path(signature_name).name != signature_name:
            raise ValueError("external keyed replay binding signature path is invalid")
        signature = binding_file.parent / signature_name
        if not signature.is_file():
            raise ValueError("external keyed replay binding detached signature is missing")
        with tempfile.TemporaryDirectory(prefix="sky-parser-keyed-binding-") as temporary:
            allowed = Path(temporary) / "allowed_signers"; allowed.write_text(f"{binding['authority_id']} {authority['public_key'].strip()}\n", encoding="utf-8", newline="\n")
            signed = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", str(binding["authority_id"]), "-n", "sky-parser-keyed-replay-binding-v1" if legacy_binding else KEYED_BINDING_NAMESPACE, "-s", str(signature)], input=canonical_bytes(_keyed_binding_payload(binding)), capture_output=True, check=False)
        if signed.returncode:
            raise ValueError("external keyed replay binding detached signature verification failed")
        if not legacy_binding:
            if binding.get("public_gold_sha256") != gold_ledger_sha256(gold):
                raise ValueError("external keyed replay binding does not bind the exact public gold ledger")
            rule_manifest = json.loads((root / RULE_MANIFEST_REL).read_text(encoding="utf-8"))
            if binding.get("rule_manifest_sha256") != rule_manifest.get("manifest_sha256") or rule_manifest.get("manifest_sha256") != sha256_bytes(manifest_payload(rule_manifest)):
                raise ValueError("external keyed replay binding does not bind the exact rule-development manifest")
        cohort_commitments = binding.get("cohort_keyed_commitments")
        if not isinstance(cohort_commitments, list) or len(cohort_commitments) != 200:
            raise ValueError("external keyed replay binding must provide exactly 200 opaque cohort commitments")
        if keyed_commitment_merkle_root(cohort_commitments) != manifest["commitment_merkle_root"]:
            raise ValueError("external keyed replay binding commitments do not reproduce custodian Merkle root")
        rows = binding.get("binding_rows")
        if not isinstance(rows, list) or len(rows) != len(gold):
            raise ValueError("external keyed replay binding rows do not cover formal gold")
        _validate_keyed_binding_coverage(gold, rows, cohort_commitments)
        if not legacy_binding and keyed_split_commitment(rows) != manifest["split_commitment"]:
            raise ValueError("external keyed replay binding does not reproduce the fixed keyed split commitment")
        gold_by_id = {str(row["gold_id"]): row for row in gold}; seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"gold_id", "input_sha256", "keyed_commitment", "split"}:
                raise ValueError("external keyed replay binding row has unsupported fields")
            gold_id = row.get("gold_id"); gold_row = gold_by_id.get(gold_id)
            # V2 formal gold intentionally has neither an input digest nor a
            # split label.  The signed external binding alone resolves both.
            if gold_row is None or gold_id in seen or (gold_row.get("input_sha256") != row.get("input_sha256") if legacy_binding else gold_row.get("keyed_commitment") != row.get("keyed_commitment")):
                raise ValueError("external keyed replay binding row does not exactly bind a gold row")
            if not isinstance(row.get("keyed_commitment"), str) or len(str(row["keyed_commitment"])) != 64 or any(char not in "0123456789ABCDEF" for char in str(row["keyed_commitment"])):
                raise ValueError("external keyed replay binding commitment is invalid")
            if row["keyed_commitment"] not in cohort_commitments:
                raise ValueError("external keyed replay binding row commitment is absent from custodian cohort")
            seen.add(str(gold_id))
        if seen != set(gold_by_id):
            raise ValueError("external keyed replay binding omits or duplicates gold rows")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [str(exc)]
    return []


def _external_bundle(path_value: str | Path | None, expected_sha: str | None, root: Path) -> tuple[dict[str, dict[str, Any]] | None, list[str]]:
    path_value = path_value or os.environ.get(AUTHORITY_ENV)
    expected_sha = expected_sha or os.environ.get(AUTHORITY_SHA_ENV)
    if not path_value or not expected_sha:
        return None, ["external parser-gold authority bundle path and SHA-256 must be injected for nonempty gold"]
    path = Path(path_value).expanduser().resolve()
    try:
        path.relative_to(root.resolve())
        return None, ["external parser-gold authority bundle must be outside the release root"]
    except ValueError:
        pass
    if not path.is_file():
        return None, ["external parser-gold authority bundle is missing"]
    if sha256_bytes(path.read_bytes()) != str(expected_sha).upper():
        return None, ["external parser-gold authority bundle SHA-256 does not match injected digest"]
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, ["external parser-gold authority bundle is not valid JSON"]
    if not isinstance(bundle, dict) or bundle.get("schema_version") != "sky-parser-gold-authority-bundle-v1":
        return None, ["external parser-gold authority bundle has unsupported schema_version"]
    records, revoked = bundle.get("authorities"), set(bundle.get("revoked_fingerprints", []))
    if not isinstance(records, list):
        return None, ["external parser-gold authority bundle has no authorities array"]
    errors: list[str] = []; authorities: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict): errors.append("external parser-gold authority is not an object"); continue
        authority_id, public_key, roles = record.get("authority_id"), record.get("public_key"), record.get("roles")
        fingerprint = _fingerprint(public_key) if isinstance(public_key, str) else None
        if not isinstance(authority_id, str) or authority_id in authorities or not isinstance(roles, list) or not fingerprint or record.get("fingerprint") != fingerprint:
            errors.append("external parser-gold authority has invalid identity, key, roles, fingerprint, or duplicate ID"); continue
        if fingerprint in revoked: errors.append(f"external parser-gold authority {authority_id} fingerprint is revoked"); continue
        authorities[authority_id] = record
    return (authorities if not errors else None), errors


def external_replay_inputs(path_value: Path | None, expected_sha: str | None, root: Path) -> list[dict[str, Any]]:
    if path_value is None or not expected_sha: raise ValueError("external replay inputs path and SHA-256 must be injected for nonempty parser gold")
    path = path_value.expanduser().resolve()
    try: path.relative_to(root.resolve())
    except ValueError: pass
    else: raise ValueError("external replay inputs must be outside the release root")
    if not path.is_file(): raise ValueError("external replay inputs are missing")
    if sha256_bytes(path.read_bytes()) != expected_sha.upper(): raise ValueError("external replay inputs SHA-256 does not match injected digest")
    return read_jsonl(path)


def validate_gold_rows(rows: list[dict[str, Any]]) -> list[str]:
    """Validate the public V2 ledger without recreating a joinable split map."""
    errors: list[str] = []; ids: set[str] = set(); commitments: set[str] = set()
    v1_allowed = {"gold_id", "input_sha256", "expected_canonical_item_ids", "expected_polarity", "split", "strata"}
    v2_allowed = {"gold_id", "keyed_commitment", "expected_canonical_item_ids", "expected_polarity", "strata"}
    for row in rows:
        gold_id = row.get("gold_id"); commitment = row.get("keyed_commitment"); targets = row.get("expected_canonical_item_ids")
        legacy = set(row) == v1_allowed
        if set(row) != v1_allowed and set(row) != v2_allowed: errors.append(f"{gold_id}: gold row contains non-contract fields (raw text/PII is forbidden)")
        if not isinstance(gold_id, str) or not gold_id.startswith("parser_gold_") or gold_id in ids: errors.append("parser gold_id is missing or duplicated")
        ids.add(str(gold_id))
        if legacy:
            value = row.get("input_sha256")
            if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789ABCDEF" for char in value): errors.append(f"{gold_id}: input_sha256 is invalid")
            if value in commitments: errors.append(f"{gold_id}: input_sha256 is reused across rows")
            commitments.add(str(value))
            if row.get("split") not in SPLITS: errors.append(f"{gold_id}: split is invalid")
        else:
            if not isinstance(commitment, str) or len(commitment) != 64 or any(char not in "0123456789ABCDEF" for char in commitment): errors.append(f"{gold_id}: keyed_commitment is invalid")
            if commitment in commitments: errors.append(f"{gold_id}: keyed_commitment is reused across rows")
            commitments.add(str(commitment))
        if not isinstance(targets, list) or not targets or len(targets) != len(set(targets)) or any(not isinstance(item, str) or not item.startswith("item_") for item in targets): errors.append(f"{gold_id}: expected canonical item IDs are invalid")
        if row.get("expected_polarity") not in POLARITIES: errors.append(f"{gold_id}: expected polarity is invalid")
        if not isinstance(row.get("strata"), dict) or set(row.get("strata", {})) != set(REQUIRED_STRATA) or any(not isinstance(row["strata"].get(key), str) or not row["strata"][key] for key in REQUIRED_STRATA):
            errors.append(f"{gold_id}: all required strata are required for sampling audit")
    return errors


def load_rule_manifest(root: Path, gold: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Load the signed rule-development boundary; callers cannot supply it."""
    path = root / RULE_MANIFEST_REL
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, [f"parser-gold rule-development manifest is unreadable: {exc}"]
    if not isinstance(manifest, dict): return {}, ["parser-gold rule-development manifest is not an object"]
    if not gold:
        return manifest, [] if manifest == {"schema_version": "1.0-p3.3", "status": "not_ready"} else ["empty parser gold requires deterministic not_ready rule-development manifest"]
    v1_allowed = {"schema_version", "gold_ledger_sha256", "parser_source_sha256", "parser_config_sha256", "development_input_hashes", "required_strata", "minimum_distinct_values_per_required_stratum", "manifest_sha256"}
    allowed = {"schema_version", "gold_ledger_sha256", "parser_source_sha256", "parser_config_sha256", "development_keyed_commitments", "required_strata", "minimum_distinct_values_per_required_stratum", "manifest_sha256"}
    errors: list[str] = []
    legacy = set(manifest) == v1_allowed and manifest.get("schema_version") == "1.0-p3.3"
    if not legacy and (set(manifest) != allowed or manifest.get("schema_version") != "2.0-p3.8"): errors.append("parser-gold rule-development manifest has unsupported fields or schema version")
    if manifest.get("manifest_sha256") != sha256_bytes(manifest_payload(manifest)): errors.append("parser-gold rule-development manifest digest does not bind its contents")
    if manifest.get("gold_ledger_sha256") != gold_ledger_sha256(gold): errors.append("parser-gold rule-development manifest does not bind the complete gold ledger")
    if manifest.get("parser_source_sha256") != parser_source_sha256(root): errors.append("parser-gold rule-development manifest parser source SHA-256 differs")
    if manifest.get("parser_config_sha256") != parser_config_sha256(): errors.append("parser-gold rule-development manifest parser config SHA-256 differs")
    commitments = manifest.get("development_input_hashes" if legacy else "development_keyed_commitments")
    if not isinstance(commitments, list) or commitments != sorted(commitments) or any(not isinstance(value, str) or len(value) != 64 for value in commitments): errors.append("parser-gold rule-development manifest commitments are invalid")
    if legacy and commitments != sorted(str(row["input_sha256"]) for row in gold if row.get("split") == "development"): errors.append("parser-gold rule-development manifest hashes must exactly equal development gold hashes")
    if manifest.get("required_strata") != list(REQUIRED_STRATA) or manifest.get("minimum_distinct_values_per_required_stratum") != MINIMUM_DISTINCT_STRATA_VALUES:
        errors.append("parser-gold rule-development manifest strata policy differs from contract")
    return manifest, errors


def audit_gold(root: Path, gold: list[dict[str, Any]], authority_bundle: str | Path | None = None, authority_bundle_sha256: str | None = None, keyed_authority_bundle: str | Path | None = None, keyed_authority_bundle_sha256: str | None = None, keyed_contract: str | Path | None = None, keyed_contract_sha256: str | None = None, keyed_replay_binding: str | Path | None = None, keyed_replay_binding_sha256: str | None = None) -> list[str]:
    errors = validate_gold_rows(gold)
    manifest, manifest_errors = load_rule_manifest(root, gold)
    errors.extend(manifest_errors)
    if not gold:
        try:
            if read_jsonl(root / ATTESTATIONS_REL): errors.append("parser-gold attestations exist without parser gold")
        except (OSError, ValueError, json.JSONDecodeError) as exc: errors.append(f"parser-gold attestation ledger is unreadable: {exc}")
        # A committed keyed-frozen state is a trust assertion, not merely a
        # self-hashed JSON document.  It therefore cannot pass a release
        # check without the injected, revocable custodian root and contract.
        try:
            queue = json.loads((root / "data/review/parser-gold/review-queue-manifest.json").read_text(encoding="utf-8"))
            if isinstance(queue, dict) and queue.get("status") == "keyed_frozen_pending_external_decisions":
                from tools.parser_review.onboarding import validate_keyed_custodian_contract
                contract_file = _outside_root(keyed_contract or os.environ.get(KEYED_CONTRACT_ENV), root, "external keyed custodian contract")
                expected = keyed_contract_sha256 or os.environ.get(KEYED_CONTRACT_SHA_ENV)
                if not expected or not contract_file.is_file() or sha256_bytes(contract_file.read_bytes()) != str(expected).upper():
                    raise ValueError("external keyed custodian contract SHA-256 does not match injected digest")
                contract = json.loads(contract_file.read_text(encoding="utf-8"))
                validate_keyed_custodian_contract(contract, contract_file, root, keyed_authority_bundle or os.environ.get(KEYED_AUTHORITY_ENV), keyed_authority_bundle_sha256 or os.environ.get(KEYED_AUTHORITY_SHA_ENV))
                if queue.get("custodian_contract_sha256") != contract.get("contract_sha256") or queue.get("commitment_merkle_root") != contract.get("commitment_merkle_root") or queue.get("split_commitment") != contract.get("split_commitment"):
                    raise ValueError("keyed public manifest does not match verified custodian contract")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))
        return errors
    errors.extend(_verify_keyed_binding(root, gold, keyed_authority_bundle, keyed_authority_bundle_sha256, keyed_contract, keyed_contract_sha256, keyed_replay_binding, keyed_replay_binding_sha256))
    # P3.8 replaces per-row public human attestations with a custodian-signed
    # finalization that binds the independently signed external ledgers.  Do
    # not require legacy in-repository signatures for the opaque V2 ledger.
    if gold and "keyed_commitment" in gold[0]:
        return errors
    authorities, authority_errors = _external_bundle(authority_bundle, authority_bundle_sha256, root)
    errors.extend(authority_errors)
    if authorities is None: return errors
    try: attestations = read_jsonl(root / ATTESTATIONS_REL)
    except (OSError, ValueError, json.JSONDecodeError) as exc: return errors + [f"parser-gold attestation ledger is unreadable: {exc}"]
    by_target: dict[str, list[dict[str, Any]]] = {}; seen_ids: set[str] = set(); signature_paths: set[str] = set()
    for entry in attestations:
        aid, sig = entry.get("attestation_id"), entry.get("signature_file")
        allowed = {"attestation_id", "gold_id", "role", "authority_id", "fingerprint", "rule_manifest_sha256", "payload_sha256", "signature_file"}
        if set(entry) != allowed:
            errors.append("parser-gold attestation contains non-contract fields")
        if not isinstance(aid, str) or aid in seen_ids: errors.append("parser-gold attestation_id is missing or duplicated")
        if not isinstance(aid, str) or not aid.startswith("parser_gold_attestation_"): errors.append("parser-gold attestation_id is invalid")
        if not isinstance(entry.get("gold_id"), str) or not str(entry["gold_id"]).startswith("parser_gold_"): errors.append("parser-gold attestation gold_id is invalid")
        if entry.get("role") not in ROLES: errors.append("parser-gold attestation role is invalid")
        if not isinstance(entry.get("authority_id"), str) or not str(entry["authority_id"]).startswith("parser_human_"): errors.append("parser-gold attestation authority_id is invalid")
        if not isinstance(entry.get("payload_sha256"), str) or len(str(entry["payload_sha256"])) != 64: errors.append("parser-gold attestation payload_sha256 is invalid")
        if entry.get("rule_manifest_sha256") != manifest.get("manifest_sha256"): errors.append("parser-gold attestation does not bind rule-development manifest")
        seen_ids.add(str(aid)); by_target.setdefault(str(entry.get("gold_id")), []).append(entry)
        if not isinstance(sig, str) or sig in signature_paths: errors.append("parser-gold signature_file is missing or reused")
        signature_paths.add(str(sig))
    for row in gold:
        gold_id = str(row.get("gold_id")); entries = by_target.get(gold_id, []); roles = [entry.get("role") for entry in entries]
        if len(entries) != 3 or set(roles) != set(ROLES): errors.append(f"{gold_id}: requires exactly one attestation for each parser-gold role"); continue
        fingerprints: set[str] = set()
        for entry in entries:
            role, authority_id, fingerprint = entry.get("role"), entry.get("authority_id"), entry.get("fingerprint")
            authority = authorities.get(authority_id) if isinstance(authority_id, str) else None
            if not authority or role not in authority.get("roles", []): errors.append(f"{gold_id}:{role}: authority is not authorized for this role"); continue
            if authority.get("fingerprint") != fingerprint: errors.append(f"{gold_id}:{role}: authority fingerprint does not match"); continue
            fingerprints.add(str(fingerprint)); payload = attestation_payload(row, manifest, entry)
            if entry.get("payload_sha256") != sha256_bytes(payload): errors.append(f"{gold_id}:{role}: payload hash does not bind gold row and rule-development manifest"); continue
            signature = root / str(entry.get("signature_file", ""))
            try: signature.resolve().relative_to((root / SIGNATURES_REL).resolve())
            except ValueError: errors.append(f"{gold_id}:{role}: signature path escapes parser-gold/signatures"); continue
            if not signature.is_file(): errors.append(f"{gold_id}:{role}: detached signature is missing"); continue
            with tempfile.TemporaryDirectory(prefix="sky-parser-gold-") as temporary:
                allowed = Path(temporary) / "allowed_signers"; allowed.write_text(f"{authority_id} {authority['public_key'].strip()}\n", encoding="utf-8", newline="\n")
                child = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", authority_id, "-n", NAMESPACE, "-s", str(signature)], input=payload, capture_output=True, check=False)
            if child.returncode: errors.append(f"{gold_id}:{role}: ssh-keygen detached signature verification failed")
        if len(fingerprints) != 3: errors.append(f"{gold_id}: three parser-gold roles require distinct authority fingerprints")
    if set(by_target) - {str(row.get("gold_id")) for row in gold}: errors.append("parser-gold attestation ledger references absent gold row")
    return errors


def _verified_binding_rows(root: Path, binding_path: str | Path | None, binding_sha256: str | None) -> list[dict[str, Any]]:
    """Return private replay rows only after ``audit_gold`` verified the bundle.

    This small loader deliberately performs no fallback and is kept private so
    callers cannot accidentally treat an unverified external file as gold.
    """
    path = _outside_root(binding_path or os.environ.get(KEYED_BINDING_ENV), root, "external keyed replay binding")
    expected = binding_sha256 or os.environ.get(KEYED_BINDING_SHA_ENV)
    if not expected or not path.is_file() or sha256_bytes(path.read_bytes()) != str(expected).upper():
        raise ValueError("external keyed replay binding SHA-256 does not match injected digest")
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("binding_rows") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("external keyed replay binding rows are missing")
    return rows


def _state_pairs(vector: dict[str, Any]) -> set[tuple[str, str]]:
    return {(str(row.get("item_id")), str(row.get("state"))) for row in vector.get("item_states", []) if row.get("state") in POLARITIES}


def _default_parser(profile: dict[str, Any], listing: dict[str, Any], root: Path) -> dict[str, Any]:
    from tools.modeling.parse_item_vectors import build_vector, load_catalog
    items, aliases = load_catalog(root)
    return build_vector(profile, listing, items, aliases, root)


def evaluate(root: Path, gold: list[dict[str, Any]], replay_inputs: list[dict[str, Any]], *, resolved_rows: list[dict[str, Any]] | None = None, parser: Callable[[dict[str, Any], dict[str, Any], Path], dict[str, Any]] | None = None) -> dict[str, Any]:
    errors = validate_gold_rows(gold)
    manifest, manifest_errors = load_rule_manifest(root, gold)
    errors.extend(manifest_errors)
    if errors: raise ValueError("; ".join(errors))
    legacy_gold = bool(gold and "input_sha256" in gold[0])
    if gold and resolved_rows is None and not legacy_gold:
        raise ValueError("V2 formal parser gold requires a verified external keyed replay binding")
    resolved_rows = resolved_rows or []
    if legacy_gold:
        resolved_rows = [{"gold_id": row["gold_id"], "input_sha256": row["input_sha256"], "keyed_commitment": row["input_sha256"], "split": row["split"]} for row in gold]
    if len(resolved_rows) != len(gold):
        raise ValueError("verified keyed replay binding rows do not cover formal parser gold")
    public_by_id = {str(row["gold_id"]): row for row in gold}
    internal_gold: list[dict[str, Any]] = []
    for private in resolved_rows:
        if not isinstance(private, dict) or set(private) != {"gold_id", "input_sha256", "keyed_commitment", "split"}:
            raise ValueError("verified keyed replay binding row has unsupported fields")
        public = public_by_id.get(str(private.get("gold_id")))
        if public is None or (public.get("input_sha256") != private.get("input_sha256") if legacy_gold else public.get("keyed_commitment") != private.get("keyed_commitment")):
            raise ValueError("verified keyed replay binding row does not match formal gold")
        internal_gold.append(public | {"input_sha256": private["input_sha256"], "split": private["split"]})
    if len({row["input_sha256"] for row in internal_gold}) != len(internal_gold):
        raise ValueError("verified keyed replay binding reuses an input hash")
    if gold and not legacy_gold:
        committed_development = manifest.get("development_keyed_commitments")
        actual_development = sorted(row["keyed_commitment"] for row in internal_gold if row["split"] == "development")
        if committed_development != actual_development:
            raise ValueError("rule-development manifest does not match the custodian-committed keyed split")
    gold_by_hash = {row["input_sha256"]: row for row in internal_gold}
    provided: dict[str, dict[str, Any]] = {}
    for row in replay_inputs:
        if set(row) != {"profile", "listing"} or not isinstance(row.get("profile"), dict) or not isinstance(row.get("listing"), dict): raise ValueError("replay input must contain only profile and listing objects")
        digest = input_sha256(row["profile"], row["listing"])
        if digest in provided: raise ValueError("replay input hash is duplicated")
        provided[digest] = row
    if set(provided) != set(gold_by_hash): raise ValueError("replay inputs must match parser gold input hashes exactly")
    rule_input_hashes = set(manifest.get("development_input_hashes", []))
    parse = parser or _default_parser; aggregate: dict[str, Counter[str]] = {"development": Counter(), "heldout": Counter()}; missing_metrics: dict[str, Counter[str]] = {"development": Counter(), "heldout": Counter()}; collision_rows: Counter[str] = Counter(); unknown_to_missing: Counter[str] = Counter()
    for digest, row in gold_by_hash.items():
        expected_ids = set(row["expected_canonical_item_ids"])
        expected = {(item_id, row["expected_polarity"]) for item_id in expected_ids}
        full_actual = _state_pairs(parse(provided[digest]["profile"], provided[digest]["listing"], root))
        # Every catalog item has an unknown state, so score only the labelled
        # targets.  A non-unknown output for a different ID remains a
        # collision and is counted separately.
        actual = {(item_id, polarity) for item_id, polarity in full_actual if item_id in expected_ids}
        split = row["split"]; aggregate[split]["tp"] += len(expected & actual); aggregate[split]["fp"] += len(actual - expected); aggregate[split]["fn"] += len(expected - actual)
        if any(item_id not in expected_ids and polarity != "unknown" for item_id, polarity in full_actual): collision_rows[split] += 1
        if row["expected_polarity"] == "unknown" and any((item_id, "confirmed_missing") in full_actual for item_id in expected_ids): unknown_to_missing[split] += 1
        # Class-specific precision must count a missing prediction on an
        # owned/unknown labelled target as a false positive too; restricting
        # this to rows labelled missing would silently hide that failure mode.
        expected_missing = {(item, "confirmed_missing") for item in expected_ids} if row["expected_polarity"] == "confirmed_missing" else set()
        actual_missing = {(item, state) for item, state in full_actual if item in expected_ids and state == "confirmed_missing"}
        missing_metrics[split]["tp"] += len(expected_missing & actual_missing); missing_metrics[split]["fp"] += len(actual_missing - expected_missing); missing_metrics[split]["fn"] += len(expected_missing - actual_missing)
    def metrics(split: str) -> dict[str, Any]:
        count = sum(1 for row in internal_gold if row["split"] == split); values = aggregate[split]; predicted = values["tp"] + values["fp"]; expected = values["tp"] + values["fn"]
        missing = missing_metrics[split]; missing_predicted = missing["tp"] + missing["fp"]
        return {"row_count": count, "true_positive": values["tp"], "false_positive": values["fp"], "false_negative": values["fn"], "precision": None if not predicted else values["tp"] / predicted, "recall": None if not expected else values["tp"] / expected, "confirmed_missing": {"true_positive": missing["tp"], "false_positive": missing["fp"], "false_negative": missing["fn"], "precision": None if not missing_predicted else missing["tp"] / missing_predicted}, "collision_rows": collision_rows[split], "collision_error_rate": None if not count else collision_rows[split] / count, "unknown_to_missing_rows": unknown_to_missing[split]}
    heldout = metrics("heldout"); development = metrics("development")
    # Coverage is judged on the locked held-out split. Development diversity
    # cannot mask a one-stratum publication test set.
    strata_coverage = {key: len({str(row["strata"][key]) for row in internal_gold if row["split"] == "heldout"}) for key in REQUIRED_STRATA}
    threshold = len(gold) >= 200 and development["row_count"] >= 100 and heldout["row_count"] >= 100 and all(value >= MINIMUM_DISTINCT_STRATA_VALUES for value in strata_coverage.values()) and heldout["precision"] is not None and heldout["recall"] is not None
    missing_gate = legacy_gold or (heldout["confirmed_missing"]["precision"] is not None and heldout["confirmed_missing"]["precision"] >= .99)
    passed = bool(threshold and heldout["precision"] >= .98 and heldout["recall"] >= .95 and missing_gate and heldout["collision_rows"] == 0 and heldout["unknown_to_missing_rows"] == 0)
    return {"schema_version": "2.0-p3.8", "model_feature": False, "status": "not_ready" if not gold else "evaluated" if threshold else "threshold_not_met", "publication_ready": passed, "gold_row_count": len(gold), "gold_keyed_commitments_sha256": sha256_bytes(canonical_bytes(sorted(row.get("keyed_commitment", row.get("input_sha256")) for row in gold))), "rule_development_manifest_sha256": manifest.get("manifest_sha256"), "heldout_excluded_from_rule_configuration": True, "strata_distinct_value_counts": strata_coverage, "development": development, "heldout": heldout, "thresholds": {"minimum_gold_rows": 200, "minimum_development_rows": 100, "minimum_heldout_rows": 100, "required_strata": list(REQUIRED_STRATA), "minimum_distinct_values_per_required_stratum": MINIMUM_DISTINCT_STRATA_VALUES, "heldout_precision_minimum": .98, "heldout_recall_minimum": .95, "heldout_confirmed_missing_precision_minimum": .99, "collision_rows_maximum": 0, "unknown_to_missing_rows_maximum": 0}}


def build(root: Path = ROOT, replay_inputs_path: Path | None = None, replay_inputs_sha256: str | None = None, authority_bundle: str | Path | None = None, authority_bundle_sha256: str | None = None, keyed_authority_bundle: str | Path | None = None, keyed_authority_bundle_sha256: str | None = None, keyed_contract: str | Path | None = None, keyed_contract_sha256: str | None = None, keyed_replay_binding: str | Path | None = None, keyed_replay_binding_sha256: str | None = None) -> dict[str, Any]:
    gold = read_jsonl(root / GOLD_REL); audit_errors = audit_gold(root, gold, authority_bundle, authority_bundle_sha256, keyed_authority_bundle, keyed_authority_bundle_sha256, keyed_contract, keyed_contract_sha256, keyed_replay_binding, keyed_replay_binding_sha256)
    if audit_errors: raise ValueError("parser gold audit failed: " + "; ".join(audit_errors))
    if not gold: return evaluate(root, [], [])
    # audit_gold above verifies the authority, fixed cohort, A/B finalization
    # digests and detached custodian signature before these rows are consumed.
    return evaluate(root, gold, external_replay_inputs(replay_inputs_path, replay_inputs_sha256, root), resolved_rows=_verified_binding_rows(root, keyed_replay_binding, keyed_replay_binding_sha256))


def main() -> None:
    parser = argparse.ArgumentParser(description="Replay external parser gold without committing raw claims.")
    parser.add_argument("--root", type=Path, default=ROOT); parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--replay-inputs", type=Path); parser.add_argument("--replay-inputs-sha256")
    parser.add_argument("--authority-bundle", type=Path); parser.add_argument("--authority-bundle-sha256")
    parser.add_argument("--keyed-custodian-authority-bundle", type=Path); parser.add_argument("--keyed-custodian-authority-bundle-sha256")
    parser.add_argument("--keyed-custodian-contract", type=Path); parser.add_argument("--keyed-custodian-contract-sha256")
    parser.add_argument("--keyed-replay-binding", type=Path); parser.add_argument("--keyed-replay-binding-sha256")
    args = parser.parse_args(); root = args.root.resolve(); report = build(root, args.replay_inputs, args.replay_inputs_sha256, args.authority_bundle, args.authority_bundle_sha256, args.keyed_custodian_authority_bundle, args.keyed_custodian_authority_bundle_sha256, args.keyed_custodian_contract, args.keyed_custodian_contract_sha256, args.keyed_replay_binding, args.keyed_replay_binding_sha256)
    output = args.output or root / "reports/parser-gold-evaluation.json"; output.parent.mkdir(parents=True, exist_ok=True); output.write_bytes(canonical_bytes(report))


if __name__ == "__main__": main()
