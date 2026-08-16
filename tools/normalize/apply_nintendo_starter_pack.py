#!/usr/bin/env python3
"""Replay and apply the bounded Nintendo Starter Pack evidence slice.

This utility is deliberately offline: it reads two committed snapshots and
updates only the four existing canonical records, their set, one availability
row, four source-description references, and its evidence ledger.  It refuses
to write when a source hash, JSON-pointer claim, foreign key, or registered
source lineage disagrees.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

OFFICIAL_SOURCE = "source_tgc_faq_823_nintendo_starter_pack"
SECONDARY_SOURCE = "source_skygame_data_1_3_4"
OFFICIAL_PATH = "data/source/research/tgc-faq-823-nintendo-starter-pack.json"
SECONDARY_PATH = "data/source/vendor/skygame-data-1.3.4-items.json"
OFFICIAL_LINEAGE = "lineage_tgc_support_faq_823"
SECONDARY_LINEAGE = "lineage_skygame_data_1_3_4"
OFFICIAL_SNAPSHOT_SHA256 = "810A83A33D30327D4497935BA0661B0F43CC9939EB9375048B6107DCFBD8FCFE"
SECONDARY_SNAPSHOT_SHA256 = "21CCAD77006C425B27EE9314870BB5BB77E8436459C6DA214ABCB2B0D8329BBB"
AS_OF = "2026-08-17"
SET_ID = "set_nintendo_starter_pack"
AVAILABILITY_ID = "availability_nintendo_starter"
ITEMS = (
    ("item_nintendo_blue_cape", 1943, "Nintendo Blue Switch Cape", "cape"),
    ("item_nintendo_red_cape", 1944, "Nintendo Red Switch Cape", "cape"),
    ("item_nintendo_hair", 1945, "Nintendo Elf Hair", "hair"),
    ("item_nintendo_vessel_flute", 1946, "Vessel Flute", "instrument"),
)
OFFICIAL_DESCRIPTIONS = {
    "item_nintendo_blue_cape": "blue themed cape",
    "item_nintendo_red_cape": "red themed cape",
    "item_nintendo_hair": "elvish hairstyle",
    "item_nintendo_vessel_flute": "vessel flute",
}


def registry_contract() -> dict[str, object]:
    return {
        "cohort_id": "canonical_cohort_nintendo_starter_pack",
        "evidence_path": "data/review/nintendo-starter-pack-canonical-evidence.jsonl",
        "snapshot_paths": [OFFICIAL_PATH, SECONDARY_PATH],
        "source_ids": [SECONDARY_SOURCE, OFFICIAL_SOURCE],
        "target_item_ids": sorted(item_id for item_id, *_rest in ITEMS),
        "target_set_ids": [SET_ID],
    }


class NintendoEvidenceError(ValueError):
    pass


def sha(value: bytes | str) -> str:
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest().upper()


def claim_hash(value: Any) -> str:
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows), encoding="utf-8", newline="\n")


def safe_path(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    if root.resolve() not in candidate.parents or not candidate.is_file():
        raise NintendoEvidenceError(f"snapshot unavailable or escapes root: {relative}")
    return candidate


def pointer(document: Any, value: str) -> Any:
    if not value.startswith("/"):
        raise NintendoEvidenceError(f"invalid JSON pointer: {value!r}")
    current = document
    for token in value[1:].split("/"):
        token = token.replace("~1", "/").replace("~0", "~")
        try:
            current = current[int(token)] if isinstance(current, list) else current[token]
        except (KeyError, IndexError, ValueError, TypeError) as exc:
            raise NintendoEvidenceError(f"unresolved JSON pointer: {value!r}") from exc
    return current


def evidence_id(target_id: str, field_path: str, source_id: str) -> str:
    return "canonical_evidence_" + hashlib.sha256(f"{target_id}\0{field_path}\0{source_id}".encode()).hexdigest()[:24]


def evidence_row(*, target_type: str, target_id: str, field_path: str, value: Any, source_id: str, lineage: str, tier: str, snapshot_path: str, snapshot_bytes: bytes, locator: str, role: str, notes: str = "") -> dict[str, Any]:
    located = pointer(json.loads(snapshot_bytes.decode("utf-8")), locator)
    if located != value:
        raise NintendoEvidenceError(f"claim does not equal source locator: {target_id}:{field_path}")
    return {
        "evidence_id": evidence_id(target_id, field_path, source_id), "target_type": target_type, "target_id": target_id,
        "field_path": field_path, "claim_value": value, "claim_hash": claim_hash(value),
        "source_id": source_id, "source_lineage_id": lineage, "source_tier": tier,
        "source_snapshot_path": snapshot_path, "source_snapshot_bytes": len(snapshot_bytes), "source_snapshot_hash": sha(snapshot_bytes),
        "claim_locator": locator, "claim_locator_hash": claim_hash(located), "evidence_role": role,
        "review_status": "approved", "reviewed_at": AS_OF, "notes": notes,
    }


def _vendor_item(document: dict[str, Any], vendor_id: int) -> tuple[int, dict[str, Any]]:
    for index, row in enumerate(document.get("items", [])):
        if row.get("id") == vendor_id:
            return index, row
    raise NintendoEvidenceError(f"pinned secondary item missing: {vendor_id}")


def build(root: Path, *, allow_registry_bootstrap: bool = False) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    root = root.resolve()
    official_bytes = safe_path(root, OFFICIAL_PATH).read_bytes()
    secondary_bytes = safe_path(root, SECONDARY_PATH).read_bytes()
    if sha(official_bytes) != OFFICIAL_SNAPSHOT_SHA256:
        raise NintendoEvidenceError("official snapshot hash mismatch")
    if sha(secondary_bytes) != SECONDARY_SNAPSHOT_SHA256:
        raise NintendoEvidenceError("secondary snapshot hash mismatch")
    official = json.loads(official_bytes.decode("utf-8")); secondary = json.loads(secondary_bytes.decode("utf-8"))
    official_descriptions = official.get("facts", {}).get("included_item_descriptions_en")
    if official_descriptions != OFFICIAL_DESCRIPTIONS:
        raise NintendoEvidenceError("official snapshot descriptive component contract changed")
    if official.get("facts", {}).get("pack_description_en") != "Starter Pack for Nintendo Switch":
        raise NintendoEvidenceError("official snapshot pack description contract changed")
    if official.get("facts", {}).get("platform_context") != "Nintendo Switch":
        raise NintendoEvidenceError("official snapshot platform contract changed")

    sources = {row["source_id"]: row for row in read_jsonl(root / "knowledge/sources/sources.jsonl")}
    requirements = {
        OFFICIAL_SOURCE: ("official_support", OFFICIAL_LINEAGE),
        SECONDARY_SOURCE: ("community_database", SECONDARY_LINEAGE),
    }
    for source_id, (source_type, lineage) in requirements.items():
        source = sources.get(source_id)
        if source is None and allow_registry_bootstrap:
            continue
        if allow_registry_bootstrap and source and source.get("source_type") == source_type and source.get("source_lineage_id") is None:
            continue
        if not source or source.get("source_type") != source_type or source.get("source_lineage_id") != lineage:
            raise NintendoEvidenceError(f"source registry or lineage mismatch: {source_id}")

    item_rows = {row["item_id"]: row for row in read_jsonl(root / "knowledge/items/items.jsonl")}
    set_rows = {row["set_id"]: row for row in read_jsonl(root / "knowledge/sets/item-sets.jsonl")}
    if SET_ID not in set_rows or any(item_id not in item_rows for item_id, *_ in ITEMS):
        raise NintendoEvidenceError("canonical target IDs are missing")
    evidence: list[dict[str, Any]] = []
    for item_id, vendor_id, name, category in ITEMS:
        vendor_index, vendor = _vendor_item(secondary, vendor_id)
        if vendor.get("name") != name:
            raise NintendoEvidenceError(f"secondary name changed: {vendor_id}")
        vendor_category = "instrument" if vendor.get("type") == "Held" and vendor.get("subtype") == "Instrument" else str(vendor.get("type", "")).casefold()
        if vendor_category != category:
            raise NintendoEvidenceError(f"secondary category changed: {vendor_id}")
        description = OFFICIAL_DESCRIPTIONS[item_id]
        description_locator = f"/facts/included_item_descriptions_en/{item_id}"
        evidence.extend((
            evidence_row(target_type="item", target_id=item_id, field_path="identity_description", value=description, source_id=OFFICIAL_SOURCE, lineage=OFFICIAL_LINEAGE, tier="official_item_specific", snapshot_path=OFFICIAL_PATH, snapshot_bytes=official_bytes, locator=description_locator, role="independent_field", notes="The official source describes the component but does not provide the vendor-aligned exact English title."),
            evidence_row(target_type="item", target_id=item_id, field_path="set_membership", value=description, source_id=OFFICIAL_SOURCE, lineage=OFFICIAL_LINEAGE, tier="official_item_specific", snapshot_path=OFFICIAL_PATH, snapshot_bytes=official_bytes, locator=description_locator, role="independent_field", notes="The official descriptive component is mapped to this existing canonical set member; it is not treated as an official exact item title."),
            evidence_row(target_type="item", target_id=item_id, field_path="canonical_name_en", value=name, source_id=SECONDARY_SOURCE, lineage=SECONDARY_LINEAGE, tier="secondary_reference", snapshot_path=SECONDARY_PATH, snapshot_bytes=secondary_bytes, locator=f"/items/{vendor_index}/name", role="secondary_field"),
            evidence_row(target_type="item", target_id=item_id, field_path="item_category", value=vendor.get("type") if category != "instrument" else vendor.get("subtype"), source_id=SECONDARY_SOURCE, lineage=SECONDARY_LINEAGE, tier="secondary_reference", snapshot_path=SECONDARY_PATH, snapshot_bytes=secondary_bytes, locator=f"/items/{vendor_index}/type" if category != "instrument" else f"/items/{vendor_index}/subtype", role="secondary_field", notes=f"Apply contract maps this vendor type to canonical category {category}."),
        ))
    evidence.extend((
        evidence_row(target_type="set", target_id=SET_ID, field_path="identity_description", value="Starter Pack for Nintendo Switch", source_id=OFFICIAL_SOURCE, lineage=OFFICIAL_LINEAGE, tier="official_item_specific", snapshot_path=OFFICIAL_PATH, snapshot_bytes=official_bytes, locator="/facts/pack_description_en", role="independent_field", notes="This official context supports the normalized canonical set label; it is not asserted as a verbatim official pack title."),
        evidence_row(target_type="set", target_id=SET_ID, field_path="source_type", value="Nintendo Switch", source_id=OFFICIAL_SOURCE, lineage=OFFICIAL_LINEAGE, tier="official_general", snapshot_path=OFFICIAL_PATH, snapshot_bytes=official_bytes, locator="/facts/platform_context", role="independent_field", notes="Apply contract maps this platform context to source_type=platform; it does not claim a present storefront offer."),
    ))
    evidence.sort(key=lambda row: (row["target_type"], row["target_id"], row["field_path"], row["source_id"]))
    return {"items": list(item_rows.values()), "sets": list(set_rows.values()), "sources": list(sources.values())}, evidence


def apply_targets(root: Path, targets: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
    items = {row["item_id"]: dict(row) for row in targets["items"]}
    for item_id, _vendor_id, name, category in ITEMS:
        row = items[item_id]
        row.update({
            "canonical_name_en": name, "canonical_name_zh_tw": f"待確認（{name}）", "item_category": category,
            "source_type": "platform", "source_id": OFFICIAL_SOURCE, "source_ids": [OFFICIAL_SOURCE, SECONDARY_SOURCE],
            "availability_status": "unknown", "availability_event_ids": [AVAILABILITY_ID], "free_or_premium": "unknown",
            "permanent_account_item": "unknown", "set_ids": [SET_ID], "visual_reference_ids": ["visual_" + item_id.removeprefix("item_")],
            "verification_status": "verified", "evidence_tier": "official_with_secondary", "model_feature_status": "excluded_pending_verification",
            "last_verified_at": AS_OF,
            "notes": "Official evidence supports the descriptive pack component; the independent vendor snapshot supplies the exact English title and category. No formal Traditional Chinese name, image asset, price, current storefront availability, return policy, or irreversible permanent-account property is asserted.",
        })
    sets = {row["set_id"]: dict(row) for row in targets["sets"]}
    sets[SET_ID].pop("notes", None)
    sets[SET_ID].update({
        "canonical_name_en": "Nintendo Switch Starter Pack", "canonical_name_zh_tw": "待確認（Nintendo Switch Starter Pack）",
        "required_item_ids": [entry[0] for entry in ITEMS], "optional_item_ids": [], "source_ids": [OFFICIAL_SOURCE, SECONDARY_SOURCE],
        "last_verified_at": AS_OF, "verification_status": "verified",
    })
    sources = {row["source_id"]: dict(row) for row in targets["sources"]}
    sources[OFFICIAL_SOURCE] = {
        "source_id": OFFICIAL_SOURCE, "source_name": "thatgamecompany Help Center FAQ 823 — Nintendo Switch Starter Pack",
        "source_type": "official_support", "url": "https://thatgamecompany.helpshift.com/hc/en/17-sky-children-of-the-light/faq/823/",
        "retrieved_at": AS_OF, "evidence_level": "official_explicit", "source_lineage_id": OFFICIAL_LINEAGE,
        "notes": "Fact-limited, locally pinned structured transcription: Starter Pack context, four descriptive components, and Nintendo Switch platform context only. It does not claim an exact official pack title, exact official item titles, storefront availability, price, image, or Traditional Chinese names.",
    }
    sources[SECONDARY_SOURCE]["source_lineage_id"] = SECONDARY_LINEAGE
    ordered_sources = [sources[row["source_id"]] for row in targets["sources"]]
    if OFFICIAL_SOURCE not in {row["source_id"] for row in targets["sources"]}:
        ordered_sources.append(sources[OFFICIAL_SOURCE])
    return {
        "items": [items[row["item_id"]] for row in targets["items"]],
        "sets": [sets[row["set_id"]] for row in targets["sets"]],
        "sources": ordered_sources,
    }


def generated_support_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    availability = [{"availability_id": AVAILABILITY_ID, "item_id": None, "availability_status": "unknown", "start_date": None, "end_date": None, "event_id": None, "source_ids": [OFFICIAL_SOURCE, SECONDARY_SOURCE], "last_verified_at": AS_OF, "verification_status": "needs_review"}]
    visual = [{"visual_reference_id": "visual_" + item_id.removeprefix("item_"), "item_id": item_id, "reference_mode": "source_description", "asset_sha256": None, "description": f"Official FAQ 823 describes a {OFFICIAL_DESCRIPTIONS[item_id]} in the Nintendo Switch Starter Pack; it does not provide this canonical exact title, and no image asset or visual match is stored or asserted.", "source_ids": [OFFICIAL_SOURCE], "verification_status": "needs_review"} for item_id, _vendor_id, _name, _category in ITEMS]
    return availability, visual


def verify(root: Path, *, require_applied: bool = True) -> list[str]:
    targets, evidence = build(root)
    expected = apply_targets(root, targets)
    problems: list[str] = []
    if require_applied:
        for relative, rows in (("knowledge/items/items.jsonl", expected["items"]), ("knowledge/sets/item-sets.jsonl", expected["sets"]), ("knowledge/sources/sources.jsonl", expected["sources"])):
            if read_jsonl(root / relative) != rows:
                problems.append(f"committed target differs from replayable apply contract: {relative}")
        availability, visual = generated_support_rows()
        existing_availability = {row["availability_id"]: row for row in read_jsonl(root / "knowledge/acquisition/availability-events.jsonl")}
        existing_visual = {row["visual_reference_id"]: row for row in read_jsonl(root / "knowledge/visual-references/manifest.jsonl")}
        if existing_availability.get(AVAILABILITY_ID) != availability[0]: problems.append("availability row differs from replayable apply contract")
        for row in visual:
            if existing_visual.get(row["visual_reference_id"]) != row: problems.append(f"visual reference differs from replayable apply contract: {row['visual_reference_id']}")
        evidence_path = root / "data/review/nintendo-starter-pack-canonical-evidence.jsonl"
        if not evidence_path.is_file() or read_jsonl(evidence_path) != evidence: problems.append("canonical field evidence differs from replayable source claims")
        item_ids = {row["item_id"] for row in expected["items"]}
        if any(SET_ID not in row["set_ids"] for row in expected["items"] if row["item_id"] in {entry[0] for entry in ITEMS}): problems.append("item-to-set FK mismatch")
        if set(next(row for row in expected["sets"] if row["set_id"] == SET_ID)["required_item_ids"]) != {entry[0] for entry in ITEMS}: problems.append("set required members mismatch")
        if any(row["item_id"] not in item_ids for row in visual): problems.append("visual FK mismatch")
    return problems


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply or verify the offline Nintendo Starter Pack evidence cohort.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--apply", action="store_true", help="Write the exact, replayable bounded cohort updates.")
    args = parser.parse_args(); root = args.root.resolve()
    if args.apply:
        targets, evidence = build(root, allow_registry_bootstrap=True); applied = apply_targets(root, targets); availability, visual = generated_support_rows()
        write_jsonl(root / "knowledge/items/items.jsonl", applied["items"]); write_jsonl(root / "knowledge/sets/item-sets.jsonl", applied["sets"]); write_jsonl(root / "knowledge/sources/sources.jsonl", applied["sources"])
        available = {row["availability_id"]: row for row in read_jsonl(root / "knowledge/acquisition/availability-events.jsonl")}; available[AVAILABILITY_ID] = availability[0]
        write_jsonl(root / "knowledge/acquisition/availability-events.jsonl", sorted(available.values(), key=lambda row: row["availability_id"]))
        visuals = {row["visual_reference_id"]: row for row in read_jsonl(root / "knowledge/visual-references/manifest.jsonl")}; visuals.update({row["visual_reference_id"]: row for row in visual})
        write_jsonl(root / "knowledge/visual-references/manifest.jsonl", sorted(visuals.values(), key=lambda row: row["visual_reference_id"]))
        write_jsonl(root / "data/review/nintendo-starter-pack-canonical-evidence.jsonl", evidence)
    problems = verify(root)
    print(json.dumps({"applied": args.apply, "valid": not problems, "problems": problems, "model_feature_status": "excluded_pending_verification"}, ensure_ascii=False, sort_keys=True))
    raise SystemExit(0 if not problems else 1)


if __name__ == "__main__":
    main()
