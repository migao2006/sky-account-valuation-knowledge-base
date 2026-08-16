# 離線工具

工具採 Python 3，僅處理本機 JSON／JSONL。正式程式不得 import 或呼叫 HTTP、socket、API、Provider、網頁自動化、排程或背景服務。

- `migrate/`：將 v2.4 已匿名資料遷移到新契約並產生逐列 ledger。
- `normalize/`：別名正規化及資料清理。
- `classify/`：產生多維帳號 profile 與季節矩陣。
- `estimate/`：離線選擇可比案例並輸出透明理由。
- `validate/`：schema、參照、隱私、日期及規則驗證。

目前資料入口為 `data/source/listings.jsonl`、`data/normalized/listings.jsonl`、`data/normalized/account-profiles.jsonl`、`data/curated/histories.jsonl`，以及由 profile 與 history 合併的衍生 `data/comparables/accounts.jsonl`。`data/comparables/histories.jsonl` 保留純價格歷程，不能單獨用來做多維估價。

```powershell
python tools/validate/validate.py
python tools/classify/classify.py input-claims.json --output account-profile.json
python tools/estimate/estimate.py account-profile.json data/comparables/accounts.jsonl --output estimate.json
```

分類器只接受受控結構化聲稱；未提供或無法確認的欄位保留 `unknown`／`needs_review`，不保存原始自由文字。估價器不足三筆同類可比時回傳資料不足，不會靜默混入不相容帳型。
