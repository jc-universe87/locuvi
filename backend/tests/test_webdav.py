import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from conftest import line
from locuvi import db
from locuvi.config import WebDavAllowlist
from locuvi.errors import DomainError
from locuvi.models import ArchiveJob, Invoice, StorageConfig
from locuvi.secrets_store import SecretBox
from locuvi.services import core
from locuvi.services import invoices as svc
from locuvi.webdav import archive
from locuvi.webdav.urlguard import (
    InvalidPath,
    UrlBlocked,
    validate_base_path,
    validate_base_url,
)
from webdav_fixture import PASSWORD, USER, DavServer


@pytest.fixture
def dav(tmp_path):
    srv = DavServer(tmp_path / "davroot")
    yield srv
    srv.stop()


@pytest.fixture
def local_settings(settings):
    return replace(
        settings,
        webdav_allowlist=WebDavAllowlist.parse("127.0.0.1"),
        webdav_allow_http_for_allowlisted=True,
        webdav_timeout_seconds=5,
    )


@pytest.fixture
def ctx(local_settings, engine):
    return archive.ArchiveContext(local_settings, SecretBox(local_settings))


def configure(s, ctx, dav, **kw):
    params = dict(enabled=True, target_url=dav.base_url, username=USER,
                  base_path="Locuvi/Invoices", auto_upload=True, password=PASSWORD)
    params.update(kw)
    return archive.save_config(s, ctx, **params)


def issue(ctx, s, practice, d="2026-10-08"):
    inv = svc.save_draft(s, None, practice_id=practice.id, lines=[line(d)])
    return svc.issue(ctx.settings, inv.id, uuid.uuid4().hex,
                     after_issue=archive.enqueue_on_issue).invoice


def job_for(inv_id) -> ArchiveJob:
    s = db.new_session()
    return next(j for j in s.get(Invoice, inv_id).archive_jobs if j.is_current)


# --------------------------------------------------------------- happy paths


def test_upload_creates_hierarchy_and_verifies(ctx, session, ready, dav):
    configure(session, ctx, dav)
    inv = issue(ctx, session, ready)
    assert job_for(inv.id).status == "pending"
    assert archive.run_due_jobs(ctx) == {job_for(inv.id).id: "synced"}
    remote = dav.root / "Locuvi" / "Invoices" / "2026" / "10" / "LOC-2026-0001.pdf"
    assert remote.read_bytes() == (ctx.settings.data_dir / inv.local_pdf_path).read_bytes()
    j = job_for(inv.id)
    assert j.verified_sha256 == inv.local_pdf_sha256 and j.remote_etag
    assert not list(remote.parent.glob("*.part"))


def test_feature_off_issue_and_no_job(ctx, session, ready):
    inv = issue(ctx, session, ready)
    assert inv.status == "issued"
    st = archive.archive_status(session, session.get(Invoice, inv.id))
    assert st["status"] == "not_configured"


def test_existing_identical_file_is_success(ctx, session, ready, dav):
    configure(session, ctx, dav)
    inv = issue(ctx, session, ready)
    target = dav.root / "Locuvi/Invoices/2026/10/LOC-2026-0001.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes((ctx.settings.data_dir / inv.local_pdf_path).read_bytes())
    assert list(archive.run_due_jobs(ctx).values()) == ["synced"]


def test_conflicting_content_never_overwritten(ctx, session, ready, dav):
    configure(session, ctx, dav)
    inv = issue(ctx, session, ready)
    target = dav.root / "Locuvi/Invoices/2026/10/LOC-2026-0001.pdf"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"someone else's file")
    assert list(archive.run_due_jobs(ctx).values()) == ["conflict"]
    assert target.read_bytes() == b"someone else's file"
    assert job_for(inv.id).next_retry_at is None


def test_repeated_job_and_manual_reverify(ctx, session, ready, dav):
    configure(session, ctx, dav)
    inv = issue(ctx, session, ready)
    archive.run_due_jobs(ctx)
    s = db.new_session()
    archive.request_upload(s, s.get(Invoice, inv.id))
    assert list(archive.run_due_jobs(ctx).values()) == ["synced"]
    # Confirmed missing remotely -> re-upload
    (dav.root / "Locuvi/Invoices/2026/10/LOC-2026-0001.pdf").unlink()
    s = db.new_session()
    archive.request_upload(s, s.get(Invoice, inv.id))
    assert list(archive.run_due_jobs(ctx).values()) == ["synced"]
    assert (dav.root / "Locuvi/Invoices/2026/10/LOC-2026-0001.pdf").exists()


def test_leftover_partial_upload_is_handled(ctx, session, ready, dav):
    configure(session, ctx, dav)
    inv = issue(ctx, session, ready)
    j = job_for(inv.id)
    folder = dav.root / "Locuvi/Invoices/2026/10"
    folder.mkdir(parents=True)
    (folder / f".LOC-2026-0001.pdf.locuvi-{j.id[:8]}.part").write_bytes(b"truncated")
    assert list(archive.run_due_jobs(ctx).values()) == ["synced"]
    assert not list(folder.glob("*.part"))


def test_wrong_password_pauses_and_keeps_invoice(ctx, session, ready, dav):
    configure(session, ctx, dav, password="wrong")
    inv = issue(ctx, session, ready)
    assert list(archive.run_due_jobs(ctx).values()) == ["failed"]
    j = job_for(inv.id)
    assert j.last_error_class == "auth_rejected" and j.next_retry_at is None
    assert archive.run_due_jobs(ctx) == {}  # paused: no hammering
    assert (ctx.settings.data_dir / inv.local_pdf_path).exists()
    # Fixing credentials resumes
    configure(db.new_session(), ctx, dav, password=PASSWORD)
    assert list(archive.run_due_jobs(ctx).values()) == ["synced"]


def test_offline_then_eventually_syncs(ctx, session, ready, tmp_path):
    srv = DavServer(tmp_path / "late")
    url = srv.base_url
    srv.stop()
    archive.save_config(session, ctx, enabled=True, target_url=url, username=USER,
                        base_path="Locuvi/Invoices", auto_upload=True, password=PASSWORD)
    inv = issue(ctx, session, ready)
    assert inv.status == "issued"
    assert list(archive.run_due_jobs(ctx).values()) == ["failed"]
    j = job_for(inv.id)
    assert j.last_error_class in {"unreachable", "network_error"}
    assert j.next_retry_at is not None
    # Not due yet
    assert archive.run_due_jobs(ctx) == {}
    # Server comes back on the same port; make the job due
    from cheroot import wsgi
    srv2 = DavServer(tmp_path / "late")
    srv2.server.stop()
    srv2.server = wsgi.Server(("127.0.0.1", srv.port), srv2.app)
    srv2.server.prepare()
    import threading
    threading.Thread(target=srv2.server.serve, daemon=True).start()
    try:
        s = db.new_session()
        jj = s.get(ArchiveJob, j.id)
        jj.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        s.commit()
        assert list(archive.run_due_jobs(ctx).values()) == ["synced"]
    finally:
        srv2.server.stop()


def test_restart_recovers_interrupted_upload(ctx, session, ready, dav):
    configure(session, ctx, dav)
    inv = issue(ctx, session, ready)
    s = db.new_session()
    j = s.get(ArchiveJob, job_for(inv.id).id)
    j.status = "uploading"
    s.commit()
    assert archive.run_due_jobs(ctx) == {}
    assert archive.recover_interrupted(db.new_session()) == 1
    assert list(archive.run_due_jobs(ctx).values()) == ["synced"]


def test_change_destination_folder(ctx, session, ready, dav):
    configure(session, ctx, dav)
    a = issue(ctx, session, ready)
    archive.run_due_jobs(ctx)
    configure(db.new_session(), ctx, dav, base_path="Finance/Ünïcode Fäll ✓", password=None)
    b = issue(ctx, db.new_session(), ready)
    archive.run_due_jobs(ctx)
    assert (dav.root / "Locuvi/Invoices/2026/10" / f"{a.invoice_number}.pdf").exists()
    assert (dav.root / "Finance/Ünïcode Fäll ✓/2026/10" / f"{b.invoice_number}.pdf").exists()
    # old synced job keeps its path history
    assert job_for(a.id).destination_path_snapshot.startswith("Locuvi/Invoices/")


def test_test_connection(ctx, session, dav):
    ok = archive.test_connection(session, ctx, target_url=dav.base_url, username=USER,
                                 base_path="Locuvi/Invoices", password=PASSWORD)
    assert ok == {"ok": True, "folder_exists": False}
    bad = archive.test_connection(session, ctx, target_url=dav.base_url, username=USER,
                                  base_path="Locuvi", password="nope")
    assert bad == {"ok": False, "error_class": "auth_rejected"}
    # nothing persisted
    assert core.get_storage_config(session).password_ciphertext is None


def test_secret_never_returned_and_encrypted(ctx, session, dav, caplog):
    cfg = configure(session, ctx, dav)
    pub = archive.config_public(ctx, cfg)
    assert PASSWORD not in str(pub) and pub["password_set"] is True
    assert PASSWORD not in (cfg.password_ciphertext or "")
    raw = (ctx.settings.db_path).read_bytes()
    assert PASSWORD.encode() not in raw
    assert PASSWORD not in caplog.text


# ------------------------------------------------------------ SSRF / URLs


@pytest.mark.parametrize("url,reason", [
    ("http://cloud.example.org/remote.php/dav/files/a/", "scheme"),
    ("ftp://cloud.example.org/", "scheme"),
    ("https://localhost/remote.php/dav/", "private"),
    ("https://127.0.0.1/dav/", "private"),
    ("https://[::1]/dav/", "private"),
    ("https://169.254.169.254/latest/", "private"),
    ("https://10.0.0.5/dav/", "private"),
    ("https://192.168.1.10/dav/", "private"),
    ("https://100.101.102.103/dav/", "private"),
    ("https://[::ffff:127.0.0.1]/dav/", "private"),
    ("https://metadata.google.internal/", "private"),
    ("https://user:pw@cloud.example.org/dav/", "userinfo"),
    ("https://cloud.example.org/dav/?x=1", "invalid"),
    ("javascript:alert(1)", "scheme"),
])
def test_malicious_urls_blocked(settings, url, reason):
    with pytest.raises(UrlBlocked) as ei:
        validate_base_url(url, settings)
    assert ei.value.reason == reason


def test_allowlist_permits_private_target(settings):
    s2 = replace(settings, webdav_allowlist=WebDavAllowlist.parse("100.64.0.0/10,nas.lan"))
    assert validate_base_url("https://100.101.102.103/remote.php/dav/files/a", s2).allowlisted
    assert validate_base_url("https://nas.lan/dav/", s2).url == "https://nas.lan/dav/"
    with pytest.raises(UrlBlocked):
        validate_base_url("http://nas.lan/dav/", s2)  # http still needs explicit opt-in


def test_dns_resolving_to_private_blocked(settings, monkeypatch):
    import socket
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda *a, **k: [(2, 1, 6, "", ("10.1.2.3", 443))])
    from locuvi.webdav.urlguard import resolve_and_check
    with pytest.raises(UrlBlocked):
        resolve_and_check("rebind.example.org", 443, settings)


@pytest.mark.parametrize("bad", ["../etc", "a/./b", "a/..", "x" * 101, "a:b", "con\x00trol",
                                 ".hidden"])
def test_invalid_folder_names(bad):
    with pytest.raises(InvalidPath):
        validate_base_path(bad)


def test_unicode_folder_encoded():
    from locuvi.webdav.urlguard import encode_path
    segs = validate_base_path("Rechnungen/Café 2026")
    assert encode_path(segs) == "Rechnungen/Caf%C3%A9%202026"


def test_save_config_rejects_bad_url(ctx, session):
    with pytest.raises(DomainError) as ei:
        archive.save_config(session, ctx, enabled=True, target_url="https://10.0.0.1/",
                            username="u", base_path="x", auto_upload=True, password="p")
    assert ei.value.code == "webdav.url_blocked"


# ------------------------------------------------- fault injection (fake server)


def fake_ctx(local_settings, handler):
    transport = httpx.MockTransport(handler)
    return archive.ArchiveContext(local_settings, SecretBox(local_settings),
                                  transport_factory=lambda: transport)


def _setup_fake(ctx, session, ready):
    archive.save_config(session, ctx, enabled=True, target_url="https://dav.example.org/dav/",
                        username="u", base_path="L", auto_upload=True, password="secret-pw")
    return issue(ctx, session, ready)


@pytest.mark.parametrize("status,err,paused", [
    (401, "auth_rejected", True),
    (403, "permission_denied", True),
    (429, "rate_limited", False),
    (500, "server_error", False),
    (503, "server_unavailable", False),
    (507, "insufficient_storage", False),
    (302, "redirect_blocked", True),
])
def test_http_failures_classified(local_settings, engine, session, ready, status, err, paused):
    seen = []

    def handler(req: httpx.Request):
        seen.append(req)
        headers = {"Location": "https://evil.example.net/"} if status == 302 else {}
        if status in (429, 503):
            headers["Retry-After"] = "120"
        return httpx.Response(status, headers=headers)

    ctx = fake_ctx(local_settings, handler)
    inv = _setup_fake(ctx, session, ready)
    ctx.check_dns = False
    assert list(archive.run_due_jobs(ctx).values()) == ["failed"]
    j = job_for(inv.id)
    assert j.last_error_class == err
    assert (j.next_retry_at is None) == paused
    if status == 429:
        assert j.next_retry_at - j.last_attempt_at >= timedelta(seconds=119)
    assert all(r.url.host == "dav.example.org" for r in seen)  # redirect not followed
    for r in seen:
        assert "secret-pw" not in str(r.url)


def test_timeout_classified(local_settings, engine, session, ready):
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)

    ctx = fake_ctx(local_settings, handler)
    ctx.check_dns = False
    inv = _setup_fake(ctx, session, ready)
    assert list(archive.run_due_jobs(ctx).values()) == ["failed"]
    j = job_for(inv.id)
    assert j.last_error_class == "timeout" and j.next_retry_at is not None


def test_never_marked_synced_without_verification(local_settings, engine, session, ready):
    """Server accepts PUT/MOVE but serves different bytes back -> not synced."""
    def handler(req: httpx.Request):
        if req.method == "PROPFIND":
            if req.url.path.endswith(".pdf"):
                return httpx.Response(404)
            return httpx.Response(207, content=b'<?xml version="1.0"?><d:multistatus xmlns:d="DAV:"><d:response><d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>')
        if req.method in ("PUT", "MOVE"):
            return httpx.Response(201)
        if req.method == "GET":
            return httpx.Response(200, content=b"corrupted")
        return httpx.Response(204)

    ctx = fake_ctx(local_settings, handler)
    ctx.check_dns = False
    inv = _setup_fake(ctx, session, ready)
    assert list(archive.run_due_jobs(ctx).values()) == ["failed"]
    assert job_for(inv.id).last_error_class == "verify_failed"


def test_move_precondition_failed_race(local_settings, engine, session, ready):
    """Another writer created the target between PROPFIND and MOVE: never overwrite."""
    calls = []

    def handler(req: httpx.Request):
        calls.append((req.method, req.headers.get("Overwrite")))
        if req.method == "PROPFIND":
            if req.url.path.endswith(".pdf"):
                return httpx.Response(404)
            return httpx.Response(207, content=b'<d:multistatus xmlns:d="DAV:"><d:response><d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype></d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response></d:multistatus>')
        if req.method == "PUT":
            return httpx.Response(201)
        if req.method == "MOVE":
            return httpx.Response(412)
        if req.method == "GET":
            return httpx.Response(200, content=b"other content")
        return httpx.Response(204)

    ctx = fake_ctx(local_settings, handler)
    ctx.check_dns = False
    inv = _setup_fake(ctx, session, ready)
    assert list(archive.run_due_jobs(ctx).values()) == ["conflict"]
    assert ("MOVE", "F") in calls
    assert ("DELETE", None) in calls  # staging file cleaned up
    assert job_for(inv.id).status == "conflict"


def test_disabled_webdav_suppresses_processing(ctx, session, ready, dav):
    configure(session, ctx, dav)
    issue(ctx, session, ready)
    cfg = session.get(StorageConfig, 1)
    archive.save_config(session, ctx, enabled=False, target_url=cfg.target_url,
                        username=cfg.username, base_path=cfg.base_path, auto_upload=True,
                        password=None)
    assert archive.run_due_jobs(ctx) == {}


def test_backoff_bounded():
    assert archive.backoff_seconds(1) == 30
    assert archive.backoff_seconds(3) == 120
    assert archive.backoff_seconds(30) == archive.MAX_BACKOFF_SECONDS
