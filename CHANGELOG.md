# Changelog

What's new in each version of Locuvi, in plain English. Every change merged into `main` is
published as a new image (`latest`, plus a `sha-…` tag), so this file groups them into
releases.

## Unreleased

- **Sync through a Dropbox, Google Drive or OneDrive account** (Settings › Sync and backup
  file): sign in once on each device, no app needed, so it works on phones and tablets too.
  Locuvi only gets its own folder, and everything in it stays encrypted with your sync code.
  The options appear once Locuvi is registered with each company
  ([docs/CLOUD_APPS.md](docs/CLOUD_APPS.md)).

- **Locuvi updates itself.** The Windows and Mac app checks for a new version every few
  hours and installs it with **Update now** (it closes, installs and opens again). The Android
  app asks once a day and installs it with one tap. iPhone and iPad offer **Restart Locuvi**
  once a new version has arrived. **Settings › Phones, tablets and computers › Updates** shows
  the version and has **Check for updates**. Every download is checked against the released
  file before it's installed.
- Android releases are now signed with one permanent key, so new versions install over old
  ones. Coming from an earlier version, reinstall once ([how](docs/APPS.md#your-records-backups-and-updates)).

- **Phones and tablets sync through Nextcloud.** On Android it works with any Nextcloud,
  including one from work; on iPhone and iPad the Nextcloud must allow Locuvi's address
  ([how](docs/SYNC.md#let-iphones-and-ipads-connect)). Sync now asks for the Nextcloud
  address, user name and app password itself, and takes an optional **home or work
  address** (such as `http://192.168.1.20`): each sync uses whichever answers, at home or
  out. Clearer messages when Nextcloud can't be reached or refuses the app password.

- **Phones and tablets say plainly what they can't do yet** (AI assistant, email, Nextcloud
  copies, calendar subscription, connecting other assistants, automatic sync), in Settings and
  once on Today, with what to use instead. The AI assistant stays off on phones.
- **The iPhone and iPad site is locked down**: its page may only load and contact its own
  address (Content Security Policy) and sends no referrer.

- **No more extra "Locuvi is running" window** on Windows and Mac: close Locuvi's window
  when you've finished, and Locuvi syncs and stops by itself a few minutes later. Quit
  Locuvi and Show my Locuvi folder are in Settings › Phones, tablets and computers.
- The iPhone and iPad app lives at <https://locuvi.pistio.co.uk/>.

- **Full Locuvi on phones and tablets.** The Android app and the iPhone/iPad Home Screen app
  now run the whole of Locuvi on the device, with records kept there, and work without the
  internet. [Sync](docs/SYNC.md) keeps them in step with your computer. Email, Nextcloud
  copies and calendar subscriptions are set up on a computer and sync to the phone.

- **Sync between your devices** (Settings › Sync and backup file): each device keeps its own
  copy and works offline; the copies meet in an encrypted folder in Google Drive, OneDrive,
  Dropbox, iCloud Drive or Nextcloud. Invoice numbers are checked with your other devices
  before issuing, so they never repeat. [docs/SYNC.md](docs/SYNC.md)
- **Everything in one file**: download all records, invoices and documents as one locked
  file, and add records from such a file.

- **Apps for Windows, Mac and Android, and the iPhone and iPad Home Screen.** The desktop app
  runs Locuvi on your PC or Mac, with no server or Docker needed. It opens in its own window
  and signs you in by itself. The Android app connects to your Locuvi. On an iPhone or iPad,
  add Locuvi to the Home Screen from Safari. Every version has every feature. Downloads are in
  the [README](README.md#download), and [docs/APPS.md](docs/APPS.md) explains how to install
  each one.
- **Settings › Phones, tablets and computers**: the downloads, the address your phone needs,
  and, in the desktop app, a switch that lets phones and tablets at home connect.
- Fixed: adding a file to the Inbox could fail with "database is locked" if something else
  was saved at the same moment.

- **Pension reminders by email** (Settings › NHS pension, off by default): 5 days before
  Form B is due, 2 weeks before a 10-week deadline, and when a Form A has waited more than 2
  weeks for a signature. Each reminder is sent once; at most one email a day.
- **Pension months link to PCSE Online** and to the official paper Forms A and B for that
  scheme year.
- **The first-time GP locum's handbook** (`docs/LOCUM_HANDBOOK.md`): a plain-English guide
  for new locums. It covers the checklist before your first session, agreeing terms, invoicing
  and chasing payment, the NHS pension, tax and Making Tax Digital, and appraisal, with tips
  and how Locuvi helps at each step.
- More AI companies to choose from: Cohere (Command), Alibaba (Qwen), Moonshot AI (Kimi),
  Z.ai (GLM) and MiniMax, alongside OpenAI, Anthropic, Google, xAI, Mistral, DeepSeek and
  OpenRouter.
- **Your own AI server**: use a self-hosted model (Ollama, LM Studio, vLLM, llama.cpp,
  LocalAI) or your organisation's OpenAI-compatible server, so booking text never leaves
  your network. Settings › Assistant shows each company's flag and links
  to its own model list and prices; the AI guide has the full table.
- **Check key** also works for companies without a model list (one tiny test request).
- Reasoning text that some models write into their answer is removed.
- **Inbox:** **I've dealt with this** opens the next item, or goes back to the list when
  there's nothing left. Tick several items to mark them dealt with, move them back or delete
  them; deleting more than one needs a second tick. **I've dealt with all** clears the list
  in one tap. Every one of these can be undone.
- **Booking emails: only the relevant ones.** Locuvi now scores each email instead of
  matching single words. It needs signs of locum work (the word "locum", one of your practices,
  booking and session words, a fee) and a work date in the message itself, not in the header
  or a quoted reply. Newsletters, mailing lists and automatic replies are left out. Emails kept
  by the old check are moved to Recently deleted (restorable for 30 days), and their booking
  suggestions are hidden with them.
- **Calendar:** one-tap subscribe buttons for Apple Calendar, Google Calendar, Outlook.com and
  Microsoft 365, plus one-off downloads of every session as a calendar file (.ics) or
  spreadsheet (.csv).
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
