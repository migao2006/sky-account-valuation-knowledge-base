#!/usr/bin/env python3
"""Replay FAQ 1381's bounded, exact-price Treasure + Bloom core-six cohort."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from tools.modeling.canonical_english_eligibility import declared_model_feature_status
from tools.normalize.apply_moomintroll_accessory_set_cohort import evidence, read, safe, sha, vendor, write

OFFICIAL_SOURCE="source_tgc_faq_1381_days_of_treasure_bloom_core_six"; SECONDARY_SOURCE="source_skygame_data_1_3_4"
OFFICIAL_LINEAGE="lineage_tgc_support_faq_1381"; SECONDARY_LINEAGE="lineage_skygame_data_1_3_4"
OFFICIAL_PATH="data/source/research/tgc-faq-1381-days-of-treasure-bloom-core-six.json"; SECONDARY_PATH="data/source/vendor/skygame-data-1.3.4-items.json"
OFFICIAL_SHA="28F064E93B9F9280B2EA9EC54526E9246DB02F3C4D31B10B9659915E38A5A6A0"; SECONDARY_SHA="21CCAD77006C425B27EE9314870BB5BB77E8436459C6DA214ABCB2B0D8329BBB"; AS_OF="2026-08-17"
# id, vendor numeric id/GUID/title/type, exact FAQ title, category, currency, price, event-window prefix.
ITEMS=(
 ("item_treasure_cavalier_boots",2528,"iMG2NRQ96n","Treasure Cavalier Boots","Shoes","Treasure Cavalier Boots","outfit","event_currency",30,"days_of_treasure"),
 ("item_treasure_shovel",2529,"aU_ZGHomyy","Treasure Shovel","Held","Treasure Shovel","prop","event_currency",30,"days_of_treasure"),
 ("item_bloom_rose_jar_prop",2541,"gSmFBHmzx7","Bloom Rose Jar Prop","Prop","Bloom Rose Jar Prop","prop","event_currency",16,"days_of_bloom"),
 ("item_bloom_rose_braided_hair",2542,"Rrhk8jKU4u","Bloom Rose Braided Hair","Hair","Bloom Rose Braided Hair","hair","event_currency",28,"days_of_bloom"),
 ("item_bloom_rose_petal_mask",2540,"rFyanmj7uL","Bloom Rose Petal Mask","Mask","Bloom Rose Petal Mask","mask","event_currency",36,"days_of_bloom"),
 ("item_bloom_rose_embroidered_cape",2539,"5F_G_puJb7","Bloom Rose-Embroidered Cape","Cape","Bloom Rose-Embroidered Cape","cape","USD",14.99,"days_of_bloom"),
)
SOURCE_ROW={"source_id":OFFICIAL_SOURCE,"source_name":"thatgamecompany Help Center FAQ 1381 — Patch Notes, February 27, 2025 (Days of Treasure and Days of Bloom 2025)","source_type":"official_support","url":"https://thatgamecompany.helpshift.com/hc/en/17-sky-children-of-the-light/faq/1381-patch-notes---february-27-2025---0-28-5-313329-android-huawei-ios-playstation-steam-switch/","retrieved_at":AS_OF,"evidence_level":"official_explicit","source_lineage_id":OFFICIAL_LINEAGE,"notes":"Fact-limited locally pinned transcription: Days of Treasure and Days of Bloom 2025 windows and six named exact-price single-item costs only. Treasure Seeker's Bounty and every no-exact-individual-price entry are excluded. It does not establish current availability, return policy, permanent ownership, images, formal Traditional Chinese names, visual matches, or first release dates."}
class DaysOfTreasureBloomEvidenceError(ValueError): pass
def registry_contract(): return {"cohort_id":"canonical_cohort_days_of_treasure_bloom_faq1381_core_six","evidence_path":"data/review/days-of-treasure-bloom-faq1381-core-six-canonical-evidence.jsonl","snapshot_paths":[OFFICIAL_PATH,SECONDARY_PATH],"source_ids":[SECONDARY_SOURCE,OFFICIAL_SOURCE],"target_item_ids":sorted(x[0] for x in ITEMS),"target_set_ids":[]}
def source_rows(rows):
 index={row["source_id"]:dict(row) for row in rows}
 if index.get(OFFICIAL_SOURCE) not in (None,SOURCE_ROW): raise DaysOfTreasureBloomEvidenceError("official source registry conflicts with cohort contract")
 index[OFFICIAL_SOURCE]=SOURCE_ROW; order=[row["source_id"] for row in rows]
 if OFFICIAL_SOURCE not in order: order.append(OFFICIAL_SOURCE)
 return [index[key] for key in order]
def valid_title_relation(official_name,vendor_name): return (official_name,vendor_name) in {(x[5],x[3]) for x in ITEMS}
def item_row(iid,name,category,currency,cost,event):
 return {"item_id":iid,"canonical_name_zh_tw":f"待確認（{name}）","canonical_name_en":name,"aliases":[],"item_category":category,"item_subcategory":"days_of_treasure_bloom_2025_historical_item","source_type":"event","source_id":OFFICIAL_SOURCE,"season_id":None,"event_id":None,"ancestor_id":None,"set_ids":[],"free_or_premium":"unknown","pass_required":"unknown","ultimate_reward":False,"collaboration":False,"permanent_account_item":"unknown","consumable":False,"original_currency":currency,"original_cost":cost,"availability_status":"unknown","first_release_date":None,"availability_event_ids":[f"availability_faq1381_{iid.removeprefix('item_') }"],"visual_reference_ids":[],"valuation_role":"collection_structure","source_ids":[OFFICIAL_SOURCE,SECONDARY_SOURCE],"last_verified_at":AS_OF,"verification_status":"verified","evidence_tier":"official_with_secondary","model_feature_status":declared_model_feature_status(iid),"notes":"FAQ 1381 establishes this named 2025 historical offer and event window only; the pinned vendor snapshot independently supplies exact vendor ID, GUID, title, and type. Treasure Seeker's Bounty bundle and all entries without an exact individual price are excluded. Current availability, return policy, permanent-account property, formal Traditional Chinese name, visual identity, first release date, and model eligibility remain unknown or unasserted. This is a bounded six-item FAQ slice, not a complete Days of Treasure or Days of Bloom catalog."}
def build(root:Path):
 root=root.resolve(); official_bytes=safe(root,OFFICIAL_PATH).read_bytes(); secondary_bytes=safe(root,SECONDARY_PATH).read_bytes()
 if sha(official_bytes)!=OFFICIAL_SHA or sha(secondary_bytes)!=SECONDARY_SHA: raise DaysOfTreasureBloomEvidenceError("official or secondary snapshot hash mismatch")
 official=json.loads(official_bytes); secondary=json.loads(secondary_bytes); facts=official.get("facts",{})
 expected=[{"item_id":x[0],"official_name_en":x[5],"original_currency":x[7],"original_cost":x[8]} for x in ITEMS]
 if official.get("source_id")!=OFFICIAL_SOURCE or facts.get("new_items")!=expected or any(facts.get(k)!=v for k,v in (("days_of_treasure_window_start_date","2025-03-03"),("days_of_treasure_window_end_date","2025-03-16"),("days_of_bloom_window_start_date","2025-03-24"),("days_of_bloom_window_end_date","2025-04-13"))): raise DaysOfTreasureBloomEvidenceError("official FAQ 1381 contract changed")
 targets={key:read(root/path) for key,path in (("items","knowledge/items/items.jsonl"),("sources","knowledge/sources/sources.jsonl"))}; sources={r["source_id"]:r for r in source_rows(targets["sources"])}
 for source_id,typ,lineage in ((OFFICIAL_SOURCE,"official_support",OFFICIAL_LINEAGE),(SECONDARY_SOURCE,"community_database",SECONDARY_LINEAGE)):
  if sources.get(source_id,{}).get("source_type")!=typ or sources[source_id].get("source_lineage_id")!=lineage: raise DaysOfTreasureBloomEvidenceError("source registry or lineage mismatch: "+source_id)
 ledger=[]
 for n,(iid,vid,guid,vname,vtype,oname,category,currency,cost,event) in enumerate(ITEMS):
  index,row=vendor(secondary,vid)
  if (row.get("guid"),row.get("name"),row.get("type"))!=(guid,vname,vtype): raise DaysOfTreasureBloomEvidenceError("secondary identity changed: "+str(vid))
  if not valid_title_relation(oname,vname): raise DaysOfTreasureBloomEvidenceError("unsupported official/vendor title relation: "+str(vid))
  note="Historical FAQ cost/window only; no current availability, permanence, or model eligibility is inferred."; prefix=f"/facts/{event}_window"; path=f"/facts/new_items/{n}"
  ledger.extend((evidence("item",iid,"canonical_name_en",oname,OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,official_bytes,path+"/official_name_en","independent_identity","FAQ exact title; only this explicit FAQ/vendor title pair is allowed."),evidence("item",iid,"original_currency",currency,OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,official_bytes,path+"/original_currency","independent_field",note),evidence("item",iid,"original_cost",cost,OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,official_bytes,path+"/original_cost","independent_field",note),evidence("item",iid,"availability_history",facts[event+"_window_start_date"],OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,official_bytes,prefix+"_start_date","independent_field",note),evidence("item",iid,"availability_history",facts[event+"_window_end_date"],OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,official_bytes,prefix+"_end_date","independent_field",note),evidence("item",iid,"vendor_item_name",vname,SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,secondary_bytes,f"/items/{index}/name","secondary_field","Pinned vendor spelling; title reconciliation is limited by this apply contract."),evidence("item",iid,"vendor_item_type",vtype,SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,secondary_bytes,f"/items/{index}/type","secondary_field",f"Apply contract maps vendor type to canonical category {category}."),evidence("item",iid,"vendor_item_guid",guid,SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,secondary_bytes,f"/items/{index}/guid","secondary_field","Pinned vendor GUID is an identity guard, not a model feature.")))
 ledger.sort(key=lambda r:(r["target_type"],r["target_id"],r["field_path"],r["source_id"],r["claim_locator"])); return targets,ledger
def apply_targets(targets):
 items={r["item_id"]:dict(r) for r in targets["items"]}; order=[r["item_id"] for r in targets["items"]]
 for iid,_vid,_guid,_vname,_vtype,name,category,currency,cost,event in ITEMS:
  items[iid]=item_row(iid,name,category,currency,cost,event)
  if iid not in order: order.append(iid)
 return {"items":[items[i] for i in order],"sources":source_rows(targets["sources"])}
def availability_rows():
 ranges={"days_of_treasure":("2025-03-03","2025-03-16"),"days_of_bloom":("2025-03-24","2025-04-13")}
 return [{"availability_id":f"availability_faq1381_{iid.removeprefix('item_')}","item_id":iid,"availability_status":"limited_time","start_date":ranges[event][0],"end_date":ranges[event][1],"event_id":None,"source_ids":[OFFICIAL_SOURCE],"last_verified_at":AS_OF,"verification_status":"verified"} for iid,*_,event in ITEMS]
def verify(root:Path,require_applied=True):
 targets,ledger=build(root); expected=apply_targets(targets); problems=[]
 if require_applied:
  for path,key in (("knowledge/items/items.jsonl","items"),("knowledge/sources/sources.jsonl","sources")):
   if read(root/path)!=expected[key]: problems.append("committed target differs from replayable apply contract: "+path)
  available={r["availability_id"]:r for r in read(root/"knowledge/acquisition/availability-events.jsonl")}
  for row in availability_rows():
   if available.get(row["availability_id"])!=row: problems.append("availability differs: "+row["availability_id"])
  ledger_path=root/"data/review/days-of-treasure-bloom-faq1381-core-six-canonical-evidence.jsonl"
  if not ledger_path.is_file() or read(ledger_path)!=ledger: problems.append("canonical field evidence differs from replayable source claims")
  for iid,*_ in ITEMS:
   item=next(r for r in expected["items"] if r["item_id"]==iid)
   if (item["availability_status"],item["permanent_account_item"],item["first_release_date"],item["model_feature_status"],item["set_ids"],item["visual_reference_ids"]) != ("unknown","unknown",None,declared_model_feature_status(iid),[],[]): problems.append("unsupported availability, permanence, first-release, visual, model promotion, or bundle membership"); break
 return problems
def main():
 parser=argparse.ArgumentParser(); parser.add_argument("--root",type=Path,default=ROOT); parser.add_argument("--apply",action="store_true"); args=parser.parse_args(); root=args.root.resolve()
 if args.apply:
  targets,ledger=build(root); output=apply_targets(targets)
  for path,key in (("knowledge/items/items.jsonl","items"),("knowledge/sources/sources.jsonl","sources")): write(root/path,output[key])
  available={r["availability_id"]:r for r in read(root/"knowledge/acquisition/availability-events.jsonl")}; available.update({r["availability_id"]:r for r in availability_rows()}); write(root/"knowledge/acquisition/availability-events.jsonl",sorted(available.values(),key=lambda r:r["availability_id"])); write(root/"data/review/days-of-treasure-bloom-faq1381-core-six-canonical-evidence.jsonl",ledger)
 problems=verify(root); print(json.dumps({"applied":args.apply,"valid":not problems,"problems":problems},sort_keys=True)); raise SystemExit(bool(problems))
if __name__=="__main__": main()
