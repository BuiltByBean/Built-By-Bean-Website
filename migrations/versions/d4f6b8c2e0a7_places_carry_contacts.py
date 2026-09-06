"""Places carry contacts

Overture Maps publishes an open places dataset with phone numbers, emails,
websites and social pages. Two columns to hold what it adds: the social
page, because a business with a Facebook page and no site of its own is the
easiest call on the list, and the place id it came from.

Revision ID: d4f6b8c2e0a7
Revises: c7e9b3d5a1f4
Create Date: 2026-09-05

"""
from alembic import op
import sqlalchemy as sa


revision = "d4f6b8c2e0a7"
down_revision = "c7e9b3d5a1f4"
branch_labels = None
depends_on = None


def _columns(bind, table):
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    have = _columns(bind, "leads")
    if "social" not in have:
        op.add_column("leads", sa.Column("social", sa.String(length=300), nullable=True))
    if "overture_id" not in have:
        op.add_column("leads", sa.Column("overture_id", sa.String(length=60), nullable=True))


def downgrade():
    bind = op.get_bind()
    have = _columns(bind, "leads")
    with op.batch_alter_table("leads") as batch:
        if "overture_id" in have:
            batch.drop_column("overture_id")
        if "social" in have:
            batch.drop_column("social")
