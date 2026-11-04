"""One record of every nightly run (models.NightRun, night_log.py)

Guarded on the table not existing, because create_all runs on boot and wins
the race.

Revision ID: b4e9c2a7d153
Revises: a8d3e6f1c047
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "b4e9c2a7d153"
down_revision = "a8d3e6f1c047"
branch_labels = None
depends_on = None


def upgrade():
    if "night_runs" in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        "night_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(10), nullable=False, server_default="running"),
        sa.Column("steps_json", sa.Text(), nullable=True),
    )
    op.create_index("ix_night_runs_started_at", "night_runs", ["started_at"])


def downgrade():
    if "night_runs" in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table("night_runs")
