<div align="center">

<img src="frontend/public/favicon.svg" width="80" alt="Locuvi logo">

# Locuvi

### Every session accounted for.

**Calm, private admin for UK GP locums.** Your diary, invoices, payments, NHS pension forms
and tax-year reports in one place, running on your own computer.

[![CI](https://github.com/jc-universe87/locuvi/actions/workflows/ci.yml/badge.svg)](https://github.com/jc-universe87/locuvi/actions/workflows/ci.yml)
[![Licence: AGPL-3.0](https://img.shields.io/badge/licence-AGPL--3.0-294d63)](LICENSE)
![Self-hosted](https://img.shields.io/badge/self--hosted-your%20data%20stays%20yours-294d63)
![Made for](https://img.shields.io/badge/made%20for-UK%20GP%20locums-294d63)

[**Download**](#download) · [**User manual**](docs/USER_GUIDE.md) · [**New to locum work?**](docs/LOCUM_HANDBOOK.md) · [**Install on a server**](docs/SETUP.md) ·
[Email](docs/EMAIL_SETUP.md) · [AI assistant](docs/AI_SETUP.md) · [Privacy](docs/PRIVACY.md) ·
[Help](docs/TROUBLESHOOTING.md)

<br>

<img src="docs/images/today-ready.png" width="820" alt="Locuvi's Today page: 'You can invoice for September 2026' with a Create invoice button">

</div>

## What it does for you

Tap the days you worked. Locuvi remembers each practice's fee and tells you when a month is
ready to invoice. It adds the practice's NHS pension contribution and makes a tidy numbered
PDF. When you tap Send, it emails the invoice from your own address. It keeps track of who
has paid, and prepares your monthly NHS pension figures and a tax-year pack for your
accountant.

<table>
<tr>
<td width="50%" valign="top">

### 📅 Diary
Tap a day to add a session. Fees are remembered for each practice. Paste a booking email and
Locuvi finds the dates for you.

<img src="docs/images/diary-month.png" alt="The Diary calendar with sessions">

</td>
<td width="50%" valign="top">

### 🧾 Invoices
One tap per month. Numbered, unchangeable PDFs with your logo, sent only when *you* say so.

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

**Also included:**
- 💷 Matching bank statements to invoices
- 📨 Reading booking emails (Gmail, Outlook, Microsoft 365, iCloud…), keeping only the ones
  about locum work
- 📥 An Inbox you can clear in one tap, with tick boxes for several items at once
- 🧭 A step-by-step guide to sending NHS pension Forms A and B on PCSE Online
- ✨ An optional AI assistant from the company you choose, or your own AI server
- 📱 Your bookings in Apple, Google or Outlook calendars, plus downloads (.ics, .csv)
- 👨‍👩‍👧 Household profiles, each one private
- ♻️ A 30-day "Recently deleted"
- 🔄 [Sync](docs/SYNC.md) between your devices through Google Drive, OneDrive, Dropbox, iCloud
  Drive or Nextcloud, encrypted, plus everything in one backup file
- ☁️ Copies of your invoices in Nextcloud
- 🔒 Nightly, checked, encrypted backups

<p align="center">
<img src="docs/images/mobile-today.png" width="180" alt="Today on a phone">
<img src="docs/images/mobile-diary.png" width="180" alt="Diary on a phone">
<img src="docs/images/mobile-invoices.png" width="180" alt="Invoices on a phone">
<img src="docs/images/mobile-pension.png" width="180" alt="Pension on a phone">
</p>

## Is Locuvi right for you?

| ✅ A good fit if you… | ⚠️ Not a good fit if you… |
| --- | --- |
| are a **self-employed GP locum in the UK** | need **VAT invoices** (not supported) |
| invoice **GP practices** by session, day or hour | want a **hosted service** you just sign up to: Locuvi runs on your own computer |
| want help with **NHS locum pension Form A and Form B** | want the app to **submit** pension forms or file tax returns for you (it prepares figures; you submit) |
| like your data **private, on your own computer** | need full **accounting** or bookkeeping software |

## Designed to just work

- **Few questions.** Three short steps to start: you, your bank details and your first
  practice.
- **Nothing to save.** Drafts save themselves.
- **Undo, not "Are you sure?"** Most actions can be undone, and deleted things wait 30 days in
  **Recently deleted**.
- **You stay in charge.** Locuvi never sends an email, submits a pension form or records a
  payment without your tap. The AI assistant is optional and only ever suggests.

## Your data stays yours

Locuvi runs on **a computer you control**: your own Windows PC or Mac, a mini PC, Raspberry
Pi, NAS or private server. There's no Locuvi account and no company holding your records. No tracking and no
analytics. Nothing leaves your server unless you switch on a feature such as email or AI.
It backs itself up every night, checks each backup can be restored, and can keep an encrypted
copy elsewhere. [Read more about privacy](docs/PRIVACY.md).

## Download

Every version has the same features and shows the same Locuvi.

| | Download | |
| --- | --- | --- |
| 🪟 **Windows** 10 and 11 | [**Locuvi-Windows-Setup.exe**](https://github.com/jc-universe87/locuvi/releases/latest/download/Locuvi-Windows-Setup.exe) | Runs Locuvi on your PC. Nothing else to install. |
| 🍎 **Mac** with Apple silicon (M1 or newer) | [**Locuvi-macOS.dmg**](https://github.com/jc-universe87/locuvi/releases/latest/download/Locuvi-macOS.dmg) | Runs Locuvi on your Mac. Nothing else to install. |
| 🤖 **Android** phones and tablets | [**Locuvi-Android.apk**](https://github.com/jc-universe87/locuvi/releases/latest/download/Locuvi-Android.apk) | Connects to your Locuvi on your computer or server. |
| 📱 **iPhone and iPad** | [Add to Home Screen](docs/APPS.md#iphone-and-ipad) | From Safari, no download needed. |
| 🖥 **Server** (home PC, Raspberry Pi, NAS) | [Docker](docs/SETUP.md) | Always on, so you can reach it from anywhere. |

Windows, macOS and Android show a warning the first time, because Locuvi is a free project
that isn't registered with Microsoft, Apple or Google.
👉 [How to install each one](docs/APPS.md) · [All releases](https://github.com/jc-universe87/locuvi/releases)

## Get started

**1. Install it.** The quickest way is the [desktop app](#download) for Windows or Mac. To
reach Locuvi from anywhere, install it on a computer that stays on instead. That takes about
15 minutes with Docker, and a friend or IT helper can do it for you once.
👉 [Apps for computer, phone and tablet](docs/APPS.md) · [Setting up a server](docs/SETUP.md)

**2. Open it** on your computer or phone and answer three questions.
👉 [Your first five minutes](docs/USER_GUIDE.md#3-your-first-five-minutes)

**3. Tap the days you work.** Locuvi tells you when it's time to invoice.
👉 [A normal month](docs/USER_GUIDE.md#4-a-normal-month-step-by-step)

| I want to… | Read |
| --- | --- |
| Learn how to use Locuvi | 📘 [User manual](docs/USER_GUIDE.md) |
| Install the Windows, Mac, Android or iPhone app | 📲 [Apps](docs/APPS.md) |
| Install it on a server, update it, or back up and restore | 🛠 [Setting up Locuvi](docs/SETUP.md) |
| Read booking emails, or send invoices by email | 📨 [Connecting your email](docs/EMAIL_SETUP.md) |
| Turn on the AI assistant | ✨ [Setting up the AI assistant](docs/AI_SETUP.md) |
| Know what's stored and where | 🔒 [Privacy and your data](docs/PRIVACY.md) |
| Fix a problem | 🧰 [Troubleshooting](docs/TROUBLESHOOTING.md) |
| See what's new | 📝 [Changelog](CHANGELOG.md) |
| Help, or change the code | 🤝 [Contributing](CONTRIBUTING.md) · 💻 [Developer notes](docs/DEVELOPERS.md) |

Already running it? On a server, update with `./update.sh` in the Locuvi folder. With the
desktop app, install the newest download over the old one. Both back up first.

## Good to know

> [!IMPORTANT]
> **Locuvi is an independent project.** It isn't affiliated with or endorsed by the NHS, NHS
> England, the NHS Business Services Authority (NHSBSA), Primary Care Support England (PCSE)
> or HMRC.
>
> It helps with admin. It is **not** accounting, tax or financial advice, and it does **not**
> submit NHS pension forms. Pension rates and rules change. Check figures against current
> NHSBSA, PCSE and GOV.UK guidance ([sources](docs/handover/SOURCES.md)). Ask your
> accountant about VAT and tax.

An example invoice made from fictional data:
[`docs/examples/example-invoice.pdf`](docs/examples/example-invoice.pdf). All names and
figures in the pictures are made up.

## 💛 Support the project

Locuvi is built and maintained by one person in their spare time, and it's free. If it saves
you an evening of invoices and pension forms each month, consider saying thanks:

<p>
  <a href="https://github.com/sponsors/jc-universe87"><img src="https://img.shields.io/badge/GitHub%20Sponsors-♥-ea4aaa?logo=github" alt="GitHub Sponsors"></a>
  <a href="https://ko-fi.com/pistio"><img src="https://img.shields.io/badge/Ko--fi-support-ff5e5b?logo=ko-fi&logoColor=white" alt="Ko-fi"></a>
</p>

## Licence

Locuvi is free software, released under the [GNU Affero General Public Licence v3.0](LICENSE).
You may use, study, change and share it. If you share a modified version, or let others use
a modified version over a network, you must make your source code available under the same
licence.

<sub>Fonts: Inter (SIL Open Font Licence 1.1, embedded in PDFs; licence in
`backend/locuvi/pdf/fonts/OFL-Inter.txt`) and Manrope (OFL, web app via @fontsource).</sub>
