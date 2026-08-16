# Fandom seasonal-cosmetics fixed snapshot

This P2.2 review artifact preserves revision `107991` of the Fandom printable
seasonal-cosmetics page as locally stored UTF-8 wikitext.  The two import tools
only consume that local file, calculate hashes, and write deterministic JSON or
JSONL.  They have no HTTP, API, crawler, provider, scheduler, or update code.

The original research request used Fandom's revision API outside the repository.
The metadata preserves the page URL, API revision URL, page/revision IDs,
timestamp, byte hash, recorded license notice, and a `needs_review` license
verification state.  It is evidence for review and attribution, not a claim of
downstream redistribution clearance.

The earlier printable-template candidates and this snapshot are from the same
Fandom community wiki lineage.  Crosswalk rows therefore always state
`not_independent_same_fandom_wiki`, have `promotion_effect: none`, and cannot
be counted as a second source, approved item identity, canonical item write, or
model feature.  Template subject/slot coordinates are retained exactly because
they are not reliable formal item names.

Rebuild locally:

```powershell
python tools/normalize/import_fandom_seasonal_cosmetics_snapshot.py --root .
python tools/normalize/import_fandom_seasonal_cosmetics_crosswalk.py --root .
```

Any later canonical change requires an independent, item-specific review path;
this snapshot alone must never be used for automatic promotion.
