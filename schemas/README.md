# 資料契約

每個 JSONL 檔案的每一列必須各自符合相對應 schema。所有 schema 使用 JSON Schema Draft 2020-12，且額外欄位預設禁止，避免未記錄的推測進入正式資料。

- `knowledge/`：遊戲知識的 canonical records。
- `market/`：匿名市場資料、帳號 profile 及可比輸出。
- `evidence/`：圖片辨識或人工證據索引。

`knowledge/official-historical-cost-reference.schema.json` 定義由 verified
canonical item 與正式 canonical-evidence cohort registry 衍生的官方歷史取得
成本參考。它保留 evidence/source/as-of，對 bundle 不分攤單件金額，並固定
`model_feature=false` 與 `resale_value_effect=not_inferred`；不是轉售估價資料。

實際 JSONL 對應：`data/source/listings.jsonl` 使用 `market/source-listing.schema.json`，`data/normalized/listings.jsonl` 使用 `market/listing.schema.json`，`data/normalized/account-profiles.jsonl` 使用 `market/account-profile.schema.json`，而 `data/curated/histories.jsonl` 與衍生 `data/comparables/histories.jsonl` 使用 `market/history.schema.json`。`market/comparable.schema.json` 定義估價器輸出的單一 JSON 結果。
