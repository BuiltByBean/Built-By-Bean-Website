"""a client can ask for changes, and it lands here

The signing portal has always let somebody decline with a reason - it records
it, flips the envelope and emails the sender. None of that reached this board,
so a client saying "section 5 is wrong" arrived as an email and lived in an
inbox, which is the one place a negotiation cannot be picked up from three
weeks later by anybody but the person who received it.

Four columns. The reason and when it was given; the form that produced the
document, so a revision starts from what was actually sent rather than from a
blank page and somebody's memory; and a link back to the request being
replaced, so a back-and-forth reads as a thread rather than as four unrelated
envelopes to the same person.

Revision ID: a7c4e0d51f83
Revises: f2c604e91d7a
Create Date: 2026-09-01 19:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a7c4e0d51f83'
down_revision = 'f2c604e91d7a'
branch_labels = None
depends_on = None


COLUMNS = (
    ("decline_reason", sa.Text()),
    ("declined_at", sa.DateTime()),
    ("form_json", sa.Text()),
    ("revision_of_id", sa.Integer()),
)


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "signature_requests" not in set(insp.get_table_names()):
        return
    have = {c["name"] for c in insp.get_columns("signature_requests")}
    with op.batch_alter_table("signature_requests", schema=None) as batch_op:
        for name, kind in COLUMNS:
            if name not in have:
                batch_op.add_column(sa.Column(name, kind, nullable=True))
        if "revision_of_id" not in have:
            # SET NULL rather than CASCADE: deleting a superseded request must
            # not take the revision that replaced it, which is the one that
            # matters.
            batch_op.create_foreign_key(
                "fk_signature_requests_revision_of_id", "signature_requests",
                ["revision_of_id"], ["id"], ondelete="SET NULL")


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    if "signature_requests" not in set(insp.get_table_names()):
        return
    have = {c["name"] for c in insp.get_columns("signature_requests")}
    with op.batch_alter_table("signature_requests", schema=None) as batch_op:
        if "revision_of_id" in have:
            try:
                batch_op.drop_constraint("fk_signature_requests_revision_of_id",
                                         type_="foreignkey")
            except Exception:
                pass
        for name, _ in COLUMNS:
            if name in have:
                batch_op.drop_column(name)
