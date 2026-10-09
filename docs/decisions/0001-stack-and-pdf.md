# ADR 0001 — Stack, packaging and PDF engine

Status: accepted (v0.1)

## Decision
- Backend: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, HTTPX — as proposed.
- Database: SQLite with WAL, `synchronous=FULL`, busy timeout, foreign keys. Money and
  quantities stored as exact decimal TEXT through a `DecimalString` column type (never REAL).
- PDF: **ReportLab** (platypus) rather than WeasyPrint.
- Frontend: React 18 + TypeScript + Vite, plain CSS variables (no Tailwind), a ~60-line
  in-house i18n helper instead of a library.
- Packaging: one container, one uvicorn worker, archive worker as a thread in the same
  process; dependencies locked with `uv.lock` and `package-lock.json`, exact versions pinned.

## Why
- ReportLab is pure Python with wheels: no Pango/Cairo/system fonts in the image, which
  makes rendering identical between development, tests and Docker. Platypus gives
  repeated table headers, `KeepTogether` for totals (no orphaned totals) and a two-pass
  canvas for "Page X of Y".
- ReportLab needs TrueType outlines. Inter 4.1 (SIL OFL 1.1) is shipped by the `inter-ui`
  npm package as WOFF2 with TrueType outlines; the three weights used were converted
  losslessly to TTF with fontTools and committed with the OFL licence. They are embedded
  (subset) in every PDF. Manrope is used only in the web UI (@fontsource, self-hosted).
- One process keeps SQLite to a single writer process; issue numbering additionally uses
  `BEGIN IMMEDIATE` so it stays correct even if a second process were started.

## Consequences
- Invoice layout changes are Python code (`backend/locuvi/pdf/render.py`), not HTML/CSS.
- ReportLab always declares an (unused) base-14 Helvetica resource; all text uses embedded Inter.
