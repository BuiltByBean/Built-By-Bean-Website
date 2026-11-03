"""Money from Chase is the owner's own money moving, never income

Michael, 2026-11-03, moved $5,000 from his personal Chase Total Checking
(••8721) into Built by Bean's new Mercury account, and EntertainHQ's
Mercury opened on a $1.00 deposit from the same account. With no rule the
bank feed reads any money in as income. This is neither income nor an
expense: it is the owner putting money into his own company. The rule
files it as a transfer, and the next nightly read (which looks ten days
back) settles the $1.00 line already read.

Revision ID: f6c1d3a8b520
Revises: e2a7c4d9f310
Create Date: 2026-11-03
"""
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "f6c1d3a8b520"
down_revision = "e2a7c4d9f310"
branch_labels = None
depends_on = None

PATTERN = "CHASE"


def upgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM vendor_rules WHERE pattern = :p"),
                    {"p": PATTERN}).first():
        return
    bind.execute(sa.text(
        "INSERT INTO vendor_rules (pattern, vendor, disposition, category, note, created_at) "
        "VALUES (:p, :v, 'transfer', 'misc', :n, :t)"),
        {"p": PATTERN, "v": "Chase (owner's own account)",
         "n": "Money in from Michael's Chase accounts: owner contribution, not income",
         "t": datetime.now(timezone.utc).replace(tzinfo=None)})
    bind.execute(sa.text(
        "UPDATE bank_transactions SET disposition = 'transfer' "
        "WHERE disposition = 'income' AND UPPER(counterparty) LIKE '%CHASE%'"))


def downgrade():
    op.get_bind().execute(sa.text("DELETE FROM vendor_rules WHERE pattern = :p"), {"p": PATTERN})
