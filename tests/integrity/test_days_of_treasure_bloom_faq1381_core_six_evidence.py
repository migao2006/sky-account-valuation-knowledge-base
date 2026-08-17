"""Regression tests for FAQ 1381's exact-price Treasure + Bloom core-six slice."""
from __future__ import annotations
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from tools.modeling.canonical_english_eligibility import declared_model_feature_status
from tools.normalize.apply_days_of_treasure_bloom_faq1381_core_six_cohort import DaysOfTreasureBloomEvidenceError, ITEMS, build, valid_title_relation, verify
from tools.validate.schema_validator import OfflineSchemaValidator
def rows(path): return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

class DaysOfTreasureBloomFaq1381CoreSixEvidenceTests(unittest.TestCase):
 def test_replays_strictly_and_excludes_bundle_claims(self):
  self.assertEqual(verify(ROOT),[]); _targets,ledger=build(ROOT); self.assertEqual(len(ledger),48)
  self.assertEqual(sum(r["field_path"]=="vendor_item_guid" for r in ledger),6)
  self.assertFalse(any("Bounty" in str(r["claim_value"]) for r in ledger))
  validator=OfflineSchemaValidator(ROOT/"schemas")
  self.assertTrue(all(not validator.validate(r,ROOT/"schemas/review/canonical-item-field-evidence.schema.json") for r in ledger))
  snapshot=json.loads((ROOT/"data/source/research/tgc-faq-1381-days-of-treasure-bloom-core-six.json").read_text(encoding="utf-8"))
  self.assertFalse(validator.validate(snapshot,ROOT/"schemas/knowledge/days-of-treasure-bloom-faq-1381-core-six-fact-snapshot.schema.json"))
  catalog={r["item_id"]:r for r in rows(ROOT/"knowledge/items/items.jsonl")}
  for iid,*_ in ITEMS:
   self.assertEqual((catalog[iid]["availability_status"],catalog[iid]["permanent_account_item"],catalog[iid]["first_release_date"],catalog[iid]["model_feature_status"],catalog[iid]["set_ids"],catalog[iid]["visual_reference_ids"]),("unknown","unknown",None,declared_model_feature_status(iid),[],[]))
  available={r["availability_id"]:r for r in rows(ROOT/"knowledge/acquisition/availability-events.jsonl")}
  for iid,*_,event in ITEMS:
   row=available["availability_faq1381_"+iid.removeprefix("item_")]
   self.assertEqual((row["availability_status"],row["start_date"],row["end_date"]),("limited_time",*( ("2025-03-03","2025-03-16") if event=="days_of_treasure" else ("2025-03-24","2025-04-13"))))
 def test_relation_is_enumerated_not_generic_normalization(self):
  self.assertTrue(valid_title_relation("Treasure Shovel","Treasure Shovel")); self.assertFalse(valid_title_relation("Treasure Shovel","Treasure Shovel prop")); self.assertFalse(valid_title_relation("Treasure Seeker's Bounty Outfit","Treasure Seeker's Bounty Outfit"))
 def test_tampering_and_apply_idempotence_fail_closed(self):
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary)/"repo"
   for rel in ("knowledge","data/source","data/review"): shutil.copytree(ROOT/rel,root/rel)
   snapshot=root/"data/source/research/tgc-faq-1381-days-of-treasure-bloom-core-six.json"; snapshot.write_text(snapshot.read_text(encoding="utf-8").replace("Treasure Shovel","Changed Shovel",1),encoding="utf-8",newline="\n")
   with self.assertRaisesRegex(DaysOfTreasureBloomEvidenceError,"snapshot hash mismatch"): build(root)
  with tempfile.TemporaryDirectory() as temporary:
   root=Path(temporary)/"repo"
   for rel in ("knowledge","data","schemas"): shutil.copytree(ROOT/rel,root/rel)
   command=[sys.executable,str(ROOT/"tools/normalize/apply_days_of_treasure_bloom_faq1381_core_six_cohort.py"),"--root",str(root),"--apply"]
   subprocess.run(command,check=True,capture_output=True,text=True)
   tracked=[root/"knowledge/items/items.jsonl",root/"knowledge/sources/sources.jsonl",root/"knowledge/acquisition/availability-events.jsonl",root/"data/review/days-of-treasure-bloom-faq1381-core-six-canonical-evidence.jsonl"]
   before={p:p.read_bytes() for p in tracked}; subprocess.run(command,check=True,capture_output=True,text=True); self.assertEqual(before,{p:p.read_bytes() for p in tracked})
   catalog=rows(root/"knowledge/items/items.jsonl"); next(r for r in catalog if r["item_id"]=="item_treasure_shovel")["model_feature_status"]="eligible"; (root/"knowledge/items/items.jsonl").write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in catalog),encoding="utf-8",newline="\n")
   self.assertIn("committed target differs from replayable apply contract: knowledge/items/items.jsonl",verify(root))
if __name__=="__main__": unittest.main()
