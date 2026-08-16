import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("build_comparables", ROOT / "tools/normalize/build_comparables.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StrictListingRecoveryTests(unittest.TestCase):
    def test_formal_recovery_is_one_strict_listing_and_preserves_legacy_rows(self):
        all_histories = MODULE.read_jsonl(ROOT / "data/curated/histories.jsonl")
        legacy = [row for row in all_histories if "recovery" not in row]
        profiles = {row["account_id"]: row for row in MODULE.read_jsonl(ROOT / "data/normalized/account-profiles.jsonl")}
        recovered = MODULE.recover_histories(ROOT, all_histories, profiles)
        self.assertEqual(len(legacy), 102)
        self.assertEqual([row for row in recovered if "recovery" not in row], legacy)
        additions = [row for row in recovered if "recovery" in row]
        self.assertEqual([row["history_id"] for row in additions], ["history_recovered_0792"])
        row = additions[0]
        self.assertEqual(row["source_listing_ids"], ["listing_0792"])
        self.assertEqual(row["market_pool"], "strict_recovered_normal_listing")
        self.assertEqual(row["price_type"], "normal_listing")
        self.assertFalse(row["date_verified"])
        self.assertFalse(row["sale_outcome"]["verified"])
        self.assertEqual(row["recovery"]["legacy_history_match"], "none")
        self.assertNotIn("listing_0864", {source for history in recovered for source in history["source_listing_ids"]})

    def test_strict_predicate_fails_closed_for_unknown_transaction(self):
        listing = {
            "listing_id": "listing_test", "offer_kind": "unknown", "entity_kind": "unknown",
            "currency": "TWD", "currency_verified": True, "server": "international", "server_verified": True,
            "price_type": "asking", "price_twd": 1000, "status": "active", "exclusion_reason": "", "duplicate_cluster_id": None,
        }
        self.assertIsNone(MODULE.strict_recovery_predicates(listing, set()))

    def test_strict_listing_without_approved_decision_is_not_recovered(self):
        strict_listing = next(row for row in MODULE.read_jsonl(ROOT / "data/normalized/listings.jsonl") if row["listing_id"] == "listing_0792")
        predicates = MODULE.strict_recovery_predicates(strict_listing, set())
        self.assertIsNotNone(predicates)
        decision = next(row for row in MODULE.read_jsonl(ROOT / "data/review/strict-listing-recovery.jsonl") if row["listing_id"] == "listing_0792")
        self.assertTrue(MODULE.predicate_hash(strict_listing, predicates, decision["deduplication"]))
        profile = next(row for row in MODULE.read_jsonl(ROOT / "data/normalized/account-profiles.jsonl") if row["account_id"] == "account_0792")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            normalized = root / "data/normalized"; review = root / "data/review"
            normalized.mkdir(parents=True); review.mkdir(parents=True)
            (normalized / "listings.jsonl").write_text(json.dumps(strict_listing) + "\n", encoding="utf-8")
            (review / "strict-listing-recovery.jsonl").write_text("", encoding="utf-8")
            self.assertEqual(MODULE.recover_histories(root, [], {"account_0792": profile}), [])

    def test_review_approval_fails_closed_when_reviewed_fact_changes(self):
        listing = next(row for row in MODULE.read_jsonl(ROOT / "data/normalized/listings.jsonl") if row["listing_id"] == "listing_0792")
        profile = next(row for row in MODULE.read_jsonl(ROOT / "data/normalized/account-profiles.jsonl") if row["account_id"] == "account_0792")
        decision = next(row for row in MODULE.read_jsonl(ROOT / "data/review/strict-listing-recovery.jsonl") if row["listing_id"] == "listing_0792")
        changed = dict(listing); changed["price_twd"] = listing["price_twd"] + 1
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            normalized = root / "data/normalized"; review = root / "data/review"
            normalized.mkdir(parents=True); review.mkdir(parents=True)
            (normalized / "listings.jsonl").write_text(json.dumps(changed) + "\n", encoding="utf-8")
            (review / "strict-listing-recovery.jsonl").write_text(json.dumps(decision) + "\n", encoding="utf-8")
            self.assertEqual(MODULE.recover_histories(root, [], {"account_0792": profile}), [])

    def test_null_duplicate_cluster_without_explicit_dedup_review_is_rejected(self):
        listing = next(row for row in MODULE.read_jsonl(ROOT / "data/normalized/listings.jsonl") if row["listing_id"] == "listing_0792")
        profile = next(row for row in MODULE.read_jsonl(ROOT / "data/normalized/account-profiles.jsonl") if row["account_id"] == "account_0792")
        decision = next(row for row in MODULE.read_jsonl(ROOT / "data/review/strict-listing-recovery.jsonl") if row["listing_id"] == "listing_0792")
        decision = dict(decision); decision.pop("deduplication")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            normalized = root / "data/normalized"; review = root / "data/review"
            normalized.mkdir(parents=True); review.mkdir(parents=True)
            (normalized / "listings.jsonl").write_text(json.dumps(listing) + "\n", encoding="utf-8")
            (review / "strict-listing-recovery.jsonl").write_text(json.dumps(decision) + "\n", encoding="utf-8")
            self.assertEqual(MODULE.recover_histories(root, [], {"account_0792": profile}), [])


if __name__ == "__main__":
    unittest.main()
