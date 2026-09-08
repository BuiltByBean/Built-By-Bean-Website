"""The two rules against building in the default shape get their own category

Both were filed through the guidance door before this category existed, so
they landed in Interface patterns. The door validates a category against
Feature.CATEGORY_LABELS and falls back rather than refusing, which is the
right behaviour and also why this has to move them afterwards.

Matched on slug, and only where the category is still the one the fallback
gave them, so a later hand edit is not overwritten.

Revision ID: d1b5f83a27c4
Revises: c8a41e6b2d05
"""
from alembic import op
import sqlalchemy as sa


revision = "d1b5f83a27c4"
down_revision = "c8a41e6b2d05"
branch_labels = None
depends_on = None


SLUGS = ("no-claude-classics", "no-em-dashes-anywhere")
NEW = "classics"
OLD = "ui"


def upgrade():
    op.get_bind().execute(
        sa.text("UPDATE features SET category = :new "
                "WHERE slug IN :slugs AND category = :old")
        .bindparams(sa.bindparam("slugs", expanding=True)),
        {"new": NEW, "old": OLD, "slugs": list(SLUGS)})


def downgrade():
    op.get_bind().execute(
        sa.text("UPDATE features SET category = :old "
                "WHERE slug IN :slugs AND category = :new")
        .bindparams(sa.bindparam("slugs", expanding=True)),
        {"new": NEW, "old": OLD, "slugs": list(SLUGS)})
