"""Whose vendor account is it

A provider row holds one account's credentials, and that account may belong to
a CLIENT and sit on the client's card. Twilio is the case: the runbook says to
get onto the client's account and make a key on it, and that the account SID
names whose account is billed. The board read one such account nightly and
booked every dollar of it into this business's ledger as money it had spent.

`account_client_id` says whose it is; null is Built by Bean's own, which is
every provider that existed before this. `account_label` is what the vendor
itself calls the account, read back on a sync, because a SID answers nobody's
question about whose it is.

One batch for the column, its foreign key and its index together, which is the
shape every other migration here uses: on SQLite a batch rebuilds the table
once, and adding the column in one statement and the constraint in another
rebuilds it twice, with the second rebuild reflecting a schema the first just
changed. That is why the first version of this downgraded to nothing at all.

Revision ID: f1a93e60c2d4
Revises: e7b2c05d18af
Create Date: 2026-09-16
"""
import sqlalchemy as sa
from alembic import op

revision = "f1a93e60c2d4"
down_revision = "e7b2c05d18af"
branch_labels = None
depends_on = None

TABLE = "service_providers"
FK = "fk_service_providers_account_client_id"
INDEX = "ix_service_providers_account_client_id"


def _columns():
    inspector = sa.inspect(op.get_bind())
    if TABLE not in inspector.get_table_names():
        return None  # create_all will build it complete
    return {c["name"] for c in inspector.get_columns(TABLE)}


def upgrade():
    have = _columns()
    if have is None:
        return
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        if "account_client_id" not in have:
            batch_op.add_column(sa.Column("account_client_id", sa.Integer(), nullable=True))
            # SET NULL, not CASCADE: deleting a client must not take the
            # provider row and every cost entry hanging off it with them.
            batch_op.create_foreign_key(FK, "clients", ["account_client_id"], ["id"],
                                        ondelete="SET NULL")
            batch_op.create_index(INDEX, ["account_client_id"])
        if "account_label" not in have:
            batch_op.add_column(sa.Column("account_label", sa.String(length=200),
                                          nullable=True))


def downgrade():
    have = _columns()
    if have is None:
        return
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        if "account_label" in have:
            batch_op.drop_column("account_label")
        if "account_client_id" in have:
            # Both wrapped: SQLite does not record a constraint's name, so a
            # drop by name is a no-op there and the table rebuild is what
            # actually removes it.
            try:
                batch_op.drop_index(INDEX)
            except Exception:
                pass
            try:
                batch_op.drop_constraint(FK, type_="foreignkey")
            except Exception:
                pass
            batch_op.drop_column("account_client_id")
