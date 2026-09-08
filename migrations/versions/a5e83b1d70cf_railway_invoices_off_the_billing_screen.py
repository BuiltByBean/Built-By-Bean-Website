"""Every Railway invoice, off the billing screen

The previous migration built the place to put these and then left it empty,
which made the hosting tile read "Estimated. No invoices recorded yet" while
the figures had already been handed over. Building the box and handing back
the typing is not finishing the job. These are his numbers, entered.

WHY EACH ONE IS FILED A MONTH EARLIER THAN ITS DATE. Railway bills usage in
arrears, so the invoice dated the 1st covers the month before, and filing it
under its own date would put every month's cost one month late. It is not an
assumption: the 2026-08-01 invoice of $21.45 sits against $19.92 of July
usage by project, and the 2026-09-01 invoice of $40.70 against $39.74 of
August. Both gaps are the projects deleted from Railway since, which the
usage screen keeps behind its own "Show deleted projects" link and which are
therefore missing from the visible per-project rows.

The two invoices dated 2026-04-01 are one month. $9.75 and $5.00 both cover
March, and the month cost $14.75; one row per month is the whole point of
the unique key, so they are summed rather than fought over.

    invoice dated     covers        amount
    2026-04-01 x2     Mar 2026      14.75
    2026-05-01        Apr 2026      20.00
    2026-06-01        May 2026      20.00
    2026-07-01        Jun 2026      20.00
    2026-08-01        Jul 2026      21.45
    2026-09-01        Aug 2026      40.70
                                   ------
                                   136.90

Nothing already recorded is touched. If he has typed a month in by hand
before this runs, his number is the one that stays.

Revision ID: a5e83b1d70cf
Revises: f4d18c7e02ab
"""
from datetime import date

from alembic import op
import sqlalchemy as sa


revision = "a5e83b1d70cf"
down_revision = "f4d18c7e02ab"
branch_labels = None
depends_on = None


INVOICES = (
    (date(2026, 3, 1), 14.75, "Two invoices dated 2026-04-01, 9.75 and 5.00"),
    (date(2026, 4, 1), 20.00, "Invoice dated 2026-05-01"),
    (date(2026, 5, 1), 20.00, "Invoice dated 2026-06-01"),
    (date(2026, 6, 1), 20.00, "Invoice dated 2026-07-01"),
    (date(2026, 7, 1), 21.45, "Invoice dated 2026-08-01"),
    (date(2026, 8, 1), 40.70, "Invoice dated 2026-09-01"),
)


def _provider_id(bind):
    row = bind.execute(
        sa.text("SELECT id FROM service_providers WHERE name = 'railway'")).first()
    return row[0] if row else None


def upgrade():
    bind = op.get_bind()
    if "provider_invoices" not in sa.inspect(bind).get_table_names():
        return
    pid = _provider_id(bind)
    if pid is None:
        return
    for month, amount, note in INVOICES:
        existing = bind.execute(
            sa.text("SELECT id FROM provider_invoices "
                    "WHERE provider_id = :p AND period_month = :m"),
            {"p": pid, "m": month}).first()
        if existing:
            continue
        bind.execute(
            sa.text("INSERT INTO provider_invoices "
                    "(provider_id, period_month, amount, note) "
                    "VALUES (:p, :m, :a, :n)"),
            {"p": pid, "m": month, "a": amount, "n": note})


def downgrade():
    bind = op.get_bind()
    if "provider_invoices" not in sa.inspect(bind).get_table_names():
        return
    pid = _provider_id(bind)
    if pid is None:
        return
    # Only the rows this put in, matched on the note as well as the month, so
    # a figure he has since corrected by hand is not taken out from under him.
    for month, amount, note in INVOICES:
        bind.execute(
            sa.text("DELETE FROM provider_invoices "
                    "WHERE provider_id = :p AND period_month = :m AND note = :n"),
            {"p": pid, "m": month, "n": note})
