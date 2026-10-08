# ADR 0002 — Authentication boundary

Status: accepted (v0.1)

The brief requires an explicit, consistent auth model even behind a private network.

## Decision
`LOCUVI_AUTH_MODE` selects one of two modes; there is no implicit "open" mode.

1. `password` (default). A single owner password supplied as a secret file
   (`LOCUVI_PASSWORD_FILE`, a Docker secret in compose). The app refuses to start without it.
   Login sets a signed (HMAC-SHA256), expiring, `HttpOnly`, `SameSite=Strict` cookie
   (`Secure` unless `COOKIE_SECURE=false`). Five failed attempts in five minutes → HTTP 429.
2. `gateway`. No in-app login. Only for deployments where the gateway authenticates
   every request (e.g. Tailscale with ACLs, or an identity-aware proxy).

In **both** modes every non-GET API request must carry `X-CSRF-Token`, derived from the
session (or a fixed server-side value in gateway mode) with the server key. No CORS
headers are ever sent, so other origins can neither read nor send that header.

## Also
- The session-signing key derives from the server key in `KEY_DIR` (or `ENCRYPTION_KEY_FILE`).
  Rotating it signs everyone out and makes a UI-stored WebDAV password unreadable (re-enter it).
- Logout clears the cookie; tokens expire after `SESSION_HOURS` (default 12).
- Not implemented: multiple users, password change UI (edit the secret file and restart), 2FA.
  Use Tailscale device authentication for a second factor.
