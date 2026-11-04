"""The icon vocabulary: one drawing per concept, in the Handbook

Michael, 2026-11-04: the icons he uses for concepts belong in the Handbook,
so every project draws notifications, clients or delete the same way
(models.IconConcept, icon_vocabulary.py). One table. Its defaults live in
code (icon_defaults.py) and a row is written the first time the door changes
a concept, so nothing is seeded here.

Guarded on the table not existing, because create_all runs on boot and wins
the race.

Revision ID: b8e4d2a6c013
Revises: d3b8f6a2c915
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "b8e4d2a6c013"
down_revision = "d3b8f6a2c915"
branch_labels = None
depends_on = None


def upgrade():
    if "icon_concepts" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "icon_concepts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("group", sa.String(12), nullable=False, server_default="thing"),
        sa.Column("svg", sa.Text(), nullable=False, server_default=""),
        sa.Column("library", sa.String(80), nullable=True),
        sa.Column("icon_name", sa.String(80), nullable=True),
        sa.Column("aliases", sa.String(400), nullable=True),
        sa.Column("used_in_md", sa.Text(), nullable=True),
        sa.Column("never_md", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("slug", name="uq_icon_concepts_slug"),
    )


def downgrade():
    if "icon_concepts" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("icon_concepts")
