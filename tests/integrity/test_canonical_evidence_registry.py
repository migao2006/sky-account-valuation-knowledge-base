"""Regression coverage for the bounded canonical evidence cohort registry."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "validate"))
from canonical_evidence_registry import load_registry, validate_registry  # noqa: E402
from tools.validate.schema_validator import OfflineSchemaValidator  # noqa: E402


def read(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class CanonicalEvidenceRegistryTests(unittest.TestCase):
    def copied_root(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "repo"
        for relative in ("knowledge", "data", "schemas"):
            shutil.copytree(ROOT / relative, root / relative)
        return root

    @staticmethod
    def context(root: Path):
        return (
            {row["item_id"]: row for row in read(root / "knowledge/items/items.jsonl")},
            {row["set_id"]: row for row in read(root / "knowledge/sets/item-sets.jsonl")},
            {row["source_id"]: row for row in read(root / "knowledge/sources/sources.jsonl")},
        )

    def problems(self, root: Path) -> list[str]:
        return validate_registry(root, *self.context(root))[0]

    def test_existing_cohorts_replay_through_registry(self):
        registry = load_registry(ROOT)
        validator = OfflineSchemaValidator(ROOT / "schemas")
        schema = ROOT / "schemas/review/canonical-evidence-cohort.schema.json"
        self.assertGreaterEqual(len(registry), 1)
        self.assertEqual(len({row["cohort_id"] for row in registry}), len(registry))
        self.assertEqual(len({row["verifier_id"] for row in registry}), len(registry))
        self.assertTrue(all(not validator.validate(row, schema) for row in registry))
        problems, ledgers = validate_registry(ROOT, *self.context(ROOT))
        self.assertEqual(problems, [])
        self.assertEqual(set(ledgers), {row["cohort_id"] for row in registry if row["release_required"]})

    def test_path_escape_and_unknown_verifier_fail_closed(self):
        root = self.copied_root()
        registry_path = root / "data/review/canonical-evidence-cohorts.jsonl"
        registry_path.write_text(
            registry_path.read_text(encoding="utf-8").replace(
                "data/review/nintendo-starter-pack-canonical-evidence.jsonl", "data/review/../escape.jsonl", 1
            ), encoding="utf-8", newline="\n"
        )
        self.assertTrue(any("unsafe evidence_path" in problem for problem in self.problems(root)))
        registry_path.write_text(
            (ROOT / "data/review/canonical-evidence-cohorts.jsonl").read_text(encoding="utf-8").replace(
                '"verifier_id":"nintendo_starter_pack"', '"verifier_id":"untrusted_module"', 1
            ), encoding="utf-8", newline="\n"
        )
        problems = self.problems(root)
        self.assertTrue(any("unknown verifier_id" in problem for problem in problems))
        self.assertTrue(any("verifier is unavailable" in problem for problem in problems))

    def test_target_and_ledger_count_tampering_fail_closed(self):
        root = self.copied_root()
        registry_path = root / "data/review/canonical-evidence-cohorts.jsonl"
        registry_path.write_text(
            registry_path.read_text(encoding="utf-8").replace("item_nintendo_blue_cape", "item_not_canonical", 1),
            encoding="utf-8", newline="\n"
        )
        problems = self.problems(root)
        self.assertTrue(any("item target must be verified and model excluded" in problem for problem in problems))
        self.assertTrue(any("ledger targets differ from registry targets" in problem for problem in problems))
        # A registry never supplies a trusted row count: duplicated ledger rows
        # are rejected from their actual evidence IDs.
        registry_path.write_bytes((ROOT / "data/review/canonical-evidence-cohorts.jsonl").read_bytes())
        ledger = root / "data/review/nintendo-starter-pack-canonical-evidence.jsonl"
        ledger.write_text(ledger.read_text(encoding="utf-8") + ledger.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8", newline="\n")
        self.assertTrue(any("duplicate evidence_id in ledger" in problem for problem in self.problems(root)))

    def test_swapped_or_reused_verifier_cannot_attest_an_unrelated_ledger(self):
        root = self.copied_root()
        registry_path = root / "data/review/canonical-evidence-cohorts.jsonl"
        registry_path.write_text(
            registry_path.read_text(encoding="utf-8").replace(
                '"verifier_id":"nintendo_starter_pack"', '"verifier_id":"moomin_pack"', 1
            ), encoding="utf-8", newline="\n",
        )
        problems = self.problems(root)
        self.assertTrue(any("differs from verifier contract" in problem for problem in problems))
        self.assertTrue(any("duplicate verifier_id" in problem for problem in problems))

        root = self.copied_root()
        ledger_path = root / "data/review/nintendo-starter-pack-canonical-evidence.jsonl"
        ledger_rows = read(ledger_path)
        forged = next(row for row in ledger_rows if row["field_path"] == "identity_description")
        forged["claim_value"] = "fabricated component"
        forged["claim_hash"] = "A" * 64
        forged["claim_locator_hash"] = "B" * 64
        ledger_path.write_text(
            "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in ledger_rows),
            encoding="utf-8", newline="\n",
        )
        self.assertTrue(any("verifier:" in problem for problem in self.problems(root)))


if __name__ == "__main__":
    unittest.main()
