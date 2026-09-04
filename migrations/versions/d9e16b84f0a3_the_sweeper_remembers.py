"""The sweeper remembers

One row per repository the nightly sweep has read: the blob sha of its
CLAUDE.md, so an unchanged file costs nothing, and the headings already
seen, so only what is new gets proposed.

Revision ID: d9e16b84f0a3
Revises: c4a9d17e5b20
Create Date: 2026-09-04

"""
from alembic import op
import sqlalchemy as sa


revision = "d9e16b84f0a3"
down_revision = "c4a9d17e5b20"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("repo_watches"):
        return
    op.create_table(
        "repo_watches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("repo", sa.String(length=200), nullable=False),
        sa.Column("last_sha", sa.String(length=64), nullable=True),
        sa.Column("seen_json", sa.Text(), nullable=True),
        sa.Column("last_swept_at", sa.DateTime(), nullable=True),
        sa.Column("filed_count", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_repo_watches"),
        sa.UniqueConstraint("repo", name="uq_repo_watches_repo"),
    )


def downgrade():
    op.drop_table("repo_watches")
