"""Best Practices curate themselves: nothing waits on a yes

Michael, 2026-11-02: "stop this waiting on a yes thing. Just have it adjust
properly over time." Every proposal still waiting becomes a candidate for
the nightly curator, which reads it, then writes a rule from it, folds it
into one, or discards it. curator_runs records each night.

Revision ID: d8e3a6f1b204
Revises: c0e4b7d2a915
Create Date: 2026-11-02
"""
import sqlalchemy as sa
from alembic import op

revision = "d8e3a6f1b204"
down_revision = "c0e4b7d2a915"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("curator_runs"):
        op.create_table(
            "curator_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("status", sa.String(length=10), nullable=False),
            sa.Column("model", sa.String(length=60), nullable=True),
            sa.Column("added", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("folded", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("merged", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("tightened", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("retired", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("discarded", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rules_before", sa.Integer(), nullable=True),
            sa.Column("rules_after", sa.Integer(), nullable=True),
            sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("note", sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_curator_runs"),
        )
    bind.execute(sa.text(
        "UPDATE catalogue_proposals SET status = 'candidate' WHERE status = 'pending'"))


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        "UPDATE catalogue_proposals SET status = 'pending' WHERE status = 'candidate'"))
    if sa.inspect(bind).has_table("curator_runs"):
        op.drop_table("curator_runs")
