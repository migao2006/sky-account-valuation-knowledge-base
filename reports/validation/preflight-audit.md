# P0 建置前稽核

- 原始 ZIP：`sky-valuation-v2.4-1022-complete-2026-08-16.zip`
- 大小：991,185 bytes
- SHA-256：`6AEEBE997E31B65EF4A7FC70E4905CF4AFAFED01FCA986DD55AB22F63EB98DA3`
- ZIP 檔案數：237（101 JSONL、63 PowerShell、47 Markdown、26 JSON）
- 建議處理：migrate 75、remove 31、replace 131、直接 keep 0；合計 237。

## 資料事實

- 71 個 batch 共 1,022 筆非空列，JSON 解析錯誤 0。
- batch 26、27 不存在；batch 25、28 為空檔，均不視為遷移失敗。
- v2.4 可比 102 筆，其中季節標籤非空 54、季節連續性 unknown 80、需人工分類 35。
- normalized 中 28 筆 `date_verified=true` 且均有日期。
- 102 筆可比中 5 筆日期旗標已驗證，但舊分類輸出遺失日期值；P0 必須由 curated history 回接 normalized 修復。
- 可驗證成交金額仍為 0。

## 安全邊界

舊 normalized 含來源社團欄位與自由文字，不能直接視為 P0 匿名資料。P0 source snapshot 必須移除社團名稱、社團 ID、作者、URL、聯絡資料及來源 locator。舊 Provider 腳本可執行任意外部程式，因此不得進入新工具目錄。

