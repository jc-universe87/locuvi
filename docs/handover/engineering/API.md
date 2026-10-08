# REST interface sketch

Version all paths `/api/v1`. Pydantic input/output validation. Auth boundary required even behind private network: choose an explicit consistent model and document it. CSRF protection where cookie auth used.

- `GET/PUT /settings/profile` owner identity/defaults (mask account number where appropriate)
- `GET/POST /practices`, `GET/PATCH /practices/{id}`
- `GET/POST /invoices`, `GET/PATCH /invoices/{id}` (draft only)
- `POST /invoices/{id}/preview` (no official number; PDF preview optional watermark)
- `POST /invoices/{id}/issue` (idempotency key required; returns number and PDF availability)
- `GET /invoices/{id}/pdf` (exact issued artifact)
- `POST /invoices/{id}/duplicate`
- `POST /invoices/{id}/void` (reason required)
- `GET/PUT /storage/webdav` (never echo secret)
- `POST /storage/webdav/test` (safe validated URL, does not persist secrets without explicit save)
- `GET /invoices/{id}/archive-status`
- `POST /invoices/{id}/archive-retry`
- `GET /health/live` and `/health/ready`

Use safe errors (no auth headers/stack traces). Pagination on invoice lists. Browser never receives raw WebDAV app password.
