"""clear the tasks that were converted into tickets

The previous migration turned the old tasks into tickets rather than dropping
them, because deleting somebody's data on the strength of a laptop copy being
empty is not a decision a migration gets to make. Michael has now looked at
them and asked for them to go: they were notes to himself from before this was
a client-facing board, and they are not work anybody is going to do.

**Scoped to origin "local", which is exactly the set that came from tasks.**
Anything pushed in by a client app carries that app's slug, so nothing from
Kuper or Talent Booker can be caught by this. It runs once, the way every
migration does, so a ticket raised by hand tomorrow is untouched.

It says what it deleted rather than doing it quietly. A cleanup that reports
nothing is indistinguishable from one that did not run, and this is the only
account of it that reaches the deploy log.

Revision ID: a1c7e93f60d2
Revises: f3a90d21c8b7
Create Date: 2026-08-29 15:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1c7e93f60d2'
down_revision = 'f3a90d21c8b7'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, title, description FROM tickets WHERE origin = 'local'"
    )).fetchall()
    if not rows:
        print("[tickets] no converted tasks left to clear")
        return

    for row in rows:
        label = (row[1] or row[2] or "")[:60]
        print(f"[tickets] clearing #{row[0]} {label!r}")

    # Notes first. ticket_id is NOT NULL on a note, so on some databases the
    # parent delete would try to null it and raise instead of cascading.
    bind.execute(sa.text(
        "DELETE FROM ticket_notes WHERE ticket_id IN "
        "(SELECT id FROM tickets WHERE origin = 'local')"
    ))
    # Then let go of anything pointing at them, rather than cascading a delete
    # into real money. An expense or a logged hour outlives the ticket it was
    # filed under; losing it because a note-to-self was tidied away would be a
    # cleanup taking the books with it.
    for table in ("expenses", "time_entries", "documents"):
        bind.execute(sa.text(
            f"UPDATE {table} SET ticket_id = NULL WHERE ticket_id IN "
            "(SELECT id FROM tickets WHERE origin = 'local')"
        ))
    result = bind.execute(sa.text("DELETE FROM tickets WHERE origin = 'local'"))
    print(f"[tickets] cleared {result.rowcount} converted task(s)")


def downgrade():
    # Deliberately nothing. They were deleted on purpose and there is nowhere
    # to bring them back from; pretending otherwise would be worse than saying
    # so here.
    pass
