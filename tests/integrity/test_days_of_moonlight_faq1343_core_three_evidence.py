"""Regression tests for bounded FAQ 1343 Days of Moonlight core-three."""
from __future__ import annotations
import json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from tools.normalize.apply_days_of_moonlight_faq1343_core_three_cohort import DaysOfMoonlightEvidenceError, ITEMS, build, valid_title_relation, verify
from tools.validate.schema_validator import OfflineSchemaValidator
def rows(path): return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
class DaysOfMoonlightFaq1343Tests(unittest.TestCase):
 def test_replay_schema_and_bounded_nonclaims(self):
  self.assertEqual(verify(ROOT),[]); _targets,ledger=build(ROOT); self.assertEqual(len(ledger),24)
  snapshot=json.loads((ROOT/"data/source/research/tgc-faq-1343-days-of-moonlight-core-three.json").read_text(encoding="utf-8"))
  self.assertFalse(OfflineSchemaValidator(ROOT/"schemas").validate(snapshot,ROOT/"schemas/knowledge/days-of-moonlight-faq-1343-core-three-fact-snapshot.schema.json"))
  self.assertEqual((snapshot["facts"]["historical_window_start_date"],snapshot["facts"]["historical_window_end_date"]),("2024-09-16","2024-09-29"))
  self.assertEqual({x[1]:(x[2],x[3],x[4]) for x in ITEMS},{2308:("A4CTK7T9ea","Moonlight Blossom Accessory","HairAccessory"),2307:("vx4vxVJ0L1","Moonlight Lantern","Furniture"),2306:("XURacs6BHP","Moonlight Earrings","HeadAccessory")})
  for iid,*_ in ITEMS:
   item={x["item_id"]:x for x in rows(ROOT/"knowledge/items/items.jsonl")}[iid]
   self.assertEqual((item["availability_status"],item["permanent_account_item"],item["first_release_date"],item["model_feature_status"],item["set_ids"],item["visual_reference_ids"]),("unknown","unknown",None,"excluded_pending_verification",[],[]))
 def test_only_explicit_lantern_relation_and_collision_guard_are_allowed(self):
  self.assertTrue(valid_title_relation("Moonlight Lantern Decoration","Moonlight Lantern",2307))
  self.assertFalse(valid_title_relation("Moonlight Lantern Decoration","Moonlight Lantern",1902))
  self.assertFalse(valid_title_relation("Moonlight Blossom Accessory","Moonlight Blossom",2308))
  self.assertFalse(valid_title_relation("Moonlight Earrings accessory","Moonlight Earrings",2306))
 def test_tamper_and_idempotence_fail_closed(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/"repo"
   for rel in ("knowledge","data/source","data/review"): shutil.copytree(ROOT/rel,root/rel)
   p=root/"data/source/research/tgc-faq-1343-days-of-moonlight-core-three.json"; p.write_text(p.read_text(encoding="utf-8").replace("Moonlight Earrings","Changed Earrings",1),encoding="utf-8",newline="\n")
   with self.assertRaisesRegex(DaysOfMoonlightEvidenceError,"snapshot hash mismatch"): build(root)
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/"repo"
   for rel in ("knowledge","data","schemas"): shutil.copytree(ROOT/rel,root/rel)
   cmd=[sys.executable,str(ROOT/"tools/normalize/apply_days_of_moonlight_faq1343_core_three_cohort.py"),"--root",str(root),"--apply"]
   subprocess.run(cmd,check=True,capture_output=True,text=True); tracked=[root/"knowledge/items/items.jsonl",root/"knowledge/sources/sources.jsonl",root/"knowledge/acquisition/availability-events.jsonl",root/"data/review/days-of-moonlight-faq1343-core-three-canonical-evidence.jsonl"]; before={p:p.read_bytes() for p in tracked}; subprocess.run(cmd,check=True,capture_output=True,text=True); self.assertEqual(before,{p:p.read_bytes() for p in tracked})
if __name__=="__main__": unittest.main()
