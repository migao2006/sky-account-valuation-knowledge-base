"""Integrity tests for the revision-pinned, non-independent Fandom snapshot."""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "validate"))

from tools.normalize.import_fandom_seasonal_cosmetics_crosswalk import crosswalk, verify_snapshot
from tools.normalize.import_fandom_seasonal_cosmetics_snapshot import build_snapshot, canonical_json
from tools.validate.schema_validator import OfflineSchemaValidator


VENDOR = ROOT / "data" / "source" / "vendor"
REVIEW = ROOT / "data" / "review"


def read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class FandomSeasonalCosmeticsSnapshotTests(unittest.TestCase):
    def test_local_pinned_wikitext_rebuilds_committed_snapshot_and_provenance(self):
        snapshot, metadata = build_snapshot(VENDOR / "fandom-seasonal-cosmetics-r107991.wikitext")
        committed_snapshot = json.loads((VENDOR / "fandom-seasonal-cosmetics-r107991-snapshot.json").read_text(encoding="utf-8"))
        committed_metadata = json.loads((VENDOR / "fandom-seasonal-cosmetics-r107991-metadata.json").read_text(encoding="utf-8"))
        self.assertEqual(snapshot, committed_snapshot)
        self.assertEqual(metadata, committed_metadata)
        self.assertEqual(metadata["revision_id"], 107991)
        self.assertEqual(metadata["revision_timestamp"], "2026-06-13T11:43:55Z")
        self.assertEqual(metadata["page_id"], 17690)
        self.assertEqual(metadata["independence_status"], "not_independent")
        self.assertEqual(metadata["canonical_promotion"], "prohibited_without_independent_review")
        self.assertEqual(metadata["record_count"], 700)
        self.assertEqual(hashlib.sha256(canonical_json(snapshot)).hexdigest().upper(), metadata["snapshot_sha256"])

    def test_crosswalk_is_deterministic_and_preserves_same_lineage_non_promotion(self):
        command = [sys.executable, "tools/normalize/import_fandom_seasonal_cosmetics_crosswalk.py", "--root", str(ROOT)]
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            first, second = directory / "first.jsonl", directory / "second.jsonl"
            first_summary, second_summary = directory / "first.json", directory / "second.json"
            subprocess.run([*command, "--output", str(first), "--summary", str(first_summary)], cwd=ROOT, check=True, capture_output=True, text=True)
            subprocess.run([*command, "--output", str(second), "--summary", str(second_summary)], cwd=ROOT, check=True, capture_output=True, text=True)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            self.assertEqual(first_summary.read_bytes(), second_summary.read_bytes())
            summary = json.loads(first_summary.read_text(encoding="utf-8"))
        self.assertEqual(summary["template_record_count"], 700)
        self.assertEqual(summary["candidate_linked_count"], 579)
        self.assertEqual(summary["independent_evidence_count"], 0)
        self.assertEqual(summary["canonical_writes"], 0)
        self.assertEqual(summary["source_independence"], "not_independent_same_fandom_wiki")
        self.assertEqual(summary["canonical_promotion"], "not_performed")
        rows = read_jsonl(REVIEW / "fandom-seasonal-cosmetics-r107991-crosswalk.jsonl")
        self.assertEqual(len(rows), 700)
        self.assertTrue(all(row["source_independence"] == "not_independent_same_fandom_wiki" for row in rows))
        self.assertTrue(all(row["promotion_effect"] == "none" for row in rows))
        self.assertTrue(all(row["season_ids"] for row in rows))

    def test_metadata_tampering_cannot_turn_the_source_into_independent_evidence(self):
        snapshot = json.loads((VENDOR / "fandom-seasonal-cosmetics-r107991-snapshot.json").read_text(encoding="utf-8"))
        metadata = json.loads((VENDOR / "fandom-seasonal-cosmetics-r107991-metadata.json").read_text(encoding="utf-8"))
        tampered = deepcopy(metadata)
        tampered["independence_status"] = "independent"
        with self.assertRaisesRegex(ValueError, "non-independent"):
            verify_snapshot(snapshot, tampered, VENDOR / "fandom-seasonal-cosmetics-r107991-snapshot.json")
        tampered = deepcopy(metadata)
        tampered["canonical_promotion"] = "allowed"
        with self.assertRaisesRegex(ValueError, "non-independent"):
            verify_snapshot(snapshot, tampered, VENDOR / "fandom-seasonal-cosmetics-r107991-snapshot.json")

    def test_ambiguous_season_is_quarantined_and_never_links_a_candidate(self):
        snapshot = {"seasonal_cosmetic_templates": [{"source_item_key": "Example|Guide|cape|1", "source_locator": "revision:107991:season:Example:template:1", "season_label": "Example", "template_subject": "Guide", "template_slot": "cape", "ordinal_in_season": 1}]}
        metadata = {"snapshot_sha256": "A" * 64}
        seasons = [
            {"season_id": "season_one", "canonical_name_en": "Season of Example", "aliases": []},
            {"season_id": "season_two", "canonical_name_en": "Example", "aliases": []},
        ]
        candidates = [{"candidate_item_id": "item_example_guide_cape", "candidate_name_en": "Guide cape", "season_id": "season_one"}]
        rows, summary = crosswalk(snapshot, metadata, seasons, candidates)
        self.assertEqual(rows[0]["match_status"], "ambiguous_season")
        self.assertEqual(rows[0]["candidate_item_ids"], [])
        self.assertEqual(rows[0]["promotion_effect"], "none")
        self.assertEqual(summary["canonical_writes"], 0)

    def test_all_committed_records_conform_to_their_new_schemas(self):
        validator = OfflineSchemaValidator(ROOT / "schemas")
        sources = [
            (VENDOR / "fandom-seasonal-cosmetics-r107991-snapshot.json", ROOT / "schemas/review/fandom-seasonal-cosmetics-snapshot.schema.json"),
            (VENDOR / "fandom-seasonal-cosmetics-r107991-metadata.json", ROOT / "schemas/review/fandom-seasonal-cosmetics-metadata.schema.json"),
        ]
        for payload, schema in sources:
            self.assertEqual(validator.validate(json.loads(payload.read_text(encoding="utf-8")), schema), [])
        schema = ROOT / "schemas/review/fandom-seasonal-cosmetics-crosswalk.schema.json"
        for row in read_jsonl(REVIEW / "fandom-seasonal-cosmetics-r107991-crosswalk.jsonl"):
            self.assertEqual(validator.validate(row, schema), [])

    def test_offline_tools_contain_no_network_client_import_or_call(self):
        prohibited = ("requests", "urllib", "http.client", "aiohttp", "httpx", "socket", "webbrowser", "urlopen")
        for path in (ROOT / "tools/normalize/import_fandom_seasonal_cosmetics_snapshot.py", ROOT / "tools/normalize/import_fandom_seasonal_cosmetics_crosswalk.py"):
            source = path.read_text(encoding="utf-8").casefold()
            self.assertTrue(all(token not in source for token in prohibited), path.name)


if __name__ == "__main__":
    unittest.main()
