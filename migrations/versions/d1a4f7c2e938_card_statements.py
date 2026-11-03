"""Card and bank statements uploaded as CSV

A BankConnection whose provider is "statement" is a card or account with no
feed (Built by Bean's Chase debit card, Michael's personal debit and credit
cards); its downloaded statements are read into the books (statements.py).
bank_connections.kind says whether it is a company's own account or an
owner's personal card, owner_name whose card it is, charges_positive whether
its export shows purchases as positive numbers. vendor_rules.applies_to keeps
a "this shop is personal" rule learned on a personal card off company cards.

Revision ID: d1a4f7c2e938
Revises: c6e2d9a4b871
Create Date: 2026-11-03
"""
import sqlalchemy as sa
from alembic import op

revision = "d1a4f7c2e938"
down_revision = "c6e2d9a4b871"
branch_labels = None
depends_on = None

ADD = {
    "bank_connections": (("kind", sa.String(12), "business"), ("owner_name", sa.String(120), None),
                         ("charges_positive", sa.Boolean(), sa.false())),
    "vendor_rules": (("applies_to", sa.String(12), "all"),),
}


def _cols(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    for table, columns in ADD.items():
        have = _cols(table)
        todo = [c for c in columns if c[0] not in have]
        if not todo:
            continue
        with op.batch_alter_table(table) as batch:
            for name, kind, default in todo:
                if default is None:
                    batch.add_column(sa.Column(name, kind, nullable=True))
                else:
                    batch.add_column(sa.Column(name, kind, nullable=False, server_default=default))


def downgrade():
    for table, columns in ADD.items():
        have = _cols(table)
        present = [c[0] for c in columns if c[0] in have]
        if present:
            with op.batch_alter_table(table) as batch:
                for name in present:
                    batch.drop_column(name)
