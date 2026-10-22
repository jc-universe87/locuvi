"""Calendar (ICS) feed by secret link. Fictional data only."""

from __future__ import annotations

from decimal import Decimal

from locuvi.services import calendar, core, diary


def test_render_ics(session, ready, settings):
    from locuvi.secrets_store import SecretBox

    today = core.today_london()
    diary.add_sessions(
        session,
        [
            diary.SessionInput(ready.id, today, "am"),
            diary.SessionInput(
                ready.id, today, "hours", quantity=Decimal("4.5"), rate=Decimal("95")
            ),
        ],
    )
    box = SecretBox(settings)
    calendar.enable(session, box, include_fees=False)
    feed = calendar.get(session)
    ics = calendar.render(session, feed)
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "SUMMARY:Locum AM · Example Medical Practice" in ics
    assert f"DTSTART:{today:%Y%m%d}T080000" in ics and "DTSTART;VALUE=DATE:" in ics
    assert "4.5 h" in ics and "DESCRIPTION" not in ics  # no fees unless chosen
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))
    calendar.enable(session, box, include_fees=True)
    assert "DESCRIPTION:£600.00" in calendar.render(session, calendar.get(session))


def test_feed_link_lifecycle(settings):
    from fastapi.testclient import TestClient

    from locuvi.main import create_app

    with TestClient(create_app(settings)) as c:
        h = {"X-CSRF-Token": c.get("/api/v1/auth/session").json()["csrf_token"]}
        assert c.get("/api/v1/settings/calendar").json()["enabled"] is False
        on = c.put("/api/v1/settings/calendar", headers=h, json={"enabled": True}).json()
        path = on["path"]
        assert path.startswith("/calendar/") and path.endswith(".ics")
        anon = TestClient(c.app)  # calendar apps have no cookie
        r = anon.get(path)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/calendar")
        assert anon.get("/calendar/wrong.ics").status_code == 404
        new = c.put(
            "/api/v1/settings/calendar", headers=h, json={"enabled": True, "regenerate": True}
        ).json()["path"]
        assert (
            new != path and anon.get(path).status_code == 404 and anon.get(new).status_code == 200
        )
        c.put("/api/v1/settings/calendar", headers=h, json={"enabled": False})
        assert anon.get(new).status_code == 404


def test_one_off_exports_cover_every_session(session, ready, settings):
    from datetime import timedelta

    from fastapi.testclient import TestClient

    from locuvi import db
    from locuvi.main import create_app

    today = core.today_london()
    old = today - timedelta(days=400)  # outside the subscription window
    with TestClient(create_app(settings)) as c:
        s = db.new_session()
        from conftest import make_practice

        p = make_practice(s, name="=Example Practice")  # a name that looks like a formula
        diary.add_sessions(s, [diary.SessionInput(p.id, old, "pm"),
                               diary.SessionInput(p.id, today, "day")])  # fmt: skip
        s.close()
        ics = c.get("/api/v1/calendar/export.ics")
        assert ics.status_code == 200 and ics.headers["content-type"].startswith("text/calendar")
        assert "attachment" in ics.headers["content-disposition"]
        assert f"DTSTART:{old:%Y%m%d}T130000" in ics.text and "DESCRIPTION" not in ics.text
        assert "DESCRIPTION:£600.00" in c.get("/api/v1/calendar/export.ics?fees=true").text
        rows = c.get("/api/v1/calendar/export.csv?fees=true").content.decode("utf-8-sig")
        lines = rows.strip().splitlines()
        assert lines[0] == "Date,Start,End,Session,Practice,Address,Status,Fee"
        assert lines[1].startswith(f"{old.isoformat()},13:00,18:30,PM,'=Example Practice,")
        assert lines[1].endswith(",Booked,600.00") and len(lines) == 3
        assert "Fee" not in c.get("/api/v1/calendar/export.csv").text
        assert c.get("/api/v1/calendar/export.pdf").status_code == 404
