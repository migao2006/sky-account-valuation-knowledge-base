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
For that reason a non-empty gold ledger now also requires a detached OpenSSH
audit contract. The authority bundle is kept outside the release and its exact
SHA-256 is injected at validation time; a repository-local bundle is rejected.
For formal gold, each row has exactly three **v2** attestations in
`data/review/market-audit/attestations.jsonl`: one detached blinded receipt for
each annotator and one adjudication receipt. Each annotator signs only their
own annotation commitment plus the committed anonymous queue hash; neither
receipt signs the completed gold row. The adjudicator signs both verified
annotator receipt IDs and commitments, the same queue commitment, and a final
adjudication commitment. All three authorities must have distinct external
public-key fingerprints and authorized roles, and both submission timestamps
must precede the adjudication timestamp. This gives a replayable evidence
chain for independently submitted blinded decisions. Legacy v1 completed-row
signatures remain auditable for review ledgers but can never establish formal
market gold. Changed labels, queue fields, commitment links, timestamp order,
signature reuse, wrong role, revoked fingerprint, absent external root, or a
tampered signature fail closed.

The external JSON authority bundle has `schema_version`
`sky-market-audit-authority-bundle-v1`, an `authorities` array with
`authority_id`, OpenSSH `public_key`, computed `fingerprint`, and allowed
`roles`, plus an optional `revoked_fingerprints` array. No private key belongs
in this repository. The current ledgers and attestation file are empty, so the
offline release remains valid without an injected authority bundle.

For a non-empty ledger, inject the trust root rather than placing it in the
checkout:

```powershell
python tools/validate/validate.py --root . --market-audit-authority-bundle C:\secure\market-authorities.json --market-audit-authority-bundle-sha256 <SHA256>
```

The same values may be supplied by `SKY_MARKET_AUDIT_AUTHORITY_BUNDLE` and
`SKY_MARKET_AUDIT_AUTHORITY_BUNDLE_SHA256` for an offline release job.

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

## External onboarding foundation

`tools/market_review/onboarding.py` is an external-only handoff helper. It
does not generate labels, OpenSSH signatures, public/private keys, receipts, or
formal gold, and it refuses every output inside the release root and every
reserved formal-gold filename. The committed market queue has public listing
hashes; issuing A/B packets from it would make assignments linkable. Therefore
`issue-blind-packets` is deliberately fail-closed until a separately reviewed,
keyed custodian protocol provides a private assignment map. Supplying an
arbitrary secret or a local mapping is not supported.

The helper can make the exact unsigned v2 annotation-receipt payload for an
already-human external submission, and can build a minimal conflict packet from
two complete 200-row ledgers. Conflict packets carry receipt commitments only,
not listing text, listing hashes, or labels. Candidate import also fails closed
unless an external authority bundle, its exact SHA-256, a keyed custodian
issuance record, and three verifiable distinct-key receipts are available.
Formal gold remains exclusively governed by the v2 market-audit contract above.

Example handoff commands (all paths other than the committed queue are outside
the repository):

```powershell
python tools/market_review/onboarding.py receipt-payload --queue-row D:\restricted\queue-row.json --submission D:\restricted\human-submission.json --output D:\restricted\unsigned-receipt.json
python tools/market_review/onboarding.py build-conflict-packet --decisions-a D:\restricted\annotator-a.jsonl --decisions-b D:\restricted\annotator-b.jsonl --output D:\restricted\conflicts.json
```
