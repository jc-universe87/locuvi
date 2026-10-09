# Product requirements — v0.1

## Goal
Create a reliable GP locum invoice from a saved practice and dated work items, issue/download an A4 PDF, retain the original forever in local storage, and optionally archive it automatically to Nextcloud via WebDAV.

## Persona and scope
One UK GP, self-employed sole trader. Normal GP practice locum work only. No OOH, SOLO, salaried GP, payroll, team accounts, or multi-user billing. No need to distribute/commercialise.

## Functional workflows
**Setup once:** owner legal invoice name, optional trading name, correspondence/service address, email/telephone, professional label, remittance bank account name/sort code/account number, invoice prefix and next sequence, default terms, pension contribution default, Nextcloud optional settings. Store practice names, billing address, email/reference, normal fee and defaults.

**Create:** choose practice; add lines with exact date, AM/PM/day/hours/custom, description, quantity and unit rate; choose whether each line is pensionable; preview subtotals, employer pension addition, total and payment details. Multiple work dates supported. Save as draft/edit/duplicate.

**Issue:** preflight validations; in one durable operation allocate unique immutable sequential number, capture sender/practice/bank snapshots and exact rate/rounding metadata, render PDF and persist it atomically. If PDF generation fails, do not mark as issued; safe reattempt without duplicate numbering. Mark status `issued`. Nextcloud upload happens independently afterwards. A browser download must work with WebDAV offline.

**Historical:** find/filter by practice/date/number/status; view/re-download exact original issued PDF. Draft editable. Issued unchanged; void with reason and immutable trail; duplicating creates new draft. No destructive delete of issued invoices. No automatic emailing in v0.1. Download and manual send are enough.

**Nextcloud:** optionally configure WebDAV server, upload path, toggle automatic upload on issue; connectivity test, upload status, manual retry and reupload if confirmed missing. Local copy always authoritative. Details in `NEXTCLOUD_WEBDAV.md`.

## Explicit exclusions
No full session diary, pension Forms A/B, PCSE uploads, payment tracking/reconciliation, chase emails, bank sync, AI agent, taxes, accountants, analytics or SaaS account system. Data architecture should accommodate future modules without building them now.

## Key acceptance outcome
Set up a practice and owner; generate an invoice covering two fictional October sessions; invoice total and pension line correct; download same PDF after app reboot; optionally upload to configured Nextcloud path; if Nextcloud offline, issuance and download still work and sync is visibly pending/failed.

## Design philosophy
A very small workflow: Invoices / Practices / Settings. Fast default; no unnecessary setup or modal chains. Accurate over clever.
