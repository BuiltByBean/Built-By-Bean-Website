"""One Michael

Two accounts stood for one person: Michael.Bean, and Mbean, which a seed
had made under the wrong first name. Michael.Bean is the account and the
CEO; whatever Mbean owned moves to it and the Mbean row goes. Where only
Mbean exists (a dev database) it becomes Michael.Bean instead. Ty Lane is
the CTO. Bound parameters throughout, and no downgrade: a merge is not a
thing to undo.

Revision ID: e5f7a9c3d1b8
Revises: d9e4a6b1c7f2
Create Date: 2026-09-05

"""
from alembic import op
import sqlalchemy as sa


revision = "e5f7a9c3d1b8"
down_revision = "d9e4a6b1c7f2"
branch_labels = None
depends_on = None


def _id(bind, username):
    row = bind.execute(sa.text("SELECT id FROM users WHERE lower(username) = :u"), {"u": username}).first()
    return row[0] if row else None


def upgrade():
    bind = op.get_bind()
    mbean = _id(bind, "mbean")
    michael = _id(bind, "michael.bean")
    if mbean is not None and michael is not None:
        # timer_sessions is the one table that points at users, one row per
        # user: hand Mbean's timer to Michael unless Michael already has one.
        has_timer = bind.execute(sa.text("SELECT 1 FROM timer_sessions WHERE user_id = :m"), {"m": michael}).first()
        if has_timer:
            bind.execute(sa.text("DELETE FROM timer_sessions WHERE user_id = :m"), {"m": mbean})
        else:
            bind.execute(sa.text("UPDATE timer_sessions SET user_id = :michael WHERE user_id = :mbean"),
                         {"michael": michael, "mbean": mbean})
        bind.execute(sa.text("DELETE FROM users WHERE id = :m"), {"m": mbean})
    elif mbean is not None:
        taken = bind.execute(sa.text("SELECT 1 FROM users WHERE lower(email) = 'michael@builtbybean.com' AND id <> :m"),
                             {"m": mbean}).first()
        bind.execute(sa.text("UPDATE users SET username = 'Michael.Bean', first_name = 'Michael', last_name = 'Bean' WHERE id = :m"),
                     {"m": mbean})
        if not taken:
            bind.execute(sa.text("UPDATE users SET email = 'michael@builtbybean.com' WHERE id = :m"), {"m": mbean})
    bind.execute(sa.text("UPDATE users SET role = 'ceo', is_active = :on WHERE lower(username) = 'michael.bean'"), {"on": True})
    bind.execute(sa.text("UPDATE users SET role = 'cto' WHERE lower(username) = 'tlane'"))
    bind.execute(sa.text("UPDATE users SET first_name = 'Ty' WHERE lower(username) = 'tlane' AND first_name IN ('T', '')"))


def downgrade():
    pass
