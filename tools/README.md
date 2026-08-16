# 離線工具（v3.0.1 P0.1）

工具採 Python 3 標準函式庫，只處理本機 JSON／JSONL。正式程式永遠不主動連網，不得 import 或呼叫 HTTP、socket、API、Provider、網頁自動化、排程或背景服務。

- `migrate/`：將 v2.4 已匿名資料遷移到新契約並產生逐列 ledger。
- `normalize/`：別名正規化及資料清理。
- `classify/`：將受控結構化聲稱轉成使用者估價輸入 profile 與季節矩陣。
- `estimate/`：離線選擇可比案例並輸出透明理由。
- `validate/`：schema、參照、隱私、日期及規則驗證。

## 正式資料入口

資料入口包含 `data/source/listings.jsonl`、`data/normalized/listings.jsonl`、`data/normalized/account-profiles.jsonl`、`data/curated/histories.jsonl`，以及由 profile 與 history 合併的正式衍生可比檔 `data/comparables/accounts.jsonl`。

估價器的正式 comparable 檔案是 `data/comparables/accounts.jsonl`。`data/comparables/histories.jsonl` 只保留價格歷程，沒有完整 profile 維度，**不是完整估價輸入**；若被誤當成 account comparable 輸入，工具應清楚拒絕或回傳格式錯誤。

```powershell
python tools/validate/build_reports.py --root .
python tools/validate/validate.py --root .
python tools/classify/classify.py input-claims.json --output valuation-account.json
python tools/estimate/estimate.py valuation-account.json data/comparables/accounts.jsonl --output estimate.json
```

分類器只接受受控結構化聲稱；未提供或無法確認的欄位保留 `unknown`／`needs_review`，不保存原始自由文字。使用者輸入可沒有市場 listing ID，格式由 `schemas/input/valuation-account.schema.json` 定義；市場正式 account profile 則使用不同的市場契約。

## 估價品質與輸出

估價器先將目標帳號與每筆 nested account comparable 各轉換一次為一致的內部表示，再執行 hard pool、帳型篩選、相似度評分與輸出說明。collection 會聯集 graduation rewards、collaboration items、bundles 與 event-limited items，不因其中一類為空而忽略其他類別。

只有同時達到下列靜態保守門檻才會輸出價格區間：至少三筆 hard-pool 相容案例、至少三筆具有有效價格、最低相似度 40/100，以及至少三個有效內容維度。少於三筆、低相似度、有效維度不足或證據不足時回傳 `insufficient_comparables`，並列出逐筆排除原因與整體不足原因，不會以三筆稀疏案例自動形成可靠區間。

輸出的 `price_type` 只使用正規化值：`normal_listing`、`urgent_sale`、`last_public_price`、`verified_sale` 或 `unknown`。已售聲稱不是 verified sale；未知資料不補值。相似度說明會將已確認不同的 `major_differences` 與資料未知的 `unconfirmed_dimensions` 分開，`unknown` 不會匹配 `unknown`。

正式市場資料目前只有三筆同時確認 TWD 與國際服，估價適用範圍有限。這一版不擴充全物品資料、不新增市場資料、不加入回測、校準或自動資料更新。

## 網路與圖片邊界

外部執行者可以在儲存庫外上網研究；儲存庫工具永遠不主動連線。外部查證若涉及正式資料，必須先進入 review，不得直接升級 canonical。

圖片功能目前只是 evidence 契約，不是 OCR 或圖示辨識引擎。可記錄圖片雜湊、證據角色與審核狀態，但不能宣稱已完成截圖辨識、visual references 或辨識準確率。
