#!/usr/bin/env python3
"""Conservative offline conversion of structured claims into a P0 profile."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from typing import Any

KNOWN = {"complete", "partial", "owned_not_complete", "confirmed_missing", "unknown"}

def _items(values: Any) -> list[str]:
    return [str(x) for x in values if isinstance(x, str) and x.startswith("item_")] if isinstance(values, list) else []

def classify(source: dict[str, Any]) -> dict[str, Any]:
    """Never infer missing ownership from absent data; raw text is not retained."""
    account_id = str(source.get("account_id", "account_new"))
    claims = source.get("structured_claims", source)
    base = claims.get("base_account", {}) if isinstance(claims.get("base_account"), dict) else {}
    seasons = []
    for row in claims.get("season_profiles", []):
        if not isinstance(row, dict) or not str(row.get("season_id", "")).startswith("season_"): continue
        status = row.get("status", "unknown")
        seasons.append({"season_id": row["season_id"], "status": status if status in KNOWN else "unknown", "completion_ratio": row.get("completion_ratio") if isinstance(row.get("completion_ratio"), (int,float)) else None, "pass_owned": row.get("pass_owned", "unknown"), "ultimate_reward_owned": row.get("ultimate_reward_owned", "unknown"), "owned_item_ids": _items(row.get("owned_item_ids", [])), "missing_item_ids": _items(row.get("missing_item_ids", [])), "evidence_state": "text_claim" if row.get("evidence_state") == "text_claim" else "unknown", "evidence_sources": ["structured_claim"], "capture_date": None, "review_status": "needs_review"})
    collection = claims.get("collection", {}) if isinstance(claims.get("collection"), dict) else {}
    resources = claims.get("resources", {}) if isinstance(claims.get("resources"), dict) else {}
    values = resources.get("values", resources)
    bindings = claims.get("bindings", {}) if isinstance(claims.get("bindings"), dict) else {}
    platforms = [x for x in bindings.get("platforms", []) if isinstance(x, dict) and x.get("platform")]
    return {"schema_version":"3.0-p0", "account_id":account_id, "source_listing_ids":list(source.get("source_listing_ids", [])),
      "base_account":{"account_type":base.get("account_type", "unknown"), "wing_state":base.get("wing_state", "unknown"), "special_appearance":list(base.get("special_appearance", [])), "short_id":base.get("short_id", "unknown")},
      "season_profiles":seasons, "season_summary":{"earliest_season_id":None,"earliest_complete_season_id":None,"complete_count":sum(x["status"]=="complete" for x in seasons),"partial_count":sum(x["status"]=="partial" for x in seasons),"pass_not_complete_count":0,"continuous_segments":[],"gap_segments":[],"evidence_state":"text_claim" if seasons else "unknown"},
      "collection":{"owned_item_ids":_items(collection.get("owned_item_ids", [])),"item_set_profiles":list(collection.get("item_set_profiles", [])),"graduation_rewards":_items(collection.get("graduation_rewards", [])),"collaboration_items":_items(collection.get("collaboration_items", [])),"bundle_claim_level":collection.get("bundle_claim_level", "unknown")},
      "map_completion": claims.get("map_completion", {"standard_maps":"unknown","second_tier_capes":"unknown","evidence_state":"unknown"}),
      "resources":{"values":{k: values.get(k) if isinstance(values,dict) and isinstance(values.get(k),(int,float)) else None for k in ("white_candles","hearts","red_candles","season_candles")},"capture_date":None,"evidence_state":"text_claim" if isinstance(values,dict) else "unknown"},
      "bindings":{"platforms":platforms,"risk_state":bindings.get("risk_state","unknown")}, "ownership_history":claims.get("ownership_history","unknown"), "trade_conditions":claims.get("trade_conditions", {"offer_kind":"unknown","entity_kind":"unknown","price_type":"unknown"}), "evidence_quality":{"listing_text":"text_claim" if claims else "unknown","image":"not_collected","ocr":"not_collected"}, "review_status":"needs_review"}

def main() -> None:
    p=argparse.ArgumentParser(); p.add_argument("input",type=Path); p.add_argument("--output",type=Path,required=True); a=p.parse_args()
    a.output.write_text(json.dumps(classify(json.loads(a.input.read_text(encoding="utf-8"))),ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
if __name__ == "__main__": main()
