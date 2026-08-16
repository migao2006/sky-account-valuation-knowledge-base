# Sky 光遇帳號估價知識庫 v3.0 P0

這是完全離線的靜態知識庫與估價工具資料包。它以匿名化市場刊登資料、可追溯的遊戲知識主檔與可重建的衍生資料為基礎；不會登入帳號、讀取私人社團、傳送訊息或連線更新。

## 快速入口

- [`knowledge/README.md`](knowledge/README.md)：季節、活動、物品、套組、別名及來源主檔。
- [`data/README.md`](data/README.md)：匿名來源、正規化、人工審核與可比資料。
- [`schemas/README.md`](schemas/README.md)：所有 JSON/JSONL 資料契約。
- [`tools/README.md`](tools/README.md)：Python 3 離線重建、分類、估價與驗證入口。
- [`docs/architecture/architecture.md`](docs/architecture/architecture.md)：資料流與 canonical source of truth。
- [`reports/README.md`](reports/README.md)：遷移、覆蓋率與驗證結果。

## 離線保證

正式工具只能讀寫本目錄內的資料，不包含 HTTP、API client、Provider、爬蟲、背景服務、排程器或自動更新。建置研究使用的來源已寫入 `knowledge/sources/sources.jsonl`；離線使用者不需開啟來源網址。

## 資料邊界

市場資料只保存匿名 ID 與必要的交易事實。不得加入玩家姓名、帳號、UID、電話、Email、付款資料、登入資訊、社群帳號或可回推至原貼文的 locator。

本版本不把單件物品換算為固定價格；物品、季節與套組只用於辨識帳號結構、完成度與可比帳號選擇。

## 重建與驗證

完成的版本可從根目錄以 Python 3 執行 `python tools/validate/validate.py`。新帳號先用 `python tools/classify/classify.py input-claims.json --output account-profile.json` 產生保守 profile，再執行 `python tools/estimate/estimate.py account-profile.json data/comparables/accounts.jsonl --output estimate.json`。`accounts.jsonl` 是由 102 筆 history 與其多維 account profile 離線合併的衍生檔，讓季節、物品／套組聲稱、資源與綁定實際參與相似度。詳細命令、輸入輸出與限制見 `tools/README.md`。`manifest.json` 記錄版本、資料統計、檔案 hash 與來源 ZIP 指紋。
