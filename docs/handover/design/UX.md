# UX and document specification

## Navigation
Only 3 primary destinations: **Invoices** (default), **Practices**, **Settings**. Responsive mobile-first, keyboard-friendly on Chromebook. No login page if deployment is limited to securely authenticated private gateway; consider app PIN/session if threat model demands it.

## Invoices index
Top action `New invoice`; compact table/cards: invoice number or Draft, practice, issue date, work period, total, status, WebDAV status. Search, filter, duplicate, download, open. Distinguish draft/issued/voided clearly.

## New invoice
- Practice autocomplete/select + inline new practice
- Issue date/default terms, optional purchase order/reference
- Lines: work date, AM/PM/full day/hours/custom, description, quantity, rate, pensionable checkbox
- Auto-add next date line; sticky total summary on mobile
- Clear breakdown: basic locum fee; 90% pensionable pay (explanatory only); employer contribution; invoice total
- `Save draft`, `Preview`, `Issue & download` (confirm irreversible issuance)
- Visible expected contribution and any mismatch with practice's agreed inclusive/exclusive fee.
- Alert for multi-calendar-month pensionable sessions with suggested split.

## Details
Immutable PDF download for issued invoice, current archive status, `Retry WebDAV backup` on failures, void with reason. No direct edit of issued details. Allow duplicate to fresh draft.

## Settings
1. Sender & bank details
2. Invoice numbering/terms
3. Pension contribution default/rates
4. Storage: local and Nextcloud/WebDAV with `Test connection` and `Save`

## Invoice A4 document
Header `INVOICE` and number; sender legal name/address/contact; Bill To recipient practice/address; issue/work dates, due date; lines for each date; subtotal, employer pension addition when applicable, GBP total; payment bank details; optional notes. Avoid overflow, clipped columns or orphan totals, with multi-page footer and page numbers.

## Errors
Friendly, actionable, nontechnical; say exactly whether invoice is saved locally even if remote sync fails. Confirm destructive/status actions. Accessible labels, visible focus, sufficient contrast and responsive layout.
