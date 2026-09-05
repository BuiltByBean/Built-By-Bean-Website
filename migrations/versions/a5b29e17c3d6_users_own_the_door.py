"""Users own the door

More than one person opens this board now. An account gains a switch, so
somebody who leaves is turned off rather than deleted and keeps owning
the rows that point at them, and a last-login stamp. The role vocabulary
becomes owner and member; every account that existed carried "admin" and
becomes an owner, so nothing loses a door it had.

Revision ID: a5b29e17c3d6
Revises: f3a18d06b2c5
Create Date: 2026-09-05

"""
from alembic import op
import sqlalchemy as sa


revision = "a5b29e17c3d6"
down_revision = "f3a18d06b2c5"
branch_labels = None
depends_on = None


def _columns(bind, table):
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    have = _columns(bind, "users")
    if "is_active" not in have:
        # sa.true(), not "1": Postgres refuses an integer default on a boolean
        # column, and SQLite has no boolean literal - this renders right on both.
        op.add_column("users", sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()))
    if "last_login_at" not in have:
        op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    bind.execute(sa.text("UPDATE users SET role = 'owner' WHERE role = 'admin' OR role IS NULL"))


def downgrade():
    bind = op.get_bind()
    have = _columns(bind, "users")
    with op.batch_alter_table("users") as batch:
        if "last_login_at" in have:
            batch.drop_column("last_login_at")
        if "is_active" in have:
            batch.drop_column("is_active")
