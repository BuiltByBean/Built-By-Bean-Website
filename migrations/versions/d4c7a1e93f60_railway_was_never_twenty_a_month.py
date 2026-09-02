"""railway was never twenty a month

Railway was set up as a flat provider before anyone had established that its
API cannot report spend. A figure went on the provider row and the sync booked
it every month against a single made-up resource, so the ledger read one
unallocated "Railway" line of the same amount forever, no matter what Railway
actually charged or which client caused it.

The real numbers now come in per project through the Monthly Costs page, which
is keyed on the calendar month and the Railway project id. Those two ways of
booking the same vendor cannot both be right, and leaving the old rows in place
would double every month that gets restated.

So: the flat rows go, the expenses they created go with them, and the figure
that generated them is cleared off the provider and off its mappings so nothing
can start booking it again.

Two identifiers, because two different code paths wrote them. `railway:account`
came from the Railway sync back when it invented a single account-wide resource;
`railway:subscription` is what the generic flat-provider sync writes. A genuine
Railway project is `railway:` followed by a UUID and matches neither, so real
per-project history is untouched.

An expense already sitting on an invoice is left alone. Deleting it would
silently change the total of a document that has been sent to a client, which
is a worse outcome than an orphaned row nobody can see.

Revision ID: d4c7a1e93f60
Revises: c8a1e05f3b74
Create Date: 2026-09-02 09:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4c7a1e93f60'
down_revision = 'c8a1e05f3b74'
branch_labels = None
depends_on = None


# What the two flat code paths called the thing they were booking. Neither is a
# Railway project: both are placeholders for "the account, in general".
FLAT_RESOURCES = ("railway:account", "railway:subscription")


def upgrade():
    conn = op.get_bind()
    tables = set(sa.inspect(conn).get_table_names())
    if not {"service_providers", "service_cost_entries"} <= tables:
        return

    provider_ids = [r[0] for r in conn.execute(sa.text(
        "SELECT id FROM service_providers WHERE name = 'railway'")).fetchall()]
    if not provider_ids:
        return

    # Bound parameters rather than an interpolated IN list, so this behaves the
    # same on Postgres and SQLite and cannot be confused by an odd id.
    for pid in provider_ids:
        rows = conn.execute(sa.text(
            "SELECT id, expense_id FROM service_cost_entries "
            "WHERE provider_id = :pid AND resource_identifier IN "
            "(:flat_a, :flat_b)"
        ), {"pid": pid, "flat_a": FLAT_RESOURCES[0], "flat_b": FLAT_RESOURCES[1]}).fetchall()

        for entry_id, expense_id in rows:
            # The entry first. expense_id is nullable and the entry is what
            # holds the reference, so dropping it releases the expense.
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

        # The figure itself, so a later sync or a saved provider form cannot
        # book it again.
        conn.execute(sa.text(
            "UPDATE service_providers SET monthly_cost = NULL, billing_day = NULL "
            "WHERE id = :pid"), {"pid": pid})
        if "service_mappings" in tables:
            have = {c["name"] for c in sa.inspect(conn).get_columns("service_mappings")}
            if "monthly_cost" in have:
                conn.execute(sa.text(
                    "UPDATE service_mappings SET monthly_cost = NULL WHERE provider_id = :pid"),
                    {"pid": pid})


def downgrade():
    """Nothing to put back.

    This migration deletes rows that were wrong and clears a number that should
    never have been set. There is no correct amount to restore them to, and
    inventing one would put the double-counting back. A downgrade that does
    nothing is honest; one that guessed would not be.
    """
