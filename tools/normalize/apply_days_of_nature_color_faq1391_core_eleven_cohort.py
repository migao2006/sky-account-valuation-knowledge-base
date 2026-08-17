#!/usr/bin/env python3
"""Replay FAQ 1391's bounded Nature + Color core-eleven cohort."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from typing import Any
ROOT=Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from tools.modeling.canonical_english_eligibility import declared_model_feature_status
from tools.normalize.apply_moomintroll_accessory_set_cohort import evidence, read, safe, sha, vendor, write

OFFICIAL_SOURCE="source_tgc_faq_1391_days_of_nature_color_core_eleven"; SECONDARY_SOURCE="source_skygame_data_1_3_4"
LEGACY_OFFICIAL_SOURCE="source_tgc_faq_1391_days_of_nature_color_core_seven"
OFFICIAL_LINEAGE="lineage_tgc_support_faq_1391"; SECONDARY_LINEAGE="lineage_skygame_data_1_3_4"
OFFICIAL_PATH="data/source/research/tgc-faq-1391-days-of-nature-color-core-eleven.json"; SECONDARY_PATH="data/source/vendor/skygame-data-1.3.4-items.json"
OFFICIAL_SHA="CD4736D3072083333DCFC8BEA70A5F30E029124C2C8AF1C0C7E4E1C42E111EEE"; SECONDARY_SHA="21CCAD77006C425B27EE9314870BB5BB77E8436459C6DA214ABCB2B0D8329BBB"; AS_OF="2026-08-17"
# canonical ID, vendor numeric ID/GUID/title/type, FAQ title, category, currency/cost, event, exact-price flag.
ITEMS=(
 ("item_days_of_nature_ocean_necklace",1779,"KZ6aQtgCqt","Ocean Necklace","Necklace","Ocean Necklace","accessory","USD",1.99,"days_of_nature",True),
 ("item_days_of_nature_sonorous_seashell",1788,"gHfkqCK-A8","Nature Sonorous Seashell","Prop","Nature Sonorous Seashell","prop","USD",4.99,"days_of_nature",True),
 ("item_days_of_nature_earth_cape",1778,"YUqENRc8rQ","Earth Cape","Cape","Earth Cape","cape","USD",4.99,"days_of_nature",True),
 ("item_days_of_nature_ocean_cape",1780,"MjA9EoD-pe","Ocean Cape","Cape","Ocean Cape","cape","USD",14.99,"days_of_nature",True),
 ("item_days_of_color_rainbow_ribbon_shawl",2634,"zG11dMlH61","Rainbow Ribbon Shawl","Cape","Rainbow Ribbon Shawl","cape","USD",14.99,"days_of_color",True),
 ("item_days_of_color_rainbow_face_paint_mask",2635,"Z9HZ5p9DX7","Rainbow Face Paint Mask","Mask","Rainbow Face Paint mask","mask","USD",19.99,"days_of_color",True),
 ("item_days_of_color_dark_rainbow_loafers",2214,"xFcmMsHvA0","Dark Rainbow Loafers","Shoes","Dark Rainbow Loafers","outfit","USD",19.99,"days_of_color",True),
 ("item_days_of_nature_ocean_waves_outfit",2622,"O-9eA-N9si","Ocean Waves Outfit","Outfit","Ocean Waves outfit","outfit","event_currency","unknown","days_of_nature",False),
 ("item_days_of_nature_ocean_manta_hair",2623,"B57ZJ9lCAE","Ocean Manta Hair","Hair","Ocean Manta hair","hair","event_currency","unknown","days_of_nature",False),
 ("item_days_of_color_rainbow_smock",2630,"iJ92oZ6f5q","Rainbow Smock","OutfitShoes","Rainbow Smock","outfit","event_currency","unknown","days_of_color",False),
 ("item_days_of_color_rainbow_head_wrap",2631,"SgIsK6N6pA","Rainbow Head Wrap","Hair","Rainbow Head Wrap","hair","event_currency","unknown","days_of_color",False),
)
SOURCE_ROW={"source_id":OFFICIAL_SOURCE,"source_name":"thatgamecompany Help Center FAQ 1391 — Patch Notes, April 17, 2025 (Days of Nature and Days of Color 2025)","source_type":"official_support","url":"https://thatgamecompany.helpshift.com/hc/en/17-sky-children-of-the-light/faq/1391-patch-notes---april-17-2025---0-29-0-319554-android-huawei-ios-playstation-steam-switch/","retrieved_at":AS_OF,"evidence_level":"official_explicit","source_lineage_id":OFFICIAL_LINEAGE,"notes":"Fact-limited locally pinned transcription: FAQ 1391's starts, stated durations, seven named exact-price single-item costs, and four named event-ticket unlocks without asserted individual ticket counts. Official capitalization is preserved and vendor-title reconciliation is limited to explicit pairs in the apply contract. Ocean Waves Mask has no exact identity in the pinned vendor snapshot; packs and bundles are excluded. It does not establish current availability, return policy, permanent ownership, images, formal Traditional Chinese names, visual matches, first release dates, or set membership."}
LEGACY_SOURCE_ROW={**SOURCE_ROW,"notes":"Fact-limited locally pinned transcription: FAQ 1391's starts, stated durations, seven named exact-price single-item costs, and four exact-name event-ticket unlocks without asserted individual ticket counts. Ocean Waves Mask has no exact identity in the pinned vendor snapshot; packs and bundles are excluded. It does not establish current availability, return policy, permanent ownership, images, formal Traditional Chinese names, visual matches, first release dates, or set membership."}
class DaysOfNatureColorEvidenceError(ValueError): pass
def registry_contract(): return {"cohort_id":"canonical_cohort_days_of_nature_color_faq1391_core_eleven","evidence_path":"data/review/days-of-nature-color-faq1391-core-eleven-canonical-evidence.jsonl","snapshot_paths":[OFFICIAL_PATH,SECONDARY_PATH],"source_ids":[SECONDARY_SOURCE,OFFICIAL_SOURCE],"target_item_ids":sorted(x[0] for x in ITEMS),"target_set_ids":[]}
def valid_title_relation(official_name,vendor_name):
 return (official_name,vendor_name) in {(row[5],row[3]) for row in ITEMS}
def source_rows(rows):
 indexed={r["source_id"]:dict(r) for r in rows if r["source_id"] != LEGACY_OFFICIAL_SOURCE}
 if indexed.get(OFFICIAL_SOURCE) not in (None,SOURCE_ROW,LEGACY_SOURCE_ROW): raise DaysOfNatureColorEvidenceError("official source registry conflicts with cohort contract")
 indexed[OFFICIAL_SOURCE]=SOURCE_ROW; ordered=[r["source_id"] for r in rows if r["source_id"] != LEGACY_OFFICIAL_SOURCE]
 if OFFICIAL_SOURCE not in ordered: ordered.append(OFFICIAL_SOURCE)
 return [indexed[i] for i in ordered]
def item_row(iid,name,category,currency,cost,event,exact_price):
 return {"item_id":iid,"canonical_name_zh_tw":f"待確認（{name}）","canonical_name_en":name,"aliases":[],"item_category":category,"item_subcategory":"days_of_nature_color_2025_historical_item","source_type":"event","source_id":OFFICIAL_SOURCE,"season_id":None,"event_id":None,"ancestor_id":None,"set_ids":[],"free_or_premium":"unknown","pass_required":"unknown","ultimate_reward":False,"collaboration":False,"permanent_account_item":"unknown","consumable":False,"original_currency":currency,"original_cost":cost,"availability_status":"unknown","first_release_date":None,"availability_event_ids":[f"availability_faq1391_{iid.removeprefix('item_') }"],"visual_reference_ids":[],"valuation_role":"collection_structure","source_ids":[OFFICIAL_SOURCE,SECONDARY_SOURCE],"last_verified_at":AS_OF,"verification_status":"verified","evidence_tier":"official_with_secondary","model_feature_status":declared_model_feature_status(iid),"notes":("FAQ 1391 establishes this named 2025 historical offer, exact USD cost, start date, and stated duration only; the vendor snapshot independently supplies exact vendor ID, GUID, title, and type." if exact_price else "FAQ 1391 establishes this named event-ticket unlock, start date, and stated duration only; it does not establish an individual ticket price.")+" The duration may support a derived end date but none is asserted as official. Ocean Waves Mask lacks exact vendor identity and is excluded, as are packs and bundles. Current availability, return policy, permanent-account property, formal Traditional Chinese name, visual identity, first release date, set membership, and model eligibility remain unknown or unasserted."}
def build(root:Path):
 root=root.resolve(); official_bytes=safe(root,OFFICIAL_PATH).read_bytes(); secondary_bytes=safe(root,SECONDARY_PATH).read_bytes()
 if sha(official_bytes)!=OFFICIAL_SHA or sha(secondary_bytes)!=SECONDARY_SHA: raise DaysOfNatureColorEvidenceError("official or secondary snapshot hash mismatch")
 official=json.loads(official_bytes); secondary=json.loads(secondary_bytes); facts=official.get("facts",{})
 exact=[{"item_id":a,"official_name_en":f,"original_currency":h,"original_cost":i,"event":j} for a,_b,_c,_d,_e,f,_g,h,i,j,k in ITEMS if k]
 ticket=[{"item_id":a,"official_name_en":f,"original_currency":h,"original_cost":i,"event":j} for a,_b,_c,_d,_e,f,_g,h,i,j,k in ITEMS if not k]
 if official.get("source_id")!=OFFICIAL_SOURCE or facts.get("exact_price_items")!=exact or facts.get("ticket_identity_items")!=ticket or {k:facts.get(k) for k in ("days_of_nature_window_start_date","days_of_nature_window_duration","days_of_color_window_start_date","days_of_color_window_duration")} != {"days_of_nature_window_start_date":"2025-04-28","days_of_nature_window_duration":"3 weeks","days_of_color_window_start_date":"2025-05-26","days_of_color_window_duration":"2 weeks"}: raise DaysOfNatureColorEvidenceError("official FAQ 1391 contract changed")
 targets={k:read(root/p) for k,p in (("items","knowledge/items/items.jsonl"),("sources","knowledge/sources/sources.jsonl"))}; sources={r["source_id"]:r for r in source_rows(targets["sources"])}
 for sid,typ,lineage in ((OFFICIAL_SOURCE,"official_support",OFFICIAL_LINEAGE),(SECONDARY_SOURCE,"community_database",SECONDARY_LINEAGE)):
  if sources.get(sid,{}).get("source_type")!=typ or sources[sid].get("source_lineage_id")!=lineage: raise DaysOfNatureColorEvidenceError("source registry or lineage mismatch: "+sid)
 ledger=[]
 for n,(iid,vid,guid,vname,vtype,oname,category,currency,cost,event,exact_price) in enumerate(ITEMS):
  vi,vrow=vendor(secondary,vid)
  if (vrow.get("guid"),vrow.get("name"),vrow.get("type")) != (guid,vname,vtype): raise DaysOfNatureColorEvidenceError("secondary identity changed: "+str(vid))
  if not valid_title_relation(oname,vname): raise DaysOfNatureColorEvidenceError("unsupported official/vendor title relation: "+str(vid))
  lane="exact_price_items" if exact_price else "ticket_identity_items"; lane_index=sum(1 for row in ITEMS[:n] if row[-1] == exact_price); path=f"/facts/{lane}/{lane_index}"; prefix=f"/facts/{event}_window"; note="Historical FAQ cost/start/duration only; no current availability, permanence, official exact end date, or model eligibility is inferred." if exact_price else "Ticket unlock identity/start/duration only; no individual ticket price, current availability, permanence, official exact end date, or model eligibility is inferred."
  title_note="FAQ and vendor titles are byte-identical." if oname==vname else f"FAQ/vendor spelling is reconciled only by the explicit contract pair {oname!r}/{vname!r}."
  ledger.extend((evidence("item",iid,"canonical_name_en",oname,OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,official_bytes,path+"/official_name_en","independent_identity",title_note),evidence("item",iid,"original_currency",currency,OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,official_bytes,path+"/original_currency","independent_field",note),evidence("item",iid,"availability_history",facts[event+"_window_start_date"],OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,official_bytes,prefix+"_start_date","independent_field",note),evidence("item",iid,"availability_history",facts[event+"_window_duration"],OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,official_bytes,prefix+"_duration","independent_field","Official duration string only; no exact official end date is claimed."),evidence("item",iid,"vendor_item_name",vname,SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,secondary_bytes,f"/items/{vi}/name","secondary_field","Pinned vendor spelling; title reconciliation is limited by this apply contract."),evidence("item",iid,"vendor_item_type",vtype,SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,secondary_bytes,f"/items/{vi}/type","secondary_field",f"Apply contract maps vendor type to canonical category {category}."),evidence("item",iid,"vendor_item_guid",guid,SECONDARY_SOURCE,SECONDARY_LINEAGE,"secondary_reference",SECONDARY_PATH,secondary_bytes,f"/items/{vi}/guid","secondary_field","Pinned vendor GUID is an identity guard, not a model feature.")))
  if exact_price: ledger.append(evidence("item",iid,"original_cost",cost,OFFICIAL_SOURCE,OFFICIAL_LINEAGE,"official_item_specific",OFFICIAL_PATH,official_bytes,path+"/original_cost","independent_field",note))
 ledger.sort(key=lambda r:(r["target_type"],r["target_id"],r["field_path"],r["source_id"],r["claim_locator"])); return targets,ledger
def apply_targets(targets):
 items={r["item_id"]:dict(r) for r in targets["items"]}; order=[r["item_id"] for r in targets["items"]]
 for iid,_vid,_guid,_vname,_vtype,name,category,currency,cost,event,exact_price in ITEMS:
  items[iid]=item_row(iid,name,category,currency,cost,event,exact_price)
  if iid not in order: order.append(iid)
 return {"items":[items[i] for i in order],"sources":source_rows(targets["sources"])}
def availability_rows():
 # No end_date: FAQ 1391 gives only a duration. A consumer may derive one but must label it derived.
 starts={"days_of_nature":"2025-04-28","days_of_color":"2025-05-26"}
 return [{"availability_id":f"availability_faq1391_{iid.removeprefix('item_')}","item_id":iid,"availability_status":"limited_time","start_date":starts[event],"end_date":None,"event_id":None,"source_ids":[OFFICIAL_SOURCE],"last_verified_at":AS_OF,"verification_status":"verified"} for iid,_vid,_guid,_vname,_vtype,_name,_category,_currency,_cost,event,_exact_price in ITEMS]
def verify(root:Path,require_applied=True):
 targets,ledger=build(root); expected=apply_targets(targets); problems=[]
 if require_applied:
  for path,key in (("knowledge/items/items.jsonl","items"),("knowledge/sources/sources.jsonl","sources")):
   if read(root/path)!=expected[key]: problems.append("committed target differs from replayable apply contract: "+path)
  available={r["availability_id"]:r for r in read(root/"knowledge/acquisition/availability-events.jsonl")}
  for r in availability_rows():
   if available.get(r["availability_id"])!=r: problems.append("availability differs: "+r["availability_id"])
  lp=root/"data/review/days-of-nature-color-faq1391-core-eleven-canonical-evidence.jsonl"
  if not lp.is_file() or read(lp)!=ledger: problems.append("canonical field evidence differs from replayable source claims")
  for iid,*_ in ITEMS:
   item=next(r for r in expected["items"] if r["item_id"]==iid)
   if (item["availability_status"],item["permanent_account_item"],item["first_release_date"],item["model_feature_status"],item["set_ids"],item["visual_reference_ids"]) != ("unknown","unknown",None,declared_model_feature_status(iid),[],[]): problems.append("unsupported availability, permanence, first-release, visual, model promotion, or bundle membership"); break
 return problems
def main():
 p=argparse.ArgumentParser(); p.add_argument("--root",type=Path,default=ROOT); p.add_argument("--apply",action="store_true"); args=p.parse_args(); root=args.root.resolve()
 if args.apply:
  targets,ledger=build(root); output=apply_targets(targets)
  for path,key in (("knowledge/items/items.jsonl","items"),("knowledge/sources/sources.jsonl","sources")): write(root/path,output[key])
  available={r["availability_id"]:r for r in read(root/"knowledge/acquisition/availability-events.jsonl")}; available.update({r["availability_id"]:r for r in availability_rows()}); write(root/"knowledge/acquisition/availability-events.jsonl",sorted(available.values(),key=lambda r:r["availability_id"])); write(root/"data/review/days-of-nature-color-faq1391-core-eleven-canonical-evidence.jsonl",ledger)
 problems=verify(root); print(json.dumps({"applied":args.apply,"valid":not problems,"problems":problems},sort_keys=True)); raise SystemExit(bool(problems))
if __name__=="__main__": main()
