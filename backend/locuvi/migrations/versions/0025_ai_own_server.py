"""address of the owner's own AI server

Revision ID: 0025
Revises: 0024
Create Date: 2026-10-18 21:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("assistant_config") as b:
        b.add_column(sa.Column("base_url", sa.String(length=300), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("assistant_config") as b:
        b.drop_column("base_url")
