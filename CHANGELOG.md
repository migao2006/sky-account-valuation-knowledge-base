# 變更紀錄

## 3.8.0-p2.6 — 2026-08-17

- 新增 FAQ 968 六件 AURORA 官方證據 cohort；固定 fact-limited transcription 與獨立 vendor snapshot，保留目前供應、永久性、正式繁中名與視覺身份為 unknown。
- 新增 To The Love Outfit、Giving In Cape 兩筆 canonical；FAQ 968 套組只表示四件 remaining seasonal IAP，明確不宣稱完整 AURORA 付費物 catalog。
- Canonical 總數 96、verified identity 10、model eligible 0；Catalog query index 2,476，vendor relation 69／296／1,393。
- 補上 evidence target／field／value／source lineage 語義 gate，並移除發布鏈對 94 件與 Nintendo 唯一 cohort 的硬編碼。
- 季節 parser 僅在明確季節上下文解析「集結／集结／破碎」；平台綁定的「第一任」不再污染整帳任次。正式價格維持正常 3、急售 0、verified sale 0，四模型仍停用。

## 3.7.0-p2.5 — 2026-08-17

- 以固定 TGC FAQ 823 fact snapshot 重播官方描述性套組成分，再以獨立 SkyGame-Data snapshot 支持精確英文名稱與類別；不把 vendor 名稱轉錄成官方原文，未證實的繁中名、供應、永久性與價格維持 unknown。
- 新增 18 筆欄位級 evidence、source lineage／JSON pointer／SHA-256 replay gate、四筆 source-description visual reference；沒有保存官方 HTML、圖片或玩家資料。
- Vendor crosswalk 重建為 67 canonical relation、296 candidate relation、1,395 unresolved；source-scoped observation 仍全部禁止 promotion 與模型使用。
- 明示「售／換」改為 mixed transaction；勳章含／不含與分期多價進 semantic review。正式價格仍為正常刊登 3、急售 0、verified sale 0。
- 近失人工 evidence queue 排除 brokerage 與 multi-price 案例，保留 16 筆真正只缺單一硬證據群組的匿名案例；approved evidence 仍為 0。
- 修正 verified item 不會連帶驗證「紅斗」等短俗稱；缺乏 alias-level 審核時不建立持有狀態。

## 3.6.0-p2.4 — 2026-08-17

- 新增 2,474 筆離線 Catalog query index 與結構化 resolver；canonical、review candidate、source observation 維持不同 truth level，verified canonical resolution 仍為 0。
- 3,266 筆 vendor universe 全部增加逐列 scope disposition、理由與證據基礎；WingBuff、Spell、Quest、Special 等 1,508 筆保留 needs review，不再用 type-only 排除冒充完整範圍判定。
- 修正套組三態：unknown／未達 model eligibility 的 required 成員不再輸出 0% 或 `false`，且不進 Elastic Net／XGBoost 特徵。
- 每筆 Item Vector 與四個模型 artifact 綁定 canonical items、aliases、sets 的 Catalog provenance；兩種 trainer 重新驗證正式白名單，不信任 vector 自稱 eligibility。
- 修正急售／急出語意、Game Center 獨立綁定、明示任次、常駐圖畢業、倒裝精確資源與 canonical 收藏投影；正式正常刊登仍為 3、急售 0、verified sale 0，模型保持 fail-closed。

## 3.5.0-p2.3 — 2026-08-17

- 將舊 review registry 遷移為唯一的 `data/normalized/source-scoped-item-identities.jsonl`：1,758 筆來源範圍身分，64 canonical relation、296 candidate relation、1,398 unresolved；全部 canonical unverified、promotion prohibited、model excluded。
- 新增 22 筆匿名 market near-miss field-evidence queue；只列出缺少的硬證據欄位，不保存原文、價格、網址、PII 或機器建議值，approved evidence 維持 0。
- 修正估價相似度：`winged_or_unspecified` 是 migration fallback，不再被視為已確認有翼，也不再因兩邊共享未知值獲得帳型相似分。
- 正式資料仍為 103 筆 comparable、正常刊登 3、急售 0、verified sale 0；模型與 Item Value Table 保持 fail-closed。

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
