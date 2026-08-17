# Verified-sale receipt archive

`tools.market_receipts.verifier` replays a caller-injected archive that must
remain outside the release root. It has no network transport and never stores
raw receipts. A disclosure contains only opaque IDs, TWD/international sale
semantics, digests and two independently signed assertions. It rejects raw
names, handles, contact data, URLs, payments, login data and receipt images.

The archive and its authority bundle are authenticated by their caller-supplied
SHA-256 bytes. Every assertion is an OpenSSH detached signature over the sale
event, exact observation/training-example digests, the external resolver's
seller identity commitment,
price, completion time, currency and server. Two assertions must have distinct
issuer fingerprints and distinct authority-controlled `independence_group`s.

`make_authorization_evaluator` connects this replay to verified-sale intake only
when the same call also replays a complete externally signed
identity-to-dedup-cluster mapping. It exact-matches the seller identity
commitment, observation/training-example bytes, price, currency, server and the
calendar date of the independently completed sale. A signed receipt alone can
never make a claimed sale eligible for a model.
