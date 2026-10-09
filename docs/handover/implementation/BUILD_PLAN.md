# Execution plan for Claude Code

## Phase 0 — repository hygiene
Inspect environment and any pre-existing files. Establish monorepo layout `backend/`, `frontend/`, `tests/`, `docs/`, Docker/compose, lockfiles, `.gitignore`. Document constraints and relevant assumptions. No real user information in fixture data.

## Phase 1 — core accounting engine
Implement database migrations/entities, Decimal fee/pension calculations, issuer snapshot and transaction-safe invoice numbering, domain tests. Guard multi-month eligible work. Provide fictional example.

## Phase 2 — PDF and local persistence
Build clean A4 template, PDF snapshot generation, crash-safe issue transaction, immutable local artifacts, index/search/duplicate/void, regression tests for PDF and number uniqueness.

## Phase 3 — WebDAV archive
Server-side config/secret strategy, connection test, target naming, safe remote path creation, upload/verify, durable retry queue/status, collision protection, network failure tests. Existing invoice still downloadable when remote down.

## Phase 4 — UI
Three-page navigation, settings/practices, responsive invoice editor, previews, totals, PDF actions, archive status and retry button; minimal colour/token system and i18n keys.

## Phase 5 — hardening
Unit/integration/e2e tests, Docker up/smoke/restart, failure injection, PDF visual verification, responsive/accessibility checks, threat modelling (SSRF/auth/secrets), backup/restore walkthrough, README and implementation report.

## Delivery order
Do not do Phase 4-only mockups or expand to full locum management. Implement a usable minimal vertical slice first and iterate. Commit logically if repository is under Git; never push to remote without user's instruction.

## Owner-provided details at runtime, not needed to scaffold
Legal invoicing identity/address, bank remittance details, practice address/contact/rates, initial invoice sequence, payment terms, WebDAV full URL/user/app password/folder, expected pensionable treatment and VAT status. Keep placeholders and setup UI rather than blocking build on missing details.
