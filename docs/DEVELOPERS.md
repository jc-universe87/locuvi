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

## Desktop and mobile apps

All the apps show the same web app; nothing is reimplemented per platform.

- **Desktop** (`desktop/`): `locuvi_desktop.py` starts the FastAPI app in a thread on
  `127.0.0.1` (port 8765 if free), with records in the user's app-data folder. It opens an
  Edge or Chrome app window (falling back to the default browser) on
  `/desktop/open?token=…`, which signs in the single profile with a per-launch token. Phone
  access (`/api/v1/desktop`) binds `0.0.0.0` after a restart and needs the owner's own
  password. PyInstaller recipe: `locuvi.spec`; Windows installer: `windows/locuvi.iss`
  (Inno Setup).
- **Android** (`mobile/android/`): one Java activity with a WebView, no AndroidX. It adds
  `window.LocuviNative` (`frontend/src/lib/native.ts`) for downloads, plus file choosing,
  outside links and `locuvi://connect?server=…`.
- **iPhone/iPad**: the web app's manifest and icons (`frontend/public/`).

Build and test locally:

```bash
(cd frontend && npm ci && npm run build)
cd desktop && pip install ../backend pyinstaller && pyinstaller --noconfirm locuvi.spec
./ci-test.sh dist/Locuvi/Locuvi "$PWD/build/test"   # selftest.py + the full e2e smoke test
gradle -p mobile/android assembleRelease            # needs the Android SDK
```

`.github/workflows/release.yml` builds each app, installs and tests it on Windows, macOS
(arm64) and an Android emulator, and publishes a GitHub release with
`Locuvi-Windows-Setup.exe`, `Locuvi-macOS.dmg` and `Locuvi-Android.apk` when run by hand or
for a `v*` tag. Pull requests touching `desktop/` or `mobile/` only build and test.

To make every Android release installable over the previous one, add the repository
secrets `ANDROID_KEYSTORE_BASE64` (a base64-encoded keystore), `ANDROID_KEYSTORE_PASSWORD`,
and optionally `ANDROID_KEY_ALIAS` (default `locuvi`) and `ANDROID_KEY_PASSWORD`. Without
them each build is signed with a fresh debug key. Never commit a keystore.

The apps aren't signed with Apple or Microsoft certificates, so macOS and Windows warn on
first run (see `docs/APPS.md`).

## The phone app (Pyodide)

`npm run build:pocket` builds the web app with `VITE_POCKET=1` into `frontend/dist-pocket/`
and `pocket/assemble.mjs` adds Pyodide, Locuvi's wheel and the pure-Python wheels it needs
(`python frontend/pocket/deps.py DIR` gathers them: Pyodide's own builds where it has them,
otherwise the versions in `backend/uv.lock`). In that build `lib/api.ts` sends requests to a
Web Worker (`src/pocket/engine.worker.ts`) that runs `locuvi.pocket.handle` instead of the
network; records live in IndexedDB (IDBFS), copied after every change and when the app is
hidden. No threads and no sockets there: FastAPI's thread hand-offs run inline, background
workers are off, and email/Nextcloud/feeds are set up on a computer.

```bash
python frontend/pocket/deps.py /tmp/pocket
(cd frontend && PYODIDE_DIR=/tmp/pocket/pyodide POCKET_WHEELS=/tmp/pocket/wheels npm run build:pocket)
(cd frontend/dist-pocket && python -m http.server 8790) &
POCKET=1 BASE_URL=http://127.0.0.1:8790 node e2e/smoke.mjs && node e2e/pocket-keeps.mjs
```

The Android app bundles `dist-pocket` in `assets/www` and serves it from
`https://app.locuvi.local` (`MainActivity.asset`). GitHub Pages serves the same build for
iPhone and iPad at `https://locuvi.pistio.com/` (custom domain set in the repository's Pages
settings; DNS: a CNAME `locuvi` → `jc-universe87.github.io`, DNS only). Its own subdomain
gives the app its own browser storage, separate from any other site. The service worker
keeps it for offline use.

## Sync

`locuvi/sync/merge.py` merges two SQLite databases row by row against the last agreed copy
(three-way); `engine.py` reads and writes the encrypted sync folder (`state.lcv` +
`blobs/`), takes the numbering lease before issuing, and does the one-file export.
Every table is either synced or listed in `merge.LOCAL_TABLES`; a test fails when a new
table is neither, so decide which when you add one. Two devices end to end:

```bash
# two fresh desktop apps whose HOME has a Dropbox folder
HOME=/tmp/s/home python desktop/locuvi_desktop.py --headless --data-dir /tmp/s/a --port 8781 --info-file /tmp/s/a.json &
HOME=/tmp/s/home python desktop/locuvi_desktop.py --headless --data-dir /tmp/s/b --port 8782 --info-file /tmp/s/b.json &
OPEN_A=… OPEN_B=… node e2e/sync.mjs    # the "open" links from the two info files
```

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
