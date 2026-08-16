from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "validate"))
from release_files import HASH_EXCLUSIONS, lf_violations, release_files  # noqa: E402


class ReleaseReproducibilityTests(unittest.TestCase):
    def test_gitattributes_enforces_lf_and_marks_binary_formats(self):
        rules = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("* text=auto eol=lf", rules)
        for suffix in ("*.zip -text", "*.png -text", "*.jpg -text", "*.webp -text"):
            self.assertIn(suffix, rules)

    def test_release_text_bytes_are_lf_only(self):
        self.assertEqual(lf_violations(ROOT), [])

    def test_manifest_has_only_generated_self_reference_exclusions(self):
        manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest["hash_exclusions"]), HASH_EXCLUSIONS)
        expected = {path.relative_to(ROOT).as_posix() for path in release_files(ROOT)}
        declared = set(manifest["file_hashes"]) | set(manifest["hash_exclusions"])
        self.assertEqual(declared, expected)

    def test_release_tools_fail_closed_on_cache_residue_without_creating_bytecode(self):
        release_check = (ROOT / "tools/validate/release_check.py").read_text(encoding="utf-8")
        package = (ROOT / "tools/validate/package_offline.py").read_text(encoding="utf-8")
        self.assertLess(release_check.index("sys.dont_write_bytecode = True"), release_check.index("from validate import validate"))
        self.assertLess(package.index("sys.dont_write_bytecode = True"), package.index("from release_files import"))
        self.assertIn('path.name == "__pycache__" or path.suffix == ".pyc"', release_check)
        self.assertIn('path.name == "__pycache__" or path.suffix == ".pyc"', package)
        self.assertIn('path.name == "staging"', package)


if __name__ == "__main__":
    unittest.main()
