from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "modeling"))
from publication_dataset import PublicationDatasetError, freeze, freeze_synthetic_for_test, split, split_synthetic_for_test  # noqa: E402

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


def training_example(signed: dict) -> dict:
    feature_payload = {"account_id": signed["account_id"], "catalog_provenance": PROVENANCE}
    return {
        "training_example_id": signed["training_example_id"],
        "training_example_digest": signed["training_example_digest"],
        "feature_payload_sha256": signed["feature_payload_sha256"],
        "catalog_provenance_sha256": signed["catalog_provenance_sha256"],
        "dedup_cluster_digest": signed["dedup_cluster_digest"],
        "account_id": signed["account_id"],
        "dedup_cluster_id": signed["cluster_id"],
        "feature_payload": feature_payload,
        "catalog_provenance": PROVENANCE,
        "_registered_observation": {
            "observation_id": "observation_fixture_0001", "price_twd": signed["selected_price_twd"],
            "post_date": signed["post_date"], "price_line": "asking",
        },
    }


class PublicationDatasetTests(unittest.TestCase):
    def test_empty_dataset_is_stable_and_not_ready(self):
        first = freeze([], [], PROVENANCE, SNAPSHOTS)
        self.assertEqual(first, freeze([], [], PROVENANCE, SNAPSHOTS))
        self.assertEqual(first["status"], "not_ready")
        self.assertEqual(first["dataset_row_count"], 0)
        self.assertEqual(split_synthetic_for_test(first)["market_pools"], [])

    def test_row_hash_dataset_hash_and_time_split_are_deterministic(self):
        rows = [row(n, "2025-01-01" if n <= 300 else "2025-01-02") for n in range(1, 401)]
        manifest = freeze_synthetic_for_test(list(reversed(rows)), vectors(rows), PROVENANCE, SNAPSHOTS)
        report = split_synthetic_for_test(manifest)
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
                freeze_synthetic_for_test([{**sample, **changed}], vectors([sample]), PROVENANCE, SNAPSHOTS)
        with self.assertRaisesRegex(PublicationDatasetError, "duplicate_clean_price_or_history_id"):
            freeze_synthetic_for_test([sample, sample.copy()], vectors([sample]), PROVENANCE, SNAPSHOTS)
        with self.assertRaisesRegex(PublicationDatasetError, "stale_or_forged_catalog_provenance"):
            freeze_synthetic_for_test([sample], [{"account_id": sample["account_id"], "catalog_provenance": {}}], PROVENANCE, SNAPSHOTS)

    def test_tampered_row_and_cluster_account_overlap_fail_closed(self):
        sample = row(1)
        manifest = freeze_synthetic_for_test([sample], vectors([sample]), PROVENANCE, SNAPSHOTS)
        manifest["dataset_rows"][0]["selected_price_twd"] = 999
        with self.assertRaisesRegex(PublicationDatasetError, "dataset_manifest_hash_mismatch"):
            split_synthetic_for_test(manifest)
        first, second = row(1, "2025-01-01", cluster="cluster_same"), row(2, "2025-01-02", cluster="cluster_same")
        manifest = freeze_synthetic_for_test([first, second], vectors([first, second]), PROVENANCE, SNAPSHOTS)
        with self.assertRaisesRegex(PublicationDatasetError, "cluster_maps_to_multiple_accounts"):
            split_synthetic_for_test(manifest)

    def test_spanning_cluster_is_excluded_not_split(self):
        rows = [row(n, "2025-01-01" if n <= 300 else "2025-01-02") for n in range(1, 401)]
        rows.append({**row(401, "2025-01-02", cluster="cluster_1"), "account_id": "account_1"})
        pool = split_synthetic_for_test(freeze_synthetic_for_test(rows, vectors(rows), PROVENANCE, SNAPSHOTS))["market_pools"][0]
        self.assertIn("cluster_1", pool["excluded_spanning_cluster_ids"])
        self.assertFalse(pool["cluster_overlap"])
        self.assertFalse(pool["requirements_met"])

    def test_signed_feature_payload_is_loaded_from_registered_external_example(self):
        sample=row(1, cluster="cluster_signed_not_account_derived")
        vector=vectors([sample])[0]
        signed=signed_row(sample, vector)
        manifest=freeze([signed], [], PROVENANCE, SNAPSHOTS, [training_example(signed)])
        self.assertEqual("cluster_signed_not_account_derived", manifest["dataset_rows"][0]["cluster_id"])
        self.assertEqual(vector, manifest["dataset_rows"][0]["feature_payload"])
        forged_example = training_example(signed)
        forged_example["feature_payload"] = {**vector, "feature_groups": {"tampered": True}}
        with self.assertRaisesRegex(PublicationDatasetError, "signed_feature_payload_vector_mismatch"):
            freeze([signed], [], PROVENANCE, SNAPSHOTS, [forged_example])

    def test_frozen_signed_feature_payload_cannot_be_swapped_and_rehashed(self):
        sample = row(1, cluster="cluster_signed_feature_replay")
        vector = vectors([sample])[0]
        signed = signed_row(sample, vector)
        manifest = freeze([signed], [], PROVENANCE, SNAPSHOTS, [training_example(signed)])
        manifest["dataset_rows"][0]["feature_payload"] = {**vector, "feature_groups": {"forged": 1}}
        payload = {key: value for key, value in manifest["dataset_rows"][0].items() if key != "row_sha256"}
        manifest["dataset_rows"][0]["row_sha256"] = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest().upper()
        manifest["dataset_sha256"] = hashlib.sha256(json.dumps(manifest["dataset_rows"], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest().upper()
        with self.assertRaisesRegex(PublicationDatasetError, "dataset_feature_payload_hash_mismatch"):
            split_synthetic_for_test(manifest)

    def test_unsigned_400_rows_are_excluded_and_cannot_ready(self):
        rows = [row(n, "2025-01-01" if n <= 300 else "2025-01-02") for n in range(1, 401)]
        manifest = freeze(rows, vectors(rows), PROVENANCE, SNAPSHOTS)
        self.assertEqual(manifest["dataset_row_count"], 0)
        self.assertEqual(manifest["rejected_clean_row_count"], 400)
        self.assertEqual(manifest["rejection_counts"], [{"reason": "unsigned_clean_row", "count": 400}])
        self.assertEqual(manifest["blockers"], [{"code": "unsigned_clean_rows_excluded", "count": 400}])
        self.assertEqual(split_synthetic_for_test(manifest)["status"], "not_ready")

    def test_partial_lineage_is_excluded_with_an_explicit_rejection(self):
        sample = {**row(1), "training_example_id": "training_example_partial"}
        manifest = freeze([sample], vectors([sample]), PROVENANCE, SNAPSHOTS)
        self.assertEqual(manifest["dataset_row_count"], 0)
        self.assertEqual(manifest["rejection_counts"], [{"reason": "incomplete_signed_feature_lineage", "count": 1}])

    def test_signed_commitment_tampering_is_rejected(self):
        sample = row(1, cluster="cluster_signed_not_account_derived")
        vector = vectors([sample])[0]
        signed = signed_row(sample, vector)
        example = training_example(signed)
        with self.assertRaisesRegex(PublicationDatasetError, "signed_training_example_commitment_mismatch"):
            freeze([{**signed, "training_example_digest": "B" * 64}], [], PROVENANCE, SNAPSHOTS, [example])

    def test_direct_production_split_requires_deterministic_root_replay(self):
        manifest = freeze_synthetic_for_test([row(1)], vectors([row(1)]), PROVENANCE, SNAPSHOTS)
        with self.assertRaisesRegex(PublicationDatasetError, "production_split_requires_deterministic_root_replay"):
            split(manifest)


if __name__ == "__main__":
    unittest.main()
