# Offline normalization tools

`import_skygame_catalog_snapshot.py` accepts only a previously downloaded, pinned
`skygame-data@1.3.4` tarball. It never opens a network connection and emits a
field-limited source snapshot plus SHA-256-bound provenance metadata.
It checks that `assets/items.json` and the `items.items` component in the
package's composite `assets/everything.json` are identical before importing.

`compare_vendor_catalog.py` verifies the source package and snapshot hashes,
then performs exact normalized-name crosswalks against canonical items and
English aliases, followed by review-candidate English names. It writes
crosswalk and candidate field-evidence records only. Canonical matches always
take precedence; a candidate match is secondary identity/name/type evidence,
not a canonical promotion, alias addition, item verification, or model-feature
approval.

```powershell
python tools/normalize/compare_vendor_catalog.py --root .
```

The tool writes its output to `data/review/`; reviewers must independently
confirm each candidate before any canonical knowledge change.

`promote_items.py` is the second, still offline, gate. It rejects fixture
locators, unknown source IDs, source-tier mismatches and changed source bytes.
P2.1 does not have a source-specific official claim extractor, so strict
`approved_for_reviewed_migration` output is deliberately disabled rather than
trusting caller-authored metadata. Its default is a dry-run and it never edits
canonical items:

```powershell
python tools/normalize/promote_items.py --root .
```

Use `--output data/review/item-promotion-ledger.jsonl` only to write a
review artifact.  Even an approved ledger row has `canonical_write` set to
`not_performed`; a separately reviewed migration is required for any canonical
change.

`build_market_claim_review.py` creates the fixed, anonymized P2.2 200-record queue for
two independent human annotations of market fields. It writes only listing IDs,
listing-text SHA-256 values, opaque buckets, and requested field names—never source
text or machine-proposed labels. It does not modify formal market data:

```powershell
python tools/normalize/build_market_claim_review.py --root .
```

The corresponding `market-claim-gold.jsonl` is intentionally empty until two
humans annotate and a human adjudicator resolves each row under
`docs/methodology/market-claim-gold-contract.md`.

`build_market_near_miss_review.py` creates a separate P2.3 queue for a narrow
review of one missing hard-evidence domain. It starts only from seller,
single-account, positive-price, verified-TWD listings, excludes mixed brokerage
prices such as `listing_0260`, and emits neither source text, URL nor a proposed
field value. Its approved-evidence ledger is intentionally empty and is never
read by comparable or price-cleaning builders:

```powershell
python tools/normalize/build_market_near_miss_review.py --root .
```

For a bounded vendor-correlation review pass, first build a replayable evidence
bundle from the existing pinned candidate page snapshot and vendored catalog,
then evaluate it in `vendor_correlation` mode:

```powershell
python tools/normalize/build_item_evidence_bundle.py --root . --output data/review/item-evidence.jsonl
python tools/normalize/promote_items.py --root . --evidence data/review/item-evidence.jsonl --mode vendor_correlation --output data/review/item-promotion-ledger.jsonl
```

Each claim has its source locator, claim hash and source snapshot hash. The
deterministic bundle is labeled `machine_correlated`, not human-approved. This
mode only records where one independent vendor catalog agrees with an
unverified printable-template seed. It must not be described as two-source
identity confirmation: canonical identity stays unresolved and the ledger
keeps `verification_status=needs_review` and
`model_feature_status=excluded_pending_verification`; season, acquisition,
availability, cost and visual-reference fields remain unresolved.

`build_catalog_query_index.py` derives a query index over the 94 canonical
items, 622 review candidates, and 1,758 source-scoped references. It verifies
the pinned snapshot bytes and all target IDs, keeps truth levels separate, and
does not duplicate or promote the canonical item master. The index is only
offline lookup/review support; it is never ownership proof or a model feature.

`apply_nintendo_starter_pack.py` is the bounded P2.5 canonical-evidence
replayer. It verifies the fixed official fact snapshot, independent vendor
snapshot, source registry lineages, JSON pointers and hashes before checking
the four existing Nintendo canonical records. Unknown Traditional Chinese
names, storefront availability, permanence, prices and images remain unknown;
the command neither fetches data nor adds model features:

```powershell
python tools/normalize/apply_nintendo_starter_pack.py --root .
```
