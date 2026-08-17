"""Offline, bounded canonical-evidence cohort registry validation.

The registry selects only fixed verifier IDs.  It intentionally never accepts a
Python module or callable name from data, so a data edit cannot cause imports or
execution outside this package.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Callable

REGISTRY_PATH = "data/review/canonical-evidence-cohorts.jsonl"
ALLOWED_VERIFIER_IDS = frozenset({"nintendo_starter_pack", "aurora_faq968", "journey_pack", "moomin_pack", "kizuna_ai_bundle", "skyfest_faq1330_core_five", "tournament_of_triumph_faq1330_core_four", "days_of_color_faq1323_core_three", "days_of_sunlight_faq1343_core_three", "cinnamoroll_popup_cafe_faq1308"})
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
    # An allowlisted but not-yet-implemented verifier remains unavailable. If
    # made active, validate_registry fails closed instead of trusting a ledger.
    return None


def _list_field(row: dict[str, Any], field: str, prefix: str, problems: list[str]) -> list[Any]:
    value = row.get(field)
    if not isinstance(value, list):
        problems.append(f"{prefix}: {field} must be an array")
        return []
    return value


def validate_registry(
    root: Path,
    items: dict[str, dict[str, Any]],
    sets: dict[str, dict[str, Any]],
    sources: dict[str, dict[str, Any]],
) -> tuple[list[str], dict[str, list[dict[str, Any]]]]:
    """Return problems and active evidence rows keyed by cohort id."""
    problems: list[str] = []
    active: dict[str, list[dict[str, Any]]] = {}
    seen_cohorts: set[str] = set()
    seen_verifiers: set[str] = set()
    seen_paths: set[str] = set()
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
        elif verifier_id in seen_verifiers:
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
