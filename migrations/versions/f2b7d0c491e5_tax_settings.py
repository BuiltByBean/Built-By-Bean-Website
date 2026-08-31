"""somewhere to keep the tax rates, because they are not ours to guess

One row. The rates on it drive the estimate and nothing else reads them, so
they can be wrong without breaking anything, which is the right shape for
numbers that depend on an entity type and a state this app has no business
inferring.

Defaults are deliberately conservative and deliberately editable: 30% set
aside is the commonly repeated rule of thumb for US self employment, 15.3% is
the statutory SE rate, and income tax starts at zero rather than at a guess.

Revision ID: f2b7d0c491e5
Revises: d1a6c8f34b72
Create Date: 2026-08-31 15:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f2b7d0c491e5'
down_revision = 'd1a6c8f34b72'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    if 'tax_settings' in sa.inspect(conn).get_table_names():
        return
    op.create_table(
        'tax_settings',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('set_aside_rate', sa.Float(), nullable=False, server_default='30.0'),
        sa.Column('self_employment_rate', sa.Float(), nullable=False, server_default='15.3'),
        sa.Column('income_tax_rate', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('state_tax_rate', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id', name='pk_tax_settings'),
    )


def downgrade():
    conn = op.get_bind()
    if 'tax_settings' in sa.inspect(conn).get_table_names():
        op.drop_table('tax_settings')
