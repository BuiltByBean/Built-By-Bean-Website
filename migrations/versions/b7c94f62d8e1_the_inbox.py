"""The inbox: the catalogue starts taking proposals

Until now a session could append a lesson or create a rule, and that was
the whole of what the catalogue could learn from the field. This table is
every other kind of learning - a playbook step that moved, a better file
to copy, a rule whose wording needs work, a product that now exists -
recorded as a proposal with a snapshot of what it replaces, so anything
additive can apply on arrival and anything that rewrites can wait for a
person, and either can be put back with one press.

Revision ID: b7c94f62d8e1
Revises: a4b83e51c7d0
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa


revision = "b7c94f62d8e1"
down_revision = "a4b83e51c7d0"
branch_labels = None
depends_on = None


def upgrade():
    # create_all runs on boot and wins the race, so this only builds the
    # table when nothing has yet.
    bind = op.get_bind()
    if sa.inspect(bind).has_table("catalogue_proposals"):
        return
    op.create_table(
        "catalogue_proposals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("target_slug", sa.String(length=80), nullable=True),
        sa.Column("field", sa.String(length=40), nullable=False),
        sa.Column("mode", sa.String(length=10), nullable=False),
        sa.Column("proposed", sa.Text(), nullable=True),
        sa.Column("previous", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("project", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False,
                  server_default="pending"),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_catalogue_proposals"),
    )
    op.create_index("ix_catalogue_proposals_status", "catalogue_proposals",
                    ["status"])
    op.create_index("ix_catalogue_proposals_target_slug", "catalogue_proposals",
                    ["target_slug"])


def downgrade():
    op.drop_index("ix_catalogue_proposals_target_slug",
                  table_name="catalogue_proposals")
    op.drop_index("ix_catalogue_proposals_status",
                  table_name="catalogue_proposals")
    op.drop_table("catalogue_proposals")
