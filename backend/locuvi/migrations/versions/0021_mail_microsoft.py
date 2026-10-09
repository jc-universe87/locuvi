"""mail: microsoft sign-in

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-09 20:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("mailbox_config", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("provider", sa.String(length=12), nullable=False, server_default="imap")
        )
        batch_op.add_column(sa.Column("ms_client_id", sa.String(length=64), nullable=True))
        batch_op.add_column(
            sa.Column("ms_tenant", sa.String(length=64), nullable=False, server_default="common")
        )
        batch_op.add_column(sa.Column("ms_token_ciphertext", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("folder_labels", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("mailbox_config", schema=None) as batch_op:
        for col in ("folder_labels", "ms_token_ciphertext", "ms_tenant", "ms_client_id",
                    "provider"):  # fmt: skip
            batch_op.drop_column(col)
