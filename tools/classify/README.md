# 分類資料入口

`classify.py` 只接受含有 `structured_claims` 物件的離線結構化聲稱，並輸出符合
`schemas/input/valuation-account.schema.json` 的本次估價輸入。它不是市場正式
account profile：使用者估價輸入可沒有 `source_listing_ids`，不得為了 schema 虛構刊登 ID。
估價範圍由 `structured_claims.market_context` 的 `currency`、`server`、
`valuation_date` 受控提供；缺少時分別輸出 `unknown`、`unknown`、`null`，而不是猜測市場。
`trade_conditions` 同樣會重建成受限的 `offer_kind`、`entity_kind`、`price_type`；已售聲稱
只能成為 `last_public_price`，不會升級成 `verified_sale`。

分類器會以 canonical 主檔核對所有 `item_*`、`season_*` 與 `set_*` ID；未知 ID 會明確
拒絕，供外部流程送 review，而不會只因前綴正確就接受。缺少資訊保留為 `unknown`，不會
被視為確認沒有或確認相同。

工具不讀取網路、原始貼文或圖片，也不保存原文。圖片欄位只是 evidence 契約，並非 OCR
或圖示辨識引擎。市場資料仍由遷移工具產生於
`data/normalized/account-profiles.jsonl`，並遵守市場專用
`schemas/market/account-profile.schema.json`。

```powershell
python tools/classify/classify.py input-claims.json --output valuation-account.json
```

`resolve_catalog_claims.py` is a separate offline Unified Catalog Query/Resolution
layer. It accepts only IDs in the derived catalog query index and retains no raw
name or post text. Results preserve canonical, review-candidate and source
observation truth levels. Only a unique verified canonical exact mapping can
resolve ownership; the current 94 canonical items are all `needs_review`, so
all current results remain review-only and are excluded from model features.
Unknown is not missing; contradictory owned/missing claims fail closed.

```powershell
python tools/classify/resolve_catalog_claims.py catalog-claims.json --output catalog-resolution.json
```
