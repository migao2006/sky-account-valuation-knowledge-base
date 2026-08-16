# 資料層

`source` 是匿名、靜態來源快照；`normalized` 是唯一標準化資料，其中 `source-scoped-item-identities.jsonl` 保存固定 vendor snapshot 的 1,758 筆來源範圍身分，不等同 canonical item；`curated` 是人工決策後的歷程；`comparables` 是可由 curated 資料重建的估價輸入；`review` 保存未確認映射與匿名 near-miss evidence queue。所有資料均可離線讀取。
