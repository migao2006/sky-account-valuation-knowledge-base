#!/usr/bin/env python3
"""Build offline, conservative price-training lines from formal comparable accounts.

The cleaner never infers market facts.  It only admits confirmed TWD,
international-server seller listings for one account, and retains every other
history in an exclusion/review ledger with machine-readable reason codes.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.market_authorization import AuthorizedMarketEvaluator, make_authorization_evaluator, model_training_authorization_reasons


ROOT = Path(__file__).resolve().parents[2]
NORMAL_TYPES = {"asking", "normal_listing"}
URGENT_TYPES = {"reduced", "instant", "urgent_sale", "quick_sale", "instant_price"}
VERIFIED_SALE_TYPES = {"verified_sale"}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows)
    path.write_text(payload, encoding="utf-8", newline="\n")


def normalized_price_type(row: dict[str, Any]) -> str:
    value = str(row.get("price_type", "unknown")).strip().lower()
    if value in NORMAL_TYPES:
        return "normal_listing"
    if value in URGENT_TYPES:
        return "urgent_sale"
    if value in VERIFIED_SALE_TYPES:
        return "verified_sale"
    return "unknown"


def base_account_type(row: dict[str, Any]) -> str:
    nested = row.get("base_account")
    if isinstance(nested, dict) and isinstance(nested.get("account_type"), str):
        return nested["account_type"]
    value = row.get("base_account_type")
    return value if isinstance(value, str) and value else "unknown"


def basic_reasons(row: dict[str, Any], authorization_evaluator: Any = None) -> tuple[str, list[str]]:
    """Return the training line and all hard rejection reasons for one row."""
    reasons: list[str] = []
    reasons.extend(model_training_authorization_reasons(row, authorization_evaluator))
    line = normalized_price_type(row)
    price = row.get("selected_price_twd")
    if not isinstance(price, (int, float)) or isinstance(price, bool) or not math.isfinite(float(price)) or price <= 0:
        reasons.append("invalid_price")
    if row.get("currency") != "TWD":
        reasons.append("currency_not_twd")
    if row.get("currency_verified") is not True:
        reasons.append("currency_unverified")
    if row.get("server") != "international":
        reasons.append("server_not_international")
    if row.get("server_verified") is not True:
        reasons.append("server_unverified")
    if row.get("offer_kind") != "seller_listing":
        reasons.append("not_seller_listing")
    if row.get("entity_kind") != "single_account":
        reasons.append("not_single_account")
    # Source adapters may explicitly flag a price which covers more than this
    # account.  Absence is not treated as a claim either way; the formal P0
    # histories instead carry the seller/single-account contract above.
    if row.get("mixed_price") is True or row.get("is_mixed_price") is True:
        reasons.append("mixed_price")
    semantic_review = row.get("price_semantic_review")
    if isinstance(semantic_review, dict) and semantic_review.get("brokerage_included") is True:
        # The displayed amount covers an account plus brokerage.  Do not guess
        # a fee or subtract one; retain the price-line semantics in the ledger
        # and require offline review before any model training use.
        reasons.append("brokerage_included_price")
    if isinstance(semantic_review, dict) and semantic_review.get("multi_price") is True:
        # Do not select one installment/badge-inclusion alternative as if it
        # were the account's single cash listing price.
        reasons.append("multiple_price_terms")
    if line == "unknown":
        reasons.append("price_type_not_training_line")
    return line, reasons


def cluster_sort_key(row: dict[str, Any]) -> tuple[str, str, str]:
    # A single anonymous account is one cluster.  Prefer the latest documented
    # observation; history_id makes ties deterministic and reproducible.
    return (str(row.get("post_date") or ""), str(row.get("observed_at") or ""), str(row.get("history_id") or ""))


def modified_z(value: float, values: list[float]) -> float | None:
    median = statistics.median(values)
    mad = statistics.median([abs(item - median) for item in values])
    if mad == 0:
        return None
    return 0.6745 * (value - median) / mad


def exclusion(row: dict[str, Any], line: str, reasons: list[str], disposition: str = "excluded") -> dict[str, Any]:
    price = row.get("selected_price_twd")
    return {
        "schema_version": "3.1-p1", "history_id": row["history_id"], "account_id": row["account_id"],
        "reason_codes": sorted(set(reasons)), "disposition": disposition, "price_line": line,
        "selected_price_twd": price if isinstance(price, (int, float)) and not isinstance(price, bool) else None,
    }


def cleaned(row: dict[str, Any], line: str, rank: int, production_feature_lineage: bool = False) -> dict[str, Any]:
    price = float(row["selected_price_twd"])
    output = {
        "schema_version": "3.1-p1", "cleaned_price_id": "cleaned_price_" + row["history_id"].removeprefix("history_"),
        "history_id": row["history_id"], "account_id": row["account_id"], "cluster_id": row["dedup_cluster_id"] if production_feature_lineage else "cluster_" + row["account_id"].removeprefix("account_"),
        "cluster_rank": rank, "selected_price_twd": price, "log_price_twd": math.log(price),
        "price_line": line, "normalized_price_type": line, "base_account_type": base_account_type(row),
        "post_date": row.get("post_date"), "date_verified": row.get("date_verified") is True,
        "observed_at": row["observed_at"], "currency": "TWD", "server": "international",
        "evidence_quality": row.get("market_evidence_quality", row.get("evidence_quality", "unknown")), "review_status": "accepted",
    }
    if production_feature_lineage:
        lineage=row["feature_lineage"]
        output.update({key: lineage[key] for key in ("training_example_id", "training_example_digest", "feature_payload_sha256", "catalog_provenance_sha256", "dedup_cluster_digest")})
        if line == "verified_sale":
            output.update({
                "completed_sale_verified": True, "sale_verified": True,
                "completed_sale_date": row["completed_sale_date"],
                "completion_evidence_digest": row["completion_evidence_digest"],
                "independent_evidence_ids": row["independent_evidence_ids"],
                "observation_row_digest": lineage["observation_row_digest"],
            })
    return output


def _clean_verified(rows: list[dict[str, Any]], authorization_evaluator: Any = None, *, include_verified_sales: bool = False) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Core cleaner; callers must obtain the evaluator from the replay factory."""
    production_feature_lineage = (
        isinstance(authorization_evaluator, AuthorizedMarketEvaluator)
        and authorization_evaluator.factory_verified is True
        and authorization_evaluator.feature_lineage_bound is True
    )
    candidates: list[tuple[dict[str, Any], str]] = []
    ledger: list[dict[str, Any]] = []
    for row in rows:
        line, reasons = basic_reasons(row, authorization_evaluator)
        if line == "verified_sale" and not include_verified_sales:
            reasons.append("verified_sale_requires_separate_pool")
        if reasons:
            disposition = "needs_review" if {"brokerage_included_price", "multiple_price_terms"} & set(reasons) else "excluded"
            ledger.append(exclusion(row, line, reasons, disposition))
        else:
            candidates.append((row, line))

    # A cluster can contribute at most once per price line.  This prevents the
    # same anonymous account being repeated in a training split.
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row, line in candidates:
        cluster = str(row["dedup_cluster_id"]) if production_feature_lineage else str(row["account_id"])
        grouped[(cluster, line)].append(row)
    retained: list[tuple[dict[str, Any], str, int]] = []
    for (_, line), group in sorted(grouped.items()):
        ordered = sorted(group, key=cluster_sort_key, reverse=True)
        retained.append((ordered[0], line, 1))
        for rank, duplicate in enumerate(ordered[1:], 2):
            ledger.append(exclusion(duplicate, line, ["duplicate_account_cluster", f"cluster_rank_{rank}"]))

    # Modified-z is only actionable in a same-line + base-account-type group of
    # at least ten independent clusters.  Small groups are not silently judged.
    by_group: dict[tuple[str, str], list[tuple[dict[str, Any], str, int]]] = defaultdict(list)
    for entry in retained:
        by_group[(entry[1], base_account_type(entry[0]))].append(entry)
    accepted: list[dict[str, Any]] = []
    for group in by_group.values():
        values = [math.log(float(entry[0]["selected_price_twd"])) for entry in group]
        actionable = len(group) >= 10
        for row, line, rank in group:
            z_score = modified_z(math.log(float(row["selected_price_twd"])), values)
            if z_score is not None and abs(z_score) > 3.5 and actionable:
                ledger.append(exclusion(row, line, ["log_price_modified_z_outlier"]))
            elif z_score is not None and abs(z_score) > 3.5:
                ledger.append(exclusion(row, line, ["log_price_outlier_insufficient_group"], "needs_review"))
            else:
                accepted.append(cleaned(row, line, rank, production_feature_lineage))
    normal = sorted((row for row in accepted if row["price_line"] == "normal_listing"), key=lambda row: row["history_id"])
    urgent = sorted((row for row in accepted if row["price_line"] == "urgent_sale"), key=lambda row: row["history_id"])
    sales = sorted((row for row in accepted if row["price_line"] == "verified_sale"), key=lambda row: row["history_id"])
    return normal, urgent, sales, sorted(ledger, key=lambda row: row["history_id"])


def clean(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Fail-closed public cleaner without externally verified authorization."""
    normal, urgent, _sales, exclusions = _clean_verified(rows)
    return normal, urgent, exclusions


def clean_authorized(
    rows: list[dict[str, Any]], root: Path,
    authority_bundle: str | Path | None = None, authority_bundle_sha256: str | None = None,
    statement: str | Path | None = None, statement_sha256: str | None = None,
    identity_authority_bundle: str | Path | None = None, identity_authority_bundle_sha256: str | None = None,
    identity_mapping: str | Path | None = None, identity_mapping_sha256: str | None = None,
    identity_statement: str | Path | None = None, identity_statement_sha256: str | None = None,
    receipt_archive: str | Path | None = None, receipt_archive_sha256: str | None = None,
    receipt_authority_bundle: str | Path | None = None, receipt_authority_bundle_sha256: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Replay external trust material internally, then clean exact bound rows."""
    evaluator = make_authorization_evaluator(
        root, authority_bundle, authority_bundle_sha256, statement, statement_sha256,
        identity_authority_bundle, identity_authority_bundle_sha256,
        identity_mapping, identity_mapping_sha256,
        identity_statement, identity_statement_sha256,
        receipt_archive, receipt_archive_sha256,
        receipt_authority_bundle, receipt_authority_bundle_sha256,
    )
    if evaluator.errors:
        raise ValueError("authorized market intake is invalid: " + "; ".join(evaluator.errors))
    projected = evaluator.bound_training_rows()
    projected_keys = {
        tuple(row["market_data_authorization"].get(name) for name in ("authorization_record_id", "dataset_id", "observation_id"))
        for row in projected
    }
    supplied = [row for row in rows if tuple((row.get("market_data_authorization") or {}).get(name) for name in ("authorization_record_id", "dataset_id", "observation_id")) not in projected_keys]
    normal, urgent, _sales, exclusions = _clean_verified([*supplied, *projected], evaluator)
    return normal, urgent, exclusions


def clean_authorized_with_verified_sales(
    rows: list[dict[str, Any]], root: Path,
    authority_bundle: str | Path | None = None, authority_bundle_sha256: str | None = None,
    statement: str | Path | None = None, statement_sha256: str | None = None,
    identity_authority_bundle: str | Path | None = None, identity_authority_bundle_sha256: str | None = None,
    identity_mapping: str | Path | None = None, identity_mapping_sha256: str | None = None,
    identity_statement: str | Path | None = None, identity_statement_sha256: str | None = None,
    receipt_archive: str | Path | None = None, receipt_archive_sha256: str | None = None,
    receipt_authority_bundle: str | Path | None = None, receipt_authority_bundle_sha256: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return a dedicated verified-sale pool; it is never mixed with asking prices."""
    evaluator = make_authorization_evaluator(
        root, authority_bundle, authority_bundle_sha256, statement, statement_sha256,
        identity_authority_bundle, identity_authority_bundle_sha256,
        identity_mapping, identity_mapping_sha256,
        identity_statement, identity_statement_sha256,
        receipt_archive, receipt_archive_sha256,
        receipt_authority_bundle, receipt_authority_bundle_sha256,
    )
    if evaluator.errors:
        raise ValueError("authorized market intake is invalid: " + "; ".join(evaluator.errors))
    projected = evaluator.bound_training_rows()
    projected_keys = {
        tuple(row["market_data_authorization"].get(name) for name in ("authorization_record_id", "dataset_id", "observation_id"))
        for row in projected
    }
    supplied = [row for row in rows if tuple((row.get("market_data_authorization") or {}).get(name) for name in ("authorization_record_id", "dataset_id", "observation_id")) not in projected_keys]
    return _clean_verified([*supplied, *projected], evaluator, include_verified_sales=True)


def build(
    root: Path, input_path: Path | None = None, output_dir: Path | None = None,
    authority_bundle: str | Path | None = None, authority_bundle_sha256: str | None = None,
    statement: str | Path | None = None, statement_sha256: str | None = None,
    identity_authority_bundle: str | Path | None = None, identity_authority_bundle_sha256: str | None = None,
    identity_mapping: str | Path | None = None, identity_mapping_sha256: str | None = None,
    identity_statement: str | Path | None = None, identity_statement_sha256: str | None = None,
    receipt_archive: str | Path | None = None, receipt_archive_sha256: str | None = None,
    receipt_authority_bundle: str | Path | None = None, receipt_authority_bundle_sha256: str | None = None,
) -> dict[str, int]:
    source = input_path or root / "data/comparables/accounts.jsonl"
    destination = output_dir or root / "data/modeling"
    normal, urgent, verified_sales, exclusions = clean_authorized_with_verified_sales(
        read_jsonl(source), root, authority_bundle, authority_bundle_sha256, statement, statement_sha256,
        identity_authority_bundle, identity_authority_bundle_sha256,
        identity_mapping, identity_mapping_sha256,
        identity_statement, identity_statement_sha256,
        receipt_archive, receipt_archive_sha256,
        receipt_authority_bundle, receipt_authority_bundle_sha256,
    )
    write_jsonl(destination / "price-cleaned-normal.jsonl", normal)
    write_jsonl(destination / "price-cleaned-urgent.jsonl", urgent)
    write_jsonl(destination / "price-cleaned-verified-sales.jsonl", verified_sales)
    write_jsonl(destination / "model-exclusions.jsonl", exclusions)
    return {"input_rows": len(read_jsonl(source)), "normal_listing": len(normal), "urgent_sale": len(urgent), "verified_sale": len(verified_sales), "excluded_or_review": len(exclusions)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean formal comparable prices for offline P1 model input")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--market-authorization-authority-bundle", type=Path)
    parser.add_argument("--market-authorization-authority-bundle-sha256")
    parser.add_argument("--market-authorization-statement", type=Path)
    parser.add_argument("--market-authorization-statement-sha256")
    parser.add_argument("--market-identity-authority-bundle", type=Path)
    parser.add_argument("--market-identity-authority-bundle-sha256")
    parser.add_argument("--market-identity-mapping", type=Path)
    parser.add_argument("--market-identity-mapping-sha256")
    parser.add_argument("--market-identity-statement", type=Path)
    parser.add_argument("--market-identity-statement-sha256")
    parser.add_argument("--market-receipt-archive", type=Path)
    parser.add_argument("--market-receipt-archive-sha256")
    parser.add_argument("--market-receipt-authority-bundle", type=Path)
    parser.add_argument("--market-receipt-authority-bundle-sha256")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        result = build(
            root, args.input, args.output_dir,
            args.market_authorization_authority_bundle,
            args.market_authorization_authority_bundle_sha256,
            args.market_authorization_statement, args.market_authorization_statement_sha256,
            args.market_identity_authority_bundle, args.market_identity_authority_bundle_sha256,
            args.market_identity_mapping, args.market_identity_mapping_sha256,
            args.market_identity_statement, args.market_identity_statement_sha256,
            args.market_receipt_archive, args.market_receipt_archive_sha256,
            args.market_receipt_authority_bundle, args.market_receipt_authority_bundle_sha256,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
