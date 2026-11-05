"""The volume inbox: files the nightly service makes, on their way to the volume

2026-11-05: cost-sync has no volume, so the icons and receipts it wrote landed
on its own disk and the website answered 404 for them. It leaves them here
now and the web service moves them onto /data (volume_files.py).

Guarded on the table not existing, because create_all runs on boot.

Revision ID: b8e4f2a6c931
Revises: a7d3e1c95b20
Create Date: 2026-11-05
"""
import sqlalchemy as sa
from alembic import op

revision = "b8e4f2a6c931"
down_revision = "a7d3e1c95b20"
branch_labels = None
depends_on = None


def upgrade():
    if "volume_inbox" not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "volume_inbox",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("folder", sa.String(length=40), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("data", sa.LargeBinary(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_volume_inbox"),
            sa.UniqueConstraint("folder", "name", name="uq_volume_inbox_folder_name"),
        )


def downgrade():
    if "volume_inbox" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("volume_inbox")
