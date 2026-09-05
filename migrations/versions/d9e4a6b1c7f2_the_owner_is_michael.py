"""The owner is Michael

The seed that creates the Mbean account named it Matthew, and that is
the account the owner signs in with, so the Users page called him by
the wrong name. The seed is corrected; this puts the live row right.
Data only, keyed on the wrong value so it touches nothing else and is
safe to run twice. There is no downgrade: nobody wants the wrong name
put back.

Revision ID: d9e4a6b1c7f2
Revises: c8d3f5a7b2e4
Create Date: 2026-09-05

"""
from alembic import op
import sqlalchemy as sa


revision = "d9e4a6b1c7f2"
down_revision = "c8d3f5a7b2e4"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text(
        "UPDATE users SET first_name = 'Michael' "
        "WHERE lower(username) = 'mbean' AND first_name = 'Matthew'"
    ))


def downgrade():
    pass
