# P0 架構

## 設計原則

P0 將「遊戲事實」與「匿名市場觀察」分離。季節、活動、物品、套組、別名、取得狀態和來源只存在於 `knowledge/`；市場資料不自行重複定義它們。帳號分類與可比輸出均引用 canonical ID。

```
已匿名 v2.4 匯入
  → source/listings
  → normalized/listings
  → normalized/account-profiles + curated/histories
  → comparables/histories + comparables/accounts
  → reports

knowledge/* ──────┘
```

`source`、`normalized`、`curated` 與 `knowledge` 是可追溯輸入；`comparables/histories.jsonl`、`comparables/accounts.jsonl` 和 `reports` 是可重建衍生輸出。`accounts.jsonl` 只是 profile 與 history 的估價用 join，不是第二套主檔。`account-profiles.jsonl` 位於 `normalized/`，避免在 curated 重複保存一份 profile。資料不因舊版版本號分裂為多套正式主檔。

## 邊界

- `schemas/` 定義每列 JSONL 的資料契約與 enum。
- `tools/` 只可在本機讀寫資料，禁止網路和背景工作。
- `tests/fixtures/` 永遠不會加入正式統計。
- `reports/` 只呈現實際產出，不能成為資料真相來源。

## 證據與隱私

來源網址只能存在於遊戲知識的 source records。市場記錄僅用匿名 ID 與必要的證據狀態。圖片 evidence 保存雜湊與結構化識別結果，不保存原始 OCR 全文或個人資訊。

## 日期資料流

`post_date` 是貼文日期，`observed_at` 是資料觀察日期，兩者不可互填。任何 `date_verified=true` 且缺少合法 `post_date` 的資料均為錯誤，驗證器必須拒絕。
