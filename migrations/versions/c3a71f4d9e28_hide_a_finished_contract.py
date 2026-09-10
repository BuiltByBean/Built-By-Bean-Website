"""A finished contract can be tidied off the list

`archived_at` on signature_requests. Nullable, so every existing row is
visible exactly as it was, and the column only ever means "hidden from the
overview": the envelope is untouched and the row is still reachable by its
own URL.

Guarded on the column not already existing, because create_all runs on boot
and wins the race on a fresh database (CLAUDE.md, migrations beside
create_all).

Revision ID: c3a71f4d9e28
Revises: b6d2e9a41c7f
Create Date: 2026-09-10
"""
import sqlalchemy as sa
from alembic import op

revision = "c3a71f4d9e28"
down_revision = "b6d2e9a41c7f"
branch_labels = None
depends_on = None

TABLE = "signature_requests"
COLUMN = "archived_at"


def _has_column():
    inspector = sa.inspect(op.get_bind())
    if TABLE not in inspector.get_table_names():
        return True  # nothing to add to; create_all will build it complete
    return COLUMN in {c["name"] for c in inspector.get_columns(TABLE)}


def upgrade():
    if not _has_column():
        op.add_column(TABLE, sa.Column(COLUMN, sa.DateTime(), nullable=True))


def downgrade():
    if _has_column():
        # batch_alter_table because SQLite cannot drop a column in place.
        with op.batch_alter_table(TABLE) as batch:
            batch.drop_column(COLUMN)
