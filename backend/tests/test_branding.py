"""Personalisation: logo, accent, footer, email sign-off. Fictional data only."""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import date

import pytest
from PIL import Image, PngImagePlugin
from pypdf import PdfReader

from locuvi import mail
from locuvi.errors import DomainError
from locuvi.services import branding, core, credit_notes, diary
from locuvi.services import invoices as svc


def png(w=400, h=200, color=(41, 77, 99, 255), margin=0, **save) -> bytes:
    img = Image.new("RGBA", (w + 2 * margin, h + 2 * margin), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (w, h), color), (margin, margin))
    out = io.BytesIO()
    img.save(out, format="PNG", **save)
    return out.getvalue()


def issue(settings, s, practice, day):
    diary.add_sessions(s, [diary.SessionInput(practice.id, day)])
    d = diary.invoice_month(s, practice.id, f"{day:%Y-%m}")
    inv = svc.issue(settings, d.id, uuid.uuid4().hex).invoice
    s.expire_all()
    return svc.get_invoice(s, inv.id)


def pdf_text(data: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)


def pdf_images(data: bytes) -> int:
    return sum(len(p.images) for p in PdfReader(io.BytesIO(data)).pages)


# ------------------------------------------------------------------ cleaning


def test_logo_is_cleaned_resized_and_trimmed():
    meta = PngImagePlugin.PngInfo()
    meta.add_text("Author", "someone@example.invalid")
    out = branding.clean_logo(png(3000, 1000, margin=200, pnginfo=meta))
    img = Image.open(io.BytesIO(out))
    assert img.format == "PNG" and img.size == (900, 300)  # margins trimmed, then fitted
    assert b"example.invalid" not in out and not img.text  # metadata dropped
    jpeg = io.BytesIO()
    Image.new("RGB", (300, 120), (200, 30, 30)).save(jpeg, format="JPEG")
    assert Image.open(io.BytesIO(branding.clean_logo(jpeg.getvalue()))).size == (300, 120)


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"", "branding.logo_empty"),
        (b"not an image at all", "branding.logo_format"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "branding.logo_format"),
        (png(10, 10), "branding.logo_size"),
        (b"x" * (branding.MAX_UPLOAD_BYTES + 1), "branding.logo_too_large"),
    ],
)
def test_bad_logos_refused(data, code):
    with pytest.raises(DomainError) as e:
        branding.clean_logo(data)
    assert e.value.code == code


def test_gif_and_decompression_bomb_refused():
    gif = io.BytesIO()
    Image.new("RGB", (100, 100)).save(gif, format="GIF")
    with pytest.raises(DomainError):
        branding.clean_logo(gif.getvalue())
    bomb = io.BytesIO()
    Image.new("1", (10_000, 10_000)).save(bomb, format="PNG")  # 100 MP, tiny file
    with pytest.raises(DomainError) as e:
        branding.clean_logo(bomb.getvalue())
    assert e.value.code == "branding.logo_size"


# ------------------------------------------------------- invoices and emails


def test_logo_accent_footer_frozen_into_issued_invoice(settings, session, ready):
    plain = issue(settings, session, ready, date(2026, 7, 6))
    assert "logo_png_b64" not in plain.immutable_snapshot_json["presentation"]

    branding.set_logo(session, png())
    p = core.get_profile(session)
    p.brand_accent, p.invoice_footer = "teal", "Thank you — Dr Alex Example"
    session.commit()
    inv = issue(settings, session, ready, date(2026, 8, 3))
    look = inv.immutable_snapshot_json["presentation"]
    first_sha = hashlib.sha256(core.get_profile(session).logo_png).hexdigest()
    assert look["accent"] == branding.ACCENTS["teal"] and look["logo_sha256"] == first_sha
    stored = (settings.data_dir / inv.local_pdf_path).read_bytes()
    assert pdf_images(stored) == 1 and "Thank you — Dr Alex Example" in pdf_text(stored)
    assert pdf_images((settings.data_dir / plain.local_pdf_path).read_bytes()) == 0

    # a new logo never touches what was already issued
    branding.set_logo(session, png(color=(107, 39, 55, 255)))
    session.expire_all()
    again = svc.get_invoice(session, inv.id)
    assert again.immutable_snapshot_json["presentation"]["logo_sha256"] == first_sha
    assert (settings.data_dir / again.local_pdf_path).read_bytes() == stored

    # credit notes look like the invoice they correct
    cn = credit_notes.issue(settings, inv.id, [inv.lines[0].id], "Session cancelled", "k" * 12)
    assert cn.snapshot_json["presentation"]["logo_sha256"] == first_sha
    assert pdf_images((settings.data_dir / cn.local_pdf_path).read_bytes()) == 1

    # draft previews use the current look
    session.commit()
    diary.add_sessions(session, [diary.SessionInput(ready.id, date(2026, 9, 7))])
    draft = diary.invoice_month(session, ready.id, "2026-09")
    assert pdf_images(svc.preview_pdf(session, draft)) == 1

    branding.remove_logo(session)
    assert pdf_images(svc.preview_pdf(session, svc.get_invoice(session, draft.id))) == 0


def test_email_signoff(settings, session, ready):
    inv = issue(settings, session, ready, date(2026, 8, 3))
    assert mail.draft_for(session, inv)["body"].endswith("Kind regards,\nDr Alex Example")
    core.get_profile(session).email_signoff = "Best wishes,\nAlex\nGP Locum · 07700 900000"
    session.commit()
    assert mail.draft_for(session, inv)["body"].endswith(
        "Best wishes,\nAlex\nGP Locum · 07700 900000"
    )


def test_api_branding(settings, session, ready):
    from fastapi.testclient import TestClient

    from locuvi.main import create_app

    with TestClient(create_app(settings)) as c:
        h = {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}
        b = c.get("/api/v1/settings/branding").json()
        assert b["has_logo"] is False and b["accent"] == "steel" and "navy" in b["accents"]
        assert c.get("/api/v1/settings/branding/logo").status_code == 404

        r = c.post("/api/v1/settings/branding/logo", headers=h,
                  files={"file": ("logo.png", png(), "image/png")})  # fmt: skip
        assert r.status_code == 200 and r.json()["has_logo"] is True
        logo = c.get("/api/v1/settings/branding/logo")
        assert logo.headers["content-type"] == "image/png"
        bad = c.post("/api/v1/settings/branding/logo", headers=h,
                    files={"file": ("x.png", b"nope", "image/png")})  # fmt: skip
        assert bad.status_code == 400 and bad.json()["error"]["code"] == "branding.logo_format"

        r = c.patch("/api/v1/settings/branding", headers=h,
                    json={"accent": "plum", "invoice_footer": "  Thank you  ",
                          "email_signoff": "Best,\nAlex"})  # fmt: skip
        assert r.json()["accent"] == "plum" and r.json()["invoice_footer"] == "Thank you"
        assert c.patch("/api/v1/settings/branding", headers=h,
                       json={"accent": "#ff00ff"}).status_code == 422  # fmt: skip

        pdf = c.get("/api/v1/settings/branding/preview.pdf")
        assert pdf.headers["content-type"] == "application/pdf"
        text = pdf_text(pdf.content)
        assert "Dr Alex Example" in text and "Thank you" in text and pdf_images(pdf.content) == 1

        assert c.delete("/api/v1/settings/branding/logo", headers=h).json()["has_logo"] is False


# ------------------------------------------------------------------- SVG logos

SVG = b"""<?xml version="1.0"?>
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" width="300" height="100"
     viewBox="0 0 300 100" onload="alert(1)" inkscape:version="1.3">
  <metadata>editor data</metadata>
  <script>alert(1)</script>
  <style>@import url(https://example.invalid/x.css); .t { fill: #1D5C58 }</style>
  <defs><linearGradient id="g"><stop offset="0" stop-color="#294D63"/></linearGradient></defs>
  <rect width="100" height="100" fill="url(#g)" onclick="steal()"/>
  <circle cx="50" cy="50" r="20" style="fill: url(https://example.invalid/track)"/>
  <image href="https://example.invalid/pixel.png" width="10" height="10"/>
  <a href="javascript:alert(1)"><text x="0" y="0">bad</text></a>
  <foreignObject><div xmlns="http://www.w3.org/1999/xhtml">html</div></foreignObject>
  <use xlink:href="https://example.invalid/sprite.svg#a"/>
  <text x="120" y="60" class="t" font-size="30">EXAMPLELOGO</text>
</svg>"""


def test_svg_logo_is_cleaned():
    out = branding.clean_svg(SVG)
    for bad in ("script", "onload", "onclick", "foreignObject", "<image", "javascript:",
                "example.invalid", "metadata", "inkscape", "@import"):  # fmt: skip
        assert bad not in out, bad
    assert 'fill="url(#g)"' in out and "EXAMPLELOGO" in out and "<rect" in out


@pytest.mark.parametrize(
    "data",
    [
        b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><text>&x;</text></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><rect',
        b'<html xmlns="http://www.w3.org/1999/xhtml"><svg/></html>',
        b"<svg>" + b"x" * (branding.MAX_SVG_BYTES + 1) + b"</svg>",
    ],
)
def test_bad_svgs_refused(data):
    with pytest.raises(DomainError):
        branding.clean_svg(data)


def test_svg_logo_on_invoice_is_vector(settings, session, ready):
    branding.set_logo(session, SVG)
    p = core.get_profile(session)
    assert p.logo_svg and p.logo_png is None
    inv = issue(settings, session, ready, date(2026, 8, 3))
    look = inv.immutable_snapshot_json["presentation"]
    assert "logo_svg" in look and "logo_png_b64" not in look
    stored = (settings.data_dir / inv.local_pdf_path).read_bytes()
    assert "EXAMPLELOGO" in pdf_text(stored) and pdf_images(stored) == 0  # drawn, not a bitmap
    # switching back to a bitmap replaces the vector logo
    branding.set_logo(session, png())
    p = core.get_profile(session)
    assert p.logo_png and p.logo_svg is None


def test_api_svg_logo_served_safely(settings, session, ready):
    from fastapi.testclient import TestClient

    from locuvi.main import create_app

    with TestClient(create_app(settings)) as c:
        h = {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}
        r = c.post("/api/v1/settings/branding/logo", headers=h,
                   files={"file": ("logo.svg", SVG, "image/svg+xml")})  # fmt: skip
        assert r.status_code == 200 and r.json()["logo_format"] == "svg"
        got = c.get("/api/v1/settings/branding/logo")
        assert got.headers["content-type"].startswith("image/svg+xml")
        assert "sandbox" in got.headers["content-security-policy"]
        assert "script" not in got.text


def test_svg_with_bom_is_accepted_and_masks_refused(session, ready):
    plain = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10">'
        b'<rect width="20" height="10"/></svg>'
    )
    p = branding.set_logo(session, b"\xef\xbb\xbf" + plain)
    assert p.logo_svg and p.logo_png is None
    masked = (
        b'<svg xmlns="http://www.w3.org/2000/svg" width="20" height="10"><defs><mask id="m">'
        b'<rect width="10" height="10" fill="#fff"/></mask></defs>'
        b'<rect width="20" height="10" mask="url(#m)"/></svg>'
    )
    with pytest.raises(DomainError) as e:
        branding.clean_svg(masked)
    assert e.value.code == "branding.svg_mask"
