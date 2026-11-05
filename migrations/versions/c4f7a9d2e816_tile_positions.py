"""My Apps tiles keep the place they were dragged to

Michael, 2026-11-05: dragging a tile up a row into the middle did nothing,
because tiles were ordered by id and the drag only knew which half it was
dropped in. `app_links.position` is the order a drag saves; NULL follows.

Guarded on the column not existing, because create_all runs on boot.

Revision ID: c4f7a9d2e816
Revises: b8e4f2a6c931
Create Date: 2026-11-05
"""
import sqlalchemy as sa
from alembic import op

revision = "c4f7a9d2e816"
down_revision = "b8e4f2a6c931"
branch_labels = None
depends_on = None


def _cols():
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns("app_links")}


def upgrade():
    if "position" not in _cols():
        op.add_column("app_links", sa.Column("position", sa.Integer(), nullable=True))


def downgrade():
    if "position" in _cols():
        with op.batch_alter_table("app_links") as batch:
            batch.drop_column("position")
