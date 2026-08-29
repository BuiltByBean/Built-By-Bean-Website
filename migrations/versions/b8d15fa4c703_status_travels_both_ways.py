"""remember which status a client's app was last told

Marking a ticket resolved here now reaches the app it came from, and marking it
resolved there reaches here. This column is what makes that safe: the drain
pushes whenever it disagrees with `status`, and a status arriving from their
side sets both at once so it is never mistaken for a change of mine and sent
straight back.

Nullable, and null means "never told them", which is true of every ticket that
existed before this. The first push after deploy brings them all into step.

Revision ID: b8d15fa4c703
Revises: a1c7e93f60d2
Create Date: 2026-08-29 16:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'b8d15fa4c703'
down_revision = 'a1c7e93f60d2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tickets", schema=None) as batch_op:
        batch_op.add_column(sa.Column("hub_status_sent", sa.String(length=20), nullable=True))
    # Everything already on the board is in step with the app it came from:
    # they were created from that app's own status minutes ago. Seeding it
    # stops the first drain pushing 140 status updates nobody asked for.
    op.execute("UPDATE tickets SET hub_status_sent = status WHERE origin <> 'local'")


def downgrade():
    with op.batch_alter_table("tickets", schema=None) as batch_op:
        batch_op.drop_column("hub_status_sent")
