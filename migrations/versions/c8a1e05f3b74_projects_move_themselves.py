"""projects move themselves along

The old phases - discovery, proposal, contracted, mvp, live - were describing
two different things at once. The first two are the state of a conversation
with a business, which the client stages now cover properly, and nothing
reaches the project board until it is under contract anyway. What is left is
the life of a build.

Five phases: Contracted, MVP, Delivered, Free maintenance, In production. All
but the first transition are already written down somewhere - the delivery
date came off the statement of work, the go-live date is set when it goes
live, and the free window is a number of days from that - so the board reads
them rather than waiting to be told.

Two columns come with it. go_live_date, because delivering something and it
being live are not the same day, and the free maintenance window should run
from the second; the window falls back to the delivery date where go-live is
unset, so no existing project loses its window. And phase_locked, because
mvp_date is what the contract promised rather than what happened: a build
running late would otherwise be marched to Delivered by its own contract date
and marched back every reload.

Existing phases map by meaning. discovery and proposal predate the contract,
so they land on Contracted - the earliest phase this board now has. live means
it shipped, which is In production.

Revision ID: c8a1e05f3b74
Revises: b3f7d29e6c40
Create Date: 2026-09-01 23:10:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c8a1e05f3b74'
down_revision = 'b3f7d29e6c40'
branch_labels = None
depends_on = None


# Old phase -> new. Anything already valid is absent and left alone.
PHASE_MAP = {
    "discovery": "contracted",
    "proposal": "contracted",
    "live": "in_production",
}

# For the way back. contracted is where two old phases collapsed to, so it
# cannot be un-collapsed; it maps to the one that keeps a project visible.
PHASE_UNMAP = {
    "delivered": "mvp",
    "free_maintenance": "live",
    "in_production": "live",
}

NEW_COLUMNS = (
    ("go_live_date", sa.Date()),
    ("phase_locked", sa.Boolean()),
)


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "projects" not in set(insp.get_table_names()):
        return

    have = {c["name"] for c in insp.get_columns("projects")}
    with op.batch_alter_table("projects", schema=None) as batch_op:
        for name, kind in NEW_COLUMNS:
            if name not in have:
                # Nullable on the way in, then filled and pinned: an existing
                # row has no value for a NOT NULL column, and SQLite will not
                # add one without a default it would then have to keep.
                batch_op.add_column(sa.Column(name, kind, nullable=True))

    if "phase_locked" not in have:
        # FALSE, not 0. SQLite takes either; Postgres refuses to compare an
        # integer to a boolean column and the whole migration aborts, which
        # is a failed deploy and a container that will not start.
        conn.execute(sa.text(
            "UPDATE projects SET phase_locked = FALSE WHERE phase_locked IS NULL"))

    for old, new in PHASE_MAP.items():
        conn.execute(sa.text("UPDATE projects SET phase = :new WHERE phase = :old"),
                     {"new": new, "old": old})
    # A project with no phase at all matches no filter and sits off the board.
    conn.execute(sa.text(
        "UPDATE projects SET phase = 'contracted' WHERE phase IS NULL OR phase = ''"))


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "projects" not in set(insp.get_table_names()):
        return

    for new, old in PHASE_UNMAP.items():
        conn.execute(sa.text("UPDATE projects SET phase = :old WHERE phase = :new"),
                     {"new": new, "old": old})

    have = {c["name"] for c in insp.get_columns("projects")}
    with op.batch_alter_table("projects", schema=None) as batch_op:
        for name, _ in NEW_COLUMNS:
            if name in have:
                batch_op.drop_column(name)
