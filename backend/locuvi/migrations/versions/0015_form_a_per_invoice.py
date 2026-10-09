"""Form A per engagement (invoice): re-key Form A records from practice to invoice

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    recs = conn.execute(sa.text("SELECT id, month, practice_key FROM form_a_record")).fetchall()
    for rec_id, month, key in recs:
        # issued invoices of that practice whose (first) pensionable work falls in the month
        rows = conn.execute(
            sa.text(
                "SELECT DISTINCT i.id FROM invoice i JOIN invoice_line l ON l.invoice_id = i.id "
                "WHERE i.status = 'issued' AND i.practice_id = :p AND l.pensionable = 1 "
                "AND substr(l.service_date, 1, 7) = :m"
            ),
            {"p": key, "m": month},
        ).fetchall()
        if len(rows) == 1:
            conn.execute(
                sa.text("UPDATE form_a_record SET practice_key = :k WHERE id = :id"),
                {"k": rows[0][0], "id": rec_id},
            )
        # several invoices for one practice-month: leave the record; the owner re-ticks them


def downgrade() -> None:
    pass  # keys stay as invoice ids; harmless for the previous code (shown as "to send")
