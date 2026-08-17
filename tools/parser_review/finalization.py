#!/usr/bin/env python3
"""Verify an external-only keyed parser-review finalization.

This module never imports formal gold and never accepts a self-authenticating
reviewer key.  Its output is an external receipt which a separate importer may
consume only by replaying this verifier again.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from tools.parser_review.onboarding import (
    KEYED_CONTRACT_NAMESPACE, _fingerprint, _outside_root, _read_jsonl,
    _read_keyed_assignment_ledger, canonical_bytes, digest,
    validate_keyed_custodian_contract,
)

ROOT = Path(__file__).resolve().parents[2]
NAMESPACE = "sky-parser-keyed-finalization-v2"
DECISION_NAMESPACE = "sky-parser-keyed-decision-v2"
ADJUDICATION_NAMESPACE = "sky-parser-keyed-adjudication-v2"
ROLES = {"annotator_a": "keyed_annotator_a", "annotator_b": "keyed_annotator_b", "adjudicator": "keyed_adjudicator", "custodian": "keyed_custodian_contract"}


def _payload(value: dict[str, Any], *excluded: str) -> dict[str, Any]:
    return {key: value[key] for key in value if key not in excluded}


def _load_authorities(path: Path, expected_sha: str, root: Path) -> dict[str, dict[str, Any]]:
    path = _outside_root(path, root, "keyed review authority bundle")
    if not path.is_file() or digest(path.read_bytes()) != expected_sha.upper():
        raise ValueError("keyed review authority bundle digest does not match")
    bundle = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(bundle, dict) or set(bundle) != {"schema_version", "authorities", "revoked_fingerprints"} or bundle["schema_version"] != "sky-parser-keyed-review-authority-bundle-v2":
        raise ValueError("keyed review authority bundle is unsupported")
    out: dict[str, dict[str, Any]] = {}
    for record in bundle["authorities"]:
        if not isinstance(record, dict) or set(record) != {"authority_id", "public_key", "fingerprint", "roles"}:
            raise ValueError("keyed review authority has unsupported fields")
        actual = _fingerprint(record.get("public_key", "")) if isinstance(record.get("public_key"), str) else None
        if not actual or actual != record.get("fingerprint") or record["authority_id"] in out or not isinstance(record.get("roles"), list):
            raise ValueError("keyed review authority identity or key is invalid")
        if actual in bundle["revoked_fingerprints"]:
            raise ValueError("keyed review authority is revoked")
        out[record["authority_id"]] = record
    return out


def _verify_sidecar(ledger: Path, role: str, authorities: dict[str, dict[str, Any]], root: Path, contract_sha: str) -> tuple[list[dict[str, Any]], str]:
    ledger = _outside_root(ledger, root, f"{role} decision ledger")
    rows = _read_jsonl(ledger)
    sidecar = ledger.with_suffix(ledger.suffix + ".commitment.json")
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    required = {"schema_version", "role", "authority_id", "fingerprint", "custodian_contract_sha256", "ledger_sha256", "signature_file"}
    if not isinstance(data, dict) or set(data) != required or data.get("schema_version") != "2.0-p3.8" or data.get("role") != role or data.get("custodian_contract_sha256") != contract_sha or data.get("ledger_sha256") != digest(b"".join(canonical_bytes(row) for row in rows)):
        raise ValueError(f"{role} signed ledger does not bind its contents")
    authority = authorities.get(data.get("authority_id"))
    if not authority or authority["fingerprint"] != data.get("fingerprint") or ROLES[role] not in authority["roles"]:
        raise ValueError(f"{role} authority is unauthorized")
    name = data.get("signature_file")
    if not isinstance(name, str) or Path(name).name != name or not (ledger.parent / name).is_file():
        raise ValueError(f"{role} signature is missing")
    with tempfile.TemporaryDirectory(prefix="sky-keyed-finalize-") as temp:
        allowed = Path(temp) / "allowed"; allowed.write_text(f"{data['authority_id']} {authority['public_key'].strip()}\n", encoding="utf-8")
        result = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", data["authority_id"], "-n", ADJUDICATION_NAMESPACE if role == "adjudicator" else DECISION_NAMESPACE, "-s", str(ledger.parent / name)], input=canonical_bytes(_payload(data, "signature_file")), capture_output=True, check=False)
    if result.returncode:
        raise ValueError(f"{role} detached signature verification failed")
    return rows, str(authority["fingerprint"])


def _decision(row: dict[str, Any], role: str) -> tuple[str, tuple[tuple[str, ...], str]]:
    required = {"decision_id", "assignment_id", "reviewer", "expected_canonical_item_ids", "expected_polarity", "decision_commitment_sha256"}
    if not isinstance(row, dict) or set(row) != required or row.get("reviewer") != role or not isinstance(row.get("assignment_id"), str):
        raise ValueError(f"{role} decision has unsupported fields")
    payload = _payload(row, "decision_commitment_sha256")
    items, polarity = payload["expected_canonical_item_ids"], payload["expected_polarity"]
    if row.get("decision_commitment_sha256") != digest(canonical_bytes(payload)) or not isinstance(items, list) or not items or len(items) != len(set(items)) or any(not isinstance(value, str) or not value.startswith("item_") for value in items) or polarity not in {"owned", "confirmed_missing", "unknown"}:
        raise ValueError(f"{role} decision commitment is invalid")
    return row["assignment_id"], (tuple(items), polarity)


def verify_finalization(contract_path: Path, assignment_ledger: Path, decisions_a: Path, decisions_b: Path, adjudications: Path, custodian_authority_bundle: Path, custodian_authority_sha256: str, review_authority_bundle: Path, review_authority_sha256: str, root: Path = ROOT) -> dict[str, Any]:
    """Replay all signed decision provenance; returns a non-gold final receipt."""
    root = root.resolve(); contract_path = _outside_root(contract_path, root, "keyed custodian contract")
    contract = validate_keyed_custodian_contract(json.loads(contract_path.read_text(encoding="utf-8")), contract_path, root, custodian_authority_bundle, custodian_authority_sha256)
    assignments = _read_keyed_assignment_ledger(assignment_ledger, contract, root)
    authorities = _load_authorities(review_authority_bundle, review_authority_sha256, root)
    # A review bundle must provide independent keys; custodian is checked via
    # the original contract trust root, not a self-declared finalizer key.
    a_rows, a_key = _verify_sidecar(decisions_a, "annotator_a", authorities, root, contract["contract_sha256"])
    b_rows, b_key = _verify_sidecar(decisions_b, "annotator_b", authorities, root, contract["contract_sha256"])
    adj_rows, adj_key = _verify_sidecar(adjudications, "adjudicator", authorities, root, contract["contract_sha256"])
    if len({a_key, b_key, adj_key}) != 3:
        raise ValueError("A/B/adjudicator require three distinct authority keys")
    expected = {role: {row["assignment_id"] for row in assignments if row["reviewer"] == role} for role in ("annotator_a", "annotator_b")}
    parsed: dict[str, dict[str, tuple[tuple[str, ...], str]]] = {}; commitments: dict[str, dict[str, str]] = {}
    for role, rows in (("annotator_a", a_rows), ("annotator_b", b_rows)):
        values: dict[str, tuple[tuple[str, ...], str]] = {}
        hashes: dict[str, str] = {}
        for row in rows:
            assignment, value = _decision(row, role)
            if assignment in values: raise ValueError(f"{role} decision assignment is duplicated")
            values[assignment] = value
            hashes[assignment] = str(row["decision_commitment_sha256"])
        if set(values) != expected[role]: raise ValueError(f"{role} decisions must cover exactly 200 issued assignments")
        parsed[role] = values
        commitments[role] = hashes
    # Both assignments for a row share a HMAC suffix issued by the custodian.
    suffix = lambda assignment: assignment.rsplit("_", 1)[-1]
    by_suffix_a = {suffix(key): value for key, value in parsed["annotator_a"].items()}; by_suffix_b = {suffix(key): value for key, value in parsed["annotator_b"].items()}
    if set(by_suffix_a) != set(by_suffix_b) or len(by_suffix_a) != 200:
        raise ValueError("A/B assignments do not form one fixed 200-row cohort")
    disagreements = {key for key in by_suffix_a if by_suffix_a[key] != by_suffix_b[key]}
    seen: set[str] = set(); adjudicated: dict[str, tuple[tuple[str, ...], str]] = {}
    for row in adj_rows:
        required = {"adjudication_id", "cohort_assignment_suffix", "annotator_a_decision_commitment_sha256", "annotator_b_decision_commitment_sha256", "final_canonical_item_ids", "final_polarity", "adjudication_commitment_sha256"}
        if not isinstance(row, dict) or set(row) != required or row.get("cohort_assignment_suffix") not in disagreements or row["cohort_assignment_suffix"] in seen:
            raise ValueError("adjudication is missing, duplicated, or not limited to an A/B disagreement")
        payload = _payload(row, "adjudication_commitment_sha256")
        if row.get("adjudication_commitment_sha256") != digest(canonical_bytes(payload)):
            raise ValueError("adjudication commitment is invalid")
        key = str(row["cohort_assignment_suffix"])
        a_assignment = next(value for value in commitments["annotator_a"] if suffix(value) == key)
        b_assignment = next(value for value in commitments["annotator_b"] if suffix(value) == key)
        if row["annotator_a_decision_commitment_sha256"] != commitments["annotator_a"][a_assignment] or row["annotator_b_decision_commitment_sha256"] != commitments["annotator_b"][b_assignment]:
            raise ValueError("adjudication does not exactly bind the A/B decision commitments")
        seen.add(row["cohort_assignment_suffix"])
        adjudicated[key] = (tuple(row["final_canonical_item_ids"]), str(row["final_polarity"]))
    if seen != disagreements:
        raise ValueError("every and only A/B disagreements require adjudication")
    final = {key: adjudicated.get(key, by_suffix_a[key]) for key in by_suffix_a}
    return {"schema_version": "2.0-p3.8", "status": "external_keyed_finalization_verified", "cohort_id": contract["cohort_id"], "custodian_contract_sha256": contract["contract_sha256"], "decision_ledger_sha256": digest(b"".join(canonical_bytes(row) for row in a_rows + b_rows)), "adjudication_ledger_sha256": digest(b"".join(canonical_bytes(row) for row in adj_rows)), "agreement_count": 200 - len(disagreements), "disagreement_count": len(disagreements), "formal_gold_written": False, "_final_decisions": final}


def build_candidate_bundle(verified: dict[str, Any], resolution_rows: list[dict[str, Any]], contract: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """Create an unsigned, external-only candidate bundle for custodian signing.

    The caller cannot submit labels: every label comes from ``verify_finalization``.
    ``resolution_rows`` only supplies the custodian-held private replay mapping.
    """
    final = verified.get("_final_decisions")
    if not isinstance(final, dict) or len(final) != 200:
        raise ValueError("candidate producer requires a just-verified 200-row finalization")
    required = {"cohort_assignment_suffix", "input_sha256", "keyed_commitment", "split", "strata"}
    if len(resolution_rows) != 200 or any(not isinstance(row, dict) or set(row) != required for row in resolution_rows):
        raise ValueError("candidate resolution map must contain exactly 200 private rows")
    seen: set[str] = set(); public: list[dict[str, Any]] = []; binding: list[dict[str, Any]] = []
    for index, row in enumerate(sorted(resolution_rows, key=lambda value: str(value["keyed_commitment"])), 1):
        suffix = row["cohort_assignment_suffix"]
        if suffix not in final or suffix in seen or row["split"] not in {"development", "heldout"}:
            raise ValueError("candidate resolution map is not a bijection to final decisions")
        seen.add(suffix); items, polarity = final[suffix]; gold_id = f"parser_gold_{index:04d}"
        public.append({"gold_id": gold_id, "keyed_commitment": row["keyed_commitment"], "expected_canonical_item_ids": list(items), "expected_polarity": polarity, "strata": row["strata"]})
        binding.append({"gold_id": gold_id, "input_sha256": row["input_sha256"], "keyed_commitment": row["keyed_commitment"], "split": row["split"]})
    if seen != set(final): raise ValueError("candidate resolution map omits final decisions")
    from tools.modeling.parser_gold_evaluator import gold_ledger_sha256, parser_config_sha256, parser_source_sha256
    from tools.parser_review.onboarding import keyed_commitment_merkle_root, keyed_split_commitment
    if contract.get("cohort_id") != verified.get("cohort_id") or keyed_commitment_merkle_root([row["keyed_commitment"] for row in binding]) != contract.get("commitment_merkle_root") or keyed_split_commitment(binding) != contract.get("split_commitment"):
        raise ValueError("candidate private map does not reproduce the signed custodian cohort")
    finalization = {key: value for key, value in verified.items() if not key.startswith("_")}
    finalization["public_gold_sha256"] = gold_ledger_sha256(public); finalization["finalization_sha256"] = digest(canonical_bytes(finalization))
    rule_manifest = {"schema_version": "2.0-p3.8", "gold_ledger_sha256": gold_ledger_sha256(public), "parser_source_sha256": parser_source_sha256(root), "parser_config_sha256": parser_config_sha256(), "development_keyed_commitments": sorted(row["keyed_commitment"] for row in binding if row["split"] == "development"), "required_strata": ["account_type", "era", "season", "collaboration", "set_context"], "minimum_distinct_values_per_required_stratum": 2}
    rule_manifest["manifest_sha256"] = digest(canonical_bytes(rule_manifest))
    binding_payload = {"schema_version": "2.0-p3.8", "contract_type": "parser_review_keyed_replay_binding", "cohort_id": contract["cohort_id"], "custodian_contract_sha256": contract["contract_sha256"], "commitment_merkle_root": contract["commitment_merkle_root"], "split_commitment": contract["split_commitment"], "authority_id": contract["authority_id"], "fingerprint": contract["fingerprint"], "cohort_keyed_commitments": sorted(row["keyed_commitment"] for row in binding), "binding_rows": binding, "decision_ledger_sha256": verified["decision_ledger_sha256"], "adjudication_ledger_sha256": verified["adjudication_ledger_sha256"], "finalization_sha256": finalization["finalization_sha256"], "public_gold_sha256": gold_ledger_sha256(public), "rule_manifest_sha256": rule_manifest["manifest_sha256"]}
    return {"schema_version": "2.0-p3.8", "status": "external_candidate_bundle_unsigned", "public_gold": public, "binding_payload": binding_payload, "rule_manifest": rule_manifest, "finalization": finalization, "candidate_sha256": "", "formal_gold_written": False} | {"candidate_sha256": digest(canonical_bytes({"schema_version": "2.0-p3.8", "status": "external_candidate_bundle_unsigned", "public_gold": public, "binding_payload": binding_payload, "rule_manifest": rule_manifest, "finalization": finalization, "formal_gold_written": False}))}


def import_signed_candidate(candidate_path: Path, candidate_signature: Path, binding_signature: Path, resolution_rows: list[dict[str, Any]], contract_path: Path, assignment_ledger: Path, decisions_a: Path, decisions_b: Path, adjudications: Path, custodian_authority_bundle: Path, custodian_authority_sha256: str, review_authority_bundle: Path, review_authority_sha256: str, root: Path = ROOT) -> None:
    """Rebuild and atomically import a custodian-signed V2 candidate bundle."""
    root = root.resolve(); candidate_path = _outside_root(candidate_path, root, "external candidate bundle")
    contract_path = _outside_root(contract_path, root, "keyed custodian contract")
    candidate = json.loads(candidate_path.read_text(encoding="utf-8")); contract = json.loads(contract_path.read_text(encoding="utf-8"))
    verified = verify_finalization(contract_path, assignment_ledger, decisions_a, decisions_b, adjudications, custodian_authority_bundle, custodian_authority_sha256, review_authority_bundle, review_authority_sha256, root)
    rebuilt = build_candidate_bundle(verified, resolution_rows, contract, root)
    if candidate != rebuilt:
        raise ValueError("candidate bundle does not exactly reproduce verified decisions and private map")
    # The same contracted, externally rooted custodian signs both the complete
    # candidate and the exact external binding payload; no caller supplied
    # digest can substitute for either detached signature.
    from tools.parser_review.onboarding import load_keyed_custodian_authorities
    authorities = load_keyed_custodian_authorities(custodian_authority_bundle, custodian_authority_sha256, root); authority = authorities.get(contract.get("authority_id"))
    if authority is None: raise ValueError("contracted custodian authority is unavailable")
    def signature(payload: dict[str, Any], path: Path, namespace: str) -> None:
        if not path.is_file(): raise ValueError("custodian detached signature is missing")
        with tempfile.TemporaryDirectory(prefix="sky-keyed-import-") as temp:
            allowed = Path(temp) / "allowed"; allowed.write_text(f"{contract['authority_id']} {authority['public_key'].strip()}\n", encoding="utf-8")
            result = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", contract["authority_id"], "-n", namespace, "-s", str(path)], input=canonical_bytes(payload), capture_output=True, check=False)
        if result.returncode: raise ValueError("custodian detached signature verification failed")
    signature(candidate, candidate_signature, NAMESPACE)
    signature(candidate["binding_payload"], binding_signature, "sky-parser-keyed-replay-binding-v2")
    binding = candidate["binding_payload"] | {"signature_file": "external-only", "binding_sha256": digest(canonical_bytes(candidate["binding_payload"]))}
    # The evaluator receives the original external binding/signature; release
    # root receives only privacy-safe public gold and rule boundary.
    target = root / "data/review/parser-gold"; target.mkdir(parents=True, exist_ok=True)
    temp_claims = target / "claims.jsonl.tmp"; temp_rules = target / "rule-development-manifest.json.tmp"; temp_attest = target / "attestations.jsonl.tmp"
    temp_claims.write_bytes(b"".join(canonical_bytes(row) for row in candidate["public_gold"])); temp_rules.write_bytes(canonical_bytes(candidate["rule_manifest"])); temp_attest.write_bytes(b"")
    os.replace(temp_claims, target / "claims.jsonl"); os.replace(temp_rules, target / "rule-development-manifest.json"); os.replace(temp_attest, target / "attestations.jsonl")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify external keyed parser decisions; never write formal gold.")
    for name in ("custodian-contract", "assignment-ledger", "decisions-a", "decisions-b", "adjudications", "custodian-authority-bundle", "review-authority-bundle"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--custodian-authority-bundle-sha256", required=True); parser.add_argument("--review-authority-bundle-sha256", required=True); parser.add_argument("--output", type=Path); parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--import-signed-candidate", action="store_true"); parser.add_argument("--candidate", type=Path); parser.add_argument("--candidate-signature", type=Path); parser.add_argument("--binding-signature", type=Path); parser.add_argument("--resolution-map", type=Path)
    args = parser.parse_args(); root = args.root.resolve()
    if args.import_signed_candidate:
        if not all((args.candidate, args.candidate_signature, args.binding_signature, args.resolution_map)):
            parser.error("--import-signed-candidate requires --candidate, --candidate-signature, --binding-signature and --resolution-map")
        resolution = _read_jsonl(_outside_root(args.resolution_map, root, "external candidate resolution map"))
        import_signed_candidate(args.candidate, args.candidate_signature, args.binding_signature, resolution, args.custodian_contract, args.assignment_ledger, args.decisions_a, args.decisions_b, args.adjudications, args.custodian_authority_bundle, args.custodian_authority_bundle_sha256, args.review_authority_bundle, args.review_authority_bundle_sha256, root)
        return
    if args.output is None: parser.error("--output is required unless importing a signed candidate")
    result = verify_finalization(args.custodian_contract, args.assignment_ledger, args.decisions_a, args.decisions_b, args.adjudications, args.custodian_authority_bundle, args.custodian_authority_bundle_sha256, args.review_authority_bundle, args.review_authority_bundle_sha256, root)
    output = _outside_root(args.output, root, "external finalization output"); output.write_bytes(canonical_bytes(result))


if __name__ == "__main__": main()
