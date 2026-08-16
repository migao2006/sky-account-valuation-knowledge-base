import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("migration_validation", ROOT / "tools/migrate/validate_migration.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
MIGRATE_SPEC = importlib.util.spec_from_file_location("p0_migration", ROOT / "tools/migrate/migrate_v24_to_p0.py")
MIGRATE = importlib.util.module_from_spec(MIGRATE_SPEC)
MIGRATE_SPEC.loader.exec_module(MIGRATE)


class MigrationContractTests(unittest.TestCase):
    def test_snapshot_counts_dates_and_privacy(self):
        result = MODULE.validate(ROOT)
        self.assertTrue(result["valid"], result)
        self.assertEqual(5, result["verified_history_dates"])
        self.assertEqual([], result["forbidden_identity_keys"])

    def test_season_range_is_conservative_and_tracks_gaps(self):
        aliases = {"表演": "season_performance", "破曉": "season_shattering", "極光": "season_aurora", "狂歡": "season_carnival", "預言": "season_prophecy"}
        order = {"season_prophecy": 0, "season_performance": 1, "season_shattering": 2, "season_aurora": 3, "season_carnival": 4}
        profiles, unresolved = MIGRATE.season_profile("表演～狂歡無斷，缺破曉；預言季卡", aliases, order)
        by_id = {row["season_id"]: row for row in profiles}
        self.assertEqual(unresolved, [])
        self.assertEqual(by_id["season_shattering"]["status"], "confirmed_missing")
        self.assertEqual(by_id["season_aurora"]["status"], "owned_not_complete")
        self.assertEqual(by_id["season_prophecy"]["pass_owned"], "yes")
        summary = MIGRATE.season_summary(profiles, order)
        self.assertEqual(summary["earliest_season_id"], "season_prophecy")
        self.assertEqual(summary["gap_segments"][0]["season_ids"], ["season_shattering"])

    def test_plain_range_keeps_middle_seasons_unknown(self):
        aliases = {"表演": "season_performance", "狂歡": "season_carnival"}
        order = {"season_performance": 1, "season_middle_a": 2, "season_middle_b": 3, "season_carnival": 4}
        profiles, _ = MIGRATE.season_profile("表演～狂歡", aliases, order)
        by_id = {row["season_id"]: row for row in profiles}
        self.assertEqual(by_id["season_middle_a"]["status"], "unknown")
        self.assertEqual(by_id["season_middle_b"]["status"], "unknown")

    def test_cjk_phrase_matching_does_not_depend_on_word_boundaries(self):
        self.assertTrue(MIGRATE.mentioned_without_negation("含TGC斗篷與白蠟", "TGC"))
        self.assertFalse(MIGRATE.mentioned_without_negation("不含TGC斗篷", "TGC"))

    def test_sold_claim_never_becomes_verified_sale(self):
        histories = [json.loads(line) for line in (ROOT / "data/curated/histories.jsonl").read_text(encoding="utf-8").splitlines() if line]
        claimed = [row for row in histories if row["sale_outcome"]["status"] == "sold_claimed"]
        self.assertGreater(len(claimed), 0)
        self.assertTrue(all(not row["sale_outcome"]["verified"] and row["sale_outcome"]["completed_sale_price_twd"] is None for row in claimed))


if __name__ == "__main__":
    unittest.main()
