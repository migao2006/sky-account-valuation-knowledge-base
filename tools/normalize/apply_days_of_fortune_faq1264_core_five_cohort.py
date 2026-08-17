#!/usr/bin/env python3
"""Replay the bounded FAQ 1264 Days of Fortune 2024 core-five cohort offline."""
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from tools.modeling.canonical_english_eligibility import declared_model_feature_status
from tools.normalize.apply_moomintroll_accessory_set_cohort import evidence,read,safe,sha,vendor,write

OFFICIAL_SOURCE="source_tgc_faq_1264_days_of_fortune_core_five"; SECONDARY_SOURCE="source_skygame_data_1_3_4"
OFFICIAL_LINEAGE="lineage_tgc_support_faq_1264"; SECONDARY_LINEAGE="lineage_skygame_data_1_3_4"
OFFICIAL_PATH="data/source/research/tgc-faq-1264-days-of-fortune-core-five.json"; SECONDARY_PATH="data/source/vendor/skygame-data-1.3.4-items.json"
OFFICIAL_SHA="9CAFE5829FBED211D55A14C3A095480C7A5E23FF66F9204C1569A067846E7C34"; SECONDARY_SHA="21CCAD77006C425B27EE9314870BB5BB77E8436459C6DA214ABCB2B0D8329BBB"; AS_OF="2026-08-17"
# canonical ID, vendor numeric ID, pinned GUID, official title, vendor title, type, category, historical currency/cost
ITEMS=(
 ("item_days_of_fortune_dragon_bangles",2055,"xsTxIqIX8E","Days of Fortune Dragon Bangles earrings","Fortune Dragon Bangles","HeadAccessory","accessory","USD",1.99),
 ("item_days_of_fortune_dragon_vestment",2053,"wkCxoe9zSP","Days of Fortune Dragon Vestment outfit","Fortune Dragon Vestment","OutfitShoes","outfit","USD",9.99),
 ("item_days_of_fortune_dragon_stole",2054,"LGaX4cqdOe","Days of Fortune Dragon Stole cape","Fortune Dragon Stole","Cape","cape","USD",14.99),
 ("item_fortune_dragon_mask",2056,"OFwVuPWmfK","Fortune Dragon Mask","Fortune Dragon Mask","Mask","mask","event_currency",14),
 ("item_fortune_drum",2057,"8KXtBlvNRO","Fortune Drum","Fortune Drum","Held","prop","event_currency",34),
)
SOURCE_ROW={"source_id":OFFICIAL_SOURCE,"source_name":"thatgamecompany Help Center FAQ 1264 — Patch Notes, January 11, 2024 (Days of Fortune 2024)","source_type":"official_support","url":"https://thatgamecompany.helpshift.com/hc/en/17-sky-children-of-the-light/faq/1264-patch-notes---january-11-2024---0-24-0-240551-ios-playstation-switch-241911-android-huawei/","retrieved_at":AS_OF,"evidence_level":"official_explicit","source_lineage_id":OFFICIAL_LINEAGE,"notes":"Fact-limited locally pinned transcription: Days of Fortune 2024 historical window and five named new-item costs only. It does not establish current availability, return policy, permanent ownership, images, formal Traditional Chinese names, or first release dates."}
class DaysOfFortuneEvidenceError(ValueError): pass
def registry_contract(): return {"cohort_id":"canonical_cohort_days_of_fortune_faq1264_core_five","evidence_path":"data/review/days-of-fortune-faq1264-core-five-canonical-evidence.jsonl","snapshot_paths":[OFFICIAL_PATH,SECONDARY_PATH],"source_ids":[SECONDARY_SOURCE,OFFICIAL_SOURCE],"target_item_ids":sorted(x[0] for x in ITEMS),"target_set_ids":[]}
def source_rows(rows):
 out={r["source_id"]:dict(r) for r in rows}; old=out.get(OFFICIAL_SOURCE)
 if old is not None and old!=SOURCE_ROW: raise DaysOfFortuneEvidenceError("official source registry conflicts with cohort contract")
 out[OFFICIAL_SOURCE]=SOURCE_ROW; order=[r["source_id"] for r in rows]
 if OFFICIAL_SOURCE not in order: order.append(OFFICIAL_SOURCE)
 return [out[x] for x in order]
def valid_title_relation(official,vendor_name):
 # Only the three pinned FAQ-to-vendor changes are accepted: Days of prefix and a category noun.
 return (official,vendor_name) in {("Days of Fortune Dragon Bangles earrings","Fortune Dragon Bangles"),("Days of Fortune Dragon Vestment outfit","Fortune Dragon Vestment"),("Days of Fortune Dragon Stole cape","Fortune Dragon Stole"),("Fortune Dragon Mask","Fortune Dragon Mask"),("Fortune Drum","Fortune Drum")}
def item_row(iid,name,category,currency,cost):
 return {"item_id":iid,"canonical_name_zh_tw":f"待確認（{name}）","canonical_name_en":name,"aliases":[],"item_category":category,"item_subcategory":"days_of_fortune_2024_historical_item","source_type":"event","source_id":OFFICIAL_SOURCE,"season_id":None,"event_id":None,"ancestor_id":None,"set_ids":[],"free_or_premium":"unknown","pass_required":"unknown","ultimate_reward":False,"collaboration":False,"permanent_account_item":"unknown","consumable":False,"original_currency":currency,"original_cost":cost,"availability_status":"unknown","first_release_date":None,"availability_event_ids":["availability_days_of_fortune_faq1264_"+iid.removeprefix("item_")],"visual_reference_ids":[],"valuation_role":"collection_structure","source_ids":[OFFICIAL_SOURCE,SECONDARY_SOURCE],"last_verified_at":AS_OF,"verification_status":"verified","evidence_tier":"official_with_secondary","model_feature_status":declared_model_feature_status(iid),"notes":"FAQ 1264 establishes this named Days of Fortune 2024 historical offer and event window only; the pinned vendor snapshot independently supplies exact vendor ID, GUID, title, and type. Current availability, return policy, permanent-account property, formal Traditional Chinese name, visual identity, first release date, and model eligibility remain unknown or unasserted. This is a bounded five-item FAQ slice, not a bundle or complete Days of Fortune catalog."}
def build(root:Path):
 root=root.resolve(); ob=safe(root,OFFICIAL_PATH).read_bytes(); sb=safe(root,SECONDARY_PATH).read_bytes()
 if sha(ob)!=OFFICIAL_SHA or sha(sb)!=SECONDARY_SHA: raise DaysOfFortuneEvidenceError("official or secondary snapshot hash mismatch")
 official,secondary=json.loads(ob),json.loads(sb); facts=official.get("facts",{})
 expected=[{"item_id":x[0],"official_name_en":x[3],"original_currency":x[7],"original_cost":x[8]} for x in ITEMS]
 if official.get("source_id")!=OFFICIAL_SOURCE or facts.get("new_items")!=expected or (facts.get("historical_window_start_date"),facts.get("historical_window_end_date"))!=("2024-01-29","2024-02-11"): raise DaysOfFortuneEvidenceError("official FAQ 1264 contract changed")
 targets={n:read(root/p) for n,p in (("items","knowledge/items/items.jsonl"),("sources","knowledge/sources/sources.jsonl"))}; sources={r["source_id"]:r for r in source_rows(targets["sources"])}
 for sid,typ,lineage in ((OFFICIAL_SOURCE,"official_support",OFFICIAL_LINEAGE),(SECONDARY_SOURCE,"community_database",SECONDARY_LINEAGE)):
  if sources.get(sid,{}).get("source_type")!=typ or sources[sid].get("source_lineage_id")!=lineage: raise DaysOfFortuneEvidenceError("source registry or lineage mismatch: "+sid)
 ledger=[]
 for i,(iid,vid,guid,official_name,vendor_name,vtype,category,currency,cost) in enumerate(ITEMS):
  vi,vr=vendor(secondary,vid)
  if (vr.get("guid"),vr.get("name"),vr.get("type"))!=(guid,vendor_name,vtype): raise DaysOfFortuneEvidenceError("secondary identity changed: "+str(vid))
  if not valid_title_relation(official_name,vendor_name): raise DaysOfFortuneEvidenceError("unsupported official/vendor title relation: "+str(vid))
  p=f"/facts/new_items/{i}"; note="Historical FAQ cost/window only; no current availability, permanence, or model eligibility is inferred."
  ledger += [evidence("item",iid,"canonical_name_en",official_name,OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,p+"/official_name_en","independent_identity","FAQ exact title; only the explicit Days of prefix/category-word relation to the pinned vendor title is allowed."),evidence("item",iid,"original_currency",currency,OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,p+"/original_currency","independent_field",note),evidence("item",iid,"original_cost",cost,OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,p+"/original_cost","independent_field",note),evidence("item",iid,"availability_history",facts["historical_window_start_date"],OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,"/facts/historical_window_start_date","independent_field",note),evidence("item",iid,"availability_history",facts["historical_window_end_date"],OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,"/facts/historical_window_end_date","independent_field",note),evidence("item",iid,"vendor_item_name",vendor_name,SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,sb,f"/items/{vi}/name","secondary_field","Pinned vendor spelling; title reconciliation is limited by the apply contract."),evidence("item",iid,"vendor_item_type",vtype,SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,sb,f"/items/{vi}/type","secondary_field",f"Apply contract maps vendor type to canonical category {category}."),evidence("item",iid,"vendor_item_guid",guid,SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,sb,f"/items/{vi}/guid","secondary_field","Pinned vendor GUID is an identity guard, not a model feature.")]
 ledger.sort(key=lambda r:(r["target_type"],r["target_id"],r["field_path"],r["source_id"],r["claim_locator"])); return targets,ledger
def apply_targets(targets):
 items={r["item_id"]:dict(r) for r in targets["items"]}
 for iid,_v,_g,name,_n,_t,category,currency,cost in ITEMS: items[iid]=item_row(iid,name,category,currency,cost)
 order=[r["item_id"] for r in targets["items"]]; order += [x[0] for x in ITEMS if x[0] not in order]
 return {"items":[items[x] for x in order],"sources":source_rows(targets["sources"])}
def availability_rows(): return [{"availability_id":"availability_days_of_fortune_faq1264_"+iid.removeprefix("item_"),"item_id":iid,"availability_status":"limited_time","start_date":"2024-01-29","end_date":"2024-02-11","event_id":None,"source_ids":[OFFICIAL_SOURCE],"last_verified_at":AS_OF,"verification_status":"verified"} for iid,*_ in ITEMS]
def verify(root:Path,require_applied=True):
 targets,ledger=build(root); expected=apply_targets(targets); bad=[]
 if require_applied:
  for rel,key in (("knowledge/items/items.jsonl","items"),("knowledge/sources/sources.jsonl","sources")):
   if read(root/rel)!=expected[key]: bad.append("committed target differs from replayable apply contract: "+rel)
  available={r["availability_id"]:r for r in read(root/"knowledge/acquisition/availability-events.jsonl")}
  for row in availability_rows():
   if available.get(row["availability_id"])!=row: bad.append("availability differs: "+row["availability_id"])
  p=root/"data/review/days-of-fortune-faq1264-core-five-canonical-evidence.jsonl"
  if not p.is_file() or read(p)!=ledger: bad.append("canonical field evidence differs from replayable source claims")
  for iid,*_ in ITEMS:
   row=next(r for r in expected["items"] if r["item_id"]==iid)
   if (row["availability_status"],row["permanent_account_item"],row["first_release_date"],row["model_feature_status"],row["set_ids"]) != ("unknown","unknown",None,declared_model_feature_status(iid),[]): bad.append("unsupported availability, permanence, first-release, model promotion, or bundle membership"); break
 return bad
def main():
 p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,default=ROOT); p.add_argument("--apply",action="store_true"); a=p.parse_args(); root=a.root.resolve()
 if a.apply:
  targets,ledger=build(root); out=apply_targets(targets)
  for rel,key in (("knowledge/items/items.jsonl","items"),("knowledge/sources/sources.jsonl","sources")): write(root/rel,out[key])
  avail={r["availability_id"]:r for r in read(root/"knowledge/acquisition/availability-events.jsonl")}; avail.update({r["availability_id"]:r for r in availability_rows()}); write(root/"knowledge/acquisition/availability-events.jsonl",sorted(avail.values(),key=lambda r:r["availability_id"]))
  write(root/"data/review/days-of-fortune-faq1264-core-five-canonical-evidence.jsonl",ledger)
 bad=verify(root); print(json.dumps({"applied":a.apply,"valid":not bad,"problems":bad},sort_keys=True)); raise SystemExit(bool(bad))
if __name__=="__main__": main()
