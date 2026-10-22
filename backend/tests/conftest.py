from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from locuvi import db
from locuvi.config import Settings
from locuvi.migrate import upgrade
from locuvi.models import Practice
from locuvi.services import core
from locuvi.services.invoices import LineData


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        data_dir=tmp_path / "data",
        key_dir=tmp_path / "keys",
        auth_mode="gateway",
        cookie_secure=False,
        worker_enabled=False,
    )


@pytest.fixture
def engine(settings: Settings):
    eng = db.init_engine(settings.db_path)
    upgrade(eng)
    s = db.new_session()
    core.ensure_singletons(s)
    s.close()
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    s = db.new_session()
    yield s
    s.close()


def fill_profile(s) -> None:
    """Fictional owner details only."""
    p = core.get_profile(s)
    p.legal_name = "Dr Alex Example"
    p.designation = "General Practitioner (Locum)"
    p.address_lines = "1 Sample Street\nExampletown"
    p.postcode = "SF1 1AA"
    p.email = "alex@example.invalid"
    p.bank_account_holder = "Dr Alex Example"
    p.bank_sort_code = "000000"
    p.bank_account_number = "00000000"
    s.commit()


def make_practice(s, **kw) -> Practice:
    p = Practice(
        name=kw.pop("name", "Example Medical Practice"),
        billing_address=kw.pop("billing_address", "2 Test Road\nSampleford\nSF1 2BB"),
        default_rate=Decimal("600.00"),
        **kw,
    )
    s.add(p)
    s.commit()
    return p


def line(
    d: str,
    price: str = "600.00",
    qty: str = "1",
    pensionable: bool = True,
    desc: str = "GP locum AM session",
    unit: str = "am",
) -> LineData:
    return LineData(date.fromisoformat(d), desc, unit, Decimal(qty), Decimal(price), pensionable)


@pytest.fixture
def ready(session):
    fill_profile(session)
    return make_practice(session)
