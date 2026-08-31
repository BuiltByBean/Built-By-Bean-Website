"""a runbook per third party vendor

One table, five markdown columns, one row per vendor. Fixed columns rather
than a sections table on purpose: the identical five-part shape across every
vendor is the whole point, and columns enforce it for free.

The foreign key to service_providers is nullable and SET NULL. Railway and
Twilio have cost-sync rows to point at; Stripe has none and still needs a
playbook, and removing a cost sync must not take the runbook with it.

Every constraint is named. SQLite batch mode cannot drop an unnamed one, so an
anonymous constraint here is a downgrade that fails on the machine it is most
likely to be run on.

Revision ID: e5c8b71d3f92
Revises: b8d15fa4c703
Create Date: 2026-08-31 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e5c8b71d3f92'
down_revision = 'b8d15fa4c703'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'playbooks' in inspector.get_table_names():
        return

    op.create_table(
        'playbooks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=60), nullable=False),
        sa.Column('display_name', sa.String(length=100), nullable=False),
        sa.Column('logo_path', sa.String(length=300), nullable=True, server_default=''),
        sa.Column('vendor_url', sa.String(length=300), nullable=True, server_default=''),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('one_liner', sa.String(length=300), nullable=True, server_default=''),
        sa.Column('client_only_md', sa.Text(), nullable=True),
        sa.Column('access_grant_md', sa.Text(), nullable=True),
        sa.Column('your_steps_md', sa.Text(), nullable=True),
        sa.Column('traps_md', sa.Text(), nullable=True),
        sa.Column('verify_md', sa.Text(), nullable=True),
        sa.Column('service_provider_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id', name='pk_playbooks'),
        sa.UniqueConstraint('slug', name='uq_playbooks_slug'),
        sa.ForeignKeyConstraint(
            ['service_provider_id'], ['service_providers.id'],
            name='fk_playbooks_service_provider_id', ondelete='SET NULL',
        ),
    )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'playbooks' in inspector.get_table_names():
        op.drop_table('playbooks')
