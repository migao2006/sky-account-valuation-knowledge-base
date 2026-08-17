#!/usr/bin/env python3
"""Derive the user-goal completion state from formal repository evidence."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _check(identifier: str, passed: bool, actual: Any, requirement: str, paths: list[str]) -> dict[str, Any]:
    return {"contract_id": identifier, "passed": passed, "actual": actual, "requirement": requirement, "evidence_paths": paths}


def _published_capacity_ready(readiness: dict[str, Any], bindings: object) -> bool:
    """Require every actually published price line to own a strict 300/100 split."""
    if not isinstance(bindings, list):
        return False
    published = {
        str(row.get("price_line")) for row in bindings
        if isinstance(row, dict) and isinstance(row.get("price_line"), str)
    }
    if not published:
        return False
    available: set[str] = set()
    for pool in readiness.get("market_pools", []):
        if not isinstance(pool, dict):
            continue
        split = pool.get("time_forward_split")
        name = pool.get("market_pool")
        if (isinstance(name, str) and isinstance(split, dict)
                and split.get("available") is True
                and split.get("training_clusters", 0) >= 300
                and split.get("holdout_clusters", 0) >= 100
                and split.get("cluster_overlap") is False):
            available.add(name.rsplit(":", 1)[-1])
    return published <= available


def build(
    root: Path,
    market_audit_authority_bundle: str | Path | None = None,
    market_audit_authority_bundle_sha256: str | None = None,
    parser_gold_replay_inputs: str | Path | None = None,
    parser_gold_replay_inputs_sha256: str | None = None,
    parser_gold_authority_bundle: str | Path | None = None,
    parser_gold_authority_bundle_sha256: str | None = None,
    parser_keyed_custodian_authority_bundle: str | Path | None = None,
    parser_keyed_custodian_authority_bundle_sha256: str | None = None,
    parser_keyed_custodian_contract: str | Path | None = None,
    parser_keyed_custodian_contract_sha256: str | None = None,
    parser_keyed_replay_binding: str | Path | None = None,
    parser_keyed_replay_binding_sha256: str | None = None,
    canonical_review_authority_bundle: str | Path | None = None,
    canonical_review_authority_bundle_sha256: str | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    parser = _json(root / "reports/parser-knowledge-coverage.json")
    readiness = _json(root / "reports/model-publication-readiness.json")
    evaluation = _json(root / "reports/model-publication-evaluation.json")
    parser_gold = _json(root / "reports/parser-gold-evaluation.json")
    market_gold_report = _json(root / "reports/market-gold-evaluation.json")
    # Keep this executable both as a package import and as ``python path/to``.
    try:
        from .catalog_completion import build as build_catalog_completion
    except ImportError:
        try:
            from .catalog_completion import build as build_catalog_completion
        except ImportError:  # direct script execution
            from catalog_completion import build as build_catalog_completion
    catalog_completion = build_catalog_completion(root, canonical_review_authority_bundle, canonical_review_authority_bundle_sha256)
    items = _jsonl(root / "knowledge/items/items.jsonl")
    eligible = sum(row.get("verification_status") == "verified" and row.get("model_feature_status") == "eligible" for row in items)
    verified = sum(row.get("verification_status") == "verified" for row in items)
    artifact_names = (
        "elastic-net-normal_listing.json", "elastic-net-urgent_sale.json",
        "xgboost-normal_listing.json", "xgboost-urgent_sale.json",
    )
    artifact_files = [root / "modeling/artifacts" / name for name in artifact_names]
    artifacts = [_json(path) for path in artifact_files]
    bindings = evaluation.get("artifact_bindings", [])
    try:
        from tools.modeling.publication_evaluator import build as replay_publication_evaluation
        from tools.validate.release_check import model_artifacts_release_valid
        evaluation_replayed = evaluation == replay_publication_evaluation(root)
        artifact_paths = {
            (str(artifact.get("model_type")), str(artifact.get("price_line"))): path
            for artifact, path in zip(artifacts, artifact_files)
        }
        exact_runtime_bindings = model_artifacts_release_valid(
            artifacts, evaluation, artifact_paths, evaluation_replayed,
        )
    except Exception:
        evaluation_replayed = False
        exact_runtime_bindings = False
    try:
        from tools.modeling.market_gold_evaluator import build as replay_market_gold_evaluation
        market_gold_replayed = market_gold_report == replay_market_gold_evaluation(
            root,
            market_audit_authority_bundle,
            market_audit_authority_bundle_sha256,
        )
    except Exception:
        market_gold_replayed = False
    try:
        from tools.modeling.parser_gold_evaluator import build as replay_parser_gold_evaluation
        parser_gold_replayed = parser_gold == replay_parser_gold_evaluation(
            root,
            Path(parser_gold_replay_inputs) if parser_gold_replay_inputs is not None else None,
            parser_gold_replay_inputs_sha256,
            parser_gold_authority_bundle,
            parser_gold_authority_bundle_sha256,
            parser_keyed_custodian_authority_bundle,
            parser_keyed_custodian_authority_bundle_sha256,
            parser_keyed_custodian_contract,
            parser_keyed_custodian_contract_sha256,
            parser_keyed_replay_binding,
            parser_keyed_replay_binding_sha256,
        )
    except Exception:
        parser_gold_replayed = False
    runtime_publication_bound = (
        evaluation.get("publication_ready") is True
        and evaluation.get("status") == "passed"
        and artifacts
        and evaluation_replayed
        and exact_runtime_bindings
    )
    checks = [
        *catalog_completion["checks"],
        _check("catalog.model_eligible_positive", eligible > 0, {"verified": verified, "model_eligible": eligible}, "verified canonical items with independently approved observation tokens", ["knowledge/items/items.jsonl", "reports/parser-knowledge-coverage.json"]),
        _check("parser.human_gold_200", parser_gold_replayed and parser_gold.get("gold_row_count", 0) == 200 and parser_gold.get("rule_development_manifest_sha256") is not None, {"report_replayed": parser_gold_replayed, "rows": parser_gold.get("gold_row_count", 0), "development": parser_gold.get("development", {}).get("row_count", 0), "heldout": parser_gold.get("heldout", {}).get("row_count", 0), "signed_rule_manifest": parser_gold.get("rule_development_manifest_sha256") is not None}, "exactly 200 independently double-annotated parser claims with adjudication and a replayed keyed 100/100 development/held-out split", ["reports/parser-gold-evaluation.json", "data/review/parser-gold/claims.jsonl"]),
        _check("parser.metrics_passed", parser_gold_replayed and parser_gold.get("publication_ready") is True and parser_gold.get("status") == "evaluated", {"report_replayed": parser_gold_replayed, "status": parser_gold.get("status"), "heldout": parser_gold.get("heldout"), "strata": parser_gold.get("strata_distinct_value_counts"), "verified_alias_tokens": parser.get("verified_alias_token_count", 0)}, "replayed held-out precision >=98%, recall >=95%, collision error rate 0, no unknown-to-missing errors, and locked strata coverage", ["reports/parser-gold-evaluation.json", "reports/parser-knowledge-coverage.json"]),
        _check("market.human_gold_evaluation_passed", market_gold_replayed and market_gold_report.get("publication_ready") is True and market_gold_report.get("status") == "evaluated", {"report_replayed": market_gold_replayed, "status": market_gold_report.get("status"), "rows": market_gold_report.get("gold_row_count"), "heldout_minimum_annotator_field_accuracy": market_gold_report.get("heldout_minimum_annotator_field_accuracy"), "verified_sale_false_positives": market_gold_report.get("heldout_verified_sale_false_positive_count"), "independent_blinded_decisions_proven": market_gold_report.get("independent_blinded_decisions_proven")}, "at least 200 externally attested independently double-annotated claims; 100/100 opaque-stratified development/held-out split; each five-field held-out accuracy >=98%; verified-sale false positives = 0", ["reports/market-gold-evaluation.json", "data/review/market-claim-gold.jsonl", "data/review/market-audit/attestations.jsonl"]),
        _check("market.train_holdout_capacity", _published_capacity_ready(readiness, bindings), [{"pool": pool.get("market_pool"), "train": pool.get("time_forward_split", {}).get("training_clusters"), "holdout": pool.get("time_forward_split", {}).get("holdout_clusters")} for pool in readiness.get("market_pools", [])], "each published pool has >=300 independent training clusters and >=100 later holdout clusters", ["reports/model-publication-readiness.json", "reports/model-publication-split.json", "reports/model-publication-evaluation.json"]),
        _check("market.verified_sales_positive", readiness.get("verified_completed_sale_count", 0) > 0, readiness.get("verified_completed_sale_count", 0), "verified completed-sale evidence available for claimed sale-price use", ["reports/model-publication-readiness.json"]),
        _check("model.replayable_publication_passed", runtime_publication_bound, {"evaluation_status": evaluation.get("status"), "publication_ready": evaluation.get("publication_ready"), "trained_artifacts": sum(row.get("status") == "trained" for row in artifacts), "runtime_artifact_bindings": len(bindings) if isinstance(bindings, list) else 0}, "replayable untouched-holdout evaluator passes every accuracy, interval, subgroup and OOD threshold and binds every published runtime artifact", ["reports/model-publication-evaluation.json", "modeling/artifacts"]),
    ]
    return {
        "schema_version": "1.5-p4.1",
        "goal": "precise_account_valuation_and_complete_knowledge_base",
        "status": "complete" if all(row["passed"] for row in checks) else "incomplete",
        "complete": all(row["passed"] for row in checks),
        "checks": checks,
        "blocking_contract_ids": [row["contract_id"] for row in checks if not row["passed"]],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--market-audit-authority-bundle")
    parser.add_argument("--market-audit-authority-bundle-sha256")
    parser.add_argument("--parser-gold-replay-inputs")
    parser.add_argument("--parser-gold-replay-inputs-sha256")
    parser.add_argument("--parser-gold-authority-bundle")
    parser.add_argument("--parser-gold-authority-bundle-sha256")
    parser.add_argument("--parser-keyed-custodian-authority-bundle")
    parser.add_argument("--parser-keyed-custodian-authority-bundle-sha256")
    parser.add_argument("--parser-keyed-custodian-contract")
    parser.add_argument("--parser-keyed-custodian-contract-sha256")
    parser.add_argument("--parser-keyed-replay-binding")
    parser.add_argument("--parser-keyed-replay-binding-sha256")
    parser.add_argument("--canonical-review-authority-bundle")
    parser.add_argument("--canonical-review-authority-bundle-sha256")
    args = parser.parse_args()
    payload = json.dumps(
        build(
            args.root,
            args.market_audit_authority_bundle,
            args.market_audit_authority_bundle_sha256,
            args.parser_gold_replay_inputs,
            args.parser_gold_replay_inputs_sha256,
            args.parser_gold_authority_bundle,
            args.parser_gold_authority_bundle_sha256,
            args.parser_keyed_custodian_authority_bundle,
            args.parser_keyed_custodian_authority_bundle_sha256,
            args.parser_keyed_custodian_contract,
            args.parser_keyed_custodian_contract_sha256,
            args.parser_keyed_replay_binding,
            args.parser_keyed_replay_binding_sha256,
            args.canonical_review_authority_bundle,
            args.canonical_review_authority_bundle_sha256,
        ),
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
