"""Personalisation: logo, accent colour, invoice footer line, email sign-off.

The logo is cleaned (decoded, metadata dropped, resized, re-encoded as PNG) and kept in the
database, so backups cover it. Each issued invoice freezes its own copy in the snapshot's
"presentation" block: changing the logo later never alters an issued document.
"""

from __future__ import annotations

import base64
import hashlib
import io
import warnings
from typing import Any

from PIL import Image, UnidentifiedImageError
from sqlalchemy.orm import Session

from locuvi.errors import DomainError
from locuvi.models import OwnerProfile
from locuvi.services import core

# Accents chosen to stay readable on white paper and in greyscale print.
ACCENTS: dict[str, str] = {
    "steel": "#294D63",
    "navy": "#1F3A5F",
    "teal": "#1D5C58",
    "forest": "#2F5233",
    "plum": "#5B3A5E",
    "burgundy": "#6B2737",
    "charcoal": "#33393F",
}
DEFAULT_ACCENT = "steel"
MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 40_000_000  # refuse decompression bombs before decoding
LOGO_BOX = (900, 360)  # stored size; printed at most 60 x 24 mm (~380 dpi)
MAX_STORED_BYTES = 512 * 1024
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}


def clean_logo(data: bytes) -> bytes:
    """Decode an uploaded PNG/JPEG/WebP and return a small, metadata-free PNG."""
    if not data:
        raise DomainError("branding.logo_empty", "Choose an image file.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise DomainError("branding.logo_too_large", "The logo must be smaller than 5 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(data))
        fmt, (w, h) = probe.format, probe.size
        probe.close()
        if fmt not in ALLOWED_FORMATS:
            raise DomainError("branding.logo_format", "Use a PNG, JPEG or WebP image.")
        if w * h > MAX_PIXELS or w < 16 or h < 16:
            raise DomainError("branding.logo_size", "This image is too large or too small.")
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            img = img.convert("RGBA")
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise DomainError("branding.logo_size", "This image is too large or too small.") from None
    except (UnidentifiedImageError, OSError):
        raise DomainError("branding.logo_format", "Use a PNG, JPEG or WebP image.") from None
    bbox = img.getchannel("A").getbbox()  # trim fully transparent margins
    if bbox:
        img = img.crop(bbox)
    img.thumbnail(LOGO_BOX, Image.Resampling.LANCZOS)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)  # no EXIF/ICC/text chunks carried over
    png = out.getvalue()
    if len(png) > MAX_STORED_BYTES:
        img = img.quantize(colors=256, method=Image.Quantize.FASTOCTREE)
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        png = out.getvalue()
    return png


def set_logo(s: Session, data: bytes) -> OwnerProfile:
    p = core.get_profile(s)
    p.logo_png = clean_logo(data)
    core.audit(s, "settings.logo_changed", sha256=hashlib.sha256(p.logo_png).hexdigest()[:16])
    s.commit()
    return p


def remove_logo(s: Session) -> OwnerProfile:
    p = core.get_profile(s)
    p.logo_png = None
    core.audit(s, "settings.logo_removed")
    s.commit()
    return p


def accent_hex(key: str | None) -> str:
    return ACCENTS.get(key or "", ACCENTS[DEFAULT_ACCENT])


def presentation(p: OwnerProfile) -> dict[str, Any]:
    """The snapshot's presentation block: frozen into each issued document."""
    out: dict[str, Any] = {
        "locale": "en-GB",
        "timezone": "Europe/London",
        "template": "a4-v1",
        "accent": accent_hex(p.brand_accent),
    }
    if p.logo_png:
        out["logo_png_b64"] = base64.b64encode(p.logo_png).decode("ascii")
        out["logo_sha256"] = hashlib.sha256(p.logo_png).hexdigest()
    footer = (p.invoice_footer or "").strip()
    if footer:
        out["footer"] = footer
    return out


def public(p: OwnerProfile) -> dict[str, Any]:
    return {
        "has_logo": bool(p.logo_png),
        "logo_sha256": hashlib.sha256(p.logo_png).hexdigest() if p.logo_png else None,
        "accent": p.brand_accent or DEFAULT_ACCENT,
        "accents": ACCENTS,
        "invoice_footer": p.invoice_footer or "",
        "email_signoff": p.email_signoff or "",
    }


def signoff(p: OwnerProfile, seller: str) -> str:
    """Closing lines for drafted emails: the owner's own, else 'Kind regards' + name."""
    own = (p.email_signoff or "").strip()
    return own if own else f"Kind regards,\n{seller}"
