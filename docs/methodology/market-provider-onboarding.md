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
