#!/usr/bin/env python3
"""Fail-closed external onboarding for the fixed market-claim cohort.

This module deliberately cannot create labels, signatures, keys, or formal
gold.  The committed queue exposes stable hashes, so an issuer without a
separate keyed custodian cannot safely issue blind packets.  All handoff
artifacts therefore live outside the release root.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.validate.market_audit import (V2_NAMESPACE, annotation_commitment,
    canonical_bytes, queue_commitment, sha256_bytes, v2_attestation_payload,
    v2_receipt_digest)

ROOT = Path(__file__).resolve().parents[2]
QUEUE_REL = Path("data/review/market-claim-review.jsonl")
QUEUE_SIZE = 200
RESERVED_NAMES = {"market-claim-gold.jsonl", "market-claim-gold.json", "claims.jsonl", "formal-gold.json", "formal-gold.jsonl"}
ROLES = {"annotator_a", "annotator_b"}
HEX = set("0123456789ABCDEF")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _outside(path: Path, root: Path, purpose: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        if resolved.name.lower() in RESERVED_NAMES:
            raise ValueError(f"{purpose} may not use a reserved formal-gold filename")
        return resolved
    raise ValueError(f"{purpose} must be outside the release root")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            if not isinstance(row, dict): raise ValueError("JSONL rows must be objects")
            rows.append(row)
    return rows


def _write_json(path: Path, value: Any, root: Path, purpose: str) -> None:
    target = _outside(path, root, purpose); target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(canonical_bytes(value))


def load_fixed_queue(root: Path = ROOT) -> list[dict[str, Any]]:
    """Load and strictly validate the committed, deterministic 200-row queue."""
    rows = _read_jsonl(root / QUEUE_REL)
    ids = [row.get("review_id") for row in rows]
    if len(rows) != QUEUE_SIZE or len(set(ids)) != QUEUE_SIZE:
        raise ValueError("market review onboarding requires exactly the committed fixed 200-row queue")
    if any(not isinstance(value, str) or not value.startswith("market_claim_review_") for value in ids):
        raise ValueError("market review queue contains an invalid review ID")
    return rows


def issue_blind_packets(packet_dir: Path, output_dir: Path, root: Path = ROOT, *, keyed_custodian_contract: Path | None = None) -> None:
    """Refuse unsafe packet issuance from public hashes.

    A current market queue has public listing hashes and no private keyed
    assignment contract.  Copying or rewrapping it would create linkable A/B
    assignments.  A future protocol may accept a separately reviewed signed
    keyed custodian contract; this version intentionally has no issuer path.
    """
    _outside(packet_dir, root, "restricted packet directory")
    _outside(output_dir, root, "blind packet output directory")
    load_fixed_queue(root)
    if keyed_custodian_contract is not None: _outside(keyed_custodian_contract, root, "keyed custodian contract")
    raise ValueError("keyed custodian contract and private assignment issuer are required; public market queue cannot be safely blinded")


def _hex(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= HEX


def canonical_submission_receipt(queue_row: dict[str, Any], submission: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """Return unsigned v2 receipt bytes for an already-human external decision."""
    committed = {row["review_id"]: row for row in load_fixed_queue(root)}
    if not isinstance(queue_row, dict) or committed.get(queue_row.get("review_id")) != queue_row:
        raise ValueError("queue row does not exactly match the committed fixed cohort")
    required = {"attestation_id", "ledger_id", "role", "authority_id", "fingerprint", "review_id", "submitted_at", "annotation"}
    if set(submission) != required or submission.get("role") not in ROLES or submission.get("review_id") != queue_row.get("review_id"):
        raise ValueError("submission has unsupported fields, role, or queue linkage")
    if not isinstance(submission.get("annotation"), dict) or not isinstance(submission.get("ledger_id"), str):
        raise ValueError("submission annotation and ledger ID are required")
    submitted = _timestamp(submission["submitted_at"])
    if submitted is None: raise ValueError("submission timestamp must be UTC RFC3339")
    receipt = {"schema_version": "sky-market-audit-attestation-v2", "receipt_type": "blinded_annotation_submission",
        "attestation_id": submission["attestation_id"], "ledger_kind": "market_claim_gold", "ledger_id": submission["ledger_id"],
        "role": submission["role"], "authority_id": submission["authority_id"], "fingerprint": submission["fingerprint"],
        "review_id": submission["review_id"], "submitted_at": submission["submitted_at"],
        "queue_commitment_sha256": queue_commitment(queue_row),
        "annotation_commitment_sha256": annotation_commitment("market_claim_gold", submission["ledger_id"], submission["role"], queue_commitment(queue_row), submission["annotation"])}
    payload = v2_attestation_payload(receipt)
    return {"receipt": receipt, "payload_sha256": sha256_bytes(payload), "payload": payload.decode("utf-8"), "receipt_sha256": v2_receipt_digest(receipt), "signature_namespace": V2_NAMESPACE,
        "notice": "Unsigned canonical payload only; this helper never creates a signature or formal gold."}


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"): return None
    try: parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError: return None
    return parsed if parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed) else None


def _ledger(path: Path, role: str, root: Path) -> dict[str, dict[str, Any]]:
    rows = _read_jsonl(_outside(path, root, f"{role} decision ledger")); queue = {x["review_id"]: x for x in load_fixed_queue(root)}
    if len(rows) != QUEUE_SIZE: raise ValueError(f"{role} ledger must cover all 200 queue rows")
    by_id: dict[str, dict[str, Any]] = {}; attestation_ids: set[str] = set(); ledger_ids: set[str] = set()
    for row in rows:
        if (row.get("role") != role or not isinstance(row.get("review_id"), str) or row["review_id"] not in queue or row["review_id"] in by_id
                or not isinstance(row.get("attestation_id"), str) or row["attestation_id"] in attestation_ids
                or not isinstance(row.get("ledger_id"), str) or row["ledger_id"] in ledger_ids):
            raise ValueError(f"{role} ledger has invalid, duplicate, or out-of-cohort review ID")
        attestation_ids.add(row["attestation_id"]); ledger_ids.add(row["ledger_id"])
        receipt = canonical_submission_receipt(queue[row["review_id"]], row, root)
        by_id[row["review_id"]] = {"submission": row, "receipt": receipt}
    return by_id


def build_conflict_packet(decisions_a: Path, decisions_b: Path, output: Path, root: Path = ROOT) -> dict[str, Any]:
    """Emit only conflict commitments, never replay text, hashes, or labels."""
    a, b = _ledger(decisions_a, "annotator_a", root), _ledger(decisions_b, "annotator_b", root)
    conflicts = []
    for review_id in sorted(a):
        if a[review_id]["submission"]["annotation"] != b[review_id]["submission"]["annotation"]:
            conflicts.append({"review_id": review_id, "annotator_a_attestation_id": a[review_id]["submission"]["attestation_id"], "annotator_b_attestation_id": b[review_id]["submission"]["attestation_id"], "annotator_a_receipt_sha256": a[review_id]["receipt"]["receipt_sha256"], "annotator_b_receipt_sha256": b[review_id]["receipt"]["receipt_sha256"]})
    packet = {"schema_version": "market-review-conflict-packet-v1", "queue_size": QUEUE_SIZE, "conflict_count": len(conflicts), "conflicts": conflicts,
        "notice": "External-only commitments. This packet is not formal gold and contains no replay input or labels."}
    _write_json(output, packet, root, "conflict packet output")
    return packet


def _validate_adjudications(rows: list[dict[str, Any]], a: dict[str, dict[str, Any]], b: dict[str, dict[str, Any]]) -> None:
    """Check the non-cryptographic v2 receipt graph before any import.

    This does not substitute for signature verification: it rejects replayed
    IDs, non-conflicts, wrong commitment links, role reuse, and invalid time
    order before a key-holding external verifier is even invoked.
    """
    conflicts = {rid for rid in a if a[rid]["submission"]["annotation"] != b[rid]["submission"]["annotation"]}
    if len(rows) != len(conflicts): raise ValueError("adjudication ledger must cover exactly, and only, A/B conflicts")
    seen: set[str] = set(); seen_authorities: set[str] = set()
    for row in rows:
        required = {"attestation_id", "ledger_id", "role", "authority_id", "fingerprint", "review_id", "adjudicated_at", "final_annotation", "annotator_a_attestation_id", "annotator_b_attestation_id", "annotator_a_receipt_sha256", "annotator_b_receipt_sha256"}
        if set(row) != required or row.get("role") != "adjudicator" or row.get("review_id") not in conflicts or row["review_id"] in seen:
            raise ValueError("adjudication ledger has invalid role, replay, or non-conflict row")
        seen.add(row["review_id"])
        if not isinstance(row.get("final_annotation"), dict) or _timestamp(row.get("adjudicated_at")) is None:
            raise ValueError("adjudication requires a final annotation and UTC timestamp")
        aa, bb = a[row["review_id"]], b[row["review_id"]]
        if (row.get("annotator_a_attestation_id") != aa["submission"]["attestation_id"] or row.get("annotator_b_attestation_id") != bb["submission"]["attestation_id"] or
                row.get("annotator_a_receipt_sha256") != aa["receipt"]["receipt_sha256"] or row.get("annotator_b_receipt_sha256") != bb["receipt"]["receipt_sha256"]):
            raise ValueError("adjudication receipt does not bind both A/B receipts")
        when = _timestamp(row["adjudicated_at"]); left = _timestamp(aa["submission"]["submitted_at"]); right = _timestamp(bb["submission"]["submitted_at"])
        if left is None or right is None or when is None or left >= when or right >= when:
            raise ValueError("both annotation receipts must precede adjudication")
        authorities = {str(aa["submission"]["fingerprint"]), str(bb["submission"]["fingerprint"]), str(row["fingerprint"])}
        if len(authorities) != 3: raise ValueError("three review roles require distinct authority fingerprints")


def import_candidate_final_ledger(decisions_a: Path, decisions_b: Path, adjudications: Path, output: Path, root: Path = ROOT, *, authority_bundle: Path | None = None, authority_bundle_sha256: str | None = None) -> dict[str, Any]:
    """Prevalidate handoff shape; fail closed until three external signatures are verified.

    Verification is intentionally not implementable from unsigned ledgers. The
    formal validator remains the sole consumer of a signed, authority-injected
    ledger.  This importer emits no candidates unless a future keyed issuer
    supplies verifiable receipt sidecars and a trust root.
    """
    a, b = _ledger(decisions_a, "annotator_a", root), _ledger(decisions_b, "annotator_b", root)
    adjudication_path = _outside(adjudications, root, "adjudication ledger"); _outside(output, root, "candidate ledger output")
    _validate_adjudications(_read_jsonl(adjudication_path), a, b)
    if authority_bundle is None or not authority_bundle_sha256:
        raise ValueError("candidate import requires an external market-audit authority bundle, SHA-256, and three verified detached receipts")
    _outside(authority_bundle, root, "market audit authority bundle")
    raise ValueError("candidate import is fail-closed: keyed custodian issuance and externally verified three-role receipt sidecars are required")


def main() -> None:
    parser = argparse.ArgumentParser(description="External-only market human-review onboarding (no labels or signatures).")
    commands = parser.add_subparsers(dest="command", required=True)
    packets = commands.add_parser("issue-blind-packets"); packets.add_argument("--packet-dir", type=Path, required=True); packets.add_argument("--output-dir", type=Path, required=True); packets.add_argument("--keyed-custodian-contract", type=Path)
    receipt = commands.add_parser("receipt-payload"); receipt.add_argument("--queue-row", type=Path, required=True); receipt.add_argument("--submission", type=Path, required=True); receipt.add_argument("--output", type=Path, required=True)
    conflict = commands.add_parser("build-conflict-packet"); conflict.add_argument("--decisions-a", type=Path, required=True); conflict.add_argument("--decisions-b", type=Path, required=True); conflict.add_argument("--output", type=Path, required=True)
    candidate = commands.add_parser("import-candidate-ledger"); candidate.add_argument("--decisions-a", type=Path, required=True); candidate.add_argument("--decisions-b", type=Path, required=True); candidate.add_argument("--adjudications", type=Path, required=True); candidate.add_argument("--output", type=Path, required=True); candidate.add_argument("--authority-bundle", type=Path); candidate.add_argument("--authority-bundle-sha256")
    args = parser.parse_args()
    if args.command == "issue-blind-packets": issue_blind_packets(args.packet_dir, args.output_dir, ROOT, keyed_custodian_contract=args.keyed_custodian_contract)
    elif args.command == "receipt-payload":
        result = canonical_submission_receipt(json.loads(args.queue_row.read_text(encoding="utf-8")), json.loads(args.submission.read_text(encoding="utf-8"))); _write_json(args.output, result, ROOT, "receipt payload output")
    elif args.command == "build-conflict-packet": build_conflict_packet(args.decisions_a, args.decisions_b, args.output, ROOT)
    else: import_candidate_final_ledger(args.decisions_a, args.decisions_b, args.adjudications, args.output, ROOT, authority_bundle=args.authority_bundle, authority_bundle_sha256=args.authority_bundle_sha256)


if __name__ == "__main__": main()
