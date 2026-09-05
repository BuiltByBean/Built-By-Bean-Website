"""Titles on the door

The role vocabulary becomes CEO, CTO, CMO and member. Every account that
was an owner (or still an admin) becomes the CEO, so nothing that existed
loses a door; the other titles are handed out from the Users page after.
Data only, no schema change, and safe to run twice.

Revision ID: c8d3f5a7b2e4
Revises: a5b29e17c3d6
Create Date: 2026-09-05

"""
from alembic import op
import sqlalchemy as sa


revision = "c8d3f5a7b2e4"
down_revision = "a5b29e17c3d6"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text("UPDATE users SET role = 'ceo' WHERE role IN ('owner', 'admin')"))


def downgrade():
    op.get_bind().execute(sa.text("UPDATE users SET role = 'owner' WHERE role IN ('ceo', 'cto', 'cmo')"))
