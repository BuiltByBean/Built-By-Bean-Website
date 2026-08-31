"""remember which contract went where, and leave the rest to the portal

The signing portal owns the envelope: status, audit chain, sealed PDF. It has
no idea which client the contract was for, which project it belongs to, or
which of our documents produced it, and it should not have to. That join is
the whole reason this table exists.

status is a cache of the portal's answer, refreshed whenever the pages are
opened. It is here so a list draws before the network does, not so anything
is decided from it.

The foreign keys are SET NULL rather than CASCADE. A client removed from the
board does not un-sign a contract they signed, and losing the record of that
signature to tidy up a row would be the wrong trade.

Revision ID: b4d70e2f1a93
Revises: a3e91c74b8d2
Create Date: 2026-08-31 18:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b4d70e2f1a93'
down_revision = 'a3e91c74b8d2'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    if 'signature_requests' in sa.inspect(conn).get_table_names():
        return
    op.create_table(
        'signature_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('envelope_id', sa.String(length=64), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('kind', sa.String(length=30), nullable=False, server_default='document'),
        sa.Column('client_id', sa.Integer(), nullable=True),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('source_document_id', sa.Integer(), nullable=True),
        sa.Column('signed_document_id', sa.Integer(), nullable=True),
        sa.Column('signer_name', sa.String(length=120), nullable=False),
        sa.Column('signer_email', sa.String(length=200), nullable=False),
        sa.Column('signer_ref', sa.String(length=64), nullable=True),
        sa.Column('signing_url', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='sent'),
        sa.Column('mail_mode', sa.String(length=10), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('synced_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id', name='pk_signature_requests'),
        sa.ForeignKeyConstraint(['client_id'], ['clients.id'],
                                name='fk_signature_requests_client', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'],
                                name='fk_signature_requests_project', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['source_document_id'], ['documents.id'],
                                name='fk_signature_requests_source_doc', ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['signed_document_id'], ['documents.id'],
                                name='fk_signature_requests_signed_doc', ondelete='SET NULL'),
        # One envelope, one row. A second would be two answers to one question.
        sa.UniqueConstraint('envelope_id', name='uq_signature_requests_envelope'),
    )
    op.create_index('ix_signature_requests_envelope_id', 'signature_requests', ['envelope_id'])


def downgrade():
    conn = op.get_bind()
    if 'signature_requests' not in sa.inspect(conn).get_table_names():
        return
    op.drop_index('ix_signature_requests_envelope_id', table_name='signature_requests')
    op.drop_table('signature_requests')
