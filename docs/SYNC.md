# Sync and the backup file

Sync keeps the same records on every device you use Locuvi on. Each device keeps its own full
copy, so Locuvi works without the internet. The copies meet in a **sync folder** in cloud
storage you already have, and the folder is locked with a **sync code** that only your
devices know.

**Contents**
[What you need](#what-you-need) · [Start syncing](#start-syncing) ·
[Add another device](#add-another-device) · [Cloud accounts](#cloud-accounts) ·
[Nextcloud](#nextcloud) ·
[Phones and tablets](#phones-and-tablets) · [Day to day](#day-to-day) ·
[Invoice numbers](#invoice-numbers) · [Everything in one file](#everything-in-one-file) ·
[What stays on one device](#what-stays-on-one-device) · [Questions](#questions)

---

## What you need

One of these:

- **Google Drive, OneDrive, Dropbox or iCloud Drive**, with its app installed and signed in
  on your computer. Locuvi keeps its sync folder inside the folder that app looks after.
- **A Dropbox or Google Drive account**, signed in once on each device. No app
  needed, so this works on phones and tablets too ([Cloud accounts](#cloud-accounts)).
- **Nextcloud**: your own, or one from work ([Nextcloud](#nextcloud)).

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

## Cloud accounts

Choose **Dropbox account** or **Google Drive account**, then **Sign in to
… and start** (or **join**). The company's own sign-in page opens; sign in and allow Locuvi.
You come back to Locuvi and sync starts. On Android the sign-in opens in your browser: when
it's done, tap **Back to Locuvi** if Locuvi doesn't open by itself.

Locuvi only gets its own folder: **Apps** in Dropbox, **Locuvi Sync** in Google
Drive, where it can only see files it made itself. Everything in it is encrypted with your sync
code. You stay signed in; if the company ever signs Locuvi out, sync says so and you sign in
again.

> [!NOTE]
> Accounts work in the Locuvi apps for Windows, Mac and Android and on iPhone and iPad. For
> OneDrive, use the OneDrive folder on a computer ([above](#what-you-need)); on a phone, use
> a Dropbox or Google Drive account, or Nextcloud.

**Your own app key.** A practice or its IT person can register Locuvi with Dropbox, Google
or Microsoft themselves ([how](CLOUD_APPS.md#your-own-app-key)) and paste the key under
**Use your own app key** when starting or joining. That also makes OneDrive accounts
possible. Use the same key on every device.

## Nextcloud

Choose **Nextcloud** when you start or join, then fill in:

- **Nextcloud address**: the address you use from anywhere, for example `cloud.example.uk`.
  You can also paste the full WebDAV address from Nextcloud (**Files › Files settings ›
  WebDAV**).
- **Address at home or work** (optional): if your Nextcloud also has an address on your home
  or office network, such as `http://192.168.1.20` or `http://nas.local`, add it too. Each
  sync uses whichever address answers, so it works both at home and when you're out. This
  address may start with `http://` because it stays on your own network.
- **Nextcloud user name** and an **app password**. Make the app password in Nextcloud:
  **Settings › Security › Devices & sessions › Create new app password**. Don't use your
  normal password; you can withdraw an app password at any time.

Locuvi keeps everything in a folder called `Locuvi/Locuvi Sync` in your Nextcloud, encrypted
with your sync code, so even the Nextcloud's owner can't read your records.

## Phones and tablets

On a phone or tablet, Locuvi syncs through a [cloud account](#cloud-accounts) (Dropbox or
Google Drive) or Nextcloud. A cloud *folder* on a computer (from the Dropbox or
Google Drive app) is the same sync folder, so a computer using the Dropbox app and a phone
signed in to the same Dropbox account don't meet: use the account on both, or Nextcloud.

- **Android:** works with any Nextcloud, including one from work, at its usual address or
  its home network address. The Android app connects to Nextcloud itself, so nothing needs
  changing on the server.
- **iPhone and iPad:** Locuvi runs in Safari, and Safari only lets a website use another
  site, such as your Nextcloud, if that site allows it. So the Nextcloud must allow Locuvi's
  address, `https://locuvi.pistio.co.uk`, and the iPhone must reach it by an `https://`
  address. If you run your own Nextcloud, follow
  [Let iPhones and iPads connect](#let-iphones-and-ipads-connect) below. With a Nextcloud
  from work, ask its IT team.

If Nextcloud doesn't allow Locuvi yet, joining stops with *"Nextcloud can't be reached from
this phone… your Nextcloud must also allow Locuvi"*, and nothing changes on the phone.

### Let iPhones and iPads connect

This is for people who run their own Nextcloud. It lets one website,
`https://locuvi.pistio.co.uk`, use your Nextcloud's WebDAV address (`/remote.php/dav/`).
Your app password is still needed for everything, as before. In web terms, it's a CORS rule
for that one origin: answer the preflight `OPTIONS` request, allow the WebDAV methods and
headers Locuvi uses, and expose `ETag`.

**nginx in front of Nextcloud** (a reverse proxy). In the `http` block:

```nginx
map $http_origin $locuvi_origin {
    default "";
    "https://locuvi.pistio.co.uk" $http_origin;
}
map "$request_method $http_origin" $locuvi_preflight {
    default 0;
    "OPTIONS https://locuvi.pistio.co.uk" 1;
}
```

and in your Nextcloud's `server` block, next to its `location /`:

```nginx
location /remote.php/dav/ {
    if ($locuvi_preflight) {
        add_header Access-Control-Allow-Origin "https://locuvi.pistio.co.uk" always;
        add_header Access-Control-Allow-Methods "GET, PUT, DELETE, MKCOL, MOVE, PROPFIND, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Authorization, Content-Type, Depth, Destination, Overwrite, If-Match, If-None-Match" always;
        add_header Access-Control-Max-Age 600 always;
        return 204;
    }
    add_header Access-Control-Allow-Origin $locuvi_origin always;
    add_header Access-Control-Expose-Headers "ETag" always;
    add_header Vary "Origin" always;
    # …then the same proxy_pass and proxy_set_header lines as your "location /"
}
```

**Apache** (for example the `nextcloud:apache` Docker image), in the Nextcloud site's
configuration, with `mod_headers` and `mod_rewrite` on:

```apache
SetEnvIf Origin "^https://locuvi\.pistio\.co\.uk$" LOCUVI_ORIGIN
<LocationMatch "^/remote\.php/dav/">
    Header always set Access-Control-Allow-Origin "https://locuvi.pistio.co.uk" env=LOCUVI_ORIGIN
    Header always set Access-Control-Allow-Methods "GET, PUT, DELETE, MKCOL, MOVE, PROPFIND, OPTIONS" env=LOCUVI_ORIGIN
    Header always set Access-Control-Allow-Headers "Authorization, Content-Type, Depth, Destination, Overwrite, If-Match, If-None-Match" env=LOCUVI_ORIGIN
    Header always set Access-Control-Expose-Headers "ETag" env=LOCUVI_ORIGIN
    Header always merge Vary "Origin"
</LocationMatch>
RewriteEngine On
RewriteCond %{REQUEST_METHOD} OPTIONS
RewriteCond %{HTTP:Origin} "^https://locuvi\.pistio\.co\.uk$"
RewriteRule "^/remote\.php/dav/" - [R=204,L]
```

If you'd rather not edit the web server, the Nextcloud app **WebAppPassword** can add CORS
rules for WebDAV from Nextcloud's own settings: add `https://locuvi.pistio.co.uk` to its
allowed origins.

To check, run this from any computer (with your address). The answer should be
`HTTP/… 204` and include `access-control-allow-origin: https://locuvi.pistio.co.uk`:

```bash
curl -si -X OPTIONS https://cloud.example.uk/remote.php/dav/files/USER/ \
  -H "Origin: https://locuvi.pistio.co.uk" -H "Access-Control-Request-Method: PROPFIND" \
  -H "Access-Control-Request-Headers: authorization,depth"
```

Locuvi's own tests check the phone app against a stand-in Nextcloud that follows exactly
these rules ([`e2e/fake_nextcloud.py`](../e2e/fake_nextcloud.py)), and against one that
doesn't.

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
<summary><b>Can my Nextcloud's owner, or my company, read my records?</b></summary>

No. They can see that a `Locuvi Sync` folder exists and how big it is, but everything in it is
encrypted with your sync code.
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
