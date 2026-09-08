"""What the vendor actually billed, one row per provider per month

The lifetime Railway figure was derived by summing every expense whose
description started with the provider's name, and two different things write
those: the flat monthly charge from before per-project figures existed, and
the sync, which books one expense per project per month. Both match, so any
month holding both was counted twice. The page read $231.65 against $136.90
of actual invoices.

The unique constraint is the point. Entering a month twice corrects it
instead of adding it again, which is the exact failure this replaces.

Revision ID: f4d18c7e02ab
Revises: e2c7a94b1f60
"""
from alembic import op
import sqlalchemy as sa


revision = "f4d18c7e02ab"
down_revision = "e2c7a94b1f60"
branch_labels = None
depends_on = None


def upgrade():
    # create_all runs on boot and wins the race, so this may already exist.
    if "provider_invoices" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "provider_invoices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider_id", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Date(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_provider_invoices"),
        sa.ForeignKeyConstraint(["provider_id"], ["service_providers.id"],
                                name="fk_provider_invoices_provider_id",
                                ondelete="CASCADE"),
        sa.UniqueConstraint("provider_id", "period_month",
                            name="uq_provider_invoices_provider_month"),
    )
    with op.batch_alter_table("provider_invoices") as batch:
        batch.create_index("ix_provider_invoices_provider_id", ["provider_id"])
        batch.create_index("ix_provider_invoices_period_month", ["period_month"])


def downgrade():
    if "provider_invoices" not in sa.inspect(op.get_bind()).get_table_names():
        return
    op.drop_table("provider_invoices")
