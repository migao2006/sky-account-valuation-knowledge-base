# Parser human-gold 外部 onboarding

這個流程只建立 200 筆固定、匿名的 review queue（100 development、100 held-out），不能建立 formal gold。repo manifest 僅含 input SHA-256、匿名 queue ID、split 與五個允許的 strata；原文、帳號／listing ID、URL 和 reviewer 決策只能位於 release root 外的受限封包。

以受控環境中的 source JSONL（每列只有 `profile`、`listing`、`strata`）建立封包：

```powershell
python tools/parser_review/onboarding.py build-queue --source D:\restricted\parser-inputs.jsonl --source-sha256 <SHA256> --manifest-out data\review\parser-gold\review-queue-manifest.json --packet-dir D:\restricted\packets
```

輸入 SHA 不符、少於 200 個 unique input、任一 split 缺少任一 strata 的兩種值，或封包輸出於 release root 內時，流程會拒絕。digest 排序使選取可重現，並把 development subset digest 寫入 freeze commitment。held-out packet 必須與 development packet 分開交付；在 rule-development manifest freeze 前不得開放 held-out labels。

兩位 annotator 必須獨立提交完整 queue 的 decision commitments。每筆 commitment 綁定匿名 queue ID、input SHA、canonical item IDs 與 polarity；每份 JSONL ledger 另需有外部 OpenSSH signed sidecar，綁定 ledger digest、reviewer role 與 signer fingerprint，且 A/B 不可共用 fingerprint。A/B 完全相同者可成為候選；只允許對分歧 queue ID 建立 adjudication，且必須連回兩份 immutable commitment。這仍只是候選，不能直接寫入 `claims.jsonl`。正式 gold 仍必須滿足 [parser gold contract](parser-gold-contract.md) 的 external authority、三角色簽章和 rule-development manifest 驗證。
