"""Personalisation: logo, accent colour, invoice footer line, email sign-off.

The logo is cleaned and kept in the database, so backups cover it. A bitmap is decoded,
stripped of metadata, resized and re-encoded as PNG. An SVG is parsed without entities or
network access and reduced to a whitelist of drawing elements (no scripts, event handlers,
external or embedded images, links or foreign content), then kept as a vector. Each issued
invoice freezes its own copy in the snapshot's "presentation" block: changing the logo
later never alters an issued document.
"""

from __future__ import annotations

import base64
import hashlib
import io
import re
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
MAX_SVG_BYTES = 1024 * 1024

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
# Drawing elements a logo needs; anything else (script, foreignObject, image, a, iframe,
# animation, metadata, editor namespaces …) is removed.
SVG_ELEMENTS = {
    "svg", "g", "defs", "symbol", "use", "title", "desc", "style",
    "path", "rect", "circle", "ellipse", "line", "polyline", "polygon",
    "text", "tspan", "textPath",
    "linearGradient", "radialGradient", "stop", "clipPath", "mask", "pattern",
}  # fmt: skip
_BAD_CSS = re.compile(r"@import|expression\s*\(|url\(\s*['\"]?(?!#)", re.I)


def looks_like_svg(data: bytes) -> bool:
    head = data[:4096].lstrip().lower()
    return head.startswith((b"<?xml", b"<svg", b"<!--")) and b"<svg" in data[:65536].lower()


def clean_svg(data: bytes) -> str:
    """Return a safe, self-contained SVG, or raise DomainError."""
    from lxml import etree

    if len(data) > MAX_SVG_BYTES:
        raise DomainError("branding.logo_too_large", "An SVG logo must be smaller than 1 MB.")
    parser = etree.XMLParser(
        resolve_entities=False, no_network=True, load_dtd=False, dtd_validation=False,
        remove_comments=True, remove_pis=True, huge_tree=False,
    )  # fmt: skip
    try:
        root = etree.fromstring(data, parser)
    except etree.XMLSyntaxError:
        raise DomainError("branding.svg_invalid", "This SVG could not be read.") from None
    tree = root.getroottree()
    if tree.docinfo.doctype or tree.docinfo.internalDTD is not None:
        raise DomainError("branding.svg_invalid", "This SVG could not be read.")
    if etree.QName(root).localname != "svg":
        raise DomainError("branding.svg_invalid", "This SVG could not be read.")

    for el in list(root.iter()):
        if not isinstance(el.tag, str):  # entities, comments
            if el.getparent() is not None:
                el.getparent().remove(el)
            continue
        q = etree.QName(el)
        if q.namespace not in (None, SVG_NS) or q.localname not in SVG_ELEMENTS:
            if el is root:
                raise DomainError("branding.svg_invalid", "This SVG could not be read.")
            el.getparent().remove(el)
            continue
        for name in list(el.attrib):
            an = etree.QName(name)
            value = el.attrib[name]
            href = an.localname == "href" and an.namespace in (None, XLINK_NS)
            if (
                an.namespace not in (None, XLINK_NS)
                or an.localname.lower().startswith("on")
                or (href and not value.startswith("#"))
                or "javascript:" in value.lower()
                or _BAD_CSS.search(value)
            ):
                del el.attrib[name]
        if q.localname == "style" and el.text and _BAD_CSS.search(el.text):
            el.getparent().remove(el)  # imports or external urls: drop the whole stylesheet
    etree.cleanup_namespaces(root)  # drop now-unused editor namespace declarations
    cleaned = etree.tostring(root, encoding="unicode")

    from svglib.svglib import svg2rlg

    try:
        drawing = svg2rlg(io.BytesIO(cleaned.encode()))
    except Exception:  # noqa: BLE001 - any parser failure means "not usable"
        drawing = None
    if drawing is None or not drawing.width or not drawing.height:
        raise DomainError("branding.svg_invalid", "This SVG could not be read.")
    return cleaned


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
            raise DomainError("branding.logo_format", "Use an SVG, PNG, JPEG or WebP image.")
        if w * h > MAX_PIXELS or w < 16 or h < 16:
            raise DomainError("branding.logo_size", "This image is too large or too small.")
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            img = img.convert("RGBA")
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise DomainError("branding.logo_size", "This image is too large or too small.") from None
    except (UnidentifiedImageError, OSError):
        raise DomainError("branding.logo_format", "Use an SVG, PNG, JPEG or WebP image.") from None
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
    if data and looks_like_svg(data):
        p.logo_svg, p.logo_png = clean_svg(data), None
    else:
        p.logo_png, p.logo_svg = clean_logo(data), None
    core.audit(s, "settings.logo_changed", sha256=(logo_sha256(p) or "")[:16])
    s.commit()
    return p


def logo_sha256(p: OwnerProfile) -> str | None:
    if p.logo_svg:
        return hashlib.sha256(p.logo_svg.encode()).hexdigest()
    return hashlib.sha256(p.logo_png).hexdigest() if p.logo_png else None


def remove_logo(s: Session) -> OwnerProfile:
    p = core.get_profile(s)
    p.logo_png = p.logo_svg = None
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
    if p.logo_svg:
        out["logo_svg"] = p.logo_svg
    elif p.logo_png:
        out["logo_png_b64"] = base64.b64encode(p.logo_png).decode("ascii")
    if p.logo_svg or p.logo_png:
        out["logo_sha256"] = logo_sha256(p)
    footer = (p.invoice_footer or "").strip()
    if footer:
        out["footer"] = footer
    return out


def public(p: OwnerProfile) -> dict[str, Any]:
    return {
        "has_logo": bool(p.logo_png or p.logo_svg),
        "logo_format": "svg" if p.logo_svg else "png" if p.logo_png else None,
        "logo_sha256": logo_sha256(p),
        "accent": p.brand_accent or DEFAULT_ACCENT,
        "accents": ACCENTS,
        "invoice_footer": p.invoice_footer or "",
        "email_signoff": p.email_signoff or "",
    }


def signoff(p: OwnerProfile, seller: str) -> str:
    """Closing lines for drafted emails: the owner's own, else 'Kind regards' + name."""
    own = (p.email_signoff or "").strip()
    return own if own else f"Kind regards,\n{seller}"
