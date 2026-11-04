"""Gaps: what one app should catch up on, found by comparing it with the others

models.AppGap, written by the Tend run and closed by Michael as done or not
wanted. Guarded on the table not existing, because create_all runs on boot
and wins the race; every constraint named.

Revision ID: a8d3e6f1c047
Revises: f7a2c4e9b318
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "a8d3e6f1c047"
down_revision = "f7a2c4e9b318"
branch_labels = None
depends_on = None


def upgrade():
    if "app_gaps" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "app_gaps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("blueprint_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(120), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("detail_md", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(12), nullable=False, server_default="gap"),
        sa.Column("source_blueprint_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="open"),
        sa.Column("filed_by", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["blueprint_id"], ["app_blueprints.id"], ondelete="CASCADE",
                                name="fk_app_gaps_blueprint_id"),
        sa.ForeignKeyConstraint(["source_blueprint_id"], ["app_blueprints.id"], ondelete="SET NULL",
                                name="fk_app_gaps_source_blueprint_id"),
        sa.UniqueConstraint("blueprint_id", "key", name="uq_app_gaps_blueprint_key"),
    )
    op.create_index("ix_app_gaps_blueprint_id", "app_gaps", ["blueprint_id"])
    op.create_index("ix_app_gaps_source_blueprint_id", "app_gaps", ["source_blueprint_id"])
    op.create_index("ix_app_gaps_status", "app_gaps", ["status"])


def downgrade():
    if "app_gaps" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("app_gaps")
