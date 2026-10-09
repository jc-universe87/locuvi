# Architecture and operations

## Proposed stack
- Python 3.12+ FastAPI + SQLAlchemy 2 + Alembic + Pydantic
- SQLite initially, WAL mode and busy timeout; transactional sequencing; database migration path to PostgreSQL if needed
- React + TypeScript + Vite, lightweight component system and CSS variables (Tailwind optional)
- PDF via WeasyPrint or ReportLab; choose after font/packaging smoke test
- HTTPX for server-side WebDAV and controlled retry worker
- Docker Compose with non-root service and named/bind persistent volumes
- pytest backend, UI tests with Vitest/Testing Library, optional Playwright smoke

Single app container with built static frontend is acceptable; background archive retry may use lightweight worker loop in the same deployment if reliable, or a separate service. Keep one database writer strategy sound with SQLite.

## Local persistence
Persist `/data/locuvi.db`, `/data/invoices/issued/{invoice_uuid}.pdf`, and backups separately. PDF write to temp, fsync/rename; checksum SHA-256; record snapshot, issue timestamp, content checksum. Crash recovery checks consistency of issued rows and files. Strong idempotency safeguards.

## Audit and secrecy
Audit invoice issue/void and archive attempts without storing secrets in logs. Personal/bank and WebDAV config handled server-side. Disable debug and unsafe CORS in production. Bind Docker only to `127.0.0.1` if proxied, or Tailscale-only interface; no internet publishing required. Document TLS/proxy setup; do not assume built-in TLS. Encrypt WebDAV UI-stored credentials using external application key or prefer mounted secret file.

## Backups
Local-only copy is insufficient. Back up SQLite with SQLite backup API/safe snapshots and immutable PDF files to separate storage on schedule. Test restore. WebDAV invoice PDFs are an **archive copy**, not database backup. Encrypt backups containing banking details.

## Packaging
Pin direct dependencies with a lockfile, document version requirements; healthcheck, logs, migrations on deploy, resource limits where practical. Provide `.env.example` and `docker-compose.yml` with empty non-secret placeholders only. Provide one-command startup, setup and data restore guide.

## Internationalisation
Do not hardcode visible strings. Use `i18n` keys from start. English fully implemented, design future additional translations EN/DE/KO/FR/ES/PT. Avoid mandatory six-language completion delaying first working single-user product.

## Future extensibility (NO implementation in v0.1)
Link work-item IDs to Form A/B, payments, reconciliations, AI agent/Bevro actions, optional structured exports. Avoid prebuilding that infrastructure.
