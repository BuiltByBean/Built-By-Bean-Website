"""the board can ask for tickets

Tickets only ever travelled one way. A client's app pushed them here when its
own outbox thread ran, and nothing on this side could ask. So an app whose
sender never started - a missing environment variable is enough - looked
exactly like an app with nothing to report, and the tickets page had no way to
tell a quiet week from a broken pipe. That is this repo's own rule about zero
hits from a check that never ran, broken a third time.

Two columns, so silence becomes readable. `hub_pulled_at` is when the board
last asked, and a stamp that stops moving is a pipe that stopped. `hub_pull_note`
is what came back, so the row says which end refused rather than only that
something did.

Nullable with no default: null means never asked, which is a different fact
from asked and got nothing, and only the first is a thing to go and wire up.

Revision ID: a7e3c81f52b4
Revises: d4f6b8c2e0a7
Create Date: 2026-09-07 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7e3c81f52b4'
down_revision = 'd4f6b8c2e0a7'
branch_labels = None
depends_on = None


NEW_COLUMNS = (
    ("hub_pulled_at", sa.DateTime()),
    ("hub_pull_note", sa.String(length=300)),
)


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "clients" not in set(insp.get_table_names()):
        return
    have = {c["name"] for c in insp.get_columns("clients")}
    with op.batch_alter_table("clients", schema=None) as batch_op:
        for name, kind in NEW_COLUMNS:
            if name not in have:
                batch_op.add_column(sa.Column(name, kind, nullable=True))


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "clients" not in set(insp.get_table_names()):
        return
    have = {c["name"] for c in insp.get_columns("clients")}
    with op.batch_alter_table("clients", schema=None) as batch_op:
        for name, _ in NEW_COLUMNS:
            if name in have:
                batch_op.drop_column(name)
