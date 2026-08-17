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
import subprocess
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REQUIRED_STRATA = ("account_type", "era", "season", "collaboration", "set_context")
QUEUE_SIZE = 200
SPLIT_SIZE = QUEUE_SIZE // 2
COMMITMENT_NAMESPACE = "sky-parser-review-commitment-v1"


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def input_sha256(profile: dict[str, Any], listing: dict[str, Any]) -> str:
    return digest(canonical_bytes({"listing": listing, "profile": profile}))


def validate_manifest(manifest: dict[str, Any]) -> list[str]:
    """Replay the public queue commitment without needing restricted inputs."""
    if manifest == {
        "schema_version": "1.0-p3.4", "status": "not_ready", "queue_size": 0,
        "reason": "No external replay inputs have been supplied; no queue or formal gold exists.",
    }:
        return []
    try:
        _validate_frozen_manifest(manifest)
    except ValueError as exc:
        return [str(exc)]
    return []


def _outside_root(path: Path, root: Path, purpose: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return resolved
    raise ValueError(f"{purpose} must be outside the release root")


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
    if any(not isinstance(value[key], str) or not value[key] for key in REQUIRED_STRATA):
        raise ValueError("review strata values must be nonempty strings")
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
    if not isinstance(payload["expected_canonical_item_ids"], list) or not payload["expected_canonical_item_ids"] or len(payload["expected_canonical_item_ids"]) != len(set(payload["expected_canonical_item_ids"])):
        raise ValueError("decision requires unique canonical item IDs")
    if payload["expected_polarity"] not in {"owned", "confirmed_missing", "unknown"}:
        raise ValueError("decision has unsupported polarity")
    return payload


def _fingerprint(public_key: str) -> str | None:
    result = subprocess.run(["ssh-keygen", "-lf", "-"], input=public_key + "\n", text=True, capture_output=True, check=False)
    fields = result.stdout.strip().split()
    return fields[1] if result.returncode == 0 and len(fields) >= 2 else None


def _verify_decision_ledger(path: Path, reviewer: str, root: Path) -> list[dict[str, Any]]:
    path = _outside_root(path, root, f"reviewer {reviewer} decisions")
    rows = _read_jsonl(path); sidecar = path.with_suffix(path.suffix + ".commitment.json")
    try: commitment = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc: raise ValueError(f"{reviewer} signed decision commitment is missing: {exc}") from exc
    allowed = {"schema_version", "reviewer", "decision_ledger_sha256", "public_key", "fingerprint", "signature_file"}
    if not isinstance(commitment, dict) or set(commitment) != allowed or commitment.get("schema_version") != "1.0-p3.4" or commitment.get("reviewer") != reviewer or commitment.get("decision_ledger_sha256") != digest(b"".join(canonical_bytes(row) for row in rows)):
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


def verify_decision_commitments(manifest: dict[str, Any], decisions_a: Path, decisions_b: Path, adjudications: Path | None, root: Path) -> dict[str, Any]:
    """Verify reviewer independence; returns candidates only, never formal gold."""
    errors = validate_manifest(manifest)
    if errors:
        raise ValueError("invalid queue manifest: " + "; ".join(errors))
    queue = manifest["queue"]
    expected = {row["queue_id"]: row for row in queue}
    def load(path: Path, reviewer: str) -> dict[str, dict[str, Any]]:
        result = {}
        for row in _verify_decision_ledger(path, reviewer, root):
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
        for row in _read_jsonl(_outside_root(adjudications, root, "adjudications")):
            allowed = {"adjudication_id", "queue_id", "annotator_a_commitment_sha256", "annotator_b_commitment_sha256", "adjudicator_commitment_sha256"}
            if set(row) != allowed or not isinstance(row.get("queue_id"), str) or row["queue_id"] in adj:
                raise ValueError("adjudication has unsupported fields or duplicate queue ID")
            qid = row["queue_id"]
            if qid not in expected or row["annotator_a_commitment_sha256"] != a[qid]["decision_commitment_sha256"] or row["annotator_b_commitment_sha256"] != b[qid]["decision_commitment_sha256"]:
                raise ValueError("adjudication must link the two immutable A/B commitments")
            if not isinstance(row["adjudicator_commitment_sha256"], str) or len(row["adjudicator_commitment_sha256"]) != 64:
                raise ValueError("adjudication requires an external adjudicator commitment digest")
            adj[qid] = row
    if set(adj) != disagreements:
        raise ValueError("adjudications must exist only and exactly for A/B disagreements")
    return {"status": "candidate_labels_only", "queue_manifest_sha256": manifest["manifest_sha256"], "agreement_count": len(expected) - len(disagreements), "disagreement_count": len(disagreements), "formal_gold_written": False}


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze parser review packets outside the release root.")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-queue"); build.add_argument("--source", type=Path, required=True); build.add_argument("--source-sha256", required=True); build.add_argument("--manifest-out", type=Path, required=True); build.add_argument("--packet-dir", type=Path, required=True); build.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    if args.command == "build-queue": build_queue(args.root.resolve(), args.source, args.source_sha256, args.manifest_out.resolve(), args.packet_dir)


if __name__ == "__main__": main()
