"""Notes: things to do that no other page owns

Four nullable foreign keys, all SET NULL. Closing a project does not mean the
note about it was done, and a note that loses its link still has its words.

Revision ID: c8a41e6b2d05
Revises: b3f9d17c04ae
"""
from alembic import op
import sqlalchemy as sa


revision = "c8a41e6b2d05"
down_revision = "b3f9d17c04ae"
branch_labels = None
depends_on = None


def upgrade():
    # create_all runs on boot and wins the race, so this may already exist.
    # Guarded rather than assumed (CLAUDE.md, migrations).
    if "notes" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("done_at", sa.DateTime(), nullable=True),
        sa.Column("due_on", sa.Date(), nullable=True),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.Integer(), nullable=True),
        sa.Column("playbook_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_notes"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"],
                                name="fk_notes_client_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"],
                                name="fk_notes_project_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"],
                                name="fk_notes_product_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["playbook_id"], ["playbooks.id"],
                                name="fk_notes_playbook_id", ondelete="SET NULL"),
    )
    with op.batch_alter_table("notes") as batch:
        batch.create_index("ix_notes_done_at", ["done_at"])
        batch.create_index("ix_notes_due_on", ["due_on"])
        batch.create_index("ix_notes_client_id", ["client_id"])
        batch.create_index("ix_notes_project_id", ["project_id"])
        batch.create_index("ix_notes_product_id", ["product_id"])
        batch.create_index("ix_notes_playbook_id", ["playbook_id"])


def downgrade():
    if "notes" not in sa.inspect(op.get_bind()).get_table_names():
        return
    op.drop_table("notes")
