"""choice of AI provider and model

Revision ID: 0024
Revises: 0023
Create Date: 2026-10-10 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("assistant_config") as b:
        b.add_column(sa.Column("model", sa.String(length=120), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("assistant_config") as b:
        b.drop_column("model")
