"""A contract's values wait for its signature; a session's time is keyed

signature_requests gains what the document proposes (effects_json), what to
put back if it is declined or voided (undo_json), and when the proposal was
applied (effects_applied_at). time_entries gains session_ref, the Claude
Code session a logged block of time came from, unique so the SessionEnd hook
re-running corrects its entry rather than adding a second one, and
spans_json, the stretches of that session that were work.

Every add is guarded on the column not existing, because create_all runs on
boot and a fresh database already has them.

Revision ID: c6d2a8e41f97
Revises: b4e9c2a7d153
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "c6d2a8e41f97"
down_revision = "b4e9c2a7d153"
branch_labels = None
depends_on = None


def _columns(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _indexes(table):
    return {i["name"] for i in sa.inspect(op.get_bind()).get_indexes(table)}


def upgrade():
    have = _columns("signature_requests")
    with op.batch_alter_table("signature_requests") as batch:
        if "effects_json" not in have:
            batch.add_column(sa.Column("effects_json", sa.Text(), nullable=True))
        if "undo_json" not in have:
            batch.add_column(sa.Column("undo_json", sa.Text(), nullable=True))
        if "effects_applied_at" not in have:
            batch.add_column(sa.Column("effects_applied_at", sa.DateTime(), nullable=True))

    have = _columns("time_entries")
    with op.batch_alter_table("time_entries") as batch:
        if "session_ref" not in have:
            batch.add_column(sa.Column("session_ref", sa.String(80), nullable=True))
        if "spans_json" not in have:
            batch.add_column(sa.Column("spans_json", sa.Text(), nullable=True))
    if "ix_time_entries_session_ref" not in _indexes("time_entries"):
        op.create_index("ix_time_entries_session_ref", "time_entries",
                        ["session_ref"], unique=True)


def downgrade():
    if "ix_time_entries_session_ref" in _indexes("time_entries"):
        op.drop_index("ix_time_entries_session_ref", table_name="time_entries")
    have = _columns("time_entries")
    with op.batch_alter_table("time_entries") as batch:
        for name in ("spans_json", "session_ref"):
            if name in have:
                batch.drop_column(name)

    have = _columns("signature_requests")
    with op.batch_alter_table("signature_requests") as batch:
        for name in ("effects_applied_at", "undo_json", "effects_json"):
            if name in have:
                batch.drop_column(name)
