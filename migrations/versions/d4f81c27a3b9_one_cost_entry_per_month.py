"""One cost entry per resource per month

A month to date figure grows all month, so a daily sync has to correct the row
it wrote yesterday rather than stack another one beside it. `period_end` is
part of a cost entry's key, and Twilio's monthly usage record carries an
end_date that moves with today while the month is open, so every nightly run
wrote a NEW row holding the whole month to date. September 2026 booked itself
fifteen times: $462.79 of outbound SMS in the ledger against $59.67 of real
usage, and the same again in miniature for inbound SMS and Polly.

`_month_bounds` now keys those entries to the calendar month, which is what
Stripe and Cloudflare already did. This folds what the old code left behind.

The rule, per (provider, resource, mapping, month): a group is a month to date
SERIES only when its rows start on the first of the month and at least one of
them ends after that day. The newest row in such a series holds the most
complete figure, so it is kept, given the month's own bounds, and the rest are
deleted with their expenses.

What that rule deliberately protects: a vendor billing twice in one month
records two SINGLE DAY entries (see `_sync_flat` - Anthropic did it in March
and again in May). Every row in such a group starts and ends on its own day, so
no row starts on the first with a later end, the group is not a series, and
nothing is touched.

Bound parameters and Python dates throughout. Postgres and SQLite disagree
about date functions and neither is asked to run one.

Revision ID: d4f81c27a3b9
Revises: c3a71f4d9e28
Create Date: 2026-09-16
"""
from datetime import date, timedelta

import sqlalchemy as sa
from alembic import op

revision = "d4f81c27a3b9"
down_revision = "c3a71f4d9e28"
branch_labels = None
depends_on = None

TABLE = "service_cost_entries"


def _as_date(value):
    """A date whether the driver handed back a date or a string."""
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _month_bounds(when):
    first = when.replace(day=1)
    return first, (first + timedelta(days=32)).replace(day=1) - timedelta(days=1)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return  # a fresh database has nothing to fold

    rows = bind.execute(sa.text(
        "SELECT id, provider_id, resource_identifier, mapping_id, "
        "period_start, period_end, expense_id FROM service_cost_entries"
    )).fetchall()

    groups = {}
    for row in rows:
        start = _as_date(row.period_start)
        key = (row.provider_id, row.resource_identifier, row.mapping_id,
               start.year, start.month)
        groups.setdefault(key, []).append(row)

    drop_entries, drop_expenses, restate = [], [], []
    for (_, _, _, year, month), members in groups.items():
        first, last = _month_bounds(date(year, month, 1))
        # Only rows that start on the first are part of a month to date series.
        series = [r for r in members if _as_date(r.period_start) == first]
        if len(series) < 2:
            continue
        # And only if one of them actually spans more than that single day,
        # which is what tells a running total apart from two separate charges
        # that happened to land on the first.
        if max(_as_date(r.period_end) for r in series) <= first:
            continue
        series.sort(key=lambda r: (_as_date(r.period_end), r.id))
        keep = series[-1]
        for row in series[:-1]:
            drop_entries.append(row.id)
            if row.expense_id:
                drop_expenses.append(row.expense_id)
        if _as_date(keep.period_end) != last:
            restate.append((keep.id, keep.expense_id, first, last))

    # Entries first: each holds the foreign key to the expense beside it, and
    # an expense deleted out from under one only sets that key to null.
    for entry_id in drop_entries:
        bind.execute(sa.text("DELETE FROM service_cost_entries WHERE id = :id"),
                     {"id": entry_id})
    for expense_id in drop_expenses:
        bind.execute(sa.text("DELETE FROM expenses WHERE id = :id"),
                     {"id": expense_id})

    # Restated only after the duplicates are gone, so widening the survivor's
    # period cannot collide with a row about to be deleted on the unique key
    # (provider, resource, period_start, period_end, mapping).
    for entry_id, expense_id, first, last in restate:
        bind.execute(sa.text(
            "UPDATE service_cost_entries SET period_start = :first, "
            "period_end = :last WHERE id = :id"),
            {"first": first, "last": last, "id": entry_id})
        if expense_id:
            # The same date the sync would write: the period's end or today,
            # whichever came first. The period is a key and covers the whole
            # month; the expense's date is a fact about when money went out,
            # and the end of a month in progress has not happened yet.
            bind.execute(sa.text("UPDATE expenses SET date = :when WHERE id = :id"),
                         {"when": min(last, date.today()), "id": expense_id})

    print(f"[d4f81c27a3b9] folded {len(drop_entries)} duplicate cost entries, "
          f"restated {len(restate)}")


def downgrade():
    # The duplicates were the same month counted over and over. There is
    # nothing in them that is not in the row that was kept, and the sync no
    # longer makes them.
    pass
