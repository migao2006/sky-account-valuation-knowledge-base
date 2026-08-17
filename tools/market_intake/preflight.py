#!/usr/bin/env python3
"""Fail-closed, non-persisting trust preflight for formal market intake.

This is deliberately an admission *readiness* report, not an importer.  All
trust files and its report must live outside the release root; the report
contains only counts, supplied byte digests, statuses, and reason codes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import re
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.market_authorization import REGISTRY_REL, make_authorization_evaluator

SCHEMA_VERSION = "market-intake-trust-preflight-v1"
SHA_FIELDS = (
    "authority_bundle_sha256", "statement_sha256",
    "identity_authority_bundle_sha256", "identity_mapping_sha256", "identity_statement_sha256",
    "receipt_archive_sha256", "receipt_authority_bundle_sha256",
)
SHA256 = re.compile(r"^[A-Fa-f0-9]{64}$")


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _outside(path: str | Path, root: Path) -> Path:
    candidate = Path(path).expanduser().resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return candidate
    raise ValueError("preflight output must be outside the release root")


def _registry(root: Path) -> tuple[list[dict[str, Any]], list[str], str]:
    path = root / REGISTRY_REL
    if not path.is_file():
        return [], ["formal_market_registry_missing"], ""
    raw = path.read_bytes()
    try:
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    except (UnicodeDecodeError, json.JSONDecodeError):
        return [], ["formal_market_registry_unreadable"], _sha256(raw)
    if not all(isinstance(row, dict) for row in rows):
        return [], ["formal_market_registry_unreadable"], _sha256(raw)
    return rows, [], _sha256(raw)


def preflight(
    root: Path,
    authority_bundle: str | Path | None = None, authority_bundle_sha256: str | None = None,
    statement: str | Path | None = None, statement_sha256: str | None = None,
    identity_authority_bundle: str | Path | None = None, identity_authority_bundle_sha256: str | None = None,
    identity_mapping: str | Path | None = None, identity_mapping_sha256: str | None = None,
    identity_statement: str | Path | None = None, identity_statement_sha256: str | None = None,
    receipt_archive: str | Path | None = None, receipt_archive_sha256: str | None = None,
    receipt_authority_bundle: str | Path | None = None, receipt_authority_bundle_sha256: str | None = None,
) -> dict[str, Any]:
    """Return a non-sensitive coverage report; never writes formal data."""
    root = root.resolve()
    rows, reasons, registry_digest = _registry(root)
    versions = Counter()
    manifest_base = (root / "data/review/market-authorization/datasets").resolve()
    for row in rows:
        relative = row.get("manifest_path")
        if not isinstance(relative, str) or not re.fullmatch(r"data/review/market-authorization/datasets/[a-z0-9_/-]+/manifest\.json", relative):
            reasons.append("formal_market_manifest_path_invalid")
            continue
        manifest_path = (root / relative).resolve()
        try:
            manifest_path.relative_to(manifest_base)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            version = manifest.get("schema_version")
            if version not in {"authorized-market-manifest-v1", "authorized-market-manifest-v2", "authorized-market-manifest-v3"}:
                reasons.append("formal_market_manifest_version_unsupported")
                continue
            versions[version] += 1
        except (OSError, ValueError, json.JSONDecodeError):
            reasons.append("formal_market_manifest_unreadable")
    v2_count = versions["authorized-market-manifest-v2"]
    v3_count = versions["authorized-market-manifest-v3"]
    if not rows and not reasons:
        reasons.append("formal_market_registry_empty")
    identity_values = (identity_authority_bundle, identity_authority_bundle_sha256, identity_mapping, identity_mapping_sha256, identity_statement, identity_statement_sha256)
    receipt_values = (receipt_archive, receipt_archive_sha256, receipt_authority_bundle, receipt_authority_bundle_sha256)
    evaluator_errors: tuple[str, ...] = ()
    identity_ok = v2_count + v3_count == 0
    receipt_ok = v3_count == 0
    training_projection_ok = False
    if rows:
        evaluator = make_authorization_evaluator(
            root, authority_bundle, authority_bundle_sha256, statement, statement_sha256,
            identity_authority_bundle, identity_authority_bundle_sha256, identity_mapping, identity_mapping_sha256,
            identity_statement, identity_statement_sha256, receipt_archive, receipt_archive_sha256,
            receipt_authority_bundle, receipt_authority_bundle_sha256,
        )
        evaluator_errors = evaluator.errors
        if evaluator_errors:
            reasons.append("authorization_or_trust_verification_failed")
        training_projection_ok = bool(evaluator.bound_training_rows())
        if not training_projection_ok:
            reasons.append("model_training_projection_not_bound")
        if v2_count + v3_count:
            if not all(identity_values):
                reasons.append("identity_trust_material_required_for_v2_v3")
            elif evaluator.cluster_independence_bound:
                identity_ok = True
            else:
                reasons.append("identity_cluster_binding_not_verified")
        if v3_count:
            if not all(receipt_values):
                reasons.append("receipt_trust_material_required_for_v3")
            elif set(evaluator.receipt_bound_observation_ids):
                # Exact full coverage is asserted by make_authorization_evaluator:
                # it fails if archive and formal v3 observation IDs differ.
                receipt_ok = not evaluator_errors
            else:
                reasons.append("receipt_binding_not_verified")
    reason_codes = sorted(set(reasons))
    status = "ready" if rows and not reason_codes and identity_ok and receipt_ok and training_projection_ok else "not_ready"
    input_digests = {name: value.upper() for name, value in zip(SHA_FIELDS, (
        authority_bundle_sha256, statement_sha256, identity_authority_bundle_sha256, identity_mapping_sha256,
        identity_statement_sha256, receipt_archive_sha256, receipt_authority_bundle_sha256,
    )) if isinstance(value, str) and SHA256.fullmatch(value)}
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "reason_codes": reason_codes,
        "formal_registry_sha256": registry_digest,
        "formal_dataset_count": len(rows),
        "manifest_version_counts": dict(sorted(versions.items())),
        "v2_or_v3_dataset_count": v2_count + v3_count,
        "v3_dataset_count": v3_count,
        "identity_binding_status": "ready" if identity_ok else "not_ready",
        "receipt_binding_status": "ready" if receipt_ok else "not_ready",
        "training_projection_status": "ready" if training_projection_ok else "not_ready",
        "input_sha256": input_digests,
        "verification_error_count": len(evaluator_errors),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    for name in ("authority-bundle", "statement", "identity-authority-bundle", "identity-mapping", "identity-statement", "receipt-archive", "receipt-authority-bundle"):
        parser.add_argument("--" + name, type=Path)
        parser.add_argument("--" + name + "-sha256")
    args = parser.parse_args()
    root = args.root.resolve()
    output = _outside(args.output, root)
    report = preflight(
        root, args.authority_bundle, args.authority_bundle_sha256, args.statement, args.statement_sha256,
        args.identity_authority_bundle, args.identity_authority_bundle_sha256, args.identity_mapping, args.identity_mapping_sha256,
        args.identity_statement, args.identity_statement_sha256, args.receipt_archive, args.receipt_archive_sha256,
        args.receipt_authority_bundle, args.receipt_authority_bundle_sha256,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(_canonical_bytes(report))
    return 0 if report["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
