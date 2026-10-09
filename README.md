# Locuvi

**Every session accounted for.** — personal, self-hosted GP locum management (v1.0).

Tap the days you worked in a calendar. Locuvi remembers each practice's rate, tells you when a
month is ready to invoice, adds the NHS employer pension contribution, issues an immutable A4
PDF, emails it from your own address, tracks payment, prepares your monthly GP Locum A/B
pension figures and gives your accountant a tax-year pack — all on your own server.

Designed to feel like *"it just works"*: few fields, sensible defaults, drafts that save
themselves, Undo instead of "Are you sure?" (see [ADR 0005](docs/decisions/0005-v1-full-app-and-design.md)).

It is single-user software for one UK self-employed GP. It is not a SaaS, it never submits
pension forms or sends anything without you tapping, and it is not an accounting package.

| Included | Not included |
| --- | --- |
| **Today**: what needs doing, one tap each | Multi-user, public hosting |
| **Diary**: tap-a-day sessions, remembered rates | Pension *submission* (worksheets only) |
| **Invoices**: one tap per month, immutable numbered PDF | VAT invoices (blocked if VAT registered) |
| Payments: mark paid with Undo, overdue detection | Credit notes (planned) |
| Email invoices via your SMTP account | Bank feeds, AI features |
| **Pension**: monthly Locum A/B figures + worksheet PDF | |
| **Reports**: tax year, CSV, year ZIP pack | |
| Nextcloud/WebDAV archive, backup/restore commands | |

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
`docker build --secret id=build_ca,src=/path/ca.pem -t locuvi:1.0.0 .` then `docker compose up -d --no-build`.

### Data and volumes

| Volume | Contents |
| --- | --- |
| `locuvi-data` → `/data` | `locuvi.db` (SQLite, WAL) and `invoices/issued/{uuid}.pdf` — the authoritative records |
| `locuvi-keys` → `/keys` | `locuvi.key`: encrypts the stored WebDAV app password and signs sessions. Kept apart from `/data` on purpose |
| `./backups` → `/backups` | Backup archives written by `locuvi backup` |

Migrations run automatically at start. On every start Locuvi checks that each issued
invoice's PDF exists and matches its SHA-256; `/api/v1/health/ready` (and the container
health check) reports `degraded` if not.

## 2. First run

Sign in and a three-step welcome asks for **you** (name, address), **getting paid** (bank
details) and **your first practice** (name, address, usual session rate). That's all.
Everything else is optional and lives under the gear icon (**Settings**): numbering and
terms, pension rates and your employee tier, email, Nextcloud.

Check the pre-loaded 2026/27 employer rate (14.38% of 90% pensionable pay) against current
NHSBSA/PCSE guidance. When it changes, add a new dated rate in Settings → Pension.

## 3. A normal month

1. **Diary** — pick the practice and AM / PM / Full day / Hours, then tap the days you work.
   The rate is remembered per practice and session type. Tap a session to change it.
   Each tap can be undone.
2. **Today** — when a month's sessions are worked, it shows *"October is ready to invoice"*.
   Tap **Create invoice**, check the draft (it saves itself) and tap **Issue & download**.
   Issuing allocates the next number and freezes the invoice and its PDF — it can't be
   edited afterwards, only voided or duplicated.
3. **Send** it from the invoice page (after a one-time email setup) or download the PDF.
4. When the money arrives, tap **Mark paid** (on Today or the invoice) — or import your bank
   statement (Invoices → **Payments in** → Import statement, CSV) and tap **Confirm N
   matches**. Only money in is kept. Overdue invoices rise to the top of Today.
5. **Pension** — after the month ends, open it to see the Form A figures per practice and the
   Form B summary, download the worksheet, copy the figures onto the official NHSBSA forms,
   track each practice's Form A (*To send → Sent → Signed*), then tap **Mark submitted**.
   Later, type in or import (CSV) what PCSE shows and Locuvi flags any difference.
6. **Reports** — tax-year totals any time; at year end download the CSV or the ZIP pack for
   your accountant.

**Phone calendar.** Settings → Phone calendar → turn on and tap **Subscribe**: booked sessions
appear in your calendar app and stay up to date (your phone must reach Locuvi on the home
network or Tailscale).

### Bookings and the inbox

Got a booking email? **Diary → Paste a booking**, paste it, tap **Read booking**. Locuvi lists
the sessions it found (date, AM/PM/day/hours, practice, fee) with anything odd flagged —
*already in your diary*, *clashes with another practice*, *cancellation*, *which practice?* —
and nothing is added until you tap **Add N sessions** (undo available). The **inbox** (tray icon,
top right) keeps booking emails, remittances, statements and pension forms: drop files on it
(PDF, images, .eml, text, CSV) or paste text; mark them done when dealt with.

**Email folders (optional).** Settings → Email folders connects to your mailbox over IMAP with
an app password and lists your folders; tick only the ones with locum mail (e.g. a "Locum"
label). Locuvi checks them hourly (or tap **Check email** in the inbox), read-only, keeps only
booking and remittance emails, and checks each booking against your diary: *already booked*,
*booked at a different fee*, or new sessions to add with one tap. Gmail, iCloud, Fastmail and
most providers work; Microsoft 365/NHSmail (OAuth only) does not yet.

**Assistant (optional, off by default).** Without AI, Locuvi reads common booking formats
itself. Settings → Assistant turns on an AI reader (Anthropic Claude) for free-form emails and
scanned PDFs/photos: paste an API key (stored encrypted) or mount one as a Docker secret and
set `ANTHROPIC_API_KEY_FILE`. Only the booking text, your practice names and today's date are
sent — lines about patients are dropped and email addresses, phone numbers, postcodes, NHS and
account numbers removed first; never passwords, bank details or invoices. A scan or photo can't
be redacted, so it is only sent after you approve that file. Refused requests are retried on a fallback model by the provider; the model used is
recorded with every suggestion. It only suggests — calculations never use AI. With the assistant on, the ✨ icon opens **Ask
Locuvi**: ask "Check all my outstanding admin", "Which practices still owe me money?" or
"Prepare invoices for last month" — it looks things up with Locuvi's own functions and can
prepare invoice drafts and email drafts, but never issues, sends, pays or submits.

**Bevro and other agents (optional).** Settings → Connected agents creates a token for your
agent platform. Point it at `http://<your Locuvi address>/mcp` (an MCP server; use the
private Tailscale/LAN address). Tokens are read-only unless you allow drafts, can be revoked,
and every call is in the audit log. See
[`docs/specs/AI_AND_AGENTS.md`](docs/specs/AI_AND_AGENTS.md).

**Credit notes.** If a practice has already booked an invoice and a session needs taking off,
open the invoice → More → **Issue credit note**, tick the lines and give a reason. It gets its own
number (CN-0001…) and PDF; the invoice itself never changes. What's owed, pension figures and
reports are reduced to match.

You can still create an invoice by hand (Invoices → New invoice). Pensionable lines in two
calendar months block issuing with a one-tap *Split by month*.

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
status with a *Retry* button. Invoices issued before you connected Nextcloud can be sent in
one go with **Settings → Storage → Archive past invoices**.

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

Locuvi backs itself up **every night after 02:00** into `./backups` (the `/backups` volume),
keeping 30 days (`BACKUP_KEEP_DAYS`). If a backup is missing or old, Today shows it with a
**Back up now** button. Each archive is a consistent snapshot (SQLite online backup + every issued
PDF + checksum manifest) and is refused if any issued PDF is missing or altered.

Archives contain bank details. To keep an **encrypted copy off the server**, give Locuvi a
backup passphrase (at least 12 characters, kept somewhere other than this server, e.g. your
password manager — without it the off-server copies cannot be read):
```bash
openssl rand -base64 24 > secrets/backup_passphrase.txt && chmod 600 secrets/backup_passphrase.txt
# then uncomment the two `backup_passphrase` lines in docker-compose.yml and:
docker compose up -d
```
Every backup is then encrypted (scrypt + AES-256-GCM, tamper-evident) and uploaded to your
Nextcloud under `Locuvi/Backups/` (`BACKUP_REMOTE_PATH`) using the WebDAV settings — never
overwriting a file and only counted once its SHA-256 matches. Locuvi does not delete old remote
copies; tidy them in Nextcloud when you like. After each backup a **restore drill** decrypts the
newest copy into a scratch folder and checks every PDF checksum, the database integrity and the
invoice count, without touching live data. Today shows it if the drill or the upload fails, or
if backups are still on this server only.

Run a drill yourself, or decrypt an off-server copy by hand:
```bash
docker compose exec locuvi python -m locuvi.cli drill                 # latest backup
python -m locuvi.cli decrypt locuvi-….tar.gz.enc out.tar.gz --passphrase-file pass.txt
```
Also keep a copy of the keys volume (separately, encrypted) if you store the WebDAV or email
password in the UI:
```bash
docker run --rm -v locuvi_locuvi-keys:/keys -v "$PWD/backups:/out" alpine tar czf /out/keys.tgz -C /keys .
```
Manual backup any time: `docker compose exec locuvi python -m locuvi.cli backup /backups/manual.tar.gz`.

Restore (verified against the manifest checksums before anything is written):

```bash
docker compose stop locuvi
docker compose run --rm --no-deps locuvi python -m locuvi.cli restore /backups/locuvi-2026-10-31-020000.tar.gz --force
# an encrypted .tar.gz.enc copy (e.g. downloaded from Nextcloud) restores the same way;
# the passphrase comes from the secret, or add --passphrase-file
docker compose up -d
docker compose exec locuvi python -m locuvi.cli verify     # prints {"ok": true, ...}
docker compose exec locuvi python -m locuvi.cli reset-password  # forgot the in-app password
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
# AI paths, against a local fake of the Anthropic API (start Locuvi with
# ANTHROPIC_BASE_URL=http://127.0.0.1:8901 after `python e2e/fake_anthropic.py 8901 &`)
BASE_URL=http://127.0.0.1:8000 LOCUVI_PASSWORD=... node e2e/assistant.mjs
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
