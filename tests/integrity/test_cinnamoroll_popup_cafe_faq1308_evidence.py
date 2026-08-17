"""Regression coverage for bounded FAQ 1308 Cinnamoroll evidence."""
from __future__ import annotations
import json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from tools.normalize.apply_cinnamoroll_popup_cafe_faq1308_cohort import ITEMS, CinnamorollEvidenceError, build, verify
from tools.modeling.canonical_english_eligibility import declared_model_feature_status
from tools.validate.schema_validator import OfflineSchemaValidator
def rows(p:Path): return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
class CinnamorollFaq1308Tests(unittest.TestCase):
 def test_replays_safe_official_and_vendor_evidence(self):
  self.assertEqual(verify(ROOT),[]); _,ledger=build(ROOT); self.assertGreaterEqual(len(ledger),30)
  schema=OfflineSchemaValidator(ROOT/"schemas"); self.assertTrue(all(not schema.validate(x,ROOT/"schemas/review/canonical-item-field-evidence.schema.json") for x in ledger))
  snapshot=json.loads((ROOT/"data/source/research/tgc-faq-1308-cinnamoroll-popup-cafe.json").read_text(encoding="utf-8")); self.assertFalse(schema.validate(snapshot,ROOT/"schemas/knowledge/cinnamoroll-popup-cafe-faq-1308-fact-snapshot.schema.json"))
  data={x["item_id"]:x for x in rows(ROOT/"knowledge/items/items.jsonl")}
  for iid,*_ in ITEMS: self.assertEqual((data[iid]["availability_status"],data[iid]["permanent_account_item"],data[iid]["first_release_date"],data[iid]["model_feature_status"]),("unknown","unknown",None,declared_model_feature_status(iid)))
  self.assertEqual(data["item_cinnamoroll_mini_companion"]["item_subcategory"],"collaboration_iap")
  self.assertEqual(data["item_cinnamoroll_bowtie"]["item_subcategory"],"collaboration_iap")
  self.assertEqual(data["item_cinnamoroll_cloud_cape"]["item_subcategory"],"collaboration_iap")
  self.assertEqual(data["item_cinnamoroll_plush"]["item_subcategory"],"collaboration_iap")
  self.assertEqual(data["item_cinnamoroll_cozy_teacup_headband"]["item_subcategory"],"collaboration_additional")
  self.assertEqual(data["item_cinnamoroll_cozy_cafe_table"]["item_subcategory"],"collaboration_additional")
  for iid in ("item_cinnamoroll_cozy_teacup_headband","item_cinnamoroll_cozy_cafe_table"):
   self.assertEqual(data[iid]["original_currency"],"event_currency")
   self.assertNotEqual(data[iid]["item_subcategory"],"collaboration_iap")
  self.assertEqual(data["item_cinnamoroll_bowtie"]["original_cost"],"bundle_only"); self.assertEqual(data["item_cinnamoroll_cozy_teacup_headband"]["original_cost"],22)
  self.assertFalse(any(x["field_path"]=="availability_status" for x in ledger))
 def test_source_change_fails_closed_and_apply_is_idempotent(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)/"repo"
   for rel in ("knowledge","data","schemas"): shutil.copytree(ROOT/rel,root/rel)
   cmd=[sys.executable,str(ROOT/"tools/normalize/apply_cinnamoroll_popup_cafe_faq1308_cohort.py"),"--root",str(root),"--apply"]
   subprocess.run(cmd,check=True,capture_output=True,text=True); tracked=[root/"knowledge/items/items.jsonl",root/"knowledge/sets/item-sets.jsonl",root/"knowledge/sources/sources.jsonl",root/"knowledge/acquisition/availability-events.jsonl",root/"data/review/cinnamoroll-popup-cafe-faq1308-canonical-evidence.jsonl"]; before={p:p.read_bytes() for p in tracked}; subprocess.run(cmd,check=True,capture_output=True,text=True); self.assertEqual(before,{p:p.read_bytes() for p in tracked})
   source=root/"data/source/research/tgc-faq-1308-cinnamoroll-popup-cafe.json"; source.write_text(source.read_text(encoding="utf-8").replace("Mini Companion","Changed Companion",1),encoding="utf-8",newline="\n")
   with self.assertRaisesRegex(CinnamorollEvidenceError,"official snapshot hash mismatch"): build(root)
if __name__=="__main__": unittest.main()
