# Model publication evaluator

P3.4's `1.2-p3.4` feature contract makes the evaluator own the evidence path: it rebuilds the frozen dataset
split, validates its row and dataset hashes, and does not consume a submitted
split to select train or holdout rows. A submitted split is only compared with
the replayed result; cluster overlap, date inversion, or any mismatch fails.

Production rows must have registered signed training-example lineage. Their
target price and event date are replayed against the registered authorized
observation; their public subgroup is deterministically derived from the
signed feature payload (`base_account.account_type`, or `unknown`). The public
production entry points reject test-only synthetic manifests. Synthetic
fixtures may exercise the scorer only through explicit `*_synthetic_for_test`
helpers, so recomputing enclosing JSON hashes after editing a target or
subgroup cannot be used as a production evaluation input.

For a pool with 300 earlier clusters and 100 later clusters, it deterministically
fits a fixed pure-standard-library linear model using only the frozen, signed
account feature payload, then scores untouched holdout rows. Dates select the
time-forward split and comparable baseline only; they are never model inputs.
It recomputes MdAPE, P90 APE, two
MAE comparisons, an empirical residual interval, and public subgroup results.
External artifact objects and prediction arrays are rejected, so a self-reported
score cannot advance state. The report also calls out every public holdout
subgroup below 30 cases.

The feature-linear evaluator is deliberately **not** a runtime artifact: even
when its gates pass, it returns `evaluation_required` with
`runtime_compatible_feature_artifact_required`. Runtime publication remains
reserved for separately replayed Elastic Net/XGBoost artifacts. P3.5 adds the
first such path only for `elastic_net` + `normal_listing`: the evaluator
reconstructs its portable JSON contract from exactly the frozen train clusters,
scores only the frozen holdout, and accepts a local artifact only if its parsed
bytes exactly equal that reconstruction. The evaluator, not the artifact,
creates the dataset/split/model/artifact hash binding. Test-only synthetic
fixtures cannot create a production binding. Urgent-sale and XGBoost remain
insufficient until they receive their own runtime contracts. A self-reported
artifact status or metric cannot advance the report. The current production
data has no qualifying pool and therefore stays `not_ready`.
