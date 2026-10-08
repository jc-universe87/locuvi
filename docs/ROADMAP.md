# Locuvi roadmap

Living plan for Locuvi. **v0.1 = GP Locum Invoicing** (done). The long-term product is
**GP Locum Management**, built in small, verified steps.

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
| Nightly backup via cron + off-server encrypted copy | 🔜 | README §5; `locuvi.cli backup` |
| Restore drill on the real server (once) | 🔜 | `locuvi.cli restore` into a scratch volume, then `verify` |
| Merge working branch into `main`; deploy from `main` | 🔜 | Owner to approve PR |
| HTTPS on the intranet (Caddy internal CA or Tailscale serve) | 🧭 | Plain http on LAN is readable by others on that network |
| Connect Nextcloud (app password, allowlist if private) | 🧭 | Optional |
| Go-live check of rules against GOV.UK invoice requirements and NHSBSA/PCSE guidance | 🔜 | `docs/handover/SOURCES.md` |

---

## Part 3 — Product roadmap

### v0.1.x — Polish from real use — 🔜 next
Small fixes after issuing real invoices. Candidates already known:
- Native translations reviewed for DE/KO/FR/ES/PT (currently navigation only).
- "Upload all past invoices" to Nextcloud after enabling it (today: per invoice).
- Password change without editing the secret file; optional session timeout setting.
- Annual prefix helper (suggest `LOC-2027-` in January; never automatic).
- Automated test against a WebDAV server with an invalid TLS certificate.
- Keep the 2027/28 employer rate up to date (add a new effective-dated rate each April).

### v0.2 — Payments (getting paid) — 🧭
Original exclusion "payment tracking/reconciliation" — first module after v0.1.
- Mark invoice paid (date, amount, method/reference), part-payments, overdue view.
- Outstanding/aged-debt summary per practice; due-date reminders inside the app.
- Payment records are separate rows linked to the invoice; the issued invoice never changes.
- Credit notes for corrections (a proper document with its own number), replacing
  "void and reissue" where a practice has already recorded the invoice.

### v0.3 — Sending invoices — 🧭
Original exclusion "no automatic emailing in v0.1".
- Send the issued PDF to the practice's billing email (owner's SMTP or provider), with a
  sent-log on the invoice. Always a deliberate click; no automatic sending.
- Optional polite payment-reminder email (owner-approved text, owner-triggered).

### v0.4 — NHS pension Forms A/B — 🧭
Original exclusions "pension Forms A/B, PCSE uploads"; architecture says to link work-item
IDs to Form A/B. The per-date, per-line pensionable data needed is already stored.
- **Locum A** (monthly, per practice): generated from issued pensionable lines of that month.
- **Locum B** (monthly summary across practices) built from the Locum A records.
- Track which invoices/lines went into which form; forms are immutable once generated.
- Exports in the formats NHSBSA/PCSE accept; no automatic submission without explicit
  owner action. Rules must be verified against current NHSBSA guidance before building
  and an ADR written. Issuing an invoice still never implies a pension submission.

### v0.5 — Session diary — 🧭
Original exclusion "no full session diary".
- Log sessions as booked/worked (practice, date, AM/PM/hours, agreed rate, pensionable).
- Month-end: turn worked sessions into draft invoices (one per practice per month).
- Optional calendar export (ICS) for booked sessions.

### v0.6 — Reporting & exports — 💭
- Income by month / tax year / practice; pension contributions summary.
- Structured exports (CSV/JSON) for the owner's accountant — exports only, no accountant
  portal (original exclusion "accountants").
- Year-end pack: all issued PDFs + summary for a tax year.

### Later ideas — 💭
- Bank statement import (CSV/OFX) to suggest payment matches — owner confirms each match;
  no live bank connection by default.
- Assistant/agent actions (the handover's "AI agent/Bevro actions"): drafts and
  suggestions only, every action confirmed by the owner, never issuing or sending alone.
- VAT-registered invoices, only if the owner becomes VAT registered and an accountant
  confirms the treatment (currently blocked by design).
- PostgreSQL migration path if SQLite ever becomes a limit (unlikely for one user).

### Out of scope — ⛔
Multi-user/team accounts, SaaS/public hosting, OOH/SOLO/salaried GP payroll, tax
calculation/self-assessment filing, analytics/tracking, patient or medical data of any kind.

---

## How to use this file
- Before starting work, pick the next 🔜 item with the owner; move it to ✅ when merged,
  with a link to the PR/commit and any ADR.
- New ideas go under "Later ideas" first; the owner decides when they become a version.
