"""A company's own Stripe account, read into its books

Michael, 2026-11-03: EntertainHQ's income belongs in Stripe, where the sale
happens, "what if there's a bunch of money sitting in Stripe that we haven't
transferred over to our Mercury account?" So a company keeps a restricted
Stripe key (businesses.stripe_key) and every line of its Stripe balance is
kept (stripe_activity): sales gross on the day paid, refunds, Stripe's fees,
and payouts, which the bank feed reads as the company's own money moving.
Deposits from Stripe already read as income are made transfers here.

Revision ID: b3f8a1d6c925
Revises: a7d2e9c4f816
Create Date: 2026-11-03
"""
import sqlalchemy as sa
from alembic import op

revision = "b3f8a1d6c925"
down_revision = "a7d2e9c4f816"
branch_labels = None
depends_on = None

COLUMNS = (("stripe_key", sa.Text()), ("stripe_synced_at", sa.DateTime()),
           ("stripe_ok", sa.Boolean()), ("stripe_note", sa.String(300)))


def upgrade():
    bind = op.get_bind()
    have = {c["name"] for c in sa.inspect(bind).get_columns("businesses")}
    missing = [(n, t) for n, t in COLUMNS if n not in have]
    if missing:
        with op.batch_alter_table("businesses") as batch:
            for name, kind in missing:
                batch.add_column(sa.Column(name, kind, nullable=True))
    if not sa.inspect(bind).has_table("stripe_activity"):
        op.create_table(
            "stripe_activity",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("external_id", sa.String(80), nullable=False),
            sa.Column("created_on", sa.Date(), nullable=False),
            sa.Column("category", sa.String(40), nullable=True),
            sa.Column("kind", sa.String(40), nullable=True),
            sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
            sa.Column("fee", sa.Float(), nullable=False, server_default="0"),
            sa.Column("net", sa.Float(), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(8), nullable=True),
            sa.Column("description", sa.String(300), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                    name="fk_stripe_activity_business_id"),
            sa.PrimaryKeyConstraint("id", name="pk_stripe_activity"),
            sa.UniqueConstraint("business_id", "external_id",
                                name="uq_stripe_activity_business_external"),
        )
        op.create_index("ix_stripe_activity_business_id", "stripe_activity", ["business_id"])
        op.create_index("ix_stripe_activity_created_on", "stripe_activity", ["created_on"])
    bind.execute(sa.text(
        "UPDATE bank_transactions SET disposition = 'transfer' WHERE disposition = 'income' "
        "AND amount > 0 AND (UPPER(counterparty) LIKE '%STRIPE%' OR UPPER(description) LIKE '%STRIPE%')"))


def downgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("stripe_activity"):
        op.drop_table("stripe_activity")
    have = {c["name"] for c in sa.inspect(bind).get_columns("businesses")}
    present = [n for n, _ in COLUMNS if n in have]
    if present:
        with op.batch_alter_table("businesses") as batch:
            for name in present:
                batch.drop_column(name)
