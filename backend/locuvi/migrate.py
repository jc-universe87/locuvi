"""Programmatic Alembic upgrade, run at application start."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


def pending(engine: Engine) -> tuple[str | None, str | None]:
    """(current, head) revisions; current is None for a brand-new database."""
    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    with engine.connect() as conn:
        current = MigrationContext.configure(conn).get_current_revision()
    return current, head


def upgrade(engine: Engine, revision: str = "head") -> None:
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, revision)


def autogenerate(engine: Engine, message: str) -> None:
    """Developer helper: ``uv run python -m locuvi.migrate "message"``."""
    cfg = alembic_config()
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.revision(cfg, message=message, autogenerate=True)


if __name__ == "__main__":
    import sys
    import tempfile

    from locuvi.db import make_engine

    with tempfile.TemporaryDirectory() as tmp:
        eng = make_engine(Path(tmp) / "gen.db")
        upgrade(eng)
        autogenerate(eng, sys.argv[1] if len(sys.argv) > 1 else "update")
