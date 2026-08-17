# 官方歷史取得成本參考

`data/derived/official-historical-cost-references.jsonl` 是可重播的官方歷史
取得成本參考，不是轉售估價、物品 resale value 或模型特徵。它只讀取已驗證
canonical item，以及 `data/review/canonical-evidence-cohorts.jsonl` 中目前
active 且通過 verifier 的 cohort ledger；任何 registry 驗證失敗都會停止產生。

每筆資料都有 `evidence_ids`、`source_ids` 和 `as_of_date`。`as_of_date` 是
所使用 ledger 的最新 `reviewed_at`，不是現時商店供應、也不是市場成交日。

- `exact_historical_item_price`：ledger 有逐項 numeric `original_cost`，而已驗證
  canonical item 也有幣別。
- `in_game_currency`：同樣是逐項成本，但幣別是遊戲內貨幣，例如 candle 或
  event_currency。
- `bundle_only`：歷史金額只屬 set。`item_amount` 和 `item_currency` 必為 `null`，
  不允許依成員數、稀有度或任何比例拆分價格。
- `unknown`：沒有可用的逐項成本，或沒有唯一、已核准且可連結的套組歷史價格；
  所有金額欄位維持 `null`。

所有列固定 `model_feature=false` 與 `resale_value_effect=not_inferred`。Estimator、
Item Value Table、Hedonic／Elastic Net 和任何帳號轉售區間都不得讀取此檔案。
它的用途僅是讓知識庫能誠實呈現「官方曾如何取得」的可追溯參考。
