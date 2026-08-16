"""Offline validation of a plain-JSON modelling artifact; it never retrains."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED = {"schema_version", "status", "price_line", "model_type", "random_seed", "training", "publication_gate", "feature_schema", "input_snapshot_paths", "input_snapshot_sha256", "prediction_contract", "artifact"}
NON_PUBLISHED_STATUSES = {"insufficient_training_data", "dependency_unavailable", "training_failed"}


def evaluate(artifact: dict) -> dict:
    # Publication fields are self-attested JSON until a future evaluator can
    # replay fixed holdout bytes, cluster splits, and model snapshots.  Never
    # let a trained envelope become valid based on those fields alone.
    if artifact.get("status") == "trained":
        return {
            "valid": False,
            "status": "invalid_artifact",
            "reasons": ["model_publication_evaluator_required"],
        }
    if artifact.get("status") not in NON_PUBLISHED_STATUSES:
        return {
            "valid": False,
            "status": "invalid_artifact",
            "reasons": ["unsupported_artifact_status"],
        }
    missing = sorted(REQUIRED - set(artifact))
    if missing:
        return {"valid": False, "status": "invalid_artifact", "reasons": ["missing_keys:" + ",".join(missing)]}
    if artifact["model_type"] != "elastic_net" or artifact["price_line"] not in {"normal_listing", "urgent_sale"}:
        return {"valid": False, "status": "invalid_artifact", "reasons": ["unsupported_model_or_price_line"]}
    return {"valid": True, "status": artifact["status"], "reasons": artifact.get("limitations", [])}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate offline Elastic Net JSON artifact")
    parser.add_argument("--artifact", type=Path, required=True)
    args = parser.parse_args(argv)
    result = evaluate(json.loads(args.artifact.read_text(encoding="utf-8")))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
