# Frozen publication dataset and split

`tools/modeling/publication_dataset.py` creates two deterministic reports from the formal cleaned-price rows, account vectors, and the exact pinned catalog provenance. It does not train, score, publish, or approve a model.

Every retained row must be TWD / international, one of the two formal price lines, have a positive selected price, reference a current vector, and carry a strict ISO `post_date` with `date_verified: true`. Production retention additionally requires one complete `authorized-market-manifest-v2` training-example commitment: `training_example_id` and digest, feature payload hash, catalog provenance hash, and dedup-cluster hash. The commitment must be registered, match the account and cluster exactly, and match the current account vector and pinned catalog byte-for-byte.

Unsigned or partially signed cleaned rows are excluded, never counted toward the 300/100 capacity, and are reported through `rejected_clean_row_count`, `rejection_counts`, and the `unsigned_clean_rows_excluded` blocker. A complete but mismatched/tampered commitment is an error. The only unsigned fixture path is `freeze_synthetic_for_test`; production `freeze` and `build` have no caller-supplied bypass flag.

The split is per currency/server/price-line pool. It lists the exact training, holdout, and spanning cluster IDs. A cluster ending before the cut is training; a cluster beginning at or after it is holdout; any cluster spanning the cut is excluded. This makes cluster overlap impossible. A pool records capacity only when it has at least 300 training clusters and 100 holdout clusters.

The split may reach `ready_for_evaluation` only after an eligible signed pool satisfies the threshold. It remains frozen evidence for the independent publication evaluator and cannot by itself unlock runtime estimation.
