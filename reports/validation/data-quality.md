# P0 資料品質與限制

## 已確認

- 季節 30、活動 24、物品 127、套組 10、別名 320、來源 38。
- 1,022 筆來源與正規化資料、102 筆 legacy 歷程均已遷移，另有 1 筆明示覆核恢復歷程；`date_verified=true` 必須同時存在有效貼文日期。
- 季節／活動／物品／套組／來源／別名使用唯一 canonical ID，跨檔參照由離線驗證器檢查。
- 大耳狗／耳狗映射至同一套組；歸巢與築巢是不同季節；極光／歐若拉、梵谷／梵高各自映射到單一季節 ID。
- 估價相似度總分 100，季節 22、物品與套組 20，另含帳型、地圖、收藏、資源、綁定、任次、日期與證據品質；沒有單品固定加價。

## 資料推論

舊市場文字只能保守抽取季節、物品與風險聲稱。沒有圖片支持的欄位維持文字聲稱或 unknown；沒有提供資料不等於確認缺少。刊登價、急售價、最後公開價與驗證成交價分池處理。

## 尚未確認

- canonical needs_review 分布為 {"seasons": 27, "events": 13, "items": 79, "sets": 4, "aliases": 306, "availability_events": 13}；另有類別缺口 queue 39 筆、隔離物品候選 622 筆、unmapped alias 14 筆、alias conflict 1 筆。這些集合可能重疊，不直接相加成唯一項目數。
- 全物品 catalog 未完成。現有 127 筆是可追溯種子與節點目錄，不代表遊戲全部物品。
- 已將 3,266 筆固定 vendor snapshot 全量分類；其中 284 筆候選只有單一 vendor correlation，canonical identity 仍 unresolved，沒有寫入 canonical 或模型特徵。
- 物品 evidence tier：{"official_with_secondary": 48, "unverified_seed": 79}；模型白名單物品 19 筆。needs_review、候選與衝突別名均不得進入正式 Item Vector。
- visual reference 10、真實 image evidence 0、可驗證成交 0；因此不宣稱圖示辨識準確率或成交價模型。
- 季節節點的繁中正式名、免費／季卡屬性、成本與取得狀態仍有 needs_review 記錄。
