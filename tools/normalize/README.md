# Offline normalization tools

`import_skygame_catalog_snapshot.py` accepts only a previously downloaded, pinned
`skygame-data@1.3.4` tarball. It never opens a network connection and emits a
field-limited source snapshot plus SHA-256-bound provenance metadata.
It checks that `assets/items.json` and the `items.items` component in the
package's composite `assets/everything.json` are identical before importing.

`compare_vendor_catalog.py` verifies the source package and snapshot hashes,
then performs exact normalized-name crosswalks against canonical items and
English aliases, followed by review-candidate English names. It writes
crosswalk and candidate field-evidence records only. Canonical matches always
take precedence; a candidate match is secondary identity/name/type evidence,
not a canonical promotion, alias addition, item verification, or model-feature
approval.

```powershell
python tools/normalize/compare_vendor_catalog.py --root .
```

The tool writes its output to `data/review/`; reviewers must independently
confirm each candidate before any canonical knowledge change.
