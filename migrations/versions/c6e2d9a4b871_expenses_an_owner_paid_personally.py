"""Expenses an owner paid personally

expenses.paid_by: the owner who paid an expense from their own pocket. The
company's books carry the expense and the same amount as that owner's money
put in. EntertainHQ's first $599.86 (LLC filing, Claude, Twilio, Google
Play) was paid on Michael's own card, 2026-10.

Revision ID: c6e2d9a4b871
Revises: b3f8a1d6c925
Create Date: 2026-11-03
"""
import sqlalchemy as sa
from alembic import op

revision = "c6e2d9a4b871"
down_revision = "b3f8a1d6c925"
branch_labels = None
depends_on = None


def upgrade():
    if "paid_by" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("expenses")}:
        with op.batch_alter_table("expenses") as batch:
            batch.add_column(sa.Column("paid_by", sa.String(120), nullable=True))


def downgrade():
    if "paid_by" in {c["name"] for c in sa.inspect(op.get_bind()).get_columns("expenses")}:
        with op.batch_alter_table("expenses") as batch:
            batch.drop_column("paid_by")
