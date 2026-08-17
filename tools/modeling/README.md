# Modeling inputs

`parse_item_vectors.py` builds deterministic, offline three-state item vectors
from normalized listings and account profiles. It only matches the local
canonical-name/alias dictionary; it is neither OCR nor a general text model.
An absent mention remains `unknown`, never `confirmed_missing`.

`publication_readiness.py` separately audits the formal clean-price pools for
the required grouped time-forward sample capacity. It is evidence accounting,
not a model publication gate; see
`docs/methodology/model-publication-readiness.md`.
