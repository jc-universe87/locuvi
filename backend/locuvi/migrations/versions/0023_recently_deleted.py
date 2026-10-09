"""recently deleted bin

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-09 23:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trash_item",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("label", sa.String(length=300), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("trash_item", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_trash_item_deleted_at"), ["deleted_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("trash_item", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_trash_item_deleted_at"))
    op.drop_table("trash_item")
