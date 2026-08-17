import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.modeling.visual_evidence_coverage import audit, build  # noqa: E402
from tools.validate.schema_validator import OfflineSchemaValidator  # noqa: E402


class VisualEvidenceCoverageTests(unittest.TestCase):
    def setUp(self):
        self.validator = OfflineSchemaValidator(ROOT / "schemas")
        self.visual_schema = ROOT / "schemas/knowledge/visual-reference.schema.json"
        self.report_schema = ROOT / "schemas/reports/visual-evidence-capability.schema.json"

    def test_committed_report_is_schema_valid_and_replayable(self):
        report_path = ROOT / "reports/coverage/visual-evidence-capability.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(self.validator.validate(report, self.report_schema), [])
        self.assertEqual(report, build(ROOT))
        self.assertEqual(report["counts"]["all"]["actual_content_addressed_assets"], 0)
        self.assertEqual(report["counts"]["all"]["approved_detections"], 0)
        self.assertEqual(report["counts"]["all"]["source_description_only_refs"], 10)

    def test_source_description_requires_null_asset_and_no_detection(self):
        source = {
            "visual_reference_id": "visual_fixture",
            "item_id": "item_fixture",
            "reference_mode": "source_description",
            "asset_sha256": None,
            "source_ids": ["source_fixture"],
            "verification_status": "needs_review",
        }
        self.assertEqual(self.validator.validate(source, self.visual_schema), [])
        self.assertTrue(self.validator.validate({**source, "asset_sha256": "a" * 64}, self.visual_schema))
        self.assertTrue(self.validator.validate({**source, "detection_ids": ["detection_fixture"]}, self.visual_schema))

    def test_offline_asset_requires_registry_binding(self):
        offline = {
            "visual_reference_id": "visual_fixture",
            "item_id": "item_fixture",
            "reference_mode": "offline_asset",
            "source_ids": ["source_fixture"],
            "verification_status": "needs_review",
        }
        errors = self.validator.validate(offline, self.visual_schema)
        self.assertTrue(any("asset_sha256" in error for error in errors))
        self.assertTrue(any("asset_registry_id" in error for error in errors))

    def test_asset_registry_schema_is_parseable(self):
        registry = {
            "asset_registry_id": "asset_fixture",
            "asset_sha256": "a" * 64,
            "asset_path": "data/curated/visual-assets/fixture.bin",
            "mime_type": "image/png",
        }
        schema = ROOT / "schemas/evidence/visual-asset-registry.schema.json"
        self.assertTrue(self.validator.validate(registry, schema))
        registry["asset_path"] = "data/curated/visual-assets/fixture.png"
        self.assertEqual(self.validator.validate(registry, schema), [])

    def test_registry_rejects_markdown_and_invalid_png_even_with_matching_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bad_path = root / "data/curated/visual-assets/not-an-image.png"
            bad_path.parent.mkdir(parents=True)
            bad_path.write_text("# this is markdown", encoding="utf-8")
            registry = [{"asset_registry_id": "asset_bad", "asset_sha256": hashlib.sha256(bad_path.read_bytes()).hexdigest(), "asset_path": "data/curated/visual-assets/not-an-image.png", "mime_type": "image/png"}]
            with self.assertRaisesRegex(ValueError, "invalid magic"):
                audit([], [], [], registry, root=root)

    def test_registry_rejects_paths_outside_controlled_asset_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            readme = root / "README.png"
            readme.write_bytes(b"not image")
            registry = [{"asset_registry_id": "asset_readme", "asset_sha256": hashlib.sha256(readme.read_bytes()).hexdigest(), "asset_path": "README.png", "mime_type": "image/png"}]
            with self.assertRaisesRegex(ValueError, "must be under"):
                audit([], [], [], registry, root=root)

    def test_builder_rejects_source_description_detection_claim(self):
        items = [{
            "item_id": "item_fixture",
            "verification_status": "verified",
            "model_feature_status": "eligible",
            "last_verified_at": "2026-08-17",
        }]
        visual = [{
            "visual_reference_id": "visual_fixture",
            "item_id": "item_fixture",
            "reference_mode": "source_description",
            "asset_sha256": None,
            "detection_ids": ["detection_fixture"],
        }]
        with self.assertRaisesRegex(ValueError, "cannot be a detection"):
            audit(items, visual, [], [], root=ROOT)


if __name__ == "__main__":
    unittest.main()
