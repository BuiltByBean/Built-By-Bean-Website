"""The login he uses

The merge before this kept the Michael.Bean row and dropped Mbean, and
Mbean was the login the owner had used all along, so the surviving
account answered to a username he does not type and a password he does
not know. The one account takes back the username Mbean, and, where
MBEAN_PASSWORD is in the environment (it is on the deployed service),
the password that made that account in the first place. Data only,
bound parameters, safe to run twice, no downgrade.

Revision ID: f1a3c5e7b9d2
Revises: e5f7a9c3d1b8
Create Date: 2026-09-05

"""
import os

from alembic import op
import sqlalchemy as sa
from werkzeug.security import generate_password_hash


revision = "f1a3c5e7b9d2"
down_revision = "e5f7a9c3d1b8"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    row = bind.execute(sa.text("SELECT id FROM users WHERE lower(username) = 'michael.bean'")).first()
    if row is not None:
        taken = bind.execute(sa.text("SELECT 1 FROM users WHERE lower(username) = 'mbean' AND id <> :i"),
                             {"i": row[0]}).first()
        if not taken:
            bind.execute(sa.text("UPDATE users SET username = 'Mbean' WHERE id = :i"), {"i": row[0]})
    password = os.environ.get("MBEAN_PASSWORD", "")
    if password:
        bind.execute(sa.text(
            "UPDATE users SET password_hash = :h, must_change_password = :off, is_active = :on, role = 'ceo' "
            "WHERE lower(username) = 'mbean'"
        ), {"h": generate_password_hash(password), "off": False, "on": True})


def downgrade():
    pass
