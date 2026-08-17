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

`review_status` has two explicit states: `needs_review` and `approved`.
An approval requires a separate scope-decision row that cites a different,
`data/source/research/` snapshot and locator. Crosswalk matching and vendor
type are never scope approval. This makes all dispositions—including
progression, consumable, quest, and Special—capable of a future reviewed final
decision, while the present artifact remains deliberately `needs_review`.

The paired summary reports both raw vendor-type counts and scope-disposition
counts, including every row whose `review_status` still needs scope review.
Rebuilding the artifact verifies the pinned snapshot and the formal scope
decision ledger before producing deterministic UTF-8 LF JSONL and summary
bytes.
