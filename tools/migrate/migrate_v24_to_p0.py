#!/usr/bin/env python3
"""Offline, repeatable migration from the v2.4 snapshot into P0 data layers.

This program deliberately reads the legacy project as an input only.  It never
imports providers, does not use the network, and removes source-group identity
and post locators before writing P0 records.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "3.0-p0"


URGENT_LISTING_MARKERS = ("急售", "急出")
NEGATED_URGENT_RE = re.compile(r"(?:不|非|不是|並非|并非)\s*急(?:售|出)")
EXPLICIT_SALE_EXCHANGE_RE = re.compile(r"(?:售|出)\s*(?:／|/)\s*(?:換|换)|(?:換|换)\s*(?:／|/)\s*(?:售|出)")
PRICE_TERM_RE = re.compile(r"\d+(?:\.\d+)?\s*萬|\d{3,}\s*(?:元|台幣|NTD)?")


def has_explicit_urgent_claim(listing_text: str) -> bool:
    """Return true only for an affirmative urgent-sale claim.

    A literal substring test would incorrectly recode statements such as
    ``不急售``.  Remove the small, explicit negation vocabulary before testing
    the two supported affirmative markers; broader sentiment inference remains
    out of scope.
    """
    affirmative_text = NEGATED_URGENT_RE.sub("", str(listing_text))
    return any(marker in affirmative_text for marker in URGENT_LISTING_MARKERS)


def normalize_urgent_listing_price_type(price_type: str, listing_text: str) -> str:
    """Apply only the urgent-text correction without recoding other legacy types."""
    if str(price_type).strip().casefold() in {
        "asking", "normal_listing", "reduced", "instant", "instant_price", "quick_sale", "buyout"
    } and has_explicit_urgent_claim(listing_text):
        return "urgent_sale"
    return price_type


def normalize_market_price_type(legacy_price_type: str, listing_text: str) -> str:
    """Separate explicit urgent listings from ordinary asking prices.

    A listed amount is still an asking price, but an explicit ``急售`` or
    ``急出`` claim changes its market line to ``urgent_sale``.  This applies
    consistently to the source listing, normalized listing, and its derived
    history.  It is a deterministic text fact, not an inferred discount or
    transaction outcome.  Sold claims retain their distinct semantics.
    """
    mapped = {
        "asking": "asking", "normal_listing": "normal_listing",
        "urgent_sale": "urgent_sale", "reduced": "reduced", "instant": "instant",
        "instant_price": "instant", "quick_sale": "urgent_sale",
        "buyout": "normal_listing", "sold_explicit": "sold_claim",
        "sold_last_ask": "sold_claim", "sold_claim": "sold_claim",
    }.get(str(legacy_price_type).strip().casefold(), "unknown")
    return normalize_urgent_listing_price_type(mapped, listing_text)


def normalize_history_price_type(legacy_price_type: str, listing_text: str) -> str:
    """Backward-compatible name for history callers of market normalization."""
    return normalize_market_price_type(legacy_price_type, listing_text)


def normalize_price_variants(price_variants: Any, listing_text: str) -> list[Any]:
    """Keep nested price observations consistent with their parent listing."""
    if not isinstance(price_variants, list):
        return []
    normalized: list[Any] = []
    for variant in price_variants:
        if not isinstance(variant, dict):
            normalized.append(variant)
            continue
        result = dict(variant)
        result["kind"] = normalize_urgent_listing_price_type(str(result.get("kind", "unknown")), listing_text)
        normalized.append(result)
    return normalized


def apply_explicit_trade_semantics(record: dict[str, Any]) -> None:
    """Fail closed when a listing expressly mixes cash sale and exchange.

    A ``售／換`` offer is not evidence that the displayed amount is a pure
    seller-to-buyer single-account listing.  Keep the source amount and text
    intact, but ensure downstream eligibility gates see a mixed transaction.
    """
    if not EXPLICIT_SALE_EXCHANGE_RE.search(str(record.get("listing_text", ""))):
        return
    record["offer_kind"] = "mixed"
    record["entity_kind"] = "unknown"
    record["core_candidate"] = False
    reason = "explicit_cash_and_exchange_offer_requires_review"
    existing = record.get("exclusion_reason")
    if not isinstance(existing, str) or not existing.strip():
        record["exclusion_reason"] = reason
    elif reason not in existing:
        record["exclusion_reason"] = f"{existing}; {reason}"


def has_explicit_multi_price_terms(listing_text: str) -> bool:
    """Recognize explicit contractual price alternatives without choosing one."""
    text = str(listing_text)
    return (
        "含勳章" in text
        and "不含勳章" in text
        and "分期" in text
        and len(PRICE_TERM_RE.findall(text)) >= 3
    )


def price_semantic_review(listing_text: str, price_type: str) -> dict[str, Any] | None:
    """Gate mixed price semantics without selecting or modifying an amount.

    The marker ``含仲`` means the public amount includes brokerage.  It remains
    an urgent observation when the text explicitly says so, but may not enter
    a model training line until its brokerage treatment is reviewed offline.
    """
    text = str(listing_text)
    brokerage_included = "含仲" in text
    multi_price = has_explicit_multi_price_terms(text)
    if not brokerage_included and not multi_price:
        return None
    result: dict[str, Any] = {
        "urgency": "urgent_sale" if price_type == "urgent_sale" else "unknown",
        "evidence_state": "text_claim",
        "review_status": "needs_review",
        "reason_codes": [],
    }
    if brokerage_included:
        result["brokerage_included"] = True
        result["reason_codes"].append("brokerage_included_price")
    if multi_price:
        result["multi_price"] = True
        result["reason_codes"].extend([
            "multiple_price_terms", "badge_inclusion_price_variants", "installment_price_variants",
        ])
    return result
FORBIDDEN_KEYS = {
    "source_group_id", "source_group_name", "source_post_key", "post_url",
    "profile_url", "author", "author_name", "uid", "group_id", "locator",
}
SEASON_RE = re.compile(
    r"感恩|追光|歸屬|归属|音韻|音韵|魔法|聖島|圣岛|預言|预言|夢想|梦想|重組|重组|"
    r"小王子|風行|风行|深淵|深渊|表演|破曉|破晓|歐若拉|欧若拉|極光|极光|追憶|追忆|"
    r"緬懷|缅怀|夜行|拾光|九色鹿|築巢|筑巢|巢穴|二重奏|姆明|彩染|遷徙|迁徙|"
    r"青鳥|青鸟|雙星|双星|織光|织光|狂歡|狂欢|梵高|梵谷|梵谷季|歸巢|归巢|"
    r"集結|集结|破碎|凜冬|凛冬"
)

# These short forms are also ordinary Chinese words.  They can represent a
# canonical season only when the surrounding listing actually presents them as
# a season claim.  In particular, a bare ``破碎`` in an item/service sentence
# must not become account ownership merely because the alias exists.
CONTEXT_GATED_SEASON_TERMS = frozenset({"集結", "集结", "破碎"})


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def pseudo(prefix: str, legacy_value: str) -> str:
    digest = hashlib.sha256(legacy_value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def safe_date(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value).isoformat()
    except ValueError:
        return None


def clean(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in FORBIDDEN_KEYS}


def sanitize_market_text(value: Any, source_names: set[str]) -> str:
    text = str(value or "")
    for name in sorted(source_names, key=len, reverse=True):
        # Group names such as 「光遇交易」 are four CJK codepoints; a length
        # threshold would silently leak them.  Keep only the bare game title
        # untouched because it is normal listing content rather than identity.
        if name and name.casefold() not in {"光遇", "sky光遇", "sky光·遇"}:
            text = text.replace(name, "[來源名稱已移除]")
    return text


def legacy_root(default_v3: Path) -> Path:
    return default_v3.parent / "sky-valuation"


def catalog_aliases(v3_root: Path) -> dict[str, str]:
    """Read only canonical knowledge files when they are already available."""
    index: dict[str, str] = {}
    candidates = [
        v3_root / "knowledge" / "aliases" / "item-aliases.jsonl",
        v3_root / "knowledge" / "seasons" / "seasons.jsonl",
    ]
    for path in candidates:
        if not path.exists():
            continue
        for row in read_jsonl(path):
            if row.get("target_type") not in (None, "season"):
                continue
            season_id = row.get("season_id") or row.get("canonical_id") or row.get("target_id")
            if not isinstance(season_id, str):
                continue
            values = row.get("aliases", [])
            if isinstance(row.get("alias"), str):
                values = list(values) + [row["alias"]]
            if isinstance(row.get("alias_text"), str):
                values = list(values) + [row["alias_text"]]
            for value in values:
                if isinstance(value, str):
                    index[value.casefold()] = season_id
            for name_key in ("canonical_name_zh_tw", "canonical_name_en"):
                value = row.get(name_key)
                if isinstance(value, str):
                    index[value.casefold()] = season_id
    return index


def item_aliases(v3_root: Path) -> dict[str, str]:
    """Load the canonical item alias index when the knowledge layer is present."""
    index: dict[str, str] = {}
    path = v3_root / "knowledge" / "aliases" / "item-aliases.jsonl"
    if not path.exists():
        return index
    for row in read_jsonl(path):
        if row.get("target_type") not in (None, "item"):
            continue
        item_id = row.get("item_id") or row.get("canonical_id") or row.get("target_id")
        alias = row.get("alias") or row.get("alias_text")
        if isinstance(item_id, str) and isinstance(alias, str):
            index[alias.casefold()] = item_id
    return index


def collection_aliases(v3_root: Path) -> dict[str, tuple[str, str]]:
    """Return exact aliases that resolve to one *existing* catalog target.

    This deliberately is not a fuzzy matcher.  A spelling is usable only when
    it appears verbatim in the canonical item/set data or in the canonical
    alias file, and its target exists in the corresponding canonical file.
    Ambiguous spellings are omitted here and must remain in review.
    """
    candidates: dict[str, set[tuple[str, str]]] = {}
    item_path = v3_root / "knowledge" / "items" / "items.jsonl"
    set_path = v3_root / "knowledge" / "sets" / "item-sets.jsonl"
    item_rows = read_jsonl(item_path) if item_path.exists() else []
    item_ids = {row.get("item_id") for row in item_rows}
    set_ids = {row.get("set_id") for row in read_jsonl(set_path)} if set_path.exists() else set()

    def add(alias: Any, target_type: str, target_id: Any) -> None:
        if not isinstance(alias, str) or len(alias.strip()) < 2:
            return
        if target_type == "item" and target_id not in item_ids:
            return
        if target_type == "set" and target_id not in set_ids:
            return
        candidates.setdefault(alias.casefold(), set()).add((target_type, str(target_id)))

    def safe_alias(value: Any, *, alias_verified: bool = False) -> bool:
        normalized = "".join(char for char in str(value) if char.isalnum())
        # Item identity verification does not automatically verify every
        # nickname attached to that item.  Short player aliases remain
        # context-dependent unless the alias record itself was reviewed.
        return alias_verified or len(normalized) >= 3

    # Canonical titles remain searchable. Short aliases on unverified items
    # (for example 鹿角 or 紅斗) require context and cannot prove ownership.
    for row in item_rows:
        for value in (row.get("canonical_name_zh_tw"), row.get("canonical_name_en")):
            add(value, "item", row.get("item_id"))
        for value in row.get("aliases", []):
            if safe_alias(value):
                add(value, "item", row.get("item_id"))
    for row in read_jsonl(set_path) if set_path.exists() else []:
        for value in (row.get("canonical_name_zh_tw"), row.get("canonical_name_en")):
            add(value, "set", row.get("set_id"))
    path = v3_root / "knowledge" / "aliases" / "item-aliases.jsonl"
    if not path.exists():
        return {alias: next(iter(targets)) for alias, targets in candidates.items() if len(targets) == 1}
    for row in read_jsonl(path):
        target_type, target_id = row.get("target_type"), row.get("target_id")
        if target_type in {"item", "set"}:
            value = row.get("alias_text") or row.get("normalized_alias")
            if target_type != "item" or safe_alias(
                value, alias_verified=row.get("verification_status") == "verified"
            ):
                add(value, target_type, target_id)
    return {alias: next(iter(targets)) for alias, targets in candidates.items() if len(targets) == 1}


def mentioned_without_negation(text: str, alias: str) -> bool:
    for match in re.finditer(re.escape(alias), text, flags=re.I):
        context = text[max(0, match.start() - 5): min(len(text), match.end() + 5)]
        if not re.search(r"(?:缺|無|无|沒有|没有|不含|未有|未擁有|未拥有).{0,4}" + re.escape(alias), context, flags=re.I):
            return True
    return False


def longest_non_overlapping_aliases(text: str, aliases: dict[str, Any]) -> set[str]:
    """Select longest alias occurrences globally so nested names count once."""
    occurrences: list[tuple[int, int, str]] = []
    for alias in aliases:
        occurrences.extend((match.start(), match.end(), alias) for match in re.finditer(re.escape(alias), text, flags=re.I))
    selected: list[tuple[int, int, str]] = []
    for start, end, alias in sorted(occurrences, key=lambda row: (-(row[1] - row[0]), row[0], row[2])):
        if any(start < chosen_end and chosen_start < end for chosen_start, chosen_end, _ in selected):
            continue
        selected.append((start, end, alias))
    return {alias for _, _, alias in selected}


def collection_claims(text: str, aliases: dict[str, tuple[str, str]], evidence_source: str) -> tuple[set[str], dict[str, dict[str, Any]]]:
    """Extract only positive exact collection claims from one source field.

    There is no safe collection-wide negative statement in this source format:
    ``沒有 X`` must not be converted into an absent item vector unless X is a
    uniquely resolved canonical alias.  Positive set mentions retain a
    non-completion claim rather than inventing member ownership.
    """
    owned: set[str] = set()
    set_claims: dict[str, dict[str, Any]] = {}
    for alias in longest_non_overlapping_aliases(text, aliases):
        target_type, target_id = aliases[alias]
        if not mentioned_without_negation(text, alias):
            continue
        if target_type == "item":
            owned.add(target_id)
        else:
            set_claims[target_id] = {
                "set_id": target_id, "status": "mentioned_unverified",
                "completion_ratio": None, "is_complete": None,
                "owned_item_ids": [], "missing_item_ids": [],
                "evidence_state": "text_claim", "review_status": "needs_review",
                "evidence_sources": [evidence_source],
            }
    return owned, set_claims


def merge_collection_claims(
    listing: tuple[set[str], dict[str, dict[str, Any]]],
    summary: tuple[set[str], dict[str, dict[str, Any]]],
) -> tuple[set[str], list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Union positive claims and preserve field-level provenance.

    A normalized feature summary is not an independent market source, but it
    is a separate extraction input.  Union is safe for positive mentions;
    completion and missing-member claims remain unknown.
    """
    listing_items, listing_sets = listing
    summary_items, summary_sets = summary
    owned = listing_items | summary_items
    sources = ([] if not listing_items else ["listing_text"]) + ([] if not summary_items else ["normalized_feature_summary"])
    set_rows: list[dict[str, Any]] = []
    for set_id in sorted(set(listing_sets) | set(summary_sets)):
        row = dict(listing_sets.get(set_id) or summary_sets[set_id])
        row["evidence_sources"] = sorted(set((listing_sets.get(set_id) or {}).get("evidence_sources", []) + (summary_sets.get(set_id) or {}).get("evidence_sources", [])))
        set_rows.append(row)
    evidence = {
        "collection.owned_item_ids": {"sources": sources, "evidence_state": "text_claim" if sources else "unknown"},
        "collection.item_set_profiles": {
            "sources": sorted({source for row in set_rows for source in row.get("evidence_sources", [])}),
            "evidence_state": "text_claim" if set_rows else "unknown",
        },
    }
    return owned, set_rows, evidence


def canonical_collection_metadata(
    items: Iterable[dict[str, Any]], sets: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Build deterministic, canonical-only collection derivation indexes.

    Listing text can establish only positive ownership.  The category fields
    below are therefore *intersections* of that ownership with the canonical
    catalog; they never turn a category word into an owned item.  Event-limited
    is intentionally narrower than general temporary availability: it requires
    an event source plus a restricted availability state.
    """
    item_rows = [row for row in items if isinstance(row.get("item_id"), str)]
    bundle_set_ids = {
        row.get("set_id") for row in sets
        if row.get("set_type") == "bundle" and isinstance(row.get("set_id"), str)
    }
    ultimate_by_season: dict[str, set[str]] = {}
    for row in item_rows:
        if row.get("ultimate_reward") is True and isinstance(row.get("season_id"), str):
            ultimate_by_season.setdefault(row["season_id"], set()).add(row["item_id"])
    return {
        "ultimate_item_ids": {row["item_id"] for row in item_rows if row.get("ultimate_reward") is True},
        "ultimate_by_season": ultimate_by_season,
        "collaboration_item_ids": {row["item_id"] for row in item_rows if row.get("collaboration") is True},
        "bundle_item_ids": {
            row["item_id"] for row in item_rows
            if bundle_set_ids.intersection(set(row.get("set_ids") or []))
        },
        "event_limited_item_ids": {
            row["item_id"] for row in item_rows
            if row.get("source_type") == "event"
            and row.get("availability_status") in {"limited_time", "temporarily_unavailable", "officially_discontinued"}
        },
    }


def enrich_collection_from_canonical(
    owned_item_ids: set[str],
    graduation_season_ids: Iterable[str],
    metadata: dict[str, Any],
    owned_evidence: dict[str, Any],
) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]]]:
    """Derive collection subsets while preserving positive-claim provenance.

    A contradictory/unknown ownership field cannot safely support a derived
    subset.  Canonical metadata itself is the only classifier and has no
    fallback from names, aliases, or availability guesses.
    """
    if owned_evidence.get("evidence_state") != "text_claim":
        empty = {key: [] for key in (
            "graduation_rewards", "collaboration_items", "bundle_item_ids", "event_limited_item_ids",
        )}
        return empty, {
            f"collection.{key}": {"sources": [], "evidence_state": owned_evidence.get("evidence_state", "unknown")}
            for key in empty
        }
    ultimate_items = set(metadata.get("ultimate_item_ids", set()))
    # An explicit "season graduation" claim supports that season's ultimate
    # reward only; it must not spill into ordinary seasonal items.
    for season_id in graduation_season_ids:
        ultimate_items.update(metadata.get("ultimate_by_season", {}).get(season_id, set()))
    values = {
        "graduation_rewards": sorted(owned_item_ids & ultimate_items),
        "collaboration_items": sorted(owned_item_ids & set(metadata.get("collaboration_item_ids", set()))),
        "bundle_item_ids": sorted(owned_item_ids & set(metadata.get("bundle_item_ids", set()))),
        "event_limited_item_ids": sorted(owned_item_ids & set(metadata.get("event_limited_item_ids", set()))),
    }
    evidence = {
        f"collection.{key}": {
            "sources": list(owned_evidence.get("sources", [])),
            "evidence_state": "text_claim",
        }
        for key in values
    }
    return values, evidence


def season_term_has_context(text: str, match: re.Match[str]) -> bool:
    """Return whether a short ambiguous alias is used as a season claim.

    The catalog deliberately keeps the aliases for review and lookup, while
    migration needs a stricter rule: only season-list, completion/pass, or
    explicit season-range contexts may establish account ownership.  A
    neighbouring season name without a delimiter (for example
    ``表演破碎畢業``) is also rejected because it can be a compressed heading
    rather than a separable claim for this account.
    """
    term = match.group(0)
    if term not in CONTEXT_GATED_SEASON_TERMS:
        return True
    before = text[max(0, match.start() - 24):match.start()]
    after = text[match.end():min(len(text), match.end() + 16)]
    context = before + term + after
    if re.search(r"(?:不含|不包|無|无|缺)\s*$", before):
        return False
    # A directly adjacent known season name has no list/range delimiter.
    if any(previous.end() == len(before) for previous in SEASON_RE.finditer(before)):
        return False
    if after.startswith("季"):
        return True
    if re.search(r"(?:季節|季节|畢業季節|毕业季节)\s*[:：\-—]?\s*(?:[^\n]{0,20})$", before):
        return True
    if re.search(r"(?:畢業|毕业|季卡|有卡|無卡|无卡|半畢|半毕)", context):
        return True
    # A delimited season range is an explicit seasonal context even when the
    # term itself omits the trailing ``季``.
    if re.search(r"(?:～|~|至|到|—|-)\s*$", before) or re.match(r"^\s*(?:～|~|至|到|—|-)", after):
        return True
    return False


def season_terms(text: str) -> list[str]:
    return list(dict.fromkeys(
        match.group(0) for match in SEASON_RE.finditer(text)
        if season_term_has_context(text, match)
    ))


def season_profile(
    text: str,
    aliases: dict[str, str],
    order: dict[str, int],
    evidence_source: str = "listing_text",
) -> tuple[list[dict[str, Any]], list[str]]:
    """Extract season claims from one evidence field only.

    ``feature_summary`` is an editorial normalization of listing text, not an
    independent source of truth.  It is deliberately parsed separately and
    combined by :func:`merge_season_profiles` so disagreement remains visible
    as a conflict instead of silently overriding the listing wording.
    """
    matches = [match for match in SEASON_RE.finditer(text) if season_term_has_context(text, match)]
    profiles_by_id: dict[str, dict[str, Any]] = {}
    unresolved: list[str] = []
    terms_by_id: dict[str, str] = {}
    positions: list[tuple[re.Match[str], str]] = []
    for match in matches:
        term = match.group(0)
        # 「凜冬」 is an ambiguous player term.  It must enter the review queue,
        # even if a future catalog happens to contain the spelling as an alias.
        season_id = None if term in {"凜冬", "凛冬"} else aliases.get(term.casefold())
        if not season_id:
            unresolved.append(term)
            continue
        if season_id not in terms_by_id:
            terms_by_id[season_id] = term
        positions.append((match, season_id))

    def make_profile(season_id: str, status: str, evidence_state: str = "text_claim") -> dict[str, Any]:
        return {
            "season_id": season_id, "status": status, "completion_ratio": None,
            "pass_owned": "unknown", "ultimate_reward_owned": "unknown",
            "owned_item_ids": [], "missing_item_ids": [], "evidence_state": evidence_state,
            "evidence_sources": [f"status:{evidence_source}"] if evidence_state != "unknown" else [],
            "capture_date": None, "review_status": "needs_review",
        }

    for season_id, term in terms_by_id.items():
        escaped = re.escape(term)
        # Completion is scoped to the same punctuation-delimited clause as the
        # season term. This prevents a preceding clause such as ``狂歡畢業，``
        # from completing the next claim ``梵谷有卡未畢``. Direct negations
        # (未畢業／尚未畢業／沒有畢業) always suppress the completion mention.
        negative_pattern = (
            rf"{escaped}[^，,。；;！!？?、\n]{{0,10}}(?:未|尚未|沒有|没有|無法|无法|無|无)(?:畢|毕)(?:業|业)?"
            rf"|(?:未|尚未|沒有|没有|無法|无法|無|无)(?:畢|毕)(?:業|业)?[^，,。；;！!？?、\n]{{0,10}}{escaped}"
            rf"|差[^，,。；;！!？?、\n]{{0,6}}{escaped}[^，,。；;！!？?、\n]{{0,10}}(?:畢|毕)(?:業|业)?"
        )
        negative_completion = bool(re.search(negative_pattern, text, re.I))
        positive_completion = False
        for term_match in re.finditer(escaped, text, re.I):
            left = max((text.rfind(mark, 0, term_match.start()) for mark in "，,。；;！!？?、\n"), default=-1) + 1
            right_candidates = [text.find(mark, term_match.end()) for mark in "，,。；;！!？?、\n"]
            right_candidates = [position for position in right_candidates if position >= 0]
            right = min(right_candidates, default=len(text))
            clause = text[left:right]
            clause_is_negative = bool(re.search(negative_pattern, clause, re.I))
            if not clause_is_negative:
                for mention in re.finditer(r"畢業|毕业", clause):
                    prefix = clause[max(0, mention.start() - 6):mention.start()]
                    if not re.search(r"(?:未|尚未|沒有|没有|無法|无法|無|无|不算)\s*$", prefix):
                        positive_completion = True
                        break
            # Explicit headings such as ``畢業季節：...`` and ``畢業季含...``
            # apply to their following list until a strong clause boundary.
            strong_left = max((text.rfind(mark, 0, term_match.start()) for mark in "。；;！!？?\n"), default=-1) + 1
            heading_prefix = text[strong_left:term_match.start()]
            if not clause_is_negative and re.search(r"(?:畢業季節|毕业季节|畢業季|毕业季)\s*(?:[:：]|含)?[^。；;！!？?\n]*$", heading_prefix):
                positive_completion = True
        explicit_completion_conflict = negative_completion and positive_completion
        complete = positive_completion and not negative_completion
        partial = re.search(rf"{escaped}.{{0,8}}(?:半畢|半毕|[1-9]\s*/\s*[2-9]|進度|进度)|(?:半畢|半毕|[1-9]\s*/\s*[2-9]).{{0,8}}{escaped}", text)
        missing = re.search(rf"(?:缺|缺少|斷|断)\s*{escaped}|{escaped}\s*(?:缺|缺少|斷季|断季)", text)
        status = (
            "confirmed_missing" if missing else
            "unknown" if explicit_completion_conflict else
            "owned_not_complete" if negative_completion else
            "complete" if complete else
            "partial" if partial else
            "owned_not_complete"
        )
        profile = make_profile(season_id, status, "conflict" if explicit_completion_conflict else "text_claim")
        if negative_completion:
            profile["evidence_sources"].append(f"status_completion_negative:{evidence_source}")
        if positive_completion:
            profile["evidence_sources"].append(f"status_completion_positive:{evidence_source}")
        if re.search(rf"{escaped}.{{0,5}}(?:季卡|有卡|卡有)|(?:季卡|有卡).{{0,5}}{escaped}", text):
            profile["pass_owned"] = "yes"
            profile["evidence_sources"].append(f"pass_owned:{evidence_source}")
        elif re.search(rf"{escaped}.{{0,5}}(?:無卡|无卡)|(?:無卡|无卡).{{0,5}}{escaped}", text):
            profile["pass_owned"] = "no"
            profile["evidence_sources"].append(f"pass_owned:{evidence_source}")
        profiles_by_id[season_id] = profile

    by_order = {value: key for key, value in order.items()}
    for (left_match, left_id), (right_match, right_id) in zip(positions, positions[1:]):
        connector = text[left_match.end():right_match.start()]
        if not re.fullmatch(r"\s*(?:～|~|至|到|—|-)\s*", connector):
            continue
        if left_id not in order or right_id not in order:
            continue
        start, end = sorted((order[left_id], order[right_id]))
        snippet = text[left_match.start(): min(len(text), right_match.end() + 12)]
        if re.search(r"(?:全畢|全毕|皆畢|皆毕)", snippet):
            inferred_status, evidence = "complete", "text_claim"
        elif re.search(r"(?:無斷|无断|不斷|不断)", snippet):
            inferred_status, evidence = "owned_not_complete", "text_claim"
        else:
            inferred_status, evidence = "unknown", "unknown"
        for position in range(start, end + 1):
            season_id = by_order.get(position)
            if season_id and season_id not in profiles_by_id:
                profiles_by_id[season_id] = make_profile(season_id, inferred_status, evidence)
        if inferred_status in {"complete", "owned_not_complete"}:
            for endpoint in (left_id, right_id):
                if endpoint in profiles_by_id and profiles_by_id[endpoint]["status"] == "owned_not_complete":
                    profiles_by_id[endpoint]["status"] = inferred_status

    profiles = sorted(profiles_by_id.values(), key=lambda row: order.get(row["season_id"], 10_000))
    return profiles, list(dict.fromkeys(unresolved))


def _merge_status(values: list[str]) -> tuple[str, bool]:
    """Merge only compatible season claims; conflicts fail closed to unknown."""
    known = [value for value in values if value != "unknown"]
    if not known:
        return "unknown", False
    distinct = set(known)
    # A bare season mention means ownership but says nothing about completion.
    # It is compatible with a more specific complete or partial claim.
    specific = distinct - {"owned_not_complete"}
    if len(specific) > 1:
        return "unknown", True
    if specific:
        return next(iter(specific)), False
    return "owned_not_complete", False


def _merge_enum(values: list[str]) -> tuple[str, bool]:
    known = [value for value in values if value != "unknown"]
    if not known:
        return "unknown", False
    return (known[0], False) if len(set(known)) == 1 else ("unknown", True)


def merge_season_profiles(
    profiles_by_source: dict[str, list[dict[str, Any]]], order: dict[str, int]
) -> list[dict[str, Any]]:
    """Merge field claims without treating missing data as agreement.

    The schema has one evidence-state per season profile, so field-level source
    provenance is retained in ``evidence_sources`` using stable
    ``field:source`` tokens.  A conflict in either structured field marks the
    profile conflict/needs-review and clears only that field to ``unknown``.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for rows in profiles_by_source.values():
        for row in rows:
            grouped.setdefault(row["season_id"], []).append(row)
    merged: list[dict[str, Any]] = []
    for season_id, rows in grouped.items():
        status, status_conflict = _merge_status([str(row.get("status", "unknown")) for row in rows])
        explicit_negative = any(
            source.startswith("status_completion_negative:")
            for row in rows for source in row.get("evidence_sources", [])
        )
        explicit_positive = any(
            source.startswith("status_completion_positive:")
            for row in rows for source in row.get("evidence_sources", [])
        )
        if explicit_negative:
            if explicit_positive or any(row.get("status") == "confirmed_missing" for row in rows):
                status, status_conflict = "unknown", True
            else:
                status, status_conflict = "owned_not_complete", False
        pass_owned, pass_conflict = _merge_enum([str(row.get("pass_owned", "unknown")) for row in rows])
        ultimate, ultimate_conflict = _merge_enum([str(row.get("ultimate_reward_owned", "unknown")) for row in rows])
        sources = sorted({source for row in rows for source in row.get("evidence_sources", []) if isinstance(source, str)})
        conflict = status_conflict or pass_conflict or ultimate_conflict
        merged.append({
            "season_id": season_id,
            "status": status,
            "completion_ratio": None,
            "pass_owned": pass_owned,
            "ultimate_reward_owned": ultimate,
            "owned_item_ids": [],
            "missing_item_ids": [],
            "evidence_state": "conflict" if conflict else "text_claim" if sources else "unknown",
            "evidence_sources": sources,
            "capture_date": None,
            "review_status": "needs_review",
        })
    return sorted(merged, key=lambda row: order.get(row["season_id"], 10_000))


def season_summary(profiles: list[dict[str, Any]], order: dict[str, int]) -> dict[str, Any]:
    owned_statuses = {"complete", "partial", "owned_not_complete"}
    owned = [row for row in profiles if row["status"] in owned_statuses]
    complete = [row for row in profiles if row["status"] == "complete"]

    def segments(statuses: set[str]) -> list[dict[str, Any]]:
        positions = sorted((order[row["season_id"]], row["season_id"]) for row in profiles if row["status"] in statuses and row["season_id"] in order)
        groups: list[list[tuple[int, str]]] = []
        for value in positions:
            if not groups or value[0] != groups[-1][-1][0] + 1:
                groups.append([value])
            else:
                groups[-1].append(value)
        return [{"start_season_id": group[0][1], "end_season_id": group[-1][1], "season_ids": [value[1] for value in group]} for group in groups]

    return {
        "earliest_season_id": min(owned, key=lambda row: order.get(row["season_id"], 10_000))["season_id"] if owned else None,
        "earliest_complete_season_id": min(complete, key=lambda row: order.get(row["season_id"], 10_000))["season_id"] if complete else None,
        "complete_count": len(complete), "partial_count": sum(row["status"] == "partial" for row in profiles),
        "pass_not_complete_count": sum(row["pass_owned"] == "yes" and row["status"] != "complete" for row in profiles),
        "continuous_segments": segments(owned_statuses), "gap_segments": segments({"confirmed_missing"}),
        "evidence_state": "unknown" if not profiles else "text_claim",
    }


def resource_vector(text: str) -> dict[str, Any]:
    labels = {"white_candles": r"(?:白蠟|白蜡)(?:燭|烛)?", "hearts": r"(?:愛心|爱心)", "red_candles": r"(?:紅蠟|红蜡)(?:燭|烛)?", "season_candles": r"(?:季蠟|季蜡)(?:燭|烛)?"}
    values: dict[str, Any] = {}
    claim_kinds: dict[str, str | None] = {}
    for key, label in labels.items():
        # Approximate point claims remain useful for coarse resource bands, but
        # lower bounds such as "1000以上" / "超過1000" are deliberately not
        # coerced to exact values by this static profile contract.
        match = re.search(rf"{label}\s*[:：]?\s*(約|约|近)?\s*(\d+)(?!\d|\s*(?:以上|起|\+))", text)
        inverted = None
        if not match:
            # Listings also commonly write "1831白蠟".  Only a bare point
            # value is exact: modifiers, lower bounds, plus signs and unit
            # abbreviations such as "千蠟" remain deliberately unknown.
            inverted = re.search(
                rf"(?<![\d約约近+])(?P<value>\d+)(?!\d|\s*(?:\+|以上|起))\s*{label}(?!\s*(?:以上|起))",
                text,
            )
        if match:
            values[key] = int(match.group(2))
            claim_kinds[key] = "approximate" if match.group(1) else "exact"
        elif inverted:
            values[key] = int(inverted.group("value"))
            claim_kinds[key] = "exact"
        else:
            values[key] = None
            claim_kinds[key] = None
    return {"values": values, "claim_kinds": claim_kinds, "capture_date": None, "evidence_state": "text_claim" if any(v is not None for v in values.values()) else "unknown"}


def merge_field_claims(
    field: str, claims: list[tuple[Any, str]], unknown: Any
) -> tuple[Any, dict[str, Any]]:
    """Merge scalar claims without allowing a missing claim to win.

    Values from listing text and its normalized summary are independent
    extraction inputs.  Equal known values retain both sources; different
    known values become ``unknown`` and an explicit conflict.  This helper is
    intentionally unsuitable for market identity/price fields, which the
    migration never derives from feature summaries.
    """
    known = [(value, source) for value, source in claims if value != unknown]
    sources = sorted({source for _, source in known})
    if not known:
        return unknown, {"sources": [], "evidence_state": "unknown"}
    values = {value for value, _ in known}
    if len(values) > 1:
        return unknown, {"sources": sources, "evidence_state": "conflict"}
    return known[0][0], {"sources": sources, "evidence_state": "text_claim"}


def merge_resources(
    listing: dict[str, Any], summary: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    values: dict[str, Any] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for key in ("white_candles", "hearts", "red_candles", "season_candles"):
        value, provenance = merge_field_claims(
            f"resources.values.{key}",
            [(listing["values"].get(key), "listing_text"), (summary["values"].get(key), "normalized_feature_summary")],
            None,
        )
        values[key] = value
        accepted_kinds = [
            source.get("claim_kinds", {}).get(key)
            for source in (listing, summary)
            if source["values"].get(key) == value and value is not None
        ]
        if provenance["evidence_state"] == "text_claim" and "approximate" in accepted_kinds:
            provenance["claim_kind"] = "approximate"
        evidence[f"resources.values.{key}"] = provenance
    states = {row["evidence_state"] for row in evidence.values()}
    overall = "conflict" if "conflict" in states else "text_claim" if "text_claim" in states else "unknown"
    return {"values": values, "capture_date": None, "evidence_state": overall}, evidence


def binding_matrix(record: dict[str, Any], text: str, summary: str = "") -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Build a fail-closed binding matrix from both textual provenance fields."""
    known = {item.get("platform"): item.get("status", "unknown") for item in record.get("bindings", []) if isinstance(item, dict) and isinstance(item.get("platform"), str)}
    platforms = ["google", "apple", "game_center", "facebook", "nintendo", "playstation", "steam", "huawei", "twitter"]
    labels = {"google": r"Google|GG", "apple": r"Apple|蘋果|苹果", "game_center": r"Game\s*Center|(?<![A-Za-z0-9])GC(?![A-Za-z0-9])", "facebook": r"Facebook|FB", "nintendo": r"Nintendo|任天堂", "playstation": r"PlayStation|PSN|PS", "steam": r"Steam", "huawei": r"Huawei|華為|华为", "twitter": r"Twitter|推特"}
    results = []
    evidence_rows: dict[str, dict[str, Any]] = {}
    for platform in platforms:
        def claim(source_text: str) -> str:
            match = re.search(labels[platform], source_text, re.I)
            if not match:
                return "unknown"
            # Keep the platform claim inside its punctuation-delimited clause.
            # Without this, e.g. "GC 不出，Apple 可綁" would leak Apple's
            # availability onto the distinct Game Center binding.
            before = source_text[:match.start()]
            after = source_text[match.end():]
            left = max(before.rfind(mark) for mark in "，,;；。\n") + 1
            right_candidates = [index for mark in "，,;；。\n" if (index := after.find(mark)) >= 0]
            right = min(right_candidates) if right_candidates else len(after)
            context = source_text[left:match.start()] + source_text[match.start():match.end()] + after[:right]
            if re.search(r"未綁|未绑|空綁|空绑|可綁|可绑|可換綁|可换绑|可改綁|可改绑|同出", context):
                return "available"
            if re.search(r"死綁|死绑|不出|遺失|遗失", context):
                return "high_risk"
            return "mentioned_unknown"

        listing_claim, summary_claim = claim(text), claim(summary)
        merged, provenance = merge_field_claims(
            f"bindings.{platform}",
            [(listing_claim, "listing_text"), (summary_claim, "normalized_feature_summary")],
            "unknown",
        )
        # The normalized legacy matrix is retained only when neither textual
        # evidence field says anything.  It has no fabricated field provenance.
        if merged == "unknown" and provenance["evidence_state"] == "unknown":
            merged = known.get(platform, "unknown")
            merged = {"restricted": "high_risk", "included": "available", "transferable": "available", "unbound": "available"}.get(merged, merged)
        evidence_rows[f"bindings.platforms.{platform}"] = provenance
        results.append({"platform": platform, "status": merged, "evidence_state": provenance["evidence_state"]})
    risk_state = record.get("binding_details", {}).get("state", "unknown")
    risk_state = {"partial_or_unknown": "unknown", "clean_claimed": "low", "restricted": "restricted"}.get(risk_state, risk_state)
    if risk_state not in {"low", "restricted", "high_risk", "unknown"}:
        risk_state = "unknown"
    return {
        "platforms": results,
        "risk_state": risk_state,
    }, evidence_rows


def map_completion(text: str) -> dict[str, Any]:
    standard = "partial" if re.search(r"(?:幾乎|几乎|近|大部分).{0,4}(?:全圖|全图|地圖|地图).{0,3}(?:畢|毕)", text) else "complete" if re.search(r"(?:全圖|全图|全地圖|全地图|常駐圖|常驻图).{0,3}(?:畢|毕)", text) else "unknown"
    second = "complete" if re.search(r"(?:全二級斗|全二级斗|二級斗全|二级斗全)", text) else "partial" if re.search(r"二級斗|二级斗", text) else "unknown"
    return {"standard_maps": standard, "second_tier_capes": second, "evidence_state": "text_claim" if standard != "unknown" or second != "unknown" else "unknown"}


def merge_map_completion(
    listing: dict[str, Any], summary: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    fields = ("standard_maps", "second_tier_capes")
    values: dict[str, Any] = {}
    evidence: dict[str, dict[str, Any]] = {}
    for key in fields:
        value, provenance = merge_field_claims(
            f"map_completion.{key}",
            [(listing.get(key), "listing_text"), (summary.get(key), "normalized_feature_summary")],
            "unknown",
        )
        values[key] = value
        evidence[f"map_completion.{key}"] = provenance
    states = {row["evidence_state"] for row in evidence.values()}
    values["evidence_state"] = "conflict" if "conflict" in states else "text_claim" if "text_claim" in states else "unknown"
    return values, evidence


def _platform_scoped_ownership_claim(text: str, match: re.Match[str]) -> bool:
    """Whether an ordinal describes a login binding rather than the account."""
    # Only the explicit "platform ... first holder/binding" construction is
    # platform-scoped. A nearby earlier binding sentence must not swallow a
    # later account-level "第三任" claim.
    if match.group(1) not in {"1", "一"}:
        return False
    before = text[max(0, match.start() - 24):match.start()]
    after = text[match.end():min(len(text), match.end() + 10)]
    platform = r"(?:google|gg|apple|ios|gc|game\s*center|facebook|fb|nintendo|steam|ps|playstation|華為|华为|平台)"
    return bool(re.search(platform + r".{0,16}(?:為|为|是)?\s*$", before, re.I) and re.match(r"\s*(?:持有|綁定|绑定)", after))


def ownership_history(text: str) -> str:
    chinese = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    claims: list[int] = []
    for ordinal in re.finditer(r"第\s*([0-9一二三四五六七八九十]+)\s*(?:任|手)", text):
        if _platform_scoped_ownership_claim(text, ordinal):
            continue
        value = ordinal.group(1)
        number = int(value) if value.isdigit() else chinese.get(value)
        if number is not None:
            claims.append(number)
    if claims:
        highest = max(claims)
        if highest == 1:
            return "first_owner"
        if highest == 2:
            return "second_owner"
        return "multiple_owners"
    if re.search(r"(?:三手|四手|五手|多任|多手)", text): return "multiple_owners"
    if re.search(r"二手|前號主|前号主", text): return "second_owner"
    if re.search(r"一手|自創|自创", text): return "first_owner"
    return "unknown"


def merge_ownership_history(
    listing: str, summary: str
) -> tuple[str, dict[str, dict[str, Any]]]:
    value, provenance = merge_field_claims(
        "ownership_history",
        [(listing, "listing_text"), (summary, "normalized_feature_summary")],
        "unknown",
    )
    return value, {"ownership_history": provenance}


def graduation_claims(text: str, aliases: dict[str, str]) -> list[str]:
    result = set()
    for match in SEASON_RE.finditer(text):
        if not season_term_has_context(text, match):
            continue
        season_id = aliases.get(match.group(0).casefold())
        context = text[max(0, match.start() - 6): min(len(text), match.end() + 8)]
        if season_id and re.search(r"畢業禮|毕业礼", context): result.add(season_id)
    return sorted(result)


def base_profile(
    record: dict[str, Any], account_id: str, aliases: dict[str, str], order: dict[str, int],
    graduation_items: dict[str, list[str]], collection_index: dict[str, tuple[str, str]] | None = None,
    collection_metadata: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    content_claims_allowed = record.get("offer_kind") == "seller_listing" and record.get("entity_kind") == "single_account"
    text = str(record.get("listing_text", "")) if content_claims_allowed else ""
    summary = "\n".join(value for value in record.get("feature_summary", []) if isinstance(value, str)) if content_claims_allowed else ""
    listing_seasons, listing_unresolved = season_profile(text, aliases, order, "listing_text")
    summary_seasons, summary_unresolved = season_profile(summary, aliases, order, "normalized_feature_summary")
    seasons = merge_season_profiles({"listing_text": listing_seasons, "normalized_feature_summary": summary_seasons}, order)
    unresolved = list(dict.fromkeys(listing_unresolved + summary_unresolved))
    account_type = record.get("account_type_primary", "unknown") if content_claims_allowed else "unknown"
    wing_state = record.get("wing_state", "unknown") if content_claims_allowed else "unknown"
    resources, resource_evidence = merge_resources(resource_vector(text), resource_vector(summary))
    maps, map_evidence = merge_map_completion(map_completion(text), map_completion(summary))
    history, history_evidence = merge_ownership_history(ownership_history(text), ownership_history(summary))
    bindings, binding_evidence = binding_matrix(record if content_claims_allowed else {}, text, summary)
    collection_owned, collection_sets, collection_evidence = merge_collection_claims(
        collection_claims(text, collection_index or {}, "listing_text"),
        collection_claims(summary, collection_index or {}, "normalized_feature_summary"),
    )
    # Positive graduation claims may be retained from either source.  This is
    # intentionally not a completion inference; only season-profile fields
    # participate in the conflict-aware merge above.
    graduation_seasons = sorted(set(graduation_claims(text, aliases)) | set(graduation_claims(summary, aliases)))
    metadata = collection_metadata or {
        "ultimate_item_ids": {item for values in graduation_items.values() for item in values},
        "ultimate_by_season": {season_id: set(item_ids) for season_id, item_ids in graduation_items.items()},
    }
    derived_collection, derived_evidence = enrich_collection_from_canonical(
        collection_owned, graduation_seasons, metadata, collection_evidence["collection.owned_item_ids"],
    )
    has_field_conflict = any(
        row["evidence_state"] == "conflict"
        for row in (*resource_evidence.values(), *map_evidence.values(), *history_evidence.values(), *binding_evidence.values())
    )
    has_season_conflict = any(row["evidence_state"] == "conflict" for row in seasons)
    return ({
        "schema_version": SCHEMA_VERSION,
        "account_id": account_id,
        "source_listing_ids": [record["listing_id"]],
        "base_account": {"account_type": account_type, "wing_state": wing_state, "special_appearance": [], "short_id": "unknown"},
        "season_profiles": seasons,
        "season_summary": season_summary(seasons, order),
        "field_evidence": {**resource_evidence, **map_evidence, **history_evidence, **binding_evidence, **collection_evidence, **derived_evidence},
        "collection": {"owned_item_ids": sorted(collection_owned), "item_set_profiles": collection_sets, "graduation_rewards": derived_collection["graduation_rewards"], "graduation_reward_season_ids": graduation_seasons, "collaboration_items": derived_collection["collaboration_items"], "bundle_item_ids": derived_collection["bundle_item_ids"], "event_limited_item_ids": derived_collection["event_limited_item_ids"], "bundle_claim_level": "unknown"},
        "map_completion": maps,
        "resources": resources,
        "bindings": bindings,
        "ownership_history": history,
        "trade_conditions": {"offer_kind": record.get("offer_kind", "unknown"), "entity_kind": record.get("entity_kind", "unknown"), "price_type": record.get("price_type", "unknown")},
        "evidence_quality": {"listing_text": record.get("evidence_quality", "unknown"), "image": "not_collected", "ocr": "not_collected"},
        "review_status": "needs_review" if unresolved or has_field_conflict or has_season_conflict else "unknown",
    }, unresolved)


def migrate(v3_root: Path, old_root: Path) -> dict[str, Any]:
    legacy_data = old_root / "data"
    batches = sorted(legacy_data.glob("batch-*.jsonl"))
    if len(batches) != 71:
        raise RuntimeError(f"expected 71 legacy batches, found {len(batches)}")
    raw_rows = [row for batch in batches for row in read_jsonl(batch)]
    normalized = read_jsonl(legacy_data / "v2.2" / "normalized-listings.jsonl")
    source_names = {str(row.get("source_group_name")) for row in normalized if row.get("source_group_name")}
    histories = read_jsonl(legacy_data / "v2" / "curated-listing-histories.jsonl")
    comparables = read_jsonl(legacy_data / "v2.4" / "market-comparables.jsonl")
    if len(raw_rows) != 1022 or len(normalized) != 1022 or len(histories) != 102 or len(comparables) != 102:
        raise RuntimeError("legacy counts do not match required 1022/102 contract")

    old_to_new: dict[str, str] = {}
    post_to_new: dict[str, str] = {}
    source_out: list[dict[str, Any]] = []
    for index, row in enumerate(raw_rows, 1):
        key = str(row.get("post_key", f"raw-{index}"))
        listing_id = f"listing_{index:04d}"
        post_to_new[key] = listing_id
        listing_text = sanitize_market_text(row.get("listing_text", ""), source_names)
        source_out.append({
            "schema_version": SCHEMA_VERSION,
            "listing_id": listing_id,
            "legacy_key": pseudo("legacy", key),
            "observed_at": safe_date(row.get("observed_date")),
            "post_date": None,
            "date_verified": False,
            "date_evidence_state": "unknown",
            "post_date_text": row.get("post_date_text") or "unknown",
            "listing_text": listing_text,
            "price_twd": row.get("price_twd"),
            "price_type": normalize_urgent_listing_price_type(str(row.get("price_type", "unknown")), listing_text),
            "status": row.get("status", "unknown"),
            "account_features": sanitize_market_text(row.get("account_features", ""), source_names),
            "risk_features": sanitize_market_text(row.get("risk_features", ""), source_names),
            "evidence_quality": row.get("evidence_quality", "unknown"),
            "exclusion_reason": row.get("exclusion_reason"),
        })

    normalized_out: list[dict[str, Any]] = []
    for index, row in enumerate(normalized, 1):
        old_id = str(row["listing_id"])
        new_id = post_to_new.get(str(row.get("source_post_key")), f"listing_{index:04d}")
        old_to_new[old_id] = new_id
        result = clean(row)
        result.update({
            "schema_version": SCHEMA_VERSION,
            "listing_id": new_id,
            "legacy_key": pseudo("legacy", str(row.get("source_post_key", old_id))),
            "post_date": safe_date(row.get("post_date_iso")),
            "observed_at": safe_date(row.get("observed_date")),
            "date_verified": bool(row.get("date_verified")),
        })
        result["listing_text"] = sanitize_market_text(result.get("listing_text", ""), source_names)
        result["price_type"] = normalize_urgent_listing_price_type(str(result.get("price_type", "unknown")), result["listing_text"])
        if "price_variants" in result:
            result["price_variants"] = normalize_price_variants(result["price_variants"], result["listing_text"])
        apply_explicit_trade_semantics(result)
        result["feature_summary"] = [sanitize_market_text(value, source_names) for value in result.get("feature_summary", [])]
        result["risk_summary"] = [sanitize_market_text(value, source_names) for value in result.get("risk_summary", [])]
        if result["date_verified"] and not result["post_date"]:
            raise RuntimeError(f"verified date missing for {old_id}")
        result.pop("post_date_iso", None)
        normalized_out.append(result)
    normalized_by_listing = {row["listing_id"]: row for row in normalized_out}
    for source in source_out:
        normalized_row = normalized_by_listing[source["listing_id"]]
        source["post_date"] = normalized_row.get("post_date")
        source["date_verified"] = bool(normalized_row.get("date_verified"))
        source["date_evidence_state"] = "verified" if source["date_verified"] else "unknown"
    aliases = catalog_aliases(v3_root)
    season_order = {row["season_id"]: int(row["order_index"]) for row in read_jsonl(v3_root / "knowledge/seasons/seasons.jsonl")}
    item_index = item_aliases(v3_root)
    collection_index = collection_aliases(v3_root)
    items = read_jsonl(v3_root / "knowledge/items/items.jsonl")
    item_sets = read_jsonl(v3_root / "knowledge/sets/item-sets.jsonl")
    collection_metadata = canonical_collection_metadata(items, item_sets)
    graduation_items: dict[str, list[str]] = {}
    for item in items:
        if item.get("ultimate_reward") is True and isinstance(item.get("season_id"), str):
            graduation_items.setdefault(item["season_id"], []).append(item["item_id"])
    profiles: list[dict[str, Any]] = []
    unresolved_seasons: Counter[str] = Counter()
    for row in normalized_out:
        profile, unresolved = base_profile(
            row, f"account_{row['listing_id'].split('_')[1]}", aliases,
            season_order, graduation_items, collection_index,
            collection_metadata,
        )
        profile["post_date"] = row.get("post_date")
        profile["date_verified"] = bool(row.get("date_verified"))
        profile["date_evidence_state"] = "verified" if profile["date_verified"] else "unknown"
        profiles.append(profile)
        unresolved_seasons.update(unresolved)

    comparable_by_id = {str(row["comparable_id"]): row for row in comparables}
    history_out: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    for history in histories:
        history_id = str(history["curated_v2_id"])
        comp = comparable_by_id.get(history_id)
        source_ids = [old_to_new.get(str(value)) for value in history.get("source_listing_ids", [])]
        if not comp or not all(source_ids):
            ledger.append({"legacy_history_id": history_id, "migration_status": "not_migrated", "reason": "missing comparable or normalized lineage"})
            continue
        primary = normalized_out[int(source_ids[0].split("_")[1]) - 1]
        post_date = primary.get("post_date")
        date_verified = bool(history.get("date_verified"))
        if date_verified and not post_date:
            ledger.append({"legacy_history_id": history_id, "migration_status": "not_migrated", "reason": "verified history has no traceable post_date"})
            continue
        sold_claimed = history.get("status") in {"sold", "sold_claimed", "reported_sold"} or history.get("price_type") in {"sold_explicit", "sold_last_ask"}
        legacy_price_type = str(history.get("price_type", "unknown"))
        price_type = normalize_market_price_type(legacy_price_type, primary.get("listing_text", ""))
        legacy_status = str(history.get("status", "unknown"))
        status = {"sold": "sold_claimed", "sold_claimed": "sold_claimed", "reported_sold": "sold_claimed", "active": "active"}.get(legacy_status, "unknown")
        history_row = {
            "schema_version": SCHEMA_VERSION,
            "history_id": f"history_{history_id.split('-')[-1]}",
            "legacy_key": pseudo("legacy_history", history_id),
            "source_listing_ids": source_ids,
            "account_id": f"account_{source_ids[0].split('_')[1]}",
            "selected_price_twd": history.get("selected_price_twd"),
            "price_history_twd": history.get("price_history_twd", []),
            "price_type": price_type,
            "status": status,
            "post_date": post_date,
            "observed_at": primary.get("observed_at"),
            "date_verified": date_verified,
            "date_evidence_state": "verified" if date_verified else "unverified",
            "currency": history.get("currency", "unknown"),
            "currency_verified": bool(history.get("currency_verified")),
            "server": history.get("server", "unknown"),
            "server_verified": bool(history.get("server_verified")),
            # An explicit source-level sale/exchange statement is stronger
            # than a legacy flat transaction label.  It fails closed only for
            # that narrow mixed-offer fact; all other legacy classifications
            # remain unchanged.
            "offer_kind": "mixed" if EXPLICIT_SALE_EXCHANGE_RE.search(str(primary.get("listing_text", ""))) else history.get("offer_kind", "unknown"),
            "entity_kind": "unknown" if EXPLICIT_SALE_EXCHANGE_RE.search(str(primary.get("listing_text", ""))) else history.get("entity_kind", "unknown"),
            "market_pool": comp.get("pool", "unknown"),
            "legacy_features": [sanitize_market_text(value, source_names) for value in comp.get("feature_summary", [])],
            "legacy_risks": [sanitize_market_text(value, source_names) for value in comp.get("risk_summary", [])],
            "evidence_quality": history.get("evidence_quality", "unknown"),
            "sale_outcome": {
                "status": "sold_claimed" if sold_claimed else "not_observed",
                "completed_sale_price_twd": None,
                "verified": False,
            },
        }
        semantic_review = price_semantic_review(str(primary.get("listing_text", "")), price_type)
        if semantic_review is not None:
            history_row["price_semantic_review"] = semantic_review
        history_out.append(history_row)
        if history.get("entity_kind") == "single_account":
            profile = profiles[int(source_ids[0].split("_")[1]) - 1]
            evidence_text = " ".join(
                [str(primary.get("listing_text", ""))]
                + [str(value) for value in comp.get("feature_summary", [])]
                + [str(value) for value in comp.get("bundle_tags", [])]
            )
            owned_items = set(profile["collection"]["owned_item_ids"])
            owned_before_comparable_summary = set(owned_items)
            set_claims = {row["set_id"]: row for row in profile["collection"]["item_set_profiles"]}
            for alias in longest_non_overlapping_aliases(evidence_text.casefold(), collection_index):
                target_type, target_id = collection_index[alias]
                if not mentioned_without_negation(evidence_text.casefold(), alias):
                    continue
                if target_type == "item":
                    owned_items.add(target_id)
                else:
                    set_claims[target_id] = {
                        "set_id": target_id, "status": "mentioned_unverified",
                        "completion_ratio": None, "is_complete": None,
                        "owned_item_ids": [], "missing_item_ids": [],
                        "evidence_state": "text_claim", "review_status": "needs_review",
                    }
            profile["collection"]["owned_item_ids"] = sorted(owned_items)
            # Comparable summaries are an explicit, normalized text field;
            # preserve that provenance when they add a canonical owned item.
            if owned_items != owned_before_comparable_summary:
                owned_provenance = profile["field_evidence"]["collection.owned_item_ids"]
                owned_provenance["sources"] = sorted(set(owned_provenance.get("sources", [])) | {"normalized_feature_summary"})
                owned_provenance["evidence_state"] = "text_claim"
            derived, derived_evidence = enrich_collection_from_canonical(
                owned_items,
                profile["collection"]["graduation_reward_season_ids"],
                collection_metadata,
                profile["field_evidence"]["collection.owned_item_ids"],
            )
            profile["collection"]["collaboration_items"] = derived["collaboration_items"]
            profile["collection"]["bundle_item_ids"] = derived["bundle_item_ids"]
            profile["collection"]["event_limited_item_ids"] = derived["event_limited_item_ids"]
            profile["collection"]["graduation_rewards"] = derived["graduation_rewards"]
            profile["field_evidence"].update(derived_evidence)
            profile["collection"]["item_set_profiles"] = [set_claims[key] for key in sorted(set_claims)]
        ledger.append({"legacy_history_id": history_id, "history_id": f"history_{history_id.split('-')[-1]}", "migration_status": "migrated", "source_listing_ids": source_ids, "date_repaired": date_verified, "post_date": post_date})

    review_rows = [{"term": term, "kind": "season_alias", "count": count, "review_status": "needs_review", "reason": "canonical season alias catalog unavailable or no mapping"} for term, count in sorted(unresolved_seasons.items())]
    unresolved_items: Counter[str] = Counter()
    for comparable in comparables:
        for term in comparable.get("bundle_tags", []):
            if isinstance(term, str) and term.casefold() not in collection_index:
                unresolved_items[term] += 1
    item_review_rows = [{"term": term, "kind": "item_alias", "count": count, "review_status": "needs_review", "reason": "legacy bundle tag has no canonical item alias mapping"} for term, count in sorted(unresolved_items.items())]
    canonical_price_types = {"asking", "normal_listing", "urgent_sale", "reduced", "instant", "instant_price", "buyout", "quick_sale", "sold_explicit", "sold_last_ask", "sold_claim"}
    price_types = Counter(str(row.get("price_type", "unknown")) for row in normalized_out)
    price_review_rows = [
        {"price_type": price_type, "count": count, "review_status": "needs_review", "reason": "non-canonical market price type; must not enter a normal single-account asking pool without explicit review"}
        for price_type, count in sorted(price_types.items()) if price_type not in canonical_price_types
    ]
    protected_group_names = {name for name in source_names if name and name.casefold() not in {"光遇", "sky光遇", "sky光·遇"}}
    serialized_output = "\n".join(json.dumps(row, ensure_ascii=False) for row in source_out + normalized_out + history_out)
    leaked_group_names = sorted(name for name in protected_group_names if name in serialized_output)
    if leaked_group_names:
        raise RuntimeError("legacy group-name sanitizer leak detected")
    write_jsonl(v3_root / "data" / "source" / "listings.jsonl", source_out)
    write_jsonl(v3_root / "data" / "normalized" / "listings.jsonl", normalized_out)
    write_jsonl(v3_root / "data" / "normalized" / "account-profiles.jsonl", profiles)
    write_jsonl(v3_root / "data" / "curated" / "histories.jsonl", history_out)
    write_jsonl(v3_root / "data" / "comparables" / "histories.jsonl", history_out)
    profile_by_id = {row["account_id"]: row for row in profiles}
    comparable_accounts = []
    for history in history_out:
        profile = dict(profile_by_id[history["account_id"]])
        profile.update({
            "comparable_id": history["history_id"], "history_id": history["history_id"],
            "selected_price_twd": history["selected_price_twd"], "price_history_twd": history["price_history_twd"],
            "price_type": history["price_type"], "status": history["status"], "post_date": history["post_date"],
            "observed_at": history["observed_at"], "date_verified": history["date_verified"],
            "currency": history["currency"], "currency_verified": history["currency_verified"],
            "server": history["server"], "server_verified": history["server_verified"],
            "offer_kind": history["offer_kind"], "entity_kind": history["entity_kind"],
            "market_pool": history["market_pool"], "market_evidence_quality": history["evidence_quality"],
            "sale_outcome": history["sale_outcome"],
        })
        comparable_accounts.append(profile)
    write_jsonl(v3_root / "data" / "comparables" / "accounts.jsonl", comparable_accounts)
    write_jsonl(v3_root / "data" / "review" / "unmapped-season-aliases.jsonl", review_rows)
    write_jsonl(v3_root / "data" / "review" / "unmapped-item-aliases.jsonl", item_review_rows)
    write_jsonl(v3_root / "data" / "review" / "price-type-review.jsonl", price_review_rows)
    write_jsonl(v3_root / "reports" / "migration" / "migration-ledger.jsonl", ledger)
    summary = {
        "schema_version": SCHEMA_VERSION, "legacy_batches": len(batches), "source_listings": len(source_out),
        "normalized_listings": len(normalized_out), "legacy_histories": len(histories), "migrated_histories": len(history_out),
        "not_migrated_histories": len(histories) - len(history_out), "verified_dates_in_normalized": sum(1 for row in normalized_out if row["date_verified"]),
        "verified_dates_repaired_in_histories": sum(1 for row in history_out if row["date_verified"]), "unmapped_season_terms": len(review_rows), "unmapped_item_terms": len(item_review_rows), "price_type_review_terms": len(price_review_rows),
        "legacy_group_names_sanitized": len(protected_group_names), "offline_only": True, "privacy": "source-group identity and locators removed; legacy keys are SHA-256 pseudonyms",
    }
    write_json(v3_root / "reports" / "migration" / "migration-summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline v2.4 to v3 P0 migration")
    parser.add_argument("--v3-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--legacy-root", type=Path)
    args = parser.parse_args()
    v3_root = args.v3_root.resolve()
    old_root = (args.legacy_root or legacy_root(v3_root)).resolve()
    print(json.dumps(migrate(v3_root, old_root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
