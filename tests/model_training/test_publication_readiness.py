from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "modeling"))
from publication_readiness import audit, build  # noqa: E402


def clean(n: int, day: int, cluster: str | None = None) -> dict:
    return {
        "account_id": f"account_{n:04d}", "cluster_id": cluster or f"cluster_{n:04d}",
        "currency": "TWD", "server": "international", "price_line": "normal_listing",
        "post_date": f"2025-01-{day:02d}", "date_verified": True,
        "observed_at": f"2025-01-{day:02d}",
    }


def vectors(rows: list[dict]) -> list[dict]:
    return [{"account_id": row["account_id"]} for row in rows]


class PublicationReadinessTests(unittest.TestCase):
    def test_current_formal_inputs_fail_closed_with_explicit_gaps(self):
        report = build(ROOT)
        self.assertEqual(report["status"], "not_ready")
        self.assertFalse(report["artifact_publication_fields_consulted"])
        self.assertFalse(report["trained_models_treated_as_passed"])
        self.assertEqual(report["model_eligible_item_count"], 0)
        self.assertEqual(report["verified_completed_sale_count"], 0)
        self.assertIn("no_model_eligible_catalog_items", report["blocking_reasons"])
        self.assertIn("no_verified_completed_sales", report["blocking_reasons"])
        # The fixture deliberately fails closed whether current clean lines are
        # present or have been invalidated by a newer catalog provenance.
        for pool in report["market_pools"]:
            self.assertFalse(pool["time_forward_split"]["available"])

    def test_sufficient_distinct_clusters_and_dates_count_a_strict_split(self):
        rows = [clean(n, 1 if n <= 300 else 2) for n in range(1, 401)]
        report = audit(rows, vectors(rows), [{"verification_status": "verified", "model_feature_status": "eligible"}], [{"sale_outcome": {"verified": True}}])
        pool = report["market_pools"][0]
        self.assertTrue(pool["time_forward_split"]["available"])
        self.assertEqual(pool["time_forward_split"]["training_clusters"], 300)
        self.assertEqual(pool["time_forward_split"]["holdout_clusters"], 100)
        self.assertEqual(pool["training_cluster_gap"], 0)
        self.assertEqual(pool["holdout_cluster_gap"], 0)
        self.assertEqual(pool["verified_date_count"], 2)

    def test_cluster_with_dates_on_both_sides_is_never_split(self):
        rows = [clean(n, 1 if n <= 300 else 2) for n in range(1, 400)]
        # A later observation of an existing cluster must not leak into the
        # holdout; changing only the account would evade that guard, so retain
        # the exact same account/cluster identity.
        rows.append({**clean(1, 2, "cluster_0001"), "account_id": "account_0001"})
        report = audit(rows, vectors(rows), [], [])
        pool = report["market_pools"][0]
        self.assertFalse(pool["time_forward_split"]["available"])
        self.assertFalse(pool["time_forward_split"]["cluster_overlap"])
        self.assertGreaterEqual(pool["time_forward_split"]["excluded_spanning_clusters"], 1)
        self.assertIn("time_forward_holdout_clusters_insufficient", pool["blocking_reasons"])

    def test_observed_at_only_is_not_a_verified_event_date_or_split(self):
        rows = [clean(n, 1 if n <= 300 else 2) for n in range(1, 401)]
        for row in rows:
            row["post_date"] = None
        report = audit(rows, vectors(rows), [], [])
        pool = report["market_pools"][0]
        self.assertEqual(pool["dated_cluster_count"], 0)
        self.assertEqual(pool["verified_date_count"], 0)
        self.assertFalse(pool["time_forward_split"]["available"])
        self.assertIn("clusters_missing_verified_dates", pool["blocking_reasons"])

    def test_post_date_without_date_verification_cannot_form_a_split(self):
        rows = [clean(n, 1 if n <= 300 else 2) for n in range(1, 401)]
        for row in rows:
            row["date_verified"] = False
        report = audit(rows, vectors(rows), [], [])
        pool = report["market_pools"][0]
        self.assertEqual(pool["dated_cluster_count"], 0)
        self.assertFalse(pool["time_forward_split"]["available"])


if __name__ == "__main__":
    unittest.main()
