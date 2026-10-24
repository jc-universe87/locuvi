# Privacy and your data

Locuvi is built so that **your records stay with you**. This page explains, in plain
English, what Locuvi stores, where it keeps it, and the only times anything leaves your
server.

## The short version

- 🏠 **Everything is stored on your own server**: a computer you control, not a company's
  cloud. There is no Locuvi account and no Locuvi company holding your data.
- 🙈 **No tracking.** Locuvi has no analytics, no advertising and no "phone home". The app
  doesn't load anything from other websites; even its fonts are built in.
- 🔌 **Nothing leaves your server unless you switch a feature on**, such as sending invoices
  by email or the AI assistant, and each feature only sends what it needs.
- 🔒 **Passwords and keys are encrypted**, never shown again after you save them, and never
  written to logs.

## What Locuvi stores

| What | Why | Where |
| --- | --- | --- |
| Your name, address, email, phone, job title | Printed on your invoices | Your server's database |
| Your bank account name, sort code and account number | Printed on invoices so practices can pay you | Database; shown masked (••••1234) on screen |
| Practices: names, addresses, contacts, fees, notes | To fill in invoices | Database |
| Your diary of sessions, invoices, credit notes, payments | Your records | Database, plus each invoice's PDF |
| Pension figures and your SD and GMC numbers | For the pension worksheet | Database |
| Files you add to the Inbox, and booking emails Locuvi keeps | So you can find and act on them | Database |
| Money **coming in** from bank statements you upload | To match payments to invoices | Database. Your spending is ignored and never saved |
| Email, Nextcloud and AI passwords or keys | So those features work | Encrypted, with a key stored separately from the database |
| A record of what happened ("audit log") | So you can see what changed and when | Database. Never contains passwords or keys |

Each [household profile](USER_GUIDE.md#16-sharing-locuvi-with-your-household) has its own
separate database and files. Profiles can't see each other's data.

## When something leaves your server

Only these features send anything outside, and only once you've set them up:

| Feature | What is sent | To whom |
| --- | --- | --- |
| **Sending invoices** (Settings › Email invoices) | The email and PDF, when you tap **Send** | Your own email provider, then the practice |
| **Reading booking emails** (Settings › Booking emails) | Locuvi signs in and *reads* the folders you chose | Your own email provider |
| **AI assistant** (Settings › Assistant) | Booking text with personal details removed, practice names and today's date. A photo or scan only after you approve that file. For **Ask Locuvi**, the records needed to answer your question | The AI company you chose ([details](AI_SETUP.md#what-is-sent-to-the-ai-company)), or nobody else if you [use your own server](AI_SETUP.md#use-your-own-server) |
| **Nextcloud copies** and **encrypted backups** | Invoice PDFs; backups are encrypted first with your backup password | Your own Nextcloud |
| **Sync** (Settings › Sync and backup file) | All your records and files, encrypted first with your sync code | The cloud folder or Nextcloud you chose |
| **Phone calendar** | Your bookings (fees only if you choose), when your calendar app asks | Your calendar app, through your private link |
| **Connect another AI assistant** | The records it asks for; never passwords, bank details or AI keys | The AI tool you connected |
| **Updates** | Nothing about you: the app asks GitHub for the latest version every few hours and downloads it (you can switch this off) | GitHub |

Switching a feature off stops it. Removing a saved password or key deletes it.

## Patient information

Locuvi is for **your business admin**, not clinical records. Don't store patient information
in it. Booking emails rarely contain patient details, but if one does:

- Locuvi drops lines that mention patients, dates of birth or NHS numbers, and masks email
  addresses, phone numbers, postcodes and long numbers, **before** anything is sent to an
  AI company.
- This is a safety net, not a guarantee. Don't upload documents that contain patient
  information.

## Backups

Backups contain **everything**, including your bank details, so:

- They're stored in the server's `backups` folder. Keep that computer safe.
- Copies kept anywhere else (for example Nextcloud) are **encrypted** with a backup
  password that only you have. Without it, nobody can open them, including you.

See [Setting up Locuvi › Backups](SETUP.md#backups).

## Your responsibilities

Because Locuvi runs on your own server, **you are in control of the data, and responsible
for it**. In practice:

- Keep the server private (don't expose it to the internet) and up to date.
- Use a strong password, and different passwords for each household member.
- If you use the AI assistant, read the AI company's data terms. Some free tiers let the
  company use what you send to improve its products.
- The records in Locuvi may include other people's details (for example practice managers'
  names and emails). Handle them as you would any business records under UK GDPR.

This page describes how the software behaves. It isn't legal advice.

## Deleting your data

- Deleted items stay in **Settings › Recently deleted** for 30 days, then are removed for good.
- A removed household profile is kept for 30 days, then deleted with its backups.
- Issued invoices are never deleted (you can cancel them), because financial records must
  be kept. In the UK, HMRC expects business records to be kept for at least 5 years after the
  31 January submission deadline of the relevant tax year.
- To remove everything, stop Locuvi and delete its Docker volumes and the `backups` folder
  (see [Setting up Locuvi › Where your data lives](SETUP.md#where-your-data-lives)).
