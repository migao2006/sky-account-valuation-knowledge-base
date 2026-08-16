import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "estimate"))
from evidence import validate_evidence


class ImageEvidenceContractTest(unittest.TestCase):
    def test_icon_evidence_accepts_canonical_item_and_bbox(self):
        row = {"case_id":"account_fixture","detection_id":"detection_fixture","image_sha256":"a" * 64,"image_role":"wardrobe","ui_language":"zh_tw","capture_date":"2026-08-16","detected_item_id":"item_example_a","bounding_box":{"x":0.1,"y":0.2,"width":0.3,"height":0.4},"recognition_method":"icon_match","confidence":0.9,"evidence_state":"claimed","conflict":False,"review_status":"needs_review","duplicate_of_image_sha256":None,"wardrobe_coverage":"partial","overlaps_detection_ids":[]}
        self.assertEqual(validate_evidence(row, {"item_example_a"}), [])

    def test_ocr_and_raw_text_are_separate(self):
        row = {"case_id":"account_fixture","image_sha256":"a" * 64,"image_role":"wardrobe","ui_language":"zh_tw","capture_date":None,"detected_item_id":"item_example_a","bounding_box":None,"recognition_method":"ocr_text","confidence":0.5,"evidence_state":"claimed","conflict":False,"review_status":"unknown","ocr_text":"private source text","wardrobe_coverage":"unknown","overlaps_detection_ids":[]}
        errors = validate_evidence(row, {"item_example_a"})
        self.assertIn("prohibited:ocr_text", errors)
        self.assertIn("invalid:ocr_text_cannot_claim_item", errors)


if __name__ == "__main__":
    unittest.main()
