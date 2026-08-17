#!/usr/bin/env python3
"""Prepare, but never authorize or sign, an external market intake bundle.

The staging file and generated bundle must both live outside the release root.
This module intentionally does not scrape, infer a price, construct account
features, or produce a signature.  It only canonicalizes already-sanitized
facts supplied by a licensed data steward into the v2/v3 intake wire format.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SHA256 = re.compile(r"^[A-Fa-f0-9]{64}$")
OPAQUE = re.compile(r"^[A-Za-z0-9_.:-]+$")
SENSITIVE_KEY = re.compile(r"(?:raw|text|body|caption|description|title|name|user|handle|social|uid|email|mail|phone|mobile|contact|login|payment|address|url|link)", re.I)
EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
PHONE = re.compile(r"(?:\+\d[\d .()-]{6,}\d|\(?\d{2,4}\)?[ .-]\d{3,4}[ .-]\d{3,4})")
OBSERVATION_BASE = {"post_date", "currency", "server", "offer_kind", "entity_kind", "price_line", "price_twd"}
STAGING_REQUIRED = OBSERVATION_BASE | {"source_snapshot_path", "source_snapshot_sha256", "dedup_cluster_digest", "account_commitment_digest", "feature_payload", "catalog_provenance", "catalog_provenance_sha256"}
V3_REQUIRED = {"completed_sale_verified", "sale_verified", "completed_sale_date", "completion_evidence", "completion_evidence_digest", "independent_evidence_ids"}
def feature_payload_errors(value: Any, root: Path = ROOT) -> list[str]:
    """Validate the shared P3.6 canonical feature contract."""
    from tools.modeling.market_feature_contract import errors
    return errors(value, root)


class IntakeError(ValueError):
    """Raised before any candidate bundle is emitted."""


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def canonical_signing_payload(dataset_candidate: dict[str, Any], manifest: dict[str, Any], statement: dict[str, Any], attestation: dict[str, Any]) -> bytes:
    """Return the exact unsigned payload consumed by the existing verifier.

    Callers supply the independently issued statement and proposed attestation;
    this helper neither creates those facts nor creates a signature.
    """
    from tools.market_authorization import attestation_payload
    return attestation_payload(dataset_candidate, manifest, statement, attestation)


def _outside(path: Path, root: Path, purpose: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return resolved
    raise IntakeError(f"{purpose} must be outside the release root")


def _valid_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def pii_findings(value: Any, path: str = "$") -> list[str]:
    """Conservative preflight: raw prose, URLs, handles and direct PII fail."""
    results: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if not isinstance(key, str) or SENSITIVE_KEY.search(key):
                results.append(child_path)
            results.extend(pii_findings(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            results.extend(pii_findings(child, f"{path}[{index}]"))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        # JSON numbers lose formatting, so normalize before applying the same
        # direct-phone rule. IDs with a leading letter remain string values.
        if isinstance(value, int) and re.fullmatch(r"(?:0?9\d{8}|\d{9,10})", str(value)):
            results.append(path)
    elif isinstance(value, str):
        # A bare nine/ten digit number and a Taiwan national ID are as
        # identifying as a formatted phone/email.  They are checked even in
        # deeply nested supplied feature/catalog payloads.
        taiwan_id = re.fullmatch(r"[A-Za-z][12]\d{8}", value)
        bare_phone = re.fullmatch(r"(?:0?9\d{8}|\d{9,10})", value)
        cjk_name = re.fullmatch(r"[\u3400-\u9fff]{2,4}", value)
        if EMAIL.search(value) or PHONE.search(value) or taiwan_id or bare_phone or cjk_name or value.startswith(("http://", "https://", "www.")) or "@" in value or any(char.isspace() for char in value):
            results.append(path)
    return results


def _load_staging(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntakeError(f"staging input is not valid JSON: {exc}") from exc
    if not isinstance(value, dict) or set(value) != {"schema_version", "dataset_id", "authorization_record_id", "expires_at", "records"}:
        raise IntakeError("staging envelope has unsupported fields")
    if value.get("schema_version") != "authorized-market-staging-v1":
        raise IntakeError("staging schema_version must be authorized-market-staging-v1")
    if not isinstance(value.get("dataset_id"), str) or not re.fullmatch(r"authorized_market_[a-z0-9_]+", value["dataset_id"]):
        raise IntakeError("dataset_id is invalid")
    if not isinstance(value.get("authorization_record_id"), str) or not re.fullmatch(r"authorization_record_[a-z0-9_]+", value["authorization_record_id"]):
        raise IntakeError("authorization_record_id is invalid")
    if not _valid_date(value.get("expires_at")):
        raise IntakeError("expires_at is not a real ISO-8601 date")
    if date.fromisoformat(value["expires_at"]) <= date.today():
        raise IntakeError("expires_at must be a future date")
    if not isinstance(value.get("records"), list) or not value["records"]:
        raise IntakeError("staging requires at least one record")
    findings = pii_findings(value)
    if findings:
        raise IntakeError("PII/raw text/URL/handle preflight failed at: " + ", ".join(sorted(set(findings))))
    return value


def _validate_record(record: Any, version: str, root: Path) -> None:
    required = STAGING_REQUIRED | (V3_REQUIRED if version == "v3" else set())
    if not isinstance(record, dict) or set(record) != required:
        raise IntakeError(f"{version} staging record has unsupported or missing fields")
    for field in ("source_snapshot_sha256", "dedup_cluster_digest", "account_commitment_digest"):
        if not isinstance(record.get(field), str) or not SHA256.fullmatch(record[field]):
            raise IntakeError(f"{field} must be an opaque SHA-256 digest")
    if not _valid_date(record.get("post_date")):
        raise IntakeError("post_date is not a real ISO-8601 date")
    if record.get("currency") != "TWD" or record.get("server") != "international" or record.get("offer_kind") != "seller_listing" or record.get("entity_kind") != "single_account":
        raise IntakeError("record violates the formal TWD/international/seller/single-account contract")
    if record.get("price_line") not in ({"asking", "reduced", "urgent_sale"} if version == "v2" else {"verified_sale"}):
        raise IntakeError(f"{version} price_line is not permitted")
    if not isinstance(record.get("price_twd"), int) or isinstance(record["price_twd"], bool) or record["price_twd"] < 1:
        raise IntakeError("price_twd must be a supplied positive integer; it is never inferred")
    feature_errors = feature_payload_errors(record.get("feature_payload"), root)
    if feature_errors:
        raise IntakeError("feature_payload runtime contract invalid: " + "; ".join(feature_errors))
    if not isinstance(record.get("catalog_provenance"), dict) or not isinstance(record.get("catalog_provenance_sha256"), str) or not SHA256.fullmatch(record["catalog_provenance_sha256"]) or record["catalog_provenance_sha256"].upper() != sha256(canonical_bytes(record["catalog_provenance"])):
        raise IntakeError("catalog_provenance SHA-256 must bind supplied canonical provenance")
    try:
        from tools.modeling.catalog_provenance import catalog_provenance
        if record["catalog_provenance"] != catalog_provenance(root):
            raise IntakeError("catalog_provenance differs from the current release catalog")
    except IntakeError:
        raise
    findings = pii_findings(record)
    if findings:
        raise IntakeError("PII/raw text/URL/handle preflight failed at: " + ", ".join(sorted(set(findings))))
    if version == "v3":
        evidence = record["completion_evidence"]
        if record["completed_sale_verified"] is not True or record["sale_verified"] is not True or record["completed_sale_date"] != record["post_date"] or not _valid_date(record["completed_sale_date"]):
            raise IntakeError("v3 completed-sale facts are incomplete")
        if not isinstance(evidence, list) or len(evidence) < 2 or any(not isinstance(row, dict) or set(row) != {"evidence_id", "source_lineage_id", "evidence_sha256"} for row in evidence):
            raise IntakeError("v3 requires at least two structural evidence commitments")
        if len({row["source_lineage_id"] for row in evidence}) != len(evidence) or any(not isinstance(row["evidence_id"], str) or not re.fullmatch(r"evidence_[a-z0-9_]+", row["evidence_id"]) or not isinstance(row["source_lineage_id"], str) or not re.fullmatch(r"lineage_[a-z0-9_]+", row["source_lineage_id"]) or not isinstance(row["evidence_sha256"], str) or not SHA256.fullmatch(row["evidence_sha256"]) for row in evidence):
            raise IntakeError("v3 evidence IDs or digests are invalid")
        if record["completion_evidence_digest"].upper() != sha256(canonical_bytes(evidence)) or record["independent_evidence_ids"] != [row["evidence_id"] for row in evidence]:
            raise IntakeError("v3 completion evidence digests do not bind supplied evidence")


def _id(prefix: str, digest_value: str) -> str:
    return prefix + digest_value[:24].lower()


def _observation(record: dict[str, Any], source_digest: str) -> dict[str, Any]:
    row = {"observation_id": _id("observation_", source_digest), "source_snapshot_sha256": source_digest, "dedup_cluster_id": _id("cluster_", record["dedup_cluster_digest"]), "post_date": record["post_date"], "date_verified": True, "currency": "TWD", "currency_verified": True, "server": "international", "server_verified": True, "offer_kind": "seller_listing", "entity_kind": "single_account", "price_line": record["price_line"], "price_twd": record["price_twd"]}
    if record["price_line"] == "verified_sale":
        row.update({field: record[field] for field in V3_REQUIRED})
    return row


def _example(record: dict[str, Any], observation: dict[str, Any], source_digest: str) -> dict[str, Any]:
    account_id = _id("account_", record["account_commitment_digest"])
    # Bind the payload to the account and catalog that the publication freezer
    # will replay.  Feature groups themselves remain supplier-supplied.
    payload = {"account_id": account_id, "catalog_provenance": record["catalog_provenance"], **record["feature_payload"]}
    row = {"training_example_id": _id("training_example_", source_digest), "observation_id": observation["observation_id"], "source_snapshot_sha256": source_digest, "account_id": account_id, "feature_payload": payload, "feature_payload_sha256": sha256(canonical_bytes(payload)), "catalog_provenance": record["catalog_provenance"], "catalog_provenance_sha256": sha256(canonical_bytes(record["catalog_provenance"])), "dedup_cluster_id": observation["dedup_cluster_id"], "dedup_cluster_digest": sha256(canonical_bytes(observation["dedup_cluster_id"]))}
    if observation["price_line"] == "verified_sale":
        row.update({"observation_row_digest": sha256(canonical_bytes(observation)), "price_line": "verified_sale", "completed_sale_verified": True, "sale_verified": True, "completion_evidence_digest": observation["completion_evidence_digest"], "independent_evidence_ids": observation["independent_evidence_ids"]})
    # Import keeps this commitment definition aligned with the production verifier.
    from tools.market_authorization import training_example_commitment
    row["training_example_digest"] = sha256(canonical_bytes(training_example_commitment(row)))
    return row


def _capacity(observations: list[dict[str, Any]]) -> dict[str, Any]:
    """Report the best cluster-exclusive chronological 300/100 split."""
    grouped: dict[str, list[date]] = defaultdict(list)
    for row in observations:
        grouped[row["dedup_cluster_id"]].append(date.fromisoformat(row["post_date"]))
    spans = {cluster: (min(values), max(values)) for cluster, values in grouped.items()}
    candidates: list[tuple[int, int, date, list[str], list[str], list[str]]] = []
    for cut in sorted({begin for begin, _end in spans.values()}):
        train = sorted(cluster for cluster, (_begin, end) in spans.items() if end < cut)
        heldout = sorted(cluster for cluster, (begin, _end) in spans.items() if begin >= cut)
        spanning = sorted(cluster for cluster, (begin, end) in spans.items() if begin < cut <= end)
        if train and heldout:
            score = min(len(train), 300) + min(len(heldout), 100)
            candidates.append((score, len(heldout), cut, train, heldout, spanning))
    if candidates:
        _score, _heldout_count, cut, train, heldout, spanning = max(candidates, key=lambda item: (item[0], item[1], -item[2].toordinal()))
    else:
        cut, train, heldout, spanning = None, [], [], []
    # Supplier-supplied opaque cluster/account digests are not independent
    # identity evidence.  Never advertise a 300/100 cohort until a future
    # externally signed identity-to-cluster mapping verifier is available.
    return {"schema_version": "authorized-market-intake-capacity-v1", "cluster_count": len(grouped), "observation_count": len(observations), "requirements": {"training_clusters": 300, "heldout_clusters": 100}, "independence_verified": False, "date_split": {"cut_date": cut.isoformat() if cut else None, "training_cluster_count": len(train), "heldout_cluster_count": len(heldout), "excluded_spanning_cluster_count": len(spanning), "cluster_overlap": bool(set(train) & set(heldout)), "requirements_met": False}, "price_line_counts": dict(sorted(Counter(row["price_line"] for row in observations).items()))}


def build(root: Path, staging_path: Path, staging_sha256: str, output_dir: Path, version: str) -> dict[str, Any]:
    """Build an unsigned external candidate bundle from sanitized staging."""
    root = root.resolve()
    staging_path = _outside(staging_path, root, "sanitized staging input")
    output_dir = _outside(output_dir, root, "candidate output directory")
    if not isinstance(staging_sha256, str) or not SHA256.fullmatch(staging_sha256) or sha256(staging_path.read_bytes()) != staging_sha256.upper():
        raise IntakeError("staging SHA-256 does not match injected digest")
    staging = _load_staging(staging_path)
    records = staging["records"]
    for record in records:
        _validate_record(record, version, root)
    source_digests: list[str] = []
    for record in records:
        source = _outside(Path(record["source_snapshot_path"]), root, "immutable source snapshot")
        if not source.is_file():
            raise IntakeError("immutable source snapshot is missing")
        actual = sha256(source.read_bytes())
        if actual != record["source_snapshot_sha256"].upper():
            raise IntakeError("immutable source snapshot SHA-256 does not match supplied digest")
        source_digests.append(actual)
    clusters = [record["dedup_cluster_digest"].upper() for record in records]
    accounts = [record["account_commitment_digest"].upper() for record in records]
    if len(source_digests) != len(set(source_digests)):
        raise IntakeError("duplicate immutable source snapshot digest: duplicate observations are forbidden")
    if len(clusters) != len(set(clusters)):
        raise IntakeError("duplicate dedup_cluster_digest: one candidate per cluster is required")
    if len(accounts) != len(set(accounts)):
        raise IntakeError("duplicate account_commitment_digest: one training example per account is required")
    pairs = [(_observation(record, source_digest), record, source_digest) for record, source_digest in zip(records, source_digests)]
    observations = sorted((observation for observation, _record, _source_digest in pairs), key=lambda row: row["observation_id"])
    examples = sorted((_example(record, observation, source_digest) for observation, record, source_digest in pairs), key=lambda row: row["training_example_id"])
    # Never let a truncated public ID stand in for uniqueness of its complete
    # cryptographic input.  These guards are also useful against a deliberate
    # prefix-collision attempt.
    for label, rows, key in (("observation", observations, "observation_id"), ("training example", examples, "training_example_id"), ("dedup cluster", observations, "dedup_cluster_id"), ("account", examples, "account_id")):
        if len(rows) != len({row[key] for row in rows}):
            raise IntakeError(f"duplicate derived {label} ID")
    # The independently sorted observations and examples are joined by stable IDs.
    if {row["observation_id"] for row in examples} != {row["observation_id"] for row in observations}:
        raise IntakeError("internal canonical observation/example join failed")
    dataset_id = staging["dataset_id"]
    base = f"data/review/market-authorization/datasets/{dataset_id}"
    observations_bytes = b"".join(canonical_bytes(row) for row in observations)
    examples_bytes = b"".join(canonical_bytes(row) for row in examples)
    manifest = {"schema_version": f"authorized-market-manifest-{version}", "dataset_id": dataset_id, "observations_path": f"{base}/observations.jsonl", "observations_sha256": sha256(observations_bytes), "observation_digests": [{"observation_id": row["observation_id"], "row_digest": sha256(canonical_bytes(row)), "dedup_cluster_digest": sha256(canonical_bytes(row["dedup_cluster_id"]))} for row in observations], "training_examples_path": f"{base}/training-examples.jsonl", "training_examples_sha256": sha256(examples_bytes), "training_example_digests": [{"training_example_id": row["training_example_id"], "training_example_digest": row["training_example_digest"], "observation_id": row["observation_id"], "account_id": row["account_id"], "feature_payload_sha256": row["feature_payload_sha256"], "catalog_provenance_sha256": row["catalog_provenance_sha256"], "dedup_cluster_digest": row["dedup_cluster_digest"]} for row in examples]}
    manifest_bytes = canonical_bytes(manifest)
    registry = {"dataset_id": dataset_id, "authorization_record_id": staging["authorization_record_id"], "manifest_path": f"{base}/manifest.json", "manifest_sha256": sha256(manifest_bytes), "statement_sha256": None, "expires_at": staging["expires_at"], "status": "candidate_requires_external_statement_and_three_role_signatures"}
    # The registry candidate deliberately is not schema-valid until an external
    # issuer provides a statement digest and reviewers supply signatures.
    capacity = _capacity(observations)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "observations.jsonl").write_bytes(observations_bytes)
    (output_dir / "training-examples.jsonl").write_bytes(examples_bytes)
    (output_dir / "manifest.json").write_bytes(manifest_bytes)
    (output_dir / "registry-candidate.json").write_bytes(canonical_bytes(registry))
    (output_dir / "capacity-report.json").write_bytes(canonical_bytes(capacity))
    return {"manifest": manifest, "registry_candidate": registry, "capacity_report": capacity}


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare unsigned, PII-free external market intake candidates.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--staging", type=Path, required=True)
    parser.add_argument("--staging-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", choices=("v2", "v3"), required=True)
    args = parser.parse_args()
    build(args.root, args.staging, args.staging_sha256, args.output_dir, args.version)


if __name__ == "__main__":
    main()
