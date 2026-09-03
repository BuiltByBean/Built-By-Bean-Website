"""The MVP, assembled: packages of products and features per client

Revision ID: b6e02d94c7a1
Revises: a91c53e0d7b4
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa


revision = "b6e02d94c7a1"
down_revision = "a91c53e0d7b4"
branch_labels = None
depends_on = None


def upgrade():
    # Guarded: create_app runs db.create_all() on boot and the deploy's own
    # `flask db upgrade` loads the app first, so the tables can already exist.
    have = set(sa.inspect(op.get_bind()).get_table_names())

    if "mvp_packages" not in have:
        op.create_table(
            "mvp_packages",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False,
                      server_default="scoping"),
            sa.Column("price_override", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"],
                                    name="fk_mvp_packages_client_id",
                                    ondelete="CASCADE"),
        )
        op.create_index("ix_mvp_packages_client_id", "mvp_packages",
                        ["client_id"])

    if "mvp_package_items" not in have:
        op.create_table(
            "mvp_package_items",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("package_id", sa.Integer(), nullable=False),
            sa.Column("kind", sa.String(length=10), nullable=False,
                      server_default="feature"),
            sa.Column("feature_id", sa.Integer(), nullable=True),
            sa.Column("product_id", sa.Integer(), nullable=True),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("price", sa.Float(), nullable=True),
            sa.Column("monthly_price", sa.Float(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.ForeignKeyConstraint(["package_id"], ["mvp_packages.id"],
                                    name="fk_mvp_package_items_package_id",
                                    ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["feature_id"], ["features.id"],
                                    name="fk_mvp_package_items_feature_id",
                                    ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["product_id"], ["products.id"],
                                    name="fk_mvp_package_items_product_id",
                                    ondelete="SET NULL"),
        )
        op.create_index("ix_mvp_package_items_package_id",
                        "mvp_package_items", ["package_id"])
        op.create_index("ix_mvp_package_items_feature_id",
                        "mvp_package_items", ["feature_id"])
        op.create_index("ix_mvp_package_items_product_id",
                        "mvp_package_items", ["product_id"])


def downgrade():
    # Children before parents, or Postgres refuses the drop.
    op.drop_index("ix_mvp_package_items_product_id",
                  table_name="mvp_package_items")
    op.drop_index("ix_mvp_package_items_feature_id",
                  table_name="mvp_package_items")
    op.drop_index("ix_mvp_package_items_package_id",
                  table_name="mvp_package_items")
    op.drop_table("mvp_package_items")
    op.drop_index("ix_mvp_packages_client_id", table_name="mvp_packages")
    op.drop_table("mvp_packages")
