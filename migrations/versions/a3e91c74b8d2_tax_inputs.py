"""take facts instead of rates, and work the rates out

Asking somebody for their effective federal rate asks them to do the hard part
themselves and then type the answer in. It also cannot be right for long: at
$125k of wages a joint return sits just under the top of the 12% band, so
business profit straddles two brackets and the effective rate moves every time
either number changes.

So the settings hold what a person actually knows, filing status, wages,
withholding, and tax_engine works out the rest.

self_employment_rate and income_tax_rate go. They are computed now, and leaving
a stale column that still looks authoritative is how the two come to disagree.
state_tax_rate stays: it is a flat rate for Texas at zero, and modelling fifty
sets of state brackets is not this.

Revision ID: a3e91c74b8d2
Revises: f2b7d0c491e5
Create Date: 2026-08-31 17:05:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a3e91c74b8d2'
down_revision = 'f2b7d0c491e5'
branch_labels = None
depends_on = None

ADDED = [
    ("filing_status", sa.String(length=10), "'single'"),
    ("your_wages", sa.Float(), "0.0"),
    ("spouse_wages", sa.Float(), "0.0"),
    ("other_income", sa.Float(), "0.0"),
    ("federal_withheld", sa.Float(), "0.0"),
]
DROPPED = [
    ("self_employment_rate", sa.Float(), "15.3"),
    ("income_tax_rate", sa.Float(), "0.0"),
]


def _columns(conn):
    return {c["name"] for c in sa.inspect(conn).get_columns("tax_settings")}


def upgrade():
    conn = op.get_bind()
    have = _columns(conn)
    with op.batch_alter_table("tax_settings", schema=None) as batch_op:
        for name, type_, default in ADDED:
            if name not in have:
                batch_op.add_column(sa.Column(name, type_, nullable=False, server_default=default))
        for name, _type, _default in DROPPED:
            if name in have:
                batch_op.drop_column(name)


def downgrade():
    conn = op.get_bind()
    have = _columns(conn)
    with op.batch_alter_table("tax_settings", schema=None) as batch_op:
        for name, type_, default in DROPPED:
            if name not in have:
                batch_op.add_column(sa.Column(name, type_, nullable=False, server_default=default))
        for name, _type, _default in ADDED:
            if name in have:
                batch_op.drop_column(name)
