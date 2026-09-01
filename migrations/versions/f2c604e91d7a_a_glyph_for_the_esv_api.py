"""a glyph for the ESV API, and it is not a logo

The last playbook on initials. Crossway publishes no icon for the ESV API, so
there was no mark to fetch and the rule here is that logos are not drawn.

The compromise Michael picked: a generic open-book glyph rather than an
invented Crossway logo, so the grid looks uniform without anything pretending
to be a brand it is not. It is the same book icon the playbooks UI already
uses, on a neutral slate ground — every other tile carries a vendor's own
colour, so slate reads as "there is no mark here".

Seventeen of seventeen have an icon now; sixteen of them are real.

Revision ID: f2c604e91d7a
Revises: e5b27fa4c193
Create Date: 2026-09-01 18:15:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f2c604e91d7a'
down_revision = 'e5b27fa4c193'
branch_labels = None
depends_on = None


LOGO = "pm/logos/book.svg"


def upgrade():
    conn = op.get_bind()
    if "playbooks" not in set(sa.inspect(conn).get_table_names()):
        return
    conn.execute(sa.text(
        "UPDATE playbooks SET logo_path = :p WHERE slug = 'esv-api' "
        "AND (logo_path IS NULL OR logo_path = '')"), {"p": LOGO})


def downgrade():
    conn = op.get_bind()
    if "playbooks" not in set(sa.inspect(conn).get_table_names()):
        return
    conn.execute(sa.text(
        "UPDATE playbooks SET logo_path = '' WHERE slug = 'esv-api' "
        "AND logo_path = :p"), {"p": LOGO})
