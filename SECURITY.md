# Security policy

Locuvi holds financial records and bank details, so security reports are taken seriously.
Thank you for helping keep its users safe.

## Reporting a vulnerability

**Please don't open a public issue for a security problem.**

Report it privately through GitHub: open the repository's **Security** tab and choose
**Report a vulnerability**. Include:

- what the problem is and what an attacker could do,
- the steps to reproduce it, with **made-up data only**,
- the version or commit (`sha-…` image tag) you tested.

You'll get an acknowledgement as soon as possible. The fix will be released, and you'll be
credited unless you'd rather not be.

## Supported versions

Only the latest published version (`latest` image, newest `sha-…` tag) receives fixes.
Update with `./update.sh` (see [Setting up Locuvi](docs/SETUP.md#updates)).

## How Locuvi is designed to be safe

- **Private by default.** Locuvi only listens on the server itself unless you choose
  otherwise. It's meant to be reached through a private network (home network or Tailscale),
  never the public internet.
- **Sign-in.** Each household profile has its own password, stored scrypt-hashed. Sign-in is
  rate-limited (5 attempts per 5 minutes). Sessions use HttpOnly, SameSite=Strict signed
  cookies, and end when a password is changed or a profile is removed. Every request that
  changes something needs a CSRF token. ([ADR 0002](docs/decisions/0002-auth-model.md))
- **Secrets.** Email, Nextcloud and AI passwords or keys are encrypted at rest with a key kept
  outside the database, never returned to the browser and never logged. Bank account numbers
  are masked in the app.
- **Records can't be quietly changed.** Issued invoices and credit notes are immutable; each
  PDF's SHA-256 fingerprint is checked on every start and before every backup.
- **Safe outgoing connections.** Nextcloud and email server addresses are checked, and private
  or internal addresses are refused unless the administrator allows them, to prevent the
  server being used to reach internal systems (SSRF). AI companies are a fixed list of
  official addresses; an owner's own AI server may be on the home network, but cloud-metadata
  and link-local addresses are refused.
- **Uploads.** SVG logos are cleaned of scripts and external references; other images are
  re-encoded. Documents are size-limited.
- **Container.** Runs as a non-root user with a read-only filesystem, all Linux capabilities
  dropped, `no-new-privileges`, and memory and process limits. A strict Content Security
  Policy and security headers are sent; API docs are disabled.
- **AI is contained.** AI is optional. AI output is only ever a suggestion, re-checked by the
  server, and the assistant (and connected agents) can never issue, send, pay or submit
  anything.
- **Backups.** Off-server backup copies are encrypted (scrypt + AES-256-GCM) and verified by
  an automatic restore drill.
