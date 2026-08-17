"""Regression coverage for the exact-English model-observation boundary."""
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.modeling.canonical_english_eligibility import APPROVED_ITEM_IDS, evaluate
from tools.modeling.catalog_provenance import CatalogProvenanceError, validate_vector_catalog_provenance
from tools.modeling.parse_item_vectors import build_vector, load_catalog
from tools.validate.canonical_evidence_registry import validate_registry
from tools.validate.schema_validator import OfflineSchemaValidator
from tools.normalize.apply_days_of_color_faq1323_core_three_cohort import verify as verify_days_of_color

ROOT = Path(__file__).resolve().parents[2]


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class CanonicalExactEnglishEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.items = {row["item_id"]: row for row in rows(ROOT / "knowledge/items/items.jsonl")}
        sets = {row["set_id"]: row for row in rows(ROOT / "knowledge/sets/item-sets.jsonl")}
        sources = {row["source_id"]: row for row in rows(ROOT / "knowledge/sources/sources.jsonl")}
        problems, groups = validate_registry(ROOT, self.items, sets, sources)
        # During migration the live catalog may temporarily carry the old
        # replay target.  The active ledgers remain the authority audited
        # below; release validation itself requires this list to be empty.
        self.groups = list(groups.items())

    def _eligible_catalog(self):
        temporary = tempfile.TemporaryDirectory(prefix="sky-exact-english-", dir=ROOT.parent)
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        for relative in ("knowledge/items/items.jsonl", "knowledge/aliases/item-aliases.jsonl", "knowledge/sets/item-sets.jsonl"):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        item_path = root / "knowledge/items/items.jsonl"
        edited = rows(item_path)
        for row in edited:
            if row["item_id"] in APPROVED_ITEM_IDS:
                row["model_feature_status"] = "eligible"
        item_path.write_text("".join(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n" for row in edited), encoding="utf-8", newline="\n")
        return root, *load_catalog(root)

    def _profile(self):
        return {"account_id": "account_exact_english", "source_listing_ids": ["listing_exact_english"], "season_profiles": [], "collection": {"owned_item_ids": [], "graduation_rewards": [], "collaboration_items": [], "bundle_item_ids": [], "event_limited_item_ids": [], "graduation_reward_season_ids": []}, "resources": {"values": {}, "evidence_state": "unknown"}, "map_completion": {"evidence_state": "unknown"}, "base_account": {}, "bindings": {}, "ownership_history": "unknown"}

    def test_only_replayed_exact_english_titles_are_approved(self):
        decisions = evaluate(self.items, self.groups)
        validator = OfflineSchemaValidator(ROOT / "schemas")
        self.assertEqual({row["item_id"] for row in decisions if row["decision"] == "eligible"}, APPROVED_ITEM_IDS)
        for row in decisions:
            self.assertEqual(validator.validate(row, ROOT / "schemas/review/canonical-exact-english-eligibility.schema.json"), [])
            self.assertEqual(row["reasons"], [])
            self.assertEqual(row["approved_observation_token"], self.items[row["item_id"]]["canonical_name_en"])

    def test_tampered_secondary_or_title_is_excluded(self):
        altered = [(cohort, [dict(row) for row in ledger]) for cohort, ledger in self.groups]
        target = "item_aurora_wings"
        for _cohort, ledger in altered:
            for row in ledger:
                if row.get("target_id") == target and row.get("source_tier") == "secondary_reference" and row.get("field_path") in {"canonical_name_en", "vendor_item_name"}:
                    row["claim_value"] = "Different Wings"; break
        decision = next(row for row in evaluate(self.items, altered) if row["item_id"] == target)
        self.assertEqual(decision["decision"], "excluded_pending_verification")
        self.assertIn("secondary_exact_canonical_english_evidence_missing", decision["reasons"])

    def test_exact_english_is_model_known_but_chinese_and_buyer_multi_are_unknown(self):
        root, items, aliases = self._eligible_catalog()
        canonical = items["item_aurora_wings"]["canonical_name_en"]
        chinese = "極光翅膀"
        for text, offer_kind, entity_kind, expected in ((canonical, "seller_listing", "single_account", "owned"), (chinese, "seller_listing", "single_account", "unknown"), (canonical, "buyer_listing", "single_account", "unknown"), (canonical, "seller_listing", "multiple_accounts", "unknown")):
            vector = build_vector(self._profile(), {"listing_text": text, "offer_kind": offer_kind, "entity_kind": entity_kind}, items, aliases, root)
            state = next(row for row in vector["item_states"] if row["item_id"] == "item_aurora_wings")
            self.assertEqual(state["state"], expected, (text, offer_kind, entity_kind))
            self.assertEqual(state["model_feature"], expected == "owned")

    def test_stale_catalog_provenance_is_rejected(self):
        root, items, aliases = self._eligible_catalog()
        vector = build_vector(self._profile(), {"listing_text": "Wings of AURORA", "offer_kind": "seller_listing", "entity_kind": "single_account"}, items, aliases, root)
        with self.assertRaisesRegex(CatalogProvenanceError, "stale_catalog_provenance"):
            validate_vector_catalog_provenance(vector, ROOT)

    def test_cohort_replay_composes_with_later_sunlight_items(self):
        """A later cohort must not invalidate an earlier cohort's item contract."""
        with tempfile.TemporaryDirectory(prefix="sky-cohort-composition-") as temporary:
            root = Path(temporary) / "repo"
            for relative in ("knowledge", "data"):
                shutil.copytree(ROOT / relative, root / relative)
            for script in (
                "tools/normalize/apply_days_of_color_faq1323_core_three_cohort.py",
                "tools/normalize/apply_days_of_sunlight_faq1343_core_three_cohort.py",
            ):
                result = subprocess.run([sys.executable, str(ROOT / script), "--root", str(root), "--apply"], capture_output=True, text=True, cwd=ROOT)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(verify_days_of_color(root), [])


if __name__ == "__main__":
    unittest.main()
