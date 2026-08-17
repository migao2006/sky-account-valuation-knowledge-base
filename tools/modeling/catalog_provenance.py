"""Deterministic catalog provenance shared by vector and model tooling.

The catalog is deliberately pinned by the bytes of the files that determine
item identity, aliases, set membership, and model eligibility.  This module
does not fetch anything: it only hashes local, canonical repository files.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


PINNED_CATALOG_PATHS = (
    "knowledge/items/items.jsonl",
    "knowledge/aliases/item-aliases.jsonl",
    "knowledge/sets/item-sets.jsonl",
)


class CatalogProvenanceError(ValueError):
    """Raised when a local catalog/vector cannot prove its exact provenance."""


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _aggregate(entries: list[tuple[str, str]]) -> str:
    digest = hashlib.sha256()
    for relative, file_hash in sorted(entries):
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest().upper()


def canonical_item_ids(items: list[dict[str, Any]]) -> list[str]:
    identifiers = [row.get("item_id") for row in items]
    if any(not isinstance(item_id, str) or not item_id.startswith("item_") for item_id in identifiers):
        raise CatalogProvenanceError("catalog_contains_invalid_item_id")
    if len(identifiers) != len(set(identifiers)):
        raise CatalogProvenanceError("catalog_contains_duplicate_item_id")
    return sorted(identifiers)


def ordered_item_universe_sha256(item_ids: list[str]) -> str:
    """Hash sorted canonical IDs, independent of JSONL row ordering."""
    ordered = sorted(item_ids)
    return hashlib.sha256("".join(f"{item_id}\n" for item_id in ordered).encode("utf-8")).hexdigest().upper()


def catalog_provenance(root: Path) -> dict[str, Any]:
    """Return the exact vector/model catalog binding for ``root``.

    The file aggregate is byte-sensitive; the item-universe digest is a second
    guard that makes additions/removals/replacements explicit to consumers.
    """
    root = root.resolve()
    paths: list[str] = []
    hashes: list[tuple[str, str]] = []
    for relative in PINNED_CATALOG_PATHS:
        path = root / relative
        if not path.is_file():
            raise CatalogProvenanceError(f"missing_pinned_catalog_path:{relative}")
        paths.append(relative)
        hashes.append((relative, hashlib.sha256(path.read_bytes()).hexdigest().upper()))
    items = read_jsonl(root / PINNED_CATALOG_PATHS[0])
    item_ids = canonical_item_ids(items)
    return {
        "canonical_item_ids_sha256": ordered_item_universe_sha256(item_ids),
        "pinned_catalog_paths": list(PINNED_CATALOG_PATHS),
        "pinned_catalog_sha256": _aggregate(hashes),
    }


def model_eligible_item_ids(root: Path) -> set[str]:
    """Return only canonical items explicitly verified and model eligible."""
    return {
        row["item_id"] for row in read_jsonl(root / PINNED_CATALOG_PATHS[0])
        if row.get("verification_status") == "verified" and row.get("model_feature_status") == "eligible"
    }


def validate_vector_catalog_provenance(vector: dict[str, Any], root: Path) -> None:
    """Fail closed when a vector's catalog or item-state policy is stale/forged."""
    expected = catalog_provenance(root)
    account_id = vector.get("account_id", "unknown")
    actual = vector.get("catalog_provenance")
    if actual != expected:
        raise CatalogProvenanceError(f"stale_catalog_provenance:{account_id}")
    items = {row["item_id"]: row for row in read_jsonl(root / PINNED_CATALOG_PATHS[0])}
    states = vector.get("item_states")
    if not isinstance(states, list):
        raise CatalogProvenanceError(f"invalid_item_states:{account_id}")
    state_ids = [state.get("item_id") for state in states if isinstance(state, dict)]
    if len(state_ids) != len(states) or len(state_ids) != len(set(state_ids)) or set(state_ids) != set(items):
        raise CatalogProvenanceError(f"item_states_not_exact_canonical_universe:{account_id}")
    for state in states:
        item_id = state["item_id"]
        item = items[item_id]
        expected_feature = (
            item.get("verification_status") == "verified"
            and item.get("model_feature_status") == "eligible"
            and state.get("state") in {"owned", "confirmed_missing"}
            and state.get("evidence_state") in {"profile_claim", "text_claim"}
            and state.get("conflict") is False
        )
        if state.get("model_feature") is not expected_feature:
            raise CatalogProvenanceError(f"item_model_eligibility_mismatch:{account_id}:{item_id}")
        expected_review = "approved" if item.get("verification_status") == "verified" else "needs_review" if item.get("verification_status") == "needs_review" else "unknown"
        if state.get("review_status") != expected_review:
            raise CatalogProvenanceError(f"item_review_status_mismatch:{account_id}:{item_id}")
    state_by_id = {state["item_id"]: state for state in states}
    set_rows = vector.get("feature_groups", {}).get("item_sets")
    canonical_sets = {row["set_id"]: row for row in read_jsonl(root / PINNED_CATALOG_PATHS[2])}
    if not isinstance(set_rows, list) or len(set_rows) != len(canonical_sets):
        raise CatalogProvenanceError(f"set_profiles_not_exact_canonical_universe:{account_id}")
    if len({row.get("set_id") for row in set_rows if isinstance(row, dict)}) != len(set_rows):
        raise CatalogProvenanceError(f"set_profiles_not_exact_canonical_universe:{account_id}")
    for row in set_rows:
        if not isinstance(row, dict) or row.get("set_id") not in canonical_sets:
            raise CatalogProvenanceError(f"set_profiles_not_exact_canonical_universe:{account_id}")
        required = sorted(set(canonical_sets[row["set_id"]].get("required_item_ids", [])))
        required_states = {item_id: state_by_id.get(item_id) for item_id in required}
        owned = sorted(item_id for item_id, state in required_states.items() if state and state.get("state") == "owned")
        missing = sorted(item_id for item_id, state in required_states.items() if state and state.get("state") == "confirmed_missing")
        known = sorted(set(owned) | set(missing))
        eligible = bool(required) and all(
            state and state.get("model_feature") is True and state.get("review_status") == "approved"
            for state in required_states.values()
        )
        model_feature = eligible and len(known) == len(required)
        expected_set = {
            "set_id": row["set_id"], "owned_item_ids": owned,
            "confirmed_missing_item_ids": missing, "member_count": len(required),
            "known_member_count": len(known),
            "completion_ratio": (len(owned) / len(required)) if model_feature else None,
            "is_complete": (len(owned) == len(required)) if model_feature else None,
            "model_feature": model_feature,
        }
        if row != expected_set:
            raise CatalogProvenanceError(f"set_profile_policy_mismatch:{account_id}:{row['set_id']}")


def validate_artifact_catalog_provenance(artifact: dict[str, Any], root: Path) -> None:
    """Require model artifacts to bind catalog files directly and exactly."""
    expected = catalog_provenance(root)
    if artifact.get("catalog_provenance") != expected:
        raise CatalogProvenanceError("artifact_catalog_provenance_mismatch")
    paths = artifact.get("input_snapshot_paths")
    if not isinstance(paths, list) or not set(PINNED_CATALOG_PATHS).issubset(paths):
        raise CatalogProvenanceError("artifact_catalog_paths_not_direct_snapshot_inputs")
