# Setting up Locuvi

This guide is for whoever installs and looks after Locuvi: you, a family member or an IT
helper. Each step says **what to type** and **what it does**. If you only use Locuvi, read the
[user guide](USER_GUIDE.md) instead.

**Contents**
[What you need](#what-you-need) ·
[Install](#install) ·
[Open it on your devices](#open-it-on-your-devices) ·
[Updates](#updates) ·
[Backups](#backups) ·
[Nextcloud copies](#nextcloud-copies-optional) ·
[Household profiles](#household-profiles) ·
[Forgotten password](#forgotten-password) ·
[How Locuvi keeps data safe](#how-locuvi-keeps-data-safe) ·
[Settings reference](#settings-reference)

---

## What you need

### Is self-hosting right for you?

Locuvi isn't a website you sign up to. It runs on **a computer you control**, so your
records never sit on someone else's servers. That computer is called the *server*. It needs
to stay switched on so Locuvi can make backups and check your email, and you open Locuvi from
your phone or laptop like a website.

If you're comfortable following step-by-step instructions and typing a few commands, you can
do this yourself in about 15 minutes. If not, ask a friend or IT helper to do this page once
for you: after that, everything happens in the app.

| Option | Good for | Notes |
| --- | --- | --- |
| **A spare PC or mini PC at home** running Linux (for example Ubuntu) | Most people | Quiet, low power, fully private |
| **Raspberry Pi 4 or 5** (4 GB or more, with an SSD or good SD card) | Low cost | ARM computers are supported |
| **A NAS** that runs Docker (for example Synology, QNAP, Unraid) | If you already have one | Use its terminal or Docker/Container app |
| **A small cloud server** (VPS) | If you have nowhere at home | Keep it private with Tailscale; never open the port to the internet |

### What to install

- **Docker** with Compose. Docker runs Locuvi in a sealed box, so you don't have to install
  anything else. Follow the official guide: <https://docs.docker.com/engine/install/>.
- **git**, to download Locuvi and its updates (on Ubuntu: `sudo apt install git`).
- About **1 GB** of disk space, plus room for backups.

> [!IMPORTANT]
> Locuvi is designed to be **private**. Out of the box, only the server itself can open it.
> Never put it directly on the public internet. To reach it from your phone, use
> [Tailscale](#option-b-anywhere-with-tailscale-recommended) or your home network.

## Install

Open a terminal on the server and run these commands one block at a time.

**1. Download Locuvi**

```bash
git clone https://github.com/pistio/locuvi.git locuvi
cd locuvi
cp .env.example .env
```

This downloads the setup files into a folder called `locuvi` and creates your settings file
(`.env`). The defaults are fine to start with.

**2. Choose the first sign-in password**

```bash
install -d -m 0700 secrets
( umask 022; printf '%s' 'choose-a-long-passphrase' > secrets/locuvi_password.txt )
```

Replace `choose-a-long-passphrase` with your own long password, for example four random
words. It is kept in a private file on the server, never in the app's code.

**3. Make a folder for backups**

```bash
sudo install -d -m 0700 -o 10001 -g 10001 backups
```

Locuvi writes a backup here every night. (`10001` is the user Locuvi runs as inside Docker.)

**4. Start it**

```bash
docker compose pull
docker compose up -d
docker compose ps
```

This downloads Locuvi and starts it in the background. Wait until `docker compose ps` shows
**healthy**. Locuvi starts again automatically after a power cut or restart.

<details>
<summary>If <code>docker compose pull</code> says "denied" or "unauthorized"</summary>

The Locuvi image is published on GitHub's container registry. If the image isn't public, log
in once with a GitHub token that can only read packages (GitHub → Settings → Developer
settings → Personal access tokens (classic) → tick only `read:packages`):

```bash
echo '<token>' | docker login ghcr.io -u <your-github-username> --password-stdin
```

The repository owner can remove this step for everyone by making the package public
(GitHub → Packages → gp-locum-manager → Package settings → Change visibility).
</details>

<details>
<summary>Behind a company proxy that inspects HTTPS?</summary>

Build the image yourself and give Docker the proxy's certificate:
`docker build --secret id=build_ca,src=/path/ca.pem -t locuvi:1.0.0 .` then
`docker compose up -d --no-build`.
</details>

**5. Sign in for the first time**

Open Locuvi (see the next section for how) and sign in with the password you chose in
step 2. Locuvi then asks three short questions: your details, your bank details and your
first practice. The [user manual](USER_GUIDE.md#3-your-first-five-minutes) walks you through
them.

> [!TIP]
> Change the password afterwards in **Settings › Password** if you like. The file in
> `secrets/` is only used for the very first sign-in and for [resetting a forgotten
> password](#forgotten-password).

## Open it on your devices

### Option A: on the server itself

Set `COOKIE_SECURE=false` in `.env`, run `docker compose up -d`, then open
<http://127.0.0.1:8000> in a browser on the server.

### Option B: anywhere, with Tailscale (recommended)

[Tailscale](https://tailscale.com) is a free private network between your own devices. Install
it on the server and on your phone and laptop, sign in with the same account, then on the
server run:

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:8000
```

Locuvi is now at `https://<server-name>.<your-tailnet>.ts.net`, with a proper padlock, from
any of your devices, at home or away, and from no one else's. Keep `COOKIE_SECURE=true`.

> [!WARNING]
> Don't use `tailscale funnel` or forward a port on your router. Both make Locuvi public.

### Option C: your home network only

To open it from any device on your home Wi-Fi, edit `.env`:

```bash
LOCUVI_BIND=192.168.1.20     # the server's address on your network (find it with: hostname -I)
LOCUVI_PORT=8767
COOKIE_SECURE=false          # plain http on the home network
```

Run `docker compose up -d` and open `http://192.168.1.20:8767`. Your password still protects
Locuvi, but plain http can be read by others on the same network, so only do this on a network
you trust. Use the server's own address (not `0.0.0.0`) and don't forward the port on your
router: that's what keeps it off the internet.

## Updates

Every improvement is tested automatically and then published. To update:

```bash
cd ~/locuvi        # or wherever you installed it
./update.sh
```

`update.sh` downloads the latest version, restarts Locuvi and waits until it's healthy.
Before changing anything in the database, Locuvi **makes a backup first**
(`backups/locuvi-…-before-NNNN.tar.gz`). If it can't (for example, the disk is full), it
refuses to start rather than risk your data: fix the cause and run `./update.sh` again.

<details>
<summary>Going back to an earlier version</summary>

1. Find the previous version's tag (like `sha-1a2b3c4`) on the package page and set it in
   `.env`: `LOCUVI_TAG=sha-1a2b3c4`.
2. Database changes only go forward, so restore the backup taken just before the update:

```bash
docker compose stop locuvi
docker compose run --rm --no-deps locuvi python -m locuvi.cli restore /backups/locuvi-…-before-NNNN.tar.gz --force
docker compose up -d
```

`LOCUVI_UPGRADE_WITHOUT_BACKUP=1` skips the safety backup deliberately; avoid it.
</details>

Your own extra settings that aren't part of Locuvi (such as the backup password below) go in
`docker-compose.override.yml`. Docker reads it automatically and updates never overwrite it.

## Backups

Locuvi **backs itself up every night after 2am** into the `backups` folder and keeps 30 days
(change with `BACKUP_KEEP_DAYS`). Each backup holds the database and every invoice PDF, and is
checked: if an issued PDF is missing or has been altered, the backup is refused and **Today**
tells you. **Today** also shows a **Back up now** button if a backup is missing or old.

### Keep an encrypted copy somewhere else (recommended)

A backup on the same server doesn't help if the server dies. Give Locuvi a backup password
and it will also save an **encrypted** copy to your Nextcloud every night:

```bash
( umask 022; openssl rand -base64 24 | tr -d '\n' > secrets/backup_passphrase.txt )
cat secrets/backup_passphrase.txt; echo     # copy this into your password manager NOW
cat > docker-compose.override.yml <<'YAML'
services:
  locuvi:
    secrets:
      - backup_passphrase
secrets:
  backup_passphrase:
    file: ./secrets/backup_passphrase.txt
YAML
docker compose up -d
```

> [!CAUTION]
> Keep the backup password somewhere other than the server, such as your password manager.
> Without it, the encrypted copies can't be opened by anyone, including you.

Copies go to `Locuvi/Backups/` in Nextcloud (set up [Nextcloud](#nextcloud-copies-optional)
first). Every night Locuvi also does a **restore drill**: it unpacks the newest copy in a
scratch folder and checks every PDF and the database, without touching your live data.
**Today** warns you if the drill or the upload fails. Old copies are never deleted from
Nextcloud; tidy them yourself when you like.

### Useful backup commands

```bash
docker compose exec locuvi python -m locuvi.cli backup /backups/manual.tar.gz   # back up now
docker compose exec locuvi python -m locuvi.cli drill                          # test the latest backup
docker compose exec locuvi python -m locuvi.cli verify                         # check everything is intact
```

Also keep a copy of the keys volume (it unlocks saved email, Nextcloud and AI passwords):

```bash
docker run --rm -v locuvi_locuvi-keys:/keys -v "$PWD/backups:/out" alpine tar czf /out/keys.tgz -C /keys .
```

If the keys are lost, invoices are safe; you just re-enter those passwords in Settings.

### Restoring

Backups are checked against their fingerprints before anything is written.

```bash
docker compose stop locuvi
docker compose run --rm --no-deps locuvi python -m locuvi.cli restore /backups/locuvi-2026-10-31-020000.tar.gz --force
docker compose up -d
docker compose exec locuvi python -m locuvi.cli verify     # should print {"ok": true, ...}
```

An encrypted `.tar.gz.enc` copy (for example downloaded from Nextcloud) restores the same way;
the password comes from the secret file, or add `--passphrase-file`. To unlock one by hand:
`python -m locuvi.cli decrypt locuvi-….tar.gz.enc out.tar.gz --passphrase-file pass.txt`.

### Where your data lives

| Docker volume | What's in it |
| --- | --- |
| `locuvi-data` → `/data` | The database (`locuvi.db`) and every issued invoice PDF: your records |
| `locuvi-keys` → `/keys` | The key that encrypts saved passwords, kept apart from the data on purpose |
| `./backups` → `/backups` | Nightly backups |

## Nextcloud copies (optional)

Locuvi can put a copy of every issued invoice PDF into your Nextcloud.

1. In Nextcloud: **Personal settings › Security › Devices & sessions › Create new app
   password**, named "Locuvi". Never use your main Nextcloud password.
2. In Nextcloud **Files › ⚙ Files settings**, copy the **WebDAV** address, like
   `https://cloud.example.org/remote.php/dav/files/USERNAME/`.
3. In Locuvi, **Settings › Nextcloud copies**: paste the address, your username and the app
   password, tap **Check Nextcloud connection**, then **Save and turn on**.

PDFs are saved as `Locuvi/Invoices/YYYY/MM/LOC-2026-0001.pdf`. Each upload is checked by
downloading it again and comparing fingerprints. Locuvi never overwrites a different file and
never deletes anything in Nextcloud. Each invoice page shows whether its copy is safely
stored, with a **Try saving to Nextcloud again** button. **Save previous invoices to Nextcloud** sends invoices issued
before you connected.

> [!NOTE]
> The Nextcloud copy of invoices is an archive, **not** a backup of Locuvi. For that, set up
> the [encrypted backup copy](#keep-an-encrypted-copy-somewhere-else-recommended).

<details>
<summary>Nextcloud on your own private network or Tailscale</summary>

For safety, Locuvi only connects to public HTTPS addresses unless you allow your own server
in `.env`:

```
WEBDAV_ALLOWED_PRIVATE_HOSTS=nextcloud.your-tailnet.ts.net,100.64.0.0/10
# only if that server has no HTTPS (not recommended):
WEBDAV_ALLOW_HTTP_FOR_ALLOWLISTED=true
```

You can also give the app password as a file: mount a secret at
`/run/secrets/locuvi_webdav_password` and set `WEBDAV_SECRET_FILE=/run/secrets/locuvi_webdav_password`.
</details>

## Household profiles

The first person (profile 1) is the **admin**. In **Settings › Profiles** they add others.
Each profile is a completely separate Locuvi with its own diary, practices, invoices and
numbering, pension figures, email accounts, calendar link and backups. With more than one
profile, everyone signs in with their **name** and password.

| | Where it's stored |
| --- | --- |
| Admin (profile 1) | `/data`, backups in `/backups` |
| Other profiles | `/data/profiles/<number>/`, backups in `/backups/profile-<number>/` |
| The list of profiles | `/data/profiles.db`, copied to `/backups/profiles.db` every night |

A removed profile is signed out at once and kept for 30 days (restorable in
**Settings › Profiles**), then deleted with its backups.

To run a command for another profile, point it at that profile's folders:

```bash
docker compose exec -e DATA_DIR=/data/profiles/2 -e BACKUP_DIR=/backups/profile-2 locuvi python -m locuvi.cli verify
```

After rebuilding a server, put `profiles.db` back as `/data/profiles.db` first, then restore
each profile's backup into its folder.

## Forgotten password

- **A household member** forgot theirs: the admin sets a new one in **Settings › Profiles**.
- **The admin** forgot theirs: reset it to the password in `secrets/locuvi_password.txt`:

```bash
docker compose exec locuvi python -m locuvi.cli reset-password                 # the admin
docker compose exec locuvi python -m locuvi.cli reset-password --profile Sam   # or someone else
docker compose restart locuvi
```

## How Locuvi keeps data safe

- **Private by default**: it only listens on the server itself unless you choose otherwise.
- **Passwords**: each profile's password is stored scrambled (scrypt), sign-in attempts are
  limited, and changing a password signs that person out everywhere.
- **Saved secrets** (email, Nextcloud and AI passwords and keys) are encrypted with a key kept
  apart from the database, never shown again, and never written to logs. Bank account numbers
  are masked on screen.
- **Locked-down container**: Locuvi runs as an ordinary user with a read-only system and no
  special permissions.
- **Your records are the truth**: issued invoices and their PDFs can't be changed, and are
  checked against their fingerprints every time Locuvi starts.
- **Nothing goes out without you**: no email is sent, no form submitted and no payment
  recorded without your tap. AI is optional and only suggests.

More detail: [docs/decisions/0002-auth-model.md](decisions/0002-auth-model.md).

## Settings reference

All settings go in `.env` (see `.env.example` for comments). The most useful:

| Setting | What it does | Default |
| --- | --- | --- |
| `LOCUVI_BIND`, `LOCUVI_PORT` | Which address and port Locuvi listens on | `127.0.0.1`, `8000` |
| `COOKIE_SECURE` | `true` with HTTPS (Tailscale), `false` with plain http | `true` |
| `LOCUVI_TAG` | Which version to run | `latest` |
| `BACKUP_KEEP_DAYS` | How many days of nightly backups to keep | `30` |
| `BACKUP_REMOTE_PATH` | Nextcloud folder for encrypted backups | `Locuvi/Backups` |
| `SESSION_HOURS` | How long you stay signed in, in hours | `12` |
| `WEBDAV_ALLOWED_PRIVATE_HOSTS` | Private Nextcloud addresses to allow | |
| `ANTHROPIC_API_KEY_FILE`, `LOCUVI_AI_MODEL` | AI key from a file, default Anthropic model | |
| `LOCUVI_AUTH_MODE` | `password` (normal) or `gateway` (only behind a login gateway) | `password` |

The full list is in `backend/locuvi/config.py`.
