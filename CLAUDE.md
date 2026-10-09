# CLAUDE.md — Locuvi

Personal, single-user GP locum management app (v1.0): diary, invoicing, payments, email,
pension A/B worksheets, reports, Nextcloud archive. Design principle: Apple-style "it just
works" — minimal fields, smart defaults, autosave, undo instead of confirm (ADR 0005). The original brief is in `docs/handover/` (read `docs/handover/CLAUDE.md` first);
interpretations are in `docs/decisions/`; the plan is `docs/ROADMAP.md` (update it when a
roadmap item ships); the AI/agent spec is `docs/specs/AI_AND_AGENTS.md` (AI optional, proposes
only, never in calculations, owner approves every consequential action). Do not expand scope beyond the roadmap without the owner asking;
never submit pension forms or send email without an explicit owner tap.

## Layout
- `backend/locuvi/` FastAPI app: `money.py` (Decimal rules), `services/invoices.py` (draft,
  analyse, issue, void, split), `services/diary.py`, `services/payments.py`,
  `services/pension.py`, `services/reports.py` (+ Today overview), `services/checks.py`
  (findings), `services/documents.py` (inbox), `services/proposals.py` (suggest → accept/undo,
  audit), `services/mailbox.py` (read-only IMAP, chosen folders only),
  `services/bank.py` (CSV statement → credits only → deterministic matches), `assistant/` (`rules.py` booking reader, `providers.py` optional LLM), `mail.py` (SMTP),
  `pdf/render.py` + `pdf/pension.py` (ReportLab A4), `webdav/` (urlguard, client, archive
  queue/worker), `api/` (routes, auth, schemas), `migrations/` (Alembic), `cli.py`.
- `frontend/src/` React + TS: `pages/` (Today, Diary, Inbox, Bank, Invoices, InvoiceEditor,
  InvoiceDetail, Pension, Reports, Settings, Welcome), `components/Booking.tsx` (paste + review), `components/ui.tsx` (sheets, toggles, segmented,
  toast+undo, autosave), `i18n/` (en complete; use `tn()` for counts), `lib/`.
- `e2e/smoke.mjs` Playwright UI smoke; `docs/` decisions, report, example PDF.

## Commands
- Backend: `cd backend && uv run pytest && uv run ruff check . && uv run ruff format .`
- New migration: edit `models.py`, then `uv run python -m locuvi.migrate "message"`, rename the
  file to the next `NNNN_` prefix and replace `locuvi.models.*` column types with `sa.*`.
- Frontend: `cd frontend && npm test && npm run typecheck && npm run build`
- Docker: `docker compose up -d --build` (needs `secrets/locuvi_password.txt`).

## Rules that must not regress
- Never use float for money; amounts cross the API as decimal strings.
- Issued invoices are immutable: number, snapshot, PDF. No edit/delete; void keeps them.
- Issue stays a single `BEGIN IMMEDIATE` transaction with idempotency key; PDF failure must
  not consume a number.
- Local DB + PDF are authoritative; WebDAV never decides issue state, never overwrites
  different remote content, never claims `synced` without SHA-256 verification.
- Secrets (owner password, app password, bank account) never in logs, API responses (masked)
  or git. Test only against disposable WebDAV servers, never the owner's live Nextcloud.
- All UI text through i18n keys in `frontend/src/i18n/en.ts` (tests enforce this).
- Fictional data only in fixtures (`example.invalid`, `00-00-00`, `00000000`).
- Tests never call a real AI API (fake provider / fake SDK client). AI output is re-validated
  server-side and only becomes data through `proposals.accept`.
