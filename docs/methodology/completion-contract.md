# 完整知識庫與精準估價完成契約

本文件定義本專案可以使用「完整知識庫」或「精準估價」描述前，必須由正式資料與離線驗證器證明的條件。Schema、測試與 manifest 通過只代表資料契約可重現，不等同於內容完整或估價準確。

## 支援範圍

完整性必須綁定研究截止日與明確母體，例如「截至 YYYY-MM-DD，國際服所有永久帳號物品」。新增季節、活動或物品後，舊版只能稱為對其研究截止日完整。

估價必須分市場線聲明支援範圍；目前預定的第一條正式市場線為：

`TWD + international + seller_listing + single_account + normal_listing`

其他幣別、伺服器、買方預算、服務、多帳、交換、急售與 verified sale 都是不同資料池，不能混合。

## Catalog 完成門檻

1. 建立封閉母體清單，逐類列出 season、event、ancestor、shop、platform、collaboration、gift、map completion、furniture 與明確排除項。
2. 母體中的每個預期項目必須恰有一個 canonical ID，或有可稽核的排除理由；不得靜默消失。
3. canonical identity unresolved 必須為 0；市場實際觀察到的 unmapped alias 必須為 0。歧義別名可保留 conflict，但必須 fail closed。
4. identity/name、category/source、free/premium/pass/ultimate、set membership、first release 與 availability-as-of 都必須有欄位級證據。
5. 每個 assertion 至少保存 entity、field path、value、source、locator、retrieved date、evidence level、review state 與 conflict state。
6. 可接受的最高證據為官方逐項來源；官方未提供逐項資料時，必須有兩個獨立且持續維護的 secondary，並明示較低證據等級。
7. `officially_discontinued` 只能由官方明示來源支持。
8. Coverage 必須以封閉母體為分母，逐季、逐活動、逐類滿足 `expected = canonical + explicitly excluded`。
9. 可視物品必須有 visual-reference 狀態；無權保存圖片時，保存來源描述與 unavailable 原因，不得冒充已有圖像資產。

## 文案解析與 Item Vector 門檻

1. 每個 vector 的 item-universe hash 必須等於同版 Catalog snapshot。
2. 未提及一律是 `unknown`；只有明確否定或完整衣櫃覆蓋證據才可成為 `confirmed_missing`。
3. 正式 parser gold set 至少 200 筆，且由兩名標註者按帳型、年代、季節、聯動與套組分層標註。
4. Held-out owned precision 至少 98%、owned recall 至少 95%、confirmed-missing precision 至少 99%。
5. canonical collision 與 unknown→missing 錯誤必須為 0；fixture 不計入正式準確率。

## 市場資料與成交證據門檻

1. normal listing、urgent sale、last public price、sold claim 與 verified sale 永不互相升級或混池。
2. 模型列必須有已驗證 currency、server、seller listing、single account、price 與 dedup cluster。
3. offer/entity/price type/currency/server 的正式雙標 gold set 至少 200 筆，各欄 held-out accuracy 至少 98%；verified-sale false positive 必須為 0。
4. verified sale 必須另有 approved、去識別、無衝突的 sale evidence，並同時證明完成狀態、成交價、日期、幣別與伺服器。`sold_claimed` 永遠不是 verified sale。
5. 若要支援成交價模型，每個市場池至少需要 300 個獨立訓練交易 cluster，另有 100 個從未參與選模的時間後切 holdout cluster。

## 精準估價門檻

樣本數門檻只允許訓練，不代表準確。每個公開支援市場池還必須通過：

- grouped、deduplicated、time-forward holdout；同帳號或重貼 cluster 不得跨 train/test；
- holdout MdAPE 不高於 20%；
- holdout P90 APE 不高於 40%；
- 相對 median baseline 的 MAE 改善至少 15%；
- 相對可比帳號 selector 的 MAE 改善至少 10%；
- 80% prediction interval 的實測 coverage 介於 75%–85%；
- interval median width 不超過 point estimate 的 50%；
- 每個公開 subgroup 至少 30 個 holdout cases 且 MdAPE 不高於 25%；
- 支援範圍內至少 80% 合格案例能輸出估價，其餘必須有 OOD／coverage 拒絕理由。

未達上述門檻時，輸出只能稱為「刊登價可比觀察」或 `insufficient_training_data`，不能稱為精準價格、成交價或單品價值。

## 圖片證據門檻

P0 至 P2.8 的 image evidence 只是資料契約，不是 OCR 或圖示辨識引擎。若未來宣稱自動辨識，必須使用真實、分層、held-out 標註集，並達到 micro precision 99%、micro recall 95%、supported-item macro recall 90%；未知圖示不得強制映射。

## 目前狀態

截至 P2.8，3,266 筆 vendor 宇宙已封閉對帳，其中 1,758 筆 collectible observation 具有唯一 source-scoped identity；另有 2,478 筆離線查詢索引。Nintendo 四件、AURORA FAQ 968 六件、Journey Pack 三件與 Moomintroll Accessory Set 兩件 canonical item 具有受限、可重播的 identity 證據鏈，但 1,388 筆 collectible observation 仍 unresolved、1,508 筆 scope disposition 仍待人工審查。市場人工 gold 與 near-miss approved evidence 都是 0，正式正常刊登仍只有 3 筆，Catalog、Item Vector、價格資料、verified sale 與 image evidence 都未達完成門檻。所有模型維持 fail closed 是正確行為，不是錯誤。

P2.8 也沒有固定 holdout bytes、不可交疊 cluster 與時間切分的可重算發布評估器；因此 runtime 與離線 evaluator 都拒絕未通過獨立發布證據的 `trained` artifact 對外估價。模型發布必須在後續版本先建立可重播 evaluator，不能由 artifact 自填指標解鎖。
