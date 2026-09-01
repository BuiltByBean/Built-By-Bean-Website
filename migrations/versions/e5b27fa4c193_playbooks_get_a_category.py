"""playbooks get a category

Seventeen tiles in one flat grid, ordered by a number nobody remembers
setting. Twilio and the YouTube Data API sat next to each other looking like
comparable jobs, and they are not: one is an account in the client's name with
a carrier approving it over a fortnight, the other is a key and a quota.

Three categories, on the axis that actually matters — how much of it is
somebody else's to do:

    service         an account in someone else's name, money or identity
                    attached, usually an approval gate
    infrastructure  where the code lives and runs, yours to drive
    api             a key and a quota, no relationship to manage

Ordered that way on the page too, so the slow ones are read first.

Revision ID: e5b27fa4c193
Revises: d4e91c62a08b
Create Date: 2026-09-01 17:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e5b27fa4c193'
down_revision = 'd4e91c62a08b'
branch_labels = None
depends_on = None


ASSIGNMENTS = {
    # Somebody else's account, and usually somebody else's timeline.
    "stripe": "service",          # their account, their bank, their identity check
    "twilio": "service",          # their brand, and a carrier approving it
    "tripleseat": "service",      # their venue system, API access on request
    "squarespace": "service",     # their existing site, their domain
    "app-store": "service",       # their developer account, and Apple reviewing it
    "gmail-smtp": "service",      # their Google account, their 2SV, their app password

    # Where it lives and runs. Mine to drive.
    "railway": "infrastructure",
    "postgres": "infrastructure",
    "github": "infrastructure",
    "aws": "infrastructure",
    "cloudflare": "infrastructure",
    "sentry": "infrastructure",
    "resend": "infrastructure",

    # A key and a quota.
    "youtube-api": "api",
    "esv-api": "api",
    "openstreetmap": "api",
    "llm-apis": "api",
}


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "playbooks" not in set(insp.get_table_names()):
        return

    if "category" not in {c["name"] for c in insp.get_columns("playbooks")}:
        with op.batch_alter_table("playbooks", schema=None) as batch_op:
            batch_op.add_column(sa.Column(
                "category", sa.String(length=20), nullable=False,
                server_default="service"))
            batch_op.create_index("ix_playbooks_category", ["category"])

    for slug, category in ASSIGNMENTS.items():
        conn.execute(sa.text(
            "UPDATE playbooks SET category = :c WHERE slug = :s"),
            {"c": category, "s": slug})


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "playbooks" not in set(insp.get_table_names()):
        return
    if "category" in {c["name"] for c in insp.get_columns("playbooks")}:
        with op.batch_alter_table("playbooks", schema=None) as batch_op:
            batch_op.drop_index("ix_playbooks_category")
            batch_op.drop_column("category")
