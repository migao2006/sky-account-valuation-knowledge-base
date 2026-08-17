# 市場資料授權與產品邊界

本專案不得以公開抓取第三方 Sky 帳號交易貼文來擴充訓練集。thatgamecompany 的現行服務條款明示帳號不得出售、交換、贈與或轉讓，官方說明也把外部販售帳號或未授權遊戲內容列為可能停權的行為：

- <https://thatgamecompany.helpshift.com/hc/en/17-sky-children-of-the-light/faq/460-eula-terms-of-service/>
- <https://thatgamecompany.helpshift.com/hc/en/17-sky-children-of-the-light/faq/469-what-is-unauthorized-selling-and-game-economy-abuse/>

因此，repository 內既有匿名市場資料只能作歷史研究與 fail-closed 規則測試；它不是交易邀請、價格保證或對帳號買賣的背書。不得從外部 marketplace 新增帳號、使用者名稱、聯絡方式、貼文 URL、圖片或其他可識別資訊，也不得以缺少日期、伺服器、去重或授權的公開刊登資料訓練／發布模型。

新的市場資料只有在下列條件全部成立時才可進入正式 intake：

1. 資料提供者對資料具有明確授權，且允許本專案所需的離線驗證、衍生與發布用途。
2. 原始資料在進入 repository 前已去識別；正式資料不得含帳號名稱、社群識別碼、聯絡資訊或可回推個人的 URL。
3. 每筆紀錄有可重播的來源 snapshot hash、觀測日期、幣別、伺服器、交易型態、單／多帳、價格語義與 dedup cluster。
4. 人工標註與裁決必須通過外部信任根驗證的 detached signatures；自填 `human_*` 字串不是審核證據。
5. 帳號刊登、急售、已售聲稱與 verified sale 永遠分池；沒有獨立完成／成交證據時不得升級為 verified sale。

在取得合法、去識別且可重播的授權資料前，account resale estimator 必須回傳資料不足，不得輸出價格區間。官方物品售價與活動成本可另作「歷史取得成本參考」，但不得被解讀為帳號轉售價、單品二手價或投資價值。
