"""Tests for the P2.9 lexical catalog review sidecar."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tools.classify.build_account_catalog_resolution import (  # noqa: E402
    MATCHER_VERSION, build_account_catalog_resolution, read_jsonl, sha256_bytes,
)


def account(account_id: str, listing_id: str = "listing_0001") -> dict:
    return {"account_id": account_id, "source_listing_ids": [listing_id], "trade_conditions": {"offer_kind": "seller_listing", "entity_kind": "single_account"}}


def listing(text: str, *, summary: list[str] | None = None, offer_kind: str = "seller_listing", entity_kind: str = "single_account") -> dict:
    return {"listing_id": "listing_0001", "listing_text": text, "feature_summary": summary or ["ignored in v1"], "offer_kind": offer_kind, "entity_kind": entity_kind}


def index(entity_id: str, key: str, *, ambiguous: list[str] | None = None) -> dict:
    return {"query_entity_id": entity_id, "query_entity_type": "canonical_item", "truth_level": "canonical_knowledge", "verification_status": "verified", "review_status": "approved", "lookup_keys": [key], "ambiguous_lookup_keys": ambiguous or []}


class AccountCatalogResolutionTests(unittest.TestCase):
    def test_cjk_only_longest_leftmost_and_collision_are_review_only(self):
        rows = build_account_catalog_resolution(
            [account("account_0001")], [listing("售：星光羽翼，星光斗篷，沒有月光斗篷；ABC")],
            [index("item_star", "星光羽翼"), index("item_star_cape", "星光斗篷"), index("item_moon", "月光斗篷"), index("item_collision", "星光斗篷", ambiguous=["星光斗篷"]), index("item_english", "ABC")],
            index_sha256="A" * 64,
        )
        row = rows[0]
        self.assertEqual(row["matcher_version"], MATCHER_VERSION)
        # The collision removes 星光斗篷 for all owners.  The shorter 星光 still
        # remains as a distinct non-colliding review-only token.
        self.assertEqual([match["query_entity_id"] for match in row["matches"]], ["item_moon", "item_star"])
        self.assertEqual(row["matches"][0]["assertion"], "negative")
        self.assertTrue(row["review_only"])
        self.assertFalse(row["model_feature"])
        self.assertTrue(all(match["review_only"] and not match["model_feature"] for match in row["matches"]))
        self.assertNotIn("item_english", {match["query_entity_id"] for match in row["matches"]})

    def test_feature_summary_is_scanned_but_not_persisted(self):
        row = build_account_catalog_resolution([account("account_0001")], [listing("售帳", summary=["月光斗篷"])], [index("item_moon", "月光斗篷")], index_sha256="C" * 64)[0]
        self.assertEqual(row["matches"][0]["query_entity_id"], "item_moon")
        self.assertNotIn("feature_summary", row)

    def test_positive_negative_conflict_and_three_negative_forms_remain_review_only(self):
        source = [index("item_moon", "月光斗篷")]
        for text in ("無月光斗篷", "缺月光斗篷", "不含月光斗篷"):
            with self.subTest(text=text):
                row = build_account_catalog_resolution([account("account_0001")], [listing(text)], source, index_sha256="B" * 64)[0]
                self.assertEqual(row["matches"][0]["assertion"], "negative")
                self.assertTrue(row["matches"][0]["review_only"])
        row = build_account_catalog_resolution([account("account_0001")], [listing("月光斗篷，無月光斗篷")], source, index_sha256="B" * 64)[0]
        self.assertEqual(row["matches"][0]["assertion"], "conflict")

    def test_real_build_is_deterministic_suppresses_ineligible_and_account_1022_has_no_ownership_output(self):
        command = [sys.executable, "tools/classify/build_account_catalog_resolution.py", "--root", str(ROOT)]
        with tempfile.TemporaryDirectory() as temporary:
            first = Path(temporary) / "one.jsonl"; second = Path(temporary) / "two.jsonl"
            subprocess.run([*command, "--output", str(first)], cwd=ROOT, check=True, capture_output=True, text=True)
            subprocess.run([*command, "--output", str(second)], cwd=ROOT, check=True, capture_output=True, text=True)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            rows = read_jsonl(first)
        self.assertEqual(len(rows), len(read_jsonl(ROOT / "data/normalized/account-profiles.jsonl")))
        target = next(row for row in rows if row["account_id"] == "account_1022")
        self.assertEqual(target["matches"], [])
        forbidden = {"ownership_state", "resolved_item_id", "state", "raw", "listing_text", "alias", "span", "url", "source_url"}
        def keys(value):
            if isinstance(value, dict): return set(value) | set().union(*(keys(child) for child in value.values())) if value else set()
            if isinstance(value, list): return set().union(*(keys(child) for child in value)) if value else set()
            return set()
        self.assertFalse(forbidden & set().union(*(keys(row) for row in rows)))
        self.assertTrue(all(not row["matches"] for row in rows if row["matching_eligibility"] != "eligible"))
        index_hash = sha256_bytes((ROOT / "data/normalized/catalog-query-index.jsonl").read_bytes())
        self.assertTrue(all(row["catalog_query_index_sha256"] == index_hash for row in rows))


if __name__ == "__main__":
    unittest.main()
