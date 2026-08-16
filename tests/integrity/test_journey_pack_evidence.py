"""Regression tests for the bounded, replayable FAQ 1308 Journey Pack cohort."""
from __future__ import annotations
import json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/"tools"/"validate"))
from tools.normalize.apply_journey_pack_cohort import ITEMS, JourneyEvidenceError, build, verify  # noqa: E402
from tools.validate.schema_validator import OfflineSchemaValidator  # noqa: E402

def rows(path:Path): return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

class JourneyPackEvidenceTests(unittest.TestCase):
 def test_replays_official_and_secondary_evidence(self):
  self.assertEqual(verify(ROOT),[])
  _,evidence=build(ROOT); self.assertEqual(len(evidence),16)
  validator=OfflineSchemaValidator(ROOT/"schemas"); evidence_schema=ROOT/"schemas/review/canonical-item-field-evidence.schema.json"
  self.assertTrue(all(not validator.validate(row,evidence_schema) for row in evidence))
  snapshot=json.loads((ROOT/"data/source/research/tgc-faq-1308-journey-pack.json").read_text(encoding="utf-8"))
  self.assertFalse(validator.validate(snapshot,ROOT/"schemas/knowledge/journey-pack-fact-snapshot.schema.json"))
  item_data={r["item_id"]:r for r in rows(ROOT/"knowledge/items/items.jsonl")}
  self.assertEqual({i:item_data[i]["canonical_name_en"] for i,*_ in ITEMS},{i:name for i,_v,name,_c in ITEMS})
  self.assertTrue(all(item_data[i]["original_cost"]=="bundle_only" for i,*_ in ITEMS))
  self.assertTrue(all(item_data[i]["availability_status"]=="unknown" and item_data[i]["permanent_account_item"]=="unknown" for i,*_ in ITEMS))
  self.assertTrue(all(item_data[i]["model_feature_status"]=="excluded_pending_verification" for i,*_ in ITEMS))
  journey_set=next(r for r in rows(ROOT/"knowledge/sets/item-sets.jsonl") if r["set_id"]=="set_journey_pack")
  self.assertEqual(journey_set["required_item_ids"],[i for i,*_ in ITEMS])
  self.assertIn("historical_pack_price_usd",{r["field_path"] for r in evidence})
  self.assertFalse(any(r["field_path"]=="availability_status" for r in evidence))

 def test_changed_source_and_missing_registry_fail_closed(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)/"repo"
   for rel in ("knowledge","data/source","data/review"):shutil.copytree(ROOT/rel,root/rel)
   p=root/"data/source/research/tgc-faq-1308-journey-pack.json"
   p.write_text(p.read_text(encoding="utf-8").replace("Journey Pack","Changed Pack",1),encoding="utf-8",newline="\n")
   with self.assertRaisesRegex(JourneyEvidenceError,"official snapshot hash mismatch"):build(root)
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)/"repo"
   for rel in ("knowledge","data/source","data/review"):shutil.copytree(ROOT/rel,root/rel)
   p=root/"knowledge/sources/sources.jsonl"
   p.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in rows(p) if r["source_id"]!="source_tgc_faq_1308_journey_pack"),encoding="utf-8",newline="\n")
   with self.assertRaisesRegex(JourneyEvidenceError,"source registry or lineage mismatch"):build(root)

 def test_apply_is_idempotent_and_rejects_overpromotion(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)/"repo"
   for rel in ("knowledge","data","schemas"):shutil.copytree(ROOT/rel,root/rel)
   command=[sys.executable,str(ROOT/"tools/normalize/apply_journey_pack_cohort.py"),"--root",str(root),"--apply"]
   first=subprocess.run(command,check=True,capture_output=True,text=True)
   tracked=[root/"knowledge/items/items.jsonl",root/"knowledge/sets/item-sets.jsonl",root/"knowledge/sources/sources.jsonl",root/"knowledge/acquisition/availability-events.jsonl",root/"data/review/journey-pack-canonical-evidence.jsonl"]
   before={p:p.read_bytes() for p in tracked}; second=subprocess.run(command,check=True,capture_output=True,text=True)
   self.assertEqual(json.loads(first.stdout),json.loads(second.stdout)); self.assertEqual(before,{p:p.read_bytes() for p in tracked})
   p=root/"knowledge/items/items.jsonl"; data=rows(p); next(r for r in data if r["item_id"]=="item_journey_mask")["model_feature_status"]="eligible"
   p.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in data),encoding="utf-8",newline="\n")
   self.assertIn("committed target differs from replayable apply contract: knowledge/items/items.jsonl",verify(root))

if __name__=="__main__":unittest.main()
