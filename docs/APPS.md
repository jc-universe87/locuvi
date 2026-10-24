# Locuvi on your computer, phone and tablet

Every version of Locuvi shows the same app, with all your records and every feature. You can
use it in three ways:

- **On a Windows PC or Mac.** Install the desktop app and Locuvi runs on that computer. Your
  records are kept there. You don't need a server, Docker or any typing in a terminal.
- **On a server.** Locuvi runs on a computer that stays switched on, such as a mini PC,
  Raspberry Pi or NAS ([Setting up Locuvi](SETUP.md)).
- **On a phone or tablet.** The whole of Locuvi runs on the phone itself, with its records
  kept on the phone, and it works without the internet. [Sync](SYNC.md) keeps the same records
  on your phone and computer. If you prefer, the phone can connect to the Locuvi on your
  computer or server instead.

| Device | Download | Needs |
| --- | --- | --- |
| 🪟 Windows PC | [**Locuvi-Windows-Setup.exe**](https://github.com/jc-universe87/locuvi/releases/latest/download/Locuvi-Windows-Setup.exe) | Windows 10 or 11 (64-bit) |
| 🍎 Mac | [**Locuvi-macOS.dmg**](https://github.com/jc-universe87/locuvi/releases/latest/download/Locuvi-macOS.dmg) | Apple silicon (M1 or newer), macOS 12 or newer |
| 🤖 Android phone or tablet | [**Locuvi-Android.apk**](https://github.com/jc-universe87/locuvi/releases/latest/download/Locuvi-Android.apk) | Android 10 or newer |
| 📱 iPhone or iPad | [**Open in Safari**](https://locuvi.pistio.co.uk/), then [Add to Home Screen](#iphone-and-ipad) | iOS or iPadOS 16.4 or newer |

All the versions are listed on the [releases page](https://github.com/jc-universe87/locuvi/releases).
Each one was built and tested automatically on its own system before it was published.

**Contents**
[Windows](#windows) · [Mac](#mac) · [Android](#android) · [iPhone and iPad](#iphone-and-ipad) ·
[Using your phone with the desktop app](#using-your-phone-with-the-desktop-app) ·
[Your records, backups and updates](#your-records-backups-and-updates) ·
[Why the warnings?](#why-the-warnings)

---

## Windows

1. Download [**Locuvi-Windows-Setup.exe**](https://github.com/jc-universe87/locuvi/releases/latest/download/Locuvi-Windows-Setup.exe)
   and open it.
2. Windows may say **"Windows protected your PC"**. Click **More info**, then **Run anyway**.
   ([Why?](#why-the-warnings))
3. Click **Install**. It installs for you alone, so you don't need an administrator password.
4. Locuvi opens in its own window and signs you in by itself. Answer the three welcome
   questions and you're ready.

When you've finished, just close the window. Locuvi sends your latest changes to
[sync](SYNC.md) and stops by itself a few minutes later. Next time, open Locuvi from the
Start menu. (**Settings › Phones, tablets and computers** also has **Quit Locuvi**, to stop it
straight away, and **Show my Locuvi folder**.)

## Mac

1. Download [**Locuvi-macOS.dmg**](https://github.com/jc-universe87/locuvi/releases/latest/download/Locuvi-macOS.dmg)
   and open it.
2. Drag **Locuvi** onto **Applications**.
3. Open Locuvi from your Applications folder. The first time, your Mac says it can't check
   Locuvi for malicious software. Click **Done** (or **OK**). Then:
   - open **System Settings › Privacy & Security**
   - scroll down to "Locuvi was blocked…" and click **Open Anyway**
   - confirm with your Mac password or Touch ID

   You only do this once. ([Why?](#why-the-warnings))
4. Locuvi opens in its own window and signs you in by itself.

As on Windows, close the window when you've finished: Locuvi stops by itself a few minutes
later.

> [!NOTE]
> The Mac app is for Macs with Apple silicon (M1, M2, M3, M4 and newer). On an older Intel
> Mac, run Locuvi on a server instead ([Setting up Locuvi](SETUP.md)) and open it in Safari.

## Android

The Android app has the whole of Locuvi inside it. Your records are kept on the phone.

1. On your phone or tablet, download [**Locuvi-Android.apk**](https://github.com/jc-universe87/locuvi/releases/latest/download/Locuvi-Android.apk)
   and open it from your notifications or the **Files** app.
2. Android asks whether to allow installs from this source (Chrome or Files). Tap
   **Settings**, switch on **Allow from this source**, and go back.
3. Tap **Install**. If Google Play Protect warns that it doesn't recognise the app, tap
   **More details**, then **Install anyway**. ([Why?](#why-the-warnings))
4. Open Locuvi. The first start takes a few seconds while it sets itself up, then you see the
   three welcome questions.

Downloads, such as invoice PDFs and pension figures, are saved in **Downloads › Locuvi** on
your phone, and open straight away. Links to PCSE Online, GOV.UK and calendar subscriptions
open in your browser or calendar app.

To use the Locuvi on your computer or server instead, go to **Settings › Phones, tablets and
computers** and tap **Connect to a computer or server instead**, then type its address
([where to find it](#using-your-phone-with-the-desktop-app)). **Use Locuvi on this phone
instead** switches back.

## iPhone and iPad

Apple only lets you install apps from the App Store, and putting an app there needs a paid
Apple developer account. Locuvi works just as well from your Home Screen instead:

1. On your iPhone or iPad, open <https://locuvi.pistio.co.uk/> in **Safari**.
2. Tap the **Share** button (the square with an arrow), then **Add to Home Screen**, then
   **Add**.
3. Open Locuvi from its new icon. The first start downloads Locuvi once (about 30 MB, so use
   Wi-Fi) and takes a few seconds; after that it opens without the internet.

Locuvi now has its own icon and opens full screen, like an app. The whole of Locuvi runs on
the iPhone or iPad, and your records are kept there. Downloads go to the **Files** app.

> [!IMPORTANT]
> Always open Locuvi from the Home Screen icon. Safari in a normal tab keeps a separate copy,
> and Apple may clear what a Safari tab stores if you don't visit for a few weeks; the Home
> Screen app is kept. Turn on [sync](SYNC.md), or save [everything in one
> file](SYNC.md#everything-in-one-file) now and then, so a lost phone never loses records.

If you'd rather use the Locuvi on your computer or server, open its address in Safari instead
and add that to your Home Screen.

## What phones and tablets can't do yet

On an iPhone, iPad or Android phone, Locuvi has everything (diary, invoices, payments, bank
statements, pension forms, reports, the Inbox, Recently deleted) **except**:

- **the AI assistant**: bookings you paste are still read and added, by Locuvi's own rules;
- **reading booking emails, and sending invoices by email**: download the PDF and share it
  from the Files app or your email app instead;
- **connecting another AI assistant** to Locuvi;
- **copies of your invoices in Nextcloud**;
- **a calendar subscription**: you can still download your sessions as a calendar file;
- **sync through iCloud Drive or OneDrive**: a Dropbox or Google Drive account, or
  Nextcloud, works ([how](SYNC.md#phones-and-tablets)); otherwise,
  move records with [Everything in one file](SYNC.md#everything-in-one-file).

A phone app can't open these connections the way a computer can, so they work in the Locuvi
app for Windows and Mac. Some of them may come to phones and tablets in a future update.
Locuvi shows this same list in **Settings** on a phone.

## How the iPhone and iPad version is kept safe

- Only the app itself comes from `locuvi.pistio.co.uk`, the same files for everyone. Your
  records are kept on your iPhone or iPad and never sent there, to GitHub or to anyone else.
- The site has its own address, so no other website can read what Locuvi stores.
- The page carries strict browser rules: it may only load code from its own address, so
  nothing from another site can run inside it. The only other place it connects to is your
  Nextcloud, over `https://`, when you [sync](SYNC.md#phones-and-tablets).
- Because the page updates itself, its safety also depends on the accounts that publish it
  (GitHub and Cloudflare), which are protected with two-step sign-in. If you'd rather have
  updates only when you choose to install them, use the Android or desktop app.

## Using your phone with the desktop app

When Locuvi runs on your Windows PC or Mac, your phone and tablet can use it too, over your
home Wi-Fi.

1. **Choose your own password first.** On the computer, go to **Settings › Password**. The
   desktop app signs you in by itself, so you've never needed one. Your phone will ask for it.
2. Go to **Settings › Phones, tablets and computers** and switch on **Let my phone and tablet
   connect**.
3. Tap **Quit Locuvi** on the same page, then open Locuvi again. From now on Locuvi keeps
   running after you close its window, so your phone can connect; quit it there when you're
   done.
4. On Windows, a **Windows Security** message asks whether Locuvi may use your network. Tick
   **Private networks** and click **Allow**. On a Mac, click **Allow** if asked.
5. The same settings page now lists your computer's address, for example
   `http://192.168.1.20:8765`. Type it into the Android app, or open it in Safari on your
   iPhone or iPad.

Your phone can reach Locuvi only while:

- the computer is switched on and Locuvi is open
- the phone is on the same Wi-Fi

To use Locuvi when you're out, run it on a server with Tailscale
([Setting up Locuvi](SETUP.md#option-b-anywhere-with-tailscale-recommended)).

> [!TIP]
> If the address stops working after your router restarts, look it up again in
> **Settings › Phones, tablets and computers**. Your router can give the computer a new one.
> Many routers let you "reserve" an address for a computer so it never changes.

## Your records, backups and updates

**Where your records are.** The desktop app keeps everything in your Locuvi folder:

- **Windows:** `%LOCALAPPDATA%\Locuvi`. Paste that into File Explorer's address bar.
- **Mac:** `~/Library/Application Support/Locuvi`. In Finder, choose **Go › Go to Folder…**
  and paste it.

You can also click **Show my Locuvi folder** in **Settings › Phones, tablets and computers**.
The folder has your
database and PDFs (`data`), the key that protects your saved passwords (`keys`), backups
(`backups`) and a log for troubleshooting (`logs`).

**Backups.** Locuvi backs itself up every night while it's open, and before every update,
into the `backups` folder. Those backups are on the same computer, so also keep a copy
somewhere else: now and then, copy the `backups` folder to a USB stick, or to a folder that
Google Drive, OneDrive, Dropbox or iCloud Drive keeps in step. A computer can be lost, stolen
or broken.

**Updates.** Locuvi updates itself. There's nothing to do:

- **Windows and Mac:** every few hours Locuvi looks for a new version and downloads it. It
  installs when you close Locuvi, so it's new the next time you open it. If you can't wait,
  the note at the top has **Update now**: Locuvi closes, installs the new version and opens
  again in about a minute. If Locuvi stays on for your phone, it installs at night once
  nobody has had its window open for half an hour, and carries on. **Settings › Phones,
  tablets and computers › Updates** has **Check for updates**, and the **Update by itself**
  switch. On a Mac, Locuvi must be in your **Applications** folder to update itself.
- **Android:** the app looks for a new version once a day. The first time, it asks: tap
  **Update**, then **Install** (and, if Android asks, switch on **Allow from this source** for
  Locuvi and go back). After that, updates install by themselves a couple of minutes after
  you leave Locuvi; the next time you open it, it's new. This needs Android 12 or newer; on
  older phones Locuvi asks each time.
- **iPhone and iPad:** the new version downloads in the background and starts the next time
  you come back to Locuvi. **Restart Locuvi** at the top starts it straight away.

Each update is the exact file published on the [releases page](https://github.com/jc-universe87/locuvi/releases),
checked before it's installed. Your records stay where they are, and Locuvi makes a backup
before it changes anything. You can still download and install a new version by hand, over
the old one.

> [!NOTE]
> **Android, once only:** versions up to 1.1.16 were each signed with a different key, so
> Android can't update them in place and says **App not installed**. Sync first (or save
> [Everything in one file](SYNC.md#everything-in-one-file)), uninstall Locuvi, install the
> new version, and join sync again. From then on, updates install with one tap.

**Uninstalling** the desktop app leaves your Locuvi folder in place. Delete that folder too
only if you really want your records gone.

## Why the warnings?

Windows, macOS and Android warn about apps that haven't been registered with Microsoft, Apple
or Google. Registering costs money every year, and Locuvi is a free project, so the warnings
don't mean anything is wrong. Every file on the releases page is built from the public code by
GitHub, tested on its own system, and published by the project's release workflow
([`.github/workflows/release.yml`](../.github/workflows/release.yml)). You can read exactly
how.

---

Something not working? See [Troubleshooting](TROUBLESHOOTING.md#apps).
