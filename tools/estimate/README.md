# 離線估價與圖片證據

`estimate.py` 只讀取帳號 JSON 與匿名 comparable JSONL，輸出可比帳選擇結果。它使用固定 100 分結構相似度，沒有任何物品加價表、匯率、網路連線或背景更新。

```powershell
python tools/estimate/estimate.py input-account.json data/comparables/accounts.jsonl --output estimate.json
```

正式可比輸入是完整巢狀帳號 profile：`data/comparables/accounts.jsonl`；單獨的 `histories.jsonl` 缺少帳號維度，CLI 會明確拒絕。省略第二個位置參數時也會使用 `accounts.jsonl`。

幣別、伺服器與價格型態是硬分池。只有至少三筆 hard-pool 相容、具有效價格、達最低 40 分相似度且各有至少三個有效內容維度的案例，才會輸出價格區間；否則回傳 `insufficient_comparables` 與 `range_twd: null`，並列出 hard-pool、品質與整體不足原因。未知資料不會視為相同，已確認不同與未確認維度會分開輸出。

目標帳號的 `trade_conditions` 必須明確為 `offer_kind: seller_listing` 與 `entity_kind: single_account`。買方預算、服務、交換、套組及未知交易型態不會借用單帳賣方價格池。

`evidence.py` 只提供圖片證據資料契約與驗證。`ocr_text` 只可表示文字觀察，不能直接聲稱偵測到物品；物品圖示需獨立的 `icon_match` 或人工標註 row，並指定已存在的 `item_*` canonical ID。正式 evidence 禁止原始 OCR 內容、玩家資料、網址及本機圖片路徑。
