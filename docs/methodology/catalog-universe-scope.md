# Catalog-universe scope accounting

`data/review/catalog-universe.jsonl` is a closed, deterministic accounting
layer over the pinned vendor snapshot.  It retains `classification` only for
reconciliation continuity; that field is not a proof that a vendor row is out
of account-item scope.

Every row includes an explicit `scope_disposition`, `disposition_reason`, and
`evidence_basis`.  The current snapshot provides type labels, not a reviewed
scope decision.  Consequently `WingBuff` (progression unlock), `Spell`
(consumable effect), `Quest` (quest record), and `Special` rows remain
`needs_review`.  This is intentional: no type-only rule may silently mark a
row `not_required` or promote it into canonical knowledge.

The paired summary reports both raw vendor-type counts and scope-disposition
counts, including the number that still need scope review.  Rebuilding the
artifact verifies the pinned snapshot before producing deterministic UTF-8 LF
JSONL and summary bytes.
