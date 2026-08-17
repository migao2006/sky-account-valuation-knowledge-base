# Deterministic model-publication readiness

`tools/modeling/publication_readiness.py` is an offline evidence audit, not a
model evaluator and not an unlock switch. It reads only the two formal cleaned
price-line files, account vectors, canonical catalog, and formal comparable
history. It never reads model artifacts or a model's self-reported
`publication_gate`.

Each `TWD:international:<price_line>` market pool is counted separately. A
pool needs 300 independent clusters for training and 100 later, independent
clusters for holdout. Dates use only a valid `post_date`: `observed_at` is a
repository collection timestamp, not evidence of the listing/transaction
event's order. A single cluster is never placed on both sides:
for every candidate cut, training clusters must end before the cut and holdout
clusters must start on/after it. Clusters spanning a cut are excluded.

The report gives independent/dated cluster counts, distinct verified dates,
the deterministic split capacity, explicit 300/100 gaps, canonical
model-eligible-item count, verified-completed-sale count, and machine-readable
blocking reasons. Its `status` is intentionally always `not_ready`; passing
sample capacity alone does not evaluate metrics, provenance, calibration, or a
trained model.

Run it without mutating the repository:

```powershell
python tools/modeling/publication_readiness.py
```

To save a review artifact, pass an explicit output path:

```powershell
python tools/modeling/publication_readiness.py --output reports/model-publication-readiness.json
```
