# Parser knowledge coverage audit

`tools/modeling/parser_knowledge_coverage.py` creates the deterministic
`reports/parser-knowledge-coverage.json` report.  It is an audit of catalog
and parser evidence, not an estimator input or a publication gate.

For every canonical item it records canonical verification/model status,
verified item-alias token availability, unverified alias gap, account-vector
owned/missing/unknown observations, review-only lexical polarity totals, and
the official historical-cost reference kind.  Counts are derived from the
current formal files rather than being release constants.

The audit fails if aliases, vector item states, sidecar item matches, or cost
references identify an item outside the canonical catalog.  The account
catalog sidecar must remain `review_only: true` and `model_feature: false` at
both row and match levels; ownership/model promotion fields are rejected.
Its positive/negative/conflict labels are lexical review evidence only and
never alter owned, missing, verification, or model eligibility counts.

Official cost references remain non-model and `not_inferred` for resale
value.  A verified canonical item therefore does not imply a verified parser
token, ownership observation, or estimable market contribution.

Run:

```powershell
python tools/modeling/parser_knowledge_coverage.py --root . --output reports/parser-knowledge-coverage.json
```
