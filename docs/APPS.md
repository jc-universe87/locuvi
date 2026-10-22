# Locuvi on your computer, phone and tablet

Every version of Locuvi shows the same app, with all your records and every feature. You can
use it in three ways:

- **On a Windows PC or Mac.** Install the desktop app and Locuvi runs on that computer. Your
  records are kept there. You don't need a server, Docker or any typing in a terminal.
- **On a server.** Locuvi runs on a computer that stays switched on, such as a mini PC,
  Raspberry Pi or NAS ([Setting up Locuvi](SETUP.md)).
- **On a phone or tablet.** Your phone connects to your Locuvi, either the desktop app or a
  server. The records stay on that computer, not on the phone, so losing a phone doesn't lose
  anything.

| Device | Download | Needs |
| --- | --- | --- |
| 🪟 Windows PC | [**Locuvi-Windows-Setup.exe**](https://github.com/jc-universe87/locuvi/releases/latest/download/Locuvi-Windows-Setup.exe) | Windows 10 or 11 (64-bit) |
| 🍎 Mac | [**Locuvi-macOS.dmg**](https://github.com/jc-universe87/locuvi/releases/latest/download/Locuvi-macOS.dmg) | Apple silicon (M1 or newer), macOS 12 or newer |
| 🤖 Android phone or tablet | [**Locuvi-Android.apk**](https://github.com/jc-universe87/locuvi/releases/latest/download/Locuvi-Android.apk) | Android 10 or newer |
| 📱 iPhone or iPad | No download: [add it to your Home Screen](#iphone-and-ipad) | Safari |

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

A small **Locuvi** window also appears. Keep it open while you use Locuvi, because closing it
stops Locuvi. It has buttons to open Locuvi again and to show your Locuvi folder.

Next time, open Locuvi from the Start menu.

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

The small **Locuvi** window works as on Windows: keep it open while you use Locuvi.

> [!NOTE]
> The Mac app is for Macs with Apple silicon (M1, M2, M3, M4 and newer). On an older Intel
> Mac, run Locuvi on a server instead ([Setting up Locuvi](SETUP.md)) and open it in Safari.

## Android

The Android app connects to your Locuvi, either the desktop app or a server.

1. On your phone or tablet, download [**Locuvi-Android.apk**](https://github.com/jc-universe87/locuvi/releases/latest/download/Locuvi-Android.apk)
   and open it from your notifications or the **Files** app.
2. Android asks whether to allow installs from this source (Chrome or Files). Tap
   **Settings**, switch on **Allow from this source**, and go back.
3. Tap **Install**. If Google Play Protect warns that it doesn't recognise the app, tap
   **More details**, then **Install anyway**. ([Why?](#why-the-warnings))
4. Open Locuvi and type your Locuvi's address, for example `192.168.1.20:8765`, then tap
   **Connect**. The next section says where to find the address.

Downloads, such as invoice PDFs and pension figures, are saved in **Downloads › Locuvi** on
your phone, and open straight away. Links to PCSE Online, GOV.UK and calendar subscriptions
open in your browser or calendar app.

To connect to a different Locuvi later, go to **Settings › Phones, tablets and computers** in
the app and tap **Connect to a different Locuvi**.

## iPhone and iPad

Apple only lets you install apps from the App Store, and putting an app there needs a paid
Apple developer account. Locuvi works just as well from your Home Screen instead:

1. Open your Locuvi's address in **Safari**, for example `http://192.168.1.20:8765`.
2. Tap the **Share** button (the square with an arrow), then **Add to Home Screen**, then
   **Add**.

Locuvi now has its own icon and opens full screen, like an app. It has every feature,
including downloads, which go to the **Files** app.

## Using your phone with the desktop app

When Locuvi runs on your Windows PC or Mac, your phone and tablet can use it too, over your
home Wi-Fi.

1. **Choose your own password first.** On the computer, go to **Settings › Password**. The
   desktop app signs you in by itself, so you've never needed one. Your phone will ask for it.
2. Go to **Settings › Phones, tablets and computers** and switch on **Let my phone and tablet
   connect**.
3. Quit Locuvi from the small Locuvi window and open it again.
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

You can also click **Show my Locuvi folder** in the small Locuvi window. The folder has your
database and PDFs (`data`), the key that protects your saved passwords (`keys`), backups
(`backups`) and a log for troubleshooting (`logs`).

**Backups.** Locuvi backs itself up every night while it's open, and before every update,
into the `backups` folder. Those backups are on the same computer, so also keep a copy
somewhere else: now and then, copy the `backups` folder to a USB stick, or to a folder that
Google Drive, OneDrive, Dropbox or iCloud Drive keeps in step. A computer can be lost, stolen
or broken.

**Updates.** Download and install the newest version over the old one. Your records stay
where they are, and Locuvi makes a backup before it changes anything. On Android, install the
new APK over the old one. If Android says **App not installed**, uninstall Locuvi from the
phone and install the new one. Nothing is lost, because your records are on the computer.

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
