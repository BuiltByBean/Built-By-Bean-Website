"""Catalog links remember who they were emailed to, and when

Issue #26, 2026-11-06: a catalog link can be sent by email from the board, to a
client or to any name and address typed in.

Revision ID: c3e5a7b9d024
Revises: b2d4f6a8c013
Create Date: 2026-11-06
"""
import sqlalchemy as sa
from alembic import op

revision = "c3e5a7b9d024"
down_revision = "b2d4f6a8c013"
branch_labels = None
depends_on = None


def _cols(bind):
    return {c["name"] for c in sa.inspect(bind).get_columns("catalog_links")}


def upgrade():
    bind = op.get_bind()
    if "catalog_links" not in sa.inspect(bind).get_table_names():
        return
    have = _cols(bind)
    with op.batch_alter_table("catalog_links") as batch:
        if "email" not in have:
            batch.add_column(sa.Column("email", sa.String(200), nullable=True))
        if "client_id" not in have:
            batch.add_column(sa.Column("client_id", sa.Integer(), nullable=True))
            batch.create_foreign_key("fk_catalog_links_client_id", "clients", ["client_id"], ["id"],
                                     ondelete="SET NULL")
            batch.create_index("ix_catalog_links_client_id", ["client_id"])
        if "sent_at" not in have:
            batch.add_column(sa.Column("sent_at", sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    if "catalog_links" not in sa.inspect(bind).get_table_names():
        return
    have = _cols(bind)
    with op.batch_alter_table("catalog_links") as batch:
        if "client_id" in have:
            batch.drop_index("ix_catalog_links_client_id")
            batch.drop_constraint("fk_catalog_links_client_id", type_="foreignkey")
            batch.drop_column("client_id")
        for name in ("sent_at", "email"):
            if name in have:
                batch.drop_column(name)
