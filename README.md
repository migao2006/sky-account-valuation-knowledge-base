# Sky 光遇帳號估價知識庫 v3.0.1 P0.1

這是完全離線的靜態知識庫與估價工具資料包。它以匿名化市場刊登資料、可追溯的遊戲知識主檔與可重建的衍生資料為基礎；不會登入帳號、讀取私人社團、傳送訊息或連線更新。

v3.0.1 P0.1 的範圍是修復發布完整性、分類器輸出契約與估價器整合，不是全物品完成版。這一版不擴充物品資料、不新增市場資料，也不重新加入回測、校準、漂移監控或網路執行能力。

## 快速入口

- [`knowledge/README.md`](knowledge/README.md)：季節、活動、物品、套組、別名及來源主檔。
- [`data/README.md`](data/README.md)：匿名來源、正規化、人工審核與可比資料。
- [`schemas/README.md`](schemas/README.md)：所有 JSON/JSONL 資料契約；使用者本次估價輸入契約見 [`schemas/input/valuation-account.schema.json`](schemas/input/valuation-account.schema.json)。
- [`tools/README.md`](tools/README.md)：Python 3 離線重建、分類、估價與驗證入口。
- [`docs/architecture/architecture.md`](docs/architecture/architecture.md)：資料流與 canonical source of truth。
- [`reports/README.md`](reports/README.md)：遷移、覆蓋率與驗證結果。

## 離線保證

儲存庫內的正式工具永遠只讀寫本目錄內的資料，永遠不主動連網；不包含 HTTP、API client、Provider、爬蟲、網頁自動化、背景服務、排程器或自動更新。外部執行者可以在儲存庫外上網研究，但研究結果若要成為正式資料，必須先進入 review，不能直接升級 canonical。離線使用者不需開啟來源網址。

## 資料邊界

正式多維估價可比輸入是 `data/comparables/accounts.jsonl`。它是由歷程資料與對應的 account profile 離線合併的衍生檔，包含季節、物品／套組、收藏、地圖、資源、綁定與交易條件等估價維度。`data/comparables/histories.jsonl` 只保存純價格歷程，**不是完整估價輸入**；將 history 檔當成 account comparable 輸入時應清楚報錯，不得以大量 unknown 靜默估價。

市場資料只保存匿名 ID 與必要的交易事實。不得加入玩家姓名、帳號、UID、電話、Email、付款資料、登入資訊、社群帳號或可回推至原貼文的 locator。

本版本不把單件物品換算為固定價格；物品、季節與套組只用於辨識帳號結構、完成度與可比帳號選擇。正式市場資料中，目前只有三筆同時確認幣別為 TWD 且伺服器為國際服，因此估價適用範圍有限，不能代表完整市場。

## 分類、估價與證據

分類器只接受受控的結構化聲稱，輸出使用者本次估價的 `valuation-account` 契約；它不宣稱能直接理解圖片、OCR 或任意原始貼文。圖片目前只是 evidence contract：可記錄圖片雜湊、角色、標註與審核狀態，但不是截圖辨識或物品圖示辨識引擎。

估價器先建立一致的內部 account representation，再執行 hard pool、帳型與相似度選擇。品質門檻是至少三筆 hard-pool 相容案例、至少三筆有有效價格的案例、每筆達到至少 40/100 的最低相似度，以及至少三個有效內容維度；少於三筆、低相似度、有效維度不足或證據不足時回傳 `insufficient_comparables`，不輸出價格區間。`unknown` 不會被當成相同，也不會被當成已確認缺少；輸出會分開列出已確認差異與尚未確認的維度。

## 重建與驗證

完成的版本可從根目錄以 Python 3 執行：

```powershell
python tools/validate/build_reports.py --root .
python tools/validate/validate.py --root .
python tools/classify/classify.py input-claims.json --output valuation-account.json
python tools/estimate/estimate.py valuation-account.json data/comparables/accounts.jsonl --output estimate.json
```

`manifest.json` 記錄版本、資料統計、檔案 hash 與來源 ZIP 指紋。P0.1 仍未完成全物品資料、圖片 evidence 的實際辨識、visual references 或 verified sales；已售聲稱不會被升級為 verified sale。
