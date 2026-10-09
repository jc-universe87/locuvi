# Connecting your email (booking emails)

Locuvi can check chosen email folders for locum bookings and payment notices
(Settings › Booking emails). It only reads: nothing is marked as read, moved, sent or deleted.

| Account | How Locuvi connects | What you need |
| --- | --- | --- |
| Gmail | IMAP with an app password | 2-Step Verification on; an app password |
| Outlook.com, Hotmail, Live, Microsoft 365 | Microsoft sign-in (read-only) | Your own Microsoft app ID (one-off, below) |
| NHSmail | Microsoft sign-in (read-only) | App ID **and** approval by NHSmail (see below) |
| iCloud, Fastmail, others | IMAP with an app password | Server name and app password |

## Gmail

1. Turn on 2-Step Verification for your Google account.
2. Go to <https://myaccount.google.com/apppasswords>, create an app password called "Locuvi"
   and copy the 16 letters.
3. In Locuvi choose **Gmail**, enter your Gmail address and the app password, then
   **Connect and choose folders**. Gmail labels appear as folders. A label such as "Locum"
   (with a Gmail filter that applies it) works best.

## Outlook, Hotmail and Microsoft 365

Microsoft no longer accepts passwords for IMAP, so Locuvi signs in through Microsoft instead.
For that, Microsoft needs to know the app: you register it once, for free, in your own
Microsoft account. Locuvi asks only for `Mail.Read` (read mail), `User.Read` (your address)
and `offline_access` (stay signed in).

1. Open <https://entra.microsoft.com> (or <https://portal.azure.com>) and sign in. A personal
   Microsoft account works; Microsoft may ask you to create a free directory first.
2. **App registrations › New registration**
   - Name: `Locuvi`
   - Supported account types: **Accounts in any organizational directory and personal
     Microsoft accounts**
   - Redirect URI: leave empty. Click **Register**.
3. On the app's page, copy the **Application (client) ID**.
4. **Authentication › Advanced settings › Allow public client flows: Yes**, then **Save**.
5. **API permissions › Add a permission › Microsoft Graph › Delegated permissions**: tick
   `Mail.Read`, `User.Read` and `offline_access`, then **Add permissions**.
6. In Locuvi choose **Outlook, Hotmail or Microsoft 365**, paste the app ID and tap
   **Sign in with Microsoft**. Open the Microsoft page, enter the code shown and approve.
   Then choose the folders to read.

No secret or password is stored in the app registration, and Locuvi never sees your
Microsoft password. Locuvi keeps the sign-in token encrypted on your server. **Sign out** in
Locuvi removes it; you can also remove "Locuvi" at <https://myapps.microsoft.com> or
<https://account.live.com/consent/Manage>.

## NHSmail

NHSmail is a Microsoft 365 service run for NHS England, and it only allows apps that its
administrators have approved. Use the same steps as for Outlook, choosing **NHSmail**.
If Microsoft says that an administrator must approve the app ("Need admin approval"), the
app has not been approved for NHSmail. You then have two choices:

- **Forward booking emails to Gmail** and connect Gmail. Forward individual emails by hand,
  or ask your organisation whether a forwarding rule is allowed: NHSmail and local
  information-governance rules may restrict automatic forwarding outside NHSmail.
  Booking emails rarely contain patient details, but check before you forward.
- **Ask for approval** through your local NHSmail administrator, quoting the app ID and the
  read-only permissions above.

Locuvi never forwards or sends anything by itself.

## Other providers (IMAP)

Choose **Other (IMAP)** and enter the IMAP server (for example `imap.mail.me.com` for
iCloud or `imap.fastmail.com`), your address and an app password from your provider.
