"""Microsoft sign-in for the booking-email reader: Outlook.com, Microsoft 365 and NHSmail.

Microsoft switched off password logins for IMAP, so these accounts are read through Microsoft
Graph after a one-time sign-in:

- Sign-in uses the device-code flow: Locuvi shows a short code, the owner enters it at
  microsoft.com/devicelogin on any device and approves. Locuvi never sees the password, and
  works the same whatever address the server is reached at.
- The only mail permission requested is ``Mail.Read`` (plus ``User.Read`` for the address and
  ``offline_access`` to stay signed in). That token cannot mark, move, send or delete mail;
  on top of that this module only ever sends GET requests to Graph.
- The refresh token is encrypted at rest, rotated on every use and never returned by the API.
- The app ID is the owner's own Microsoft app registration (see docs/EMAIL_SETUP.md).
  Organisations such as NHSmail may require an administrator to approve it.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from locuvi.errors import DomainError
from locuvi.models import MailboxConfig
from locuvi.secrets_store import SecretBox, SecretUnavailable

LOGIN = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = "offline_access User.Read Mail.Read"
TIMEOUT = 30.0
MAX_FOLDERS = 300
_GUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_TENANT = re.compile(r"[a-z0-9][a-z0-9.-]{0,63}")

# The one sign-in in progress (single-user app). The device code never leaves the server.
_pending: dict[str, Any] = {}
_pending_lock = threading.Lock()


def client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, transport=transport, follow_redirects=False)


def _check_ids(client_id: str, tenant: str) -> tuple[str, str]:
    client_id, tenant = (client_id or "").strip(), (tenant or "common").strip().lower()
    if not _GUID.fullmatch(client_id):
        raise DomainError(
            "mailbox.ms_client_id",
            "Enter the Application (client) ID from your Microsoft app registration.",
        )
    if not _TENANT.fullmatch(tenant):
        raise DomainError("mailbox.ms_client_id", "That Microsoft directory name isn't valid.")
    return client_id, tenant


def _login_error(data: dict[str, Any]) -> DomainError:
    """Map Microsoft's sign-in errors to messages the owner can act on."""
    code = str(data.get("error") or "")
    desc = str(data.get("error_description") or "")
    if "AADSTS65001" in desc or "AADSTS90094" in desc or "AADSTS90095" in desc:
        return DomainError(
            "mailbox.ms_admin_consent",
            "Your organisation must approve Locuvi before it can read this mailbox.",
        )
    if "AADSTS53003" in desc or "AADSTS50097" in desc or "AADSTS530" in desc:
        return DomainError("mailbox.ms_blocked", "Your organisation blocks this way of signing in.")
    if code in {"invalid_client", "unauthorized_client"} or "AADSTS700016" in desc:
        return DomainError(
            "mailbox.ms_app_setup",
            "Microsoft didn't accept the app ID. Check the app registration in the setup guide.",
        )
    if code == "expired_token":
        return DomainError("mailbox.ms_expired", "The sign-in code expired. Start again.")
    if code in {"authorization_declined", "access_denied"}:
        return DomainError("mailbox.ms_declined", "The sign-in was cancelled.")
    if code == "invalid_grant":
        return DomainError("mailbox.ms_signed_out", "Sign in to Microsoft again.")
    return DomainError("mailbox.ms_failed", "Microsoft sign-in didn't work. Try again.")


def _post_login(http: httpx.Client, tenant: str, path: str, form: dict[str, str]) -> dict[str, Any]:
    try:
        r = http.post(f"{LOGIN}/{tenant}/oauth2/v2.0/{path}", data=form)
        data = r.json()
    except (httpx.HTTPError, ValueError):
        raise DomainError("mailbox.unreachable", "Couldn't reach Microsoft.") from None
    if not isinstance(data, dict):
        raise DomainError("mailbox.ms_failed", "Microsoft sign-in didn't work. Try again.")
    data["_status"] = r.status_code
    return data


def start_sign_in(
    client_id: str,
    tenant: str,
    transport: httpx.BaseTransport | None = None,
    account_id: int | None = None,
) -> dict[str, Any]:
    """Ask Microsoft for a sign-in code for one account; returns what the owner needs to see.
    One sign-in runs at a time: starting another replaces it."""
    client_id, tenant = _check_ids(client_id, tenant)
    with client(transport) as http:
        data = _post_login(http, tenant, "devicecode", {"client_id": client_id, "scope": SCOPES})
    if data["_status"] != 200 or not data.get("device_code"):
        raise _login_error(data)
    expires = int(data.get("expires_in") or 900)
    with _pending_lock:
        _pending.clear()
        _pending.update(
            device_code=data["device_code"], client_id=client_id, tenant=tenant,
            account_id=account_id,
            expires_at=time.monotonic() + expires, interval=int(data.get("interval") or 5),
        )  # fmt: skip
    return {
        "user_code": str(data.get("user_code", ""))[:20],
        "verification_uri": "https://microsoft.com/devicelogin",
        "expires_in": expires,
        "interval": int(data.get("interval") or 5),
    }


def poll_sign_in(
    cfg: MailboxConfig,
    box: SecretBox,
    transport: httpx.BaseTransport | None = None,
    account_id: int | None = None,
) -> dict[str, Any]:
    """Check whether the owner has approved the sign-in yet. On success, keep the token."""
    with _pending_lock:
        pending = dict(_pending)
    if pending and pending.get("account_id") != account_id:  # a sign-in for another account
        raise DomainError("mailbox.ms_expired", "The sign-in code expired. Start again.")
    if not pending or time.monotonic() > pending["expires_at"]:
        _forget(pending)
        raise DomainError("mailbox.ms_expired", "The sign-in code expired. Start again.")
    with client(transport) as http:
        data = _post_login(http, pending["tenant"], "token", {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "client_id": pending["client_id"],
            "device_code": pending["device_code"],
        })  # fmt: skip
        if data.get("error") in {"authorization_pending", "slow_down"}:
            interval = pending["interval"]
            if data["error"] == "slow_down":  # RFC 8628 §3.5: wait 5 s longer from now on
                interval += 5
                with _pending_lock:
                    if _pending.get("device_code") == pending["device_code"]:
                        _pending["interval"] = interval
            return {"status": "pending", "interval": interval}
        # Only the sign-in still in progress may finish; a stale poll (the owner cancelled
        # and started again meanwhile) neither saves its account nor clears the new one.
        current = _forget(pending)
        if data["_status"] != 200 or not data.get("refresh_token"):
            raise _login_error(data)
        if not current:
            raise DomainError("mailbox.ms_expired", "The sign-in code expired. Start again.")
        if "Mail.Read" not in str(data.get("scope", "")):
            raise DomainError(
                "mailbox.ms_admin_consent",
                "Your organisation must approve Locuvi before it can read this mailbox.",
            )
        me = _get_json(http, data["access_token"], f"{GRAPH}/me?$select=mail,userPrincipalName")
    cfg.ms_client_id, cfg.ms_tenant = pending["client_id"], pending["tenant"]
    cfg.ms_token_ciphertext = box.encrypt(data["refresh_token"])
    cfg.username = str(me.get("mail") or me.get("userPrincipalName") or "")[:200]
    return {"status": "done", "username": cfg.username}


def _forget(pending: dict[str, Any]) -> bool:
    """End this sign-in attempt if it is still the current one; True if it was."""
    with _pending_lock:
        if pending and _pending.get("device_code") == pending.get("device_code"):
            _pending.clear()
            return True
        return False


def sign_out(cfg: MailboxConfig) -> None:
    cfg.ms_token_ciphertext = None
    cfg.enabled = False


# ------------------------------------------------------------------------ Graph


class GraphMail:
    """Read-only Graph access for one scan. Only GET requests are ever sent to Graph."""

    def __init__(self, cfg: MailboxConfig, box: SecretBox, transport: Any = None):
        if not (cfg.ms_client_id and cfg.ms_token_ciphertext):
            raise DomainError("mailbox.ms_signed_out", "Sign in to Microsoft again.")
        try:
            refresh = box.decrypt(cfg.ms_token_ciphertext)
        except SecretUnavailable:
            raise DomainError("mailbox.ms_signed_out", "Sign in to Microsoft again.") from None
        self.http = client(transport)
        data = _post_login(self.http, cfg.ms_tenant or "common", "token", {
            "grant_type": "refresh_token", "client_id": cfg.ms_client_id,
            "refresh_token": refresh, "scope": SCOPES,
        })  # fmt: skip
        if data["_status"] != 200 or not data.get("access_token"):
            self.http.close()
            raise _login_error(data)
        if data.get("refresh_token"):  # Microsoft rotates refresh tokens: keep the newest
            cfg.ms_token_ciphertext = box.encrypt(data["refresh_token"])
        self.token = data["access_token"]

    def close(self) -> None:
        self.http.close()

    def _get(self, url: str) -> dict[str, Any]:
        return _get_json(self.http, self.token, url)

    def folders(self) -> list[dict[str, str]]:
        """All mail folders (with sub-folders), labelled by path, Inbox first."""
        out: list[dict[str, str]] = []
        queue: list[tuple[str, str]] = [(f"{GRAPH}/me/mailFolders?$top=100", "")]
        while queue and len(out) < MAX_FOLDERS:
            url, prefix = queue.pop(0)
            while url and len(out) < MAX_FOLDERS:
                page = self._get(url)
                for f in page.get("value") or []:
                    fid, name = str(f.get("id", "")), str(f.get("displayName", ""))
                    if not fid or len(fid) > 300:
                        continue
                    label = f"{prefix}{name}"
                    out.append({"name": fid, "label": label})
                    if int(f.get("childFolderCount") or 0) > 0:
                        queue.append((f"{GRAPH}/me/mailFolders/{_q(fid)}/childFolders?$top=100",
                                      f"{label} / "))  # fmt: skip
                url = page.get("@odata.nextLink") or ""
                if url and not url.startswith(GRAPH + "/"):
                    url = ""
        return sorted(out, key=lambda f: (f["label"].lower() != "inbox", f["label"].lower()))

    def changes(
        self, folder_id: str, cursor: str | None, since: datetime
    ) -> Iterator[tuple[list[dict[str, Any]], str | None]]:
        """Messages added to (or moved into) a folder since the last scan, page by page.

        Uses Graph's per-folder delta query, so a message filed into the folder later is
        still seen even though it was received long ago. Yields ``(messages, link)``: save
        ``link`` once the page is handled; it resumes there (next page, or the next scan).
        """
        url: str | None = cursor
        if not url:
            start = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
            url = (
                f"{GRAPH}/me/mailFolders/{_q(folder_id)}/messages/delta"
                f"?$select=id,internetMessageId,receivedDateTime"
                f"&$filter=receivedDateTime ge {start}"
            )
        while url:
            if not url.startswith(GRAPH + "/"):
                raise DomainError("mailbox.failed", "Reading the mail folders failed.")
            page = _get_json(self.http, self.token, url, {"Prefer": "odata.maxpagesize=50"})
            items = [m for m in page.get("value") or [] if "@removed" not in m]
            nxt = page.get("@odata.nextLink")
            yield items, nxt or page.get("@odata.deltaLink")
            url = nxt

    def mime(self, message_id: str, limit: int) -> bytes | None:
        """The full original message (RFC 822), or None if it is larger than ``limit``."""
        url = f"{GRAPH}/me/messages/{_q(message_id)}/$value"
        try:
            with self.http.stream("GET", url, headers=self._auth()) as r:
                if r.status_code != 200:
                    raise DomainError("mailbox.failed", "Reading the mail folders failed.")
                buf = bytearray()
                for chunk in r.iter_bytes():
                    buf += chunk
                    if len(buf) > limit:
                        return None
                return bytes(buf)
        except httpx.HTTPError:
            raise DomainError("mailbox.failed", "Reading the mail folders failed.") from None

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def _q(graph_id: str) -> str:
    return quote(graph_id, safe="")


def _get_json(
    http: httpx.Client, token: str, url: str, extra: dict[str, str] | None = None
) -> dict[str, Any]:
    try:
        r = http.get(url, headers={"Authorization": f"Bearer {token}", **(extra or {})})
    except httpx.HTTPError:
        raise DomainError("mailbox.unreachable", "Couldn't reach Microsoft.") from None
    if r.status_code == 410 or (r.status_code == 400 and "syncState" in r.text):
        raise DomainError("mailbox.ms_resync", "Folder changes must be read again from the start.")
    if r.status_code in (401, 403):
        raise DomainError(
            "mailbox.ms_admin_consent",
            "Your organisation must approve Locuvi before it can read this mailbox.",
        )
    if r.status_code != 200:
        raise DomainError("mailbox.failed", "Reading the mail folders failed.")
    try:
        data = r.json()
    except ValueError:
        raise DomainError("mailbox.failed", "Reading the mail folders failed.") from None
    return data if isinstance(data, dict) else {}
