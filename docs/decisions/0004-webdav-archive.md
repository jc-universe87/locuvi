# ADR 0004 — Nextcloud / WebDAV archive

Status: accepted (v0.1)

## Model
One-way, best-effort archive of **issued PDFs only**. The local DB + PDF stay authoritative;
archive state never affects issue. Default disabled.

## Upload algorithm (per job, idempotent)
1. Destination fixed when the job is created: `{base}/{YYYY}/{MM}/{NUMBER}.pdf` (invoice
   date; number-only basename). Stored on the job; never recomputed from practice data.
2. `PROPFIND Depth:0` the folder; if missing, `MKCOL` each level (201 created / 405 exists;
   409/401/403 are errors).
3. `PROPFIND` the target. If it exists, `GET` it and compare SHA-256: same → **synced**;
   different → **conflict** (never overwritten, no auto-retry).
4. Otherwise `PUT` to a job-specific staging name `.{NUMBER}.pdf.locuvi-{job}.part`, then
   `MOVE` with `Overwrite: F`. `412` (someone created the target meanwhile) → compare as in 3.
   A leftover `.part` from an interrupted attempt is simply replaced by the next PUT of the same job.
5. `GET` the final file and compare SHA-256 before marking **synced**; record the ETag.

## Retry
Statuses: `not_configured` (no job), `pending`, `uploading`, `synced`, `failed`, `conflict`.
Backoff 30 s × 2^(n-1), max 6 h, honouring `Retry-After`; after 10 attempts it waits for a
manual retry. 401/403/redirect/blocked-URL/credential errors **pause** retries until the
settings are saved again or *Retry* is pressed. Jobs stuck in `uploading` after a crash are
reset at start-up. Changing the destination re-targets unsynced jobs; synced jobs keep their
history. "Re-upload if missing" re-verifies a synced file and uploads only if it is gone.

## Security
- Basic auth with a Nextcloud **app password**, server-side only, TLS verification always on,
  redirects never followed, host pinned to the configured host on every request.
- SSRF: HTTPS only; loopback, private, link-local, CGNAT/Tailscale, multicast, reserved,
  metadata hostnames and IPv4-mapped forms blocked — checked on the literal URL at save and on
  the resolved addresses before every request. Private targets require
  `WEBDAV_ALLOWED_PRIVATE_HOSTS`; plain HTTP additionally requires
  `WEBDAV_ALLOW_HTTP_FOR_ALLOWLISTED=true`.
- Known limitation: the DNS check and the connection resolve separately (a DNS-rebinding
  window). Mitigated by the per-request check and by the target being the owner's own server.
- App password: Fernet-encrypted with a key in `KEY_DIR` (separate volume) or
  `ENCRYPTION_KEY_FILE`; or supplied via `WEBDAV_SECRET_FILE`. Never returned by the API,
  never logged (httpx logging is held at WARNING; errors carry only a non-secret class).
- Folder segments are validated (no `..`, separators, control chars; ≤ 100 chars, ≤ 10
  levels), Unicode-normalised (NFC) and percent-encoded.
