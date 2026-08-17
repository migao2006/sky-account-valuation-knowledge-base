# 變更紀錄

## 4.5.0-p3.3 — 2026-08-17

- 新增 Days of Sunlight FAQ 1343 core-three 的可重播官方／vendor identity 與歷史成本證據。
- 新增 19 項 exact-English model eligibility；中文玩家詞仍為 review-only。
- 新增外部簽章 parser gold、locked development/held-out split 與 precision/recall/collision 評估。
- publication evaluator 可自行訓練固定 train-only 模型並重播 holdout 指標；runtime/release 只接受精確 artifact binding。
- signed market intake v3 新增獨立 verified-sale metadata 契約；因尚無可重播成交證據 archive，production pool 明確 fail closed。
- 正式市場授權與真人 gold 仍為 0；估價保持 fail closed。

## 4.4.0-p3.2 — 2026-08-17

- 新增 Days of Color FAQ 1323 core-three：3 件官方逐項 identity／歷史成本證據；目前 112 canonical、30 verified，全部仍排除於模型。
- 授權市場 manifest v2 可用外部三方簽章把價格 observation、去識別 feature payload、正式 Item Vector、catalog provenance 與 signed dedup cluster 原子綁定；交換、竄改與重複 commitment 皆 fail closed。
- publication dataset／readiness schema 改為由證據推導 `not_ready` 或 `ready_for_evaluation`，不再永久硬編未完成；新增不信 artifact 自填欄位的 publication evaluation boundary。
- 新增正式 `completion-status.json`，逐條報告完整知識庫、parser gold、市場 gold、300/100 時間切分、verified sales 與模型評估的達成狀態。
- 新增 FAQ 968 六個官方英文精確 item title 的 parser 回歸；未核准中文玩家詞即使未來 item eligible 仍保持 unknown。

## 4.3.0-p3.1 — 2026-08-17

- 新增 Tournament of Triumph FAQ 1330 core-four：4 件 canonical identity 與歷史取得成本可重播驗證，仍不推論目前供應、玩家持有或轉售價。
- 新增外部授權市場 dataset intake：repo 外聲明與 trust root、三角色 OpenSSH 簽章、逐 observation row／cluster／manifest digest 綁定；空 registry 維持離線 fail closed。
- 正式 cleaner、估價 CLI、validator、report 與 release gate 共用同一授權 verifier；手填 market authorization 不能進入 clean price，且在完整 feature/vector lineage 尚未簽署前，合法 price-only observation 也不會解鎖訓練或估價。
- 新增固定 publication dataset／split 與 parser knowledge coverage 報告；目前 dataset 為 0、狀態 `not_ready`、模型白名單仍為 0。

## 4.2.0-p3.0 — 2026-08-17

- 新增 SkyFest FAQ 1330 core-five 的官方／固定 vendor identity evidence；維持目前供應、永久性、正式繁中名、視覺身份與模型 eligibility 為 unknown／excluded。
- 新增官方歷史取得成本參考層；bundle 不分攤、全列 `model_feature=false`，且明示不推論帳號轉售價。
- 市場人工 ledger 改以外部信任根、三個不同 OpenSSH keys 與 detached signatures 驗證；無信任根時非空 ledger fail closed。
- 103 筆既有市場歷程標示為 `legacy_research_only`；沒有外部資料授權 evaluator 時，正式正常／急售訓練列皆為 0，估價器不輸出價格。
- 新增 deterministic publication-readiness 報告；目前狀態仍為 `not_ready`，不接受 artifact 自填發布指標。

## 4.1.0-p2.9 — 2026-08-17

- 新增 Kizuna AI 2022 FAQ 879 三件可重播官方／獨立 vendor identity cohort；Hair、Bow、Cape 與 bounded set scope 均已驗證，但目前供應、永久性、正式繁中名、視覺身份與個別價格仍為 unknown／`bundle_only`。
- 移除錯掛在 Bow 單品的「絆愛三件套／絆愛套組」待審 alias；未將其轉成自動可解析的 verified set alias。
- 新增 1,022 筆帳號 Catalog lexical review sidecar：僅掃 seller single-account、抑制碰撞與短英文，160 個命中全部維持 review-only，不改寫 ownership、Item Vector、相似度或模型。
- 將「最多分三期，超過一期加 500」辨識為 payment-dependent multi-price；不推算替代價格，`history_0068` 進 needs-review，正式正常價格由 3 筆降為 2 筆。
- Vendor crosswalk 重建為 76 canonical relation、296 candidate relation、1,386 unresolved；query index 為 2,480 筆、verified canonical resolution 18、model eligible 0。

## 4.0.0-p2.8 — 2026-08-17

- 新增 Moomintroll Accessory Set 兩件可重播官方／獨立 vendor identity cohort；套組兩件均為 required，歷史價格只保存 USD 11.99。
- 目前供應、回歸政策、永久性、正式繁中名、視覺身份與單件價格仍為 unknown／`bundle_only`，兩件仍排除模型。
- Canonical evidence cohort 改由 schema registry、受限 verifier allowlist 與實際 ledger targets 動態驗證；發布鏈不再逐 cohort 硬編路徑或 row count。
- Vendor crosswalk 重建為 74 canonical relation、296 candidate relation、1,388 unresolved；query index 為 2,478 筆、verified canonical resolution 15、model eligible 0。
- 估價器會尊重資源欄位 provenance：`approximate` 數值不再提供精確相似度分數或有效內容維度；正式三筆價格仍不足，估價維持 `insufficient_comparables`。

## 3.9.0-p2.7 — 2026-08-17

- 新增 Journey Pack 三件可重播官方／獨立 vendor identity cohort；新增 Journey Hair、Journey Mask，並驗證 Journey Cape 與三件套組。
- 單件價格維持 `bundle_only`；只保存歷史套組 USD 24.99，現時供應、永久性、正式繁中名與圖片身份仍為 unknown，模型仍排除。
- 修正中文頓號造成的跨平台綁定污染、「無法轉出／註銷／被封」高風險漏判，以及「半畢業」誤升完整畢業。
- 發布契約改為資料衍生的一致性 gate，不再把空人工 gold、空核准 evidence、固定 1,022／103／3／0 或永遠 insufficient 模型當作未來版本成功條件。
- 模型 evaluator 在沒有獨立 time-forward publication evidence 時拒絕 trained artifact；正式三筆價格仍不足，估價維持 `insufficient_comparables`。

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
