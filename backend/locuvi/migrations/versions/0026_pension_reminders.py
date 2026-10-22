"""email reminders before NHS pension deadlines

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-22 22:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("owner_profile") as b:
        b.add_column(
            sa.Column("pension_reminders", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        b.add_column(
            sa.Column("pension_reminders_sent", sa.JSON(), nullable=False, server_default="[]")
        )


def downgrade() -> None:
    with op.batch_alter_table("owner_profile") as b:
        b.drop_column("pension_reminders_sent")
        b.drop_column("pension_reminders")
