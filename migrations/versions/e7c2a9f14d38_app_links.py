"""the apps board becomes rows instead of a hardcoded template

Adding something to the board meant editing a template and deploying. It is a
list of links; it should be a table.

Seeded with what is actually deployed on Railway today, so the board is useful
the moment it exists rather than being an empty page with an Add button. URLs
are the ones in use: J&D is staff.jdentertain.com rather than the two other
domains pointing at the same service, and Christ Community Church is on its
railway.app address until it has a domain of its own.

Descriptions are deliberately left empty except for the two pages that came
from the old hub and already had wording. They are the owner's to write, and
inventing a sentence about somebody's app is how a board fills up with
confident nonsense.

Icons are not seeded: they are fetched from each app's own manifest or
favicon, which is a network call and has no business inside a migration.

Revision ID: e7c2a9f14d38
Revises: b4d70e2f1a93
Create Date: 2026-09-01 06:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e7c2a9f14d38'
down_revision = 'b4d70e2f1a93'
branch_labels = None
depends_on = None


SEED = [
    ("Built By Beans", "https://builtbybeans.com", ""),
    ("Data Dungeon", "https://datadungeon.io", ""),
    ("Kuper Plumbing", "https://kuperplumbing.com", ""),
    ("The Wisdom Crucible", "https://thewisdomcrucible.com", ""),
    ("J&D Entertainment", "https://staff.jdentertain.com", ""),
    ("Christ Community Church", "https://covenantchristianchurch-production.up.railway.app", ""),
    ("Signadoc", "https://signadoc-production.up.railway.app",
     "Self-hosted e-signature portal. Contracts sent from here open in it."),
    ("Chop Builder", "https://chopbuilder-production.up.railway.app", ""),
    ("CrossFit Games", "https://crossfit-games-production.up.railway.app", ""),
    ("Flipping", "https://flipping-production.up.railway.app", ""),
    ("Gym Ecosystem", "https://gym-ecosystem-production.up.railway.app", ""),
    ("Personal Trainer", "https://personal-trainer-production-5aa8.up.railway.app", ""),
    ("The Pluralism Within", "/Pluralism",
     "Interactive D3.js visualisation tracing the fractures of Christendom."),
    ("Bible Study", "/Bible-Study",
     "Scripture reader with notes, tags, questions, journal and topics."),
]


def upgrade():
    conn = op.get_bind()
    if 'app_links' not in sa.inspect(conn).get_table_names():
        table = op.create_table(
            'app_links',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(length=120), nullable=False),
            sa.Column('url', sa.String(length=500), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('icon_file', sa.String(length=120), nullable=True),
            sa.Column('icon_source', sa.String(length=500), nullable=True),
            sa.Column('icon_fetched_at', sa.DateTime(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id', name='pk_app_links'),
        )
    else:
        # create_all() runs when the app is imported, which happens before
        # this does, so on a real deploy the table is already here and empty.
        # Keying the seed off creation would mean it never ran.
        table = sa.table('app_links',
                         sa.column('name', sa.String),
                         sa.column('url', sa.String),
                         sa.column('description', sa.Text))

    # Seeded only into an empty board, so this cannot duplicate and cannot
    # resurrect a tile somebody deliberately removed.
    if not conn.execute(sa.text("SELECT COUNT(*) FROM app_links")).scalar():
        op.bulk_insert(table, [
            {"name": n, "url": u, "description": d} for n, u, d in SEED
        ])


def downgrade():
    conn = op.get_bind()
    if 'app_links' in sa.inspect(conn).get_table_names():
        op.drop_table('app_links')
