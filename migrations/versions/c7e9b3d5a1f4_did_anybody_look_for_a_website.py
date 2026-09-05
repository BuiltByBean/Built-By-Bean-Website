"""Did anybody look for a website

An empty website column meant "no source mentioned one", and the board read
it as "they have no website". Those are different facts. This column records
when somebody actually went looking, so the absence can be stated only once
it has been established.

Revision ID: c7e9b3d5a1f4
Revises: b2c4e6a8f0d1
Create Date: 2026-09-05

"""
from alembic import op
import sqlalchemy as sa


revision = "c7e9b3d5a1f4"
down_revision = "b2c4e6a8f0d1"
branch_labels = None
depends_on = None


def _columns(bind, table):
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    if "website_checked_at" not in _columns(bind, "leads"):
        op.add_column("leads", sa.Column("website_checked_at", sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    if "website_checked_at" in _columns(bind, "leads"):
        with op.batch_alter_table("leads") as batch:
            batch.drop_column("website_checked_at")
