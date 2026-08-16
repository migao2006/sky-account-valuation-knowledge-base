# Project instructions

This repository is an offline-only static Sky account valuation knowledge base.

- Use Python 3 standard-library tools only.
- Do not add HTTP clients, crawlers, providers, schedulers, background services, or automatic update code.
- Repository tools must never initiate network access. An external researcher may use the network outside this repository; any resulting formal data must enter review before it can become canonical.
- Keep canonical knowledge under `knowledge/`; derived market data must remain reproducible from canonical/source data.
- Preserve anonymity. Never store player names, social IDs, UIDs, phone numbers, email addresses, login or payment data.
- Keep listing, urgent, last-public and verified-sale prices distinct. Never infer a verified sale from a sold claim.
- Never use fixed per-item price additions.
- Treat `data/comparables/accounts.jsonl` as the formal multi-dimensional comparable input. `data/comparables/histories.jsonl` is price history only and is not a complete estimation input; reject it clearly when it is supplied as an account comparable file.
- Classifier output for a user's valuation is governed by `schemas/input/valuation-account.schema.json` and may omit a market listing ID. The classifier accepts structured claims only; image support is an evidence contract, not OCR or visual-item recognition.
- Unknown is not a match and is not confirmed absence. Keep confirmed differences separate from unconfirmed dimensions.
- Estimation must require at least three hard-pool-compatible cases, at least three valid prices, a minimum similarity of 40/100, and at least three effective content dimensions. Otherwise return `insufficient_comparables` without a price range and explain exclusions and limitations.
- P0.1 is not a full-item release. Do not claim completion of all items, image evidence, visual references, or verified sales. Current formal market coverage has only three cases with both TWD and international-server values confirmed, so the applicable range is limited.

## Release verification

Before publishing, run:

```powershell
python tools/validate/build_reports.py --root .
python tools/validate/validate.py --root .
python tools/validate/release_check.py --root . --source-zip ../sky-valuation-v2.4-1022-complete-2026-08-16.zip
```

Rebuild the offline ZIP only after validation succeeds. Confirm that the checkout uses UTF-8 LF text files, all manifest hashes match, no staging or `__pycache__` files are present, and the source ZIP remains unchanged.

For each user-authorized repository update, treat validation, commit, push to the current task branch, and pull-request handoff as one completion flow unless the user explicitly requests a local-only change. Never bypass branch protections or assume that direct pushes to `main` are authorized. Do not run a background file watcher or auto-commit unreviewed working-tree changes.
