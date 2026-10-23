"""Sync through Dropbox, Google Drive and OneDrive accounts, against stand-ins (fake_clouds).

Never a real account or a real company's servers. Fictional data only."""

from __future__ import annotations

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest
from fake_clouds import EMAIL, FakeCloud
from test_api import Api, client_for
from test_sync_engine import Device

from locuvi.errors import DomainError
from locuvi.models import Practice
from locuvi.sync import cloud, engine

PROVIDERS = ["dropbox", "google", "onedrive"]


@pytest.fixture(params=PROVIDERS)
def fake(request, monkeypatch):
    provider = request.param
    monkeypatch.setenv(f"LOCUVI_{provider.upper()}_CLIENT_ID", f"{provider}-test-app")
    if provider == "google":
        monkeypatch.setenv("LOCUVI_GOOGLE_CLIENT_SECRET", "google-test-secret")
    fc = FakeCloud(provider)
    monkeypatch.setattr(cloud, "_http", fc.client)
    cloud.Session._cache.clear()
    yield fc
    cloud.Session._cache.clear()


def sign_in(fc: FakeCloud, return_to: str = "local:8765") -> dict:
    b = cloud.begin(fc.provider, return_to)
    q = parse_qs(urlsplit(b["url"]).query)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(b["verifier"].encode()).digest())
    assert q["code_challenge"] == [challenge.decode().rstrip("=")]
    assert q["code_challenge_method"] == ["S256"] and q["state"] == [b["state"]]
    assert b["state"].endswith("." + return_to)
    return cloud.finish(fc.provider, "good-code", b["verifier"], return_to)


def connect(d: Device, fc: FakeCloud) -> dict:
    result = sign_in(fc)
    assert result["account"] == EMAIL
    return engine.cloud_spec(d.settings, engine.cloud_connected(d.settings, d.secrets, result))


def test_two_devices_sync_through_a_cloud_account(tmp_path, fake, monkeypatch):
    # small limits, so OneDrive's upload sessions and Google's resumable uploads are used too
    monkeypatch.setattr(cloud, "SIMPLE_UPLOAD", 300)
    monkeypatch.setattr(cloud, "CHUNK", 256)
    laptop, phone = Device(tmp_path, "laptop"), Device(tmp_path, "phone")
    with laptop.session() as s:
        s.add(Practice(id="p1", name="Example Surgery"))
        s.commit()
    laptop.file("invoices/issued/inv-1.pdf", b"%PDF-1.7 fictional invoice " * 40)
    spec = connect(laptop, fake)
    connect_first = laptop.secrets.decrypt(spec["refresh_ciphertext"])
    code = engine.start(laptop.settings, laptop.secrets, spec, "Laptop")

    engine.join(phone.settings, phone.secrets, connect(phone, fake), "Phone", code)
    with phone.session() as s:
        assert s.get(Practice, "p1").name == "Example Surgery"
        s.add(Practice(id="p2", name="Example Health Centre"))
        s.commit()
    assert (phone.settings.data_dir / "invoices/issued/inv-1.pdf").is_file()

    fake.expire_access()  # an hour later: Locuvi renews its sign-in by itself
    phone.sync()
    laptop.sync()
    with laptop.session() as s:
        assert s.get(Practice, "p2") is not None
    assert fake.refreshes >= 1

    st = engine.status(laptop.settings)
    assert st["kind"] == "cloud" and st["cloud"] == {"provider": fake.provider, "account": EMAIL}
    cfg_text = (laptop.settings.data_dir / "sync" / "config.json").read_text()
    assert "rt-" not in cfg_text  # the sign-in is kept encrypted
    if fake.provider == "onedrive":  # a replaced refresh token is kept for next time
        cfg = engine.load_config(laptop.settings)
        saved = laptop.secrets.decrypt(cfg.target["refresh_ciphertext"])
        assert saved in fake.valid_refresh and saved != connect_first


def test_a_write_onto_a_newer_copy_is_refused(tmp_path, fake):
    d = Device(tmp_path, "laptop")
    target = engine.build_target(d.settings, d.secrets,
                                 engine.Config(target=connect(d, fake)))  # fmt: skip
    assert target.read_state() is None
    assert target.write_state(b"first", None)
    assert not target.write_state(b"again", None)  # it exists now
    data, version = target.read_state()
    assert data == b"first"
    assert target.write_state(b"second", version)
    assert not target.write_state(b"stale", version)  # someone else wrote in between
    assert target.read_state()[0] == b"second"
    target.write_blob("ab" * 32, b"blob")
    target.write_blob("ab" * 32, b"blob")  # already there: nothing to do
    assert target.blob_names() == {"ab" * 32}
    assert target.read_blob("ab" * 32) == b"blob"


def test_google_two_devices_writing_at_once(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCUVI_GOOGLE_CLIENT_ID", "google-test-app")
    fc = FakeCloud("google")
    monkeypatch.setattr(cloud, "_http", fc.client)
    d = Device(tmp_path, "laptop")
    target = engine.build_target(d.settings, d.secrets, engine.Config(target=connect(d, fc)))
    assert target.write_state(b"one", None)
    _, version = target.read_state()
    real_upload = target._upload

    def other_device_first(name, parent, data):  # type: ignore[no-untyped-def]
        real_upload(name, parent, b"theirs")  # the same number, a moment earlier
        return real_upload(name, parent, data)

    monkeypatch.setattr(target, "_upload", other_device_first)
    assert not target.write_state(b"mine", version)  # theirs came first: merge again
    assert target.read_state()[0] == b"theirs"


def test_wrong_sign_in_is_refused(fake):
    b = cloud.begin(fake.provider, "web")
    with pytest.raises(DomainError) as e:
        cloud.finish(fake.provider, "bad-code", b["verifier"], "web")
    assert e.value.code == "sync.cloud_signin"


def test_sign_in_can_only_return_to_locuvi(fake):
    for bad in ("https://evil.example.invalid", "local:abc", "local:99999", ""):
        with pytest.raises(DomainError):
            cloud.begin(fake.provider, bad)


def test_onedrive_uses_its_native_address_outside_a_browser():
    assert cloud.redirect_uri("onedrive", "local:8765").endswith("/oauth-native.html")
    assert cloud.redirect_uri("onedrive", "app").endswith("/oauth-native.html")
    assert cloud.redirect_uri("onedrive", "web").endswith("/oauth.html")
    assert cloud.redirect_uri("dropbox", "app").endswith("/oauth.html")


def test_phone_joining_keeps_the_sign_in_readable(tmp_path, fake):
    """Joining adopts the household key; the saved sign-in is re-encrypted with it."""
    laptop, phone = Device(tmp_path, "laptop"), Device(tmp_path, "phone")
    code = engine.start(laptop.settings, laptop.secrets, connect(laptop, fake), "Laptop")
    engine.join(phone.settings, phone.secrets, connect(phone, fake), "Phone", code)
    cfg = engine.load_config(phone.settings)
    assert phone.secrets.decrypt(cfg.target["refresh_ciphertext"]).startswith("rt-")
    cloud.Session._cache.clear()  # no access token left: it must renew from the saved one
    phone.sync()


def test_api_offers_only_set_up_accounts(settings, monkeypatch):
    for p in PROVIDERS:
        monkeypatch.delenv(f"LOCUVI_{p.upper()}_CLIENT_ID", raising=False)
    monkeypatch.setenv("LOCUVI_DROPBOX_CLIENT_ID", "dropbox-test-app")
    with client_for(settings) as c:
        api = Api(c)
        assert api.get("/api/v1/sync").json()["cloud_accounts"] == ["dropbox"]
        r = api.post("/api/v1/sync/cloud/begin", {"provider": "google", "return_to": "web"})
        assert r.status_code == 400 and r.json()["error"]["code"] == "sync.cloud_unavailable"
        r = api.post("/api/v1/sync/cloud/begin", {"provider": "dropbox", "return_to": "web"})
        assert r.status_code == 200 and r.json()["url"].startswith("https://www.dropbox.com/")
