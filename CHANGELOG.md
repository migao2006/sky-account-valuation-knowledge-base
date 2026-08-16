# 變更紀錄

## 3.4.0-p2.2 — 2026-08-17

- 新增 1,758 筆 review-only vendor collectible registry；64 canonical link、296 candidate link、1,398 unresolved，所有跨類型名稱衝突隔離，canonical/model writes 均為 0。
- 固定 Fandom Printable Seasonal Cosmetics revision 107991，產生 700 筆 template-coordinate crosswalk；明示與既有 printable 同 lineage，獨立證據與 canonical promotion 都為 0。
- 人工 market-claim 盲審佇列由 20 擴為 200 筆，gold 仍為 0，未以機器標籤冒充人工標註。
- 帳號 profile 與 Item Vector 同時使用 listing text 和 normalized feature summary，保留逐來源 provenance、衝突 fail-closed；collection profile 覆蓋提高但仍只使用 canonical 精確別名。
- 正常刊登模型價格列仍只有 3 筆、急售 0；正式模型與 item value table 維持停用。

## 3.3.0-p2.1 — 2026-08-17

- 將固定 vendor snapshot 的 3,266 筆列完整對帳：64 canonical-linked、296 candidate-linked、1,398 unmatched、1,508 explicitly-excluded，沒有靜默遺失。
- 新增 1,776 筆可重播的 template-seed/vendor correlation 記錄，以及 622 筆 fail-closed review ledger；284 筆有單一獨立 vendor correlation、338 筆拒絕，canonical identity 仍 unresolved，canonical writes 與 model promotions 都維持 0。
- 自動 exact-match 證據明確標記為 `machine_correlated`，不冒充人工審核；season、取得、availability、成本與 visual reference 未因此升級。
- 新增固定 20 筆匿名 market-claim 人工 review queue 與雙人獨立標註＋人工裁決契約；正式 human gold 維持 0。
- 資源解析可保守保存「約／近」數值為 approximate claim；「以上／起／+」等下限聲稱不轉成精確值。正式嚴格市場池仍是正常刊登 3、急售 0，模型保持停用。

## 3.2.0-p2 — 2026-08-17

- 固定保存 MIT 授權 `skygame-data@1.3.4` 的離線快照、來源 metadata、SHA-256 與 3,266 筆逐列 crosswalk；正式工具不含下載或網路能力。
- 64 個 vendor 名稱精確命中 canonical，296 個精確命中 candidate；296 筆欄位級 evidence 全為 `needs_review`，沒有自動升級 canonical 或模型物品特徵。
- 新增完整知識庫、文案解析、市場標籤、圖片與精準估價的可量測完成契約，避免把 schema 通過誤稱內容完整或模型精準。
- 以明示 review 決策、strict predicates 與 predicate hash 恢復 `listing_0792`，正式歷程成為 102 legacy + 1 reviewed recovery；`listing_0864` 仍因交易型態未知與既有排除理由拒絕。
- 明示「急售」不再混入正常 asking 線；唯一急售列又明示含仲，保留 urgent 語意但以 `brokerage_included_price` 進 `needs_review`，不猜測仲介費。正式清洗結果為正常刊登 3、可訓練急售 0、排除或待審 100，四個模型仍為 `insufficient_training_data`。
- 可比選樣新增同帳號、來源 listing 重疊與重複群組排除，避免 self-comparable 或重貼洩漏。
- 季節與 feature summary 改為欄位級來源合併；衝突保持 unknown/conflict，「凜冬」進 review 而不猜測 canonical season。

## 3.1.0-p1 — 2026-08-16

- 新增 1,022 筆三態 Item Vector；未提及物品保持 unknown，待審核物品不得進正式模型特徵。
- 新增正常刊登／急售分線的嚴格價格清洗：正式結果為正常 3、急售 0、排除或待審 99。
- 新增隔離、無網路的 Elastic Net、XGBoost、TreeSHAP 與條件式 Item Value Table 管線。
- 新增模型資料門檻、分組巢狀交叉驗證、snapshot hash、純 JSON／安全模型 artifact 與模型估價入口。
- 正式模型仍為 `insufficient_training_data`；94 列 Item Value Table 均為 `insufficient_support`，不輸出單品價值或模型估價。

## 3.0.1-p0.1 — 2026-08-16

- 修復 v3 P0 的發布完整性、換行與 manifest 重建說明，要求以 UTF-8 LF checkout 驗證實際檔案位元組。
- 明確以 `data/comparables/accounts.jsonl` 作為正式多維估價輸入；`data/comparables/histories.jsonl` 僅是價格歷程，不是完整估價輸入。
- 修復 nested account profile 的分類器／估價器資料契約邊界，將使用者估價輸入與市場正式 account profile 分開建模。
- 將估價品質門檻文件化：至少三筆 hard-pool 相容案例、至少三筆有效價格、最低相似度 40/100 與至少三個有效內容維度；不足時回傳 `insufficient_comparables`，不輸出價格區間。
- 明確區分已確認差異與資料未知；`unknown` 不會匹配 `unknown`。collection 的 graduation rewards、collaboration items、bundles 與 event-limited items 使用聯集。
- 估價目標必須明確為 `seller_listing` 與 `single_account`；買方預算、服務、交換、套組與未知交易型態一律 fail closed。
- 離線 ZIP 固定以 manifest 的 `package_id` 作為根目錄，因此不同 checkout 資料夾名稱仍會產生相同封裝雜湊。
- 明確限制圖片功能目前只是 evidence contract，不是 OCR 或截圖／物品圖示辨識引擎；外部研究可上網，但儲存庫工具永遠不主動連網。
- 本版不擴充全物品資料、不新增市場資料、不重新引入回測、校準、漂移監控、Provider、排程或背景更新。正式市場資料目前僅三筆同時確認 TWD 與國際服，估價適用範圍有限；全物品、visual references、圖片 evidence 與 verified sales 仍未完成。

## 3.0.0-p0 — 2026-08-16

- 從 v2.4 重構為單一、離線、可驗證的知識庫架構。
- 將遊戲知識主檔、匿名市場資料、衍生可比資料、工具、測試與報告分離。
- 加入 canonical season、event、item、set、alias、availability、source 和 image evidence 契約。
- 移除 backtest、calibration、drift、prediction outcome、follow-up、provider、網路與排程功能。

此檔案只記錄正式版本行為變化；資料遷移細節見 `reports/migration/P0-MIGRATION-REPORT.md`。
