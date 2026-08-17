# Model publication evaluator

P3.3 makes the evaluator own the evidence path: it rebuilds the frozen dataset
split, validates its row and dataset hashes, and does not consume a submitted
split to select train or holdout rows. A submitted split is only compared with
the replayed result; cluster overlap, date inversion, or any mismatch fails.

For a pool with 300 earlier clusters and 100 later clusters, it deterministically
fits a fixed pure-standard-library linear trend using only verified training
dates, then scores untouched holdout rows. It recomputes MdAPE, P90 APE, two
MAE comparisons, an empirical residual interval, and public subgroup results.
External artifact objects and prediction arrays are rejected, so a self-reported
score cannot advance state. The report also calls out every public holdout
subgroup below 30 cases.

The evaluator may set `publication_ready=true` only when every implemented
gate passes: MdAPE/P90 APE, both MAE improvements, interval coverage and width,
subgroup size, and qualified coverage. A passed report emits an
`artifact_bindings` entry with `price_line`, `model_type`, recomputed
dataset/manifest/split SHA-256 values, plus evaluator-owned `model_sha256` and
`artifact_sha256`. A self-reported artifact status or metric cannot advance the
report. The current production data has no qualifying pool and therefore stays
`not_ready`.
