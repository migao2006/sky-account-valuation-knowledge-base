"""Offline validation of a plain-JSON modelling artifact; it never retrains."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED = {"schema_version", "status", "price_line", "model_type", "random_seed", "training", "feature_schema", "input_snapshot_paths", "input_snapshot_sha256", "prediction_contract", "artifact"}


def evaluate(artifact: dict) -> dict:
    missing = sorted(REQUIRED - set(artifact))
    if missing:
        return {"valid": False, "status": "invalid_artifact", "reasons": ["missing_keys:" + ",".join(missing)]}
    if artifact["model_type"] != "elastic_net" or artifact["price_line"] not in {"normal_listing", "urgent_sale"}:
        return {"valid": False, "status": "invalid_artifact", "reasons": ["unsupported_model_or_price_line"]}
    status = artifact["status"]
    if status != "trained":
        return {"valid": True, "status": status, "reasons": artifact.get("limitations", [])}
    model = artifact.get("artifact")
    training = artifact["training"]
    reasons = []
    contract = artifact.get("prediction_contract", {})
    if contract.get("kind") != "additive_log_price":
        reasons.append("trained_artifact_missing_additive_prediction_contract")
    if not isinstance(contract.get("intercept"), (float, int)) or not isinstance(contract.get("coefficients"), dict):
        reasons.append("trained_artifact_missing_plain_coefficients")
    if not isinstance(model, dict) or model.get("serialization") != "plain_json" or not isinstance(model.get("model"), dict):
        reasons.append("trained_artifact_missing_plain_coefficients")
    if not training.get("baseline_beaten") or not training.get("threshold_met"):
        reasons.append("trained_artifact_does_not_meet_quality_gate")
    if not isinstance(training.get("outer_cv_mae"), (float, int)):
        reasons.append("trained_artifact_missing_outer_cv_mae")
    return {"valid": not reasons, "status": "trained" if not reasons else "invalid_artifact", "reasons": reasons, "outer_cv_mae": training.get("outer_cv_mae"), "baseline_mae": training.get("baseline_mae")}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate offline Elastic Net JSON artifact")
    parser.add_argument("--artifact", type=Path, required=True)
    args = parser.parse_args(argv)
    result = evaluate(json.loads(args.artifact.read_text(encoding="utf-8")))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
