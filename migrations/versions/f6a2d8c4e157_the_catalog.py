"""The catalog: approved apps, their tours, and the links prospects open

Issue #23, 2026-11-06. Michael picks which apps go into a private showcase and
sends each prospect a link of their own (catalog_links), which expires and can
be switched off. Each approved tile carries its catalog name, pitch, what it
does, a live demo address once it has one, and the services its code uses;
its tour is catalog_shots. catalog_views is what each link opened.

Every create is guarded on the table or column not existing, because
create_all runs on boot and can get there first.

Revision ID: f6a2d8c4e157
Revises: e8b4c2d6a913
Create Date: 2026-11-06
"""
import sqlalchemy as sa
from alembic import op

revision = "f6a2d8c4e157"
down_revision = "e8b4c2d6a913"
branch_labels = None
depends_on = None

TILE_COLUMNS = [
    sa.Column("catalog", sa.Boolean(), nullable=False, server_default=sa.false()),
    sa.Column("catalog_name", sa.String(120), nullable=True),
    sa.Column("catalog_pitch", sa.Text(), nullable=True),
    sa.Column("catalog_points", sa.Text(), nullable=True),
    sa.Column("catalog_position", sa.Integer(), nullable=True),
    sa.Column("demo_url", sa.String(500), nullable=True),
    sa.Column("catalog_icon", sa.String(120), nullable=True),
    sa.Column("services_json", sa.Text(), nullable=True),
    sa.Column("services_checked_at", sa.DateTime(), nullable=True),
]


def _tables(bind):
    return set(sa.inspect(bind).get_table_names())


def _cols(bind, table):
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    have = _cols(bind, "app_links")
    missing = [c for c in TILE_COLUMNS if c.name not in have]
    if missing:
        with op.batch_alter_table("app_links") as batch:
            for col in missing:
                batch.add_column(col.copy())

    tables = _tables(bind)
    if "catalog_shots" not in tables:
        op.create_table(
            "catalog_shots",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("app_link_id", sa.Integer(), sa.ForeignKey(
                "app_links.id", ondelete="CASCADE", name="fk_catalog_shots_app_link_id"), nullable=False),
            sa.Column("file", sa.String(120), nullable=False),
            sa.Column("caption", sa.String(200), nullable=False, server_default=""),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_catalog_shots_app_link_id", "catalog_shots", ["app_link_id"])
    if "catalog_links" not in tables:
        op.create_table(
            "catalog_links",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("token", sa.String(48), nullable=False),
            sa.Column("label", sa.String(120), nullable=False),
            sa.Column("app_ids_json", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("expires_at", sa.DateTime(), nullable=False),
            sa.Column("revoked_at", sa.DateTime(), nullable=True),
            sa.Column("last_opened_at", sa.DateTime(), nullable=True),
            sa.Column("open_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by_id", sa.Integer(), sa.ForeignKey(
                "users.id", ondelete="SET NULL", name="fk_catalog_links_created_by_id"), nullable=True),
            sa.UniqueConstraint("token", name="uq_catalog_links_token"),
        )
        op.create_index("ix_catalog_links_token", "catalog_links", ["token"])
        op.create_index("ix_catalog_links_created_by_id", "catalog_links", ["created_by_id"])
    if "catalog_views" not in tables:
        op.create_table(
            "catalog_views",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("link_id", sa.Integer(), sa.ForeignKey(
                "catalog_links.id", ondelete="CASCADE", name="fk_catalog_views_link_id"), nullable=False),
            sa.Column("app_link_id", sa.Integer(), sa.ForeignKey(
                "app_links.id", ondelete="SET NULL", name="fk_catalog_views_app_link_id"), nullable=True),
            sa.Column("at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_catalog_views_link_id", "catalog_views", ["link_id"])
        op.create_index("ix_catalog_views_app_link_id", "catalog_views", ["app_link_id"])


def downgrade():
    bind = op.get_bind()
    tables = _tables(bind)
    # Children before parents.
    for table in ("catalog_views", "catalog_shots", "catalog_links"):
        if table in tables:
            op.drop_table(table)
    have = _cols(bind, "app_links")
    gone = [c.name for c in TILE_COLUMNS if c.name in have]
    if gone:
        with op.batch_alter_table("app_links") as batch:
            for name in gone:
                batch.drop_column(name)
