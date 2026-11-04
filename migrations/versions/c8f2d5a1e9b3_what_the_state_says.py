"""What the state says: the franchise search, the permit list, the rate file,
drafted returns and the deadline list (comptroller.py, deadlines.py)

Every column and table is guarded, because create_all runs on boot and wins
the race on a fresh database.

Revision ID: c8f2d5a1e9b3
Revises: c6d2a8e41f97
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "c8f2d5a1e9b3"
down_revision = "c6d2a8e41f97"
branch_labels = None
depends_on = None

BUSINESS_COLUMNS = (
    ("ein", sa.String(12)),
    ("franchise_status", sa.String(30)),
    ("sos_status", sa.String(30)),
    ("registered_agent", sa.String(200)),
    ("registered_office", sa.String(300)),
    ("mailing_address", sa.String(300)),
    ("franchise_report_year", sa.Integer()),
    ("comptroller_checked_at", sa.DateTime()),
    ("comptroller_note", sa.String(300)),
    ("permit_status", sa.String(10)),
    ("permit_checked_at", sa.DateTime()),
    ("assumed_name_filed_on", sa.Date()),
)
LOCATION_COLUMNS = (
    ("city", sa.String(80)),
    ("inside_city_limits", sa.Boolean()),
    ("permit_listed", sa.Boolean()),
    ("permit_seen_at", sa.DateTime()),
    ("rate_source", sa.String(40)),
    ("rate_note", sa.String(200)),
)


def _columns(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    have = _columns("businesses")
    with op.batch_alter_table("businesses") as batch:
        for name, kind in BUSINESS_COLUMNS:
            if name not in have:
                batch.add_column(sa.Column(name, kind, nullable=True))

    have = _columns("business_locations")
    with op.batch_alter_table("business_locations") as batch:
        for name, kind in LOCATION_COLUMNS:
            if name not in have:
                batch.add_column(sa.Column(name, kind, nullable=True))

    if "drafted_from_line_id" not in _columns("sales_tax_filings"):
        with op.batch_alter_table("sales_tax_filings") as batch:
            batch.add_column(sa.Column("drafted_from_line_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_sales_tax_filings_drafted_from_line_id", "bank_transactions",
                                     ["drafted_from_line_id"], ["id"], ondelete="SET NULL")
            batch.create_index("ix_sales_tax_filings_drafted_from_line_id", ["drafted_from_line_id"])

    tables = _tables()
    if "comptroller_flags" not in tables:
        op.create_table(
            "comptroller_flags",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("business_id", sa.Integer(), sa.ForeignKey(
                "businesses.id", ondelete="CASCADE", name="fk_comptroller_flags_business_id"),
                nullable=False),
            sa.Column("location_id", sa.Integer(), sa.ForeignKey(
                "business_locations.id", ondelete="SET NULL", name="fk_comptroller_flags_location_id"),
                nullable=True),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("old_value", sa.String(300), nullable=True),
            sa.Column("new_value", sa.String(300), nullable=True),
            sa.Column("seen_at", sa.DateTime(), nullable=True),
            sa.Column("seen_by", sa.String(80), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_comptroller_flags_business_id", "comptroller_flags", ["business_id"])
        op.create_index("ix_comptroller_flags_location_id", "comptroller_flags", ["location_id"])
        op.create_index("ix_comptroller_flags_seen_at", "comptroller_flags", ["seen_at"])
    if "deadline_done" not in tables:
        op.create_table(
            "deadline_done",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("key", sa.String(80), nullable=False),
            sa.Column("done_at", sa.DateTime(), nullable=True),
            sa.Column("done_by", sa.String(80), nullable=True),
            sa.UniqueConstraint("key", name="uq_deadline_done_key"),
        )


def downgrade():
    tables = _tables()
    if "deadline_done" in tables:
        op.drop_table("deadline_done")
    if "comptroller_flags" in tables:
        op.drop_table("comptroller_flags")
    if "drafted_from_line_id" in _columns("sales_tax_filings"):
        with op.batch_alter_table("sales_tax_filings") as batch:
            batch.drop_index("ix_sales_tax_filings_drafted_from_line_id")
            batch.drop_constraint("fk_sales_tax_filings_drafted_from_line_id", type_="foreignkey")
            batch.drop_column("drafted_from_line_id")
    have = _columns("business_locations")
    with op.batch_alter_table("business_locations") as batch:
        for name, _kind in reversed(LOCATION_COLUMNS):
            if name in have:
                batch.drop_column(name)
    have = _columns("businesses")
    with op.batch_alter_table("businesses") as batch:
        for name, _kind in reversed(BUSINESS_COLUMNS):
            if name in have:
                batch.drop_column(name)
