"""Regression coverage for the bounded FAQ 1391 Nature + Color core-eleven."""
from __future__ import annotations
import json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from tools.normalize.apply_days_of_nature_color_faq1391_core_eleven_cohort import DaysOfNatureColorEvidenceError, ITEMS, build, valid_title_relation, verify
from tools.validate.schema_validator import OfflineSchemaValidator
def rows(path): return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x]
class DaysOfNatureColorFaq1391Tests(unittest.TestCase):
 def test_replay_schema_and_nonclaims(self):
  self.assertEqual(verify(ROOT),[]); targets,ledger=build(ROOT); self.assertEqual(len(ledger),84)
  self.assertEqual(sum(x[10] for x in ITEMS),7); self.assertEqual(sum(r["field_path"]=="original_cost" for r in ledger),7)
  ticket={x[0] for x in ITEMS if not x[10]}; self.assertFalse(any(r["target_id"] in ticket and r["field_path"]=="original_cost" for r in ledger))
  snapshot=json.loads((ROOT/"data/source/research/tgc-faq-1391-days-of-nature-color-core-eleven.json").read_text(encoding="utf-8"))
  self.assertEqual(snapshot["source_url"],"https://thatgamecompany.helpshift.com/hc/en/17-sky-children-of-the-light/faq/1391-patch-notes---april-17-2025---0-29-0-319554-android-huawei-ios-playstation-steam-switch/")
  self.assertEqual(snapshot["facts"]["exact_price_items"][5]["official_name_en"],"Rainbow Face Paint mask")
  self.assertIn("do not establish individual ticket prices", " ".join(snapshot["non_claims"]))
  validator=OfflineSchemaValidator(ROOT/"schemas")
  self.assertFalse(validator.validate(snapshot,ROOT/"schemas/knowledge/days-of-nature-color-faq-1391-core-eleven-fact-snapshot.schema.json"))
  items={r["item_id"]:r for r in rows(ROOT/"knowledge/items/items.jsonl")}
  for iid,*_ in ITEMS: self.assertEqual((items[iid]["availability_status"],items[iid]["permanent_account_item"],items[iid]["first_release_date"],items[iid]["set_ids"],items[iid]["visual_reference_ids"]),("unknown","unknown",None,[],[]))
  availability={r["availability_id"]:r for r in rows(ROOT/"knowledge/acquisition/availability-events.jsonl")}
  for iid,*_ in ITEMS: self.assertIsNone(availability[f"availability_faq1391_{iid.removeprefix('item_')}"]["end_date"])
  self.assertNotIn("item_days_of_nature_ocean_waves_mask",items)
 def test_casing_relations_are_explicit_not_a_transform(self):
  self.assertTrue(valid_title_relation("Rainbow Face Paint mask","Rainbow Face Paint Mask"))
  self.assertTrue(valid_title_relation("Ocean Waves outfit","Ocean Waves Outfit"))
  self.assertTrue(valid_title_relation("Ocean Manta hair","Ocean Manta Hair"))
  self.assertFalse(valid_title_relation("Rainbow Face Paint MASK","Rainbow Face Paint Mask"))
  self.assertFalse(valid_title_relation("Rainbow Face Paint mask","Rainbow Face Paint Mask extra"))
  self.assertFalse(valid_title_relation("Ocean Waves OUTFIT","Ocean Waves Outfit"))
  self.assertFalse(valid_title_relation("Ocean Manta Hair","Ocean Manta Hair"))
 def test_tamper_and_apply_idempotence_fail_closed(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/"repo"
   for rel in ("knowledge","data/source","data/review"): shutil.copytree(ROOT/rel,root/rel)
   p=root/"data/source/research/tgc-faq-1391-days-of-nature-color-core-eleven.json"; p.write_text(p.read_text(encoding="utf-8").replace("Ocean Necklace","Changed Necklace",1),encoding="utf-8",newline="\n")
   with self.assertRaisesRegex(DaysOfNatureColorEvidenceError,"snapshot hash mismatch"): build(root)
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/"repo"
   for rel in ("knowledge","data","schemas"): shutil.copytree(ROOT/rel,root/rel)
   cmd=[sys.executable,str(ROOT/"tools/normalize/apply_days_of_nature_color_faq1391_core_eleven_cohort.py"),"--root",str(root),"--apply"]
   subprocess.run(cmd,check=True,capture_output=True,text=True); paths=[root/"knowledge/items/items.jsonl",root/"knowledge/sources/sources.jsonl",root/"knowledge/acquisition/availability-events.jsonl",root/"data/review/days-of-nature-color-faq1391-core-eleven-canonical-evidence.jsonl"]; before={p:p.read_bytes() for p in paths}; subprocess.run(cmd,check=True,capture_output=True,text=True); self.assertEqual(before,{p:p.read_bytes() for p in paths})
if __name__=="__main__": unittest.main()
