# P0 移除功能

v3.0 P0 是靜態、完全離線的知識庫。原始 ZIP 保留為外部唯讀備份；下列功能及檔案不會複製到新版本。

## 移除原則

- 回測、預測結果、校準與市場漂移。
- 成交 follow-up、due jobs、排程、cycle 與自動查詢。
- Provider 執行介面、Mock Provider、HTTP/API client、爬蟲與背景服務。
- v2、v2.1、v2.2、v2.3、v2.4 的重複正式資料、舊 release 報告及相容包裝。

## 原 ZIP 中直接命中的 31 個檔案

```text
data/templates/v2.2-backtest-template.jsonl
data/templates/v2.3-followup-import-template.json
data/templates/v2.4-followup-cases-template.json
data/tests/mock-v2.4-followup-provider-path.ps1
data/tests/mock-v2.4-followup-provider-pii.ps1
data/tests/mock-v2.4-followup-provider.ps1
data/tests/v2.2-mock-ocr-provider.ps1
data/tests/v2.3-mock-ocr-provider.ps1
data/tests/v2.4-mock-multi-image-provider.ps1
data/v2.3/backtest.json
data/v2.3/calibration.json
data/v2.3/drift.json
data/v2.3/followup-ledger.jsonl
data/v2.3/prediction-outcomes.jsonl
data/v2.4/account-lifecycles.jsonl
data/v2.4/followup-schedule.jsonl
scripts/backtest-v2.2.ps1
scripts/backtest-v2.3.ps1
scripts/build-v2.4-followup-schedule.ps1
scripts/calibrate-v2.3.ps1
scripts/complete-v2.4-followup.ps1
scripts/drift-v2.3.ps1
scripts/execute-v2.4-followup-query.ps1
scripts/import-v2.3-followups.ps1
scripts/run-v2.4-followup-cycle.ps1
scripts/run-v2.4-followup-due.ps1
scripts/transition-v2.3-followup.ps1
test-v2.3/fixtures/backtest-fixtures.jsonl
test-v2.3/fixtures/integration-followups.json
v2.2-sales-ocr-backtest.md
v2.4-sales-followup-schema.md
```

其餘舊檔即使只是在文件或測試中提及上述能力，也不會直接複製；所需的市場事實由新 migration 工具轉換成單一 P0 schema。

