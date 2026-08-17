# Declarative canonical evidence

`canonical_evidence_declaration_v1` is a narrow, data-only replay format. It accepts only repository-local `data/source/**/*.json` snapshots, SHA-256 pinning, RFC 6901 exact pointers, and an exact selected source item ID. Each rule emits the existing canonical field-evidence shape; values are read verbatim at the declared locator.

It rejects path traversal, non-JSON inputs, unresolved or malformed pointers, hash changes, unknown fields, duplicate target/source/field/locator rules, and data-driven execution capabilities (`regex`, transforms, imports, modules, callables, scripts, and commands). It has no write API and never changes items, model features, visual evidence, availability, or registry promotion state.

The Days of Love FAQ 1374 four-item declaration is a **shadow-only** parity fixture. Its generated ledger must byte-match the established Python verifier's ledger. It cannot be promoted by changing a registry row.

## Production v2 cohort

`canonical_evidence_declaration_v2` is the only declarative format that the
registry can replay as a production cohort. It remains intentionally
data-only: every source must be a registered source with the exact registered
lineage, a repository-local JSON snapshot SHA-256, RFC 6901 object/claim
pointers, an exact selected source item ID, and verbatim target/field mapping.
No transforms, patterns, imports, code, or path traversal are accepted.

A production registry row must be `approved` and `release_required`, pin both
the declaration path and byte SHA-256, and point at separate review metadata.
That metadata contains two distinct reviewer attestations, each bound to the
cohort ID, declaration digest, reviewer ID, and review date. The registry also
rejects same-lineage sources, unregistered sources, target overlap with any
other cohort, declaration/registry target or source mismatches, and a ledger
that is not byte-for-byte reproducible from the declaration. Existing bespoke
verifiers remain valid; no current shadow declaration is production data.
