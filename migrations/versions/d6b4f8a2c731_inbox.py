"""The inbox: all of Primary, not only client mail (issue #40).

Revision ID: d6b4f8a2c731
Revises: c3e5a7b9d024

Michael, 2026-11-06: "similar to how I did the email receive and send ability
in the entertainhq admin portal I want that ability in my bbb pm as well".
The board read only mail from clients and contact-form writers. It now reads
his whole Primary inbox and his Sent mail, so a row needs what Gmail knows it
by, who else was on it, what it carried, and whether he has read it here.

`watched` is what keeps Needs attention as it was: only mail from a client, a
lead or the contact form waits on a reply there. Every row written before
this was watched by construction, so it starts true, and every one of them
counts as read, or the first look at the inbox would be a wall of old mail.
"""
from alembic import op
import sqlalchemy as sa

revision = "d6b4f8a2c731"
down_revision = "c3e5a7b9d024"
branch_labels = None
depends_on = None

COLUMNS = [
    ("gm_msgid", sa.String(32)),
    ("gm_thrid", sa.String(32)),
    ("recipients_json", sa.Text()),
    ("refs", sa.Text()),
    ("attachments_json", sa.Text()),
    ("seen_at", sa.DateTime()),
    ("archived_at", sa.DateTime()),
    ("send_key", sa.String(64)),
]


def _have():
    insp = sa.inspect(op.get_bind())
    return {c["name"] for c in insp.get_columns("messages")}, \
        {i["name"] for i in insp.get_indexes("messages")}


def upgrade():
    have, indexes = _have()
    with op.batch_alter_table("messages") as b:
        for name, kind in COLUMNS:
            if name not in have:
                b.add_column(sa.Column(name, kind, nullable=True))
        if "watched" not in have:
            b.add_column(sa.Column("watched", sa.Boolean(), nullable=False,
                                   server_default=sa.true()))
    have, indexes = _have()
    for name, cols, unique in (("ix_messages_gm_msgid", ["gm_msgid"], True),
                               ("ix_messages_gm_thrid", ["gm_thrid"], False),
                               ("ix_messages_send_key", ["send_key"], True),
                               ("ix_messages_archived_at", ["archived_at"], False)):
        if name not in indexes:
            op.create_index(name, "messages", cols, unique=unique)
    op.execute(sa.text("UPDATE messages SET seen_at = COALESCE(received_at, CURRENT_TIMESTAMP) "
                       "WHERE seen_at IS NULL"))


def downgrade():
    have, indexes = _have()
    for name in ("ix_messages_gm_msgid", "ix_messages_gm_thrid",
                 "ix_messages_send_key", "ix_messages_archived_at"):
        if name in indexes:
            op.drop_index(name, table_name="messages")
    with op.batch_alter_table("messages") as b:
        for name in [c for c, _ in COLUMNS] + ["watched"]:
            if name in have:
                b.drop_column(name)
