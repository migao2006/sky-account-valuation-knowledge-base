# Offline modelling environment

This directory is an optional, isolated research environment.  It never contacts a
network and it never installs dependencies.  Operators may provision the versions
listed in `requirements-modeling.lock` in a separate environment before running it.

`train_elastic_net.py` accepts newline-delimited account item vectors.  A row must
have an account identifier and a `feature_vector`, `features`, or P1
`feature_groups` object. Prices may be embedded (`price_twd` or
`selected_price_twd`) or joined from the corresponding cleaned-price file by
`account_id`. Only catalog-approved `item_states` become individual item features.
It writes an auditable JSON artifact only.  The artifact contains no pickle, model
binary, source listing text, or personal data.  Its status is fail-closed when
dependencies or sufficient data are unavailable.

Elastic Net and XGBoost use the same vectors and cleaned price line. XGBoost's
native `pred_contribs`／`pred_interactions` interface provides TreeSHAP values;
no external SHAP service or network access is involved.

Repeated accounts are separated with grouped cross-validation. Structured
season, binding and set records are expanded by canonical identifiers rather
than serialized as whole-dict categories. Item identity enters either model
only through catalog-approved `item_states`. Explanation files are accepted by
the Item Value Table only when their model, artifact, input-snapshot and price-
line provenance match; within-model bootstrap stability is diagnostic and does
not replace across-refit direction evidence.

Example (offline):

```powershell
python modeling/train_elastic_net.py --input data/modeling/account-item-vectors.jsonl --prices data/modeling/price-cleaned-normal.jsonl --output-dir modeling/artifacts --price-line normal_listing
python modeling/train_xgboost.py --input data/modeling/account-item-vectors.jsonl --prices data/modeling/price-cleaned-normal.jsonl --output modeling/artifacts/xgboost-normal_listing.json --price-line normal_listing
python modeling/evaluate.py --artifact modeling/artifacts/elastic-net-normal_listing.json
```

Formal P2 data has 3 normal-listing rows, 0 urgent-sale rows, and 0
model-eligible canonical items. Both trainers therefore publish only
`insufficient_training_data`; the 94-row Item Value Table is entirely
`insufficient_support` and contains no numerical item attribution.
