"""A runbook wears the vendor's own mark

The seeded runbooks carry hand-picked SVGs in static/pm/logos. Every runbook
written through the guidance door does not, and cannot: the door takes JSON,
so a session can send a vendor_url but never a picture, and each one has been
a two-letter monogram ever since. These three columns are the same ones an
AppLink already has, so a playbook can wear the mark fetched off its own
vendor_url the way an app tile wears its favicon.

Nullable and empty. Nothing is fetched here: a migration that reaches out to
other people's servers is a deploy that hangs on somebody else's outage.

Revision ID: b3f9d17c04ae
Revises: a7e3c81f52b4
"""
from alembic import op
import sqlalchemy as sa


revision = "b3f9d17c04ae"
down_revision = "a7e3c81f52b4"
branch_labels = None
depends_on = None


COLUMNS = (
    ("icon_file", lambda: sa.String(length=120)),
    ("icon_source", lambda: sa.String(length=500)),
    ("icon_fetched_at", lambda: sa.DateTime()),
)


def _present():
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("playbooks")}


def upgrade():
    # create_all runs on boot and wins the race, so a column may already be
    # here on an environment that booted before this landed. Guarded rather
    # than assumed (CLAUDE.md, migrations).
    have = _present()
    todo = [(n, t) for n, t in COLUMNS if n not in have]
    if not todo:
        return
    with op.batch_alter_table("playbooks") as batch:
        for name, type_ in todo:
            batch.add_column(sa.Column(name, type_(), nullable=True))


def downgrade():
    have = _present()
    todo = [n for n, _ in reversed(COLUMNS) if n in have]
    if not todo:
        return
    with op.batch_alter_table("playbooks") as batch:
        for name in todo:
            batch.drop_column(name)
