from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def read_jsonl(relative: str):
    path = ROOT / relative
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class PackageIntegrityTests(unittest.TestCase):
    def test_canonical_alias_cases(self):
        aliases = read_jsonl("knowledge/aliases/item-aliases.jsonl")
        targets = {}
        for row in aliases:
            targets.setdefault(row["alias_text"], set()).add(row["target_id"])
        self.assertEqual(targets["大耳狗"], targets["耳狗"])
        self.assertEqual(targets["極光"], targets["歐若拉"])
        self.assertEqual(targets["梵谷"], targets["梵高"])
        self.assertNotEqual(targets["歸巢"], targets["築巢"])

    def test_alias_is_unique_within_target_type(self):
        aliases = read_jsonl("knowledge/aliases/item-aliases.jsonl")
        groups = {}
        for row in aliases:
            groups.setdefault((row["target_type"], row["normalized_alias"]), set()).add(row["target_id"])
        self.assertFalse({key: value for key, value in groups.items() if len(value) > 1})

    def test_date_verified_always_has_date(self):
        for relative in (
            "data/source/listings.jsonl", "data/normalized/listings.jsonl",
            "data/curated/histories.jsonl", "data/comparables/histories.jsonl",
        ):
            for row in read_jsonl(relative):
                if row.get("date_verified") is True:
                    self.assertTrue(row.get("post_date"), relative)

    def test_no_verified_sale_was_fabricated(self):
        histories = read_jsonl("data/curated/histories.jsonl")
        self.assertEqual(sum(row["sale_outcome"]["verified"] is True for row in histories), 0)

    def test_joined_comparables_match_canonical_inputs(self):
        histories = {row["history_id"]: row for row in read_jsonl("data/curated/histories.jsonl")}
        profiles = {row["account_id"]: row for row in read_jsonl("data/normalized/account-profiles.jsonl")}
        accounts = read_jsonl("data/comparables/accounts.jsonl")
        self.assertEqual(len(accounts), 102)
        self.assertEqual({row["history_id"] for row in accounts}, set(histories))
        for row in accounts:
            history = histories[row["history_id"]]
            self.assertEqual(row["account_id"], history["account_id"])
            self.assertIn(row["account_id"], profiles)
            self.assertEqual(row["selected_price_twd"], history["selected_price_twd"])
            self.assertEqual(row["season_profiles"], profiles[row["account_id"]]["season_profiles"])

    def test_tools_have_no_network_imports(self):
        forbidden = {"requests", "socket", "http.client", "urllib.request", "aiohttp", "httpx"}
        for path in (ROOT / "tools").rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module)
            self.assertFalse(imported & forbidden, f"{path}: {imported & forbidden}")


if __name__ == "__main__":
    unittest.main()
