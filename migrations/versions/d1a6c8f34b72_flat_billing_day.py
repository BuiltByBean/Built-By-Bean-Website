"""a billing day, for vendors that bill on a date rather than a month

Anthropic charges on the 17th. Cloudflare and Twilio report their own dates, so
nothing needed one before; a vendor with no billing API has to be told when its
charge lands or the expense gets filed on whatever day the sync happened to
run.

Nullable, because it only means anything for a flat monthly provider. A vendor
whose API reports real charges carries their dates already.

Revision ID: d1a6c8f34b72
Revises: c9b1f47ea230
Create Date: 2026-08-31 13:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd1a6c8f34b72'
down_revision = 'c9b1f47ea230'
branch_labels = None
depends_on = None


def _has_column(conn, table, column):
    return column in {c["name"] for c in sa.inspect(conn).get_columns(table)}


def upgrade():
    if not _has_column(op.get_bind(), "service_providers", "billing_day"):
        with op.batch_alter_table("service_providers", schema=None) as batch_op:
            batch_op.add_column(sa.Column("billing_day", sa.Integer(), nullable=True))


def downgrade():
    if _has_column(op.get_bind(), "service_providers", "billing_day"):
        with op.batch_alter_table("service_providers", schema=None) as batch_op:
            batch_op.drop_column("billing_day")
