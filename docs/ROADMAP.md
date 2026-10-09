# Locuvi roadmap

Living plan for Locuvi. **v0.1 = GP Locum Invoicing** (done). **v1.0 = GP Locum Management**
(done, 8 Oct 2026): diary, payments, email, pension worksheets, reports and the "it just works"
redesign (ADR 0005). Next: polish from real use, then the groundwork for the optional AI
assistant (Part 4, spec in `docs/specs/AI_AND_AGENTS.md`).

Sources: the original handover (`docs/handover/` — especially `implementation/BUILD_PLAN.md`,
`specs/PRODUCT.md` "Explicit exclusions" and `engineering/ARCHITECTURE.md` "Future
extensibility"), decisions in `docs/decisions/`, and owner feedback.

Ground rules for every phase (from `docs/handover/CLAUDE.md`, still binding):
- Personal, single-user, self-hosted, private network only. Not a SaaS.
- Local DB + immutable local PDFs are authoritative; never silently alter issued records.
- Decimal money, versioned rates, explicit rounding; fictional data only in tests/fixtures.
- No secrets in git or logs. Test integrations only against disposable fixtures.
- A scope expansion starts only when the owner asks; each phase gets a short ADR if it
  changes a business rule, tests, a Docker smoke test and an update to this file.

Status key: ✅ done · 🔜 next · 🧭 planned · 💭 idea / later · ⛔ out of scope

---

## Part 1 — Original build plan (v0.1) — ✅ complete

| Phase (handover BUILD_PLAN) | Status | Where |
| --- | --- | --- |
| 0. Repository hygiene: monorepo `backend/ frontend/ docs/`, lockfiles, Docker, `.gitignore` | ✅ | repo root |
| 1. Core accounting engine: migrations, Decimal fee/pension maths, snapshots, transactional numbering, multi-month guard | ✅ | `backend/locuvi/money.py`, `services/`, ADR 0003 |
| 2. PDF and local persistence: A4 template, crash-safe issue, immutable PDFs, search/duplicate/void | ✅ | `pdf/render.py`, `storage/local.py` |
| 3. WebDAV archive: secret strategy, connection test, safe paths, verified upload, retry queue, conflict protection | ✅ | `webdav/`, ADR 0004 |
| 4. UI: Invoices / Practices / Settings, responsive editor, previews, archive status, i18n | ✅ | `frontend/` |
| 5. Hardening: tests, Docker smoke/restart, failure injection, PDF check, SSRF/auth/secrets review, backup/restore drill | ✅ | `docs/IMPLEMENTATION_REPORT.md` |
| Deployment on owner's server (LAN, port 8767, password mode) | ✅ | README §1 |

Acceptance criteria from `implementation/ACCEPTANCE.md`: all met — evidence in
`docs/IMPLEMENTATION_REPORT.md`.

---

## Part 2 — Operations (do now) — 🔜

| Item | Status | Notes |
| --- | --- | --- |
| Owner setup: sender/bank, numbering, pension rate check, practices, first test invoice | 🔜 | In the app; verify 14.38% / 90% against current NHSBSA guidance |
| Nightly backup | ✅ | Automatic after 02:00 into `/backups` (30 days kept), "Back up now" on Today |
| Off-server encrypted copy of `backups/` | 🔜 | Built in: create `secrets/backup_passphrase.txt` and enable it in compose (README §5) |
| Restore drill on the real server (once) | 🔜 | `locuvi.cli restore` into a scratch volume, then `verify` |
| Merge working branch into `main`; deploy from `main` | 🔜 | Owner to approve PR |
| HTTPS on the intranet (Caddy internal CA or Tailscale serve) | 🧭 | Plain http on LAN is readable by others on that network |
| Connect Nextcloud (app password, allowlist if private) | 🧭 | Optional |
| Go-live check of rules against GOV.UK invoice requirements and NHSBSA/PCSE guidance | 🔜 | `docs/handover/SOURCES.md` |

---

## Part 2b — Review fixes (external code review, 9 Oct 2026)

| Item | Status |
|---|---|
| Form B by month fees were **received** (payments apportioned per invoice, exact across partial/late payments); Form A one per invoice for the work month (migration 0015 re-keys) | ✅ |
| Pension deadlines: 10-week rule per engagement (incl. work not yet invoiced / unpaid / Form A unsigned / not on a submitted Form B) and Form B 7th-of-month due/overdue | ✅ |
| Cash-basis (default, HMRC) and invoiced-income reports, switchable and remembered; payments-received CSV in the year pack; 12 tax months (6th–5th) instead of 13 calendar months | ✅ |
| Atomic multi-invoice bank matching (all payments + "matched" in one transaction; failure-injection tests) | ✅ |
| Refund owed after a credit note on a paid invoice: "refund_due" state, finding, "Record refund" (negative payment with undo), netted in cash reports and Form B | ✅ |
| AI attachments only with explicit per-document approval (audited; automatic email scans never send files); stronger redaction (patient lines dropped; emails, phones, postcodes, bank details, NHS and long numbers masked) | ✅ |
| Credit notes archived to Nextcloud: own jobs at `<base>/YYYY/MM/CN-….pdf`, SHA-256 verified, never overwritten; status on the invoice page; included in "Archive all" | ✅ |
| Encrypted off-server backups (passphrase secret; scrypt + AES-256-GCM; uploaded to Nextcloud, SHA-256 verified, never overwritten) + automatic restore drill after every backup (`locuvi.cli drill` / `decrypt`; failures on Today) | ✅ |
| CI on GitHub Actions (`.github/workflows/ci.yml`: backend ruff + format + pytest, frontend test + typecheck + build, Docker image) on every PR and push to `main`; `main` as the stable branch (owner: set it as the default branch and protect it in GitHub settings) | ✅ |

## Part 3 — Product roadmap

Design principle for everything below (owner, 8 Oct 2026): **Apple-style intuitiveness** —
"oh, it just works", minimal fields, smart defaults, hands-free feeling. See ADR 0005.

### v0.1.x — Polish — ✅
- ✅ Upload all past invoices to Nextcloud in one go; ✅ new-year prefix helper;
  ✅ TLS test with a self-signed WebDAV server.

### v1.0 — GP Locum Management — ✅ (ADR 0005)
| Former version | Feature | Status |
| --- | --- | --- |
| v0.5 Session diary | Tap-a-day calendar, remembered rates, Undo; month → draft invoice in one tap | ✅ |
| v0.2 Payments | One-tap "Mark paid" with Undo, part payments, overdue detection, outstanding totals | ✅ |
| v0.3 Sending | Email the issued PDF from your own address (explicit tap, sent log) | ✅ |
| v0.4 Pension A/B | Monthly Form A/B figures from issued invoices, worksheet PDF, mark submitted | ✅ (worksheet, not a submission) |
| v0.6 Reports | Tax-year summary, by month/practice, CSV, year ZIP pack | ✅ |
| — | Today screen, 3-step welcome wizard, autosave, iOS-style navigation, sheets, toasts | ✅ |

### Next — 🔜 driven by owner feedback
- 🔜 Owner feedback after a month of real use (list items here).
- ✅ Credit notes (own number series, `CN-0001`…) for corrections after a practice has booked
  an invoice: credit whole lines, priced with the invoice's frozen pension rates (the last
  credit takes exactly what remains, so a fully credited invoice nets to £0.00); issued like
  invoices (BEGIN IMMEDIATE, idempotency key, immutable PDF in `invoices/credit/`, PDF failure
  doesn't use a number); reduces what's owed, bank matching, pension month figures and the
  tax-year report; covered by integrity checks and backups; invoices with credit notes can't be
  voided. Credit-note PDFs are archived to Nextcloud too (Part 2b).
- ✅ Repeating bookings ("every Tuesday AM at X until December") in the Diary: Repeat… →
  weekdays, weekly/fortnightly, from/until, live preview; days already booked are skipped;
  one undo removes the whole series.
- ✅ Calendar subscription (ICS) of booked sessions for the phone calendar (Settings › Phone
  calendar): private secret link (encrypted at rest, regenerate/turn off), no fees unless
  chosen, cancelled sessions marked cancelled, RFC 5545 folding/escaping.
- ✅ Personalisation (owner request, Settings › Personalisation): own logo on invoices and
  credit notes (PNG/JPEG/WebP, cleaned: metadata dropped, empty edges trimmed, resized; kept in
  the database so backups cover it), accent colour from print-safe presets, one-line footer on
  every invoice page, email sign-off for drafted emails, sample-invoice preview. Frozen into each
  issued snapshot (`presentation`), so issued documents never change (migration 0018).
- 🧭 Native review of DE/KO/FR/ES/PT translations (currently navigation only).
- ✅ Password change without editing the secret file (Settings › Password): scrypt hash in the
  database overrides the secret file; changing it signs out every other device (session epoch);
  `python -m locuvi.cli reset-password` falls back to the secret file if forgotten.
- 🧭 Each April: add the new employer rate and check your employee tier (Settings → Pension).

### Later ideas — 💭
- VAT-registered invoices, only if the owner becomes VAT registered and an accountant
  confirms the treatment (currently blocked by design).
- PostgreSQL migration path if SQLite ever becomes a limit (unlikely for one user).
- Installable phone app (PWA) with offline read-only view of the Diary and invoices.

### Out of scope — ⛔
Multi-user/team accounts, SaaS/public hosting, OOH/SOLO/salaried GP payroll, tax
calculation/self-assessment filing, analytics/tracking, patient or medical data of any kind.

---

---

## Part 4 — AI assistant and agents

Specification: [`docs/specs/AI_AND_AGENTS.md`](specs/AI_AND_AGENTS.md) (owner, 8 Oct 2026).
**The application manages the records; the AI helps manage the work.** AI is optional and
off by default. Calculations, numbering, deadlines and pension figures stay deterministic.
The AI proposes and the owner approves. It never issues, sends, pays, submits or changes bank
details on its own, and every proposal and tool call is audit-logged.

**Bevro** is the owner's own agent platform: it links all of the owner's agents and lets them
communicate from one place. Locuvi joins it as one connected agent/tool provider (Phase 4).

**Agreed order (owner, 8 Oct 2026):**
1. Polish from real use.
2. Checks engine and weekly digest.
3. Document inbox, then paste-a-booking as the first AI feature. ✅ (Oct 2026)
4. Bank CSV import. ✅ (Oct 2026)
5. Form A tracking and PCSE import. ✅ (Oct 2026)
6. The full administrative agent. ✅ (Oct 2026)
7. Bevro integration. ✅ (Oct 2026)

### Phase 1 — Foundation without AI — ✅ (v1.0)
Structured sessions, deterministic invoice engine, payments, pension figures, Nextcloud archive.
The Today overview already gives rule-based monitoring for uninvoiced months, overdue invoices
and pension months. Service functions (`services/*.py`) are the future tool layer.

### v1.5 — Groundwork the assistant needs (no AI yet) — ✅
Each item is useful on its own and gives the AI something reliable to work with.
- ✅ **Checks engine** (`services/checks.py`): deterministic rules that produce *findings* (severity, explanation,
  linked records, suggested action), e.g. uninvoiced sessions, due/overdue invoices,
  sessions with no rate, duplicate or overlapping bookings, Form A not returned, Form B missing,
  payments not matched. Today shows the findings; a scheduler re-runs them daily. (Spec E)
- ✅ **Document inbox** (`services/documents.py`, `/inbox`): add PDFs, images, .eml, text or
  CSV files (drop or pick) or paste text. Stored locally under random names, de-duplicated by
  SHA-256, text extracted once (pypdf / email parser), type and practice guessed, searchable,
  New/Done, delete with undo (purged after 30 days). Forwarding by email is still to do.
  (Spec A, 4 `read_authorised_document`)
- ✅ **Bank statement CSV import** (`services/bank.py`, Invoices › Payments in): reads the
  common UK CSV exports (signed amount, separate paid in/out, £ signs, CR/DR, headerless),
  keeps **only money in** (debits, balances and the file itself are never stored), de-duplicates
  re-imports, and matches deterministically: invoice number in the reference → exact amount
  with the practice named → exact amount → combined payment of 2–4 invoices of one practice.
  Ambiguous amounts are never guessed. "Confirm N matches" records payments (dated as the
  bank credit); manual pick, "Not an invoice", and undo for each. (Spec D)
- ✅ **Form A tracking**: per practice-month status (to send → sent → signed; Form B
  "submitted" as before) with dates and an optional linked inbox document as evidence. A
  finding asks to chase a Form A sent > 14 days ago and not signed. Progress never counts
  as a figure change. (Spec C)
- ✅ **PCSE comparison**: type in, or import as CSV (month + pensionable pay and/or
  contributions; rows per practice are summed), what PCSE/NHS Pensions shows; Locuvi compares
  with the expected figures from issued invoices and flags mismatches. (Spec C)
- ✅ **Correspondence log**: each invoice shows the emails sent from Locuvi (recipient,
  subject, time) and the inbox documents/emails linked to it — linked automatically when the
  invoice number appears in the text (remittances, replies), or by hand in the inbox. The
  agent sees it through `get_invoice`. (Spec F)
- ✅ **Audit log for proposals** (`Proposal` table, `services/proposals.py`): what was proposed,
  by which engine (`rules` or `ai:<model>`), what the owner accepted, changed or rejected, and
  what was created — with undo. Used by the rules reader and the AI alike.
- ✅ **Notifications**: optional weekly email digest of findings ("2 sessions not invoiced,
  1 invoice overdue").
- ✅ **Practice instructions** as structured fields: PO number required, invoice address/email,
  portal upload, who signs Form A. Useful now, and reliable context for the AI later.
- ✅ **Self-assessment figures** in the tax-year pack: income totals and employee pension
  contributions, as figures only, not tax advice.

### Phase 2 — AI invoice assistant — ✅ (v2.0, Oct 2026)
- ✅ Provider-agnostic LLM interface (`assistant/providers.py`; Claude API first via the
  official SDK, local model option later). Off by default; API key encrypted at rest or
  supplied as `ANTHROPIC_API_KEY_FILE`. Structured JSON output, explicit effort, server-side
  refusal fallback enabled, refusals reported plainly. Long numbers and DOBs are redacted
  before anything is sent; only the text, practice names and today's date leave Locuvi.
- ✅ **Paste a booking** (Diary, Inbox) → sessions (practice, dates, AM/PM/day/hours, fee)
  shown as a checklist to confirm: "Add N sessions", with undo. Works **without AI** too
  (`assistant/rules.py` reads common formats); with the assistant on, scans/PDF images and
  free-form emails are read by the model. Every value is re-validated by the server, rates
  fall back to the remembered rate, and duplicates, clashes, cancellations, unknown
  practices and missing rates are flagged against the Diary. Missing details become
  questions, not guesses. (A)
- ✅ **Email folders** (`services/mailbox.py`, Settings › Email folders; owner request
  9 Oct 2026): read-only IMAP access to **only the folders the owner ticks** (EXAMINE +
  BODY.PEEK — nothing marked read, moved or deleted), hourly or on "Check email". Booking and
  remittance emails (incl. PDF/text attachments) are kept in the inbox; everything else is
  skipped and not stored. Bookings are read (rules, or the assistant if on) and **verified
  against the Diary**: already booked → filed as verified, no action; booked but a different
  fee → "rate differs"; new → suggestion to check. Resumes by UID; app password encrypted.
  Microsoft 365 / NHSmail OAuth is not supported yet (💭).
- ✅ "Prepare all outstanding invoices for September" → drafts made by the deterministic
  engine from confirmed sessions; inconsistent rates are flagged. (B)
- ✅ Draft invoice emails and polite reminders in the right tone; always reviewed and sent with
  one tap by the owner. (B, F)
- ✅ Structured outputs validated by backend schemas; every proposal is audit-logged.

### Phase 3 — Administrative agent — ✅ (v2.x, Oct 2026)
- ✅ **Ask Locuvi** (`assistant/agent.py`, `/ask`, sparkle icon when the assistant is on):
  tool-calling agent over controlled service functions — `get_overview`, `run_checks`,
  `list_practices`, `list_sessions`, `find_uninvoiced_sessions`, `list_invoices`,
  `get_invoice`, `financial_summary`, `pension_overview`, `pension_month`, `list_documents`,
  `read_document` (inbox only, minimised), `bank_payments_to_match`, plus two draft-only tools:
  `prepare_invoice_draft` (no number; owner issues) and `draft_email` (invoice email or polite
  reminder; never sent). Strict tool schemas, no forced tool choice, adaptive thinking echoed
  unchanged, server-side refusal fallback (with the documented echo rule), step limit, every
  call logged on the conversation and in the audit log. Follow-up questions keep context.
- ✅ "Check all outstanding administrative work" → runs the checks engine and explains,
  prioritised, separating records from assumptions. (Spec 3)
- ✅ Payment and pension questions answer from the deterministic bank matcher, Form A
  tracking and PCSE comparison (Spec C, D); it never claims a submission was accepted.
- ✅ Questions in plain language over your records ("Which practices still owe me money?").
  Figures come from the services, never from AI estimates. (G)
- ✅ Correspondence log (emails sent/received per invoice) as further context. (F)

### Phase 4 — Extended integration — 🔜 partly done (v3)
- ✅ **Bevro integration** (`api/mcp.py`, Settings › Connected agents): Locuvi is an **MCP
  server** at `/mcp` (JSON-RPC over streamable HTTP; `initialize`, `tools/list`,
  `tools/call`, `ping`, batches). Same tools as Ask Locuvi. Each connection gets a bearer
  token (shown once, SHA-256 stored, revocable, last-used shown); **read-only by default**,
  "allow drafts" adds only the two draft tools — nothing can issue, send, pay or submit.
  Browser-origin requests are refused; every call is audit-logged with the connection name.
  Verified with the official MCP Python client.
- ✅ Email connector: read-only IMAP of chosen folders (see Phase 2 › Email folders).
- ✅ Better document processing: scanned PDFs and photos are read by the assistant when on.
- ✅ Scheduled review: optional Monday brief written by the agent (Settings › Assistant), at
  the top of the weekly digest email; the rule-based list stays underneath as the record, and
  any AI failure falls back to the plain digest.
- 💭 Calendar connector (bookings from a calendar feed).
- 💭 Microsoft 365 / NHSmail OAuth for the email connector.
- 💭 Optional local models for maximum privacy (the provider interface is ready).
- 💭 Controlled execution of workflows the owner has approved in advance.

### Privacy guardrails (binding for every AI item)
Explicit opt-in. Minimum data per request. Never send secrets (bank, WebDAV, SMTP, API keys) or
patient-identifiable information. Narrowly scoped integrations. No LLM in any calculation.
Issued invoices stay immutable. AI suggestions are visibly marked as suggestions. Every proposal
can be rejected. A full audit trail. Check the AI provider's data-processing terms (UK GDPR)
before enabling a cloud model.

## How to use this file
- Before starting work, pick the next 🔜 item with the owner; move it to ✅ when merged,
  with a link to the PR/commit and any ADR.
- New ideas go under "Later ideas" first; the owner decides when they become a version.
