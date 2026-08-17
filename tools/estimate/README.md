# 離線估價與圖片證據

`estimate.py` 只讀取帳號 JSON 與匿名 comparable JSONL，輸出可比帳選擇結果。它使用固定 100 分結構相似度，沒有任何物品加價表、匯率、網路連線或背景更新。

```powershell
python tools/estimate/estimate.py input-account.json data/comparables/accounts.jsonl --output estimate.json
```

正式可比輸入是完整巢狀帳號 profile：`data/comparables/accounts.jsonl`；單獨的 `histories.jsonl` 缺少帳號維度，CLI 會明確拒絕。省略第二個位置參數時也會使用 `accounts.jsonl`。

幣別、伺服器與價格型態是硬分池。只有至少三筆 hard-pool 相容、具有效價格、達最低 40 分相似度且各有至少三個有效內容維度的案例，才會輸出價格區間；否則回傳 `insufficient_comparables` 與 `range_twd: null`，並列出 hard-pool、品質與整體不足原因。未知資料不會視為相同，已確認不同與未確認維度會分開輸出。

資源的數值相似度會讀取欄位來源：`field_evidence.resources.values.<key>.claim_kind: approximate` 表示約數，該資源一律不計入數值相似度或有效內容維度；`exact` 與沒有欄位來源的既有結構化輸入仍可比較。

目標帳號的 `trade_conditions` 必須明確為 `offer_kind: seller_listing` 與 `entity_kind: single_account`。買方預算、服務、交換、套組及未知交易型態不會借用單帳賣方價格池。

`model_estimator.py` 是離線模型入口，讀取同一個結構化帳號 JSON。`trained` artifact 不信任其內嵌的 `publication_gate`；只有當目前的可重播 publication evaluation 報告為 `passed`，而且其單一 binding 精確覆蓋 artifact bytes、模型 payload、frozen dataset manifest 與 split 雜湊時才可發布。正式 P3.3 有 0 筆獲外部授權的正常刊登、0 筆急售與 0 筆 verified sale，四個 artifact 皆停用，因此模型入口會回傳資料不足，而不是產生模型價格。

`estimate.py` CLI 不接受可注入的授權 callback，也不宣稱已啟用 signed comparable。P3.3 的外部材料重播已接到訓練資料 cleaner 與獨立 verified-sale pool；估價器的授權接線仍是明列的未完成邊界。

`evidence.py` 只提供圖片證據資料契約與驗證。`ocr_text` 只可表示文字觀察，不能直接聲稱偵測到物品；物品圖示需獨立的 `icon_match` 或人工標註 row，並指定已存在的 `item_*` canonical ID。正式 evidence 禁止原始 OCR 內容、玩家資料、網址及本機圖片路徑。
