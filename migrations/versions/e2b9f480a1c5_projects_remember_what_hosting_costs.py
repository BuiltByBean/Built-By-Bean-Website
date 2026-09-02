"""projects remember what hosting costs

The hosting and infrastructure fee has always been typed into the statement of
work, printed into the PDF, and then forgotten. Nothing in the app knew what any
client had agreed to pay to stay online, so there was no way to compare it to
what keeping them online actually costs - which is the whole question worth
asking about a recurring fee.

Two columns on the project, because that is the thing being hosted and the thing
a Railway project maps to. A client with two applications is paying for two, and
one number on the client would have to be split back apart by hand every time.

hosting_fee is nullable and nothing defaults it. Zero would mean "hosted for
free", which is a real and different answer from "nobody has set this yet", and
the difference decides whether a project belongs on the hosting margin page at
all.

Revision ID: e2b9f480a1c5
Revises: d4c7a1e93f60
Create Date: 2026-09-02 09:45:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e2b9f480a1c5'
down_revision = 'd4c7a1e93f60'
branch_labels = None
depends_on = None


NEW_COLUMNS = (
    ("hosting_fee", sa.Float()),
    ("hosting_cycle", sa.String(length=20)),
)


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "projects" not in set(insp.get_table_names()):
        return

    have = {c["name"] for c in insp.get_columns("projects")}
    with op.batch_alter_table("projects", schema=None) as batch_op:
        for name, kind in NEW_COLUMNS:
            if name not in have:
                batch_op.add_column(sa.Column(name, kind, nullable=True))


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "projects" not in set(insp.get_table_names()):
        return

    have = {c["name"] for c in insp.get_columns("projects")}
    with op.batch_alter_table("projects", schema=None) as batch_op:
        for name, _ in NEW_COLUMNS:
            if name in have:
                batch_op.drop_column(name)
