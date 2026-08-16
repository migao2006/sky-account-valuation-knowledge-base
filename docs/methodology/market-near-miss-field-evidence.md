# Market near-miss field evidence

P2.4 provides a deterministic offline queue for a limited human field-evidence
review. It selects only anonymous normalized listings that are already a
seller listing, a single account, a positive TWD price with verified TWD, have
no editorial exclusion or known duplicate cluster, and miss exactly one
remaining hard-evidence domain: verified international server, normal-listing
price type, or active status.

`data/review/market-near-miss-field-review.jsonl` deliberately stores only a
listing ID, SHA-256 hash of existing anonymous listing text, required field
names, and an opaque evidence domain. It contains no source text, URL, contact
data, machine-proposed values, item inference, season inference, or automatic
admission. Mixed brokerage pricing is permanently excluded from this queue;
`listing_0260` is not eligible.

`data/review/market-near-miss-approved-evidence.jsonl` is initially empty. An
evidence row must link the exact listing/hash, a requested field and final
value, two distinct pseudonymous human reviewers, and a third human
adjudicator. The ledger is review-only: it is not read by formal comparable,
price-cleaning, item-vector, or model tooling. Any future use requires a
separate reviewed migration of normalized facts, followed by ordinary rebuild
and validation. It cannot create a verified sale or imply ownership of 凜冬、
絆愛、阿努、多禮 or any other item.
