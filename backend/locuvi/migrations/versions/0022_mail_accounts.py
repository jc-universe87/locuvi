"""mail: several accounts

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-09 22:30:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("mailbox_config", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("label", sa.String(length=100), nullable=False, server_default="")
        )
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))
    op.create_table(
        "mail_folder_progress",
        sa.Column("account_id", sa.Integer(), nullable=False),
        sa.Column("folder", sa.String(length=300), nullable=False),
        sa.Column("uidvalidity", sa.Integer(), nullable=False),
        sa.Column("last_uid", sa.Integer(), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["account_id"], ["mailbox_config.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("account_id", "folder"),
    )
    # The old single mailbox becomes account 1 (with its reading progress); an empty,
    # never-configured row is dropped so the list starts empty.
    op.execute(
        "DELETE FROM mailbox_config WHERE enabled = 0 AND COALESCE(host, '') = '' "
        "AND COALESCE(username, '') = '' AND ms_client_id IS NULL "
        "AND password_ciphertext IS NULL AND ms_token_ciphertext IS NULL "
        "AND COALESCE(folders, '[]') = '[]' "
        "AND NOT EXISTS (SELECT 1 FROM mail_folder_state)"
    )
    op.execute("UPDATE mailbox_config SET label = COALESCE(NULLIF(username, ''), host, '')")
    op.execute(
        "INSERT INTO mail_folder_progress (account_id, folder, uidvalidity, last_uid, cursor) "
        "SELECT 1, folder, uidvalidity, last_uid, cursor FROM mail_folder_state "
        "WHERE EXISTS (SELECT 1 FROM mailbox_config WHERE id = 1)"
    )
    op.drop_table("mail_folder_state")


def downgrade() -> None:
    op.create_table(
        "mail_folder_state",
        sa.Column("folder", sa.String(length=300), nullable=False),
        sa.Column("uidvalidity", sa.Integer(), nullable=False),
        sa.Column("last_uid", sa.Integer(), nullable=False),
        sa.Column("cursor", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("folder"),
    )
    op.execute(
        "INSERT INTO mail_folder_state (folder, uidvalidity, last_uid, cursor) "
        "SELECT folder, uidvalidity, last_uid, cursor FROM mail_folder_progress "
        "WHERE account_id = 1"
    )
    op.drop_table("mail_folder_progress")
    op.execute("DELETE FROM mailbox_config WHERE id <> 1")
    with op.batch_alter_table("mailbox_config", schema=None) as batch_op:
        batch_op.drop_column("deleted_at")
        batch_op.drop_column("label")
