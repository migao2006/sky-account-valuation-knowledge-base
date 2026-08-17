#!/usr/bin/env python3
"""Replay the bounded official FAQ 1343 Days of Moonlight 2024 core-three."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from tools.modeling.canonical_english_eligibility import declared_model_feature_status
from tools.normalize.apply_moomintroll_accessory_set_cohort import evidence, read, safe, sha, vendor, write
OFFICIAL_SOURCE="source_tgc_faq_1343_days_of_moonlight_core_three"; SECONDARY_SOURCE="source_skygame_data_1_3_4"
LINEAGE="lineage_tgc_support_faq_1343"; SECONDARY_LINEAGE="lineage_skygame_data_1_3_4"; AS_OF="2026-08-17"
OFFICIAL_PATH="data/source/research/tgc-faq-1343-days-of-moonlight-core-three.json"; SECONDARY_PATH="data/source/vendor/skygame-data-1.3.4-items.json"
OFFICIAL_SHA="0923938CFE1D3154F12B24489102BA78FD85BDFAD839026041549E048BE845ED"; SECONDARY_SHA="21CCAD77006C425B27EE9314870BB5BB77E8436459C6DA214ABCB2B0D8329BBB"
# id, vendor id, GUID, vendor title/type, official title, canonical category, currency, cost
ITEMS=(("item_days_of_moonlight_blossom_accessory",2308,"A4CTK7T9ea","Moonlight Blossom Accessory","HairAccessory","Moonlight Blossom Accessory","accessory","event_currency",17),("item_days_of_moonlight_lantern_decoration",2307,"vx4vxVJ0L1","Moonlight Lantern","Furniture","Moonlight Lantern Decoration","furniture","event_currency",32),("item_days_of_moonlight_earrings",2306,"XURacs6BHP","Moonlight Earrings","HeadAccessory","Moonlight Earrings","accessory","USD",2.99))
class DaysOfMoonlightEvidenceError(ValueError): pass
SOURCE_ROW={"source_id":OFFICIAL_SOURCE,"source_name":"thatgamecompany Help Center FAQ 1343 — Days of Moonlight 2024 core-three","source_type":"official_support","url":"https://thatgamecompany.helpshift.com/hc/en/17-sky-children-of-the-light/faq/1343-patch-notes---august-22-2024---0-26-5-280889-android-huawei-ios-steam-switch-282398-playstation/","retrieved_at":AS_OF,"evidence_level":"official_explicit","source_lineage_id":LINEAGE,"notes":"Fact-limited locally pinned transcription: Days of Moonlight 2024 Pacific window and three named individual costs only. It does not establish current availability, permanence, first release, Traditional Chinese names, images, visual matches, resale prices, or account ownership; the Frock and Updo bundle is excluded."}
def registry_contract(): return {"cohort_id":"canonical_cohort_days_of_moonlight_faq1343_core_three","evidence_path":"data/review/days-of-moonlight-faq1343-core-three-canonical-evidence.jsonl","snapshot_paths":[OFFICIAL_PATH,SECONDARY_PATH],"source_ids":[SECONDARY_SOURCE,OFFICIAL_SOURCE],"target_item_ids":sorted(x[0] for x in ITEMS),"target_set_ids":[]}
def valid_title_relation(official,vendor,vid=None): return (official,vendor,vid) in {(x[5],x[3],x[1]) for x in ITEMS}
def source_rows(rows):
 d={r["source_id"]:dict(r) for r in rows}
 if d.get(OFFICIAL_SOURCE) not in (None,SOURCE_ROW): raise DaysOfMoonlightEvidenceError("official source registry conflicts with cohort contract")
 d[OFFICIAL_SOURCE]=SOURCE_ROW; order=[r["source_id"] for r in rows]
 if OFFICIAL_SOURCE not in order: order.append(OFFICIAL_SOURCE)
 return [d[x] for x in order]
def item_row(iid,name,category,currency,cost): return {"item_id":iid,"canonical_name_zh_tw":f"待確認（{name}）","canonical_name_en":name,"aliases":[],"item_category":category,"item_subcategory":"days_of_moonlight_2024_historical_item","source_type":"event","source_id":OFFICIAL_SOURCE,"season_id":None,"event_id":None,"ancestor_id":None,"set_ids":[],"free_or_premium":"unknown","pass_required":"unknown","ultimate_reward":False,"collaboration":False,"permanent_account_item":"unknown","consumable":False,"original_currency":currency,"original_cost":cost,"availability_status":"unknown","first_release_date":None,"availability_event_ids":["availability_faq1343_days_of_moonlight_"+iid.removeprefix("item_")+"_historical"],"visual_reference_ids":[],"valuation_role":"collection_structure","source_ids":[OFFICIAL_SOURCE,SECONDARY_SOURCE],"last_verified_at":AS_OF,"verification_status":"verified","evidence_tier":"official_with_secondary","model_feature_status":declared_model_feature_status(iid),"notes":"FAQ 1343 establishes this named Days of Moonlight 2024 historical offer, exact cost, and Pacific event window only. The pinned vendor snapshot supplies exact vendor ID, GUID, title, and type. Moonlight Frock and Updo bundle, current availability, permanence, first release date, formal Traditional Chinese name, visual identity, resale price, and account ownership remain unknown or unasserted."}
def build(root):
 root=Path(root).resolve(); ob=safe(root,OFFICIAL_PATH).read_bytes(); sb=safe(root,SECONDARY_PATH).read_bytes(); official=json.loads(ob); secondary=json.loads(sb)
 if sha(ob)!=OFFICIAL_SHA or sha(sb)!=SECONDARY_SHA: raise DaysOfMoonlightEvidenceError("snapshot hash mismatch")
 expected=[{"item_id":x[0],"official_name_en":x[5],"original_currency":x[7],"original_cost":x[8]} for x in ITEMS]; facts=official.get("facts",{})
 if official.get("source_id")!=OFFICIAL_SOURCE or facts.get("items")!=expected or (facts.get("historical_window_start_date"),facts.get("historical_window_end_date"))!=("2024-09-16","2024-09-29"): raise DaysOfMoonlightEvidenceError("official FAQ 1343 contract changed")
 targets={k:read(root/p) for k,p in (("items","knowledge/items/items.jsonl"),("sources","knowledge/sources/sources.jsonl"))}; sources={r["source_id"]:r for r in source_rows(targets["sources"])}
 for sid,typ,lineage in ((OFFICIAL_SOURCE,"official_support",LINEAGE),(SECONDARY_SOURCE,"community_database",SECONDARY_LINEAGE)):
  if sources.get(sid,{}).get("source_type")!=typ or sources[sid].get("source_lineage_id")!=lineage: raise DaysOfMoonlightEvidenceError("source registry or lineage mismatch: "+sid)
 ledger=[]
 for n,(iid,vid,guid,vname,vtype,oname,category,currency,cost) in enumerate(ITEMS):
  vi,row=vendor(secondary,vid)
  if (row.get("guid"),row.get("name"),row.get("type"))!=(guid,vname,vtype): raise DaysOfMoonlightEvidenceError("secondary identity changed: "+str(vid))
  if not valid_title_relation(oname,vname,vid): raise DaysOfMoonlightEvidenceError("unsupported official/vendor title relation: "+str(vid))
  p=f"/facts/items/{n}"; relation="FAQ and vendor titles are byte-identical." if oname==vname else "FAQ/vendor wording is reconciled only by the explicit vendor-2307 suffix contract; vendor 1902 Held collision is rejected."
  ledger += [evidence("item",iid,"canonical_name_en",oname,OFFICIAL_SOURCE,LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,p+"/official_name_en","independent_identity",relation),evidence("item",iid,"original_currency",currency,OFFICIAL_SOURCE,LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,p+"/original_currency","independent_field","Historical cost/window only; no current availability, permanence, or model eligibility is inferred."),evidence("item",iid,"original_cost",cost,OFFICIAL_SOURCE,LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,p+"/original_cost","independent_field","Historical cost/window only; no current availability, permanence, or model eligibility is inferred."),evidence("item",iid,"availability_history",facts["historical_window_start_date"],OFFICIAL_SOURCE,LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,"/facts/historical_window_start_date","independent_field","Historical event-window start only."),evidence("item",iid,"availability_history",facts["historical_window_end_date"],OFFICIAL_SOURCE,LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,"/facts/historical_window_end_date","independent_field","Historical event-window end only."),evidence("item",iid,"vendor_item_name",vname,SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,sb,f"/items/{vi}/name","secondary_field","Pinned vendor spelling; title reconciliation is limited by this apply contract."),evidence("item",iid,"vendor_item_type",vtype,SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,sb,f"/items/{vi}/type","secondary_field",f"Apply contract maps vendor type to canonical category {category}."),evidence("item",iid,"vendor_item_guid",guid,SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,sb,f"/items/{vi}/guid","secondary_field","Pinned vendor GUID is an identity guard, not a model feature.")]
 ledger.sort(key=lambda r:(r["target_type"],r["target_id"],r["field_path"],r["source_id"],r["claim_locator"])); return targets,ledger
def output(targets):
 indexed={r["item_id"]:dict(r) for r in targets["items"]}; order=[r["item_id"] for r in targets["items"]]
 for iid,_a,_b,_c,_d,name,category,currency,cost in ITEMS: indexed[iid]=item_row(iid,name,category,currency,cost); order += [] if iid in order else [iid]
 return {"items":[indexed[x] for x in order],"sources":source_rows(targets["sources"])}
def availability_rows(): return [{"availability_id":"availability_faq1343_days_of_moonlight_"+iid.removeprefix("item_")+"_historical","item_id":iid,"availability_status":"limited_time","start_date":"2024-09-16","end_date":"2024-09-29","event_id":None,"source_ids":[OFFICIAL_SOURCE],"last_verified_at":AS_OF,"verification_status":"verified"} for iid,*_ in ITEMS]
def verify(root,require_applied=True):
 targets,ledger=build(root); expected=output(targets); problems=[]
 if require_applied:
  for p,k in (("knowledge/items/items.jsonl","items"),("knowledge/sources/sources.jsonl","sources")):
   if read(Path(root)/p)!=expected[k]: problems.append("committed target differs from replayable apply contract: "+p)
  available={r["availability_id"]:r for r in read(Path(root)/"knowledge/acquisition/availability-events.jsonl")}
  for r in availability_rows():
   if available.get(r["availability_id"])!=r: problems.append("availability differs: "+r["availability_id"])
  lp=Path(root)/"data/review/days-of-moonlight-faq1343-core-three-canonical-evidence.jsonl"
  if not lp.is_file() or read(lp)!=ledger: problems.append("canonical field evidence differs from replayable source claims")
 return problems
def main():
 p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,default=ROOT); p.add_argument("--apply",action="store_true"); a=p.parse_args(); root=a.root.resolve()
 if a.apply:
  targets,ledger=build(root); result=output(targets)
  for path,key in (("knowledge/items/items.jsonl","items"),("knowledge/sources/sources.jsonl","sources")): write(root/path,result[key])
  available={r["availability_id"]:r for r in read(root/"knowledge/acquisition/availability-events.jsonl")}; available.update({r["availability_id"]:r for r in availability_rows()}); write(root/"knowledge/acquisition/availability-events.jsonl",sorted(available.values(),key=lambda r:r["availability_id"])); write(root/"data/review/days-of-moonlight-faq1343-core-three-canonical-evidence.jsonl",ledger)
 problems=verify(root); print(json.dumps({"applied":a.apply,"valid":not problems,"problems":problems},sort_keys=True)); raise SystemExit(bool(problems))
if __name__=="__main__": main()
