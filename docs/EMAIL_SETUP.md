# Connecting your email

Locuvi can check chosen email folders for **booking emails** and **payment notices**, and
show you the sessions to add to your Diary.

> [!NOTE]
> Locuvi **only reads**. It never sends, moves, deletes or marks anything as read, and it only
> looks in the folders you choose.

<img src="images/settings-mailbox.png" alt="Settings › Booking emails, where you add email accounts">

Open **Settings › Booking emails** and tap **Add an email account**. You can add several, for
example your Gmail and your Outlook address. **Check for bookings now** checks them all;
otherwise Locuvi checks every hour.

> [!TIP]
> A folder (or Gmail label) called something like **Locum**, with a rule that files booking
> emails into it, works best. Locuvi then reads only those emails.

| Your email | How it connects | What you need |
| --- | --- | --- |
| **Gmail** | An "app password" | 5 minutes ([steps](#gmail)) |
| **Outlook, Hotmail, Live, Microsoft 365** | Sign in with Microsoft | 10 minutes, once ([steps](#outlook-hotmail-and-microsoft-365)) |
| **NHSmail** | Sign in with Microsoft | Approval from NHSmail ([read this](#nhsmail)) |
| **iCloud, Fastmail, others** | An "app password" | 5 minutes ([steps](#other-email-providers)) |

## Gmail

An **app password** is a separate password that lets one app read your email. It doesn't
reveal your real Google password, and you can cancel it at any time.

1. Make sure **2-Step Verification** is on for your Google account
   (<https://myaccount.google.com/security>).
2. Go to <https://myaccount.google.com/apppasswords>, create an app password called
   **Locuvi** and copy the 16 letters.
3. In Locuvi choose **Gmail**, type your Gmail address, paste the app password and tap
   **Connect and choose folders**. Your Gmail labels appear as folders: tick the ones with
   locum emails.

## Outlook, Hotmail and Microsoft 365

Microsoft doesn't let apps use your password, so Locuvi asks you to **sign in with Microsoft**
instead. For that, Microsoft needs to know about Locuvi. You tell it once, for free, in your
own Microsoft account. It looks technical but is mostly clicking through.

1. Go to <https://entra.microsoft.com> and sign in. (A personal Outlook/Hotmail account works;
   Microsoft may ask you to create a free "directory" first. Follow its prompts.)
2. Click **App registrations › New registration** and fill in:
   - **Name**: `Locuvi`
   - **Supported account types**: *Accounts in any organizational directory and personal
     Microsoft accounts*
   - **Redirect URI**: leave empty

   Click **Register**.
3. Copy the **Application (client) ID**: a long code like `1a2b3c4d-…`.
4. Click **Authentication**. Under **Advanced settings**, set **Allow public client flows** to
   **Yes**, then **Save**.
5. Click **API permissions › Add a permission › Microsoft Graph › Delegated permissions**.
   Tick `Mail.Read`, `User.Read` and `offline_access`, then **Add permissions**.
   (These mean: read mail, know your address, and stay signed in.)
6. In Locuvi choose **Outlook, Hotmail or Microsoft 365**, paste the ID and tap
   **Sign in with Microsoft**. Open the Microsoft page shown, type the code Locuvi gives you and
   approve. Then tick the folders to read.

Locuvi never sees your Microsoft password. It keeps only a sign-in pass, encrypted on your
server. **Sign out** in Locuvi deletes it. You can also remove Locuvi's access at
<https://myapps.microsoft.com> (work accounts) or <https://account.live.com/consent/Manage>
(personal accounts).

## NHSmail

NHSmail runs on Microsoft 365, but only allows apps that its administrators have approved.
Follow the [Outlook steps](#outlook-hotmail-and-microsoft-365) and choose **NHSmail**.

If Microsoft says **"Need admin approval"**, NHSmail hasn't approved the app. You can either:

- **Forward booking emails to Gmail**, and connect Gmail. Forward them one by one, or ask your
  organisation whether an automatic forwarding rule is allowed. NHSmail and local information
  governance rules may restrict forwarding outside NHSmail. Booking emails rarely contain
  patient details, but check before you forward.
- **Ask for approval** through your local NHSmail administrator, quoting the app ID and the
  read-only permissions above.

## Other email providers

Choose **Other (IMAP)** and enter:

- the **IMAP server**: for example `imap.mail.me.com` (iCloud) or `imap.fastmail.com` (Fastmail).
  Your provider's help pages list it under "IMAP settings".
- your **email address**
- an **app password** from your provider (iCloud: <https://account.apple.com> › Sign-In and
  Security › App-Specific Passwords).

---

**Something not working?** The account shows its last check and any problem in
**Settings › Booking emails**. The most common fix is to create a new app password, or sign in
with Microsoft again.
