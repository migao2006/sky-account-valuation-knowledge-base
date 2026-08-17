"""Offline, bounded canonical-evidence cohort registry validation.

The registry selects only fixed verifier IDs.  It intentionally never accepts a
Python module or callable name from data, so a data edit cannot cause imports or
execution outside this package.
"""
from __future__ import annotations

import hashlib
import base64
import json
import subprocess
import tempfile
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from tools.validate.declarative_canonical_evidence import DeclarationError, ledger_bytes, load_declaration, replay

REGISTRY_PATH = "data/review/canonical-evidence-cohorts.jsonl"
ALLOWED_VERIFIER_IDS = frozenset({"nintendo_starter_pack", "aurora_faq968", "journey_pack", "moomin_pack", "kizuna_ai_bundle", "skyfest_faq1330_core_five", "tournament_of_triumph_faq1330_core_four", "days_of_color_faq1323_core_three", "days_of_sunlight_faq1343_core_three", "cinnamoroll_popup_cafe_faq1308", "days_of_fortune_faq1264_core_five", "days_of_love_faq1374_core_four", "days_of_treasure_bloom_faq1381_core_six", "declarative_v2"})
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def safe_relative_path(value: object, prefixes: tuple[str, ...]) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and ".." not in path.parts and any(value.startswith(prefix) for prefix in prefixes)


def load_registry(root: Path) -> list[dict[str, Any]]:
    return read_jsonl(root / REGISTRY_PATH)


def _verifier(verifier_id: str) -> tuple[Callable[[Path], list[str]], dict[str, object]] | None:
    # This is deliberately an explicit allowlist, never importlib/data driven.
    if verifier_id == "nintendo_starter_pack":
        from tools.normalize.apply_nintendo_starter_pack import registry_contract, verify
        return verify, registry_contract()
    if verifier_id == "aurora_faq968":
        from tools.normalize.apply_aurora_faq968_cohort import registry_contract, verify
        return verify, registry_contract()
    if verifier_id == "journey_pack":
        from tools.normalize.apply_journey_pack_cohort import registry_contract, verify
        return verify, registry_contract()
    if verifier_id == "moomin_pack":
        try:
            from tools.normalize.apply_moomintroll_accessory_set_cohort import registry_contract, verify
        except ImportError:
            return None
        return verify, registry_contract()
    if verifier_id == "kizuna_ai_bundle":
        from tools.normalize.apply_kizuna_ai_2022_cohort import registry_contract, verify
        return verify, registry_contract()
    if verifier_id == "skyfest_faq1330_core_five":
        from tools.normalize.apply_skyfest_faq1330_core_five_cohort import registry_contract, verify
        return verify, registry_contract()
    if verifier_id == "tournament_of_triumph_faq1330_core_four":
        from tools.normalize.apply_tournament_of_triumph_faq1330_core_four_cohort import registry_contract, verify
        return verify, registry_contract()
    if verifier_id == "days_of_color_faq1323_core_three":
        from tools.normalize.apply_days_of_color_faq1323_core_three_cohort import registry_contract, verify
        return verify, registry_contract()
    if verifier_id == "days_of_sunlight_faq1343_core_three":
        from tools.normalize.apply_days_of_sunlight_faq1343_core_three_cohort import registry_contract, verify
        return verify, registry_contract()
    if verifier_id == "cinnamoroll_popup_cafe_faq1308":
        from tools.normalize.apply_cinnamoroll_popup_cafe_faq1308_cohort import registry_contract, verify
        return verify, registry_contract()
    if verifier_id == "days_of_fortune_faq1264_core_five":
        from tools.normalize.apply_days_of_fortune_faq1264_core_five_cohort import registry_contract, verify
        return verify, registry_contract()
    if verifier_id == "days_of_love_faq1374_core_four":
        from tools.normalize.apply_days_of_love_faq1374_core_four_cohort import registry_contract, verify
        return verify, registry_contract()
    if verifier_id == "days_of_treasure_bloom_faq1381_core_six":
        from tools.normalize.apply_days_of_treasure_bloom_faq1381_core_six_cohort import registry_contract, verify
        return verify, registry_contract()
    # An allowlisted but not-yet-implemented verifier remains unavailable. If
    # made active, validate_registry fails closed instead of trusting a ledger.
    return None


def _list_field(row: dict[str, Any], field: str, prefix: str, problems: list[str]) -> list[Any]:
    value = row.get(field)
    if not isinstance(value, list):
        problems.append(f"{prefix}: {field} must be an array")
        return []
    return value


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest().upper()


def _production_review(root: Path, row: dict[str, Any], prefix: str, problems: list[str], authority_bundle: str | Path | None, authority_bundle_sha256: str | None) -> bool:
    """Verify the deliberately data-only, independently recorded dual approval."""
    if authority_bundle is None or not isinstance(authority_bundle_sha256, str):
        problems.append(f"{prefix}: external review authority bundle and SHA-256 are required")
        return False
    bundle_path = Path(authority_bundle).resolve()
    if root.resolve() in bundle_path.parents or not bundle_path.is_file() or _sha256(bundle_path.read_bytes()) != authority_bundle_sha256.upper():
        problems.append(f"{prefix}: external review authority bundle digest mismatch")
        return False
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8")); authorities = bundle.get("authorities", [])
    except (OSError, json.JSONDecodeError, AttributeError):
        authorities = []
    if not isinstance(bundle, dict) or bundle.get("schema_version") != "canonical-evidence-review-authority-bundle-v1" or not isinstance(authorities, list):
        problems.append(f"{prefix}: external review authority bundle is malformed")
        return False
    authority_index = {entry.get("authority_id"): entry for entry in authorities if isinstance(entry, dict)}
    if len(authority_index) != len(authorities):
        problems.append(f"{prefix}: external review authority IDs must be unique")
        return False
    fingerprints: set[str] = set()
    for authority in authorities:
        try:
            with tempfile.TemporaryDirectory() as temporary:
                key = Path(temporary) / "authority.pub"; key.write_text(str(authority["public_key"]) + "\n", encoding="utf-8")
                actual = subprocess.run(["ssh-keygen", "-lf", str(key), "-E", "sha256"], capture_output=True, text=True, check=True).stdout.split()[1]
            if authority.get("fingerprint") != actual or actual in fingerprints or authority.get("revoked") is True:
                raise ValueError
            fingerprints.add(actual)
        except (KeyError, ValueError, OSError, subprocess.SubprocessError, IndexError):
            problems.append(f"{prefix}: external review authority key/fingerprint is invalid, duplicated, or revoked")
            return False
    review_path = row.get("review_metadata_path")
    if not safe_relative_path(review_path, ("data/review/canonical-evidence-reviews/",)):
        problems.append(f"{prefix}: unsafe review_metadata_path")
        return False
    path = root / str(review_path)
    if not path.is_file():
        problems.append(f"{prefix}: review metadata is missing")
        return False
    try:
        metadata = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        problems.append(f"{prefix}: review metadata is invalid JSON")
        return False
    expected = {"review_format", "cohort_id", "declaration_sha256", "review_status", "release_required", "approvals"}
    if not isinstance(metadata, dict) or set(metadata) != expected:
        problems.append(f"{prefix}: review metadata has unknown or missing fields")
        return False
    if (metadata.get("review_format"), metadata.get("cohort_id"), metadata.get("declaration_sha256"), metadata.get("review_status"), metadata.get("release_required")) != ("canonical_evidence_review_v1", row.get("cohort_id"), row.get("declaration_sha256"), "approved", True):
        problems.append(f"{prefix}: review metadata does not approve this release-required declaration")
        return False
    approvals = metadata.get("approvals")
    if not isinstance(approvals, list) or len(approvals) < 2:
        problems.append(f"{prefix}: production declaration requires two approvals")
        return False
    reviewer_ids: set[str] = set()
    reviewer_fingerprints: set[str] = set()
    for approval in approvals:
        if not isinstance(approval, dict) or set(approval) != {"authority_id", "fingerprint", "reviewed_at", "payload_sha256", "signature"}:
            problems.append(f"{prefix}: approval has unknown or missing fields")
            return False
        reviewer = approval.get("authority_id")
        reviewed_at = approval.get("reviewed_at")
        authority = authority_index.get(reviewer)
        if not isinstance(reviewer, str) or not isinstance(authority, dict) or authority.get("fingerprint") != approval.get("fingerprint") or "canonical_evidence_reviewer" not in authority.get("roles", []) or not isinstance(reviewed_at, str):
            problems.append(f"{prefix}: approval is malformed")
            return False
        payload = f"canonical_evidence_review_v1\0{row['cohort_id']}\0{row['declaration_sha256']}\0{reviewer}\0{reviewed_at}".encode("utf-8")
        if approval.get("payload_sha256") != _sha256(payload):
            problems.append(f"{prefix}: approval attestation is not bound to this declaration")
            return False
        try:
            signature = base64.b64decode(str(approval["signature"]), validate=True)
            with tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary); allowed = base / "allowed_signers"; signature_path = base / "review.sig"
                allowed.write_text(f"{reviewer} {authority['public_key']}\n", encoding="utf-8"); signature_path.write_bytes(signature)
                verified = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", str(allowed), "-I", reviewer, "-n", "sky-canonical-evidence-review-v1", "-s", str(signature_path)], input=payload, capture_output=True, check=False).returncode == 0
            if not verified: raise ValueError
        except (ValueError, KeyError, OSError, subprocess.SubprocessError):
            problems.append(f"{prefix}: detached reviewer signature does not verify")
            return False
        reviewer_ids.add(reviewer)
        reviewer_fingerprints.add(str(approval.get("fingerprint")))
    if len(reviewer_ids) != len(approvals) or len(reviewer_fingerprints) != len(approvals):
        problems.append(f"{prefix}: production approvals must be from distinct reviewers")
        return False
    return True


def validate_registry(
    root: Path,
    items: dict[str, dict[str, Any]],
    sets: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]], review_authority_bundle: str | Path | None = None, review_authority_bundle_sha256: str | None = None,
) -> tuple[list[str], dict[str, list[dict[str, Any]]]]:
    """Return problems and active evidence rows keyed by cohort id."""
    problems: list[str] = []
    active: dict[str, list[dict[str, Any]]] = {}
    seen_cohorts: set[str] = set()
    seen_verifiers: set[str] = set()
    seen_paths: set[str] = set()
    seen_declaration_paths: set[str] = set()
    seen_declaration_digests: set[str] = set()
    seen_targets: set[tuple[str, str]] = set()
    seen_sources: set[str] = set()
    for row in load_registry(root):
        cohort_id = str(row.get("cohort_id", "unknown"))
        prefix = f"canonical-evidence-registry:{cohort_id}"
        if cohort_id in seen_cohorts:
            problems.append(f"{prefix}: duplicate cohort_id")
        seen_cohorts.add(cohort_id)
        verifier_id = row.get("verifier_id")
        snapshot_paths = _list_field(row, "snapshot_paths", prefix, problems)
        source_ids = _list_field(row, "source_ids", prefix, problems)
        target_item_ids = _list_field(row, "target_item_ids", prefix, problems)
        target_set_ids = _list_field(row, "target_set_ids", prefix, problems)
        if verifier_id not in ALLOWED_VERIFIER_IDS:
            problems.append(f"{prefix}: unknown verifier_id")
        elif verifier_id in seen_verifiers and verifier_id != "declarative_v2":
            problems.append(f"{prefix}: duplicate verifier_id")
        else:
            seen_verifiers.add(str(verifier_id))
        evidence_path = row.get("evidence_path")
        if not safe_relative_path(evidence_path, ("data/review/",)):
            problems.append(f"{prefix}: unsafe evidence_path")
        elif evidence_path in seen_paths:
            problems.append(f"{prefix}: duplicate evidence_path")
        else:
            seen_paths.add(evidence_path)
        for path in snapshot_paths:
            if not safe_relative_path(path, ("data/source/",)):
                problems.append(f"{prefix}: unsafe snapshot_path")
        target_pairs = {("item", target) for target in target_item_ids} | {("set", target) for target in target_set_ids}
        if len(target_pairs) != len(target_item_ids) + len(target_set_ids):
            problems.append(f"{prefix}: duplicate target within cohort")
        overlap = seen_targets & target_pairs
        if overlap:
            problems.append(f"{prefix}: target already belongs to another cohort")
        seen_targets |= target_pairs
        for item_id in target_item_ids:
            item = items.get(item_id)
            if not item or item.get("verification_status") != "verified" or item.get("model_feature_status") not in {"eligible", "excluded_pending_verification"}:
                problems.append(f"{prefix}: item target must be verified with a recognized model status")
        for set_id in target_set_ids:
            if set_id not in sets:
                problems.append(f"{prefix}: set target is not canonical")
        for source_id in source_ids:
            if source_id not in sources:
                problems.append(f"{prefix}: source_id is not registered")
            if source_id in seen_sources:
                # A source may support evidence in distinct cohorts, so only the
                # list itself is unique; targets/paths are globally exclusive.
                pass
            seen_sources.add(source_id)
        is_active = row.get("review_status") == "approved" or row.get("release_required") is True
        if not is_active:
            continue
        if verifier_id == "declarative_v2":
            if row.get("review_status") != "approved" or row.get("release_required") is not True:
                problems.append(f"{prefix}: declarative production cohort must be approved and release-required")
                continue
            required = {"declaration_path", "declaration_sha256", "review_metadata_path"}
            if not required <= set(row):
                problems.append(f"{prefix}: declarative production fields are missing")
                continue
            declaration_path = row.get("declaration_path")
            if declaration_path in seen_declaration_paths:
                problems.append(f"{prefix}: duplicate declaration_path")
            seen_declaration_paths.add(str(declaration_path))
            if row.get("declaration_sha256") in seen_declaration_digests:
                problems.append(f"{prefix}: duplicate declaration_sha256")
            seen_declaration_digests.add(str(row.get("declaration_sha256")))
            if not safe_relative_path(declaration_path, ("data/review/canonical-evidence-declarations/",)):
                problems.append(f"{prefix}: unsafe declaration_path")
                continue
            path = root / str(declaration_path)
            if not path.is_file() or not isinstance(row.get("declaration_sha256"), str) or _sha256(path.read_bytes()) != row["declaration_sha256"]:
                problems.append(f"{prefix}: declaration digest mismatch or declaration is missing")
                continue
            try:
                declaration, raw_declaration = load_declaration(root, str(declaration_path))
                if declaration.get("declaration_format") != "canonical_evidence_declaration_v2" or declaration.get("mode") != "production":
                    problems.append(f"{prefix}: shadow_only declarations cannot be promoted")
                    continue
                if declaration.get("cohort_id") != cohort_id:
                    problems.append(f"{prefix}: declaration cohort_id differs from registry")
                    continue
                declared_sources = declaration.get("sources", {})
                if {value.get("source_id") for value in declared_sources.values() if isinstance(value, dict)} != set(source_ids):
                    problems.append(f"{prefix}: declaration sources differ from registry")
                if {value.get("path") for value in declared_sources.values() if isinstance(value, dict)} != set(snapshot_paths):
                    problems.append(f"{prefix}: declaration snapshots differ from registry")
                lineages = [value.get("source_lineage_id") for value in declared_sources.values() if isinstance(value, dict)]
                if len(lineages) != len(set(lineages)):
                    problems.append(f"{prefix}: declarative sources must have independent lineages")
                for value in declared_sources.values():
                    if not isinstance(value, dict):
                        continue
                    registered = sources.get(value.get("source_id"))
                    if not registered or registered.get("source_lineage_id") != value.get("source_lineage_id"):
                        problems.append(f"{prefix}: declaration source is unregistered or lineage-mismatched")
                declared_targets = {(rule.get("target_type"), rule.get("target_id")) for rule in declaration.get("rules", []) if isinstance(rule, dict)}
                if declared_targets != target_pairs:
                    problems.append(f"{prefix}: declaration targets differ from registry")
                if not _production_review(root, row, prefix, problems, review_authority_bundle, review_authority_bundle_sha256):
                    continue
                replayed = replay(root, str(declaration_path))
            except (DeclarationError, OSError, json.JSONDecodeError) as exc:
                problems.append(f"{prefix}: declarative replay failed: {exc}")
                continue
            if not isinstance(evidence_path, str) or not (root / evidence_path).is_file():
                problems.append(f"{prefix}: evidence ledger is missing")
                continue
            ledger = read_jsonl(root / evidence_path)
            if ledger != replayed or ledger_bytes(ledger) != ledger_bytes(replayed):
                problems.append(f"{prefix}: evidence ledger differs from declarative replay")
            # A verbatim source claim is not sufficient by itself: production
            # evidence must attest the exact value already stored for the
            # canonical target/field.  This prevents an availability or other
            # field assertion from being attached to the wrong catalog item.
            for evidence in replayed:
                target = items.get(evidence["target_id"]) if evidence["target_type"] == "item" else sets.get(evidence["target_id"])
                field = evidence["field_path"]
                if not isinstance(target, dict) or field not in target or target[field] != evidence["claim_value"]:
                    problems.append(f"{prefix}: claim value does not match canonical target field")
            active[cohort_id] = ledger
            continue
        verifier_spec = _verifier(str(verifier_id)) if isinstance(verifier_id, str) else None
        if verifier_spec is None:
            problems.append(f"{prefix}: verifier is unavailable")
            continue
        verifier, contract = verifier_spec
        for field in ("cohort_id", "evidence_path", "snapshot_paths", "source_ids", "target_item_ids", "target_set_ids"):
            actual = sorted(row.get(field, [])) if field.endswith("_paths") or field.endswith("_ids") else row.get(field)
            expected_value = contract.get(field)
            expected = sorted(expected_value) if isinstance(expected_value, list) else expected_value
            if actual != expected:
                problems.append(f"{prefix}: {field} differs from verifier contract")
        for snapshot_path in snapshot_paths:
            if isinstance(snapshot_path, str) and safe_relative_path(snapshot_path, ("data/source/",)) and not (root / snapshot_path).is_file():
                problems.append(f"{prefix}: snapshot is missing")
        if not isinstance(evidence_path, str) or not (root / evidence_path).is_file():
            problems.append(f"{prefix}: evidence ledger is missing")
            continue
        ledger = read_jsonl(root / evidence_path)
        active[cohort_id] = ledger
        evidence_ids = [entry.get("evidence_id") for entry in ledger]
        if len(evidence_ids) != len(set(evidence_ids)):
            problems.append(f"{prefix}: duplicate evidence_id in ledger")
        actual_targets = {(entry.get("target_type"), entry.get("target_id")) for entry in ledger}
        if actual_targets != target_pairs:
            problems.append(f"{prefix}: ledger targets differ from registry targets")
        if any(entry.get("review_status") != "approved" for entry in ledger):
            problems.append(f"{prefix}: ledger contains non-approved evidence")
        if {entry.get("source_id") for entry in ledger} != set(source_ids):
            problems.append(f"{prefix}: ledger sources differ from registry sources")
        if {entry.get("source_snapshot_path") for entry in ledger} != set(snapshot_paths):
            problems.append(f"{prefix}: ledger snapshots differ from registry snapshots")
        for verifier_problem in verifier(root):
            problems.append(f"{prefix}: verifier: {verifier_problem}")
    return problems, active
