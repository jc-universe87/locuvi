# ruff: noqa: E501
from sqlalchemy import text

from locuvi import db
from locuvi.migrate import upgrade


def test_upgrade_from_v01_keeps_data_and_skips_wizard(tmp_path):
    eng = db.init_engine(tmp_path / "old.db")
    upgrade(eng, "0001")
    with eng.begin() as c:
        c.execute(
            text(
                "INSERT INTO owner_profile (id, legal_name, designation, address_lines, postcode, email,"
                " bank_account_holder, bank_sort_code, bank_account_number, vat_status,"
                " payment_terms_days, pension_default_enabled, created_at, updated_at)"
                " VALUES (1, 'Dr Alex Example', '', '1 Sample Street', 'EX1 1AA', 'a@example.invalid',"
                " 'Dr Alex Example', '000000', '00000000', 'not_vat_registered', 30, 1,"
                " '2026-10-01 00:00:00', '2026-10-01 00:00:00')"
            )
        )
        c.execute(
            text(
                "INSERT INTO practice (id, name, billing_address, default_unit, default_pensionable,"
                " rate_includes_pension, is_archived, created_at, updated_at) VALUES"
                " ('p1', 'Example Medical Practice', '2 Test Road', 'am', 1, 0, 0,"
                " '2026-10-01 00:00:00', '2026-10-01 00:00:00')"
            )
        )
    upgrade(eng)
    with eng.connect() as c:
        assert c.execute(text("SELECT setup_completed FROM owner_profile")).scalar() == 1
        assert c.execute(text("SELECT name FROM practice")).scalar() == "Example Medical Practice"
        assert c.execute(text("SELECT practice_code FROM practice")).scalar() is None
        tables = {
            r[0] for r in c.execute(text("SELECT name FROM sqlite_master WHERE type='table'"))
        }
    assert {"work_session", "payment", "email_config", "pension_submission"} <= tables
    eng.dispose()


def test_fresh_install_starts_wizard(tmp_path):
    eng = db.init_engine(tmp_path / "new.db")
    upgrade(eng)
    from locuvi.services import core

    s = db.new_session()
    core.ensure_singletons(s)
    assert core.get_profile(s).setup_completed is False
    s.close()
    eng.dispose()
