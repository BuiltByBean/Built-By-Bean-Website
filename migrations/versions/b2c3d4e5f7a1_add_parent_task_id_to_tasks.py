"""Add parent_task_id to tasks

Revision ID: b2c3d4e5f7a1
Revises: a1b2c3d4e5f6
Create Date: 2026-04-11 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f7a1'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = [c['name'] for c in inspector.get_columns('tasks')]

    with op.batch_alter_table('tasks', schema=None) as batch_op:
        if 'parent_task_id' not in existing:
            batch_op.add_column(sa.Column('parent_task_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key(
                'fk_tasks_parent_task_id',
                'tasks',
                ['parent_task_id'],
                ['id'],
                ondelete='CASCADE',
            )
            batch_op.create_index('ix_tasks_parent_task_id', ['parent_task_id'])


def downgrade():
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_index('ix_tasks_parent_task_id')
        batch_op.drop_constraint('fk_tasks_parent_task_id', type_='foreignkey')
        batch_op.drop_column('parent_task_id')
