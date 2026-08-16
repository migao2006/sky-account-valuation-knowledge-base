# 變更紀錄

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
