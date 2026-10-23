# Sync and the backup file

Sync keeps the same records on every device you use Locuvi on. Each device keeps its own full
copy, so Locuvi works without the internet. The copies meet in a **sync folder** in cloud
storage you already have, and the folder is locked with a **sync code** that only your
devices know.

**Contents**
[What you need](#what-you-need) · [Start syncing](#start-syncing) ·
[Add another device](#add-another-device) · [Day to day](#day-to-day) ·
[Invoice numbers](#invoice-numbers) · [Everything in one file](#everything-in-one-file) ·
[What stays on one device](#what-stays-on-one-device) · [Questions](#questions)

---

## What you need

One of these:

- **Google Drive, OneDrive, Dropbox or iCloud Drive**, with its app installed and signed in
  on your computer. Locuvi keeps its sync folder inside the folder that app looks after.
- **Nextcloud**, set up in **Settings › Nextcloud copies**.

## Start syncing

Do this once, on the device that has your records now (usually your computer).

1. Open **Settings › Sync and backup file**.
2. Tap **Start syncing from this device**.
3. Choose where the sync folder goes, for example **Dropbox** or **Google Drive**. Locuvi
   lists the cloud folders it finds on this computer.
4. Give this device a name, such as *Laptop*, and tap **Start syncing**.
5. Locuvi shows your **sync code**, for example `KQ7M-2XRT-9WHC-4PZB-LN6D`. Write it down or
   save it in your password manager. You need it for each new device.

> [!IMPORTANT]
> The sync code is the key to your records. Locuvi can't show it to anyone else and can't
> recover it. If you lose it, tap **Show sync code** on a device that's already syncing.

## Add another device

On the new device:

1. Install Locuvi ([apps](APPS.md)), and on a computer the same cloud storage app.
2. Open **Settings › Sync and backup file** and tap **Join from another device**.
3. Choose the same cloud folder, type the sync code, and tap **Join and sync**.

Your records, invoice PDFs and documents arrive on the new device. Saved passwords (email,
Nextcloud, the AI assistant) come too, so you don't type them again.

## Day to day

You don't need to do anything. Locuvi syncs:

- a few seconds after you change something
- every five minutes while it's open
- when you tap **Sync now**

If two devices change the same thing while offline, Locuvi keeps both changes where it can,
for example a new address on one device and a new phone number on the other. Where both
changed the same detail, the most recent change wins. Nothing is deleted just because
another device didn't have it yet.

## Invoice numbers

Invoice numbers must run in order without repeats. So before an invoice or credit note gets
its number, Locuvi checks with your other devices. This needs the internet for a moment.
Offline, you can still prepare drafts, record work and payments, and look everything up;
only the final **Issue** step waits until you're back online. Your draft is kept.

An issued invoice never changes, on any device.

## Everything in one file

**Settings › Sync and backup file › Everything in one file** downloads all your records,
invoices and documents as one locked `.locuvi` file. Choose a password of at least 12
characters; you need it to open the file again, and it can't be recovered.

Use the file as an extra backup, to move to a new computer, or to bring records into a
Locuvi that isn't syncing. **Add from file** never deletes anything on the device. Where both
have the same record, the file's version is kept.

## What stays on one device

These stay on the device where you set them up:

- the email accounts Locuvi reads booking emails from, so two computers never file the same
  email twice;
- your sign-in password;
- the calendar subscription link and agent tokens, which point at that device.

## Questions

<details>
<summary><b>Can Google, Microsoft, Dropbox or Apple read my records?</b></summary>

No. Everything in the sync folder is encrypted with your sync code before it leaves your
device. They only see files with meaningless names.
</details>

<details>
<summary><b>It says "Another device has a newer Locuvi"</b></summary>

Update Locuvi on this device ([apps](APPS.md#your-records-backups-and-updates)), then sync.
</details>

<details>
<summary><b>It says "Your other device is issuing an invoice right now"</b></summary>

Wait a minute and tap **Issue** again. This only happens if two devices issue at the same
moment.
</details>

<details>
<summary><b>How do I stop syncing?</b></summary>

Tap **Stop syncing on this device**. Its records stay on it; the sync folder and your other
devices are left as they are.
</details>
