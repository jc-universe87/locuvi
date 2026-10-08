import hashlib
import uuid
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from webdav_fixture import PASSWORD, USER, DavServer

from locuvi.config import WebDavAllowlist
from locuvi.main import create_app

PROFILE = {
    "legal_name": "Dr Alex Example",
    "designation": "General Practitioner (Locum)",
    "address_lines": "1 Sample Street\nExampletown",
    "postcode": "EX1 1AA",
    "email": "alex@example.invalid",
    "bank_account_holder": "Dr Alex Example",
    "bank_sort_code": "00-00-00",
    "bank_account_number": "00000000",
}


def client_for(settings) -> TestClient:
    return TestClient(create_app(settings))


class Api:
    def __init__(self, c: TestClient):
        self.c = c
        sess = c.get("/api/v1/auth/session").json()
        self.csrf = sess["csrf_token"]

    def h(self, **extra):
        return {"X-CSRF-Token": self.csrf or "", **extra}

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers=self.h(**kw.pop("headers", {})), **kw)

    def put(self, url, json=None):
        return self.c.put(url, json=json, headers=self.h())

    def patch(self, url, json=None):
        return self.c.patch(url, json=json, headers=self.h())


@pytest.fixture
def api(settings):
    with client_for(settings) as c:
        yield Api(c)


def setup_owner_and_practice(api) -> str:
    r = api.put("/api/v1/settings/profile", PROFILE)
    assert r.status_code == 200, r.text
    assert r.json()["bank_account_number_masked"] == "••••0000"
    assert "bank_account_number" not in r.json()
    r = api.post(
        "/api/v1/practices",
        {
            "name": "Example Medical Practice",
            "billing_address": "2 Test Road\nSampleford",
            "default_rate": "600.00",
        },
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def two_october_sessions(practice_id):
    return {
        "practice_id": practice_id,
        "invoice_date": "2026-10-20",
        "lines": [
            {
                "service_date": "2026-10-08",
                "description": "GP locum AM session",
                "unit": "am",
                "quantity": "1",
                "unit_price": "600.00",
                "pensionable": True,
            },
            {
                "service_date": "2026-10-15",
                "description": "GP locum PM session",
                "unit": "pm",
                "quantity": "1",
                "unit_price": "550.00",
                "pensionable": True,
            },
        ],
    }


def test_key_acceptance_flow_and_restart(settings):
    with client_for(settings) as c:
        api = Api(c)
        pid = setup_owner_and_practice(api)
        r = api.post("/api/v1/invoices", two_october_sessions(pid))
        assert r.status_code == 201, r.text
        inv = r.json()
        assert inv["status"] == "draft" and inv["invoice_number"] is None
        t = inv["analysis"]["totals"]
        assert t["fee_subtotal"] == "1150.00"
        assert t["pensionable_pay"] == "1035.00"
        assert t["employer_contribution"] == "148.83"  # 1035 * .1438 = 148.833
        assert t["grand_total"] == "1298.83"
        assert inv["analysis"]["blocking"] == []
        # preview: no official number
        r = api.post(f"/api/v1/invoices/{inv['id']}/preview")
        assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
        # issue requires idempotency key
        r = api.post(f"/api/v1/invoices/{inv['id']}/issue")
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "invoice.idempotency_key_required"
        k = uuid.uuid4().hex
        r = api.post(f"/api/v1/invoices/{inv['id']}/issue", headers={"Idempotency-Key": k})
        assert r.status_code == 200, r.text
        issued = r.json()
        assert issued["invoice_number"] == "LOC-2026-0001"
        assert issued["archive"]["status"] == "not_configured"
        assert issued["snapshot"]["bank"]["account_number"] == "••••0000"
        r2 = api.post(f"/api/v1/invoices/{inv['id']}/issue", headers={"Idempotency-Key": k})
        assert r2.json()["replayed"] is True
        pdf1 = api.get(f"/api/v1/invoices/{inv['id']}/pdf")
        assert pdf1.status_code == 200
        assert 'filename="LOC-2026-0001.pdf"' in pdf1.headers["content-disposition"]
        assert hashlib.sha256(pdf1.content).hexdigest() == issued["local_pdf_sha256"]
        # issued cannot be edited
        r = api.patch(f"/api/v1/invoices/{inv['id']}", {"notes": "x"})
        assert r.status_code == 409
    # "reboot"
    with client_for(settings) as c:
        api = Api(c)
        pdf2 = api.get(f"/api/v1/invoices/{inv['id']}/pdf")
        assert pdf2.content == pdf1.content
        lst = api.get("/api/v1/invoices?q=LOC-2026").json()
        assert lst["total"] == 1 and lst["items"][0]["status"] == "issued"
        assert api.get("/api/v1/health/ready").json()["integrity"]["ok"] is True


def test_list_filters_and_pagination(api):
    pid = setup_owner_and_practice(api)
    for _ in range(3):
        api.post("/api/v1/invoices", two_october_sessions(pid))
    r = api.get("/api/v1/invoices?page_size=2&status=draft").json()
    assert r["total"] == 3 and len(r["items"]) == 2
    r = api.get("/api/v1/invoices?q=Example%20Medical").json()
    assert r["total"] == 3
    r = api.get("/api/v1/invoices?date_from=2026-11-01").json()
    assert r["total"] == 0


def test_void_requires_reason_and_keeps_pdf(api):
    pid = setup_owner_and_practice(api)
    inv = api.post("/api/v1/invoices", two_october_sessions(pid)).json()
    api.post(f"/api/v1/invoices/{inv['id']}/issue", headers={"Idempotency-Key": uuid.uuid4().hex})
    assert api.post(f"/api/v1/invoices/{inv['id']}/void", {"reason": ""}).status_code == 422
    r = api.post(f"/api/v1/invoices/{inv['id']}/void", {"reason": "Billed wrong practice"})
    assert r.json()["status"] == "voided" and r.json()["invoice_number"] == "LOC-2026-0001"
    assert api.get(f"/api/v1/invoices/{inv['id']}/pdf").status_code == 200
    assert (
        api.c.delete(f"/api/v1/invoices/{inv['id']}", headers=api.h()).status_code == 409
    )  # no delete of issued


def test_multi_month_split_endpoint(api):
    pid = setup_owner_and_practice(api)
    body = two_october_sessions(pid)
    body["lines"][1]["service_date"] = "2026-11-02"
    inv = api.post("/api/v1/invoices", body).json()
    codes = [b["code"] for b in inv["analysis"]["blocking"]]
    assert "invoice.pensionable_multi_month" in codes
    r = api.post(
        f"/api/v1/invoices/{inv['id']}/issue", headers={"Idempotency-Key": uuid.uuid4().hex}
    )
    assert r.status_code == 422
    parts = api.post(f"/api/v1/invoices/{inv['id']}/split-by-month").json()["invoices"]
    assert len(parts) == 2


def test_calculate_rejects_float_and_validates(api):
    r = api.post(
        "/api/v1/invoices/calculate",
        {"lines": [{"service_date": "2026-10-01", "unit_price": 600.5, "pensionable": True}]},
    )
    assert r.status_code == 422
    r = api.post(
        "/api/v1/invoices/calculate",
        {
            "pension_enabled": True,
            "lines": [{"service_date": "2026-10-01", "unit_price": "600.00", "pensionable": True}],
        },
    )
    assert r.json()["totals"]["grand_total"] == "677.65"


def test_numbering_settings(api):
    r = api.put("/api/v1/settings/numbering", {"prefix": "LOC-2026-", "next_number": 41})
    assert r.json()["preview"] == "LOC-2026-0041"
    assert (
        api.put("/api/v1/settings/numbering", {"prefix": "../x", "next_number": 1}).status_code
        == 422
    )


def test_policy_versions(api):
    pols = api.get("/api/v1/settings/pension-policies").json()
    assert pols[0]["employer_rate"] == "0.1438" and pols[0]["effective_from"] == "2026-04-01"
    r = api.post(
        "/api/v1/settings/pension-policies",
        {"effective_from": "2027-04-01", "employer_rate": "14.38"},
    )
    assert r.json()["error"]["code"] == "policy.rate_range"
    r = api.post(
        "/api/v1/settings/pension-policies",
        {"effective_from": "2027-04-01", "employer_rate": "0.15"},
    )
    assert r.status_code == 201


def test_webdav_config_never_echoes_secret(api, settings):
    r = api.put(
        "/api/v1/storage/webdav",
        {
            "enabled": True,
            "target_url": "https://cloud.example.org/remote.php/dav/files/alex",
            "username": "alex",
            "password": "very-secret-app-pw",
        },
    )
    assert r.status_code == 200, r.text
    assert "very-secret" not in r.text and r.json()["password_set"] is True
    g = api.get("/api/v1/storage/webdav")
    assert "very-secret" not in g.text
    assert g.json()["target_url"] == "https://cloud.example.org/remote.php/dav/files/alex/"
    r = api.put(
        "/api/v1/storage/webdav",
        {"enabled": True, "target_url": "http://169.254.169.254/", "username": "a"},
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "webdav.url_blocked"


def test_offline_webdav_issue_still_works_then_syncs(settings, tmp_path):
    st = replace(
        settings,
        webdav_allowlist=WebDavAllowlist.parse("127.0.0.1"),
        webdav_allow_http_for_allowlisted=True,
        webdav_timeout_seconds=3,
    )
    dav = DavServer(tmp_path / "dav")
    with client_for(st) as c:
        api = Api(c)
        pid = setup_owner_and_practice(api)
        r = api.put(
            "/api/v1/storage/webdav",
            {"enabled": True, "target_url": dav.base_url, "username": USER, "password": PASSWORD},
        )
        assert r.status_code == 200
        t = api.post("/api/v1/storage/webdav/test", {}).json()
        assert t["ok"] is True
        dav.stop()
        inv = api.post("/api/v1/invoices", two_october_sessions(pid)).json()
        r = api.post(
            f"/api/v1/invoices/{inv['id']}/issue", headers={"Idempotency-Key": uuid.uuid4().hex}
        )
        assert r.status_code == 200
        assert r.json()["archive"]["status"] == "pending"
        assert api.get(f"/api/v1/invoices/{inv['id']}/pdf").status_code == 200
        from locuvi.webdav import archive

        archive.run_due_jobs(c.app.state.archive_ctx)
        st_ = api.get(f"/api/v1/invoices/{inv['id']}/archive-status").json()
        assert st_["status"] == "failed" and st_["last_error_class"] in {
            "unreachable",
            "network_error",
        }
        dav2 = DavServer(tmp_path / "dav")
        api.put(
            "/api/v1/storage/webdav",
            {"enabled": True, "target_url": dav2.base_url, "username": USER},
        )
        archive.run_due_jobs(c.app.state.archive_ctx)
        st_ = api.get(f"/api/v1/invoices/{inv['id']}/archive-status").json()
        assert st_["status"] == "synced", st_
        assert st_["verified_sha256"] == st_["local_sha256"]
        dav2.stop()


def test_password_mode_auth_and_csrf(settings):
    st = replace(settings, auth_mode="password", password="correct horse battery")
    with client_for(st) as c:
        assert c.get("/api/v1/invoices").status_code == 401
        assert c.get("/api/v1/health/live").status_code == 200
        r = c.post("/api/v1/auth/login", json={"password": "nope"})
        assert r.status_code == 401
        r = c.post("/api/v1/auth/login", json={"password": "correct horse battery"})
        assert r.status_code == 200
        csrf = r.json()["csrf_token"]
        assert c.get("/api/v1/invoices").status_code == 200
        # missing / wrong CSRF header rejected
        assert c.post("/api/v1/practices", json={"name": "X"}).status_code == 403
        assert (
            c.post(
                "/api/v1/practices", json={"name": "X"}, headers={"X-CSRF-Token": "forged"}
            ).status_code
            == 403
        )
        assert (
            c.post(
                "/api/v1/practices", json={"name": "X"}, headers={"X-CSRF-Token": csrf}
            ).status_code
            == 201
        )


def test_login_rate_limited(settings):
    st = replace(settings, auth_mode="password", password="pw")
    with client_for(st) as c:
        for _ in range(5):
            c.post("/api/v1/auth/login", json={"password": "bad"})
        assert c.post("/api/v1/auth/login", json={"password": "pw"}).status_code == 429


def test_password_mode_requires_password(settings):
    with pytest.raises(RuntimeError):
        create_app(replace(settings, auth_mode="password", password=None))


def test_security_headers_and_no_docs(api):
    r = api.get("/api/v1/health/live")
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert api.get("/api/docs").status_code == 404


def test_whitespace_practice_name_rejected(api):
    r = api.post("/api/v1/practices", {"name": "   ", "billing_address": "x"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "practice.name_required"
    pid = api.post("/api/v1/practices", {"name": "Example Medical Practice"}).json()["id"]
    assert api.patch(f"/api/v1/practices/{pid}", {"name": "  "}).status_code == 400


def test_search_finds_frozen_practice_name_after_rename(api):
    pid = setup_owner_and_practice(api)
    inv = api.post("/api/v1/invoices", two_october_sessions(pid)).json()
    api.post(f"/api/v1/invoices/{inv['id']}/issue", headers={"Idempotency-Key": uuid.uuid4().hex})
    api.patch(f"/api/v1/practices/{pid}", {"name": "Renamed Surgery"})
    assert api.get("/api/v1/invoices?q=Example%20Medical").json()["total"] == 1
    assert api.get("/api/v1/invoices?q=Renamed").json()["total"] == 1
