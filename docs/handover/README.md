# Locuvi — Complete Claude Code Handover

**Version:** Concept handover v1.0 (8 October 2026)  
**Product:** Locuvi — *Every session accounted for.*  
**Owner/use:** Personal, single-user, self-hosted GP locum invoicing software. NOT a public commercial product.

## Start here
1. Read `CLAUDE.md`, then all `specs/`, `design/` and `engineering/` documents before modifying code.
2. Execute `implementation/BUILD_PLAN.md` sequentially; the **first release is invoicing only**.
3. Preserve the explicit acceptance tests in `implementation/ACCEPTANCE.md`.
4. Use fictional data for development. Ask for actual bank details and WebDAV credentials only in the running application/configuration; never in commits.

## Files
- `CLAUDE.md` — master implementation instruction
- `specs/PRODUCT.md` — purpose, workflows, boundaries
- `specs/INVOICES_AND_PENSIONS.md` — invoice and pension fee rules
- `specs/NEXTCLOUD_WEBDAV.md` — required Nextcloud/WebDAV storage integration
- `design/BRAND.md` — name, style, colours and typography
- `design/UX.md` — screen and PDF layouts
- `engineering/ARCHITECTURE.md` — architecture, security, data and operations
- `engineering/DATA_MODEL.md` — proposed entities and fields
- `engineering/API.md` — proposed REST endpoints
- `implementation/BUILD_PLAN.md` — build sequence
- `implementation/ACCEPTANCE.md` — quality gates/test matrix
- `examples/.env.example` — illustrative non-secret configuration
- `examples/invoice-fixture.json` — fictional data and example totals
- `SOURCES.md` — external guidance for verification

## Status
This bundle is a **specification and handover**, not a working codebase. Claude Code owns implementation from scratch. No production credentials or source code are bundled.
