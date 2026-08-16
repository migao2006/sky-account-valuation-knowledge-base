# 估價方法（v3.1 P1）

P1 保留 P0.1 的「可比帳號選擇器」，並新增資料門檻控制的可解釋模型線；兩者都不是把物品價格相加的報價表。它以帳型、季節結構、物品與套組、完成度、地圖、收藏、資源、綁定、任次、日期和證據品質選擇透明的同類案例。

## 輸入與正規化

正式多維 comparable 輸入是 `data/comparables/accounts.jsonl`。每列同時帶有 account profile 與 history 維度；`data/comparables/histories.jsonl` 只有價格歷程，不能單獨支撐完整估價。估價器會將目標帳號與每個 nested comparable 各轉換一次為一致的內部表示，之後 hard pool、帳型篩選、相似度評分、選樣說明與價格型態都只使用該表示，不在後段重新讀取未轉換的頂層欄位。

若輸入只有 history、沒有 profile 維度，工具應清楚拒絕或回傳格式錯誤，不得悄悄以大量 `unknown` 進行估價。

## 分池與相似度

先排除服務、收購、混價及多帳資料，再依單帳、相容帳型家族、伺服器／幣別證據及價格型態分池。輸入已明示 TWD／國際服時，幣別或伺服器未知或不相符的案例不會進入同一價格池。相似度總分 100：帳型 15、季節 22、物品與套組 20、地圖 10、收藏結構 8、資源 7、綁定 6、任次 4、日期 5、證據 3。

collection 維度是下列集合的聯集：graduation rewards、collaboration items、bundles 與 event-limited items；任何一類即使為空，也不能遮蔽其他已知集合。季節矩陣、已映射物品、套組聲稱、資源與逐平台綁定是實際評分欄位，不是輸出裝飾。文字只提到套組但未證明完整時只形成 `mentioned_unverified`，不得升級為完整套組。

未知資料不會得到相同分數：`unknown` 不匹配 `unknown`，也不表示已確認缺少。輸出中的 `major_differences` 只列已確認不同，`unconfirmed_dimensions` 只列資料未知或無法確認的維度；同一維度不得同時出現在兩者。

## 保守品質門檻

價格區間只有在靜態規則全部成立時才會產生：

- hard pool 至少有 3 筆相容案例；
- 至少有 3 筆案例具有有效價格；
- 每筆保留案例至少達到 40/100 的最低相似度；
- 至少有 3 個有效內容維度支撐相似度。

少於三筆、低相似度、有效維度不足或證據不足時，回傳 `insufficient_comparables`，`range_twd` 維持空值，並列出每筆候選的排除原因與整體不足原因。這些是固定且保守的發布規則，不是回測、校準、漂移監控或自動調整機制。

若嚴格帳型不足三筆，只能明示擴張到相同帳型家族（例如永久無翼與未細分無翼）；不得跨到有翼、簡號或其他不相容帳型。幣別、伺服器及價格型態條件不可因案例不足而放寬。

## 價格與證據

刊登、急售、最後公開、已售聲稱和可驗證成交各自獨立，輸出的 `price_type` 正規化為 `normal_listing`、`urgent_sale`、`last_public_price`、`verified_sale` 或 `unknown`。已售聲稱不是成交；沒有符合契約的成交證據時不得輸出 `verified_sale`。未知資料不補值，綁定風險是獨立維度，不能取代帳號內容分類。

正式市場資料目前只有三筆同時確認幣別為 TWD 且伺服器為國際服，因此結果的適用範圍有限，不代表完整市場。

## 三態 Item Vector 與模型線

每個物品狀態只能是 `owned`、`confirmed_missing` 或 `unknown`。文案未提及不等於缺少；只有 canonical 且完成物品級證據審核的 item 才可進正式模型特徵。needs_review 與候選只保留於敏感度／人工審核層。

正常刊登與急售分開訓練。Elastic Net 最低樣本為 `max(100, 10 × 有效特徵群)`，XGBoost 為 `max(300, 20 × 有效特徵群)`。Elastic Net 以帳號／重貼 cluster 做分組巢狀交叉驗證；P1 的 XGBoost 固定超參數，只做不跨 cluster 的 grouped outer CV，不宣稱已做 inner tuning。兩者都必須優於 median baseline。兩模型均通過時依外層 MAE 反比加權；否則只用合格模型或完全停用。

TreeSHAP 與 Item Value Table 只描述條件歸因。單件物品至少需要 10 個獨立持有帳號、5 個具相同欄位且已核准證據的 confirmed-missing 帳號，以及至少兩個 refit fold 的方向一致性達 80%；不足時歸因為 null。單一已訓練模型內的 bootstrap 穩定度只作診斷，不冒充跨重訓穩定性。解釋資料還必須與模型雜湊、輸入快照與價格線完全一致。現有正式資料未達任何模型門檻，因此本版只發布可重現管線與資料不足 artifact。
