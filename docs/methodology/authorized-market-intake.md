# 授權彙總市場資料 intake

此 intake 只接受已去識別的彙總觀測資料，並不授權帳號交易、公開貼文爬取或個人資料保存。正式 registry 預設為空；空 registry 可離線驗證通過，但不會授權任何模型列。

非空 dataset 必須在 `data/review/market-authorization/registry.jsonl` 登記，並具有獨立 `authorization_record_id`、manifest SHA-256 與外部 statement 的實際 bytes SHA-256。每一筆只能指向其 dataset 目錄內的 `manifest.json` 與 `observations.jsonl`。manifest 鎖定 observation 檔案 bytes，並以 `observation_id` 對應每列 canonical JSON digest 和 `dedup_cluster_id` digest。觀測採 exact allowlist：不透明 observation／cluster ID、已驗證日期、TWD、international、seller listing、single account 與價格線；不得含 history/listing/raw text、姓名、帳號／社群識別碼、聯絡方式、URL、付款或登入資訊，包含任意巢狀欄位。

資料集會失敗關閉，除非呼叫端同時注入四個 repository 外部值：authority bundle 路徑與 SHA-256，以及 authorization statement 路徑與 SHA-256。兩份檔案位於 release root 內、摘要不符、已撤銷 fingerprint、過期聲明或未綁定 manifest/observation bytes 都會拒絕資料。

authority bundle 的 `schema_version` 為 `authorized-market-authority-bundle-v1`，每個 authority 有 OpenSSH public key、與該 key 相符的 SHA256 fingerprint、可擔任的角色，以及撤銷 fingerprint 清單。statement 的 `schema_version` 為 `authorized-market-statement-v1`，並精確綁定 `dataset_id`、`manifest_sha256`、`observations_sha256` 和 `expires_at`。

每個 dataset 要有 `data_steward`、`privacy_reviewer`、`method_reviewer` 三個角色各一份 OpenSSH detached signature。三份簽章需使用不同 fingerprint，並覆蓋完整 registry row、manifest、外部 statement 及 attestation metadata。簽章僅能在 `data/review/market-authorization/signatures/`。

Consumer 可用 `make_authorization_evaluator(root, bundle, bundle_sha, statement, statement_sha)` 建立 callable。它只有在整個 intake 全數驗證通過、五個 authorization lineage 欄位精確對應，且價格、日期、幣別、伺服器、交易方向與實體種類逐欄等於已簽署 observation 時才回傳 `True`。

P3.1 的 signed observation 尚未綁定完整 account feature／Item Vector bytes，也不能證明同一 observation 沒被複製成多個 feature clusters。因此 production cleaner 會另回 `market_data_feature_lineage_evaluator_required`，正式 estimator 也不使用這個 price-only evaluator。只有後續契約把完整 feature/vector digest 與 signed dedup cluster 綁入外部授權證據後，才可讓這些列進入訓練或可比估價；目前 registry 即使非空也不會解鎖模型。
