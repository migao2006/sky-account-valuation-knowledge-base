"""Fail-closed coverage for the restricted declarative evidence shadow."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from tools.normalize.apply_days_of_love_faq1374_core_four_cohort import build
from tools.validate.declarative_canonical_evidence import DeclarationError, ledger_bytes, replay
from tools.validate.schema_validator import OfflineSchemaValidator

ROOT = Path(__file__).resolve().parents[2]
DECLARATION = "data/review/shadow/days-of-love-faq1374-core-four.declaration.json"


class DeclarativeCanonicalEvidenceShadowTests(unittest.TestCase):
    def copied_root(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name) / "repo"
        for relative in ("data", "knowledge", "schemas"):
            shutil.copytree(ROOT / relative, root / relative)
        return root

    @staticmethod
    def declaration(root: Path) -> tuple[Path, dict]:
        path = root / DECLARATION
        return path, json.loads(path.read_text(encoding="utf-8"))

    def mutate(self, root: Path, change) -> None:
        path, value = self.declaration(root)
        change(value)
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    def test_days_of_love_shadow_is_semantic_and_byte_parity_with_existing_verifier(self):
        _targets, expected = build(ROOT)
        actual = replay(ROOT, DECLARATION)
        self.assertEqual(actual, expected)
        self.assertEqual(ledger_bytes(actual), ledger_bytes(expected))
        validator = OfflineSchemaValidator(ROOT / "schemas")
        self.assertFalse(validator.validate(json.loads((ROOT / DECLARATION).read_text(encoding="utf-8")), ROOT / "schemas/review/canonical-evidence-declaration.schema.json"))

    def test_path_hash_locator_source_target_tier_and_duplicate_fail_closed(self):
        cases = (
            ("path", lambda value: value["sources"]["official"].update(path="data/source/../research/tgc-faq-1374-days-of-love-core-four.json")),
            ("hash", lambda value: value["sources"]["official"].update(sha256="0" * 64)),
            ("locator", lambda value: value["rules"][0].update(claim_locator="/facts/missing")),
            ("source", lambda value: value["rules"][0].update(source_key="unregistered")),
            ("target", lambda value: value["rules"][0].update(target_id=17)),
            ("tier", lambda value: value["sources"]["official"].update(source_tier="untrusted")),
            ("duplicate", lambda value: value["rules"].append(dict(value["rules"][0]))),
        )
        for name, change in cases:
            with self.subTest(name=name):
                root = self.copied_root()
                self.mutate(root, change)
                with self.assertRaises(DeclarationError):
                    replay(root, DECLARATION)

    def test_exact_source_item_id_and_forbidden_execution_fields_fail_closed(self):
        root = self.copied_root()
        self.mutate(root, lambda value: value["rules"][0].update(source_item_id_exact="other_item"))
        with self.assertRaises(DeclarationError):
            replay(root, DECLARATION)
        root = self.copied_root()
        self.mutate(root, lambda value: value.update(regex=".*"))
        with self.assertRaises(DeclarationError):
            replay(root, DECLARATION)


if __name__ == "__main__":
    unittest.main()
