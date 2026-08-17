# Frozen publication dataset and split

`tools/modeling/publication_dataset.py` creates two deterministic reports from the formal cleaned-price rows, account vectors, and the exact pinned catalog provenance. It does not train, score, publish, or approve a model.

Every retained row must be TWD / international, one of the two formal price lines, have a positive selected price, reference a current vector, and carry a strict ISO `post_date` with `date_verified: true`. The report stores the canonical row hash, a dataset hash over sorted rows, byte hashes of all direct input files, and the catalog provenance. Missing vectors, stale provenance, duplicates, mixed pools, invalid prices, or unverified dates raise an error; they are never silently dropped.

The split is per currency/server/price-line pool. It lists the exact training, holdout, and spanning cluster IDs. A cluster ending before the cut is training; a cluster beginning at or after it is holdout; any cluster spanning the cut is excluded. This makes cluster overlap impossible. A pool records capacity only when it has at least 300 training clusters and 100 holdout clusters.

Both reports deliberately have the constant status `not_ready`, including when the count threshold is met. They are frozen evidence inputs for a future, independent publication evaluation and cannot unlock runtime estimation.
