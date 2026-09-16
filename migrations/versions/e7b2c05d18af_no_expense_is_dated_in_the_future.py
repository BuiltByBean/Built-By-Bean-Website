"""No expense is dated in the future

A cost entry's period is a KEY and has to be the whole calendar month, or the
nightly sync writes a new row every night instead of correcting the one it
wrote before. The expense beside it took its date from the end of that period,
which for a month still in progress has not happened yet: September's accruing
Twilio, Cloudflare and Stripe charges were all stamped Sep 30 while it was the
16th, and the ledger read as a list of things that had not occurred.

The date is the period's end or today, whichever came first. This pulls back
the rows already written that way.

Only expenses this sync wrote are touched, found through their cost entry. A
hand typed expense dated ahead is somebody's deliberate note about money going
out later, and not this migration's business.

Bound parameters and Python dates throughout. Postgres and SQLite disagree
about date functions and neither is asked to run one.

Revision ID: e7b2c05d18af
Revises: d4f81c27a3b9
Create Date: 2026-09-16
"""
from datetime import date

import sqlalchemy as sa
from alembic import op

revision = "e7b2c05d18af"
down_revision = "d4f81c27a3b9"
branch_labels = None
depends_on = None

TABLE = "service_cost_entries"


def _as_date(value):
    """A date whether the driver handed back a date or a string."""
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    names = inspector.get_table_names()
    if TABLE not in names or "expenses" not in names:
        return  # a fresh database has nothing to pull back

    today = date.today()
    rows = bind.execute(sa.text(
        "SELECT e.id AS entry_id, e.period_end, x.id AS expense_id, x.date AS on_date "
        "FROM service_cost_entries e JOIN expenses x ON x.id = e.expense_id"
    )).fetchall()

    moved = 0
    for row in rows:
        if _as_date(row.on_date) <= today:
            continue
        when = min(_as_date(row.period_end), today)
        bind.execute(sa.text("UPDATE expenses SET date = :when WHERE id = :id"),
                     {"when": when, "id": row.expense_id})
        moved += 1

    print(f"[e7b2c05d18af] pulled {moved} future dated expenses back to today")


def downgrade():
    # Putting a date back into the future is not something to offer. The sync
    # writes the honest one from here on.
    pass
