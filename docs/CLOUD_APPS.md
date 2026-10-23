# Setting up Dropbox, Google Drive and OneDrive sign-in

*For the person who publishes Locuvi.* Everyone else just picks an account in
**Settings › Sync and backup file**.

Locuvi can sync through a Dropbox, Google Drive or OneDrive **account**: people sign in once on
each device, so phones and tablets don't need the company's app. Each company only lets an app
offer this once it has been registered under someone's account. Locuvi has no server of its
own, so the registrations below are all there is: they identify Locuvi when people sign in and
give no access to anyone's files.

Do each one once, then put the IDs in [`backend/locuvi/cloud_apps.py`](../backend/locuvi/cloud_apps.py).
A provider without an ID simply isn't offered.

All three send people back to the same page on Locuvi's site, which passes the sign-in on to
the computer, Android app or iPhone that asked:

```
https://locuvi.pistio.co.uk/oauth.html
```

**Contents**
[Dropbox](#dropbox) · [Google Drive](#google-drive) · [OneDrive](#onedrive) ·
[What each company gets](#what-each-company-gets) · [Limits](#limits)

---

## Dropbox

At [dropbox.com/developers/apps](https://www.dropbox.com/developers/apps):

1. **Create app** → **Scoped access** → **App folder** → a name such as *Locuvi Sync* (it must
   be unique across Dropbox; people see it as the folder **Apps › Locuvi Sync**).
2. **Settings** tab:
   - **Redirect URIs**: add `https://locuvi.pistio.co.uk/oauth.html`
   - **Allow public clients (Implicit Grant & PKCE)**: **Allow**
3. **Permissions** tab: tick `files.metadata.read`, `files.content.read`, `files.content.write`
   and `account_info.read`, then **Submit**.
4. Copy the **App key** into `DROPBOX_APP_KEY`. The app secret isn't needed.

A new Dropbox app can be used by up to 500 people; for more, use **Apply for production** on
the same page.

## Google Drive

At [console.cloud.google.com](https://console.cloud.google.com):

1. Create a project called *Locuvi*. In **APIs & Services › Library**, find **Google Drive API**
   and **Enable** it.
2. **Google Auth Platform**:
   - **Branding**: app name *Locuvi*, your support email, and the home page
     `https://github.com/jc-universe87/locuvi`.
   - **Audience**: **External**, then **Publish app**. While it says *Testing*, people have to
     sign in again every 7 days.
   - **Data access**: **Add or remove scopes** → `.../auth/drive.file` ("See, edit, create and
     delete only the specific Google Drive files you use with this app"). It needs no review
     by Google.
3. **Clients** → **Create client** → **Web application**:
   - **Authorised JavaScript origins**: `https://locuvi.pistio.co.uk`
   - **Authorised redirect URIs**: `https://locuvi.pistio.co.uk/oauth.html`
4. Copy the **Client ID** into `GOOGLE_CLIENT_ID` and the **Client secret** into
   `GOOGLE_CLIENT_SECRET`.

Google calls this a "secret", but in an app without a server it can't be kept secret: every
copy of Locuvi carries it. It only proves a sign-in came through Locuvi's registration; on its
own it opens nobody's files. If it is ever abused, make a new one in the same place.

## OneDrive

At [entra.microsoft.com](https://entra.microsoft.com) → **App registrations** → **New
registration** (with a personal Microsoft account you may first need a free Azure sign-up):

1. Name *Locuvi*. **Supported account types**: *Accounts in any organizational directory and
   personal Microsoft accounts*. **Redirect URI**: platform **Single-page application**,
   `https://locuvi.pistio.co.uk/oauth.html`. **Register**.
2. **Authentication** → **Add a platform** → **Mobile and desktop applications** → custom
   redirect URI `https://locuvi.pistio.co.uk/oauth-native.html`. Set **Allow public client
   flows** to **Yes**. **Save**.
3. **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated**:
   `Files.ReadWrite.AppFolder`, `offline_access`, `User.Read`.
4. Copy the **Application (client) ID** into `ONEDRIVE_CLIENT_ID`.

Two addresses, because Microsoft keeps a browser sign-in (the iPhone and iPad site) for 24 hours
only; the computer and Android app use the second one and stay signed in.

## What each company gets

Only Locuvi's own folder, holding the same encrypted sync folder as anywhere else
([Sync](SYNC.md)):

| Account | Where Locuvi keeps its files | What Locuvi can see |
| --- | --- | --- |
| Dropbox | **Apps › *your app name*** | That folder only |
| Google Drive | **My Drive › Locuvi Sync** | Only files Locuvi made |
| OneDrive | **Apps › Locuvi** | That folder only |

The files are encrypted with the sync code before they leave a device, so the company sees file
names and sizes, never records.

## Limits

- **OneDrive on iPhone and iPad** asks people to sign in again once a day (above). Dropbox,
  Google Drive or Nextcloud don't.
- **Google Drive** can't refuse a write that would land on a newer copy. Locuvi writes a new
  numbered copy each time and the first of two simultaneous copies wins, so nothing is lost, but
  Dropbox and OneDrive check this more directly.
- Signing in opens the company's page: on Android in the phone's browser, which then hands back
  to the app (tap **Back to Locuvi** if it asks).
