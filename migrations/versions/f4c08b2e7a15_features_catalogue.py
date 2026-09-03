"""What I have built before, catalogued once

Revision ID: f4c08b2e7a15
Revises: e8a4d7b91f06
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa


revision = "f4c08b2e7a15"
down_revision = "e8a4d7b91f06"
branch_labels = None
depends_on = None


def upgrade():
    # Guarded: create_app runs db.create_all() on boot and the deploy's own
    # `flask db upgrade` loads the app first, so the table can already be here.
    if "features" not in set(sa.inspect(op.get_bind()).get_table_names()):
        op.create_table(
            "features",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("slug", sa.String(length=80), nullable=False),
            sa.Column("name", sa.String(length=160), nullable=False),
            sa.Column("category", sa.String(length=20), nullable=False,
                      server_default="records"),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("typical_value", sa.Float(), nullable=True),
            sa.Column("gold_standard_md", sa.Text(), nullable=True),
            sa.Column("pitfalls_md", sa.Text(), nullable=True),
            sa.Column("reference_project", sa.String(length=120), nullable=True),
            sa.Column("reference_path", sa.String(length=300), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False,
                      server_default="built"),
            sa.Column("is_active", sa.Boolean(), nullable=False,
                      server_default=sa.true()),
            sa.Column("sort_order", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug", name="uq_features_slug"),
        )
        op.create_index("ix_features_category", "features", ["category"])


def downgrade():
    op.drop_index("ix_features_category", table_name="features")
    op.drop_table("features")
