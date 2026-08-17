from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "modeling"))
from publication_dataset import PublicationDatasetError, freeze, split  # noqa: E402

PROVENANCE = {"pinned_catalog_sha256": "A" * 64}
SNAPSHOTS = [{"path": "x", "sha256": "B" * 64}]


def row(n: int, day: str = "2025-01-01", line: str = "normal_listing", cluster: str | None = None) -> dict:
    return {"cleaned_price_id": f"cleaned_price_{n}", "history_id": f"history_{n}", "account_id": f"account_{n}", "cluster_id": cluster or f"cluster_{n}", "currency": "TWD", "server": "international", "price_line": line, "selected_price_twd": 1000, "post_date": day, "date_verified": True}


def vectors(rows: list[dict]) -> list[dict]:
    return [{"account_id": account, "catalog_provenance": PROVENANCE} for account in sorted({item["account_id"] for item in rows})]


def signed_sha(value: object) -> str:
    return hashlib.sha256((json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()).hexdigest().upper()


def signed_row(sample: dict, vector: dict) -> dict:
    return {**sample, "training_example_id": "training_example_fixture_0001", "training_example_digest": "A" * 64,
        "feature_payload_sha256": signed_sha(vector), "catalog_provenance_sha256": signed_sha(vector["catalog_provenance"]),
        "dedup_cluster_digest": signed_sha(sample["cluster_id"])}


class PublicationDatasetTests(unittest.TestCase):
    def test_empty_dataset_is_stable_and_not_ready(self):
        first = freeze([], [], PROVENANCE, SNAPSHOTS)
        self.assertEqual(first, freeze([], [], PROVENANCE, SNAPSHOTS))
        self.assertEqual(first["status"], "not_ready")
        self.assertEqual(first["dataset_row_count"], 0)
        self.assertEqual(split(first)["market_pools"], [])

    def test_row_hash_dataset_hash_and_time_split_are_deterministic(self):
        rows = [row(n, "2025-01-01" if n <= 300 else "2025-01-02") for n in range(1, 401)]
        manifest = freeze(list(reversed(rows)), vectors(rows), PROVENANCE, SNAPSHOTS)
        report = split(manifest)
        self.assertEqual(manifest["status"], "not_ready")
        self.assertEqual(manifest["dataset_row_count"], 400)
        self.assertTrue(all(item["row_sha256"] for item in manifest["dataset_rows"]))
        pool = report["market_pools"][0]
        self.assertEqual(pool["cut_date"], "2025-01-02")
        self.assertEqual((len(pool["training_cluster_ids"]), len(pool["holdout_cluster_ids"])), (300, 100))
        self.assertTrue(pool["requirements_met"])
        self.assertEqual(report["status"], "ready_for_evaluation")

    def test_rejects_tamper_duplicate_mixed_pool_unverified_date_and_stale_vector(self):
        sample = row(1)
        for changed, reason in [({"date_verified": False}, "date_not_verified"), ({"currency": "USD"}, "mixed_or_nonformal_market_pool"), ({"cleaned_price_id": ""}, "missing_cleaned_price_id")]:
            with self.subTest(reason=reason), self.assertRaisesRegex(PublicationDatasetError, reason):
                freeze([{**sample, **changed}], vectors([sample]), PROVENANCE, SNAPSHOTS)
        with self.assertRaisesRegex(PublicationDatasetError, "duplicate_clean_price_or_history_id"):
            freeze([sample, sample.copy()], vectors([sample]), PROVENANCE, SNAPSHOTS)
        with self.assertRaisesRegex(PublicationDatasetError, "stale_or_forged_catalog_provenance"):
            freeze([sample], [{"account_id": sample["account_id"], "catalog_provenance": {}}], PROVENANCE, SNAPSHOTS)

    def test_tampered_row_and_cluster_account_overlap_fail_closed(self):
        sample = row(1)
        manifest = freeze([sample], vectors([sample]), PROVENANCE, SNAPSHOTS)
        manifest["dataset_rows"][0]["selected_price_twd"] = 999
        with self.assertRaisesRegex(PublicationDatasetError, "dataset_manifest_hash_mismatch"):
            split(manifest)
        first, second = row(1, "2025-01-01", cluster="cluster_same"), row(2, "2025-01-02", cluster="cluster_same")
        manifest = freeze([first, second], vectors([first, second]), PROVENANCE, SNAPSHOTS)
        with self.assertRaisesRegex(PublicationDatasetError, "cluster_maps_to_multiple_accounts"):
            split(manifest)

    def test_spanning_cluster_is_excluded_not_split(self):
        rows = [row(n, "2025-01-01" if n <= 300 else "2025-01-02") for n in range(1, 401)]
        rows.append({**row(401, "2025-01-02", cluster="cluster_1"), "account_id": "account_1"})
        pool = split(freeze(rows, vectors(rows), PROVENANCE, SNAPSHOTS))["market_pools"][0]
        self.assertIn("cluster_1", pool["excluded_spanning_cluster_ids"])
        self.assertFalse(pool["cluster_overlap"])
        self.assertFalse(pool["requirements_met"])

    def test_signed_feature_payload_must_be_exact_matching_vector(self):
        sample=row(1, cluster="cluster_signed_not_account_derived")
        vector=vectors([sample])[0]
        signed=signed_row(sample, vector)
        manifest=freeze([signed], [vector], PROVENANCE, SNAPSHOTS)
        self.assertEqual("cluster_signed_not_account_derived", manifest["dataset_rows"][0]["cluster_id"])
        forged={**vector, "feature_groups": {"tampered": True}}
        with self.assertRaisesRegex(PublicationDatasetError, "signed_feature_payload_vector_mismatch"):
            freeze([signed], [forged], PROVENANCE, SNAPSHOTS)


if __name__ == "__main__":
    unittest.main()
