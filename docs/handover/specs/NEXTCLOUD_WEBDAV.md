# Nextcloud / generic WebDAV invoice file archive

## User request
Archive generated **issued invoice PDF files** into existing Nextcloud, accessible by WebDAV. This is a first-release feature, not a future optional roadmap item. No sync of medical data or patient data.

## Operating model
- Local SQLite database and locally stored issued PDFs are canonical. Nextcloud is secondary **one-way archive**.
- On issue: persist invoice and PDF locally, then enqueue an archive job. Do not block issue on remote connectivity.
- On startup/scheduled limited retries (and button `Retry upload`), process pending/failed jobs with bounded exponential backoff and idempotent target paths.
- Upload only issued PDF files. Do not upload drafts, db, personal profiles, account credentials, logs or backups by default.
- Never pull from Nextcloud to overwrite local historical issued PDFs. No automatic delete on void; instead keep original and indicate voided in app, consider void notice only in later versions.
- WebDAV must be optional, default disabled. User can change folder and enable/disable without breaking invoices.

## Configuration
Settings > Storage > Nextcloud / WebDAV:
- enabled (boolean)
- base WebDAV URL (e.g. `https://cloud.example.org/remote.php/dav/files/USERNAME/`)
- username
- dedicated app password (masked, never returned to frontend after save)
- remote root folder (default `Locuvi/Invoices`)
- auto-upload on issue (boolean)
- `Test connection` and `Save` actions
- human-readable upload status per invoice: `not_configured`, `pending`, `uploading`, `synced`, `failed`, with last attempt timestamp, error class, remote path, optional remote etag and checksum

The existing cloud may be reachable at a private address or via HTTPS hostname; do not bake any real domain into code.

## WebDAV protocol details
Use standard authenticated endpoint `/remote.php/dav/files/{username}/...` (or supplied equivalent), HTTP Basic auth over verified TLS with a dedicated Nextcloud **app password**, not the user's main password. Directory verification/listing via `PROPFIND` (`Depth: 0/1`), create hierarchy with `MKCOL`, upload with `PUT`, inspect target via `PROPFIND` and optionally `GET` for checksum verification. Percent-encode path segments safely. Handle 207, 201, 204 and 404 appropriately. Network timeouts and authentication failure must be actionable; 401/403 should pause retries until credentials fixed.

Example path (proposal): `Locuvi/Invoices/2026/10/LOC-2026-0001_Example-Medical-Practice.pdf`.
**Safer alternative:** immutable number-only basename `LOC-2026-0001.pdf`, avoiding practice names in paths; default to this privacy-friendly format. Store complete path in DB and never recompute it from edited practice details for an already synced file.

**Overwrite protection:** WebDAV PUT may replace an existing object. Before upload, detect path collisions and enforce never replacing a different invoice's content. Prefer staging as unique `.part` file and MOVE to a final path with `Overwrite: F` where server supports, or check path existence and remote verification with strict collision handling. Concurrent/retry cases must be tested. A matching remote hash or verified download makes retry successful without duplication; mismatched remote file creates `conflict`, not overwrite. Handle leftovers from interrupted staging uploads.

**Folder creation:** idempotently create remote folder hierarchy; distinguish directory already exists from permission failures. Limit path segments to safe, validated names.

## Security
- Store app password outside tracked config; environment secret or secret file recommended. If entered in UI, encrypt at rest using a server-held key outside DB; do not merely base64 encode. Do not echo or log Authorization headers. Never include password in diagnostics or export.
- Validate URL. Default allow HTTPS only; block localhost/loopback/link-local/internal metadata addresses and unsafe redirects for UI-entered remote endpoints to prevent SSRF. If a deliberately private Tailscale/LAN Nextcloud target is needed, use explicit administrator allowlist rather than globally disabling protections. Prevent redirection with authentication headers across hosts.
- Ensure TLS verification is on. Credentials transmitted server-side only, never from browser directly to WebDAV.
- Avoid leaking banking details or practice information via errors, metrics and paths.
- Archive uploads are **not** replacements for independent encrypted backups of DB and PDF volume.

## Conflict/failure UX
Display e.g. `PDF saved locally • Nextcloud backup pending`, `Archived to Nextcloud`, or `Upload failed: authentication rejected; check credentials`. Manual `Retry` and `Test connection` actions. Never claim success until remotely verified. If WebDAV disabled, suppress unnecessary failure warnings and permit issuing.

## Scope boundary
No Nextcloud OAuth, two-way sync, remote browser, document editing or version restore in v0.1. Generic WebDAV compatibility as far as practical, but optimise for Nextcloud.

## Test cases
Working upload, folder creation, wrong app password, expired password, remote server offline, timeout, rate limit, no permissions, existing identical file, conflicting content, partially uploaded file, repeated job, restart/retry persistence, malicious URL, encoded/unicode folder name, change of destination folder, database and PDF recovery. Use disposable fixture server or fake, not live cloud.
