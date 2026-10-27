"""Forget the signing links

A signer's link from the portal is a sign-in AS that signer, good for fourteen
days and for more than one click. Whoever holds it can sign in their name. The
board kept one for every contract on `signature_requests.signing_url` and
printed it on the contract's page, so a database dump or a shoulder was enough
to sign somebody's contract.

Talent Booker, which ported this board's SignaDoc wire on 2026-09-30, found the
same thing in its review on 2026-10-06 and stopped keeping them (its LM-145):
Copy link now asks the portal for a fresh link at the click and hands it back
once, unstored. This brings the board level with it, and empties the column of
the links already written. The column stays, unused, so an older deploy rolled
back onto this database still reads it without error.

No downgrade: a forgotten link cannot be remembered, and nothing needs one
back. Copy link mints another.

Revision ID: a6c3e19d4b70
Revises: f1a93e60c2d4
Create Date: 2026-10-27
"""
import sqlalchemy as sa
from alembic import op

revision = "a6c3e19d4b70"
down_revision = "f1a93e60c2d4"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "signature_requests" not in inspector.get_table_names():
        return
    op.execute(sa.text(
        "UPDATE signature_requests SET signing_url = NULL WHERE signing_url IS NOT NULL"))


def downgrade():
    pass
