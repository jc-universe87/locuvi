# Troubleshooting

Find what you're seeing, then try the fix. Messages in **bold** are exactly what Locuvi shows.
Fixes marked 🛠 are for whoever looks after the server.

**Jump to:** [Opening and signing in](#opening-and-signing-in) ·
[Invoices](#invoices) · [Payments and bank statements](#payments-and-bank-statements) ·
[Email](#email) · [Phone calendar](#phone-calendar) · [Nextcloud](#nextcloud) ·
[Backups and updates](#backups-and-updates) · [AI assistant](#ai-assistant) ·
[Still stuck?](#still-stuck)

---

## Opening and signing in

<details>
<summary><b>The page won't open at all</b></summary>

- Check you're using the right address, including `https://` or `http://` and any port number
  (for example `:8767`).
- On your phone, make sure you're on your home Wi-Fi, or that Tailscale is switched on.
- 🛠 On the server, run `docker compose ps`. Locuvi should show **healthy**. If it doesn't,
  see **Locuvi won't start after an update** under [Backups and updates](#backups-and-updates).
</details>

<details>
<summary><b>I type my password, tap Sign in, and nothing happens</b> (or I'm sent back to sign in)</summary>

This usually means Locuvi is opened over plain `http://` while it expects a secure
connection.

🛠 In `.env`, set `COOKIE_SECURE=false` if you open Locuvi with `http://` (on the server or
your home network), or keep it `true` and use `https://` (for example with Tailscale). Then
run `docker compose up -d`.
</details>

<details>
<summary><b>"That name or password isn't right."</b></summary>

- Check Caps Lock, and that the name matches your profile (capitals don't matter).
- With only one profile, there's no name box: just the password.
- [Forgotten your password?](USER_GUIDE.md#18-common-questions)
</details>

<details>
<summary><b>"Too many attempts. Wait a few minutes."</b></summary>

After 5 wrong passwords, Locuvi pauses sign-in for 5 minutes to stop guessing. Wait, then try
again carefully.
</details>

<details>
<summary><b>"Security check failed. Reload the page and try again."</b></summary>

Your page was open for a long time, or you signed in elsewhere. Reload the page (pull down on a
phone, or press F5) and try again.
</details>

<details>
<summary><b>I'm signed out every day</b></summary>

For safety you stay signed in for 12 hours. 🛠 `SESSION_HOURS` in `.env` changes this.
</details>

## Invoices

<details>
<summary><b>I can't issue an invoice</b>: <b>"Please check these details before issuing"</b></summary>

Locuvi lists exactly what to fix. The usual ones:

| Message | Fix |
| --- | --- |
| **Add your name, address and bank details in Settings first.** | **Settings › Your details** and **Bank account** |
| **Add the practice's billing address.** | **Settings › Practices** |
| **… requires a purchase order (PO) number.** | Type it in **Practice reference or PO number** |
| **Your NHS pensionable work covers more than one month** | Tap **Make a separate invoice for each month** |
| **The NHS pension rate changes during this period.** | Make separate invoices for the dates before and after the change |
| **No pension contribution rate is set for these work dates.** | Add a rate in **Settings › NHS pension** that starts on or before those dates |
| **You marked yourself as VAT registered…** | Locuvi doesn't create VAT invoices. Check **Settings › Invoice settings** and ask your accountant |
| **Invoice number … has already been used.** | Increase **Next invoice number** in **Settings › Invoice settings** |
</details>

<details>
<summary><b>"View PDF before issuing" doesn't open</b></summary>

Your browser may have blocked it as a pop-up. Allow pop-ups for Locuvi's address, or tap
again.
</details>

<details>
<summary><b>I can't change a session</b>: <b>"This work is already on an issued invoice"</b></summary>

That's deliberate, so your diary always matches your invoices. To change it, correct the
invoice (see [Corrections](USER_GUIDE.md#9-corrections-cancelling-and-credit-notes)).
</details>

<details>
<summary><b>I can't cancel an invoice</b></summary>

- **"Remove or correct the recorded payments before cancelling this invoice."** Remove the
  payment first (it goes to Recently deleted), or use a credit note instead.
- **"This invoice has credit notes, so it can't be voided."** Use another credit note.
</details>

## Payments and bank statements

<details>
<summary><b>"Couldn't find an amount column in this file." / "Couldn't read this statement."</b></summary>

Locuvi needs a **CSV** file with a date, a description and an amount (or separate money-in and
money-out columns). In your online banking, look for "Export", "Download transactions" or
"Statement as CSV". PDF statements can't be read. Files up to 5 MB work.
</details>

<details>
<summary><b>A payment wasn't matched to its invoice</b></summary>

Open **Check bank payments**, find it under **Need checking**, and tap **Record** to choose the
invoice yourself. Asking practices to quote the invoice number (for example `LOC-2026-0001`) in
their payment reference makes matching automatic.
</details>

## Email

<details>
<summary><b>Sending: "Your email provider didn't accept the username or password."</b></summary>

- Use an **app password**, not your normal password ([how](EMAIL_SETUP.md#part-2-sending-invoices-from-your-email-address)).
- Gmail needs 2-Step Verification turned on before you can make an app password.
- Outlook, Hotmail, Microsoft 365 and NHSmail often refuse password-based sending. Use another
  address for sending, or download the PDF and send it yourself.
</details>

<details>
<summary><b>Sending: the test email never arrives</b></summary>

Check your spam folder. Check **Your email address** is spelled right. Some providers only let
you send from the address you sign in with.
</details>

<details>
<summary><b>Reading: "The mail server rejected the login."</b></summary>

Create a new app password and enter it again. For Gmail, make sure the app password belongs
to the same Google account as the address.
</details>

<details>
<summary><b>Reading: Microsoft says "Need admin approval"</b> (often NHSmail)</summary>

Your organisation must approve the app before Locuvi can read that mailbox. For NHSmail, the
practical option is to forward booking emails to a Gmail address and connect Gmail. See
[NHSmail](EMAIL_SETUP.md#nhsmail).
</details>

<details>
<summary><b>Reading: "The sign-in code expired. Start again." / "Sign in to Microsoft again."</b></summary>

Tap **Sign in with Microsoft** again and finish within a few minutes. If you signed Locuvi out
in your Microsoft account, sign in again in Locuvi.
</details>

<details>
<summary><b>Reading: booking emails aren't being found</b></summary>

- Check you ticked the right folders, and **Check emails from the last …** covers the dates.
- Tap **Check for bookings now** to try straight away.
- Very unusual booking emails may need the [AI assistant](AI_SETUP.md), or paste them in by
  hand.
</details>

## Phone calendar

<details>
<summary><b>My bookings don't appear in my phone's calendar</b></summary>

- Your phone must be able to reach Locuvi: on your home Wi-Fi, or with Tailscale switched on.
- Calendar apps check for changes on their own schedule, sometimes only every few hours.
- If you tapped **Replace link**, add the new link to your calendar again.
</details>

## Nextcloud

<details>
<summary><b>"Nextcloud didn't accept your login."</b></summary>

Create a new app password in Nextcloud (Settings › Security) and enter it in
**Settings › Nextcloud copies**. Don't use your main Nextcloud password.
</details>

<details>
<summary><b>"File already exists in Nextcloud"</b></summary>

A different file with that name is already there, and Locuvi never overwrites files. Check that
file in Nextcloud, rename or move it, then tap **Try saving to Nextcloud again**.
</details>

<details>
<summary><b>"This server address is blocked for security."</b></summary>

For safety Locuvi only connects to public `https://` addresses. 🛠 For a Nextcloud on your own
network or Tailscale, allow it with `WEBDAV_ALLOWED_PRIVATE_HOSTS` in `.env` (see
[Setting up Locuvi](SETUP.md#nextcloud-copies-optional)).
</details>

## Backups and updates

<details>
<summary><b>"Couldn't back up your records. Check that Locuvi can write to the backup folder."</b></summary>

🛠 The `backups` folder must belong to Locuvi's user inside Docker (number 10001) and the disk
must have space:

```bash
sudo chown -R 10001:10001 backups
df -h .
```

Then tap **Back up now** on **Today**.
</details>

<details>
<summary><b>"Your backups are only on this server."</b></summary>

Not an error, a reminder: set a backup password so Locuvi also keeps an encrypted copy in your
Nextcloud. See [Keep an encrypted copy somewhere else](SETUP.md#keep-an-encrypted-copy-somewhere-else-recommended).
You can **Hide** the reminder if you keep copies another way.
</details>

<details>
<summary><b>Locuvi won't start after an update</b></summary>

Before changing your data, Locuvi makes a backup. If it can't (for example the disk is full or
the backup folder isn't writable), it refuses to start rather than risk your records.

🛠 Look at the reason:

```bash
docker compose logs --tail 50 locuvi
```

Fix it (free up disk space, or fix the backup folder as above), then run `./update.sh` again.
To go back to the previous version, see [Updates](SETUP.md#updates).
</details>

<details>
<summary><b>"The saved PDF is missing" / "doesn't match the original. Restore it from a backup."</b></summary>

Locuvi checks every issued invoice's PDF against its fingerprint. This message means a file
was deleted or changed outside Locuvi. 🛠 Restore the latest good backup (see
[Restoring](SETUP.md#restoring)).
</details>

## AI assistant

<details>
<summary><b>"The AI provider rejected the API key."</b></summary>

Copy the key again from the AI company's website and paste it in **Settings › Assistant**, then
tap **Check key**. Make sure it's an **API key** from the developer site, not a chat
subscription, and that your account has credit or billing set up.
</details>

<details>
<summary><b>"The AI service is busy." / "Couldn't reach the AI service."</b></summary>

Wait a minute and try again. 🛠 If it keeps happening, check the server has internet access.
</details>

<details>
<summary><b>"This AI company can't read this scan or photo. Paste the text instead."</b></summary>

Some companies or models don't read images. Paste the email text, or choose a company that
reads photos (see [Choose an AI company](AI_SETUP.md#choose-an-ai-company)).
</details>

<details>
<summary><b>"This AI company can read bookings but can't answer questions."</b></summary>

Some companies (currently Perplexity) don't support the "tools" Ask Locuvi needs to look up
your records. Booking reading still works. To use Ask Locuvi or the assistant-written weekly
summary, choose another company in **Settings › Assistant**.
</details>

<details>
<summary><b>The model I chose stopped working</b></summary>

AI companies retire model names. Tap **Check key**, pick a model from the list, and **Save**.
Leaving **Model** empty uses Locuvi's default for that company.
</details>

## Still stuck?

- 🛠 The server log usually says why: `docker compose logs --tail 100 locuvi`. It never contains
  your passwords or keys.
- 🛠 `docker compose exec locuvi python -m locuvi.cli verify` checks every invoice PDF and the
  database.
- Report a problem on the project's [GitHub issues page](https://github.com/jc-universe87/locuvi/issues).
  **Never include real names, bank details, invoices or log lines with personal details.** Use
  made-up examples.
- Found a security problem? Please follow [SECURITY.md](../SECURITY.md) instead of opening a
  public issue.
