"""Regression coverage for the bounded FAQ 1362 Days of Music core-four."""
from __future__ import annotations
import json, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]; sys.path.insert(0,str(ROOT))
from tools.normalize.apply_days_of_music_faq1362_core_four_cohort import DaysOfMusicEvidenceError, ITEMS, build, valid_title_relation, verify
from tools.validate.schema_validator import OfflineSchemaValidator
def rows(path): return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
class DaysOfMusicFaq1362Tests(unittest.TestCase):
 def test_replay_schema_and_bounded_nonclaims(self):
  self.assertEqual(verify(ROOT),[]); _targets,ledger=build(ROOT); self.assertEqual(len(ledger),34)
  snapshot=json.loads((ROOT/"data/source/research/tgc-faq-1362-days-of-music-core-four.json").read_text(encoding="utf-8"))
  self.assertEqual(snapshot["source_url"],"https://thatgamecompany.helpshift.com/hc/en/17-sky-children-of-the-light/faq/1362-patch-notes---november-21-2024---0-27-5-302936-android-huawei-ios-playstation-304181-steam-303477-switch/")
  self.assertEqual((snapshot["facts"]["historical_window_start_date"],snapshot["facts"]["historical_window_end_date"]),("2024-11-25","2024-12-08"))
  self.assertEqual(snapshot["facts"]["post_event_permanent_item_ids"],["item_permanent_jam_station","item_permanent_fledgling_upright_piano"])
  self.assertFalse(OfflineSchemaValidator(ROOT/"schemas").validate(snapshot,ROOT/"schemas/knowledge/days-of-music-faq-1362-core-four-fact-snapshot.schema.json"))
  expected={"item_days_of_music_marching_band_cape":(2404,"XCTyx0K4zm","Marching Band Cape","Cape"),"item_days_of_music_music_marching_uniform":(2405,"n6S9sKtNlW","Music Marching Uniform","OutfitShoes"),"item_permanent_jam_station":(2407,"WMNr4yo_35","Jam Station","Furniture"),"item_permanent_fledgling_upright_piano":(2406,"10Ol7H9jKg","Fledgling Upright Piano","Prop")}
  for iid,(vid,guid,name,typ) in expected.items():
   self.assertIn((iid,vid,guid,name,typ),{(x[0],x[1],x[2],x[3],x[4]) for x in ITEMS})
  canonical={r["item_id"]:r for r in rows(ROOT/"knowledge/items/items.jsonl")}
  piano=canonical["item_permanent_fledgling_upright_piano"]
  self.assertEqual((piano["verification_status"],piano["source_id"],piano["original_currency"],piano["original_cost"],piano["availability_status"],piano["permanent_account_item"]),("verified","source_tgc_faq_1362_days_of_music_core_four","USD",4.99,"unknown","unknown"))
  availability={r["availability_id"]:r for r in rows(ROOT/"knowledge/acquisition/availability-events.jsonl")}
  for iid in ("item_permanent_jam_station","item_permanent_fledgling_upright_piano"):
   policy=availability[f"availability_faq1362_{iid.removeprefix('item_')}_post_event_permanent"]
   self.assertEqual((policy["availability_status"],policy["start_date"],policy["end_date"]),("permanent","2024-12-09",None))
  self.assertNotIn("item_wonderland_pinafore_set",{x[0] for x in ITEMS})
 def test_only_explicit_suffix_pair_is_accepted(self):
  self.assertTrue(valid_title_relation("Music Marching Uniform outfit","Music Marching Uniform"))
  self.assertFalse(valid_title_relation("Music Marching Uniform Outfit","Music Marching Uniform"))
  self.assertFalse(valid_title_relation("Music Marching Uniform outfit","Music Marching Uniform Outfit"))
  self.assertFalse(valid_title_relation("Marching Band Cape outfit","Marching Band Cape"))
  self.assertFalse(valid_title_relation("Fledgling Upright Piano prop","Fledgling Upright Piano"))
 def test_tamper_and_apply_idempotence_fail_closed(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/"repo"
   for rel in ("knowledge","data/source","data/review"): shutil.copytree(ROOT/rel,root/rel)
   p=root/"data/source/research/tgc-faq-1362-days-of-music-core-four.json"; p.write_text(p.read_text(encoding="utf-8").replace("Jam Station","Changed Station",1),encoding="utf-8",newline="\n")
   with self.assertRaisesRegex(DaysOfMusicEvidenceError,"snapshot hash mismatch"): build(root)
  with tempfile.TemporaryDirectory() as d:
   root=Path(d)/"repo"
   for rel in ("knowledge","data","schemas"): shutil.copytree(ROOT/rel,root/rel)
   cmd=[sys.executable,str(ROOT/"tools/normalize/apply_days_of_music_faq1362_core_four_cohort.py"),"--root",str(root),"--apply"]
   subprocess.run(cmd,check=True,capture_output=True,text=True)
   paths=[root/"knowledge/items/items.jsonl",root/"knowledge/sources/sources.jsonl",root/"knowledge/acquisition/availability-events.jsonl",root/"data/review/days-of-music-faq1362-core-four-canonical-evidence.jsonl"]
   before={p:p.read_bytes() for p in paths}; subprocess.run(cmd,check=True,capture_output=True,text=True); self.assertEqual(before,{p:p.read_bytes() for p in paths})
if __name__=="__main__": unittest.main()
