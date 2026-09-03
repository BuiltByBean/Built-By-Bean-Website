"""Filters stay while the list scrolls - onto the catalogue entry

The phone-filter-bars entry knew about the mobile collapse pattern. It did
not say the bar must PIN: every list page here shipped with the search box
scrolling away above the very rows it filters, found on the page that is
open during a phone call. Appended rather than rewritten, so an edit made
from the page survives.

Revision ID: e8f61c40d2b9
Revises: d7e50f31a9c2
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa


revision = "e8f61c40d2b9"
down_revision = "d7e50f31a9c2"
branch_labels = None
depends_on = None


LESSON = (
    " And the bar stays put: a search box that scrolls away above the list "
    "it filters means scrolling back up to refine, on exactly the page that "
    "is open mid-call. Pin it below the sticky header with position sticky "
    "and an offset MEASURED off the real header (headers wrap on phones), "
    "give an in-card bar its own glass so rows stay readable passing "
    "underneath, and verify by scrolling - the failure does not exist in a "
    "screenshot taken at the top of the page (this board, 2026-09-03, every "
    "list page)."
)


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        UPDATE features
           SET gold_standard_md = gold_standard_md || :lesson
         WHERE slug = 'phone-filter-bars'
           AND gold_standard_md NOT LIKE '%the bar stays put%'
    """), {"lesson": LESSON})


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        UPDATE features
           SET gold_standard_md = REPLACE(gold_standard_md, :lesson, '')
         WHERE slug = 'phone-filter-bars'
    """), {"lesson": LESSON})
