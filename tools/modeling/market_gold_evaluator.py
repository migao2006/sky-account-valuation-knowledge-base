#!/usr/bin/env python3
"""Evaluate the formal market-field human-gold gate without fabricating gold."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.normalize.build_market_claim_review import validate_gold_links
from tools.validate.market_audit import audit_market_ledgers, independent_blinded_decisions_errors, keyed_market_finalization_errors


LABEL_FIELDS = ("offer_kind", "entity_kind", "price_type", "currency", "server")
MINIMUM_ROWS = 200
MINIMUM_PER_PARTITION = 100
MINIMUM_FIELD_ACCURACY = 0.98


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _partitions(queue: list[dict[str, Any]], gold: list[dict[str, Any]], binding_rows: list[dict[str, Any]] | None = None) -> tuple[dict[str, str], dict[str, dict[str, int]], list[str]]:
    """Assign a reproducible 5/5 development/held-out split per opaque bucket."""
    errors: list[str] = []
    if binding_rows is not None:
        partitions = {str(row.get("review_id")): str(row.get("split")) for row in binding_rows}
        if len(partitions) != len(gold) or set(partitions) != {str(row.get("review_id")) for row in gold}:
            return {}, {}, ["signed keyed binding does not bijectively cover public gold"]
        coverage: dict[str, dict[str, int]] = {}
        queue_by_id = {str(row.get("review_id")): row for row in queue}
        for review_id, split in partitions.items():
            bucket = str(queue_by_id.get(review_id, {}).get("selection_bucket"))
            coverage.setdefault(bucket, {"gold_rows": 0, "development": 0, "heldout": 0})
            coverage[bucket]["gold_rows"] += 1
            if split in {"development", "heldout"}:
                coverage[bucket][split] += 1
            else:
                errors.append("signed keyed binding contains invalid split")
        for bucket, values in coverage.items():
            if values != {"gold_rows": 10, "development": 5, "heldout": 5}:
                errors.append(f"opaque bucket {bucket} requires exactly 10 gold rows split 5 development / 5 heldout")
        if len(coverage) != 20:
            errors.append(f"requires all 20 opaque review buckets; found {len(coverage)}")
        return partitions, coverage, errors
    by_review = {str(row.get("review_id")): row for row in gold}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in queue:
        if str(row.get("review_id")) in by_review:
            grouped[str(row.get("selection_bucket"))].append(row)
    partitions: dict[str, str] = {}
    coverage: dict[str, dict[str, int]] = {}
    for bucket, rows in sorted(grouped.items()):
        ordered = sorted(rows, key=lambda item: str(item.get("review_id")))
        coverage[bucket] = {"gold_rows": len(ordered), "development": 0, "heldout": 0}
        for index, row in enumerate(ordered):
            partition = "development" if index % 2 == 0 else "heldout"
            partitions[str(row["review_id"])] = partition
            coverage[bucket][partition] += 1
        if len(ordered) != 10 or coverage[bucket]["development"] != 5 or coverage[bucket]["heldout"] != 5:
            errors.append(f"opaque bucket {bucket} requires exactly 10 gold rows split 5 development / 5 heldout")
    if len(coverage) != 20:
        errors.append(f"requires all 20 opaque review buckets; found {len(coverage)}")
    return partitions, coverage, errors


def _metrics(gold: list[dict[str, Any]], partitions: dict[str, str]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for partition in ("development", "heldout"):
        rows = [row for row in gold if partitions.get(str(row.get("review_id"))) == partition]
        role_metrics: dict[str, Any] = {}
        for role, labels_key in (("annotator_a", "annotator_a"), ("annotator_b", "annotator_b")):
            correct = Counter()
            totals = Counter()
            false_positives = 0
            for row in rows:
                annotation = row.get(labels_key, {})
                proposed = annotation.get("labels", {}) if isinstance(annotation, dict) else {}
                adjudication = row.get("adjudication", {})
                final = adjudication.get("final_labels", {}) if isinstance(adjudication, dict) else {}
                for field in LABEL_FIELDS:
                    totals[field] += 1
                    correct[field] += proposed.get(field) == final.get(field)
                false_positives += int(proposed.get("verified_sale") is True and final.get("verified_sale") is not True)
            role_metrics[role] = {
                "field_accuracy": {field: (correct[field] / totals[field] if totals[field] else None) for field in LABEL_FIELDS},
                "verified_sale_false_positive_count": false_positives,
            }
        output[partition] = {"row_count": len(rows), "annotator_metrics": role_metrics}
    return output


def build(root: Path, authority_bundle: str | Path | None = None, authority_bundle_sha256: str | None = None,
          keyed_custodian_authority_bundle: str | Path | None = None, keyed_custodian_authority_bundle_sha256: str | None = None,
          keyed_review_authority_bundle: str | Path | None = None, keyed_review_authority_bundle_sha256: str | None = None,
          keyed_contract: str | Path | None = None, keyed_assignment_ledger: str | Path | None = None,
          keyed_decisions_a: str | Path | None = None, keyed_decisions_b: str | Path | None = None, keyed_adjudications: str | Path | None = None,
          keyed_resolution_map: str | Path | None = None, keyed_candidate: str | Path | None = None,
          keyed_candidate_signature: str | Path | None = None, keyed_binding_signature: str | Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    queue = _jsonl(root / "data/review/market-claim-review.jsonl")
    gold = _jsonl(root / "data/review/market-claim-gold.jsonl")
    linkage_errors = validate_gold_links(queue, gold)
    keyed_args = (keyed_custodian_authority_bundle, keyed_custodian_authority_bundle_sha256, keyed_review_authority_bundle, keyed_review_authority_bundle_sha256, keyed_contract, keyed_assignment_ledger, keyed_decisions_a, keyed_decisions_b, keyed_adjudications, keyed_resolution_map, keyed_candidate, keyed_candidate_signature, keyed_binding_signature)
    keyed_errors, binding = keyed_market_finalization_errors(root, gold, *keyed_args) if (root / "data/review/market-keyed-finalization-receipt.json").exists() else ([], None)
    keyed_mode = binding is not None
    audit_errors = audit_market_ledgers(root, queue, gold, [], [], authority_bundle, authority_bundle_sha256, *keyed_args)
    independence_errors = [] if keyed_mode else independent_blinded_decisions_errors(root, queue, gold, authority_bundle, authority_bundle_sha256)
    partitions, bucket_coverage, stratum_errors = _partitions(queue, gold, binding.get("binding_rows") if keyed_mode else None)
    metrics = _metrics(gold, partitions)
    heldout = metrics["heldout"]
    heldout_field_accuracy = {}
    for field in LABEL_FIELDS:
        values = [role["field_accuracy"][field] for role in heldout["annotator_metrics"].values()]
        heldout_field_accuracy[field] = min(values) if all(value is not None for value in values) else None
    heldout_false_positives = sum(role["verified_sale_false_positive_count"] for role in heldout["annotator_metrics"].values())
    metric_passed = all(value is not None and value >= MINIMUM_FIELD_ACCURACY for value in heldout_field_accuracy.values()) and heldout_false_positives == 0
    count_passed = len(gold) >= MINIMUM_ROWS and metrics["development"]["row_count"] >= MINIMUM_PER_PARTITION and heldout["row_count"] >= MINIMUM_PER_PARTITION
    has_keyed_receipt = (root / "data/review/market-keyed-finalization-receipt.json").exists()
    independence_supported = bool(gold) and not independence_errors and (not has_keyed_receipt or keyed_mode)
    blockers: list[str] = []
    if linkage_errors:
        blockers.extend(linkage_errors)
    if audit_errors:
        blockers.extend(f"market audit: {item}" for item in audit_errors)
    if independence_errors:
        blockers.extend(f"market independence: {item}" for item in independence_errors)
    blockers.extend(keyed_errors); blockers.extend(stratum_errors)
    if not gold:
        blockers.append("requires externally signed blinded annotation-submission receipts before a formal market-gold ledger can be recognized")
    if not count_passed:
        blockers.append("requires >=200 human-gold rows with >=100 development and >=100 held-out rows")
    if not metric_passed:
        blockers.append("requires every held-out offer/entity/price type/currency/server accuracy >=98% and verified-sale false-positive count 0")
    publication_ready = bool(gold) and not linkage_errors and not audit_errors and not keyed_errors and not stratum_errors and independence_supported and count_passed and metric_passed
    return {
        "schema_version": "market-gold-evaluation-v2" if keyed_mode else "market-gold-evaluation-v1",
        "status": "evaluated" if publication_ready else "not_ready",
        "publication_ready": publication_ready,
        "gold_row_count": len(gold),
        "minimums": {"gold_rows": MINIMUM_ROWS, "development_rows": MINIMUM_PER_PARTITION, "heldout_rows": MINIMUM_PER_PARTITION, "heldout_field_accuracy": MINIMUM_FIELD_ACCURACY, "verified_sale_false_positive_count": 0},
        "partition_method": "keyed_signed_binding_v1" if keyed_mode else "opaque_bucket_review_id_alternating_v1",
        "bucket_coverage": bucket_coverage,
        "metrics": metrics,
        "heldout_minimum_annotator_field_accuracy": heldout_field_accuracy,
        "heldout_verified_sale_false_positive_count": heldout_false_positives,
        "independent_blinded_decisions_proven": independence_supported,
        "audit_errors": audit_errors,
        "independence_errors": independence_errors,
        "linkage_errors": linkage_errors,
        "blocking_reasons": blockers,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--market-audit-authority-bundle", type=Path)
    parser.add_argument("--market-audit-authority-bundle-sha256")
    parser.add_argument("--market-keyed-custodian-authority-bundle", type=Path); parser.add_argument("--market-keyed-custodian-authority-bundle-sha256")
    parser.add_argument("--market-keyed-review-authority-bundle", type=Path); parser.add_argument("--market-keyed-review-authority-bundle-sha256")
    parser.add_argument("--market-keyed-contract", type=Path); parser.add_argument("--market-keyed-assignment-ledger", type=Path)
    parser.add_argument("--market-keyed-decisions-a", type=Path); parser.add_argument("--market-keyed-decisions-b", type=Path); parser.add_argument("--market-keyed-adjudications", type=Path)
    parser.add_argument("--market-keyed-resolution-map", type=Path); parser.add_argument("--market-keyed-candidate", type=Path); parser.add_argument("--market-keyed-candidate-signature", type=Path); parser.add_argument("--market-keyed-binding-signature", type=Path)
    args = parser.parse_args()
    payload = json.dumps(build(args.root, args.market_audit_authority_bundle, args.market_audit_authority_bundle_sha256, args.market_keyed_custodian_authority_bundle, args.market_keyed_custodian_authority_bundle_sha256, args.market_keyed_review_authority_bundle, args.market_keyed_review_authority_bundle_sha256, args.market_keyed_contract, args.market_keyed_assignment_ledger, args.market_keyed_decisions_a, args.market_keyed_decisions_b, args.market_keyed_adjudications, args.market_keyed_resolution_map, args.market_keyed_candidate, args.market_keyed_candidate_signature, args.market_keyed_binding_signature), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
