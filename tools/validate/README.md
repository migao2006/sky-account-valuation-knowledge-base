# 離線驗證

```powershell
python tools/validate/validate.py --root . --output reports/validation/p0-validation.json
```

驗證器檢查 JSONL 可讀性、canonical ID、物品與套組參照、已驗證日期、正式市場資料隱私欄位、圖片 evidence 契約，以及正式工具樹是否混入已移除的執行能力。它不會連線或修改資料。
