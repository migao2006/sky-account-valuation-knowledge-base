"""Regression tests for bounded FAQ 1356 Days of Mischief core-five."""
from __future__ import annotations
import json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from tools.normalize.apply_days_of_mischief_faq1356_core_five_cohort import DaysOfMischiefEvidenceError, ITEMS, build, valid_title_relation, verify
from tools.validate.schema_validator import OfflineSchemaValidator
def rows(path): return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
class DaysOfMischiefFaq1356Tests(unittest.TestCase):
 def test_replay_schema_and_bounded_nonclaims(self):
  self.assertEqual(verify(ROOT),[]); _targets,ledger=build(ROOT); self.assertEqual(len(ledger),40)
  snapshot=json.loads((ROOT/"data/source/research/tgc-faq-1356-days-of-mischief-core-five.json").read_text(encoding="utf-8"))
  self.assertFalse(OfflineSchemaValidator(ROOT/"schemas").validate(snapshot,ROOT/"schemas/knowledge/days-of-mischief-faq-1356-core-five-fact-snapshot.schema.json"))
  self.assertEqual((snapshot["facts"]["historical_window_start_date"],snapshot["facts"]["historical_window_end_date"]),("2024-10-21","2024-11-10"))
  expected={2397:("5wLqxZqnGM","Mischief Star Sticker","FaceAccessory"),2396:("kSphDUSrju","Mischief Cauldron","Furniture"),2395:("CCT1qLLxKN","Mischief Spider Bun Hair","Hair"),2393:("uvx7_B9OyH","Mischief Raven-Feathered Cloak","Cape"),2394:("8rYQfi8VP3","Mischief Withered Broom","Held")}
  self.assertEqual({x[1]:(x[2],x[3],x[4]) for x in ITEMS},expected)
  for iid,*_ in ITEMS:
   item={x["item_id"]:x for x in rows(ROOT/"knowledge/items/items.jsonl")}[iid]
   self.assertEqual((item["availability_status"],item["permanent_account_item"],item["first_release_date"],item["model_feature_status"],item["set_ids"],item["visual_reference_ids"]),("unknown","unknown",None,"excluded_pending_verification",[],[]))
 def test_only_two_relations_are_allowed(self):
  self.assertTrue(valid_title_relation("Mischief Star Sticker accessory","Mischief Star Sticker")); self.assertTrue(valid_title_relation("Mischief Spider Bun hairstyle","Mischief Spider Bun Hair"))
  self.assertFalse(valid_title_relation("Mischief Cauldron accessory","Mischief Cauldron")); self.assertFalse(valid_title_relation("Mischief Spider Bun hairstyle","Mischief Spider Bun"))
 def test_tamper_and_idempotence_fail_closed(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/"repo"
   for rel in ("knowledge","data/source","data/review"): shutil.copytree(ROOT/rel,root/rel)
   p=root/"data/source/research/tgc-faq-1356-days-of-mischief-core-five.json"; p.write_text(p.read_text(encoding="utf-8").replace("Mischief Cauldron","Changed Cauldron",1),encoding="utf-8",newline="\n")
   with self.assertRaisesRegex(DaysOfMischiefEvidenceError,"snapshot hash mismatch"): build(root)
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/"repo"
   for rel in ("knowledge","data","schemas"): shutil.copytree(ROOT/rel,root/rel)
   cmd=[sys.executable,str(ROOT/"tools/normalize/apply_days_of_mischief_faq1356_core_five_cohort.py"),"--root",str(root),"--apply"]
   subprocess.run(cmd,check=True,capture_output=True,text=True); tracked=[root/"knowledge/items/items.jsonl",root/"knowledge/sources/sources.jsonl",root/"knowledge/acquisition/availability-events.jsonl",root/"data/review/days-of-mischief-faq1356-core-five-canonical-evidence.jsonl"]; before={p:p.read_bytes() for p in tracked}; subprocess.run(cmd,check=True,capture_output=True,text=True); self.assertEqual(before,{p:p.read_bytes() for p in tracked})
if __name__=="__main__": unittest.main()
