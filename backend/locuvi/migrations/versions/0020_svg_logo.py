"""svg logo

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-09 15:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("owner_profile", schema=None) as batch_op:
        batch_op.add_column(sa.Column("logo_svg", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("owner_profile", schema=None) as batch_op:
        batch_op.drop_column("logo_svg")
