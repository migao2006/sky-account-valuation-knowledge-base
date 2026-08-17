# Parser human-gold 外部 onboarding

這個流程只建立 200 筆固定、匿名的 review queue（100 development、100 held-out），不能建立 formal gold。repo manifest 僅含 input SHA-256、匿名 queue ID、split 與五個允許的 strata；原文、帳號／listing ID、URL 和 reviewer 決策只能位於 release root 外的受限封包。

以受控環境中的 source JSONL（每列只有 `profile`、`listing`、`strata`）建立封包：

```powershell
python tools/parser_review/onboarding.py build-queue --source D:\restricted\parser-inputs.jsonl --source-sha256 <SHA256> --manifest-out data\review\parser-gold\review-queue-manifest.json --packet-dir D:\restricted\packets
```

輸入 SHA 不符、少於 200 個 unique input、任一 split 缺少任一 strata 的兩種值，或封包輸出於 release root 內時，流程會拒絕。digest 排序使選取可重現，並把 development subset digest 寫入 freeze commitment。held-out packet 必須與 development packet 分開交付；在 rule-development manifest freeze 前不得開放 held-out labels。

兩位 annotator 必須獨立提交完整 queue 的 decision commitments。每筆 commitment 綁定匿名 queue ID、input SHA、canonical item IDs 與 polarity；每份 JSONL ledger 另需有外部 OpenSSH signed sidecar，綁定 ledger digest、reviewer role 與 signer fingerprint，且 A/B 不可共用 fingerprint。A/B 完全相同者可成為候選；只允許對分歧 queue ID 建立 adjudication，且必須連回兩份 immutable commitment。這仍只是候選，不能直接寫入 `claims.jsonl`。正式 gold 仍必須滿足 [parser gold contract](parser-gold-contract.md) 的 external authority、三角色簽章和 rule-development manifest 驗證。

## P3.5 外部人工審核封包

目前不得發出 A/B 盲化封包。公開 manifest 含 unsalted `input_sha256` 與 split，reviewer 能由 profile/listing 重算 hash 並連回 held-out mapping；`build-blind-packages` 與 preflight 因此 fail-closed。必須先完成 release root 外的 keyed commitment 與 split mapping 協定，才能安全恢復發放。

```powershell
python tools/parser_review/onboarding.py build-blind-packages --manifest data\review\parser-gold\review-queue-manifest.json --packet-dir D:\restricted\packets --output-dir D:\restricted\issued --blind-secret <external-secret>
python tools/parser_review/onboarding.py preflight --manifest data\review\parser-gold\review-queue-manifest.json --packet-dir D:\restricted\packets --output D:\restricted\parser-review-preflight.json
```

annotator 從盲化 assignment 與決策建立 canonical signing payload。受控 consumer 以 manifest 的 input hash 解析 queue ID，因此輸出即為 verifier-compatible decision-ledger row；把這些 row 組成 JSONL 後，仍須以 annotator 自己的 OpenSSH key 簽署 `decision_ledger_sha256` 與精確 `queue_manifest_sha256` 的 P3.5 sidecar。這會阻止跨 split／freeze manifest 重用 receipt。payload 及簽章仍在 repo 外。

```powershell
python tools/parser_review/onboarding.py decision-receipt-payload --assignment D:\restricted\assignment.json --assignment-ledger D:\restricted\issued\blind-assignment-ledger.json --decision D:\restricted\decision.json --manifest data\review\parser-gold\review-queue-manifest.json --output D:\restricted\receipt-payload.json
python tools/parser_review/onboarding.py build-conflict-packet --manifest data\review\parser-gold\review-queue-manifest.json --decisions-a D:\restricted\annotator_a.jsonl --decisions-b D:\restricted\annotator_b.jsonl --output D:\restricted\conflicts.json
python tools/parser_review/onboarding.py import-candidate-ledger --manifest data\review\parser-gold\review-queue-manifest.json --decisions-a D:\restricted\annotator_a.jsonl --decisions-b D:\restricted\annotator_b.jsonl --adjudications D:\restricted\adjudications.jsonl --output D:\restricted\candidate-ledger.json
```

第二個命令只產生 A/B 分歧的最小 adjudication packet，連結兩個 commitment digest、不含 replay input，且不建立 formal gold。每一筆 adjudication 必須有 final canonical IDs 與 polarity、其 canonical receipt digest，並由第三把不同於 A/B 的 OpenSSH key 對整份 adjudication ledger 簽署；任意 64-hex 字串不是 adjudication。raw source、profile/listing、private key、blind secret、receipt 及 reviewer signature 都必須在 release root 外；工具不會寫入 `claims.jsonl`、解除 runtime gate 或假造 gold。

`import-candidate-ledger` 僅在 A/B ledger 的 external signatures 與 conflict-only adjudication 都通過後，輸出 hash、canonical IDs、polarity 的 candidate ledger；所有 P3.5 handoff 輸出均強制在 release root 外，且拒絕 `claims.jsonl` 等 formal/reserved 檔名。分歧不會被升格為候選，也不會變更任何 formal claim。
