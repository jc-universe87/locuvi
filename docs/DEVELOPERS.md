# Developer notes

Technical notes for people changing Locuvi's code. Users don't need this; see the
[user guide](USER_GUIDE.md) and [setup guide](SETUP.md).

## Stack

| Part | Technology |
| --- | --- |
| Backend | Python 3.12, FastAPI, SQLAlchemy + Alembic, SQLite (WAL), ReportLab PDFs |
| Frontend | React + TypeScript + Vite; i18n in `frontend/src/i18n/` (English complete) |
| Tests | pytest, Vitest, Playwright end-to-end (`e2e/`) |
| Delivery | Docker image built and published by GitHub Actions (`.github/workflows/ci.yml`) |

Project rules (money as `Decimal`, issued invoices immutable, secrets never logged, fictional
fixtures only, AI never in calculations) are in [`CLAUDE.md`](../CLAUDE.md). Plain-English copy
rules are in [`PLAIN_ENGLISH_UX.md`](PLAIN_ENGLISH_UX.md).

## Run it locally

```bash
# Backend
cd backend && uv sync && uv run pytest && uv run ruff check .
APP_ENV=development DATA_DIR=../data KEY_DIR=../keys LOCUVI_AUTH_MODE=gateway \
  COOKIE_SECURE=false uv run uvicorn locuvi.main:create_app --factory --reload --port 8000

# Frontend (Node 22)
cd frontend && npm ci && npm run dev        # http://localhost:5173, proxies /api
npm test && npm run typecheck && npm run build
```

## End-to-end checks and screenshots

Against a **fresh** instance (needs Playwright and Chromium):

```bash
BASE_URL=http://127.0.0.1:8000 LOCUVI_PASSWORD=... node e2e/smoke.mjs

# AI paths, against a local fake of the Anthropic API: start it, then start Locuvi with
# ANTHROPIC_BASE_URL=http://127.0.0.1:8901
python e2e/fake_anthropic.py 8901 &
BASE_URL=http://127.0.0.1:8000 LOCUVI_PASSWORD=... node e2e/assistant.mjs

# Screenshots for the docs (run after the two above, on the same instance)
BASE_URL=http://127.0.0.1:8000 LOCUVI_PASSWORD=... SHOTS=./shots node e2e/docs-shots.mjs
```

The pictures in `docs/images/` come from `docs-shots.mjs` (fictional data only), resized and
reduced to 160 colours to keep the repository small. It also walks the second household
profile that `smoke.mjs` creates (`Sam`, password from `SAM_PASSWORD`, default the smoke
test's) through the welcome steps and a first month, so run it on a fresh instance.

## Database changes

Edit `backend/locuvi/models.py`, then `uv run python -m locuvi.migrate "message"`, rename the
new file to the next `NNNN_` prefix and replace `locuvi.models.*` column types with `sa.*`.
Locuvi backs up before migrating on start-up.

## AI providers

`backend/locuvi/assistant/providers.py` holds the provider catalogue (`PROVIDERS`).
Anthropic uses the official SDK; every other company goes through `CompatibleProvider`, an
OpenAI-style chat-completions adapter that returns Anthropic-shaped blocks so the agent loop
(`assistant/agent.py`) is shared. Adding a company that offers an OpenAI-compatible API is one
entry in `PROVIDERS`. Tests use fake HTTP transports only.

## Background reading

- [Roadmap](ROADMAP.md): what's done and what's next
- [Decisions](decisions/): why things work the way they do
- [AI and agents spec](specs/AI_AND_AGENTS.md)
- [Implementation report](IMPLEMENTATION_REPORT.md)
- [Original brief](handover/)
- Rounding: each line is rounded half-up to pennies; pensionable pay = 90% of the eligible
  basic fee, rounded; employer contribution = 14.38% of pensionable pay, rounded
  ([ADR 0003](decisions/0003-business-rules.md)).

## Configuration reference

`APP_ENV`, `DATA_DIR`, `KEY_DIR`, `STATIC_DIR`, `LOCUVI_AUTH_MODE`, `LOCUVI_PASSWORD_FILE`
(or `LOCUVI_PASSWORD`), `COOKIE_SECURE`, `SESSION_HOURS`, `ENCRYPTION_KEY_FILE`,
`WEBDAV_SECRET_FILE`, `WEBDAV_ALLOWED_PRIVATE_HOSTS`, `WEBDAV_ALLOW_HTTP_FOR_ALLOWLISTED`,
`WEBDAV_TIMEOUT_SECONDS`, `ARCHIVE_WORKER_ENABLED`, `ARCHIVE_WORKER_POLL_SECONDS`,
`BACKUP_DIR`, `BACKUP_KEEP_DAYS`, `BACKUP_REMOTE_PATH`, `BACKUP_PASSPHRASE_FILE`, `ANTHROPIC_API_KEY_FILE`,
`LOCUVI_AI_MODEL`, `LOG_LEVEL`. See `backend/locuvi/config.py`.
