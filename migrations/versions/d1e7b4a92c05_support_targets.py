"""Which apps Michael supports (SupportApp.supported)

An app wired to the hub during a build that was never contracted is not a
support target. Michael, 2026-11-04, of Robinson & Co.: "there would also be no
tickets even possible on Robinson and Co, because that product never even got
contracted." He chose a switch per app, on by default, with Robinson & Co.
switched off; its rows are kept and leave the board with it.

Revision ID: d1e7b4a92c05
Revises: c6d2a8f41e97
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "d1e7b4a92c05"
down_revision = "c6d2a8f41e97"
branch_labels = None
depends_on = None


def upgrade():
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("support_apps")}
    if "supported" not in have:
        with op.batch_alter_table("support_apps") as batch:
            batch.add_column(sa.Column("supported", sa.Boolean(), nullable=False,
                                       server_default=sa.true()))
    op.get_bind().execute(sa.text(
        "UPDATE support_apps SET supported = :no "
        "WHERE LOWER(origin) LIKE :r OR LOWER(name) LIKE :r"), {"no": False, "r": "%robinson%"})


def downgrade():
    have = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("support_apps")}
    if "supported" in have:
        with op.batch_alter_table("support_apps") as batch:
            batch.drop_column("supported")
