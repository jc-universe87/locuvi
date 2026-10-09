"""personalisation: logo, accent, invoice footer, email sign-off

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-09 09:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("owner_profile", schema=None) as batch_op:
        batch_op.add_column(sa.Column("logo_png", sa.LargeBinary(), nullable=True))
        batch_op.add_column(
            sa.Column("brand_accent", sa.String(length=20), nullable=False, server_default="steel")
        )
        batch_op.add_column(sa.Column("invoice_footer", sa.String(length=300), nullable=True))
        batch_op.add_column(sa.Column("email_signoff", sa.String(length=500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("owner_profile", schema=None) as batch_op:
        batch_op.drop_column("email_signoff")
        batch_op.drop_column("invoice_footer")
        batch_op.drop_column("brand_accent")
        batch_op.drop_column("logo_png")
