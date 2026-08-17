# Parser gold 與 held-out 評估契約

`data/review/parser-gold/claims.jsonl` 是正式 parser accuracy 的唯一標籤
ledger。每列只可保存 `input_sha256`、預期 canonical item ID、polarity、split
與分層欄位；不得保存原文、帳號／貼文 ID、URL、圖片、聯絡方式或其他 PII。
原始 replay input 僅由離線評估工作注入，輸入雜湊以完整 `{profile,listing}`
canonical JSON 計算，並必須與 ledger 恰好一對一。

非空 ledger 的每列必須有 `annotator_a`、`annotator_b`、`adjudicator` 各一份
OpenSSH detached signature，三個不同 fingerprint 必須來自 release root 外的
`sky-parser-gold-authority-bundle-v1`。本契約與市場人審的 authority namespace、
目錄及 ID 完全隔離。簽章綁定完整 gold row，任何 label、split、hash 或 strata
變更都會使驗證失敗。

`tools/modeling/parser_gold_evaluator.py` 只以 catalog parser replay 外部輸入。非空
gold 必須有正式 `rule-development-manifest.json`：它精確承諾完整 gold ledger 的
digest、parser source SHA、runtime config SHA、全部且僅有 development input hashes、
必需 strata policy，並有自身 digest。每一份三角色 attestation payload 同時綁定該
manifest 與 gold row；因此移動一筆 gold、替換規則開發 hash、或更換 parser source/
config 都會使簽章失效。replay input 也必須由 release root 外注入並給定 SHA-256。
報告只輸出匿名 hash aggregate 與 metrics，不回寫 raw input。

P3.7 起，非空 formal gold 還必須回放外部 keyed custodian binding：同時注入 SHA-256
固定的 custodian authority bundle、已簽署 contract 與 replay-binding bundle。contract
只含 authority ID 與 fingerprint，不得自帶驗證 public key；authority bundle 會驗證角色
`keyed_custodian_contract` 並拒絕 revoked fingerprint。binding 必須由同一 authority
簽署、重建 200 筆 opaque commitment 的 Merkle root，並逐列精確綁定 gold 的
`input_sha256` 與 split。這些逐列資料只存在 release root 外，公開 queue manifest
始終只保留 aggregate commitment。

達成 completion contract 仍需要至少 200 個已簽章的分層 gold rows，development 和
held-out 各至少 100 筆；每筆必須覆蓋 account type、era、season、collaboration、set
context，且每個 strata 至少兩種值。held-out 必須達 owned/known-state precision >=
98%、recall >= 95%、canonical collision = 0、unknown→confirmed-missing = 0。空 ledger 的 deterministic report 是 `not_ready`，
不是聲稱沒有錯誤率的正式準確率。
# P3.8 keyed finalization boundary

Formal public rows use `keyed_commitment` only. They must not contain an
`input_sha256` or `split`: those fields are retained exclusively in the
external replay binding. A valid V2 binding is custodian-signed, covers all
200 opaque leaves exactly once, recomputes the fixed 100/100 split commitment,
and carries the digests of both independently signed decision ledgers plus the
disagreement-only adjudication ledger. The accompanying finalization receipt
binds those three ledgers and the public gold ledger. No receipt, arbitrary
split digest, duplicate leaf, 201st row, or post-hoc held-out assignment can
make the evaluator publication-ready.
