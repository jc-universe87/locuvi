# Locuvi roadmap

Living plan for Locuvi. **v0.1 = GP Locum Invoicing** (done). **v1.0 = GP Locum Management**
(done, 8 Oct 2026): diary, payments, email, pension worksheets, reports and the "it just works"
redesign (ADR 0005). Further work is driven by real use.

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
- 🧭 Credit notes (own number series) for corrections after a practice has booked an invoice.
- 🧭 Repeating bookings ("every Tuesday AM at X until December") in the Diary.
- 🧭 Calendar subscription (ICS) of booked sessions for the phone calendar.
- 🧭 Native review of DE/KO/FR/ES/PT translations (currently navigation only).
- 🧭 Password change without editing the secret file.
- 🧭 Each April: add the new employer rate and check your employee tier (Settings → Pension).

### Later ideas — 💭
- Automatic payment reminders (owner-approved text, still one tap to send).
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
