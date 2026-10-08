# CLAUDE.md — Locuvi build contract

You are implementing **Locuvi**, a small personal GP locum invoice application. Read all supplied markdown specifications, not just this file. Treat them as product requirements, with `specs/PRODUCT.md` defining v0.1 scope.

## Non-negotiable instructions
- Build and test a working application, not a prototype mock-up.
- Implement **v0.1 invoicing only** plus **Nextcloud/WebDAV invoice-file archival**. Do not expand into pensions Form A/B, email, bank integration, or agentic workflows.
- Data is personal financial data: store secrets carefully and do not log amounts paired with banking details or app passwords unnecessarily.
- Local database + immutable local PDF are authoritative; Nextcloud is an *optional secondary copy*, never the only copy.
- No production secrets in source, test fixtures or documentation. No sample real users' identities.
- No public internet exposure by default. Deploy privately on Linux/Docker behind Tailscale or another authenticated private gateway.
- Use GBP Decimal amounts, transactional sequential numbering, explicit rounding and versioned employer contribution rate.
- Never silently alter an issued invoice. Treat void/reissue and credit-note requirements carefully.
- Do not assume all GP work is automatically VAT exempt. Avoid claiming universal VAT treatment.
- Do not infer that an invoice being issued is an NHS pension submission.
- Keep design deliberately simple, mobile-friendly and accessible.
- All user-visible UI text should use localisation keys. Ship complete English plus placeholder architecture ready for German/Korean/French/Spanish/Portuguese; ideally add all six catalogues for stable keys, but do not delay functional v0.1 for translation polishing.
- Make a short technical decision record if deviating from stack or any business rule.
- Test using an isolated disposable WebDAV fixture/server, never the owner's existing live Nextcloud without explicit permission.
- Before claiming done, run and report tests and a real Docker smoke test; include limitations.

## Working order
1. Inspect repository/current state; if empty, scaffold it.
2. Read the entire brief.
3. Implement core domain/data and tests.
4. Implement invoicing, PDF and immutable issue workflow.
5. Implement secure WebDAV upload/retry/status.
6. Implement responsive UI/settings.
7. End-to-end verification and deployment guide.

## Delivery
Provide a runnable Docker Compose project with persistent volumes, README, migrations, tests, an example PDF produced from fictional data, and a concise handover of implemented/not implemented items. Do not invent credentials, deployment facts or real integrations.
