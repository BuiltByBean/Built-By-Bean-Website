"""Scheduling is part of the build, not something sold on top of it

An add-on is one of two things: connecting the client to somebody else's
platform, or handing them what amounts to a second product. Scheduling is
neither. A business that books jobs needs a screen to book jobs on - that is
the custom build doing its job, and charging separately for it is charging
twice for one thing.

Deactivated rather than deleted. The row keeps its wording and its reasoning,
and the decision is one flag to reverse if a client ever wants scheduling
bolted onto a system that was built without it.

Revision ID: e8a4d7b91f06
Revises: d3f95c218a04
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa


revision = "e8a4d7b91f06"
down_revision = "d3f95c218a04"
branch_labels = None
depends_on = None


def upgrade():
    op.get_bind().execute(sa.text(
        "UPDATE products SET is_active = false WHERE slug = 'scheduling'"))


def downgrade():
    op.get_bind().execute(sa.text(
        "UPDATE products SET is_active = true WHERE slug = 'scheduling'"))
