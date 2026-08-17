# Visual evidence capability coverage

`tools/modeling/visual_evidence_coverage.py` builds
`reports/coverage/visual-evidence-capability.json` from the committed catalog,
visual-reference manifest, image-evidence ledger, and an optional local asset
registry.  It is an offline audit only: it never downloads, invents, or
promotes an image, detection, or item identity.

## Evidence classes

- An **actual content-addressed asset** is a local file listed in
  `data/curated/visual-assets.jsonl` whose bytes replay to the declared
  SHA-256.  The registry ID and hash are the binding used by an
  `offline_asset` visual reference.
- An **asset-backed reference** is an `offline_asset` visual-reference row
  whose hash and registry ID match an actual registry row.
- An **approved detection** is an image-evidence row with `approved` review,
  `confirmed` evidence, a canonical `detected_item_id`, a unique detection ID,
  and an image hash present in the asset registry.  A text description is
  never a detection.
- A **source-description-only reference** is a `source_description` row.  It
  is a text locator for a catalog item, not a stored image and not a visual
  match.
- A **catalog identity locator** is a distinct canonical item ID linked by a
  visual-reference row.  It indicates that the reference can be joined to the
  catalog; it does not assert that the visual identity was confirmed.

The report emits each metric for three disjoint views of the catalog:

- `all`: every canonical item row;
- `verified`: items with `verification_status=verified`;
- `eligible`: items with `model_feature_status=eligible`.

Asset and detection counts are scoped through their referenced canonical item.
Unreferenced registry files remain visible in the registry summary but are not
silently attached to an item scope.

## Schema hardening

`offline_asset` requires both `asset_sha256` and `asset_registry_id`.  A
registered asset must be an `image/png` file under
`data/curated/visual-assets/`; its SHA-256, PNG magic/CRC structure, and
zlib-compressed pixel stream are replayed before it counts.  Arbitrary files
(including Markdown, source snapshots, or a path outside that directory) can
never be registered as an image.
`source_description` requires `asset_sha256: null`, cannot bind a registry
asset, and may not carry detection IDs.  `unavailable` has the same no-asset,
no-detection boundary.  The existing source-description rows omit the optional
registry and detection fields, so they remain valid without adding any visual
row.

## Rebuild

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
python tools/modeling/visual_evidence_coverage.py --root . `
  --output reports/coverage/visual-evidence-capability.json
```

The default registry path is optional.  Until an authorized local asset and a
matching registry row are supplied, the report correctly records zero actual
assets, zero asset-backed references, and zero approved detections.  The
current ten source-description references remain text-only.
