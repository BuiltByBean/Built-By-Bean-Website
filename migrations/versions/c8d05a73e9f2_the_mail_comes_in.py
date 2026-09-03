"""The mail comes in

A table for what clients and leads write: the contact form's submissions,
recorded before any email is attempted, and anything sent to Michael's
Gmail from a client's address, read over IMAP. Replies sent from the board
live here too, threaded to what they answer.

Revision ID: c8d05a73e9f2
Revises: b7c94f62d8e1
Create Date: 2026-09-03

"""
from alembic import op
import sqlalchemy as sa


revision = "c8d05a73e9f2"
down_revision = "b7c94f62d8e1"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if sa.inspect(bind).has_table("messages"):
        return
    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="gmail"),
        sa.Column("direction", sa.String(length=3), nullable=False, server_default="in"),
        sa.Column("from_name", sa.String(length=200), nullable=True),
        sa.Column("from_email", sa.String(length=200), nullable=False),
        sa.Column("to_email", sa.String(length=200), nullable=True),
        sa.Column("subject", sa.String(length=300), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("project_type", sa.String(length=80), nullable=True),
        sa.Column("external_id", sa.String(length=300), nullable=True),
        sa.Column("thread_id", sa.Integer(), nullable=True),
        sa.Column("in_reply_to_id", sa.Integer(), nullable=True),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=10), nullable=False, server_default="new"),
        sa.Column("received_at", sa.DateTime(), nullable=True),
        sa.Column("replied_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
        sa.ForeignKeyConstraint(["in_reply_to_id"], ["messages.id"],
                                name="fk_messages_in_reply_to_id", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"],
                                name="fk_messages_client_id", ondelete="SET NULL"),
        sa.UniqueConstraint("external_id", name="uq_messages_external_id"),
    )
    op.create_index("ix_messages_direction", "messages", ["direction"])
    op.create_index("ix_messages_from_email", "messages", ["from_email"])
    op.create_index("ix_messages_thread_id", "messages", ["thread_id"])
    op.create_index("ix_messages_client_id", "messages", ["client_id"])
    op.create_index("ix_messages_status", "messages", ["status"])
    op.create_index("ix_messages_received_at", "messages", ["received_at"])


def downgrade():
    for name in ("ix_messages_received_at", "ix_messages_status",
                 "ix_messages_client_id", "ix_messages_thread_id",
                 "ix_messages_from_email", "ix_messages_direction"):
        op.drop_index(name, table_name="messages")
    op.drop_table("messages")
