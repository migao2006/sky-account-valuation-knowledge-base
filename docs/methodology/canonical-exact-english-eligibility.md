# Exact-English canonical observation eligibility

`canonical-exact-english-v1` is a narrow identity gate for model inputs. It is
not a market-price or resale-value gate.

An item becomes model-feature eligible only when the bounded declaration is
replayed successfully: its catalog record is `verified` with
`official_with_secondary` evidence; an approved official item-specific ledger
claim exactly equals `canonical_name_en`; and an approved secondary claim from
a distinct source lineage has the same parser-normalized English token. The
approved token is the official exact English spelling alone; case and punctuation
variation in an independent vendor title cannot expand it into an alias.

Traditional-Chinese labels, player aliases, fuzzy/casefold-only secondary
spellings, profile-migrated IDs, buyer listings, and multi-account listings do
not create a known model observation. They can remain review evidence, but are
not feature values. Item-vector and catalog-provenance checks reject a stale
catalog binding.

The cohort replay contracts own the model status of their target rows. A direct
edit to `items.jsonl` is rejected because validation recomputes the bounded
eligibility decisions from pinned field-evidence ledgers.
