"""Email templates: his edits to a saved email (issue #41).

Revision ID: f1d3b5a7c962
Revises: e9c1a3f5b247

The defaults live in email_templates.py; a row is written only once he
changes one on the board.
"""
from alembic import op
import sqlalchemy as sa

revision = "f1d3b5a7c962"
down_revision = "e9c1a3f5b247"
branch_labels = None
depends_on = None


def upgrade():
    if "email_templates" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "email_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("slug", sa.String(60), nullable=False),
        sa.Column("name", sa.String(120), nullable=False, server_default=""),
        sa.Column("subject", sa.String(300), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("slug", name="uq_email_templates_slug"),
    )


def downgrade():
    if "email_templates" in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table("email_templates")
