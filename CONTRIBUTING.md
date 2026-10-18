# Contributing to Locuvi

Thanks for wanting to help. Locuvi is a small, focused app for UK GP locums, and contributions
of all kinds are welcome: bug reports, clearer wording, translations, documentation and code.

## Reporting a problem or idea

Open an issue on GitHub and describe what you expected and what happened.

> [!CAUTION]
> **Never post real data.** No real names, bank details, invoices, emails or log lines with
> personal details. Use made-up examples such as "Dr Alex Example", `example.invalid`,
> `00-00-00` and `00000000`. Security problems go through [SECURITY.md](SECURITY.md), not
> issues.

## Changing the code

The technical details are in [docs/DEVELOPERS.md](docs/DEVELOPERS.md). In short:

1. Fork the repository and create a branch.
2. Make your change, with tests.
3. Run the same checks as CI:
   ```bash
   cd backend && uv run pytest && uv run ruff check . && uv run ruff format --check .
   cd frontend && npm test && npm run typecheck && npm run build
   ```
4. Open a pull request explaining what changed and why.

### Rules that keep Locuvi trustworthy

- **Money is never a float.** Use `Decimal`; amounts cross the API as strings.
- **Issued invoices are immutable.** Corrections are credit notes.
- **Nothing is sent, issued, paid or submitted without the user's tap.** AI and agents only
  suggest; their output is re-checked by the server.
- **Secrets never appear** in logs, API responses or git.
- **Fictional data only** in tests, fixtures and screenshots.
- **Tests never call a real AI service, email account or the user's Nextcloud.** Use the fakes.
- **All UI text goes through i18n** (`frontend/src/i18n/en.ts`) and follows
  [plain-English rules](docs/PLAIN_ENGLISH_UX.md): short, natural UK English, action-led
  labels, official NHS and accounting terms kept accurate.
- **Visible changes update the docs**: the user manual, and screenshots via
  `e2e/docs-shots.mjs`.

### Translations

English (`en.ts`) is the reference. Other languages live next to it; missing keys fall back to
English. A test makes sure the main screens (sign-in, settings, password) are translated in
every language.

## Other ways to help

Not a coder? Clearer wording, translations and bug reports all help. You can also support
the project on [GitHub Sponsors](https://github.com/sponsors/jc-universe87) or
[Ko-fi](https://ko-fi.com/pistio).

## Licence

By contributing, you agree that your contribution is licensed under the
[GNU AGPL-3.0](LICENSE), the same as the rest of Locuvi.
