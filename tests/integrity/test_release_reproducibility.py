from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "validate"))
from release_files import HASH_EXCLUSIONS, lf_violations, release_files  # noqa: E402


class ReleaseReproducibilityTests(unittest.TestCase):
    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest().upper()

    @classmethod
    def _checkout_with_fresh_manifest(
        cls, source: Path, destination: Path, package_id: object | None = None
    ) -> None:
        """Create an independent checkout root with a manifest for its actual bytes."""
        shutil.copytree(
            source,
            destination,
            ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "staging"),
        )
        manifest_path = destination / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if package_id is not None:
            manifest["package_id"] = package_id
        manifest["file_hashes"] = {
            path.relative_to(destination).as_posix(): cls._sha256(path)
            for path in release_files(destination)
            if path.relative_to(destination).as_posix() not in HASH_EXCLUSIONS
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

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

    def test_package_is_identical_from_differently_named_checkout_roots(self):
        """The ZIP root comes from package_id, never from the checkout directory."""
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            first = temporary_root / "checkout-from-local-folder"
            second = temporary_root / "github-default-clone-name"
            self._checkout_with_fresh_manifest(ROOT, first)
            self._checkout_with_fresh_manifest(ROOT, second)
            first_zip = temporary_root / "first.zip"
            second_zip = temporary_root / "second.zip"
            for checkout, output in ((first, first_zip), (second, second_zip)):
                subprocess.run(
                    [
                        sys.executable,
                        str(checkout / "tools" / "validate" / "package_offline.py"),
                        "--root",
                        str(checkout),
                        "--output",
                        str(output),
                    ],
                    cwd=checkout,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                package_id = json.loads((checkout / "manifest.json").read_text(encoding="utf-8"))["package_id"]
                with zipfile.ZipFile(output) as archive:
                    self.assertTrue(archive.namelist())
                    self.assertTrue(all(name.startswith(f"{package_id}/") for name in archive.namelist()))
            self.assertEqual(self._sha256(first_zip), self._sha256(second_zip))

    def test_package_rejects_unsafe_manifest_package_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            for index, package_id in enumerate(("..", "../escape", "nested/package", r"nested\\package", "/absolute", "Uppercase", False)):
                with self.subTest(package_id=package_id):
                    checkout = temporary_root / f"checkout-{index}"
                    self._checkout_with_fresh_manifest(ROOT, checkout, package_id=package_id)
                    completed = subprocess.run(
                        [
                            sys.executable,
                            str(checkout / "tools" / "validate" / "package_offline.py"),
                            "--root",
                            str(checkout),
                            "--output",
                            str(temporary_root / f"invalid-{index}.zip"),
                        ],
                        cwd=checkout,
                        check=False,
                        capture_output=True,
                        text=True,
                    )
                    self.assertNotEqual(completed.returncode, 0)
                    self.assertIn("safe single directory name", completed.stderr)


if __name__ == "__main__":
    unittest.main()
