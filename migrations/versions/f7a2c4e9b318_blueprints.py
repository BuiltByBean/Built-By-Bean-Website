"""Blueprints: a whole app end to end, to start the next one from

Michael, 2026-11-04: playbooks are one vendor each, and a new project of a
known shape runs a dozen of them in an order nobody wrote down. A blueprint is
that order, the parts, how they talk, what changes per project and the traps
between systems (models.AppBlueprint, app_blueprints.py). Two tables, and a
package in the MVP Builder can start from one.

Each create is guarded on the table not existing, because create_all runs on
boot and wins the race; the column on mvp_packages goes in a batch with its
named foreign key and index. Children are dropped before parents.

Revision ID: f7a2c4e9b318
Revises: e5c3a9b17d42
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "f7a2c4e9b318"
down_revision = "e5c3a9b17d42"
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    have = _tables()
    if "app_blueprints" not in have:
        op.create_table(
            "app_blueprints",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("slug", sa.String(80), nullable=False),
            sa.Column("name", sa.String(160), nullable=False),
            sa.Column("one_liner", sa.String(400), nullable=True),
            sa.Column("source_repos", sa.String(400), nullable=True),
            sa.Column("shape_md", sa.Text(), nullable=True),
            sa.Column("parts_md", sa.Text(), nullable=True),
            sa.Column("connections_md", sa.Text(), nullable=True),
            sa.Column("tweaks_md", sa.Text(), nullable=True),
            sa.Column("traps_md", sa.Text(), nullable=True),
            sa.Column("app_id", sa.Integer(), nullable=True),
            sa.Column("business_id", sa.Integer(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["app_id"], ["app_links.id"], ondelete="SET NULL",
                                    name="fk_app_blueprints_app_id"),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="SET NULL",
                                    name="fk_app_blueprints_business_id"),
            sa.UniqueConstraint("slug", name="uq_app_blueprints_slug"),
        )
        op.create_index("ix_app_blueprints_app_id", "app_blueprints", ["app_id"])
        op.create_index("ix_app_blueprints_business_id", "app_blueprints", ["business_id"])
    if "app_blueprint_stages" not in have:
        op.create_table(
            "app_blueprint_stages",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("blueprint_id", sa.Integer(), nullable=False),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("detail_md", sa.Text(), nullable=True),
            sa.Column("playbooks_json", sa.Text(), nullable=True),
            sa.Column("features_json", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["blueprint_id"], ["app_blueprints.id"], ondelete="CASCADE",
                                    name="fk_app_blueprint_stages_blueprint_id"),
        )
        op.create_index("ix_app_blueprint_stages_blueprint_id", "app_blueprint_stages", ["blueprint_id"])
    if "mvp_packages" in have and "blueprint_id" not in _columns("mvp_packages"):
        with op.batch_alter_table("mvp_packages", schema=None) as batch_op:
            batch_op.add_column(sa.Column("blueprint_id", sa.Integer(), nullable=True))
            batch_op.create_foreign_key("fk_mvp_packages_blueprint_id", "app_blueprints",
                                        ["blueprint_id"], ["id"], ondelete="SET NULL")
            batch_op.create_index("ix_mvp_packages_blueprint_id", ["blueprint_id"])


def downgrade():
    have = _tables()
    if "mvp_packages" in have and "blueprint_id" in _columns("mvp_packages"):
        with op.batch_alter_table("mvp_packages", schema=None) as batch_op:
            try:
                batch_op.drop_index("ix_mvp_packages_blueprint_id")
            except Exception:
                pass
            try:
                batch_op.drop_constraint("fk_mvp_packages_blueprint_id", type_="foreignkey")
            except Exception:
                pass
            batch_op.drop_column("blueprint_id")
    if "app_blueprint_stages" in have:
        op.drop_table("app_blueprint_stages")
    if "app_blueprints" in have:
        op.drop_table("app_blueprints")
