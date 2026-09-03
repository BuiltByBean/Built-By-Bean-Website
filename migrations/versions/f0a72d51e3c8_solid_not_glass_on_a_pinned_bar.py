"""Solid, not glass, on a pinned bar - correcting the catalogue's lesson

The sticky-filters lesson written earlier today said to give an in-card
bar "its own glass so rows stay readable passing underneath". That taught
the wrong goal with the wrong material: rows are not supposed to stay
readable under a pinned bar, they are supposed to vanish, and glass is
what let them read straight through it an hour after it shipped.

Revision ID: f0a72d51e3c8
Revises: e8f61c40d2b9
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa


revision = "f0a72d51e3c8"
down_revision = "e8f61c40d2b9"
branch_labels = None
depends_on = None


WRONG = ("give an in-card bar its own glass so rows stay readable passing "
         "underneath")
RIGHT = ("back the pinned bar SOLID and pin it flush under the header - a "
         "translucent bar or a gap above it is a window the rows read "
         "straight through, which is the failure being fixed")


def upgrade():
    op.get_bind().execute(sa.text("""
        UPDATE features
           SET gold_standard_md = REPLACE(gold_standard_md, :wrong, :right)
         WHERE slug = 'phone-filter-bars'
    """), {"wrong": WRONG, "right": RIGHT})


def downgrade():
    op.get_bind().execute(sa.text("""
        UPDATE features
           SET gold_standard_md = REPLACE(gold_standard_md, :right, :wrong)
         WHERE slug = 'phone-filter-bars'
    """), {"wrong": WRONG, "right": RIGHT})
