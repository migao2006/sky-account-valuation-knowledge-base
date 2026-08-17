"""Regression tests for bounded FAQ 1278 Days of Bloom core-four."""
from __future__ import annotations
import json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from tools.normalize.apply_days_of_bloom_faq1278_core_four_cohort import DaysOfBloomEvidenceError, ITEMS, build, valid_title_relation, verify
from tools.validate.schema_validator import OfflineSchemaValidator
def rows(path): return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
class DaysOfBloomFaq1278Tests(unittest.TestCase):
 def test_replay_schema_and_bounded_nonclaims(self):
  self.assertEqual(verify(ROOT),[]); _targets,ledger=build(ROOT); self.assertEqual(len(ledger),32)
  snapshot=json.loads((ROOT/"data/source/research/tgc-faq-1278-days-of-bloom-core-four.json").read_text(encoding="utf-8"))
  self.assertFalse(OfflineSchemaValidator(ROOT/"schemas").validate(snapshot,ROOT/"schemas/knowledge/days-of-bloom-faq-1278-core-four-fact-snapshot.schema.json"))
  self.assertEqual((snapshot["facts"]["historical_window_start_date"],snapshot["facts"]["historical_window_end_date"]),("2024-03-25","2024-04-14"))
  self.assertEqual({x[1]:(x[2],x[3],x[4]) for x in ITEMS},{2075:("kLfBsnAsUL","Bloom Lilypad Umbrella","Held"),2076:("MgQqIuTSuC","Bloom Arum Petal Cape","Cape"),2077:("vxfZZiaabO","Bloom Spiky Sprig Hair","Hair"),2078:("nkJXDrn2cV","Bloom Arum Petal Hair","Hair")})
  for iid,*_ in ITEMS:
   item={x["item_id"]:x for x in rows(ROOT/"knowledge/items/items.jsonl")}[iid]
   self.assertEqual((item["availability_status"],item["permanent_account_item"],item["first_release_date"],item["model_feature_status"],item["set_ids"],item["visual_reference_ids"]),("unknown","unknown",None,"excluded_pending_verification",[],[]))
 def test_only_exact_title_relations_are_allowed(self):
  self.assertTrue(valid_title_relation("Bloom Lilypad Umbrella","Bloom Lilypad Umbrella",2075))
  self.assertTrue(valid_title_relation("Bloom Arum Petal Cape","Bloom Arum Petal Cape",2076))
  self.assertFalse(valid_title_relation("Bloom Lilypad Umbrella prop","Bloom Lilypad Umbrella",2075))
  self.assertFalse(valid_title_relation("Bloom Arum Petal Cape","Bloom Arum Petal",2076))
 def test_tamper_and_idempotence_fail_closed(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/"repo"
   for rel in ("knowledge","data/source","data/review"): shutil.copytree(ROOT/rel,root/rel)
   p=root/"data/source/research/tgc-faq-1278-days-of-bloom-core-four.json"; p.write_text(p.read_text(encoding="utf-8").replace("Bloom Lilypad Umbrella","Changed Umbrella",1),encoding="utf-8",newline="\n")
   with self.assertRaisesRegex(DaysOfBloomEvidenceError,"snapshot hash mismatch"): build(root)
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/"repo"
   for rel in ("knowledge","data","schemas"): shutil.copytree(ROOT/rel,root/rel)
   cmd=[sys.executable,str(ROOT/"tools/normalize/apply_days_of_bloom_faq1278_core_four_cohort.py"),"--root",str(root),"--apply"]
   subprocess.run(cmd,check=True,capture_output=True,text=True); tracked=[root/"knowledge/items/items.jsonl",root/"knowledge/sources/sources.jsonl",root/"knowledge/acquisition/availability-events.jsonl",root/"data/review/days-of-bloom-faq1278-core-four-canonical-evidence.jsonl"]; before={p:p.read_bytes() for p in tracked}; subprocess.run(cmd,check=True,capture_output=True,text=True); self.assertEqual(before,{p:p.read_bytes() for p in tracked})
if __name__=="__main__": unittest.main()
