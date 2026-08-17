# Sky 光遇知識庫與授權估價框架 v4.8 P3.6

這是完全離線的靜態知識庫與估價工具資料包。它以匿名化市場刊登資料、可追溯的遊戲知識主檔與可重建的衍生資料為基礎；不會登入帳號、讀取私人社團、傳送訊息或連線更新。

v4.8 P3.6 新增 Days of Love FAQ 1374 core-four 的可重播官方／vendor evidence，並完成三條不降低安全門檻的外部契約：雙獨立簽章的 identity→cluster mapping、不可由公開 manifest 反推個別 split 的 keyed parser custodian protocol，以及雙 issuer 的 verified-sale receipt archive replay。市場 payload 也擴為 catalog-bound 的完整八組特徵與 exact item states，訓練與 runtime 共用同一 canonical mapping。上述能力都只接受 release root 外、SHA-256 固定且可重播的資料；正式 registry、identity mapping、receipt archive、真人 gold 與圖片資產仍為空，所以 production training／verified-sale pool／估價仍保持 not ready。所有正式工具只處理本機檔案，不主動連網。

目前資料仍不足以訓練可信模型：103 筆既有市場歷程全標示為 `legacy_research_only`，授權 dataset registry 為空，因此正式正常／急售／verified-sale 列皆為 0。123 個 canonical item 中 44 筆 identity 已驗證，19 筆只允許官方精確英文 token 進入模型白名單；正式帳號資料仍沒有可發布的授權價格。四個正式模型 artifact 均為 `insufficient_training_data`，Item Value Table 也全部為 `insufficient_support`。

P2 固定保存 MIT 授權 `skygame-data@1.3.4` 的 3,266 筆欄位限制快照。P3.5 的 relation、成本參考、parser coverage、lexical sidecar 與 visual locator 都只是來源／文字覆核關係，不會自動提升 ownership 或轉售價。新增的 provider／parser onboarding 只會產生 repo 外候選包與簽署 payload，不會伪造正式資料。固定 publication dataset／split／evaluation 報告目前為空且 `not_ready`；[`reports/completion-status.json`](reports/completion-status.json) 逐條公開尚未完成的契約。完整知識庫與精準估價的正式完成門檻見 [`docs/methodology/completion-contract.md`](docs/methodology/completion-contract.md)。

本專案不會抓取公開第三方帳號交易貼文來補足訓練資料。官方條款禁止帳號出售／轉讓，新的市場資料必須具備明確授權、去識別、固定來源 bytes 與可驗證人審；詳見 [`docs/methodology/market-data-authorization-policy.md`](docs/methodology/market-data-authorization-policy.md)。在此之前，轉售估價維持 fail closed；官方歷史取得成本也不得被解讀為帳號轉售價。

P2.4 也修正 Item Vector 的套組三態：任何 required 成員未知或尚未達 model eligibility 時，套組比例與完整旗標維持 `null`，不再把缺資料寫成 0%／不完整。每筆 vector 與模型 artifact 都綁定 canonical item、alias、set 的 Catalog provenance；Catalog 變更但未重建時會 fail closed。3,266 筆 vendor 列均有逐列 scope disposition，但其中 1,508 筆仍需範圍審查，不能據此宣稱全物品完成。

## 快速入口

- [`knowledge/README.md`](knowledge/README.md)：季節、活動、物品、套組、別名及來源主檔。
- [`data/README.md`](data/README.md)：匿名來源、正規化、人工審核與可比資料。
- [`schemas/README.md`](schemas/README.md)：所有 JSON/JSONL 資料契約；使用者本次估價輸入契約見 [`schemas/input/valuation-account.schema.json`](schemas/input/valuation-account.schema.json)。
- [`tools/README.md`](tools/README.md)：Python 3 離線重建、分類、估價與驗證入口。
- [`modeling/README.md`](modeling/README.md)：隔離的 Elastic Net、XGBoost、TreeSHAP 與 Item Value Table 管線。
- [`docs/architecture/architecture.md`](docs/architecture/architecture.md)：資料流與 canonical source of truth。
- [`reports/README.md`](reports/README.md)：遷移、覆蓋率與驗證結果。

## 離線保證

儲存庫內的正式工具永遠只讀寫本目錄內的資料，永遠不主動連網；不包含 HTTP、API client、Provider、爬蟲、網頁自動化、背景服務、排程器或自動更新。外部執行者可以在儲存庫外上網研究，但研究結果若要成為正式資料，必須先進入 review，不能直接升級 canonical。離線使用者不需開啟來源網址。

## 資料邊界

正式多維估價可比輸入是 `data/comparables/accounts.jsonl`。它是由歷程資料與對應的 account profile 離線合併的衍生檔，包含季節、物品／套組、收藏、地圖、資源、綁定與交易條件等估價維度。`data/comparables/histories.jsonl` 只保存純價格歷程，**不是完整估價輸入**；將 history 檔當成 account comparable 輸入時應清楚報錯，不得以大量 unknown 靜默估價。

市場資料只保存匿名 ID 與必要的交易事實。不得加入玩家姓名、帳號、UID、電話、Email、付款資料、登入資訊、社群帳號或可回推至原貼文的 locator。

本版本不把單件物品換算為固定價格。Item Value Table 是控制其他特徵後的條件歸因，不能逐件相加；未達持有、具證據的確認缺少、跨 refit fold 方向穩定度及模型 provenance 門檻時不顯示數值。單一模型內的 bootstrap 只作診斷，不能自行解鎖物品歸因。正式市場資料中沒有任何一筆同時具備外部可重播資料授權與訓練資格，因此模型保持停用。

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
python tools/modeling/parse_item_vectors.py --root .
python tools/modeling/clean_prices.py --root .
python tools/estimate/model_estimator.py valuation-account.json --root . --output model-estimate.json
```

`manifest.json` 記錄版本、資料統計、模型狀態、檔案 hash 與來源 ZIP 指紋。P3.6 仍未完成全物品 canonical identity、圖片 evidence 的實際辨識或任何正式 verified sale；visual capability 報告明確記錄實體資產 0、核准 detection 0。已售聲稱不會被升級為 verified sale。
