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
                " VALUES (1, 'Dr Alex Example', '', '1 Sample Street', 'SF1 1AA', 'a@example.invalid',"
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


def test_0019_marks_inclusive_draft_lines_and_hourly_rates(tmp_path):
    eng = db.init_engine(tmp_path / "r.db")
    upgrade(eng, "0018")
    now = "'2026-10-01 00:00:00'"
    with eng.begin() as c:
        c.execute(
            text(
                "INSERT INTO practice (id, name, billing_address, default_rate, default_unit,"
                " default_pensionable, rate_includes_pension, is_archived, po_required, created_at,"
                f" updated_at) VALUES ('pi', 'Inclusive Surgery', '', '600.00', 'am', 1, 1, 0, 0, {now}, {now}),"
                f" ('ph', 'Hourly Surgery', '', '95.00', 'hours', 1, 0, 0, 0, {now}, {now})"
            )
        )
        c.execute(
            text(
                "INSERT INTO invoice (id, status, practice_id, currency, pension_enabled, created_at,"
                f" updated_at) VALUES ('d1', 'draft', 'pi', 'GBP', 1, {now}, {now}),"
                f" ('i1', 'issued', 'pi', 'GBP', 1, {now}, {now})"
            )
        )
        c.execute(
            text(
                "INSERT INTO work_session (id, practice_id, date, unit, quantity, rate, pensionable,"
                " description, status, invoice_id, created_at, updated_at) VALUES"
                f" ('w1', 'pi', '2026-09-01', 'am', '1', '600.00', 1, '', 'active', 'd1', {now}, {now}),"
                f" ('w2', 'pi', '2026-08-01', 'am', '1', '600.00', 1, '', 'active', 'i1', {now}, {now}),"
                f" ('w3', 'pi', '2026-09-08', 'am', '1', '600.00', 1, '', 'active', NULL, {now}, {now})"
            )
        )
        c.execute(
            text(
                "INSERT INTO invoice_line (id, invoice_id, service_date, description, unit, quantity,"
                " unit_price, amount, pensionable, sort_order, created_at, updated_at) VALUES"
                f" ('l1', 'd1', '2026-09-01', '', 'am', '1', '600.00', '600.00', 1, 0, {now}, {now}),"
                f" ('l2', 'd1', '2026-09-02', '', 'am', '1', '531.25', '531.25', 1, 1, {now}, {now}),"
                f" ('l3', 'i1', '2026-08-01', '', 'am', '1', '600.00', '600.00', 1, 0, {now}, {now})"
            )
        )
    upgrade(eng)
    with eng.connect() as c:
        agreed = dict(c.execute(text("SELECT id, agreed_rate FROM invoice_line")).all())
        flags = dict(c.execute(text("SELECT id, rate_includes_pension FROM work_session")).all())
        hourly = c.execute(text("SELECT hourly_rate FROM practice WHERE id = 'ph'")).scalar()
    assert agreed == {"l1": "600.00", "l2": None, "l3": None}  # issued + hand-typed untouched
    assert flags == {"w1": 1, "w2": 0, "w3": 1}
    assert hourly == "95.00"
    eng.dispose()


def test_upgrade_from_0001_with_invoices_referencing_practices(tmp_path):
    """Table rebuilds (SQLite batch mode) must work with real, referenced rows."""
    eng = db.init_engine(tmp_path / "v1.db")
    upgrade(eng, "0001")
    now = "'2026-10-01 00:00:00'"
    with eng.begin() as c:
        c.execute(
            text(
                "INSERT INTO practice (id, name, billing_address, default_unit, default_pensionable,"
                f" rate_includes_pension, is_archived, created_at, updated_at) VALUES"
                f" ('p1', 'Example Medical Practice', '', 'am', 1, 0, 0, {now}, {now})"
            )
        )
        c.execute(
            text(
                "INSERT INTO invoice (id, status, practice_id, currency, pension_enabled, created_at,"
                f" updated_at) VALUES ('i1', 'draft', 'p1', 'GBP', 1, {now}, {now})"
            )
        )
    upgrade(eng)
    with eng.connect() as c:
        assert c.execute(text("SELECT practice_id FROM invoice")).scalar() == "p1"
        assert c.execute(text("PRAGMA foreign_keys")).scalar() == 1  # enforcement back on
        assert c.execute(text("PRAGMA foreign_key_check")).fetchall() == []
    eng.dispose()


def test_upgrade_rolls_back_on_broken_reference(tmp_path):
    import pytest

    eng = db.init_engine(tmp_path / "bad.db")
    upgrade(eng, "0018")
    now = "'2026-10-01 00:00:00'"
    with eng.connect() as c:
        c.connection.dbapi_connection.execute("PRAGMA foreign_keys=OFF")
        c.exec_driver_sql(
            "INSERT INTO invoice (id, status, practice_id, currency, pension_enabled, created_at,"
            f" updated_at) VALUES ('i1', 'draft', 'missing', 'GBP', 1, {now}, {now})"
        )
        c.commit()
    with pytest.raises(RuntimeError, match="broken reference"):
        upgrade(eng)
    with eng.connect() as c:  # nothing was applied
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0018"
    eng.dispose()


def test_0022_single_mailbox_becomes_first_account_with_progress(tmp_path):
    eng = db.init_engine(tmp_path / "m.db")
    upgrade(eng, "0021")
    with eng.begin() as c:
        c.execute(
            text(
                "INSERT INTO mailbox_config (id, enabled, provider, ms_tenant, host, port, security,"
                " username, password_ciphertext, folders, since_days, auto_scan, updated_at)"
                " VALUES (1, 1, 'imap', 'common', 'imap.example.invalid', 993, 'ssl',"
                " 'alex@example.invalid', 'enc', '[\"Locum\"]', 90, 1, '2026-10-01 00:00:00')"
            )
        )
        c.execute(
            text(
                "INSERT INTO mail_folder_state (folder, uidvalidity, last_uid)"
                " VALUES ('Locum', 7, 42)"
            )
        )
    upgrade(eng)
    with eng.connect() as c:
        acc = c.execute(text("SELECT id, label, enabled, deleted_at FROM mailbox_config")).all()
        progress = c.execute(text("SELECT * FROM mail_folder_progress")).all()
    assert acc == [(1, "alex@example.invalid", 1, None)]
    assert [tuple(r)[:4] for r in progress] == [(1, "Locum", 7, 42)]
    eng.dispose()


def test_0022_unused_mailbox_row_is_dropped(tmp_path):
    eng = db.init_engine(tmp_path / "e.db")
    upgrade(eng, "0021")
    with eng.begin() as c:
        c.execute(
            text(
                "INSERT INTO mailbox_config (id, enabled, provider, ms_tenant, host, port, security,"
                " username, folders, since_days, auto_scan, updated_at) VALUES (1, 0, 'imap',"
                " 'common', '', 993, 'ssl', '', '[]', 90, 1, '2026-10-01 00:00:00')"
            )
        )
    upgrade(eng)
    with eng.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM mailbox_config")).scalar() == 0
    eng.dispose()


def test_0022_keeps_a_signed_out_microsoft_mailbox(tmp_path):
    eng = db.init_engine(tmp_path / "s.db")
    upgrade(eng, "0021")
    with eng.begin() as c:
        c.execute(
            text(
                "INSERT INTO mailbox_config (id, enabled, provider, ms_client_id, ms_tenant, host,"
                " port, security, username, folders, since_days, auto_scan, updated_at) VALUES"
                " (1, 0, 'microsoft', '00000000-0000-0000-0000-000000000000', 'common', '', 993,"
                " 'ssl', 'alex@example.invalid', '[\"f1\"]', 90, 1, '2026-10-01 00:00:00')"
            )
        )
        c.execute(
            text(
                "INSERT INTO mail_folder_state (folder, uidvalidity, last_uid, cursor)"
                " VALUES ('f1', -1, 0, 'https://graph.microsoft.com/v1.0/delta?x')"
            )
        )
    upgrade(eng)
    with eng.connect() as c:
        assert c.execute(text("SELECT username FROM mailbox_config")).all() == [
            ("alex@example.invalid",)
        ]
        assert c.execute(text("SELECT account_id, cursor FROM mail_folder_progress")).all() == [
            (1, "https://graph.microsoft.com/v1.0/delta?x")
        ]
    eng.dispose()
