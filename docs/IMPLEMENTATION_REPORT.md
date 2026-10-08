# Locuvi v0.1 — implementation report

Date: 8 October 2026. Scope: `docs/handover/specs/PRODUCT.md` v0.1 (invoicing + Nextcloud/WebDAV
archive). All data used in development and tests is fictional.

## Verification performed

| Check | Result |
| --- | --- |
| Backend unit/integration tests (`cd backend && uv run pytest`) | **94 passed** |
| Backend lint (`ruff check`) | clean |
| Frontend tests (`npm test`) — formatters, i18n completeness, invoices page | **8 passed** |
| Frontend typecheck + production build | clean |
| UI smoke in Chromium (`e2e/smoke.mjs`), desktop + 390 px mobile | passed 3× against a local server, 1× against the Docker container |
| Docker image build (multi-stage, pinned) | built; runs as uid 10001, read-only rootfs |
| Docker restart: PDF downloaded before restart, after `restart`, after `down`/`up` | identical SHA-256 |
| Backup in container → restore into a **new** volume → `verify` | ok, checksums match |
| WebDAV in Docker against a disposable WsgiDAV container: issue while server offline → `failed: unreachable` (retry scheduled) → server back → worker syncs automatically, remote SHA-256 = local, folders created | passed |
| Container logs searched for owner password, app password, `Authorization`, account number | none found |

## Acceptance matrix (`implementation/ACCEPTANCE.md`)

### Invoice behaviour
| Criterion | Status | Evidence |
| --- | --- | --- |
| Identity, bank details and practice saved | ✅ | `test_api.py::test_key_acceptance_flow_and_restart`, UI smoke |
| Multiple dates in a month with differing rates | ✅ | `test_money.py::test_differing_rates_and_hours`, UI smoke (600 + 550) |
| Accurate subtotal, pensionable base, 14.38% addition | ✅ | `test_money.py` (stage-by-stage half-up tests) |
| £600 → £540 → £77.65 → £677.65 | ✅ | `test_money.py::test_handover_fixture_600` (reads the handover fixture), `/invoices/calculate` test |
| Non-pensionable line excluded | ✅ | `test_non_pensionable_line_excluded` |
| Pensionable lines across two months blocked / split offered | ✅ | `test_pensionable_multi_month_blocked_and_split`, API + UI smoke |
| Draft editable; preview has no number | ✅ | `test_preview_has_no_number` |
| Double-click / parallel issue cannot issue twice | ✅ | `test_parallel_issue_cannot_issue_twice` (8 threads), `test_parallel_issue_of_different_drafts_unique_numbers`, idempotent replay test |
| Snapshot/PDF unchanged after practice/bank edit | ✅ | `test_snapshot_and_pdf_unchanged_after_settings_edit` |
| PDF has invoice essentials; typography/page breaks | ✅ | `test_two_october_sessions_issue` (text checks), `test_multi_page_pdf_has_page_numbers`, visual check of `docs/examples/example-invoice.pdf` |
| Void keeps number and PDF; no delete | ✅ | `test_void_keeps_number_and_pdf`, `test_void_requires_reason_and_keeps_pdf` |
| Restart keeps records and exact PDFs | ✅ | API restart test + Docker restart check |

### WebDAV
| Criterion | Status | Evidence |
| --- | --- | --- |
| Feature off: issue/download normal | ✅ | `test_feature_off_issue_and_no_job`, API tests |
| Upload to selected hierarchy on a disposable server | ✅ | `test_upload_creates_hierarchy_and_verifies` (WsgiDAV), Docker drill |
| Folder hierarchy created | ✅ | same |
| No overwrite of different content | ✅ | `test_conflicting_content_never_overwritten`, `test_move_precondition_failed_race` |
| Retry recognises identical uploaded file | ✅ | `test_existing_identical_file_is_success`, `test_repeated_job_and_manual_reverify` |
| Bad credentials → clear state, invoice kept | ✅ | `test_wrong_password_pauses_and_keeps_invoice` |
| Offline → issue works, job retried, eventually syncs | ✅ | `test_offline_then_eventually_syncs`, API offline test, Docker drill |
| Interrupted upload / restart safe | ✅ | `test_restart_recovers_interrupted_upload`, `test_leftover_partial_upload_is_handled` |
| SSRF, URL/redirect validation, TLS verification | ✅ | `test_malicious_urls_blocked` (14 cases), DNS-to-private test, redirect not followed; TLS verify is hard-coded on (see limitations) |
| Secret never returned / logged | ✅ | `test_secret_never_returned_and_encrypted` (also checks raw DB bytes), API test, Docker log search |
| Status truthful, never falsely synced | ✅ | `test_never_marked_synced_without_verification` |

Also covered: timeouts, 429 with `Retry-After`, 500/503/507, 403, 302, change of destination folder, Unicode folder names, invalid folder names, disabled WebDAV suppressing processing.

### Deployment
| Criterion | Status | Notes |
| --- | --- | --- |
| Image builds with pinned dependencies | ✅ | `uv.lock`, `package-lock.json`, exact base-image tags |
| Tests pass and output documented | ✅ | this report |
| Private binding, non-root, debug off | ✅ | `127.0.0.1` port, uid 10001, `APP_ENV=production` disables docs |
| Persistent volumes with working restore | ✅ | backup/restore drill above |
| README for setup, app password, backup | ✅ | `README.md` |
| No secrets or real details committed | ✅ | fixtures use `example.invalid`, `00-00-00`, `00000000`; `secrets/`, `.env`, data ignored |

## Deviations and interpretations
See `docs/decisions/`. In short: ReportLab chosen over WeasyPrint (0001); explicit two-mode
auth with CSRF (0002); pension policy chosen by earliest pensionable date with a block if the
rate changes within the invoice, VAT-registered issuing blocked, no credit notes (0003);
number-only remote filenames and staged `MOVE Overwrite:F` uploads (0004).

## Not implemented (by design for v0.1)
Pension Forms A/B, emailing, payment tracking, bank/accountant integration, VAT invoices,
credit notes, multi-user, password-change UI, remote file deletion on void, bulk "upload all
past invoices" after enabling Nextcloud (use *Upload to Nextcloud* per invoice), scheduled
automatic backups (run the `backup` command from cron/systemd timer).

## Known limitations
- TLS verification is always on in code but has no automated test against a bad
  certificate (the tests use plain HTTP with an explicit allowlist).
- DNS-rebinding window between the SSRF resolution check and the connection (ADR 0004).
- Non-English catalogues (DE/KO/FR/ES/PT) cover navigation and common actions only and need
  native review; everything else falls back to English. The PDF is English (en-GB) only.
- Date inputs use the browser's native picker, whose display format follows the browser locale.
- Single process by design (SQLite + in-process worker); do not run multiple replicas.
- The 2026/27 contribution rate and the multi-month rule come from the handover and must be
  checked against current NHSBSA/PCSE guidance before real use.
