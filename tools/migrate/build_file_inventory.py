#!/usr/bin/env python3
"""Build the immutable v2.4 ZIP keep/migrate/replace/remove inventory offline."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

REMOVE = {
    "data/templates/v2.2-backtest-template.jsonl", "data/templates/v2.3-followup-import-template.json",
    "data/templates/v2.4-followup-cases-template.json", "data/tests/mock-v2.4-followup-provider-path.ps1",
    "data/tests/mock-v2.4-followup-provider-pii.ps1", "data/tests/mock-v2.4-followup-provider.ps1",
    "data/tests/v2.2-mock-ocr-provider.ps1", "data/tests/v2.3-mock-ocr-provider.ps1",
    "data/tests/v2.4-mock-multi-image-provider.ps1", "data/v2.3/backtest.json",
    "data/v2.3/calibration.json", "data/v2.3/drift.json", "data/v2.3/followup-ledger.jsonl",
    "data/v2.3/prediction-outcomes.jsonl", "data/v2.4/account-lifecycles.jsonl",
    "data/v2.4/followup-schedule.jsonl", "scripts/backtest-v2.2.ps1", "scripts/backtest-v2.3.ps1",
    "scripts/build-v2.4-followup-schedule.ps1", "scripts/calibrate-v2.3.ps1",
    "scripts/complete-v2.4-followup.ps1", "scripts/drift-v2.3.ps1",
    "scripts/execute-v2.4-followup-query.ps1", "scripts/import-v2.3-followups.ps1",
    "scripts/run-v2.4-followup-cycle.ps1", "scripts/run-v2.4-followup-due.ps1",
    "scripts/transition-v2.3-followup.ps1", "test-v2.3/fixtures/backtest-fixtures.jsonl",
    "test-v2.3/fixtures/integration-followups.json", "v2.2-sales-ocr-backtest.md",
    "v2.4-sales-followup-schema.md",
}


def migrate(path: str) -> bool:
    if path.startswith("data/batch-") and path.endswith(".jsonl"):
        return True
    return path in {
        "data/v2.2/normalized-listings.jsonl", "data/v2/curated-listing-histories.jsonl",
        "data/v2.4/market-comparables.jsonl", "data/v2.4/classifications.jsonl",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-zip", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    digest = hashlib.sha256(args.source_zip.read_bytes()).hexdigest().upper()
    rows = []
    with zipfile.ZipFile(args.source_zip) as archive:
        for name in sorted(info.filename for info in archive.infolist() if not info.is_dir()):
            path = name.removeprefix("sky-valuation/")
            action = "remove" if path in REMOVE else "migrate" if migrate(path) else "replace"
            rows.append({"legacy_path": path, "action": action})
    counts = {key: sum(row["action"] == key for row in rows) for key in ("keep", "migrate", "replace", "remove")}
    output = {
        "source_zip": args.source_zip.name, "source_zip_sha256": digest,
        "source_file_count": len(rows), "counts": counts, "classification_total": sum(counts.values()),
        "entries": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if len(rows) != 237 or counts != {"keep": 0, "migrate": 75, "replace": 131, "remove": 31}:
        raise SystemExit(f"unexpected inventory counts: {counts}, total={len(rows)}")


if __name__ == "__main__":
    main()
