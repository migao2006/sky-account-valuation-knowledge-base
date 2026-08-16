# P0 遷移報告

## 實際結果

- 原始 ZIP：`sky-valuation-v2.4-1022-complete-2026-08-16.zip`，SHA-256 `6AEEBE997E31B65EF4A7FC70E4905CF4AFAFED01FCA986DD55AB22F63EB98DA3`；本次未改寫。
- 原始 ZIP 檔案：237；盤點分類為 migrate 75、replace 131、remove 31、keep 0。
- 71 個舊批次共遷移 1022 筆匿名來源列，正規化 1022 筆，建立 1022 筆帳號 profile。
- 既有 102 筆 legacy 可比歷程已全部遷移；另有 1 筆 normalized listing 經明示人工 review 與可重算 predicate hash 恢復，正式歷程共 103 筆；無法遷移 0 筆。
- 103 筆歷程已與 profile 合併成 103 筆多維可比帳號；其中 24 個 profile 有保守文字映射物品，10 個有套組聲稱；模糊詞未映射。
- 正規化資料有 28 筆可驗證貼文日期；其中 5 筆舊可比歷程已回接實際日期。
- 未映射季節詞 1；未映射物品詞 13，均在 review／coverage 檔中保留。
- 可驗證成交價仍為 0 筆；重構沒有把已售聲稱或最後公開價升級成成交。

## 資料流與替換

舊版只作外部不可變來源。新版本只有一套正式來源：`data/source/listings.jsonl` → `data/normalized/*` → `data/curated/histories.jsonl`；`data/comparables/histories.jsonl` 是可重建衍生檔。遊戲知識則只由 `knowledge/` canonical 主檔提供。

逐檔 keep／migrate／replace／remove 清單見 `file-inventory.json`；被移除的執行能力見 `removed-features.md`。
