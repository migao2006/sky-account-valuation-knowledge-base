#!/usr/bin/env python3
"""Derive the user-goal completion state from formal repository evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _check(identifier: str, passed: bool, actual: Any, requirement: str, paths: list[str]) -> dict[str, Any]:
    return {"contract_id": identifier, "passed": passed, "actual": actual, "requirement": requirement, "evidence_paths": paths}


def build(root: Path) -> dict[str, Any]:
    root = root.resolve()
    coverage = _json(root / "reports/coverage/catalog-coverage.json")
    parser = _json(root / "reports/parser-knowledge-coverage.json")
    readiness = _json(root / "reports/model-publication-readiness.json")
    evaluation = _json(root / "reports/model-publication-evaluation.json")
    parser_gold = _json(root / "reports/parser-gold-evaluation.json")
    unresolved = _jsonl(root / "reports/coverage/unresolved-items.jsonl")
    unmapped = _jsonl(root / "reports/coverage/unmapped-aliases.jsonl")
    market_gold = _jsonl(root / "data/review/market-claim-gold.jsonl")
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
    runtime_publication_bound = (
        evaluation.get("publication_ready") is True
        and evaluation.get("status") == "passed"
        and artifacts
        and all(row.get("status") == "trained" for row in artifacts)
        and evaluation_replayed
        and exact_runtime_bindings
    )
    source_unresolved = coverage.get("p2_3_reference_identities", {}).get("unresolved_rows", 0)
    checks = [
        _check("catalog.unresolved_zero", not unresolved and source_unresolved == 0, {"review_scopes": len(unresolved), "source_references": source_unresolved}, "all in-scope catalog observations resolved or explicitly excluded with evidence", ["reports/coverage/unresolved-items.jsonl", "reports/coverage/catalog-coverage.json"]),
        _check("catalog.unmapped_alias_zero", not unmapped, len(unmapped), "zero unresolved or conflicting aliases", ["reports/coverage/unmapped-aliases.jsonl"]),
        _check("catalog.model_eligible_positive", eligible > 0, {"verified": verified, "model_eligible": eligible}, "verified canonical items with independently approved observation tokens", ["knowledge/items/items.jsonl", "reports/parser-knowledge-coverage.json"]),
        _check("parser.human_gold_200", parser_gold.get("gold_row_count", 0) >= 200 and parser_gold.get("rule_development_manifest_sha256") is not None, {"rows": parser_gold.get("gold_row_count", 0), "development": parser_gold.get("development", {}).get("row_count", 0), "heldout": parser_gold.get("heldout", {}).get("row_count", 0), "signed_rule_manifest": parser_gold.get("rule_development_manifest_sha256") is not None}, "at least 200 independently double-annotated parser claims with adjudication, including >=100 development and >=100 held-out rows", ["reports/parser-gold-evaluation.json", "data/review/parser-gold/claims.jsonl"]),
        _check("parser.metrics_passed", parser_gold.get("publication_ready") is True and parser_gold.get("status") == "evaluated", {"status": parser_gold.get("status"), "heldout": parser_gold.get("heldout"), "strata": parser_gold.get("strata_distinct_value_counts"), "verified_alias_tokens": parser.get("verified_alias_token_count", 0)}, "held-out precision >=98%, recall >=95%, collision error rate 0, no unknown-to-missing errors, and locked strata coverage", ["reports/parser-gold-evaluation.json", "reports/parser-knowledge-coverage.json"]),
        _check("market.human_gold_200", len(market_gold) >= 200, len(market_gold), "at least 200 independently double-annotated market claims", ["data/review/market-claim-gold.jsonl"]),
        _check("market.train_holdout_capacity", any(pool.get("time_forward_split", {}).get("available") for pool in readiness.get("market_pools", [])), [{"pool": pool.get("market_pool"), "train": pool.get("time_forward_split", {}).get("training_clusters"), "holdout": pool.get("time_forward_split", {}).get("holdout_clusters")} for pool in readiness.get("market_pools", [])], "each published pool has >=300 independent training clusters and >=100 later holdout clusters", ["reports/model-publication-readiness.json", "reports/model-publication-split.json"]),
        _check("market.verified_sales_positive", readiness.get("verified_completed_sale_count", 0) > 0, readiness.get("verified_completed_sale_count", 0), "verified completed-sale evidence available for claimed sale-price use", ["reports/model-publication-readiness.json"]),
        _check("model.replayable_publication_passed", runtime_publication_bound, {"evaluation_status": evaluation.get("status"), "publication_ready": evaluation.get("publication_ready"), "trained_artifacts": sum(row.get("status") == "trained" for row in artifacts), "runtime_artifact_bindings": len(bindings) if isinstance(bindings, list) else 0}, "replayable untouched-holdout evaluator passes every accuracy, interval, subgroup and OOD threshold and binds every published runtime artifact", ["reports/model-publication-evaluation.json", "modeling/artifacts"]),
    ]
    return {
        "schema_version": "1.1-p3.3",
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
    args = parser.parse_args()
    payload = json.dumps(build(args.root), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8", newline="\n")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
