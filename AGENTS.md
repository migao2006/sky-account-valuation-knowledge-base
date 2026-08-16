# Project instructions

This repository is an offline-only static Sky account valuation knowledge base.

- Use Python 3 standard-library tools only.
- Do not add HTTP clients, crawlers, providers, schedulers, background services, or automatic update code.
- Keep canonical knowledge under `knowledge/`; derived market data must remain reproducible from canonical/source data.
- Preserve anonymity. Never store player names, social IDs, UIDs, phone numbers, email addresses, login or payment data.
- Keep listing, urgent, last-public and verified-sale prices distinct. Never infer a verified sale from a sold claim.
- Never use fixed per-item price additions.
- Before publishing, run:
  - `python tools/validate/build_reports.py --root .`
  - `python tools/validate/release_check.py --root . --source-zip ../sky-valuation-v2.4-1022-complete-2026-08-16.zip`
- Rebuild the offline ZIP only after validation succeeds.

