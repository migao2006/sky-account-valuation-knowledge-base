# Model publication evaluator

P3.2 adds a deterministic evaluator boundary that rebuilds the frozen dataset
and time-forward split without consulting model artifact claims. It can report
that a market pool is ready for evaluation, but it cannot publish a model yet.

`publication_ready` remains `false` until a later evaluator deterministically
fits on the frozen training clusters only and recomputes every holdout,
baseline, prediction-interval, subgroup and out-of-distribution threshold in
the completion contract. A self-reported artifact status or metric cannot
advance this report.
