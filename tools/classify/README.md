# 分類資料入口

P0 帳號 profile 由 `tools/migrate/migrate_v24_to_p0.py` 產生。正式多維分類器應只讀取 `data/normalized/account-profiles.jsonl` 和 canonical knowledge 主檔，不得讀取網路或舊版資料。
