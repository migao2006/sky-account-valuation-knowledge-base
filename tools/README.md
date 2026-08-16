# 離線工具（v3.5 P2.3）

核心工具採 Python 3 標準函式庫，只處理本機 JSON／JSONL。`modeling/` 是獨立鎖版的可選科學運算環境；它也不含下載、HTTP、排程或背景能力。

- `migrate/`：將 v2.4 已匿名資料遷移到新契約並產生逐列 ledger。
- `normalize/`：別名正規化及資料清理。
- `classify/`：將受控結構化聲稱轉成使用者估價輸入 profile 與季節矩陣。
- `estimate/`：離線選擇可比案例並輸出透明理由。
- `modeling/`：建立三態 Item Vector、清洗正常／急售價格，並提供模型估價整合入口。
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

正式市場資料目前只有兩筆正常刊登同時確認 TWD、國際服與單一價格語義；唯一急售觀察含仲，56,000 元觀察另有分期加價，均保留為 `needs_review`，不猜測或計算替代價格。估價適用範圍有限。這一版新增固定 vendor catalog 的 review evidence 與一筆明示覆核恢復歷程，但不把二級來源自動升級 canonical，也不加入回測、校準或自動資料更新。

## P2.3 Catalog reference 與市場證據資料流

`tools/normalize/build_catalog_universe.py` 對固定 vendor snapshot 作全量封閉分類；`build_source_scoped_item_identities.py` 產生單一 1,758 筆 source-scoped reference identity 主檔，並禁止 canonical 與模型提升；Fandom import 工具只重播固定 revision 且不提供獨立 promotion evidence。`build_item_evidence_bundle.py` 與 `promote_items.py` 不修改 canonical；`apply_nintendo_starter_pack.py` 分開重播官方描述性成分與 vendor 精確名稱，不推測未知欄位。`build_market_claim_review.py` 產生固定 200 筆匿名人工雙標 queue；`build_market_near_miss_review.py` 目前產生 16 筆只缺單一硬證據群組的匿名 queue。兩條市場 evidence ledger 在真正人工標註與裁決前保持空白。

`parse_item_vectors.py` 會為每個帳號與每個 canonical item 產生 `owned`、`confirmed_missing` 或 `unknown`；未提及永遠是 unknown。`clean_prices.py` 只保留已驗證 TWD、international、seller listing、single account，並將正常刊登與急售分開。

正式結果為 1,022 個向量、2 筆正常刊登、0 筆可訓練急售、101 筆排除／待審。模型門檻未達時，`model_estimator.py` 回傳 `insufficient_training_data`，不輸出模型價格；既有 comparable estimator 仍可作保守 fallback。

## 網路與圖片邊界

外部執行者可以在儲存庫外上網研究；儲存庫工具永遠不主動連線。外部查證若涉及正式資料，必須先進入 review，不得直接升級 canonical。

圖片功能目前只是 evidence 契約，不是 OCR 或圖示辨識引擎。可記錄圖片雜湊、證據角色與審核狀態，但不能宣稱已完成截圖辨識、visual references 或辨識準確率。
