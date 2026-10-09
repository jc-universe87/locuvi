"""rates: hourly practices, rates agreed including employer pension

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-09 13:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("practice", schema=None) as batch_op:
        batch_op.add_column(sa.Column("hourly_rate", sa.String(length=40), nullable=True))
        batch_op.add_column(sa.Column("default_hours", sa.String(length=40), nullable=True))
    with op.batch_alter_table("invoice_line", schema=None) as batch_op:
        batch_op.add_column(sa.Column("agreed_rate", sa.String(length=40), nullable=True))
    with op.batch_alter_table("work_session", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "rate_includes_pension", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
    # Hourly practices kept their per-hour figure in default_rate until now.
    op.execute(
        "UPDATE practice SET hourly_rate = default_rate "
        "WHERE default_unit = 'hours' AND hourly_rate IS NULL AND default_rate IS NOT NULL"
    )
    # Sessions not yet on an issued invoice take the practice's inclusive setting, so they are
    # converted correctly when invoiced. Issued invoices are never touched.
    op.execute(
        "UPDATE work_session SET rate_includes_pension = 1 "
        "WHERE practice_id IN (SELECT id FROM practice WHERE rate_includes_pension = 1) "
        "AND (invoice_id IS NULL OR invoice_id IN "
        "(SELECT id FROM invoice WHERE status = 'draft'))"
    )


def downgrade() -> None:
    with op.batch_alter_table("work_session", schema=None) as batch_op:
        batch_op.drop_column("rate_includes_pension")
    with op.batch_alter_table("invoice_line", schema=None) as batch_op:
        batch_op.drop_column("agreed_rate")
    with op.batch_alter_table("practice", schema=None) as batch_op:
        batch_op.drop_column("default_hours")
        batch_op.drop_column("hourly_rate")
