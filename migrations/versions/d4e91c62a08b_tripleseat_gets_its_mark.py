"""Tripleseat gets its mark

It shipped with initials because simple-icons has no Tripleseat entry, which
is fair enough — it is a venue-industry tool, not a developer brand. But
Tripleseat publishes a perfectly good 300x300 icon of its own, so there was a
real mark to be had; nobody had gone and looked for it.

Fetched from their site rather than drawn, same rule as every other logo here.
The ESV API keeps its initials: Crossway publishes no icon.

Revision ID: d4e91c62a08b
Revises: c1f8b03d7a52
Create Date: 2026-09-01 17:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e91c62a08b'
down_revision = 'c1f8b03d7a52'
branch_labels = None
depends_on = None


LOGO = "pm/logos/tripleseat.png"


def upgrade():
    conn = op.get_bind()
    if "playbooks" not in set(sa.inspect(conn).get_table_names()):
        return
    # Only where it still has none, so a hand-picked logo is never replaced.
    conn.execute(sa.text(
        "UPDATE playbooks SET logo_path = :p WHERE slug = 'tripleseat' "
        "AND (logo_path IS NULL OR logo_path = '')"), {"p": LOGO})


def downgrade():
    conn = op.get_bind()
    if "playbooks" not in set(sa.inspect(conn).get_table_names()):
        return
    conn.execute(sa.text(
        "UPDATE playbooks SET logo_path = '' WHERE slug = 'tripleseat' "
        "AND logo_path = :p"), {"p": LOGO})
