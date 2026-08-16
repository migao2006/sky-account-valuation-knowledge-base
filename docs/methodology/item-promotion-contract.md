# P2.5 pinned-item promotion contract

`tools/normalize/promote_items.py` is an offline, deterministic review gate.
It may produce an `approved_for_canonical_promotion` ledger row only from
reviewed P2.5 evidence; it never changes `knowledge/items/items.jsonl`.

Each eligible claim is governed by
`schemas/review/item-promotion-evidence.schema.json` and must provide:

- a `source_id` foreign key to `knowledge/sources/sources.jsonl` and an exact
  registered `source_lineage_id`;
- a repository-relative snapshot path, byte count, and SHA-256 of the pinned
  UTF-8 JSON snapshot;
- an RFC-6901 claim locator plus the hash of both that located value and the
  normalized claim value; and
- human `approved` review status.

The strict gate replays snapshot bytes, resolves the locator, and rejects a
claim when any hash, byte count, value, source tier, source registry key, or
lineage disagrees. It requires canonical identity, English name, category,
and (where applicable) season coverage. Identity confirmation must include an
item-specific official source and two independently registered source
lineages. Missing or unknown evidence fails closed.

The output ledger records the contract version, replay state, source lineages,
and per-field source coverage. `promotion_ready` is only a reproducible review
decision. A separately reviewed migration is still required to write canonical
items, aliases, or model eligibility. P2.5 contains no fixture evidence and
does not promote existing candidate items.
