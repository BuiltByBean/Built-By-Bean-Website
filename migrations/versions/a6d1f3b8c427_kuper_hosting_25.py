"""Kuper Plumbing's hosting is $25 a month

Michael, 2026-11-05: the new hosting subscription he set up for Cason Kuper
bills $25 a month, and asked whether that or the board's $50 was right: "$25
is right". The board's agreed fee follows him, so Hosting stops offering to
raise the subscription to $50. Only while it still reads $50, so a fee
somebody changed since is left alone; downgrade puts back $50 the same way.

Revision ID: a6d1f3b8c427
Revises: f4c9a2e6b318
Create Date: 2026-11-05
"""
import sqlalchemy as sa
from alembic import op

revision = "a6d1f3b8c427"
down_revision = "f4c9a2e6b318"
branch_labels = None
depends_on = None

NAME = "Kuper Plumbing"


def _set(old, new):
    n = op.get_bind().execute(sa.text(
        "UPDATE projects SET hosting_fee = :new WHERE name = :n AND hosting_fee = :old"),
        {"new": new, "old": old, "n": NAME}).rowcount
    print(f"{NAME}: hosting fee {old} -> {new} on {n} project(s)")


def upgrade():
    _set(50.0, 25.0)


def downgrade():
    _set(25.0, 50.0)
