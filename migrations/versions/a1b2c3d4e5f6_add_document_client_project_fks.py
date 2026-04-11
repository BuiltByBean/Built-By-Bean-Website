"""Add client_id and project_id to documents, make task_id nullable

Revision ID: a1b2c3d4e5f6
Revises: 3ddb192484f3
Create Date: 2026-04-04 11:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = '3ddb192484f3'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = [c['name'] for c in inspector.get_columns('documents')]

    with op.batch_alter_table('documents', schema=None) as batch_op:
        if 'client_id' not in existing:
            batch_op.add_column(sa.Column('client_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_documents_client_id', 'clients', ['client_id'], ['id'], ondelete='CASCADE')
        if 'project_id' not in existing:
            batch_op.add_column(sa.Column('project_id', sa.Integer(), nullable=True))
            batch_op.create_foreign_key('fk_documents_project_id', 'projects', ['project_id'], ['id'], ondelete='CASCADE')
        # Make task_id nullable
        batch_op.alter_column('task_id', existing_type=sa.Integer(), nullable=True)


def downgrade():
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.alter_column('task_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_constraint('fk_documents_project_id', type_='foreignkey')
        batch_op.drop_column('project_id')
        batch_op.drop_constraint('fk_documents_client_id', type_='foreignkey')
        batch_op.drop_column('client_id')
