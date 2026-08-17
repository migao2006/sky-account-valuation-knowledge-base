# Market human-gold evaluation gate

The market-field completion gate measures the two independent annotators against
the final adjudicated label on held-out claims. It covers `offer_kind`,
`entity_kind`, `price_type`, `currency`, and `server`; the lower of the two
annotator accuracies for every field must be at least 98%. Both annotators must
also have zero false positives for `verified_sale`. A claimed sale therefore
cannot become a verified sale through annotation or consensus.

The fixed anonymous queue supplies twenty opaque buckets of ten claims. The
evaluator deterministically assigns alternating review IDs in every bucket to
development and held-out sets, producing five rows in each partition. A formal
set needs all 200 queue rows, at least 100 rows in each partition, exact queue
linkage, and a valid external market-audit trust root.

The evaluator replays a v2 market-audit evidence chain: two separately signed
blinded annotation-plus-queue commitments, then an adjudicator signature that
links both verified commitments to the final adjudication. Three distinct
external authority keys are required and both submissions must precede the
adjudication receipt. Legacy completed-row (v1) signatures remain insufficient
and a non-empty ledger using only them stays `not_ready`.

Run it locally without writing data:

```powershell
python tools/modeling/market_gold_evaluator.py --root .
```
