"""Restricted, data-only canonical-evidence declaration interpreter.

This is deliberately *not* a promotion mechanism.  It may only replay field
evidence from pinned JSON snapshots into the already-existing evidence ledger
shape.  Declarations cannot select code, use patterns, transform values, or
write catalog/model/visual data.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any


class DeclarationError(ValueError):
    pass


_SOURCE_KEYS = frozenset({"path", "sha256", "source_id", "source_lineage_id", "source_tier"})
_RULE_KEYS = frozenset({"target_type", "target_id", "field_path", "source_key", "source_item_pointer", "source_item_id_exact", "claim_locator", "evidence_role", "notes"})
_SHADOW_TOP_LEVEL_KEYS = frozenset({"declaration_format", "cohort_id", "mode", "reviewed_at", "sources", "rules"})
_PRODUCTION_TOP_LEVEL_KEYS = frozenset({"declaration_format", "cohort_id", "mode", "reviewed_at", "sources", "rules"})
_FORBIDDEN_KEYS = frozenset({"regex", "transform", "import", "module", "callable", "script", "command"})
_ALLOWED_TIERS = frozenset({"official_item_specific", "official_general", "secondary_reference"})
_ALLOWED_ROLES = frozenset({"independent_identity", "independent_field", "secondary_field"})


def _hash(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest().upper()


def _canonical_hash(value: Any) -> str:
    return _hash(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _evidence_id(target: str, field: str, source: str, locator: str, value: Any) -> str:
    seed = f"{target}\0{field}\0{source}\0{locator}\0{_canonical_hash(value)}"
    return "canonical_evidence_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _safe_snapshot_path(value: object) -> str:
    if not isinstance(value, str) or "\\" in value or not value.endswith(".json"):
        raise DeclarationError("snapshot path must be a repository JSON snapshot")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or not value.startswith("data/source/"):
        raise DeclarationError("snapshot path escapes allowed data/source JSON snapshots")
    return value


def _pointer(document: Any, pointer: object) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        raise DeclarationError("locator must be a non-root RFC6901 JSON pointer")
    current = document
    for encoded in pointer[1:].split("/"):
        if "~" in encoded:
            index = 0
            while index < len(encoded):
                if encoded[index] == "~":
                    if index + 1 >= len(encoded) or encoded[index + 1] not in "01":
                        raise DeclarationError("locator has invalid RFC6901 escape")
                    index += 2
                else:
                    index += 1
        part = encoded.replace("~1", "/").replace("~0", "~")
        try:
            current = current[int(part)] if isinstance(current, list) else current[part]
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise DeclarationError(f"unresolved JSON pointer: {pointer}") from exc
    return current


def _exact(left: Any, right: Any) -> bool:
    return type(left) is type(right) and left == right


def _reject_forbidden(value: Any) -> None:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in _FORBIDDEN_KEYS:
                raise DeclarationError(f"forbidden declarative capability: {key}")
            _reject_forbidden(nested)
    elif isinstance(value, list):
        for nested in value:
            _reject_forbidden(nested)


def load_declaration(root: Path, declaration_path: str | Path) -> tuple[dict[str, Any], bytes]:
    """Load one declaration from a repository-local JSON file, fail closed."""
    root = root.resolve()
    path = (root / declaration_path).resolve() if not Path(declaration_path).is_absolute() else Path(declaration_path).resolve()
    if root not in path.parents:
        raise DeclarationError("declaration path escapes repository root")
    raw_declaration = path.read_bytes()
    declaration = json.loads(raw_declaration)
    if not isinstance(declaration, dict):
        raise DeclarationError("declaration has unknown or missing top-level keys")
    _reject_forbidden(declaration)
    shadow = declaration.get("declaration_format") == "canonical_evidence_declaration_v1" and declaration.get("mode") == "shadow_only"
    production = declaration.get("declaration_format") == "canonical_evidence_declaration_v2" and declaration.get("mode") == "production"
    expected_keys = _SHADOW_TOP_LEVEL_KEYS if shadow else _PRODUCTION_TOP_LEVEL_KEYS if production else frozenset()
    if set(declaration) != expected_keys:
        raise DeclarationError("unsupported declaration format or unknown/missing top-level keys")
    if not isinstance(declaration["cohort_id"], str):
        raise DeclarationError("cohort_id is required")
    if not isinstance(declaration.get("reviewed_at"), str):
        raise DeclarationError("reviewed_at is required")
    return declaration, raw_declaration


def replay(root: Path, declaration_path: str | Path) -> list[dict[str, Any]]:
    """Replay a shadow or production declaration. It performs no writes."""
    root = root.resolve()
    declaration, _raw_declaration = load_declaration(root, declaration_path)
    sources = declaration["sources"]
    rules = declaration["rules"]
    if not isinstance(sources, dict) or not isinstance(rules, list) or not rules:
        raise DeclarationError("sources and non-empty rules are required")
    loaded: dict[str, tuple[dict[str, Any], bytes, Any]] = {}
    for key, source in sources.items():
        if not isinstance(key, str) or not isinstance(source, dict) or set(source) != _SOURCE_KEYS:
            raise DeclarationError("source declaration has unknown or missing fields")
        snapshot = _safe_snapshot_path(source.get("path"))
        if source.get("source_tier") not in _ALLOWED_TIERS or not isinstance(source.get("source_id"), str) or not isinstance(source.get("source_lineage_id"), str):
            raise DeclarationError("source id, lineage, or tier is invalid")
        if not isinstance(source.get("sha256"), str) or len(source["sha256"]) != 64:
            raise DeclarationError("source hash is invalid")
        actual = (root / snapshot).resolve()
        if root not in actual.parents or not actual.is_file():
            raise DeclarationError("declared snapshot is unavailable")
        raw = actual.read_bytes()
        if _hash(raw) != source["sha256"]:
            raise DeclarationError("declared snapshot hash mismatch")
        loaded[key] = (source, raw, json.loads(raw))
    output: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != _RULE_KEYS:
            raise DeclarationError("rule has unknown or missing fields")
        if rule["target_type"] not in {"item", "set"} or not isinstance(rule["target_id"], str) or not isinstance(rule["field_path"], str):
            raise DeclarationError("rule target or field is invalid")
        if rule["evidence_role"] not in _ALLOWED_ROLES or rule["source_key"] not in loaded:
            raise DeclarationError("rule source or evidence role is invalid")
        source, raw, document = loaded[rule["source_key"]]
        selected = _pointer(document, rule["source_item_pointer"])
        if not isinstance(selected, dict):
            raise DeclarationError("source_item_pointer must select an object")
        id_value = selected.get("item_id", selected.get("id"))
        if not _exact(id_value, rule["source_item_id_exact"]):
            raise DeclarationError("source_item_id_exact does not match selected snapshot object")
        claim_locator = rule["claim_locator"]
        # Production evidence is an item-scoped assertion: it may not borrow a
        # convenient global/event fact while claiming it belongs to this item.
        # Shadow fixtures deliberately retain their historical parity freedom.
        if declaration["mode"] == "production" and not (
            claim_locator == rule["source_item_pointer"] or claim_locator.startswith(rule["source_item_pointer"] + "/")
        ):
            raise DeclarationError("production claim_locator escapes selected source item")
        claim = _pointer(document, claim_locator)
        duplicate = (rule["target_type"], rule["target_id"], rule["field_path"], source["source_id"], rule["claim_locator"])
        if duplicate in seen:
            raise DeclarationError("duplicate target/source/field/locator rule")
        seen.add(duplicate)
        output.append({
            "evidence_id": _evidence_id(rule["target_id"], rule["field_path"], source["source_id"], rule["claim_locator"], claim),
            "target_type": rule["target_type"], "target_id": rule["target_id"], "field_path": rule["field_path"],
            "claim_value": claim, "claim_hash": _canonical_hash(claim), "source_id": source["source_id"],
            "source_lineage_id": source["source_lineage_id"], "source_tier": source["source_tier"],
            "source_snapshot_path": source["path"], "source_snapshot_bytes": len(raw), "source_snapshot_hash": _hash(raw),
            "claim_locator": rule["claim_locator"], "claim_locator_hash": _canonical_hash(claim),
            "evidence_role": rule["evidence_role"], "review_status": "approved", "reviewed_at": declaration["reviewed_at"], "notes": rule["notes"],
        })
    output.sort(key=lambda row: (row["target_type"], row["target_id"], row["field_path"], row["source_id"], row["claim_locator"]))
    return output


def ledger_bytes(rows: list[dict[str, Any]]) -> bytes:
    return "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows).encode("utf-8")
