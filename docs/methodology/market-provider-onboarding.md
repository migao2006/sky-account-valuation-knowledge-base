# Authorized market-data provider onboarding

`tools/market_intake/onboarding.py` prepares an **unsigned candidate** from an
externally held, licensed, already-sanitized JSON staging file. It accepts no
raw listing text, URL, handle, contact detail, or source locator. It does not
scrape, infer a price, derive account features, create a statement, or sign.

The staging file and output directory must both be outside this release root.
Pass the staging file's SHA-256 explicitly:

```powershell
python tools/market_intake/onboarding.py --root . --version v2 `
  --staging C:\restricted\licensed-market-v2.json `
  --staging-sha256 <SHA256> --output-dir C:\restricted\candidate-v2
```

The strict `authorized-market-staging-v1` envelope contains an outside-root
immutable source-snapshot path plus its SHA-256, opaque cluster and
account-commitment digests, verified date/currency/server/entity
facts; the provider-supplied price and feature/catalog commitments. A feature
payload must be exactly `{ "feature_groups": ... }` and include
`feature_groups.base_account.account_type`, matching the publication runtime;
its catalog-provenance SHA-256 is separately supplied and verified. For
v3, structural completed-sale evidence IDs and hashes. v2 accepts asking,
reduced, and urgent listings. v3 accepts only verified completed sales, with
at least two independent structural evidence commitments.

P3.6 replaces the bootstrap payload with the exact
`authorized-market-feature-payload-v1` contract. It carries all eight model
groups (`season_profiles`, `item_sets`, `collection`, `resources`,
`map_completion`, `base_account`, `bindings`, and `ownership_history`) plus an
exact, catalog-bound `item_states` universe. All supplier values are bounded
enums, pinned canonical IDs, booleans, or bounded integers. Free prose,
account identifiers, short IDs, source descriptions, URLs, handles and contact
fields are not contract fields and are rejected.

The provider supplies an empty `item_sets` array. On import, the shared feature
canonicalizer derives every set summary and every model-eligibility flag from
the pinned catalog and the supplied item states; neither can be self-attested.
The same canonicalizer is used by authorization replay, publication training,
and Elastic Net inference, so signed training rows and runtime estimates use
the same item and aggregate features. A stale catalog binding, a missing or
duplicate canonical item state, or any unsupported field fails closed.

The builder re-hashes every immutable source file before emitting output. The
full source hash determines each derived observation/training ID and is included
in each signed observation and training-example commitment; neither source bytes
nor source paths are output. Duplicate full source digests and duplicate derived
IDs fail closed.

Outputs are `observations.jsonl`, `training-examples.jsonl`, `manifest.json`,
`registry-candidate.json`, and `capacity-report.json`. The candidate registry
has `statement_sha256: null` and is deliberately not admissible to the formal
registry. An independent issuer must provide the statement, and separate data
steward, privacy reviewer, and method reviewer must sign with three authorized
keys before it can be imported through the existing authorization contract.

The capacity report shows a deterministic cluster-exclusive chronological
300/100 calculation, but always reports `independence_verified: false` and
`requirements_met: false`: provider-supplied opaque cluster/account digests are
not proof that records represent independent identities. A future formally
signed, outside-root identity-to-cluster mapping verifier is required before
capacity can be claimed. It never becomes a fabricated training row or release
claim.

Consequently, even a cryptographically valid v2/v3 candidate remains ineligible
for model training and cleaning with
`market_data_cluster_independence_evaluator_required` until that mapping
contract exists.

## P3.6 external identity-to-cluster replay

`tools.market_identity.verifier` can now consume the required mapping contract,
but no mapping, identity key, or restricted source is stored in this repository.
The resolver supplies three outside-root inputs: an authority bundle, a PII-free
JSONL mapping, and a signed statement, each accompanied by its actual SHA-256.
The mapping binds every exact signed training example and observation to its
existing opaque account and cluster IDs.  It contains a resolver-generated
HMAC commitment only—never an account name, handle, source locator, identity
value, or resolver salt.

Two distinct OpenSSH identities are required: `identity_resolver` and
`identity_dedup_reviewer`. They attest the mapping byte digest, dataset roots,
expiry, and canonical receipt payload. A verifier rejects a missing or extra
row, any binding mismatch, one commitment assigned to multiple clusters, one
cluster assigned to multiple commitments, local release-root inputs, expired
statements, revoked keys, or invalid signatures. Only a fully replayed mapping
sets the factory evaluator's `cluster_independence_bound` flag; the cleaner and
publication freezer receive no raw identity commitment.

For the exact unsigned payload used by the existing OpenSSH verifier, import
`canonical_signing_payload(dataset_candidate, manifest, statement, attestation)`.
It returns bytes only; it never creates a signature.

## P4.0 external finalization

`tools/market_intake/finalization.py` is the only supported importer for a
candidate that has completed the external authorization process.  It accepts
the candidate directory, authority bundle, authorization statement, detached
signatures, and a `authorized-market-finalization-handoff-v1` handoff only from
outside the release root; each file is accompanied by its actual SHA-256.
The handoff pins candidate manifest/observations/training examples/registry
bytes, trust bundle and statement bytes, and the canonical bytes plus signature
digest of all three attestation receipts.

Each receipt must name exactly one `data_steward`, `privacy_reviewer`, or
`method_reviewer`; they must be three different non-revoked OpenSSH public-key
fingerprints.  The statement, manifest, observations, registry and each
signature payload must agree exactly. The importer never reads a private key,
creates a signature, or overwrites a dataset, registry, attestation, or
signature path. It currently imports one dataset only when the formal registry
and attestation ledger are empty; a non-empty registry fails closed rather than
claiming one external statement authorizes multiple datasets.

It stages the candidate under the fixed formal dataset location, invokes
`verify_authorized_market_intake` with the same external trust files, and rolls
back all newly-created files if replay fails. A successful import therefore
immediately passes formal authorization replay, though it still does not claim
identity independence, sale-receipt evidence, or model readiness.

## P4.1 append-only v2 finalization

`finalization.py --append-v2` is a separate protocol for a formal ledger that
uses `authorized-market-statement-bundle-v2`.  It accepts exactly one new,
outside-root candidate and a `authorized-market-finalization-handoff-v2`.
The externally SHA-pinned statement bundle must contain one canonical v1-shaped
claim for every already-imported dataset **and** the new candidate—no missing,
extra, or duplicate dataset claim is accepted.

Before mutation the importer replays the entire existing ledger against that
bundle. It then validates the new candidate's exact bytes and three distinct
role signatures, rejects collisions in dataset ID, authorization record ID,
attestation ID and signature path, and obtains an exclusive append lock. It
stages all bytes, checks the old ledger preimage through the same file handle,
creates new paths exclusively, and replays the complete resulting ledger. The
advisory lock serializes cooperating finalizer processes; operators must not
run a non-cooperating writer against the same ledger inode during a transaction.
On error or interrupt, rollback removes only matching file identities/dataset
hashes and restores an aggregate ledger only when its observed preimage is the
transaction output. The importer never signs, stores a private key, or turns a
candidate into model readiness.
