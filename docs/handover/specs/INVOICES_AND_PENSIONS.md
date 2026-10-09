# Invoice content and NHS employer contribution — v0.1

## UK sole trader invoice required information
Include unique invoice identification number, legal seller name (and trading name if used), seller address/contact, customer practice name/address, description, supply/work date(s), issue date, line amounts, total owed, and VAT amount where applicable. Bank remittance and due date are practical additions. Do not expose UTR, NI, GMC or NHS identifier by default. Verify with current GOV.UK guidance before production release.

## NHS GP freelance locum fee model
For **eligible NHS pensionable normal GP practice locum work**: pensionable pay is 90% of the relevant basic locum fee; employer contribution initial configuration for 2026/27 is **14.38% of pensionable pay**, equivalent to **12.942% of eligible basic fee**. Thus e.g. a £600.00 fee implies £540.00 pensionable pay, £77.65 employer contribution (77.652 rounded to pennies), invoice total £677.65. This is **employer addition to the invoice**, not the GP's employee contribution, and this app does not submit pension forms.

The fee must be clearly identified as *basic locum fee exclusive of employer pension addition* to avoid double counting if a practice quotes an inclusive figure. Allow explicit non-pensionable work lines and a manual choice to switch off pension additions. No fees should automatically be declared pensionable without user's confirmation/default visibility.

Store policy as effective-dated versioned settings, not a magic number, allowing future contribution rates to change. Calculate with Decimal and explicitly define rounding: line amount = qty × rate rounded half up at 2dp; aggregate eligible basic fee then pensionable pay (90%, round half up at 2dp); employer contribution from pensionable pay × 14.38%, half up at 2dp. Freeze rounded base, rate and result on issue. Include tests for edge cases and split invoices.

For GP locum pension administration, practices/months may require separate documentation. In v0.1 **warn/block merging eligible work across calendar months into one pensionable invoice**, offering to split, but permit nonpensionable cases explicitly. All dated line data remains available for a future forms module. Verify business rule against NHSBSA/PCSE current guidance before go-live and document chosen policy.

## VAT
Do not automatically impose 20% VAT or assert all medical/locum work is exempt. Provide status `not_vat_registered` as starting default, with a clearly marked manual/future VAT-compatible extension and corresponding validation if VAT registered. If VAT-registered invoice requirements cannot be fully met in v0.1, block issuing VAT invoices rather than creating a deficient legal document. Ask owner to confirm circumstances with their accountant if necessary.

## Numbering and issue
Use an editable initial sequence at setup then allocate each number transactionally and uniquely when issued. Allow prefix e.g. `LOC-2026-0001` without relying on auto-reset annually. Never reuse a voided number. Strong consistency between status, saved PDF checksum and number; robust recovery of partially completed issue operation. Use idempotency keys or database uniqueness/locking to avoid duplicate issues on repeated click.

## Dates, fees, money
Use Europe/London calendar interpretation for dates; persist ISO dates and GBP amounts as Decimal strings/integer pennies. Due date can be overridden. Store currency GBP. Render ISO internally, UK dates in UI/PDF. All illustrations are fictional.
