"""a record of who has been called, and what happened

Stage was a free string with a default of "lead", written in exactly one place
in the whole application - set to "contracted" when a contract came back
signed. There was no way to choose one, no list of what they could be, and no
way to filter by it, so in practice a client was a lead until they signed and
nothing in between was recorded anywhere.

That is survivable while the pipeline is two people you already know. It stops
being survivable the moment somebody is working down a list of businesses in
town, because the only thing preventing a second cold call to a business that
already said no is a written record that they did.

So: a stage set with the two closed states that matter, and a row per attempt
to reach somebody. A row rather than a flag per channel, because "phoned: yes"
answers the question for a fortnight and "phoned, 14 August, left a voicemail"
answers it in November.

The one client sitting at the legacy stage "client" becomes "active_client",
which is the same thing in the new vocabulary. Every other existing value -
lead, contracted - is already valid and is left alone.

Revision ID: b3f7d29e6c40
Revises: a7c4e0d51f83
Create Date: 2026-09-01 21:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b3f7d29e6c40'
down_revision = 'a7c4e0d51f83'
branch_labels = None
depends_on = None


# Old value -> new. Anything not named here was already a valid stage.
STAGE_RENAMES = {"client": "active_client"}


def upgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = set(insp.get_table_names())

    if "client_contacts" not in tables:
        op.create_table(
            "client_contacts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("client_id", sa.Integer(), nullable=False),
            sa.Column("channel", sa.String(length=20), nullable=False,
                      server_default="phone"),
            sa.Column("occurred_on", sa.Date(), nullable=False),
            sa.Column("note", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["client_id"], ["clients.id"],
                                    ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_client_contacts_client_id", "client_contacts",
                        ["client_id"])

    if "clients" in tables:
        for old, new in STAGE_RENAMES.items():
            conn.execute(
                sa.text("UPDATE clients SET stage = :new WHERE stage = :old"),
                {"new": new, "old": old},
            )
        # A client with no stage at all would not match any filter, including
        # the one for leads, and would be invisible on a filtered board.
        conn.execute(
            sa.text("UPDATE clients SET stage = 'lead' "
                    "WHERE stage IS NULL OR stage = ''")
        )


def downgrade():
    conn = op.get_bind()
    insp = sa.inspect(conn)
    tables = set(insp.get_table_names())

    if "clients" in tables:
        for old, new in STAGE_RENAMES.items():
            conn.execute(
                sa.text("UPDATE clients SET stage = :old WHERE stage = :new"),
                {"new": new, "old": old},
            )

    if "client_contacts" in tables:
        # Dropped explicitly before the table: SQLite carries indexes with the
        # table, but Postgres does not complain about the belt either.
        try:
            op.drop_index("ix_client_contacts_client_id",
                          table_name="client_contacts")
        except Exception:
            pass
        op.drop_table("client_contacts")
