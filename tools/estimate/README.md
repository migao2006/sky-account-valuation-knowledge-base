# 離線估價與圖片證據

`estimate.py` 只讀取帳號 JSON 與匿名 comparable JSONL，輸出可比帳選擇結果。它使用固定 100 分結構相似度，沒有任何物品加價表、匯率、網路連線或背景更新。

```powershell
python tools/estimate/estimate.py input-account.json data/comparables/histories.jsonl --output estimate.json
```

幣別、伺服器與價格型態是硬分池。三筆以下會回傳 `insufficient_comparables` 及 `range_twd: null`。輸入帳號與可比帳使用 `base_account_type`、`season_profile`、`owned_item_ids`、`complete_set_ids`、`resources`、`bindings`、`map_completion_ratio`、`evidence_quality` 等欄位。

`evidence.py` 只提供圖片證據資料契約與驗證。`ocr_text` 只可表示文字觀察，不能直接聲稱偵測到物品；物品圖示需獨立的 `icon_match` 或人工標註 row，並指定已存在的 `item_*` canonical ID。正式 evidence 禁止原始 OCR 內容、玩家資料、網址及本機圖片路徑。
