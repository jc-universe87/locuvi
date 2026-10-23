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
| Off-server encrypted copy of `backups/` | 🔜 | Built in: create `secrets/backup_passphrase.txt` and enable it in compose (docs/SETUP.md, Backups) |
| Restore drill on the real server (once) | 🔜 | `locuvi.cli restore` into a scratch volume, then `verify` |
| Merge working branch into `main`; deploy from `main` | ✅ | PR #1 merged 9 Oct 2026 |
| One-command updates: image published to GHCR on every green push to `main`; `./update.sh` (or `docker compose pull && docker compose up -d`); automatic backup before any database upgrade | ✅ | README "Updates"; one-time `docker login ghcr.io` (repo is private) |
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
  credit notes (SVG kept as a sanitised vector, or PNG/JPEG/WebP cleaned: metadata dropped, empty edges trimmed, resized; kept in
  the database so backups cover it), accent colour from print-safe presets, one-line footer on
  every invoice page, email sign-off for drafted emails, sample-invoice preview. Frozen into each
  issued snapshot (`presentation`), so issued documents never change (migration 0018).
- ✅ Rates (owner request): each practice is paid per **session** or per **hour** (hourly
  rate + usual hours; the Diary opens on the practice's pay type), and the NHS employer
  pension is either **added on top** or **included in the rate**. Included rates are really
  calculated now: basic fee = agreed rate ÷ (1 + 90% × employer rate), rounded to the penny,
  then the normal rules; the agreed rate is kept on the session, invoice line, snapshot and
  PDF note, and any penny rounding against the agreed total is shown before issuing
  (migration 0019). A session rate is never used as an hourly rate.
- ✅ Plain-English en-GB wording across the app (`docs/PLAIN_ENGLISH_UX.md`) and native DE/ES/FR/KO/PT
  translations of the main screens, with dates in the chosen language (Oct 2026).
- 🧭 Translate the remaining ~40% (mostly error messages and the newest screens: rates,
  invoice appearance), and re-check older translations against the new English wording.
- ✅ Password change without editing the secret file (Settings › Password): scrypt hash in the
  database overrides the secret file; changing it signs out every other device (session epoch);
  `python -m locuvi.cli reset-password` falls back to the secret file if forgotten.
- ✅ Guardrails against accidental deletion (owner request, "Confirm + 30-day bin"): every
  delete asks first, naming what goes (shared `useConfirm` sheet, Cancel focused, Escape
  cancels), then keeps a copy in **Settings › Recently deleted** for 30 days with Restore
  (`services/trash.py`, `trash_item` table, migration 0023; purged nightly by the scheduler).
  Covers diary sessions (one entry per undone series), draft invoices (lines, history and
  linked sessions — only still-unbilled sessions are re-linked), payments and refunds,
  pension rates, "Form B submitted" marks, inbox files and email accounts. Restores refuse
  clearly on conflicts (already booked, overpaying, rate or month taken again). Issued
  invoices and credit notes are still never deleted (void only).
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
  **Account presets** (Gmail with app password; Outlook/Hotmail/Microsoft 365 and NHSmail via
  Microsoft sign-in, `services/mail_microsoft.py`; owner request 9 Oct 2026): device-code
  sign-in with the owner's own app registration, Graph with `Mail.Read` only, GET requests
  only, refresh token encrypted and rotated, per-folder delta links (messages filed later are
  still read). NHSmail needs its administrators' approval of
  the app; until then, forwarding booking emails to Gmail is the documented route
  (`docs/EMAIL_SETUP.md`). **Several accounts** (owner request 9 Oct 2026): each with its
  own type, folders, progress and status; one failing account doesn't stop the others;
  remove with undo (kept in Recently deleted, purged with its secrets after 30 days).
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
- ✅ Microsoft 365 / NHSmail sign-in for the email connector (read-only; see Email folders).
- ✅ Optional local models for maximum privacy: **Your own server** (any OpenAI-compatible
  API, such as Ollama or LM Studio), 18 Oct 2026.
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

## Household profiles (owner request, 9 Oct 2026) ✅

- Separate Locuvi per person: own database and files (`profiles.py`; profile 1 stays in
  `DATA_DIR`, others in `DATA_DIR/profiles/<id>`), selected per request from the signed-in
  session (`db` context variable); hourly jobs, archive workers, backups, Bevro tokens and
  calendar links all work per profile.
- The first user (the existing owner) is the admin: adds, renames, resets passwords of and
  removes profiles (removal is restorable for 30 days). Sign-in asks for a name once there is
  more than one profile.


## Choice of AI company and plain-English manuals (owner request, 10 Oct 2026) ✅

- Settings › Assistant: choose Anthropic (Claude), OpenAI, Google Gemini, DeepSeek, Mistral,
  xAI (Grok) or OpenRouter, with the owner's own API key and an optional model; **Check key**
  lists the models the key can use. Non-Anthropic companies use one OpenAI-compatible adapter
  (`assistant/providers.py`); switching company forgets the saved key. Migration 0024.
- Documentation rewritten for non-technical readers with current screenshots:
  `README.md`, `docs/USER_GUIDE.md`, `docs/SETUP.md`, `docs/EMAIL_SETUP.md`,
  `docs/AI_SETUP.md`, `docs/DEVELOPERS.md`; pictures come from `e2e/docs-shots.mjs`.
- Repository checked for personal data before going public: fictional fixtures only.

## Public-release documentation (owner request, 17 Oct 2026) ✅

- Documentation prepared as for a public release: a full user manual (every screen, a normal
  month, settings one by one, FAQ, glossary), setup guide with hosting options, email guide
  for reading **and** sending, AI guide, privacy page, troubleshooting by message, docs index,
  `SECURITY.md`, `CHANGELOG.md`, `CONTRIBUTING.md` and an AGPL-3.0 `LICENSE` (with a
  "Source code" link in Settings, as the AGPL expects for network use).
- Screenshots extended (welcome steps, first month, issue check, practice sheet, settings),
  UK date formats.
- Fixes found while documenting: the scan-to-AI warning now names the chosen AI company; the
  weekly-brief hint points to Settings › Email invoices.

## More AI companies (owner request, 18 Oct 2026) ✅

- Added Cohere (Command), Alibaba (Qwen), Moonshot AI (Kimi), Z.ai (GLM)
  and MiniMax through the OpenAI-compatible adapter; each company carries its country, model
  list and price list links (shown in Settings › Assistant and docs/AI_SETUP.md), its JSON
  mode, and whether it supports tools (Ask Locuvi) and a model list (else Check key sends one
  tiny request). `<think>` reasoning in answers is stripped.
  Perplexity was tried and left out (its chat endpoint is being retired). The same day:
  **Your own server** (`custom`): owner-entered OpenAI-compatible address (migration 0025),
  optional key, compose maps `host.docker.internal` for a model on the same computer.

## Email, pension guide, calendar and Inbox (owner requests, 22 Oct 2026) ✅

- Sending email checked end to end against real TLS mail servers (STARTTLS 587 and SSL 465,
  with login) in `tests/test_mail_real_smtp.py`; messages now carry a Date header, and an
  unknown server name has its own plain message.
- Pension page: **How to send your pension forms**, a step-by-step guide to Forms A and B on
  PCSE Online with official links (`components/PensionGuide.tsx`).
- Booking emails: relevance is scored (`mailbox.relevance`), ignoring header dates and quoted
  replies and counting newsletters and auto-replies against; earlier junk is tidied to
  Recently deleted on the next scan.
- Calendar: subscribe buttons for Apple, Google, Outlook.com and Microsoft 365; one-off
  `.ics` and `.csv` downloads of every session.
- Inbox: next item after **I've dealt with this**, tick boxes and batch actions
  (`POST /documents/batch`), a second tick for deleting several, **I've dealt with all**.
- Documentation: [the first-time GP locum's handbook](LOCUM_HANDBOOK.md).

## Pension reminders and form links (owner request, 22 Oct 2026) ✅

- Opt-in email reminders before NHS pension deadlines (`services/pension_reminders.py`,
  migration 0026), built on the Today checks: Form B 5 days before the 7th and when late, the
  10-week limit 2 weeks before and when passed, Form A waiting more than 2 weeks for a
  signature. Each sent once; at most one email a day from 08:00.
- Pension months link to PCSE Online and to the checked NHSBSA paper forms for the scheme year
  (`lib/pensionForms.ts`), falling back to NHSBSA's forms page.
- Not done, and why: PCSE Online has no public interface, so Locuvi can't read form status.
  Recognising PCSE notification emails, and checking the PCSE statement import against PCSE's
  real CSV, both wait for a real sample.

## Apps for computer, phone and tablet (owner request, 22 Oct 2026) ✅

- Windows and macOS desktop app (`desktop/`): the whole Locuvi on the computer, own window,
  automatic sign-in, optional phone access over home Wi-Fi. Android WebView app
  (`mobile/android/`). iPhone and iPad through Add to Home Screen. Same features everywhere.
- `release.yml` builds, installs and tests each app on its own system, then publishes a
  release; the README links to `releases/latest/download/…`.
- Not done, and why: no App Store or Play Store listing, and no Apple or Microsoft code
  signing (each needs a paid developer account). No Intel Mac build: GitHub's Intel Mac
  runners are being retired.

## Sync, one-file export and full Locuvi on phones (owner requests, 22 Oct 2026)

- ✅ Sync core (`locuvi/sync/`): each device keeps its own copy; three-way merge row by row
  (issued invoices never go back, numbering only forwards, natural keys folded); encrypted
  sync folder (state + write-once files) in a cloud app's folder or Nextcloud; a write only
  lands on the copy it read; numbering lease before issuing ("sync before issuing", owner's
  choice); saved passwords travel with the household key; one-file export/import.
- ✅ Full Locuvi on phones and tablets, offline (owner's choice): the backend in Pyodide
  (`locuvi/pocket.py`, `frontend/src/pocket/`), bundled in the Android app and published for
  the iPhone/iPad Home Screen on GitHub Pages; CI runs the full UI smoke test on it. Email,
  Nextcloud copies, calendar subscriptions and agent connections stay on a computer.
- ✅ Nextcloud sync on phones and tablets (owner request, 23 Oct 2026): sync keeps its own
  Nextcloud details (address, optional home network address with failover, user, app
  password); the phone engine connects through `locuvi/webdav/browser.py` (the Android app
  makes the connection natively, `Net.java`; iPhone/iPad through the browser, which needs the
  Nextcloud to allow `https://locuvi.pistio.co.uk` by CORS). Tested end to end in CI against a
  stand-in Nextcloud, in a browser and in the Android app on an emulator.
- 🔜 Dropbox, OneDrive and Google Drive accounts directly (needed on phones, which have no
  synced folder), with step-by-step app registration for the owner.
