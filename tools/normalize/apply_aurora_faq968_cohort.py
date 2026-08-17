#!/usr/bin/env python3
"""Replay the bounded, offline FAQ 968 AURORA evidence cohort.

It is deliberately fail-closed: both source bytes and every JSON-pointer claim
are pinned before it writes.  FAQ 968 proves only this six-item slice, never a
complete AURORA catalog or present availability.
"""
from __future__ import annotations
import argparse, hashlib, json, sys
from pathlib import Path
from typing import Any

REPOSITORY_ROOT=Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path: sys.path.insert(0,str(REPOSITORY_ROOT))
from tools.modeling.canonical_english_eligibility import declared_model_feature_status

OFFICIAL_SOURCE="source_tgc_faq_968_aurora_remaining_iap"; SECONDARY_SOURCE="source_skygame_data_1_3_4"
OFFICIAL_LINEAGE="lineage_tgc_support_faq_968"; SECONDARY_LINEAGE="lineage_skygame_data_1_3_4"
OFFICIAL_PATH="data/source/research/tgc-faq-968-aurora-remaining-iap.json"; SECONDARY_PATH="data/source/vendor/skygame-data-1.3.4-items.json"
OFFICIAL_SNAPSHOT_SHA256="85F610DC391DA37754061F9B205F51A9A2705F087FD03C844D2BBA983DD15C1C"; SECONDARY_SNAPSHOT_SHA256="21CCAD77006C425B27EE9314870BB5BB77E8436459C6DA214ABCB2B0D8329BBB"
AS_OF="2026-08-17"; SET_ID="set_aurora_iap"
# id, vendor id, canonical exact title, category, official list, money field, price, historical start
ITEMS=(
 ("item_aurora_voice",1558,"Voice of AURORA","instrument","remaining_seasonal_iap","original_cost",14.99,None),
 ("item_aurora_wings",1560,"Wings of AURORA","cape","remaining_seasonal_iap","original_cost",24.99,None),
 ("item_aurora_cure_for_me_mask",573,"Cure For Me Mask","mask","cure_for_me_unlocks","original_cost",50,None),
 ("item_aurora_cure_for_me_outfit",572,"Cure For Me Outfit","outfit","cure_for_me_unlocks","original_cost",200,None),
 ("item_aurora_to_the_love_outfit",1557,"To the Love Outfit","outfit","remaining_seasonal_iap","original_cost",9.99,"2022-12-08"),
 ("item_aurora_giving_in_cape",1559,"Giving In Cape","cape","remaining_seasonal_iap","original_cost",14.99,"2022-12-08"),
)
IAP_IDS={"item_aurora_voice","item_aurora_wings","item_aurora_to_the_love_outfit","item_aurora_giving_in_cape"}
def registry_contract()->dict[str,object]:
 return {"cohort_id":"canonical_cohort_aurora_faq968","evidence_path":"data/review/aurora-faq968-canonical-evidence.jsonl","snapshot_paths":[OFFICIAL_PATH,SECONDARY_PATH],"source_ids":[SECONDARY_SOURCE,OFFICIAL_SOURCE],"target_item_ids":sorted(item_id for item_id,*_rest in ITEMS),"target_set_ids":[SET_ID]}
class AuroraEvidenceError(ValueError): pass
def sha(v:bytes|str)->str:
 if isinstance(v,str): v=v.encode()
 return hashlib.sha256(v).hexdigest().upper()
def chash(v:Any)->str: return sha(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")))
def read(path:Path)->list[dict[str,Any]]: return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
def write(path:Path,rows:list[dict[str,Any]])->None: path.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in rows),encoding="utf-8",newline="\n")
def safe(root:Path,rel:str)->Path:
 p=(root/rel).resolve()
 if root.resolve() not in p.parents or not p.is_file(): raise AuroraEvidenceError(f"snapshot unavailable or escapes root: {rel}")
 return p
def ptr(doc:Any,loc:str)->Any:
 if not loc.startswith("/"): raise AuroraEvidenceError(f"invalid JSON pointer: {loc!r}")
 cur=doc
 for part in loc[1:].split("/"):
  part=part.replace("~1","/").replace("~0","~")
  try: cur=cur[int(part)] if isinstance(cur,list) else cur[part]
  except (KeyError,IndexError,ValueError,TypeError) as exc: raise AuroraEvidenceError(f"unresolved JSON pointer: {loc!r}") from exc
 return cur
def eid(target:str,field:str,source:str,locator:str,value:Any)->str: return "canonical_evidence_"+hashlib.sha256(f"{target}\0{field}\0{source}\0{locator}\0{chash(value)}".encode()).hexdigest()[:24]
def ev(target_type:str,target_id:str,field:str,value:Any,source:str,lineage:str,tier:str,path:str,raw:bytes,loc:str,role:str,notes:str="")->dict[str,Any]:
 found=ptr(json.loads(raw.decode("utf-8")),loc)
 if found!=value: raise AuroraEvidenceError(f"claim does not equal source locator: {target_id}:{field}")
 return {"evidence_id":eid(target_id,field,source,loc,value),"target_type":target_type,"target_id":target_id,"field_path":field,"claim_value":value,"claim_hash":chash(value),"source_id":source,"source_lineage_id":lineage,"source_tier":tier,"source_snapshot_path":path,"source_snapshot_bytes":len(raw),"source_snapshot_hash":sha(raw),"claim_locator":loc,"claim_locator_hash":chash(found),"evidence_role":role,"review_status":"approved","reviewed_at":AS_OF,"notes":notes}
def vendor(doc:dict[str,Any],vid:int)->tuple[int,dict[str,Any]]:
 for index,row in enumerate(doc["items"]):
  if row.get("id")==vid:return index,row
 raise AuroraEvidenceError(f"pinned secondary item missing: {vid}")
def build(root:Path)->tuple[dict[str,list[dict[str,Any]]],list[dict[str,Any]]]:
 root=root.resolve(); ob=safe(root,OFFICIAL_PATH).read_bytes(); sb=safe(root,SECONDARY_PATH).read_bytes()
 if sha(ob)!=OFFICIAL_SNAPSHOT_SHA256: raise AuroraEvidenceError("official snapshot hash mismatch")
 if sha(sb)!=SECONDARY_SNAPSHOT_SHA256: raise AuroraEvidenceError("secondary snapshot hash mismatch")
 official=json.loads(ob); secondary=json.loads(sb)
 if official.get("source_id")!=OFFICIAL_SOURCE: raise AuroraEvidenceError("official source contract changed")
 rows={r["item_id"]:r for r in read(root/"knowledge/items/items.jsonl")}; sets={r["set_id"]:r for r in read(root/"knowledge/sets/item-sets.jsonl")}
 sources={r["source_id"]:r for r in read(root/"knowledge/sources/sources.jsonl")}
 for source_id,source_type,lineage in ((OFFICIAL_SOURCE,"official_support",OFFICIAL_LINEAGE),(SECONDARY_SOURCE,"community_database",SECONDARY_LINEAGE)):
  existing=sources.get(source_id)
  if existing is None or existing.get("source_type")!=source_type or existing.get("source_lineage_id")!=lineage: raise AuroraEvidenceError(f"source registry or lineage mismatch: {source_id}")
 if SET_ID not in sets: raise AuroraEvidenceError("canonical AURORA IAP set missing")
 evidence=[]
 for item_id,vid,name,category,list_key,_field,price,start in ITEMS:
  vi,vr=vendor(secondary,vid)
  if str(vr.get("name","")).casefold()!=name.casefold(): raise AuroraEvidenceError(f"secondary name changed: {vid}")
  got_category="instrument" if (vr.get("type"),vr.get("subtype"))==("Held","Instrument") else str(vr.get("type","")).casefold()
  if got_category!=category: raise AuroraEvidenceError(f"secondary type changed: {vid}")
  source_entries=official["facts"][list_key]; oi=next((i for i,x in enumerate(source_entries) if x["official_name_en"].casefold()==name.casefold()),None)
  if oi is None: raise AuroraEvidenceError(f"official item identity missing: {item_id}")
  official_name=source_entries[oi]["official_name_en"]; price_key="price_usd" if list_key=="remaining_seasonal_iap" else "price_candles"
  if source_entries[oi].get(price_key)!=price: raise AuroraEvidenceError(f"official price changed: {item_id}")
  evidence.extend([
   ev("item",item_id,"canonical_name_en",official_name,OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,f"/facts/{list_key}/{oi}/official_name_en","independent_identity","FAQ 968 exact item wording; vendor supplies any title-casing normalization."),
   ev("item",item_id,"original_cost",price,OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,f"/facts/{list_key}/{oi}/{price_key}","independent_field","FAQ 968 stated historical price; no current price is inferred."),
   ev("item",item_id,"vendor_item_name",vr.get("name"),SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,sb,f"/items/{vi}/name","secondary_field","Exact vendor wording; the official FAQ controls canonical wording where title case differs."),
   ev("item",item_id,"item_category",vr.get("subtype") if category=="instrument" else vr.get("type"),SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,sb,f"/items/{vi}/subtype" if category=="instrument" else f"/items/{vi}/type","secondary_field",f"Apply contract maps this vendor type to canonical category {category}.")])
  if start:
   evidence.append(ev("item",item_id,"availability_history",official["facts"]["availability_context"]["to_the_love_and_giving_in_available_at"],OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,"/facts/availability_context/to_the_love_and_giving_in_available_at","independent_field","Historical opening context only; current availability stays unknown."))
  evidence.append(ev("item",item_id,"availability_history",official["facts"]["availability_context"]["historical_window_end_date"],OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,"/facts/availability_context/historical_window_end_date","independent_field","Historical window end only; current availability stays unknown."))
 evidence.append(ev("set",SET_ID,"scope_definition",official["facts"]["remaining_seasonal_iap"],OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,"/facts/remaining_seasonal_iap","independent_field","FAQ 968's explicitly enumerated remaining seasonal IAP scope; this is not asserted to be all AURORA paid items."))
 evidence.sort(key=lambda r:(r["target_type"],r["target_id"],r["field_path"],r["source_id"]))
 return {"items":list(rows.values()),"sets":list(sets.values()),"sources":read(root/"knowledge/sources/sources.jsonl")},evidence
def item_row(item_id:str,name:str,category:str,price:float|int,start:str|None)->dict[str,Any]:
 iap=item_id in IAP_IDS; currency="USD" if iap else "candle"
 return {"item_id":item_id,"canonical_name_zh_tw":f"待確認（{name}）","canonical_name_en":name,"aliases":[],"item_category":category,"item_subcategory":"collaboration_iap" if iap else "collaboration_additional","source_type":"collaboration","source_id":OFFICIAL_SOURCE,"season_id":"season_aurora","event_id":None,"ancestor_id":None,"set_ids":[SET_ID] if iap else [],"free_or_premium":"premium" if iap else "free","pass_required":"unknown" if iap else "no","ultimate_reward":False,"collaboration":True,"permanent_account_item":"unknown","consumable":False,"original_currency":currency,"original_cost":price,"availability_status":"unknown","first_release_date":None,"availability_event_ids":["availability_aurora_faq968_"+item_id.removeprefix("item_aurora_")],"visual_reference_ids":["visual_"+item_id.removeprefix("item_")],"valuation_role":"collection_structure","source_ids":[OFFICIAL_SOURCE,SECONDARY_SOURCE],"last_verified_at":AS_OF,"verification_status":"verified","evidence_tier":"official_with_secondary","model_feature_status":declared_model_feature_status(item_id),"notes":"FAQ 968 establishes this named item's historical price and limited collaboration context; an independent pinned vendor snapshot supplies exact canonical title/type. Historical availability is recorded separately and is not promoted to a first-release claim. Current availability, return policy, permanent-account property, formal Traditional Chinese name, and visual identity remain unknown or unasserted. This cohort is not a complete AURORA paid-item catalog."}
def apply_targets(root:Path,targets:dict[str,list[dict[str,Any]]])->dict[str,list[dict[str,Any]]]:
 items={r["item_id"]:dict(r) for r in targets["items"]}
 for iid,_v,n,c,_l,_f,p,start in ITEMS: items[iid]=item_row(iid,n,c,p,start)
 ordered=[items[r["item_id"]] for r in targets["items"] if r["item_id"] in items]+[items[i] for i,*_ in ITEMS if i not in {r["item_id"] for r in targets["items"]}]
 sets={r["set_id"]:dict(r) for r in targets["sets"]}; sets[SET_ID]={"set_id":SET_ID,"canonical_name_zh_tw":"待確認（AURORA FAQ 968 剩餘季節付費物品）","canonical_name_en":"AURORA FAQ 968 remaining seasonal IAP","set_type":"collaboration","required_item_ids":["item_aurora_to_the_love_outfit","item_aurora_voice","item_aurora_giving_in_cape","item_aurora_wings"],"optional_item_ids":[],"source_ids":[OFFICIAL_SOURCE,SECONDARY_SOURCE],"last_verified_at":AS_OF,"verification_status":"verified"}
 # Source master records are reviewed inputs.  This replay tool never creates
 # or upgrades them; build() has already required their exact lineage.
 return {"items":ordered,"sets":[sets[r["set_id"]] for r in targets["sets"]],"sources":targets["sources"]}
def support()->tuple[list[dict[str,Any]],list[dict[str,Any]]]:
 av=[]; vis=[]
 for iid,_v,n,_c,_l,_f,_p,start in ITEMS:
  av.append({"availability_id":"availability_aurora_faq968_"+iid.removeprefix("item_aurora_"),"item_id":iid,"availability_status":"limited_time","start_date":start,"end_date":"2023-01-02","event_id":None,"source_ids":[OFFICIAL_SOURCE],"last_verified_at":AS_OF,"verification_status":"verified"})
  vis.append({"visual_reference_id":"visual_"+iid.removeprefix("item_"),"item_id":iid,"reference_mode":"source_description","asset_sha256":None,"description":f"FAQ 968 textually names {n}; no image asset or visual match is stored or asserted.","source_ids":[OFFICIAL_SOURCE],"verification_status":"needs_review"})
 return av,vis
def verify(root:Path,require_applied:bool=True)->list[str]:
 targets,evidence=build(root); expected=apply_targets(root,targets); bad=[]
 if require_applied:
  current_items={row["item_id"]:row for row in read(root/"knowledge/items/items.jsonl")}; expected_items={row["item_id"]:row for row in expected["items"]}
  for item_id,*_ in ITEMS:
   if current_items.get(item_id)!=expected_items.get(item_id): bad.append("committed target differs from replayable apply contract: knowledge/items/items.jsonl"); break
  current_sets={row["set_id"]:row for row in read(root/"knowledge/sets/item-sets.jsonl")}; expected_sets={row["set_id"]:row for row in expected["sets"]}
  if current_sets.get(SET_ID)!=expected_sets.get(SET_ID): bad.append("committed target differs from replayable apply contract: knowledge/sets/item-sets.jsonl")
  av,vis=support(); havea={r["availability_id"]:r for r in read(root/"knowledge/acquisition/availability-events.jsonl")}; havev={r["visual_reference_id"]:r for r in read(root/"knowledge/visual-references/manifest.jsonl")}
  for row in av:
   if havea.get(row["availability_id"])!=row: bad.append(f"availability differs: {row['availability_id']}")
  for row in vis:
   if havev.get(row["visual_reference_id"])!=row: bad.append(f"visual reference differs: {row['visual_reference_id']}")
  ep=root/"data/review/aurora-faq968-canonical-evidence.jsonl"
  if not ep.is_file() or read(ep)!=evidence: bad.append("canonical field evidence differs from replayable source claims")
  byid={r["item_id"]:r for r in expected["items"]}
  if any(byid[i]["availability_status"]!="unknown" or byid[i]["permanent_account_item"]!="unknown" or byid[i]["model_feature_status"]!=declared_model_feature_status(i) for i,*_ in ITEMS): bad.append("unsupported current availability, permanence, or exact-English model eligibility")
  if set(next(x for x in expected["sets"] if x["set_id"]==SET_ID)["required_item_ids"])!=IAP_IDS: bad.append("FAQ 968 set membership mismatch")
  if any(i in next(x for x in expected["sets"] if x["set_id"]==SET_ID)["required_item_ids"] for i in ("item_aurora_cure_for_me_mask","item_aurora_cure_for_me_outfit")): bad.append("Cure items incorrectly included in FAQ 968 IAP set")
 return bad
def main()->None:
 ap=argparse.ArgumentParser(); ap.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[2]); ap.add_argument("--apply",action="store_true"); args=ap.parse_args(); root=args.root.resolve()
 if args.apply:
  targets,evidence=build(root); out=apply_targets(root,targets); av,vis=support(); write(root/"knowledge/items/items.jsonl",out["items"]); write(root/"knowledge/sets/item-sets.jsonl",out["sets"])
  a={r["availability_id"]:r for r in read(root/"knowledge/acquisition/availability-events.jsonl")}; a.update({r["availability_id"]:r for r in av}); write(root/"knowledge/acquisition/availability-events.jsonl",sorted(a.values(),key=lambda r:r["availability_id"]))
  v={r["visual_reference_id"]:r for r in read(root/"knowledge/visual-references/manifest.jsonl")}; v.update({r["visual_reference_id"]:r for r in vis}); write(root/"knowledge/visual-references/manifest.jsonl",sorted(v.values(),key=lambda r:r["visual_reference_id"]))
  write(root/"data/review/aurora-faq968-canonical-evidence.jsonl",evidence)
 bad=verify(root); print(json.dumps({"applied":args.apply,"valid":not bad,"problems":bad,"model_feature_status":"excluded_pending_verification"},ensure_ascii=False,sort_keys=True)); raise SystemExit(bool(bad))
if __name__=="__main__": main()
