# Locuvi

**Every session accounted for.** — personal, self-hosted GP locum invoicing (v0.1).

Locuvi creates a GP locum invoice from a saved practice and dated work lines, adds the
NHS employer pension contribution where you mark work as pensionable, issues an
immutable A4 PDF with a unique sequential number, keeps the original forever on your
server, and can archive each issued PDF to your Nextcloud over WebDAV.

It is single-user software for one UK self-employed GP. It is not a SaaS, not a pension
submission tool and not an accounting package.

| v0.1 includes | Not in v0.1 |
| --- | --- |
| Owner/sender & bank details, practices | Pension Forms A/B, PCSE uploads |
| Draft → preview → issue (immutable number + PDF) | Emailing invoices, payment tracking |
| Employer pension addition (versioned rates) | VAT invoices (issuing is blocked if VAT registered) |
| Void with reason, duplicate, search/filter | Credit notes |
| Nextcloud/WebDAV one-way archive with retry | Two-way sync, OAuth, multi-user |
| Backup / restore / integrity commands | Bank integration, AI features |

The roadmap (what's done, what's next) is in [`docs/ROADMAP.md`](docs/ROADMAP.md).
The full brief is in [`docs/handover/`](docs/handover/). Decisions that interpret or deviate
from it are in [`docs/decisions/`](docs/decisions/). What was built and verified is in
[`docs/IMPLEMENTATION_REPORT.md`](docs/IMPLEMENTATION_REPORT.md). An example invoice made
from fictional data: [`docs/examples/example-invoice.pdf`](docs/examples/example-invoice.pdf).

---

## 1. Run it (Docker Compose)

Requirements: a Linux host with Docker Engine + Compose v2. By default Locuvi listens on
`127.0.0.1` only; reach it through Tailscale, or publish it on your LAN (see below).

```bash
git clone <this repository> locuvi && cd locuvi
cp .env.example .env                       # adjust if needed

# Owner sign-in password (a long passphrase). Stored as a Docker secret, not in git.
install -d -m 0700 secrets
( umask 022; printf '%s' 'choose-a-long-passphrase' > secrets/locuvi_password.txt )

# Directory for backup archives, writable by the container user (uid 10001)
sudo install -d -m 0700 -o 10001 -g 10001 backups

docker compose up -d --build
docker compose ps                          # wait for "healthy"
```

Open `http://127.0.0.1:8000` on the host (set `COOKIE_SECURE=false` in `.env` for plain
http on localhost), or publish it privately with Tailscale (recommended, gives HTTPS):

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:8000
# → https://<host>.<tailnet>.ts.net  (only devices in your tailnet can reach it)
```

Keep `COOKIE_SECURE=true` when serving over HTTPS. Do **not** use `tailscale funnel` or any
public port forward.

**Intranet (LAN) access**: publish on the server's LAN address instead of localhost:

```bash
# .env
LOCUVI_BIND=192.168.1.20     # the server's LAN IP (`hostname -I`); avoid 0.0.0.0
LOCUVI_PORT=8767
COOKIE_SECURE=false          # plain http on the LAN
```

Then `docker compose up -d` and open `http://192.168.1.20:8767` from any device on the
network. The owner password still protects the app, but plain HTTP on a LAN can be read
by others on that network — prefer a trusted home/office network, or put a TLS reverse
proxy (e.g. Caddy with an internal certificate) in front. Docker-published ports bypass
ufw/firewalld, so binding to the LAN IP (not `0.0.0.0`) and not forwarding the port on
your router are what keep it off the internet.

**Behind a TLS-intercepting proxy?** Pass its CA to the build only:
`docker build --secret id=build_ca,src=/path/ca.pem -t locuvi:0.1.0 .` then `docker compose up -d --no-build`.

### Data and volumes

| Volume | Contents |
| --- | --- |
| `locuvi-data` → `/data` | `locuvi.db` (SQLite, WAL) and `invoices/issued/{uuid}.pdf` — the authoritative records |
| `locuvi-keys` → `/keys` | `locuvi.key`: encrypts the stored WebDAV app password and signs sessions. Kept apart from `/data` on purpose |
| `./backups` → `/backups` | Backup archives written by `locuvi backup` |

Migrations run automatically at start. On every start Locuvi checks that each issued
invoice's PDF exists and matches its SHA-256; `/api/v1/health/ready` (and the container
health check) reports `degraded` if not.

## 2. First-time setup (in the app)

1. **Settings → Sender & bank details**: legal name, address, email, bank account name,
   sort code, account number. Shown on future invoices only; issued invoices keep the details
   they were issued with.
2. **Settings → Invoice numbering & terms**: prefix (default `LOC-<year>-`), next number,
   default payment terms. Numbers are only allocated at issue and are never reused. The
   prefix does not change automatically each year — edit it yourself in January if you
   want year-based prefixes.
3. **Settings → NHS employer pension contribution**: the 2026/27 rate (14.38% of 90%
   pensionable pay) is pre-loaded. Check it against current NHSBSA/PCSE guidance. Add a new
   effective-dated rate when it changes; existing rates are never edited.
4. **Practices**: add each practice with billing address and usual rate. Tick *"Agreed rate
   already includes employer pension"* only if the practice quoted an inclusive figure — Locuvi
   then warns before adding the contribution again.

## 3. Invoicing

**Invoices → New invoice** → choose practice → *Add next date* for each session → set
date, session type, rate and whether the line is **NHS pensionable** → the summary shows the
basic fee, pensionable pay (90%, for information), the employer contribution and the total,
calculated on the server with exact decimal arithmetic.

- *Save draft* / *Preview PDF* (watermarked, no number).
- *Issue & download* asks for confirmation, then in one transaction allocates the number,
  freezes a snapshot of all details, renders and stores the PDF. A double click or retry can
  never issue twice. The PDF downloads straight away and is always available from the
  invoice page — with or without Nextcloud.
- Pensionable lines in **two calendar months** block issuing; *Split by month* creates one draft
  per month. Non-pensionable lines across months are allowed with a warning.
- Issued invoices cannot be edited or deleted. *Void* (with a reason) keeps the number and
  the original PDF; *Duplicate* creates a new draft.

Rounding (see [ADR 0003](docs/decisions/0003-business-rules.md)): each line is rounded
half-up to pennies; pensionable pay = 90% of the eligible basic fee, rounded; employer
contribution = 14.38% of pensionable pay, rounded. £600.00 → £540.00 → £77.65 → total £677.65.

## 4. Nextcloud archive (optional)

1. In Nextcloud: **Personal settings → Security → Devices & sessions → Create new app
   password** (name it "Locuvi"). Never use your main password.
2. In Nextcloud **Files → ⚙ Files settings** copy the WebDAV URL, e.g.
   `https://cloud.example.org/remote.php/dav/files/USERNAME/`.
3. In Locuvi **Settings → Storage**: tick *Archive issued PDFs to Nextcloud*, paste the URL,
   username and app password, choose the folder (default `Locuvi/Invoices`), *Test
   connection*, then *Save*.

Files are stored as `Locuvi/Invoices/YYYY/MM/LOC-2026-0001.pdf` (number only, no practice
names). Uploads happen in the background after issue, are verified by downloading and
comparing SHA-256, and are retried automatically with backoff. Locuvi never overwrites a
different remote file (status **conflict**) and never deletes remote files. Wrong
credentials pause retries until you fix the settings; each invoice page shows the true
status with a *Retry* button.

**Private Nextcloud (Tailscale/LAN)**: by default only public HTTPS addresses are allowed
(SSRF protection). To allow your own private server, set in `.env`:
```
WEBDAV_ALLOWED_PRIVATE_HOSTS=nextcloud.your-tailnet.ts.net,100.64.0.0/10
# only if that server has no TLS (not recommended):
WEBDAV_ALLOW_HTTP_FOR_ALLOWLISTED=true
```
Alternatively supply the app password as a secret file instead of the UI: add a compose
secret mounted at `/run/secrets/locuvi_webdav_password` and set
`WEBDAV_SECRET_FILE=/run/secrets/locuvi_webdav_password`.

> The Nextcloud copy is an archive of PDFs, **not a backup** of Locuvi.

## 5. Backups and restore

Back up regularly to separate storage. Archives contain bank details — **encrypt them**.

```bash
# Consistent snapshot (SQLite online backup + issued PDFs + checksum manifest)
docker compose exec locuvi python -m locuvi.cli backup /backups/locuvi-$(date +%F).tar.gz

# Encrypt before it leaves the machine, e.g. with age or gpg
age -p -o locuvi-$(date +%F).tar.gz.age backups/locuvi-$(date +%F).tar.gz
# Also keep a copy of the keys volume (separately, encrypted) if you store the
# WebDAV app password in the UI:
docker run --rm -v locuvi_locuvi-keys:/keys -v "$PWD/backups:/out" alpine tar czf /out/keys.tgz -C /keys .
```

Restore (verified against the manifest checksums before anything is written):

```bash
docker compose stop locuvi
docker compose run --rm --no-deps locuvi python -m locuvi.cli restore /backups/locuvi-2026-10-31.tar.gz --force
docker compose up -d
docker compose exec locuvi python -m locuvi.cli verify     # prints {"ok": true, ...}
```

If the keys volume is lost, invoices are unaffected; re-enter the WebDAV app password and sign in again.

## 6. Security model (summary)

- Private by default: port bound to `127.0.0.1`; use Tailscale/VPN with HTTPS in front.
- Auth (`LOCUVI_AUTH_MODE`): `password` (default) — single owner password from a secret file,
  HttpOnly + SameSite=Strict signed session cookie, login rate-limited; or `gateway` — no
  in-app login, **only** when the gateway itself authenticates. Every state-changing request
  requires a CSRF header in both modes. See [ADR 0002](docs/decisions/0002-auth-model.md).
- Container: non-root (uid 10001), read-only root filesystem, all capabilities dropped,
  `no-new-privileges`, memory/pid limits, strict CSP and security headers, API docs disabled.
- The WebDAV app password is encrypted at rest (Fernet) with a key outside the database,
  never returned to the browser, never logged. Bank account numbers are masked in API views.

## 7. Development

```bash
# Backend (Python 3.12, uv)
cd backend && uv sync && uv run pytest && uv run ruff check .
APP_ENV=development DATA_DIR=../data KEY_DIR=../keys LOCUVI_AUTH_MODE=gateway \
  COOKIE_SECURE=false uv run uvicorn locuvi.main:create_app --factory --reload --port 8000

# Frontend (Node 22)
cd frontend && npm ci && npm run dev        # http://localhost:5173, proxies /api
npm test && npm run typecheck && npm run build

# UI smoke test against a running instance (needs playwright + chromium)
BASE_URL=http://127.0.0.1:8000 LOCUVI_PASSWORD=... node e2e/smoke.mjs
```

Configuration reference (environment): `APP_ENV`, `DATA_DIR`, `KEY_DIR`, `STATIC_DIR`,
`LOCUVI_AUTH_MODE`, `LOCUVI_PASSWORD_FILE` (or `LOCUVI_PASSWORD`), `COOKIE_SECURE`,
`SESSION_HOURS`, `ENCRYPTION_KEY_FILE`, `WEBDAV_SECRET_FILE`, `WEBDAV_ALLOWED_PRIVATE_HOSTS`,
`WEBDAV_ALLOW_HTTP_FOR_ALLOWLISTED`, `WEBDAV_TIMEOUT_SECONDS`, `ARCHIVE_WORKER_ENABLED`,
`ARCHIVE_WORKER_POLL_SECONDS`, `LOG_LEVEL` — see `backend/locuvi/config.py`.

## Important

Rates and rules must be checked against current NHSBSA/PCSE and GOV.UK guidance before
production use ([sources](docs/handover/SOURCES.md)). Issuing an invoice is not an NHS pension
submission. Locuvi does not decide VAT treatment; ask your accountant if unsure.

Fonts: Inter (SIL Open Font License 1.1, embedded in PDFs; licence in
`backend/locuvi/pdf/fonts/OFL-Inter.txt`) and Manrope (OFL, web UI via @fontsource).
