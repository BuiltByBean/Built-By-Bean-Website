"""Add timer_sessions table

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f7a1
Create Date: 2026-07-01 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c3d4e5f6a1b2'
down_revision = 'b2c3d4e5f7a1'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'timer_sessions' in inspector.get_table_names():
        return

    op.create_table(
        'timer_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('rate_type', sa.String(length=20), nullable=False, server_default='maintenance'),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('accumulated_seconds', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('is_paused', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('last_resumed_at', sa.DateTime(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_timer_sessions_user_id'),
    )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'timer_sessions' in inspector.get_table_names():
        op.drop_table('timer_sessions')
