#!/usr/bin/env python3
"""Replay the bounded FAQ 1308 Cinnamoroll Pop-Up Cafe cohort offline."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
from tools.normalize.apply_moomintroll_accessory_set_cohort import chash, evidence, read, safe, sha, vendor, write
from tools.modeling.canonical_english_eligibility import declared_model_feature_status

OFFICIAL_SOURCE="source_tgc_faq_1308_cinnamoroll_popup_cafe"; SECONDARY_SOURCE="source_skygame_data_1_3_4"
OFFICIAL_LINEAGE="lineage_tgc_support_faq_1308"; SECONDARY_LINEAGE="lineage_skygame_data_1_3_4"
OFFICIAL_PATH="data/source/research/tgc-faq-1308-cinnamoroll-popup-cafe.json"; SECONDARY_PATH="data/source/vendor/skygame-data-1.3.4-items.json"
OFFICIAL_SHA="2C62638C940D280F6561D530BD25A082A2FC9B0547EEE74685D43AFC50050442"; SECONDARY_SHA="21CCAD77006C425B27EE9314870BB5BB77E8436459C6DA214ABCB2B0D8329BBB"; AS_OF="2026-08-17"
IAP_SET="set_cinnamoroll_popup_cafe_iap"
IAP_SUBCATEGORY="collaboration_iap"
ADDITIONAL_SUBCATEGORY="collaboration_additional"
ITEMS=(
 ("item_cinnamoroll_mini_companion",2141,"Cinnamoroll Mini Companion","HairAccessory","accessory",None),
 ("item_cinnamoroll_bowtie",2142,"Cinnamoroll Bowtie","Necklace","accessory",IAP_SET),
 ("item_cinnamoroll_cloud_cape",2143,"Cinnamoroll Cloud Cape","Cape","cape",IAP_SET),
 ("item_cinnamoroll_plush",2146,"Cinnamoroll Plushie","Prop","prop",None),
 ("item_cinnamoroll_cozy_teacup_headband",2147,"Cozy Teacup Headband","HairAccessory","accessory",None),
 ("item_cinnamoroll_cozy_cafe_table",2148,"Cozy Cafe Table","Furniture","furniture",None),
)
OFFICIAL_SOURCE_ROW={"source_id":OFFICIAL_SOURCE,"source_name":"thatgamecompany Help Center FAQ 1308 — Patch Notes, April 10, 2024 (Cinnamoroll Pop-Up Cafe)","source_type":"official_support","url":"https://thatgamecompany.helpshift.com/hc/en/17-sky-children-of-the-light/faq/1308-patch-notes---april-10-2024---0-25-0-257483-android-huawei-256148-ios-playstation-257607-pc-255731-switch/","retrieved_at":AS_OF,"evidence_level":"official_explicit","source_lineage_id":OFFICIAL_LINEAGE,"notes":"Fact-limited locally pinned transcription: Cinnamoroll Pop-Up Cafe historical window, four paid offers, their stated USD prices, and FAQ return-plan wording only. It does not establish current availability, individual bundle prices, permanent ownership, images, or Traditional Chinese names."}
class CinnamorollEvidenceError(ValueError): pass

def registry_contract()->dict[str,object]: return {"cohort_id":"canonical_cohort_cinnamoroll_popup_cafe_faq1308","evidence_path":"data/review/cinnamoroll-popup-cafe-faq1308-canonical-evidence.jsonl","snapshot_paths":[OFFICIAL_PATH,SECONDARY_PATH],"source_ids":[SECONDARY_SOURCE,OFFICIAL_SOURCE],"target_item_ids":sorted(x[0] for x in ITEMS),"target_set_ids":[IAP_SET]}
def source_rows(rows:list[dict[str,Any]])->list[dict[str,Any]]:
 out={r["source_id"]:dict(r) for r in rows}; current=out.get(OFFICIAL_SOURCE)
 if current is not None and current != OFFICIAL_SOURCE_ROW: raise CinnamorollEvidenceError("official source registry conflicts with cohort contract")
 out[OFFICIAL_SOURCE]=OFFICIAL_SOURCE_ROW
 order=[r["source_id"] for r in rows];
 if OFFICIAL_SOURCE not in order: order.append(OFFICIAL_SOURCE)
 return [out[x] for x in order]
def acquisition_taxonomy_note(currency:str)->str:
 if currency=="USD": return "Historical paid USD offer; canonical item_subcategory remains collaboration_iap."
 return "Historical event-currency offer; canonical item_subcategory is collaboration_additional, not collaboration_iap."
def item_row(iid:str,name:str,category:str,set_id:str|None)->dict[str,Any]:
 cost={"item_cinnamoroll_mini_companion":("USD",6.99),"item_cinnamoroll_plush":("USD",14.99),"item_cinnamoroll_cozy_teacup_headband":("event_currency",22),"item_cinnamoroll_cozy_cafe_table":("event_currency",52)}.get(iid,("USD","bundle_only"))
 subcategory=IAP_SUBCATEGORY if cost[0]=="USD" else ADDITIONAL_SUBCATEGORY
 return {"item_id":iid,"canonical_name_zh_tw":f"待確認（{name}）","canonical_name_en":name,"aliases":[],"item_category":category,"item_subcategory":subcategory,"source_type":"collaboration","source_id":OFFICIAL_SOURCE,"season_id":None,"event_id":None,"ancestor_id":None,"set_ids":[] if set_id is None else [set_id],"free_or_premium":"unknown","pass_required":"unknown","ultimate_reward":False,"collaboration":True,"permanent_account_item":"unknown","consumable":False,"original_currency":cost[0],"original_cost":cost[1],"availability_status":"unknown","first_release_date":None,"availability_event_ids":["availability_cinnamoroll_faq1308_"+iid.removeprefix("item_cinnamoroll_")],"visual_reference_ids":[],"valuation_role":"collection_structure","source_ids":[OFFICIAL_SOURCE,SECONDARY_SOURCE],"last_verified_at":AS_OF,"verification_status":"verified","evidence_tier":"official_with_secondary","model_feature_status":declared_model_feature_status(iid),"notes":"FAQ 1308 establishes a historical Cinnamoroll Pop-Up Cafe offer and event window only; the pinned vendor snapshot supplies exact title and type. Current availability, permanent-account property, formal Traditional Chinese name, and visual identity remain unknown. Bundle price is never allocated to an individual member. "+acquisition_taxonomy_note(cost[0])}
def build(root:Path)->tuple[dict[str,list[dict[str,Any]]],list[dict[str,Any]]]:
 root=root.resolve(); ob=safe(root,OFFICIAL_PATH).read_bytes(); sb=safe(root,SECONDARY_PATH).read_bytes()
 if sha(ob)!=OFFICIAL_SHA: raise CinnamorollEvidenceError("official snapshot hash mismatch")
 if sha(sb)!=SECONDARY_SHA: raise CinnamorollEvidenceError("secondary snapshot hash mismatch")
 official=json.loads(ob); secondary=json.loads(sb); facts=official.get("facts",{}); offers=facts.get("paid_offers",[])+facts.get("event_currency_offers",[])
 expected=[("cinnamoroll_mini_companion",6.99,["item_cinnamoroll_mini_companion"]),("cinnamoroll_bowtie_cloud_cape",14.99,["item_cinnamoroll_bowtie","item_cinnamoroll_cloud_cape"]),("cinnamoroll_combo",14.99,["item_cinnamoroll_swirled_hair","item_cinnamoroll_ears"]),("cinnamoroll_plushie",14.99,["item_cinnamoroll_plush"])]
 if official.get("source_id")!=OFFICIAL_SOURCE or (facts.get("historical_window_start_date"),facts.get("historical_window_end_date"))!=("2024-04-27","2024-05-17") or [(x.get("offer_id"),x.get("original_cost"),x.get("item_ids")) for x in facts.get("paid_offers",[]) ]!=expected or len(facts.get("event_currency_offers",[]))!=2: raise CinnamorollEvidenceError("official FAQ 1308 contract changed")
 targets={n:read(root/p) for n,p in (("items","knowledge/items/items.jsonl"),("sets","knowledge/sets/item-sets.jsonl"),("sources","knowledge/sources/sources.jsonl"))}; sources={r["source_id"]:r for r in source_rows(targets["sources"])}
 for sid,typ,lineage in ((OFFICIAL_SOURCE,"official_support",OFFICIAL_LINEAGE),(SECONDARY_SOURCE,"community_database",SECONDARY_LINEAGE)):
  if sources.get(sid,{}).get("source_type")!=typ or sources[sid].get("source_lineage_id")!=lineage: raise CinnamorollEvidenceError("source registry or lineage mismatch: "+sid)
 ledger=[]
 offer_by_item={iid:(n,o) for n,o in enumerate(offers) for iid in o["item_ids"]}
 for iid,vid,name,vtype,category,set_id in ITEMS:
  vi,vr=vendor(secondary,vid)
  if vr.get("name")!=name or vr.get("type")!=vtype: raise CinnamorollEvidenceError("secondary identity changed: "+str(vid))
  oi,offer=offer_by_item[iid]; prefix=(f"/facts/paid_offers/{oi}" if oi < len(facts["paid_offers"]) else f"/facts/event_currency_offers/{oi-len(facts['paid_offers'])}")
  ledger += [evidence("item",iid,"availability_history",facts["historical_window_start_date"],OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,"/facts/historical_window_start_date","independent_field","Historical window only; current availability stays unknown."),evidence("item",iid,"availability_history",facts["historical_window_end_date"],OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,"/facts/historical_window_end_date","independent_field","Historical window only; current availability stays unknown."),evidence("item",iid,"vendor_item_name",name,SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,sb,f"/items/{vi}/name","secondary_field"),evidence("item",iid,"vendor_item_type",vtype,SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,sb,f"/items/{vi}/type","secondary_field",f"Apply contract maps vendor type to {category}.")]
  if len(offer["item_ids"])==1:
   taxonomy_note=acquisition_taxonomy_note(offer["original_currency"])
   ledger += [evidence("item",iid,"identity_description",offer["official_name_en"],OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,prefix+"/official_name_en","independent_identity",taxonomy_note),evidence("item",iid,"original_cost",offer["original_cost"],OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,prefix+"/original_cost","independent_field",taxonomy_note+" Historical individual offer price only.")]
 for sid,members in ((IAP_SET,["item_cinnamoroll_bowtie","item_cinnamoroll_cloud_cape"]),):
  oi=next(i for i,o in enumerate(offers) if o["item_ids"]==members); p=f"/facts/paid_offers/{oi}"; o=offers[oi]
  ledger += [evidence("set",sid,"identity_description",o["official_name_en"],OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,p+"/official_name_en","independent_identity"),evidence("set",sid,"scope_definition",members,OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,p+"/item_ids","independent_field"),evidence("set",sid,"historical_pack_price_usd",o["original_cost"],OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,p+"/original_cost","independent_field","Historical bundle price; never allocated to members.")]
 ledger.sort(key=lambda r:(r["target_type"],r["target_id"],r["field_path"],r["source_id"],r["claim_locator"])); return targets,ledger
def apply_targets(targets:dict[str,list[dict[str,Any]]])->dict[str,list[dict[str,Any]]]:
 items={r["item_id"]:dict(r) for r in targets["items"]}
 for excluded in ("item_cinnamoroll_swirled_hair","item_cinnamoroll_ears"): items.pop(excluded,None)
 for iid,_v,name,_vt,cat,set_id in ITEMS: items[iid]=item_row(iid,name,cat,set_id)
 order=[r["item_id"] for r in targets["items"] if r["item_id"] not in {"item_cinnamoroll_swirled_hair","item_cinnamoroll_ears"}]+[iid for iid,*_ in ITEMS if iid not in {r["item_id"] for r in targets["items"]}]
 sets={r["set_id"]:dict(r) for r in targets["sets"]}; sets.pop("set_cinnamoroll_popup_cafe_combo",None); sets[IAP_SET]={"set_id":IAP_SET,"canonical_name_zh_tw":"待確認（Cinnamoroll Pop-Up Cafe Bowtie and Cloud Cape）","canonical_name_en":"Cinnamoroll Pop-Up Cafe Bowtie and Cloud Cape","set_type":"bundle","required_item_ids":["item_cinnamoroll_bowtie","item_cinnamoroll_cloud_cape"],"optional_item_ids":[],"source_ids":[OFFICIAL_SOURCE,SECONDARY_SOURCE],"last_verified_at":AS_OF,"verification_status":"verified"}
 set_order=[r["set_id"] for r in targets["sets"] if r["set_id"]!="set_cinnamoroll_popup_cafe_combo"]
 return {"items":[items[x] for x in order],"sets":[sets[x] for x in set_order],"sources":source_rows(targets["sources"])}
def availability_rows(): return [{"availability_id":"availability_cinnamoroll_faq1308_"+iid.removeprefix("item_cinnamoroll_"),"item_id":iid,"availability_status":"limited_time","start_date":"2024-04-27","end_date":"2024-05-17","event_id":None,"source_ids":[OFFICIAL_SOURCE],"last_verified_at":AS_OF,"verification_status":"verified"} for iid,*_ in ITEMS]
def verify(root:Path,require_applied:bool=True)->list[str]:
 targets,ledger=build(root); expected=apply_targets(targets); bad=[]
 if require_applied:
  for rel,key in (("knowledge/items/items.jsonl","items"),("knowledge/sets/item-sets.jsonl","sets"),("knowledge/sources/sources.jsonl","sources")):
   if read(root/rel)!=expected[key]: bad.append("committed target differs from replayable apply contract: "+rel)
  available={r["availability_id"]:r for r in read(root/"knowledge/acquisition/availability-events.jsonl")}
  for row in availability_rows():
   if available.get(row["availability_id"])!=row: bad.append("availability differs: "+row["availability_id"])
  if not (root/"data/review/cinnamoroll-popup-cafe-faq1308-canonical-evidence.jsonl").is_file() or read(root/"data/review/cinnamoroll-popup-cafe-faq1308-canonical-evidence.jsonl")!=ledger: bad.append("canonical field evidence differs from replayable source claims")
  for iid,*_ in ITEMS:
   row=next(r for r in expected["items"] if r["item_id"]==iid)
   expected_subcategory=IAP_SUBCATEGORY if row["original_currency"]=="USD" else ADDITIONAL_SUBCATEGORY
   if row["item_subcategory"]!=expected_subcategory: bad.append("acquisition taxonomy disagrees with historical currency: "+iid);break
   if row["availability_status"]!="unknown" or row["permanent_account_item"]!="unknown" or row["first_release_date"] is not None or row["model_feature_status"]!=declared_model_feature_status(iid): bad.append("unsupported availability, permanence, first-release, or model promotion");break
 return bad
def main():
 p=argparse.ArgumentParser();p.add_argument("--root",type=Path,default=ROOT);p.add_argument("--apply",action="store_true");a=p.parse_args();root=a.root.resolve()
 if a.apply:
  targets,ledger=build(root);out=apply_targets(targets)
  for rel,key in (("knowledge/items/items.jsonl","items"),("knowledge/sets/item-sets.jsonl","sets"),("knowledge/sources/sources.jsonl","sources")): write(root/rel,out[key])
  available={r["availability_id"]:r for r in read(root/"knowledge/acquisition/availability-events.jsonl")};available.pop("availability_cinnamoroll_faq1308_swirled_hair",None);available.pop("availability_cinnamoroll_faq1308_ears",None);available.update({r["availability_id"]:r for r in availability_rows()});write(root/"knowledge/acquisition/availability-events.jsonl",sorted(available.values(),key=lambda r:r["availability_id"]))
  write(root/"data/review/cinnamoroll-popup-cafe-faq1308-canonical-evidence.jsonl",ledger)
 bad=verify(root);print(json.dumps({"applied":a.apply,"valid":not bad,"problems":bad},ensure_ascii=False,sort_keys=True));raise SystemExit(bool(bad))
if __name__=="__main__":main()
