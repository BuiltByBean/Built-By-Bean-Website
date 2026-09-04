"""the railway months that were never booked

Six months of Railway went into the ledger as a flat twenty a month, which the
previous migration deleted because it was wrong. This puts the real numbers in.

The figures are Michael's, off the Railway usage and billing screens. Per
project from July onward, which is as far back as the per-project breakdown
goes; a single total before that, because there is nothing finer to have.

Invoices bill in arrears, so each one is booked to the month it covers rather
than the month it is dated. The invoice dated 2026-09-01 exists on 2026-09-02
and September has barely happened, so it can only be August's.

Every month is booked to its invoice total, not to the sum of its projects.
Those differ: August's twelve projects come to $39.74 against an invoice of
$40.70. The difference is the plan fee plus usage by projects since deleted,
and it goes on the unallocated "Not broken down" line rather than being spread
across clients, because a seat fee is a cost of being in business and not a
cost of anybody's application. The six months booked here add up to $136.90,
which is every invoice Railway has issued.

A project's share lands on its client only where a mapping already says which
client that is. Where no mapping exists the amount falls back to the same
unallocated line, so the month still totals correctly and the split can be
redone later from the Monthly Costs page. Guessing an owner would be the one
outcome worse than not knowing.

Skips any month that already has entries, so it cannot fight numbers entered by
hand, and cannot double if it somehow runs twice.

Revision ID: f1d63a08c527
Revises: c8d05a73e9f2
Create Date: 2026-09-03 20:30:00.000000

"""
from datetime import date, datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = 'f1d63a08c527'
down_revision = 'c8d05a73e9f2'
branch_labels = None
depends_on = None


OTHER_RESOURCE = "railway:other"
OTHER_LABEL = "Not broken down"

# (year, month, invoice total, {project name: usage}).
#
# The invoice total leads, because it is what was actually paid. The per-project
# figures are the split, and whatever they do not account for is the remainder.
MONTHS = [
    (2026, 8, 40.70, {
        "Talent Booker": 22.30,
        "Data Dungeon": 4.96,
        "Built By Beans Website": 3.34,
        "Gym Ecosystem": 1.91,
        "Flipping": 1.73,
        "Personal Trainer": 1.48,
        "CrossFit Games": 1.20,
        "The Wisdom Crucible": 1.02,
        "Kuper Plumbing": 0.9258,
        "Chop Builder": 0.4989,
        "Christ Community Church": 0.3140,
        "Signadoc": 0.0632,
    }),
    (2026, 7, 21.45, {
        "Talent Booker": 10.30,
        "Data Dungeon": 3.84,
        "Built By Beans Website": 2.92,
        "Personal Trainer": 1.28,
        "Gym Ecosystem": 0.7486,
        "Flipping": 0.6941,
        "CrossFit Games": 0.1375,
    }),
    # No per-project breakdown exists this far back. The invoice is the number.
    (2026, 6, 20.00, {}),
    (2026, 5, 20.00, {}),
    (2026, 4, 20.00, {}),
    # Two invoices dated 2026-04-01, $9.75 and $5.00, which is what a plan
    # change mid-cycle looks like. Booked together against the month they cover.
    (2026, 3, 14.75, {}),
]

# Stamped on every row this migration writes, and the only thing the downgrade
# needs to find them again.
MARK = "seed:f1d63a08c527"


def _norm(name):
    """A name reduced to what it is, so spelling differences do not lose money.

    Punctuation and case go, the same way the paste box on the Monthly Costs
    page reduces them, because "Built By Beans Website" and
    "Built-By-Beans-Website" are one project and failing to match them would
    silently move a real cost off its client and onto the unallocated line.
    """
    # Apostrophes are dropped rather than turned into a space, so "Kuper's
    # Plumbing" and "Kupers Plumbing" are one name instead of "kuper s" and
    # "kupers". Every other separator becomes a space.
    cleaned = "".join(
        "" if ch in "'’" else (ch if ch.isalnum() else " ")
        for ch in (name or "")
    )
    return " ".join(cleaned.split()).casefold()


def _month_bounds(year, month):
    first = date(year, month, 1)
    nxt = date(year + (month == 12), (month % 12) + 1, 1)
    return first, date.fromordinal(nxt.toordinal() - 1)


def upgrade():
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())
    if not {"service_providers", "service_cost_entries", "service_mappings",
            "expenses", "projects"} <= tables:
        return

    provider = conn.execute(sa.text(
        "SELECT id, display_name FROM service_providers WHERE name = 'railway' "
        "ORDER BY id LIMIT 1")).first()
    if provider is None:
        return
    provider_id, display_name = provider

    # Every way a Railway project name might already be tied to a client: the
    # label on the mapping, and the name of the project it points at.
    mappings = conn.execute(sa.text(
        "SELECT m.id, m.resource_identifier, m.resource_label, m.client_id, "
        "       m.project_id, m.split_percentage, p.name "
        "FROM service_mappings m LEFT JOIN projects p ON p.id = m.project_id "
        "WHERE m.provider_id = :pid AND m.is_active = TRUE"
    ), {"pid": provider_id}).fetchall()

    # Keyed by mapping id inside each name, not appended to a list. The label
    # and the project's name are usually the same string - automap sets the
    # first from the second - so a list matched one mapping twice, split the
    # amount across the duplicate, and then hit the unique constraint inserting
    # the second half against a key it had just used.
    by_name = {}
    for mid, rid, label, client_id, project_id, split, pname in mappings:
        row = {"id": mid, "rid": rid, "client_id": client_id,
               "project_id": project_id, "split": split if split is not None else 100.0}
        for candidate in (label, pname):
            key = _norm(candidate)
            if key:
                by_name.setdefault(key, {})[mid] = row

    now = datetime.now(timezone.utc)

    for year, month, invoice, projects in MONTHS:
        p_start, p_end = _month_bounds(year, month)

        # Never overwrite what somebody entered by hand.
        existing = conn.execute(sa.text(
            "SELECT 1 FROM service_cost_entries WHERE provider_id = :pid "
            "AND period_start = :s AND period_end = :e LIMIT 1"
        ), {"pid": provider_id, "s": p_start, "e": p_end}).first()
        if existing:
            continue

        remainder = invoice

        for name, amount in projects.items():
            targets = list(by_name.get(_norm(name), {}).values())
            if not targets:
                # No mapping, so no owner. The money is still real and stays in
                # the month, on the line that carries costs with nobody attached.
                continue

            # Two different projects answering to one name cannot be told apart
            # from a name, and a cost billed confidently to the wrong client is
            # worse than one sitting unallocated where it can be seen. A cost
            # split across several mappings of the *same* project is legitimate,
            # and that is what this distinguishes.
            if len({t["project_id"] for t in targets if t["project_id"]}) > 1:
                continue

            total_share = sum(t["split"] for t in targets) or 100.0
            for target in targets:
                share = target["split"] / total_share
                allocated = round(amount * share, 2)
                if allocated <= 0:
                    continue
                _book(conn, provider_id, display_name, target["rid"], target["id"],
                      target["client_id"], target["project_id"], p_start, p_end,
                      round(amount, 4), allocated, name, now)
                remainder -= allocated

        remainder = round(remainder, 2)
        if remainder > 0:
            _book(conn, provider_id, display_name, OTHER_RESOURCE, None, None, None,
                  p_start, p_end, remainder, remainder, OTHER_LABEL, now)


def _book(conn, provider_id, display_name, resource_id, mapping_id, client_id,
          project_id, p_start, p_end, raw_amount, allocated, label, now):
    """One cost entry and the expense that mirrors it.

    The same shape the Monthly Costs page writes, so a row seeded here and a row
    typed there are indistinguishable afterwards - which they have to be, or
    re-saving a month would treat one as foreign and leave it behind.
    """
    expense_id = conn.execute(sa.text(
        "INSERT INTO expenses (client_id, project_id, amount, description, "
        "                      category, date, created_at, is_recurring) "
        "VALUES (:client_id, :project_id, :amount, :description, 'service_cost', "
        "        :date, :created_at, FALSE) RETURNING id"
    ), {
        "client_id": client_id, "project_id": project_id, "amount": allocated,
        "description": f"{display_name} - {label}", "date": p_end, "created_at": now,
    }).scalar()

    conn.execute(sa.text(
        "INSERT INTO service_cost_entries (provider_id, mapping_id, expense_id, "
        "    resource_identifier, period_start, period_end, raw_amount, "
        "    allocated_amount, currency, description, raw_data_json, created_at) "
        "VALUES (:provider_id, :mapping_id, :expense_id, :resource_identifier, "
        "    :period_start, :period_end, :raw_amount, :allocated_amount, 'USD', "
        "    :description, :raw_data_json, :created_at)"
    ), {
        "provider_id": provider_id, "mapping_id": mapping_id, "expense_id": expense_id,
        "resource_identifier": resource_id, "period_start": p_start, "period_end": p_end,
        "raw_amount": raw_amount, "allocated_amount": allocated,
        "description": f"{display_name} - {label}",
        "raw_data_json": '{"source": "manual", "label": "%s", "seed": "%s"}'
                         % (label.replace('"', "'"), MARK),
        "created_at": now,
    })


def downgrade():
    """Take back exactly what was added, and nothing else.

    Reversible on purpose, unlike the migration that deleted the flat rows.
    That one removed numbers that were wrong; this one asserts numbers that are
    a reading of two screenshots, and a reading can be wrong. Rows are found by
    the mark stamped into raw_data_json, so a month re-entered by hand since -
    which rewrites raw_data_json without the mark - is left alone.
    """
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())
    if not {"service_cost_entries", "expenses"} <= tables:
        return

    rows = conn.execute(sa.text(
        "SELECT id, expense_id FROM service_cost_entries "
        "WHERE raw_data_json LIKE :mark"
    ), {"mark": f"%{MARK}%"}).fetchall()

    for entry_id, expense_id in rows:
        conn.execute(sa.text("DELETE FROM service_cost_entries WHERE id = :id"),
                     {"id": entry_id})
        if expense_id is None:
            continue
        if "invoice_line_items" in tables:
            billed = conn.execute(sa.text(
                "SELECT 1 FROM invoice_line_items WHERE expense_id = :eid LIMIT 1"
            ), {"eid": expense_id}).first()
            if billed:
                continue
        conn.execute(sa.text("DELETE FROM expenses WHERE id = :id"), {"id": expense_id})
