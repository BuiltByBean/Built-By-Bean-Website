"""Add recurring expense fields and time_entry_id to expenses

Revision ID: 3ddb192484f3
Revises:
Create Date: 2026-04-04 10:05:41.375307

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '3ddb192484f3'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Add columns only if they don't already exist (safe for both fresh and existing DBs)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = [c['name'] for c in inspector.get_columns('expenses')]

    with op.batch_alter_table('expenses', schema=None) as batch_op:
        if 'time_entry_id' not in existing:
            batch_op.add_column(sa.Column('time_entry_id', sa.Integer(), nullable=True))
            batch_op.create_unique_constraint('uq_expenses_time_entry_id', ['time_entry_id'])
            batch_op.create_foreign_key('fk_expenses_time_entry_id', 'time_entries', ['time_entry_id'], ['id'], ondelete='CASCADE')
        if 'is_recurring' not in existing:
            batch_op.add_column(sa.Column('is_recurring', sa.Boolean(), server_default='0', nullable=True))
        if 'frequency' not in existing:
            batch_op.add_column(sa.Column('frequency', sa.String(length=20), nullable=True))
        if 'recurring_end_date' not in existing:
            batch_op.add_column(sa.Column('recurring_end_date', sa.Date(), nullable=True))
        if 'next_due_date' not in existing:
            batch_op.add_column(sa.Column('next_due_date', sa.Date(), nullable=True))
        if 'parent_expense_id' not in existing:
            batch_op.add_column(sa.Column('parent_expense_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_expenses_parent_expense_id', 'expenses', ['parent_expense_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('expenses', schema=None) as batch_op:
        batch_op.drop_constraint('fk_expenses_parent_expense_id', type_='foreignkey')
        batch_op.drop_column('parent_expense_id')
        batch_op.drop_column('next_due_date')
        batch_op.drop_column('recurring_end_date')
        batch_op.drop_column('frequency')
        batch_op.drop_column('is_recurring')
        batch_op.drop_constraint('fk_expenses_time_entry_id', type_='foreignkey')
        batch_op.drop_constraint('uq_expenses_time_entry_id', type_='unique')
        batch_op.drop_column('time_entry_id')
