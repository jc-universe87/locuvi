# ADR 0005 — v1.0: from invoicing tool to "it just works"

Status: accepted (owner gave a free hand on 8 Oct 2026: "build the whole app", Apple-style
intuitiveness, a hands-free feeling).

## Design principle
Locuvi should feel like *"oh, it just works"*, not *"look how much I can do"*:
- **Organised around the work, not around forms.** Sessions are logged by tapping days in a
  calendar; invoices, pension figures and reports are derived from them.
- **Today tells you what to do next** (month ready to invoice, drafts, unpaid/overdue invoices,
  pension months ready) with one primary action per item.
- **Remember instead of asking.** The last rate per practice and session type, the practice's
  pensionable default, the selected practice and session type, account name = your name.
- **No save buttons where nothing can go wrong.** Drafts and profile settings autosave
  (debounced, "✓ Saved"). Credentials (email, Nextcloud) keep an explicit Save/Test because a
  half-typed password must never be used.
- **Irreversible steps still confirm** (issuing). Reversible steps don't confirm but offer
  **Undo** (logging a session, marking paid, marking pension submitted).
- **Progressive disclosure:** advanced practice fields sit behind "More options"; three-step
  welcome wizard on first run instead of a settings maze.
- Five destinations: Today · Diary · Invoices · Pension · Reports; Settings behind the gear.
  iOS-style tab bar on phones, quiet top bar on desktop.

## Business rules added
**Diary.** A session is active or cancelled; an active session dated today or earlier counts as
worked. "Create invoice" for a practice-month builds a draft from worked, uninvoiced sessions
(adding to an existing draft for that practice-month). Sessions on an issued invoice are locked;
deleting a draft or voiding an invoice releases them; at issue, sessions whose date was removed
from the draft are released.

**Payments.** Separate rows; the issued invoice and PDF never change. State is derived:
unpaid → part paid → paid; overdue = unpaid/part paid after the due date. "Mark paid" records the
full outstanding amount today (with Undo). Over-payment is rejected. An invoice with payments
cannot be voided (remove the payments first). Credit notes are still not implemented.

**Email.** Sent only on an explicit tap, via the owner's SMTP account (STARTTLS 587 or SSL 465,
certificate verified, same SSRF host check as WebDAV, password Fernet-encrypted, never returned).
Recipient pre-filled from the practice's billing email; PDF attached from the verified local
file; optional BCC to self; each send logged on the invoice.

**Pension (GP Locum A/B).** Figures per month are summed from *issued* invoices' frozen totals.
Because pensionable work cannot span months on one invoice, each invoice belongs to one
practice-month. Form A per practice: fees, pensionable pay (90%), employer contribution.
Form B: totals plus employee contribution = pensionable pay × the owner's tier rate (owner-entered,
since tiers depend on annual earnings). Locuvi produces a worksheet PDF and a "marked submitted"
record with frozen figures (flagged if figures later change, e.g. a void). **It does not submit
anything and the worksheet is not the official form.** Deadlines and tiers must be checked against
NHSBSA/PCSE guidance.

**Reports.** UK tax year 6 April – 5 April by invoice date; invoiced, received, outstanding,
employer pension; by month and by practice; CSV export (no bank details) and a year ZIP with all
issued/voided PDFs.

## Data
Migration 0002 adds `work_session`, `payment`, `email_config`, `pension_submission`, and columns
`owner_profile.{professional_number, pension_ref, employee_rate, setup_completed}`,
`practice.practice_code`, `invoice.last_emailed_at`. Existing installations with sender and bank
details are marked `setup_completed` so the wizard does not reappear.
