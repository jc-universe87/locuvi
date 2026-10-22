# Changelog

What's new in each version of Locuvi, in plain English. Every change merged into `main` is
published as a new image (`latest`, plus a `sha-…` tag), so this file groups them into
releases.

## Unreleased

- More AI companies to choose from: Cohere (Command), Alibaba (Qwen), Moonshot AI (Kimi),
  Z.ai (GLM) and MiniMax, alongside OpenAI, Anthropic, Google, xAI, Mistral, DeepSeek and
  OpenRouter.
- **Your own AI server**: use a self-hosted model (Ollama, LM Studio, vLLM, llama.cpp,
  LocalAI) or your organisation's OpenAI-compatible server, so booking text never leaves
  your network. Settings › Assistant shows each company's flag and links
  to its own model list and prices; the AI guide has the full table.
- **Check key** also works for companies without a model list (one tiny test request).
- Reasoning text that some models write into their answer is removed.
- **Pension guide**: a plain-English, step-by-step guide on the Pension page to sending Forms A
  and B on PCSE Online and paying the contributions, with the deadlines, what to do if
  something goes wrong, and links to the official PCSE pages.
- Invoice emails now carry a date header (some spam filters distrust mail without one), and a
  mistyped email server name gets a clear message instead of a general error.

## 1.0.0 (October 2026): first public release

**Everyday work**
- **Today**: what needs doing, one tap each: months ready to invoice, late payments, pension
  forms due, and automatic checks (duplicate or overlapping sessions, missing details,
  backups).
- **Diary**: tap a day to add a session (AM, PM, full day or hours); fees remembered per
  practice; repeating bookings; per-session or per-hour fees; fees agreed with or without the
  practice's NHS pension contribution.
- **Add bookings from a message**: paste a booking email; Locuvi finds the dates, flags
  duplicates, clashes and cancellations, and adds nothing until you approve.

**Invoices and payments**
- One-tap monthly invoices with the practice's NHS employer pension contribution worked out;
  numbered, unchangeable A4 PDFs; automatic split when NHS work spans two months.
- Your logo, colour, footer and email sign-off on invoices.
- Email invoices from your own address (only when you tap Send).
- Record payments with Undo; part payments; match a bank statement (CSV) to invoices, keeping
  only money coming in.
- Credit notes with their own number series, and refunds when a paid invoice is credited.

**NHS pension and tax**
- Monthly Form A figures per practice (with signature tracking and the 10-week deadline) and
  Form B by money received (due on the 7th); a worksheet PDF; comparison with your PCSE
  record.
- Tax-year reports by date paid or date invoiced, with figures for your tax return and
  downloads for your accountant (CSV and a ZIP of every PDF).

**Email, calendar and AI (all optional)**
- Read booking emails from chosen folders: Gmail and other IMAP accounts, Outlook and
  Microsoft 365 through Microsoft sign-in; several accounts.
- A private calendar link for your phone or computer calendar.
- An AI assistant with your choice of company (Anthropic, OpenAI, Google Gemini, DeepSeek,
  Mistral, xAI or OpenRouter) and your own key: reads messy bookings and answers questions in
  **Ask Locuvi**. It only suggests; it never issues, sends, pays or submits.
- Connect other AI agents (such as Bevro) with revocable, read-only-by-default keys.

**Safety**
- Household profiles: separate, password-protected data for each person.
- 30-day **Recently deleted** for anything you delete; issued invoices are never deleted.
- Nightly checked backups, optional encrypted off-server copies to Nextcloud with an
  automatic restore drill, and a backup before every update.
- Nextcloud copies of every issued PDF, verified by fingerprint.
- Plain-English interface in English, with Deutsch, Español, Français, Português and 한국어
  for the main screens.
- Released under the GNU AGPL-3.0 licence.
