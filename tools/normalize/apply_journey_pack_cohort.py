#!/usr/bin/env python3
"""Replay bounded offline Journey Pack evidence; fail closed on every source claim."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path
from typing import Any

OFFICIAL_SOURCE="source_tgc_faq_1308_journey_pack"; SECONDARY_SOURCE="source_skygame_data_1_3_4"
OFFICIAL_LINEAGE="lineage_tgc_support_faq_1308"; SECONDARY_LINEAGE="lineage_skygame_data_1_3_4"
OFFICIAL_PATH="data/source/research/tgc-faq-1308-journey-pack.json"; SECONDARY_PATH="data/source/vendor/skygame-data-1.3.4-items.json"
OFFICIAL_SNAPSHOT_SHA256="DA8FF3F2A492B922A1BC61C60206920398676A294419CA682130FEC01DA429E0"; SECONDARY_SNAPSHOT_SHA256="21CCAD77006C425B27EE9314870BB5BB77E8436459C6DA214ABCB2B0D8329BBB"
AS_OF="2026-08-17"; SET_ID="set_journey_pack"; AVAILABILITY_ID="availability_journey_pack"
ITEMS=(("item_journey_pack_cape",1948,"Journey Cape","cape"),("item_journey_hair",1949,"Journey Hair","hair"),("item_journey_mask",1947,"Journey Mask","mask"))

class JourneyEvidenceError(ValueError): pass
def sha(v:bytes|str)->str:
 if isinstance(v,str): v=v.encode()
 return hashlib.sha256(v).hexdigest().upper()
def chash(v:Any)->str:return sha(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(",",":")))
def read(p:Path)->list[dict[str,Any]]:return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
def write(p:Path,rows:list[dict[str,Any]])->None:p.write_text("".join(json.dumps(r,ensure_ascii=False,separators=(",",":"))+"\n" for r in rows),encoding="utf-8",newline="\n")
def safe(root:Path,rel:str)->Path:
 p=(root/rel).resolve()
 if root.resolve() not in p.parents or not p.is_file():raise JourneyEvidenceError(f"snapshot unavailable or escapes root: {rel}")
 return p
def ptr(doc:Any,loc:str)->Any:
 if not loc.startswith("/"):raise JourneyEvidenceError(f"invalid JSON pointer: {loc!r}")
 cur=doc
 for part in loc[1:].split("/"):
  part=part.replace("~1","/").replace("~0","~")
  try:cur=cur[int(part)] if isinstance(cur,list) else cur[part]
  except (KeyError,IndexError,ValueError,TypeError) as exc:raise JourneyEvidenceError(f"unresolved JSON pointer: {loc!r}") from exc
 return cur
def eid(target:str,field:str,source:str,loc:str,value:Any)->str:return "canonical_evidence_"+hashlib.sha256(f"{target}\0{field}\0{source}\0{loc}\0{chash(value)}".encode()).hexdigest()[:24]
def ev(target_type:str,target_id:str,field:str,value:Any,source:str,lineage:str,tier:str,path:str,raw:bytes,loc:str,role:str,notes:str="")->dict[str,Any]:
 found=ptr(json.loads(raw.decode("utf-8")),loc)
 if found!=value:raise JourneyEvidenceError(f"claim does not equal source locator: {target_id}:{field}")
 return {"evidence_id":eid(target_id,field,source,loc,value),"target_type":target_type,"target_id":target_id,"field_path":field,"claim_value":value,"claim_hash":chash(value),"source_id":source,"source_lineage_id":lineage,"source_tier":tier,"source_snapshot_path":path,"source_snapshot_bytes":len(raw),"source_snapshot_hash":sha(raw),"claim_locator":loc,"claim_locator_hash":chash(found),"evidence_role":role,"review_status":"approved","reviewed_at":AS_OF,"notes":notes}
def vendor(doc:dict[str,Any],vid:int)->tuple[int,dict[str,Any]]:
 for i,row in enumerate(doc.get("items",[])):
  if row.get("id")==vid:return i,row
 raise JourneyEvidenceError(f"pinned secondary item missing: {vid}")
def item_row(item_id:str,name:str,category:str)->dict[str,Any]:
 return {"item_id":item_id,"canonical_name_zh_tw":f"待確認（{name}）","canonical_name_en":name,"aliases":[],"item_category":category,"item_subcategory":"platform_bundle","source_type":"platform","source_id":OFFICIAL_SOURCE,"season_id":None,"event_id":None,"ancestor_id":None,"set_ids":[SET_ID],"free_or_premium":"premium","pass_required":"unknown","ultimate_reward":False,"collaboration":True,"permanent_account_item":"unknown","consumable":False,"original_currency":"USD","original_cost":"bundle_only","availability_status":"unknown","first_release_date":None,"availability_event_ids":[AVAILABILITY_ID],"visual_reference_ids":[],"valuation_role":"collection_structure","source_ids":[OFFICIAL_SOURCE,SECONDARY_SOURCE],"last_verified_at":AS_OF,"verification_status":"verified","evidence_tier":"official_with_secondary","model_feature_status":"excluded_pending_verification","notes":"FAQ 1308 establishes only the historical Journey Pack context, its three descriptive components, stated pack price, and cross-platform account-access statement. The independent pinned vendor snapshot supplies exact English titles and categories. The pack price is not allocated to individual items; current availability, return policy, permanent-account property, formal Traditional Chinese names, and visual identity remain unknown or unasserted."}
def build(root:Path)->tuple[dict[str,list[dict[str,Any]]],list[dict[str,Any]]]:
 root=root.resolve(); ob=safe(root,OFFICIAL_PATH).read_bytes(); sb=safe(root,SECONDARY_PATH).read_bytes()
 if sha(ob)!=OFFICIAL_SNAPSHOT_SHA256:raise JourneyEvidenceError("official snapshot hash mismatch")
 if sha(sb)!=SECONDARY_SNAPSHOT_SHA256:raise JourneyEvidenceError("secondary snapshot hash mismatch")
 official=json.loads(ob); secondary=json.loads(sb); facts=official.get("facts",{})
 if facts.get("pack_description_en")!="Journey Pack" or facts.get("historical_price_usd")!=24.99:raise JourneyEvidenceError("official pack contract changed")
 descriptions=facts.get("included_component_descriptions_en")
 if descriptions!={"item_journey_pack_cape":"cape","item_journey_hair":"hood","item_journey_mask":"mask"}:raise JourneyEvidenceError("official component contract changed")
 rows=read(root/"knowledge/items/items.jsonl"); sets=read(root/"knowledge/sets/item-sets.jsonl"); sources=read(root/"knowledge/sources/sources.jsonl"); sm={r["source_id"]:r for r in sources}
 for sid,typ,lineage in ((OFFICIAL_SOURCE,"official_support",OFFICIAL_LINEAGE),(SECONDARY_SOURCE,"community_database",SECONDARY_LINEAGE)):
  if sid not in sm or sm[sid].get("source_type")!=typ or sm[sid].get("source_lineage_id")!=lineage:raise JourneyEvidenceError(f"source registry or lineage mismatch: {sid}")
 evidence=[]
 for iid,vid,name,category in ITEMS:
  vi,vr=vendor(secondary,vid)
  if vr.get("name")!=name or str(vr.get("type","")).casefold()!=category:raise JourneyEvidenceError(f"secondary identity changed: {vid}")
  desc=descriptions[iid]; dl=f"/facts/included_component_descriptions_en/{iid}"
  evidence += [ev("item",iid,"identity_description",desc,OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,dl,"independent_field","Official descriptive component; not an exact vendor-aligned title."),ev("item",iid,"set_membership",desc,OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,dl,"independent_field","Official pack component mapped to this canonical set member."),ev("item",iid,"canonical_name_en",name,SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,sb,f"/items/{vi}/name","secondary_field"),ev("item",iid,"item_category",vr["type"],SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,sb,f"/items/{vi}/type","secondary_field",f"Apply contract maps this vendor type to canonical category {category}.")]
 evidence += [ev("set",SET_ID,"identity_description","Journey Pack",OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,"/facts/pack_description_en","independent_field","Historical pack label only."),ev("set",SET_ID,"scope_definition",["cape","hood","mask"],OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,"/facts/included_component_values","independent_field","Three components explicitly stated by FAQ 1308."),ev("set",SET_ID,"historical_pack_price_usd",24.99,OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,ob,"/facts/historical_price_usd","independent_field","Historical pack price; it is not allocated to individual items."),ev("set",SET_ID,"platform_access_history",facts["cross_platform_account_access"],OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_general",OFFICIAL_PATH,ob,"/facts/cross_platform_account_access","independent_field","Historical cross-platform account-access statement; not a current availability assertion.")]
 evidence.sort(key=lambda r:(r["target_type"],r["target_id"],r["field_path"],r["source_id"],r["claim_locator"]))
 return {"items":rows,"sets":sets,"sources":sources},evidence
def apply_targets(root:Path,targets:dict[str,list[dict[str,Any]]])->dict[str,list[dict[str,Any]]]:
 items={r["item_id"]:dict(r) for r in targets["items"]}
 for iid,_vid,name,category in ITEMS:items[iid]=item_row(iid,name,category)
 initial=[r["item_id"] for r in targets["items"]]; ordered=[items[i] for i in initial]+[items[i] for i,*_ in ITEMS if i not in initial]
 sets={r["set_id"]:dict(r) for r in targets["sets"]}; sets[SET_ID]={"set_id":SET_ID,"canonical_name_zh_tw":"待確認（Journey Pack）","canonical_name_en":"Journey Pack","set_type":"bundle","required_item_ids":[i for i,*_ in ITEMS],"optional_item_ids":[],"source_ids":[OFFICIAL_SOURCE,SECONDARY_SOURCE],"last_verified_at":AS_OF,"verification_status":"verified"}
 sources={r["source_id"]:dict(r) for r in targets["sources"]}; sources[SECONDARY_SOURCE]["source_lineage_id"]=SECONDARY_LINEAGE
 return {"items":ordered,"sets":[sets[r["set_id"]] for r in targets["sets"] if r["set_id"]!=SET_ID]+[sets[SET_ID]],"sources":[sources[r["source_id"]] for r in targets["sources"]]}
def availability()->dict[str,Any]:return {"availability_id":AVAILABILITY_ID,"item_id":None,"availability_status":"unknown","start_date":None,"end_date":None,"event_id":None,"source_ids":[OFFICIAL_SOURCE,SECONDARY_SOURCE],"last_verified_at":AS_OF,"verification_status":"needs_review"}
def verify(root:Path,require_applied:bool=True)->list[str]:
 targets,evidence=build(root); expected=apply_targets(root,targets); bad=[]
 if require_applied:
  for rel,rows in (("knowledge/items/items.jsonl",expected["items"]),("knowledge/sets/item-sets.jsonl",expected["sets"]),("knowledge/sources/sources.jsonl",expected["sources"])):
   if read(root/rel)!=rows:bad.append(f"committed target differs from replayable apply contract: {rel}")
  have={r["availability_id"]:r for r in read(root/"knowledge/acquisition/availability-events.jsonl")}
  if have.get(AVAILABILITY_ID)!=availability():bad.append("availability row differs from replayable apply contract")
  ep=root/"data/review/journey-pack-canonical-evidence.jsonl"
  if not ep.is_file() or read(ep)!=evidence:bad.append("canonical field evidence differs from replayable source claims")
  items={r["item_id"]:r for r in expected["items"]}; journey=[items[i] for i,*_ in ITEMS]
  if any(r["availability_status"]!="unknown" or r["permanent_account_item"]!="unknown" or r["original_cost"]!="bundle_only" or r["model_feature_status"]!="excluded_pending_verification" for r in journey):bad.append("unsupported availability, permanence, price allocation, or model promotion")
  s=next(r for r in expected["sets"] if r["set_id"]==SET_ID)
  if s["required_item_ids"]!=[i for i,*_ in ITEMS]:bad.append("Journey Pack required members mismatch")
 return bad
def main()->None:
 ap=argparse.ArgumentParser(); ap.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[2]); ap.add_argument("--apply",action="store_true"); args=ap.parse_args(); root=args.root.resolve()
 if args.apply:
  targets,evidence=build(root); out=apply_targets(root,targets); write(root/"knowledge/items/items.jsonl",out["items"]); write(root/"knowledge/sets/item-sets.jsonl",out["sets"]); write(root/"knowledge/sources/sources.jsonl",out["sources"])
  a={r["availability_id"]:r for r in read(root/"knowledge/acquisition/availability-events.jsonl")}; a[AVAILABILITY_ID]=availability(); write(root/"knowledge/acquisition/availability-events.jsonl",sorted(a.values(),key=lambda r:r["availability_id"]))
  write(root/"data/review/journey-pack-canonical-evidence.jsonl",evidence)
 bad=verify(root); print(json.dumps({"applied":args.apply,"valid":not bad,"problems":bad,"model_feature_status":"excluded_pending_verification"},ensure_ascii=False,sort_keys=True));raise SystemExit(bool(bad))
if __name__=="__main__":main()
