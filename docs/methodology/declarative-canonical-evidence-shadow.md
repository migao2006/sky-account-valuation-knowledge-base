# Declarative canonical-evidence shadow

`canonical_evidence_declaration_v1` is a narrow, data-only replay format. It accepts only repository-local `data/source/**/*.json` snapshots, SHA-256 pinning, RFC 6901 exact pointers, and an exact selected source item ID. Each rule emits the existing canonical field-evidence shape; values are read verbatim at the declared locator.

It rejects path traversal, non-JSON inputs, unresolved or malformed pointers, hash changes, unknown fields, duplicate target/source/field/locator rules, and data-driven execution capabilities (`regex`, transforms, imports, modules, callables, scripts, and commands). It has no write API and never changes items, model features, visual evidence, availability, or registry promotion state.

The Days of Love FAQ 1374 four-item declaration is a **shadow-only** parity fixture. Its generated ledger must byte-match the established Python verifier's ledger. The existing verifier remains authoritative; a later explicit review would be required before any promotion decision.
