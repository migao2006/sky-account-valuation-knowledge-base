"""Regression tests for the bounded FAQ 1264 Days of Fortune core-five cohort."""
from __future__ import annotations
import json,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from tools.modeling.canonical_english_eligibility import declared_model_feature_status
from tools.normalize.apply_days_of_fortune_faq1264_core_five_cohort import DaysOfFortuneEvidenceError,ITEMS,build,verify
from tools.validate.schema_validator import OfflineSchemaValidator
def rows(path): return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
class DaysOfFortuneFaq1264CoreFiveEvidenceTests(unittest.TestCase):
 def test_replays_official_and_secondary_evidence_without_promotion(self):
  self.assertEqual(verify(ROOT),[]); _targets,ledger=build(ROOT); self.assertEqual(len(ledger),40)
  self.assertEqual(sum(x["field_path"]=="vendor_item_guid" for x in ledger),5)
  validator=OfflineSchemaValidator(ROOT/"schemas")
  self.assertTrue(all(not validator.validate(x,ROOT/"schemas/review/canonical-item-field-evidence.schema.json") for x in ledger))
  snapshot=json.loads((ROOT/"data/source/research/tgc-faq-1264-days-of-fortune-core-five.json").read_text(encoding="utf-8"))
  self.assertFalse(validator.validate(snapshot,ROOT/"schemas/knowledge/days-of-fortune-faq-1264-core-five-fact-snapshot.schema.json"))
  data={x["item_id"]:x for x in rows(ROOT/"knowledge/items/items.jsonl")}
  for iid,*_ in ITEMS:
   self.assertEqual((data[iid]["availability_status"],data[iid]["permanent_account_item"],data[iid]["first_release_date"],data[iid]["model_feature_status"],data[iid]["set_ids"]),("unknown","unknown",None,declared_model_feature_status(iid),[]))
  availability={x["availability_id"]:x for x in rows(ROOT/"knowledge/acquisition/availability-events.jsonl")}
  for iid,*_ in ITEMS: self.assertEqual((availability["availability_days_of_fortune_faq1264_"+iid.removeprefix("item_")]["availability_status"],availability["availability_days_of_fortune_faq1264_"+iid.removeprefix("item_")]["start_date"],availability["availability_days_of_fortune_faq1264_"+iid.removeprefix("item_")]["end_date"]),("limited_time","2024-01-29","2024-02-11"))
 def test_snapshot_and_identity_tampering_fail_closed(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/"repo"
   for rel in ("knowledge","data/source","data/review"): shutil.copytree(ROOT/rel,root/rel)
   p=root/"data/source/research/tgc-faq-1264-days-of-fortune-core-five.json"; p.write_text(p.read_text(encoding="utf-8").replace("Fortune Drum","Changed Drum",1),encoding="utf-8",newline="\n")
   with self.assertRaisesRegex(DaysOfFortuneEvidenceError,"snapshot hash mismatch"): build(root)
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/"repo"
   for rel in ("knowledge","data/source","data/review"): shutil.copytree(ROOT/rel,root/rel)
   p=root/"data/source/vendor/skygame-data-1.3.4-items.json"; data=json.loads(p.read_text(encoding="utf-8")); next(x for x in data["items"] if x["id"]==2055)["guid"]="tampered"; p.write_text(json.dumps(data),encoding="utf-8",newline="\n")
   with self.assertRaisesRegex(DaysOfFortuneEvidenceError,"snapshot hash mismatch"): build(root)
 def test_apply_is_idempotent_and_rejects_model_promotion(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/"repo"
   for rel in ("knowledge","data","schemas"): shutil.copytree(ROOT/rel,root/rel)
   command=[sys.executable,str(ROOT/"tools/normalize/apply_days_of_fortune_faq1264_core_five_cohort.py"),"--root",str(root),"--apply"]
   subprocess.run(command,check=True,capture_output=True,text=True); tracked=[root/"knowledge/items/items.jsonl",root/"knowledge/sources/sources.jsonl",root/"knowledge/acquisition/availability-events.jsonl",root/"data/review/days-of-fortune-faq1264-core-five-canonical-evidence.jsonl"]; before={p:p.read_bytes() for p in tracked}; subprocess.run(command,check=True,capture_output=True,text=True); self.assertEqual(before,{p:p.read_bytes() for p in tracked})
   p=root/"knowledge/items/items.jsonl"; data=rows(p); next(x for x in data if x["item_id"]=="item_fortune_drum")["model_feature_status"]="eligible"; p.write_text("".join(json.dumps(x,ensure_ascii=False,separators=(",",":"))+"\n" for x in data),encoding="utf-8",newline="\n")
   self.assertIn("committed target differs from replayable apply contract: knowledge/items/items.jsonl",verify(root))
if __name__=="__main__": unittest.main()
