# 遊戲知識主檔

此目錄是季節、活動、物品、套組、別名、取得狀態、研究來源與視覺參考的唯一 canonical source of truth。衍生帳號 profile 與 comparables 不得重新定義這些資料。

所有外部事實必須透過 `sources/sources.jsonl` 的 `source_id` 追溯；資訊衝突或未能查證時使用 `needs_review`。

物品另以 `evidence_tier` 與 `model_feature_status` 明確區分研究種子和模型白名單。只有 `verification_status=verified` 且 evidence tier 為 `official_item_specific` 或 `official_with_secondary` 的物品可標記 `eligible`；候選、`needs_review` 與別名衝突資料一律隔離於 `data/review/`，不得進入正式 Item Vector。
