<div align="center">

<img src="frontend/public/favicon.svg" width="80" alt="Locuvi logo">

# Locuvi

### Every session accounted for.

**A calm, private home for a UK GP locum's admin:** diary, invoices, payments, NHS pension
forms and tax-year reports, on your own server.

[![CI](https://github.com/jc-universe87/GP-Locum-Manager/actions/workflows/ci.yml/badge.svg)](https://github.com/jc-universe87/GP-Locum-Manager/actions/workflows/ci.yml)
![Self-hosted](https://img.shields.io/badge/self--hosted-your%20server-294d63)
![Made for](https://img.shields.io/badge/made%20for-UK%20GP%20locums-294d63)

[**User guide**](docs/USER_GUIDE.md) · [**Set it up**](docs/SETUP.md) ·
[Email](docs/EMAIL_SETUP.md) · [AI assistant](docs/AI_SETUP.md) · [Developers](docs/DEVELOPERS.md)

<br>

<img src="docs/images/today.png" width="820" alt="Locuvi's Today page: what you've invoiced, what you're owed and what needs doing">

</div>

## What it does for you

Tap the days you worked. Locuvi remembers each practice's fee, tells you when a month is ready
to invoice, adds the practice's NHS pension contribution, creates a tidy numbered PDF, emails
it from your own address, keeps track of who has paid, and prepares your monthly pension
figures and a tax-year pack for your accountant.

<table>
<tr>
<td width="50%" valign="top">

### 📅 Diary
Tap a day to add a session. Fees are remembered for each practice. Paste a booking email and
Locuvi finds the dates for you.

<img src="docs/images/diary.png" alt="The Diary calendar">

</td>
<td width="50%" valign="top">

### 🧾 Invoices
One tap per month. Numbered, unchangeable PDFs with your logo, emailed when *you* say so.

<img src="docs/images/invoice.png" alt="An issued, paid invoice">

</td>
</tr>
<tr>
<td valign="top">

### 🏛 NHS pension
Form A figures for each practice and Form B for each month, with deadlines and reminders.
Download the figures; you submit the forms.

<img src="docs/images/pension-month.png" alt="A month's pension figures">

</td>
<td valign="top">

### 📊 Reports
Tax-year totals by month and by practice, the figures your tax return needs, and one-click
downloads for your accountant.

<img src="docs/images/reports.png" alt="Tax-year reports">

</td>
</tr>
</table>

**Also included:** 💷 bank statement matching · 📨 reads booking emails (Gmail, Outlook,
Microsoft 365, iCloud…) · ✨ optional AI assistant with your choice of AI company ·
📱 phone calendar feed · 👨‍👩‍👧 household profiles, each private · ♻️ 30-day "Recently deleted" ·
☁️ Nextcloud copies · 🔒 nightly, checked, encrypted backups

<p align="center">
<img src="docs/images/mobile-today.png" width="180" alt="Today on a phone">
<img src="docs/images/mobile-diary.png" width="180" alt="Diary on a phone">
<img src="docs/images/mobile-invoices.png" width="180" alt="Invoices on a phone">
<img src="docs/images/mobile-pension.png" width="180" alt="Pension on a phone">
</p>

## Designed to just work

- **Few questions.** Three short steps to start: you, your bank details, your first practice.
- **Nothing to save.** Drafts save themselves.
- **Undo, not "Are you sure?"** Most actions can be undone, and deleted things wait 30 days in
  **Recently deleted**.
- **You stay in charge.** Locuvi never sends an email, submits a pension form or records a
  payment without your tap. The AI assistant is optional and only ever suggests.

## Your data stays yours

Locuvi runs on **your own computer or server**, not in someone else's cloud. Nobody else can
see your records. It backs itself up every night, checks each backup can be restored, and can
keep an encrypted copy elsewhere. Saved passwords and keys are encrypted and never shown again.

## Get started

| I want to… | Read |
| --- | --- |
| Learn how to use Locuvi | 📘 [User guide](docs/USER_GUIDE.md) |
| Install it on a server, update it or restore a backup | 🛠 [Setting up Locuvi](docs/SETUP.md) |
| Let Locuvi read booking emails | 📨 [Connecting your email](docs/EMAIL_SETUP.md) |
| Turn on the AI assistant | ✨ [Setting up the AI assistant](docs/AI_SETUP.md) |
| Change the code | 💻 [Developer notes](docs/DEVELOPERS.md) · [Roadmap](docs/ROADMAP.md) |

Already running it? Update with `./update.sh` in the Locuvi folder.

## Good to know

> [!IMPORTANT]
> Locuvi helps with admin. It is **not** an accounting package and it does **not** submit NHS
> pension forms. Pension rates and rules change: check them against current NHSBSA, PCSE and
> GOV.UK guidance ([sources](docs/handover/SOURCES.md)). Locuvi doesn't decide VAT treatment and
> doesn't produce VAT invoices; ask your accountant if unsure.

An example invoice made from fictional data: [`docs/examples/example-invoice.pdf`](docs/examples/example-invoice.pdf).
All names and figures in the pictures are made up.

<sub>Fonts: Inter (SIL Open Font License 1.1, embedded in PDFs; licence in
`backend/locuvi/pdf/fonts/OFL-Inter.txt`) and Manrope (OFL, web app via @fontsource).</sub>
