"""The owner's registered apps at Dropbox, Google and Microsoft (docs/CLOUD_APPS.md).

These identify Locuvi to each company when someone signs in to sync; they are public by
design (every copy of Locuvi carries them) and give no access to anyone's files. A provider
whose ID is empty isn't offered. ``LOCUVI_<PROVIDER>_CLIENT_ID`` (and, for Google,
``LOCUVI_GOOGLE_CLIENT_SECRET``) override them, for tests or a build of your own.
"""

from __future__ import annotations

import os

DROPBOX_APP_KEY = "xn87zdu7r3pu03w"
GOOGLE_CLIENT_ID = "645552268873-bqfqglhsm96r34gafkjenk6s81elj95u.apps.googleusercontent.com"
ONEDRIVE_CLIENT_ID = ""

# Google's "Web application" clients need a secret to redeem a sign-in. It only identifies
# the app (Locuvi has no server to keep it on, so every built copy carries it), but it isn't
# kept in git: GitHub would flag it. The builds write it into locuvi/_cloud_secret.py from
# the GOOGLE_CLIENT_SECRET repository secret (docs/CLOUD_APPS.md).
try:
    from locuvi._cloud_secret import GOOGLE_CLIENT_SECRET  # type: ignore[import-not-found]
except ImportError:
    GOOGLE_CLIENT_SECRET = ""

# Where each company sends the person back after signing in (the iPhone/iPad site); that
# page passes the result on to the Locuvi that asked (computer, Android app or this site).
RETURN_PAGE = "https://locuvi.pistio.co.uk/oauth.html"
# OneDrive: Microsoft lets apps in a browser stay signed in for 24 hours only, so the
# computer and Android app use a separate "mobile and desktop" address (same page).
RETURN_PAGE_NATIVE = "https://locuvi.pistio.co.uk/oauth-native.html"


def client(provider: str) -> tuple[str, str]:
    """(client id, client secret) for a provider; empty when not set up."""
    key = provider.upper()
    ids = {"DROPBOX": DROPBOX_APP_KEY, "GOOGLE": GOOGLE_CLIENT_ID, "ONEDRIVE": ONEDRIVE_CLIENT_ID}
    cid = os.environ.get(f"LOCUVI_{key}_CLIENT_ID", ids.get(key, ""))
    default_secret = GOOGLE_CLIENT_SECRET if key == "GOOGLE" else ""
    secret = os.environ.get(f"LOCUVI_{key}_CLIENT_SECRET", default_secret)
    if key == "GOOGLE" and not secret:
        return "", ""  # a build without the secret can't finish a Google sign-in
    return cid, secret
