# 授權彙總市場資料 intake

此 intake 只接受已去識別的彙總觀測資料，並不授權帳號交易、公開貼文爬取或個人資料保存。正式 registry 預設為空；空 registry 可離線驗證通過，但不會授權任何模型列。

非空 dataset 必須在 `data/review/market-authorization/registry.jsonl` 登記，並具有獨立 `authorization_record_id`、manifest SHA-256 與外部 statement 的實際 bytes SHA-256。每一筆只能指向其 dataset 目錄內的 `manifest.json` 與 `observations.jsonl`。manifest 鎖定 observation 檔案 bytes，並以 `observation_id` 對應每列 canonical JSON digest 和 `dedup_cluster_id` digest。觀測採 exact allowlist：不透明 observation／cluster ID、已驗證日期、TWD、international、seller listing、single account 與價格線；不得含 history/listing/raw text、姓名、帳號／社群識別碼、聯絡方式、URL、付款或登入資訊，包含任意巢狀欄位。

資料集會失敗關閉，除非呼叫端同時注入四個 repository 外部值：authority bundle 路徑與 SHA-256，以及 authorization statement 路徑與 SHA-256。兩份檔案位於 release root 內、摘要不符、已撤銷 fingerprint、過期聲明或未綁定 manifest/observation bytes 都會拒絕資料。

authority bundle 的 `schema_version` 為 `authorized-market-authority-bundle-v1`，每個 authority 有 OpenSSH public key、與該 key 相符的 SHA256 fingerprint、可擔任的角色，以及撤銷 fingerprint 清單。statement 的 `schema_version` 為 `authorized-market-statement-v1`，並精確綁定 `dataset_id`、`manifest_sha256`、`observations_sha256` 和 `expires_at`。

每個 dataset 要有 `data_steward`、`privacy_reviewer`、`method_reviewer` 三個角色各一份 OpenSSH detached signature。三份簽章需使用不同 fingerprint，並覆蓋完整 registry row、manifest、外部 statement 及 attestation metadata。簽章僅能在 `data/review/market-authorization/signatures/`。

Consumer 可用 `make_authorization_evaluator(root, bundle, bundle_sha, statement, statement_sha)` 建立 callable。它只有在整個 intake 全數驗證通過、五個 authorization lineage 欄位精確對應，且價格、日期、幣別、伺服器、交易方向與實體種類逐欄等於已簽署 observation 時才回傳 `True`。

v1 signed observation 只綁價格，仍會回 `market_data_feature_lineage_evaluator_required`。v2 另外簽署 account feature／Item Vector、catalog provenance 與跨資料集唯一 dedup cluster；factory evaluator 驗證外部 trust material 後，才會把這些 opaque observation 直接投影至 production cleaner。正式 registry 目前為空，所以實際模型列仍為 0；任何缺少 v2 commitments 的資料都不會解鎖訓練或估價。

## Verified completed-sale intake (v3)

`authorized-market-manifest-v3` is the only intake version that can carry a
`verified_sale` line. It is a distinct completed transaction event, never a
listing re-label. Its signed observation must contain exactly these additional
facts: `completed_sale_verified: true`, `sale_verified: true`, a completed-sale
date equal to the verified event date, a SHA-256 `completion_evidence_digest`,
and at least two unique `evidence_*` IDs. Asking, reduced, and urgent rows are
rejected if they try to attach any of those fields.

The v3 training example repeats and signs the observation-row digest, sale
line, completion digest, and independent evidence IDs alongside the feature,
catalog, and cluster commitments. Those row fields alone are not sufficient:
production admission additionally requires both external trust paths below.

1. The market identity mapping verifier must bind the signed example to an
   independently reviewed account and deduplication cluster. Resolver and
   reviewer signatures, mapping bytes, statement bytes, and their SHA-256
   values are injected from outside the release root.
2. The verified-sale receipt archive must replay the exact observation,
   training-example digest, seller-cluster commitment, completed-sale date,
   price, currency, and server. It requires distinct authorized settlement and
   completion assertions, with revocation and expiry checks. Archive and
   authority-bundle bytes and SHA-256 values are likewise external inputs.

`make_authorization_evaluator(...)` joins those two verified disclosures to the
signed v3 dataset. Missing, partial, stale, mismatched, reused, or in-repository
trust material keeps the sale out of `bound_training_rows()` and the dedicated
verified-sale cleaner pool. A positive receipt is provenance evidence for a
completed transaction; it does not by itself publish a completed-sale price
model. The pool remains separate from normal asking and urgent listings, and
the committed repository currently contains no formal sale rows.
