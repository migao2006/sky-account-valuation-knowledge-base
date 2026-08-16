# 離線估價與圖片證據指南（v4.0 P2.8）

## 估價輸入

正式多維估價使用 `data/comparables/accounts.jsonl`。這個檔案由 account profile 與 history 離線合併，具有季節、收藏、物品／套組、地圖、資源、綁定、任次與交易條件等維度。`data/comparables/histories.jsonl` 是純價格歷程，**不是完整估價輸入**；不能拿它代替 account comparable 檔案。

使用者本次估價輸入與市場正式 profile 分開建模，前者遵循 `schemas/input/valuation-account.schema.json`，可以沒有市場 listing ID，但仍保留估價所需的多維欄位。分類器只接受受控的結構化聲稱，不宣稱能直接理解圖片或任意原始貼文。

## 估價流程與門檻

工具先將目標與每筆 nested comparable 轉成一致的內部表示，再以幣別、伺服器、價格型態與相容帳型建立 hard pool，接著比較季節、物品／套組、地圖、收藏、資源、綁定、任次、日期及證據品質。collection 會聯集 graduation rewards、collaboration items、bundles 與 event-limited items。

只有同時符合以下固定門檻，才會輸出價格區間：至少三筆 hard-pool 相容案例、至少三筆有效價格、最低相似度 40/100，以及至少三個有效內容維度。少於三筆、低相似度、有效維度不足或證據不足時回傳 `insufficient_comparables`，不輸出價格區間；結果會列出每筆被排除的原因與整體不足原因。

輸出的 `price_type` 使用 `normal_listing`、`urgent_sale`、`last_public_price`、`verified_sale` 或 `unknown`。價格欄位仍是市場觀察，不代表成交；`verified_sale` 僅能使用符合資料契約的可驗證成交資料，已售聲稱不得升級為 verified sale。`unknown` 不會被當成相同，也不會被當成已確認缺少；已確認不同與資料未知會分別列在 `major_differences` 和 `unconfirmed_dimensions`。

正式市場資料目前只有三筆正常刊登同時確認 TWD 與國際服；唯一急售觀察含仲，保留為 `needs_review`，不能代表可訓練的帳號單價。因此估價適用範圍有限，不能代表完整市場。

## 圖片證據

圖片功能目前只是 evidence contract，不是 OCR 或物品圖示辨識引擎。一張圖片以 SHA-256 識別，可標示其角色、語言、拍攝日和衣櫃拍攝完整度。文字 OCR 與物品圖示辨識是不同的證據欄位；OCR 文本不保存到正式知識庫。圖示辨識若日後完成，必須寫入 canonical `item_*` ID、標準化 bounding box、信心與審核狀態。

相同圖片、同頁重複與圖像重疊以 `image_sha256`、`page_group_id`、`duplicate_of_image_sha256`、`overlaps_detection_ids` 記錄。P2.8 仍只有來源文字描述，沒有 Moomintroll／Journey 圖片資產、OCR 或圖示辨識結果，也沒有足夠真實標註資料可宣稱辨識準確率。文案 Item Vector 是離線字典解析，不是 OCR 或圖片模型。

## 網路與研究邊界

儲存庫工具永遠不主動連線，沒有 HTTP/API client、Provider、爬蟲、排程器、背景服務或自動資料更新。外部執行者可以在儲存庫外上網研究；若查證結果涉及正式資料，必須先進入 review，不得直接升級 canonical。
