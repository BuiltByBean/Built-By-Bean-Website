"""The dropdown lesson, paid for a second time

The catalogue's dropdown entry knew about clipping ancestors. It did not
know about stagger animations whose fill-mode leaves every card a stacking
context, which is how this board shipped panels that painted underneath the
next card with their text blurred out by its glass. Appended rather than
rewritten, so an edit made from the page survives.

Revision ID: d7e50f31a9c2
Revises: c9d41e28b7f0
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa


revision = "d7e50f31a9c2"
down_revision = "c9d41e28b7f0"
branch_labels = None
depends_on = None


LESSON = (
    " A glass card's backdrop-filter makes every card a stacking context "
    "all by itself - an entry animation whose fill-mode retains a transform "
    "adds a second way - so a z-50 panel inside card one paints UNDER card "
    "two: the option text sits behind the next card's glass, blurred to "
    "nothing, while the DOM reads perfectly (this board, 2026-09-03, "
    "shipped after being seen and excused as a rendering glitch). Give any "
    "container whose panel can overlap later siblings relative z-30, fill "
    "animations backwards, and verify paint order with elementFromPoint on "
    "the OPEN panel, never by eye."
)


def upgrade():
    bind = op.get_bind()
    # Guarded on the lesson not already being there, so a re-run or a
    # create_all-then-migrate boot cannot append it twice.
    bind.execute(sa.text("""
        UPDATE features
           SET pitfalls_md = pitfalls_md || :lesson
         WHERE slug = 'teleported-dropdown'
           AND pitfalls_md NOT LIKE '%blurred to nothing%'
    """), {"lesson": LESSON})


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("""
        UPDATE features
           SET pitfalls_md = REPLACE(pitfalls_md, :lesson, '')
         WHERE slug = 'teleported-dropdown'
    """), {"lesson": LESSON})
