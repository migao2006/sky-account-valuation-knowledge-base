# Market-claim gold contract

P2.2 establishes an offline, fixed 200-listing review queue for market-field
labels. The queue stores only an anonymous `listing_id`, a SHA-256 digest of
the existing normalized listing text, an opaque selection bucket, and fields
to label. It stores neither listing text nor machine-proposed labels. Bucket
names intentionally do not reveal seller/buyer, service, currency, sold, or
exchange classifications to annotators.

`data/review/market-claim-gold.jsonl` intentionally starts empty. A row becomes
gold only after two independent humans (`annotator_a`, `annotator_b`) label all
requested fields and a distinct human adjudicator records final labels. The
integrity validator requires three distinct pseudonymous IDs and exact review
queue/listing/hash linkage. The schema requires `annotator_kind: human`,
`adjudicator_kind: human`, and
`annotation_protocol: double_independent_human_annotation`; agent, model, OCR,
or parser output cannot satisfy this contract.

The repository can enforce distinct pseudonymous roles and exact data linkage,
but it cannot cryptographically prove that a pseudonym belongs to a human.
Operational review must therefore verify reviewer identity outside the dataset
before any non-empty gold file is accepted; the current gold file is empty.

The deterministic sample has twenty opaque buckets of ten unique listings.
Selection coverage includes price presence and price-type ambiguity, TWD/HKD/RM/CNY
and unknown currency claims, international/China/unknown server claims, seller-like
and non-seller transaction forms, multi-account posts, date claims, and listings
with resource, season, and binding text. This coverage is encoded only in the
offline selector; it is not exposed in queue rows and must not be treated as a
machine-proposed label. The queue is a review instrument, not a market-price
sample and not a license to treat a sold claim as a verified sale.

Build the deterministic queue offline:

```powershell
python tools/normalize/build_market_claim_review.py --root .
```

The script does not contact a network and never modifies normalized listings,
formal profiles, comparables, market reports, or canonical knowledge.
