"""The hours Claude sessions logged come off the board

Michael, 2026-11-05, asked whether to delete the time Claude sessions had
logged (171.8 hours on the old Time not yet billed tab): "Delete Claude's". He
had said why the same morning: made-up hours "would be lying to my customers".

A Claude entry is one the SessionEnd hook wrote (it carries `session_ref`) or
one written through the door's log_time, which ended every description with
"(logged from <source>)". Nothing a person types on the Time page or stops on
the timer carries either. An entry already on an invoice line is left where it
is, because an invoice that was sent is history: there were none on the tab,
and the deploy log names any that are skipped.

Every removed row is kept whole in time_entry_removals, with any legacy mirror
expense the delete would cascade to, and downgrade puts them all back with
their ids.

Revision ID: d9a3c6e1b704
Revises: c4f7a9d2e816
Create Date: 2026-11-05
"""
import json
from datetime import date, datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "d9a3c6e1b704"
down_revision = "c4f7a9d2e816"
branch_labels = None
depends_on = None

REASON = "Logged by a Claude session; Claude never logs time (Michael, 2026-11-05)."


def _tables(bind):
    return set(sa.inspect(bind).get_table_names())


def _plain(row):
    out = {}
    for key, value in row.items():
        if isinstance(value, (datetime, date)):
            value = value.isoformat()
        out[key] = value
    return out


def _typed(table, data):
    """A row read back from JSON, with dates as dates again."""
    out = {}
    for col in table.columns:
        if col.name not in data:
            continue
        value = data[col.name]
        if value is not None and isinstance(col.type, sa.DateTime):
            value = datetime.fromisoformat(value)
        elif value is not None and isinstance(col.type, sa.Date):
            value = date.fromisoformat(value[:10])
        out[col.name] = value
    return out


def upgrade():
    bind = op.get_bind()
    have = _tables(bind)
    if "time_entry_removals" not in have:
        op.create_table(
            "time_entry_removals",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("entry_id", sa.Integer(), nullable=False),
            sa.Column("row_json", sa.Text(), nullable=False),
            sa.Column("expense_json", sa.Text(), nullable=True),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("removed_at", sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint("id", name="pk_time_entry_removals"),
        )
    if "time_entries" not in have:
        return
    meta = sa.MetaData()
    entries = sa.Table("time_entries", meta, autoload_with=bind)
    expenses = sa.Table("expenses", meta, autoload_with=bind) if "expenses" in have else None
    lines = sa.Table("invoice_line_items", meta, autoload_with=bind) if "invoice_line_items" in have else None
    removals = sa.Table("time_entry_removals", meta, autoload_with=bind)

    claude = sa.or_(entries.c.session_ref.isnot(None),
                    entries.c.description.like("%(logged from %"))
    rows = [dict(r._mapping) for r in bind.execute(sa.select(entries).where(claude)).fetchall()]
    on_invoice = set()
    if lines is not None and rows:
        on_invoice = {r[0] for r in bind.execute(
            sa.select(lines.c.time_entry_id).where(lines.c.time_entry_id.in_([r["id"] for r in rows])))}

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    removed, hours, skipped = 0, 0.0, []
    for row in rows:
        if row["id"] in on_invoice:
            skipped.append(row["id"])
            continue
        mirror = None
        if expenses is not None and "time_entry_id" in expenses.c:
            hit = bind.execute(sa.select(expenses).where(expenses.c.time_entry_id == row["id"])).fetchone()
            if hit is not None:
                mirror = dict(hit._mapping)
                bind.execute(expenses.delete().where(expenses.c.id == mirror["id"]))
        bind.execute(removals.insert().values(
            entry_id=row["id"], row_json=json.dumps(_plain(row)),
            expense_json=json.dumps(_plain(mirror)) if mirror else None,
            reason=REASON, removed_at=now))
        bind.execute(entries.delete().where(entries.c.id == row["id"]))
        removed += 1
        hours += row.get("hours") or 0.0
    print(f"  hours Claude logged: {removed} entries, {hours:,.2f}h removed and kept in "
          f"time_entry_removals; {len(skipped)} left because they are on an invoice {skipped}", flush=True)


def downgrade():
    bind = op.get_bind()
    have = _tables(bind)
    if "time_entry_removals" not in have:
        return
    meta = sa.MetaData()
    entries = sa.Table("time_entries", meta, autoload_with=bind)
    expenses = sa.Table("expenses", meta, autoload_with=bind) if "expenses" in have else None
    removals = sa.Table("time_entry_removals", meta, autoload_with=bind)
    for r in bind.execute(sa.select(removals)).fetchall():
        bind.execute(entries.insert().values(**_typed(entries, json.loads(r.row_json))))
        if r.expense_json and expenses is not None:
            bind.execute(expenses.insert().values(**_typed(expenses, json.loads(r.expense_json))))
    op.drop_table("time_entry_removals")
