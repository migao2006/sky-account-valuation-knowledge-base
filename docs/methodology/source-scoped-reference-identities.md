# Source-scoped reference identities

`data/normalized/source-scoped-item-identities.jsonl` is the single derived
record of the 1,758 collectible observations in the pinned SkyGame-Data 1.3.4
snapshot.  A `reference_identity_id` is deterministic from `source_id`,
`snapshot_id`, and `vendor_guid`; it is not a canonical `item_id`.

Every row retains the observed name and type, fixed snapshot SHA-256, exact
crosswalk links, and collision quarantine state.  `canonical_link` and
`candidate_link` are review links only: the identity status remains
`unverified`, promotion is `prohibited`, and model feature status remains
`excluded_pending_verification`.  The builder is offline and reproducible:

```powershell
python tools/normalize/build_source_scoped_item_identities.py --root .
```

The P2.6 summary records 69 canonical relations, 296 candidate relations,
1,393 unresolved observations, and 26 quarantined cross-type observations.
It does not assert 1,758 canonical game items or make any catalog/model
promotion; the counts are rebuilt rather than treated as permanent constants.
