# CLAUDE.md — Locuvi

Personal, single-user GP locum invoicing app. v0.1 scope = invoicing + Nextcloud/WebDAV archive
only. The original brief is in `docs/handover/` (read `docs/handover/CLAUDE.md` first);
interpretations are in `docs/decisions/`. Do not expand scope (no Forms A/B, email, payments,
VAT invoices) without the owner asking.

## Layout
- `backend/locuvi/` FastAPI app: `money.py` (Decimal rules), `services/invoices.py` (draft,
  analyse, issue, void, split), `pdf/render.py` (ReportLab A4), `webdav/` (urlguard, client,
  archive queue/worker), `api/` (routes, auth, schemas), `migrations/` (Alembic), `cli.py`.
- `frontend/src/` React + TS: `pages/`, `components/ui.tsx`, `i18n/` (en is the complete
  reference catalogue), `lib/` (api, format, types).
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
