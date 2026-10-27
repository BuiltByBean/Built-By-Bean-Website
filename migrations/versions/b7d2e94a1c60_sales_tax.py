"""Sales tax: who is exempt, which invoices are catch-up, and the rate

Texas taxes software sold as a service as a data processing service, on 80%
of the charge. Nothing on the board knew that, and most invoices went out
without it, so each client owes the shortfall. This adds what the ledger needs:

  * clients.sales_tax_exempt / sales_tax_exempt_reason - the buyer is out of
    state or holds a certificate.
  * invoices.issued_on - the day of the sale, for the quarter it is filed in.
  * invoices.sales_tax_catchup - an invoice that bills tax missed earlier.
  * invoices.sales_tax_exempt - one invoice that is not a taxable sale.
  * sales_tax_settings - the rate, the taxable share and the Stripe tax rate.

Booleans carry a server default so the existing rows read False on Postgres,
where adding a NOT NULL column without one is refused on a non-empty table.

Revision ID: b7d2e94a1c60
Revises: a6c3e19d4b70
Create Date: 2026-10-27
"""
import sqlalchemy as sa
from alembic import op

revision = "b7d2e94a1c60"
down_revision = "a6c3e19d4b70"
branch_labels = None
depends_on = None


def _columns(table):
    inspector = sa.inspect(op.get_bind())
    if table not in inspector.get_table_names():
        return None  # create_all will build it complete
    return {c["name"] for c in inspector.get_columns(table)}


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    have = _columns("clients")
    if have is not None:
        with op.batch_alter_table("clients", schema=None) as batch_op:
            if "sales_tax_exempt" not in have:
                batch_op.add_column(sa.Column("sales_tax_exempt", sa.Boolean(), nullable=False,
                                              server_default=sa.false()))
            if "sales_tax_exempt_reason" not in have:
                batch_op.add_column(sa.Column("sales_tax_exempt_reason", sa.String(length=200),
                                              nullable=True, server_default=""))

    have = _columns("invoices")
    if have is not None:
        with op.batch_alter_table("invoices", schema=None) as batch_op:
            if "issued_on" not in have:
                batch_op.add_column(sa.Column("issued_on", sa.Date(), nullable=True))
            if "sales_tax_catchup" not in have:
                batch_op.add_column(sa.Column("sales_tax_catchup", sa.Boolean(), nullable=False,
                                              server_default=sa.false()))
            if "sales_tax_exempt" not in have:
                batch_op.add_column(sa.Column("sales_tax_exempt", sa.Boolean(), nullable=False,
                                              server_default=sa.false()))

    # Guarded on the table: create_all runs on boot and may have made it.
    if "sales_tax_settings" not in _tables():
        op.create_table(
            "sales_tax_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("rate_percent", sa.Float(), nullable=False, server_default="8.25"),
            sa.Column("taxable_share", sa.Float(), nullable=False, server_default="80"),
            sa.Column("count_from", sa.Date(), nullable=True),
            sa.Column("stripe_tax_rate_id", sa.String(length=100), nullable=True),
            sa.Column("stripe_tax_rate_percent", sa.Float(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_sales_tax_settings"),
        )


def downgrade():
    if "sales_tax_settings" in _tables():
        op.drop_table("sales_tax_settings")

    have = _columns("invoices")
    if have is not None:
        with op.batch_alter_table("invoices", schema=None) as batch_op:
            for name in ("sales_tax_exempt", "sales_tax_catchup", "issued_on"):
                if name in have:
                    batch_op.drop_column(name)

    have = _columns("clients")
    if have is not None:
        with op.batch_alter_table("clients", schema=None) as batch_op:
            for name in ("sales_tax_exempt_reason", "sales_tax_exempt"):
                if name in have:
                    batch_op.drop_column(name)
