"""Businesses, where they sell from, and the sales tax returns they filed

The board was Built by Bean's alone; EntertainHQ LLC is the second business
it runs, so the facts a return needs are kept per business: the Texas
taxpayer number, the two WebFile numbers, the locations a permit lists, and
each return as WebFile confirmed it, with the confirmation page kept beside it.

  * businesses               - one row per company owned
  * business_locations       - each place a permit lists, open and closed
  * sales_tax_filings        - one row per business per period, as filed
  * sales_tax_filing_files   - the confirmations, stored on the volume

Every create_table is guarded on the table: create_all runs on boot and may
have built it first. Children are dropped before parents on the way down.

Revision ID: c4e81a7f2d93
Revises: b7d2e94a1c60
Create Date: 2026-10-30
"""
import sqlalchemy as sa
from alembic import op

revision = "c4e81a7f2d93"
down_revision = "b7d2e94a1c60"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    existing = _tables()

    if "businesses" not in existing:
        op.create_table(
            "businesses",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("short_name", sa.String(length=80), nullable=True),
            sa.Column("slug", sa.String(length=40), nullable=False),
            sa.Column("texas_taxpayer_number", sa.String(length=11), nullable=True),
            sa.Column("sos_file_number", sa.String(length=20), nullable=True),
            sa.Column("formed_on", sa.Date(), nullable=True),
            sa.Column("franchise_tax_webfile", sa.String(length=20), nullable=True),
            sa.Column("sales_tax_webfile", sa.String(length=20), nullable=True),
            sa.Column("sales_tax_registered_on", sa.Date(), nullable=True),
            sa.Column("sales_tax_first_sale", sa.Date(), nullable=True),
            sa.Column("sales_tax_frequency", sa.String(length=12), nullable=False,
                      server_default="quarterly"),
            sa.Column("taxable_share", sa.Float(), nullable=False, server_default="80"),
            sa.Column("naics_code", sa.String(length=10), nullable=True),
            sa.Column("sales_source", sa.String(length=12), nullable=False,
                      server_default="manual"),
            sa.Column("admin_url", sa.String(length=300), nullable=True),
            sa.Column("hub_slug", sa.String(length=40), nullable=True),
            sa.Column("hub_base_url", sa.String(length=300), nullable=True),
            sa.Column("hub_secret", sa.String(length=120), nullable=True),
            sa.Column("hub_pulled_at", sa.DateTime(), nullable=True),
            sa.Column("hub_pull_note", sa.String(length=300), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_businesses"),
            sa.UniqueConstraint("slug", name="uq_businesses_slug"),
            sa.UniqueConstraint("hub_slug", name="uq_businesses_hub_slug"),
        )

    if "business_locations" not in existing:
        op.create_table(
            "business_locations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("webfile_number", sa.String(length=5), nullable=True),
            sa.Column("label", sa.String(length=100), nullable=False),
            sa.Column("address", sa.String(length=300), nullable=True),
            sa.Column("county", sa.String(length=60), nullable=True),
            sa.Column("local_rate", sa.Float(), nullable=False, server_default="2"),
            sa.Column("opened_on", sa.Date(), nullable=True),
            sa.Column("closed_on", sa.Date(), nullable=True),
            sa.Column("closure_filed", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                    name="fk_business_locations_business_id"),
            sa.PrimaryKeyConstraint("id", name="pk_business_locations"),
        )
        op.create_index("ix_business_locations_business_id", "business_locations",
                        ["business_id"])

    if "sales_tax_filings" not in existing:
        op.create_table(
            "sales_tax_filings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("business_id", sa.Integer(), nullable=False),
            sa.Column("year", sa.Integer(), nullable=False),
            sa.Column("quarter", sa.Integer(), nullable=False),
            sa.Column("filed_at", sa.DateTime(), nullable=True),
            sa.Column("reference_number", sa.String(length=40), nullable=True),
            sa.Column("payment_reference", sa.String(length=40), nullable=True),
            sa.Column("trace_number", sa.String(length=40), nullable=True),
            sa.Column("payment_method", sa.String(length=20), nullable=True),
            sa.Column("total_sales", sa.Float(), nullable=False, server_default="0"),
            sa.Column("taxable_sales", sa.Float(), nullable=False, server_default="0"),
            sa.Column("tax_due", sa.Float(), nullable=False, server_default="0"),
            sa.Column("penalty", sa.Float(), nullable=False, server_default="0"),
            sa.Column("late_filing_penalty", sa.Float(), nullable=False, server_default="0"),
            sa.Column("interest", sa.Float(), nullable=False, server_default="0"),
            sa.Column("discount", sa.Float(), nullable=False, server_default="0"),
            sa.Column("amount_paid", sa.Float(), nullable=False, server_default="0"),
            sa.Column("processing_fee", sa.Float(), nullable=False, server_default="0"),
            sa.Column("locations_json", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("recorded_by", sa.String(length=80), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE",
                                    name="fk_sales_tax_filings_business_id"),
            sa.PrimaryKeyConstraint("id", name="pk_sales_tax_filings"),
            sa.UniqueConstraint("business_id", "year", "quarter",
                                name="uq_sales_tax_filings_period"),
        )
        op.create_index("ix_sales_tax_filings_business_id", "sales_tax_filings",
                        ["business_id"])

    if "sales_tax_filing_files" not in existing:
        op.create_table(
            "sales_tax_filing_files",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("filing_id", sa.Integer(), nullable=False),
            sa.Column("stored_name", sa.String(length=100), nullable=False),
            sa.Column("original_name", sa.String(length=300), nullable=False),
            sa.Column("content_type", sa.String(length=100), nullable=True),
            sa.Column("size", sa.Integer(), nullable=True),
            sa.Column("uploaded_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["filing_id"], ["sales_tax_filings.id"], ondelete="CASCADE",
                                    name="fk_sales_tax_filing_files_filing_id"),
            sa.PrimaryKeyConstraint("id", name="pk_sales_tax_filing_files"),
        )
        op.create_index("ix_sales_tax_filing_files_filing_id", "sales_tax_filing_files",
                        ["filing_id"])


def downgrade():
    existing = _tables()
    # Children before parents: Postgres refuses to drop a table another still
    # points at, where SQLite would let it through.
    for table in ("sales_tax_filing_files", "sales_tax_filings", "business_locations",
                  "businesses"):
        if table in existing:
            op.drop_table(table)
