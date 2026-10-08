# ADR 0003 — Invoice and pension business rules as implemented

Status: accepted (v0.1). **Verify against current NHSBSA/PCSE and GOV.UK guidance before go-live.**

## Money and rounding
- GBP only; amounts and quantities are `Decimal`, stored as text, sent to the browser as
  strings; the browser never does arithmetic (totals come from `/invoices/calculate`).
- Floats are rejected at the API. Quantities and rates allow at most 2 decimal places;
  quantity > 0, rate ≥ 0. Negative lines/credit notes are not supported in v0.1.
- `line amount = round_half_up(qty × rate, 0.01)`
- `eligible basic fee = Σ amounts of lines marked pensionable` (only if the invoice's
  pension addition is switched on)
- `pensionable pay = round_half_up(basic × pensionable_fraction, 0.01)` (0.90)
- `employer contribution = round_half_up(pensionable pay × employer_rate, 0.01)` (0.1438)
- `total = fee subtotal + employer contribution`. VAT is not added.

## Pension policy
- Effective-dated rows in `pension_policy`, seeded by migration with 2026-04-01 → 0.90 / 0.1438.
  Rows are append-only from the UI; a row used by an issued invoice cannot be deleted.
- The policy is chosen by the **earliest pensionable work date** on the invoice. If a different
  policy would apply to a later pensionable date in the same month, issuing is blocked
  (split the invoice) — a rate change mid-month is not silently averaged.
- The chosen policy id, fraction, rate, rounding description and all results are frozen
  in the issue snapshot.
- New invoices default to "add employer contribution" (configurable); each line's
  pensionable flag is visible and defaults from the practice. Nothing is pensionable
  without being shown as such in the editor and the confirmation dialog.

## Calendar months
Pensionable lines spanning more than one calendar month **block** issuing, with a one-click
*Split by month* (one draft per month; the original keeps the earliest month).
Non-pensionable lines across months are allowed with a warning. Dates are plain ISO dates
interpreted in Europe/London; "today" defaults use Europe/London.

## VAT
`vat_status` defaults to `not_vat_registered`; the PDF states "No VAT charged: supplier is
not VAT registered". If set to `vat_registered`, **issuing is blocked** in v0.1 rather than
producing an incomplete VAT invoice. No claim is made about whether any service is exempt.

## Numbering and issue
- Prefix + zero-padded counter (e.g. `LOC-2026-0001`), editable at setup; no automatic
  annual reset. A number is allocated only at issue inside `BEGIN IMMEDIATE`; a unique
  constraint backs it. Settings refuse a "next number" that is already used.
- Issue requires an `Idempotency-Key`: a repeat with the same key returns the original
  result; any other attempt on an issued invoice is 409.
- The PDF is rendered and written (temp file → fsync → rename) *inside* the transaction; if
  rendering or writing fails nothing is committed and the number is not consumed. A file
  left by a transaction that failed at commit is moved to `invoices/quarantine/` at next start.
- Issue date defaults to today; due date defaults to issue date + practice terms (or the
  default terms). The snapshot holds seller, practice, bank, lines, totals, policy and
  presentation; later edits to settings or practices never change issued invoices.

## Void, duplicate, delete
Void requires a reason, keeps number, snapshot and PDF; the archive copy is left as is.
Drafts can be deleted; issued/voided invoices cannot. Duplicate copies lines into a new draft.

## Invoice content
Number, issue date, due date, work period, seller legal name (+ trading name, address,
contact), Bill-to practice and address, dated lines with descriptions/qty/rate/amount,
pensionable flag column, subtotal, employer addition with its basis, total, bank remittance
and payment reference, optional notes, a footnote that the invoice is not an NHS pension form,
and "Page X of Y" footers. UTR/NI/GMC numbers are not shown.
