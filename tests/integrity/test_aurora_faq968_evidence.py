"""Bounded regression tests for the replayable FAQ 968 AURORA cohort."""
from __future__ import annotations
import json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"/"validate"))
from tools.normalize.apply_aurora_faq968_cohort import ITEMS, IAP_IDS, AuroraEvidenceError, build, verify  # noqa: E402
from tools.validate.schema_validator import OfflineSchemaValidator  # noqa: E402

def rows(path:Path): return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

class AuroraFaq968EvidenceTests(unittest.TestCase):
 def test_replays_pinned_facts_and_six_item_scope(self):
  self.assertEqual(verify(ROOT),[])
  _, evidence=build(ROOT); self.assertEqual(len(evidence),33)
  validator=OfflineSchemaValidator(ROOT/"schemas"); schema=ROOT/"schemas/review/canonical-item-field-evidence.schema.json"
  self.assertTrue(all(not validator.validate(row,schema) for row in evidence))
  data={r["item_id"]:r for r in rows(ROOT/"knowledge/items/items.jsonl")}
  self.assertEqual(set(i for i,*_ in ITEMS),{"item_aurora_voice","item_aurora_wings","item_aurora_cure_for_me_mask","item_aurora_cure_for_me_outfit","item_aurora_to_the_love_outfit","item_aurora_giving_in_cape"})
  for item_id,*_ in ITEMS:
   self.assertEqual(data[item_id]["availability_status"],"unknown")
   self.assertEqual(data[item_id]["permanent_account_item"],"unknown")
   self.assertEqual(data[item_id]["model_feature_status"],"excluded_pending_verification")
   self.assertIsNone(data[item_id]["first_release_date"])
   self.assertTrue(data[item_id]["canonical_name_zh_tw"].startswith("待確認（"))
  aurora_set=next(r for r in rows(ROOT/"knowledge/sets/item-sets.jsonl") if r["set_id"]=="set_aurora_iap")
  self.assertEqual(set(aurora_set["required_item_ids"]),IAP_IDS)
  self.assertNotIn("item_aurora_cure_for_me_mask",aurora_set["required_item_ids"])
  self.assertNotIn("item_aurora_cure_for_me_outfit",aurora_set["required_item_ids"])
  self.assertIn("FAQ 968",aurora_set["canonical_name_en"])
  self.assertNotIn("all AURORA",aurora_set["canonical_name_en"])
  snapshot=json.loads((ROOT/"data/source/research/tgc-faq-968-aurora-remaining-iap.json").read_text(encoding="utf-8"))
  self.assertFalse(validator.validate(snapshot,ROOT/"schemas/knowledge/aurora-faq-968-fact-snapshot.schema.json"))

 def test_field_evidence_schema_rejects_cross_kind_and_wrong_value_types(self):
  validator=OfflineSchemaValidator(ROOT/"schemas"); schema=ROOT/"schemas/review/canonical-item-field-evidence.schema.json"
  sample=rows(ROOT/"data/review/aurora-faq968-canonical-evidence.jsonl")[0]
  wrong_target=dict(sample,target_type="item",target_id="set_aurora_iap")
  wrong_field=dict(sample,target_type="set",target_id="set_aurora_iap",field_path="item_category")
  wrong_value=dict(sample,field_path="original_cost",claim_value={"amount":14.99})
  self.assertTrue(validator.validate(wrong_target,schema))
  self.assertTrue(validator.validate(wrong_field,schema))
  self.assertTrue(validator.validate(wrong_value,schema))

 def test_changed_pinned_snapshot_fails_closed(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)/"repo"
   for rel in ("knowledge","data/source","data/review"): shutil.copytree(ROOT/rel,root/rel)
   p=root/"data/source/research/tgc-faq-968-aurora-remaining-iap.json"
   p.write_text(p.read_text(encoding="utf-8").replace("Voice of AURORA","Changed Voice",1),encoding="utf-8",newline="\n")
   with self.assertRaisesRegex(AuroraEvidenceError,"official snapshot hash mismatch"): build(root)

 def test_apply_cannot_bootstrap_an_official_source_master_record(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)/"repo"
   for rel in ("knowledge","data/source","data/review"): shutil.copytree(ROOT/rel,root/rel)
   p=root/"knowledge/sources/sources.jsonl"
   p.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in rows(p) if r["source_id"]!="source_tgc_faq_968_aurora_remaining_iap"),encoding="utf-8",newline="\n")
   with self.assertRaisesRegex(AuroraEvidenceError,"source registry or lineage mismatch"):
    build(root)

 def test_apply_is_idempotent_and_rejects_overpromotion(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)/"repo"
   for rel in ("knowledge","data","schemas"): shutil.copytree(ROOT/rel,root/rel)
   command=[sys.executable,str(ROOT/"tools/normalize/apply_aurora_faq968_cohort.py"),"--root",str(root),"--apply"]
   first=subprocess.run(command,check=True,capture_output=True,text=True)
   tracked=[root/"knowledge/items/items.jsonl",root/"knowledge/sets/item-sets.jsonl",root/"knowledge/sources/sources.jsonl",root/"knowledge/acquisition/availability-events.jsonl",root/"knowledge/visual-references/manifest.jsonl",root/"data/review/aurora-faq968-canonical-evidence.jsonl"]
   first_bytes={p:p.read_bytes() for p in tracked}; second=subprocess.run(command,check=True,capture_output=True,text=True)
   self.assertEqual(json.loads(first.stdout),json.loads(second.stdout)); self.assertEqual(first_bytes,{p:p.read_bytes() for p in tracked})
   p=root/"knowledge/items/items.jsonl"; current=rows(p); next(r for r in current if r["item_id"]=="item_aurora_voice")["model_feature_status"]="eligible"
   p.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in current),encoding="utf-8",newline="\n")
   self.assertIn("committed target differs from replayable apply contract: knowledge/items/items.jsonl",verify(root))

if __name__=="__main__": unittest.main()
