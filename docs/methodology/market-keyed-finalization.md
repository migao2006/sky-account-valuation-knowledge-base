# Keyed market finalization (P4.2)

`tools.market_review.finalization.verify_finalization(...)` is the read-only
replay API.  It requires the external custodian contract and SHA-pinned
authority bundle, opaque 400-row assignment ledger, signed A/B 200-row
decision ledgers, signed disagreement-only adjudication ledger, and a
separately SHA-pinned review authority bundle.  It returns no listing linkage
and does not write gold.

`build_candidate_bundle(verified, resolution_rows, contract, root)` is also
read-only.  The private custodian map must be a bijection to the committed
queue and paired assignment suffixes, reproduce both contract commitments,
and contain exactly twenty buckets with five development and five heldout rows
each.  The returned candidate is deterministic; it is only a signing request.

`import_signed_candidate(...)` repeats both operations before accepting a
custodian signature over the complete candidate and a second signature over
its private replay binding.  The minimum external inputs are the nine replay
inputs above, private resolution rows, candidate, candidate signature, and
binding signature.  The importer writes only the legacy-compatible formal
gold JSONL plus a privacy-safe receipt.  The receipt records hashes of the
candidate, binding payload, detached signatures, custodian contract, public
gold, and finalization—never private mapping rows or split assignments.

Only the tracked exact-empty `market-claim-gold.jsonl` placeholder can be
replaced.  Existing nonempty artifacts are immutable.  Identical re-import is
idempotent; any other existing output fails closed.  Created files are removed
only after ownership checks, and an import failure restores the empty baseline.
