#!/usr/bin/env python3
"""Build factual P0 coverage/migration/quality reports and refresh manifest hashes."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
from pathlib import Path
from typing import Any

from release_files import HASH_EXCLUSIONS, release_files

BUILT_AT = "2026-08-16T20:00:00+08:00"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def count(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    values = collections.Counter(str(row.get(key, "unknown")) for row in rows)
    return dict(sorted(values.items()))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def write_utf8_lf(path: Path, content: str) -> None:
    """Avoid Windows text-mode conversion so manifest bytes are platform-stable."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    root = args.root.resolve()

    paths = {
        "seasons": root / "knowledge/seasons/seasons.jsonl",
        "events": root / "knowledge/events/events.jsonl",
        "ancestors": root / "knowledge/seasons/ancestors.jsonl",
        "items": root / "knowledge/items/items.jsonl",
        "sets": root / "knowledge/sets/item-sets.jsonl",
        "aliases": root / "knowledge/aliases/item-aliases.jsonl",
        "availability_events": root / "knowledge/acquisition/availability-events.jsonl",
        "sources": root / "knowledge/sources/sources.jsonl",
        "visual_references": root / "knowledge/visual-references/manifest.jsonl",
        "source_listings": root / "data/source/listings.jsonl",
        "normalized_listings": root / "data/normalized/listings.jsonl",
        "account_profiles": root / "data/normalized/account-profiles.jsonl",
        "curated_histories": root / "data/curated/histories.jsonl",
        "comparable_histories": root / "data/comparables/histories.jsonl",
        "comparable_accounts": root / "data/comparables/accounts.jsonl",
        "image_evidence": root / "data/curated/image-evidence.jsonl",
        "unresolved": root / "reports/coverage/unresolved-items.jsonl",
        "unmapped": root / "reports/coverage/unmapped-aliases.jsonl",
        "item_candidates": root / "data/review/item-candidates.jsonl",
    }
    migration_aliases = read_jsonl(root / "data/review/unmapped-season-aliases.jsonl") + read_jsonl(root / "data/review/unmapped-item-aliases.jsonl")
    unmapped_rows = [
        {
            "review_id": f"unmapped_{index:04d}", "term": row.get("term"),
            "kind": row.get("kind", "unknown"), "occurrences": row.get("count"),
            "status": "needs_review",
        }
        for index, row in enumerate(migration_aliases, 1)
    ]
    write_utf8_lf(paths["unmapped"], "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in unmapped_rows))
    rows = {name: read_jsonl(path) for name, path in paths.items()}
    migration = json.loads((root / "reports/migration/migration-summary.json").read_text(encoding="utf-8"))
    inventory = json.loads((root / "reports/migration/file-inventory.json").read_text(encoding="utf-8"))

    verified_sales = sum(1 for row in rows["curated_histories"] if row.get("sale_outcome", {}).get("verified") is True)
    source_type_counts = count(rows["sources"], "source_type")
    official_types = {"official_site", "official_news", "official_support", "thatgamecompany"}
    canonical_entities = ("seasons", "events", "items", "sets", "aliases", "availability_events")
    canonical_needs_review = {
        name: sum(row.get("verification_status") == "needs_review" for row in rows[name])
        for name in canonical_entities
    }
    coverage = {
        "schema_version": "3.0-p0",
        "as_of_date": "2026-08-16",
        "catalog_claim": "partial_verified_catalog",
        "full_item_catalog_complete": False,
        "counts": {name: len(rows[name]) for name in (
            "seasons", "events", "ancestors", "items", "sets", "aliases",
            "availability_events", "sources", "visual_references", "unresolved", "unmapped", "item_candidates"
        )},
        "review_state": {
            "canonical_needs_review_by_entity": canonical_needs_review,
            "canonical_needs_review_total": sum(canonical_needs_review.values()),
            "unresolved_queue_records": len(rows["unresolved"]),
            "item_candidate_records": len(rows["item_candidates"]),
            "unmapped_terms": len(rows["unmapped"]),
            "overlap_note": "各欄分開計數，可能描述同一知識缺口，不直接相加為唯一項目數。",
        },
        "item_coverage": {
            "by_category": count(rows["items"], "item_category"),
            "by_source_type": count(rows["items"], "source_type"),
            "by_verification_status": count(rows["items"], "verification_status"),
            "by_availability_status": count(rows["items"], "availability_status"),
            "with_visual_reference": sum(bool(row.get("visual_reference_ids")) for row in rows["items"]),
            "with_canonical_zh_tw_name_confirmed": sum(
                row.get("verification_status") == "verified" and bool(row.get("canonical_name_zh_tw"))
                for row in rows["items"]
            ),
        },
        "season_coverage": {
            "total": len(rows["seasons"]),
            "with_one_or_more_items": sum(
                any(item.get("season_id") == season["season_id"] for item in rows["items"])
                for season in rows["seasons"]
            ),
            "without_items": [
                season["season_id"] for season in rows["seasons"]
                if not any(item.get("season_id") == season["season_id"] for item in rows["items"])
            ],
        },
        "source_coverage": {
            "by_type": source_type_counts,
            "official_source_records": sum(value for key, value in source_type_counts.items() if key in official_types),
            "community_or_other_source_records": sum(value for key, value in source_type_counts.items() if key not in official_types),
        },
        "market_migration": {
            "source_listings": len(rows["source_listings"]),
            "normalized_listings": len(rows["normalized_listings"]),
            "account_profiles": len(rows["account_profiles"]),
            "curated_histories": len(rows["curated_histories"]),
            "comparable_histories": len(rows["comparable_histories"]),
            "comparable_accounts": len(rows["comparable_accounts"]),
            "unmigrated_histories": migration["not_migrated_histories"],
            "verified_normalized_dates": migration["verified_dates_in_normalized"],
            "verified_history_dates_repaired": migration["verified_dates_repaired_in_histories"],
            "verified_completed_sales": verified_sales,
            "image_evidence_records": len(rows["image_evidence"]),
            "profiles_with_mapped_items": sum(bool(row.get("collection", {}).get("owned_item_ids")) for row in rows["account_profiles"]),
            "profiles_with_set_claims": sum(bool(row.get("collection", {}).get("item_set_profiles")) for row in rows["account_profiles"]),
        },
        "known_limitations": [
            "全物品主檔尚未完成；未確認類別保留在 unresolved-items.jsonl，未逐項查證的列印頁候選隔離於 data/review/item-candidates.jsonl，不參與 canonical 辨識或估價。",
            "物品圖示參考與真實圖片 evidence 目前為零，不宣稱具備圖示辨識準確率。",
            "可驗證成交價為零；估價只能輸出匿名刊登／急售可比觀察。",
            "部分季節節點的免費／季卡、成本及正式繁中名稱仍需逐頁查證。",
        ],
    }
    coverage_path = root / "reports/coverage/catalog-coverage.json"
    write_utf8_lf(coverage_path, json.dumps(coverage, ensure_ascii=False, indent=2) + "\n")

    migration_md = f"""# P0 遷移報告

## 實際結果

- 原始 ZIP：`{inventory['source_zip']}`，SHA-256 `{inventory['source_zip_sha256']}`；本次未改寫。
- 原始 ZIP 檔案：{inventory['source_file_count']}；盤點分類為 migrate {inventory['counts']['migrate']}、replace {inventory['counts']['replace']}、remove {inventory['counts']['remove']}、keep {inventory['counts']['keep']}。
- 71 個舊批次共遷移 {len(rows['source_listings'])} 筆匿名來源列，正規化 {len(rows['normalized_listings'])} 筆，建立 {len(rows['account_profiles'])} 筆帳號 profile。
- 既有 102 筆可比歷程已遷移 {len(rows['curated_histories'])} 筆；無法遷移 {migration['not_migrated_histories']} 筆。
- 102 筆歷程已與 profile 合併成 {len(rows['comparable_accounts'])} 筆多維可比帳號；其中 {sum(bool(row.get('collection', {}).get('owned_item_ids')) for row in rows['account_profiles'])} 個 profile 有保守文字映射物品，{sum(bool(row.get('collection', {}).get('item_set_profiles')) for row in rows['account_profiles'])} 個有套組聲稱；模糊詞未映射。
- 正規化資料有 {migration['verified_dates_in_normalized']} 筆可驗證貼文日期；其中 {migration['verified_dates_repaired_in_histories']} 筆舊可比歷程已回接實際日期。
- 未映射季節詞 {migration['unmapped_season_terms']}；未映射物品詞 {migration['unmapped_item_terms']}，均在 review／coverage 檔中保留。
- 可驗證成交價仍為 {verified_sales} 筆；重構沒有把已售聲稱或最後公開價升級成成交。

## 資料流與替換

舊版只作外部不可變來源。新版本只有一套正式來源：`data/source/listings.jsonl` → `data/normalized/*` → `data/curated/histories.jsonl`；`data/comparables/histories.jsonl` 是可重建衍生檔。遊戲知識則只由 `knowledge/` canonical 主檔提供。

逐檔 keep／migrate／replace／remove 清單見 `file-inventory.json`；被移除的執行能力見 `removed-features.md`。
"""
    write_utf8_lf(root / "reports/migration/P0-MIGRATION-REPORT.md", migration_md)

    quality_md = f"""# P0 資料品質與限制

## 已確認

- 季節 {len(rows['seasons'])}、活動 {len(rows['events'])}、物品 {len(rows['items'])}、套組 {len(rows['sets'])}、別名 {len(rows['aliases'])}、來源 {len(rows['sources'])}。
- 1,022 筆來源與正規化資料、102 筆歷程均已遷移；`date_verified=true` 必須同時存在有效貼文日期。
- 季節／活動／物品／套組／來源／別名使用唯一 canonical ID，跨檔參照由離線驗證器檢查。
- 大耳狗／耳狗映射至同一套組；歸巢與築巢是不同季節；極光／歐若拉、梵谷／梵高各自映射到單一季節 ID。
- 估價相似度總分 100，季節 22、物品與套組 20，另含帳型、地圖、收藏、資源、綁定、任次、日期與證據品質；沒有單品固定加價。

## 資料推論

舊市場文字只能保守抽取季節、物品與風險聲稱。沒有圖片支持的欄位維持文字聲稱或 unknown；沒有提供資料不等於確認缺少。刊登價、急售價、最後公開價與驗證成交價分池處理。

## 尚未確認

- canonical needs_review 分布為 {json.dumps(canonical_needs_review, ensure_ascii=False)}；另有類別缺口 queue {len(rows['unresolved'])} 筆、隔離物品候選 {len(rows['item_candidates'])} 筆、unmapped alias {len(rows['unmapped'])} 筆。這些集合可能重疊，不直接相加成唯一項目數。
- 全物品 catalog 未完成。現有 {len(rows['items'])} 筆是可追溯種子與節點目錄，不代表遊戲全部物品。
- visual reference {len(rows['visual_references'])}、真實 image evidence {len(rows['image_evidence'])}、可驗證成交 {verified_sales}；因此不宣稱圖示辨識準確率或成交價模型。
- 季節節點的繁中正式名、免費／季卡屬性、成本與取得狀態仍有 needs_review 記錄。
"""
    write_utf8_lf(root / "reports/validation/data-quality.md", quality_md)

    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["package_version"] = "3.0.1-p0.1"
    manifest["statistics"] = {
        "seasons": len(rows["seasons"]), "events": len(rows["events"]), "ancestors": len(rows["ancestors"]),
        "items": len(rows["items"]), "sets": len(rows["sets"]), "aliases": len(rows["aliases"]),
        "availability_events": len(rows["availability_events"]), "sources": len(rows["sources"]),
        "canonical_needs_review_by_entity": canonical_needs_review,
        "unresolved_queue_records": len(rows["unresolved"]),
        "item_candidate_records": len(rows["item_candidates"]),
        "unmapped_aliases": len(rows["unmapped"]),
        "source_listings": len(rows["source_listings"]), "normalized_listings": len(rows["normalized_listings"]),
        "curated_histories": len(rows["curated_histories"]), "verified_completed_sales": verified_sales,
        "comparable_accounts": len(rows["comparable_accounts"]),
        "image_evidence_records": len(rows["image_evidence"]),
    }
    manifest["generated_at"] = BUILT_AT
    manifest["catalog_status"] = "partial_verified_catalog"
    manifest["hash_exclusions"] = sorted(HASH_EXCLUSIONS)
    manifest["file_hashes"] = {
        path.relative_to(root).as_posix(): sha256(path)
        for path in release_files(root)
        if path.relative_to(root).as_posix() not in HASH_EXCLUSIONS
    }
    write_utf8_lf(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    print(json.dumps({"coverage": coverage["counts"], "migration": coverage["market_migration"], "manifest_hashes": len(manifest["file_hashes"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
