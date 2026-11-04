"""One support board across every business (support_service.py)

Tickets may now belong to a business rather than a client (EntertainHQ's and
Data Dungeon's customers are nobody's clients here), carry the desk's own key
for a ticket read from a business's support desk, and keep the timestamps the
health tiles are made of. `support_apps` is one row per app that feeds the
board: its quick links, and for a desk its API door.

Every create is guarded on the thing not existing, because create_all runs on
boot and wins the race for the new table. Columns on an existing table are
not something create_all adds, but they are guarded the same way so a second
run is a no-op.

Revision ID: c6d2a8f41e97
Revises: a5d17c3e92b4
Create Date: 2026-11-04
"""
import sqlalchemy as sa
from alembic import op

revision = "c6d2a8f41e97"
down_revision = "a5d17c3e92b4"
branch_labels = None
depends_on = None

NEW_TICKET_COLUMNS = (
    ("business_id", sa.Integer(), {}),
    ("origin_ref", sa.String(80), {}),
    ("origin_updated_at", sa.DateTime(), {}),
    ("waiting_on", sa.String(10), {"nullable": False, "server_default": ""}),
    ("waiting_since", sa.DateTime(), {}),
    ("first_reply_at", sa.DateTime(), {}),
    ("resolved_at", sa.DateTime(), {}),
    ("reopen_count", sa.Integer(), {"nullable": False, "server_default": "0"}),
    ("verify_requested_at", sa.DateTime(), {}),
    ("verified_at", sa.DateTime(), {}),
    ("said_solved", sa.Boolean(), {}),
)


def _inspect():
    return sa.inspect(op.get_bind())


def upgrade():
    insp = _inspect()
    tables = set(insp.get_table_names())

    if "support_apps" not in tables:
        op.create_table(
            "support_apps",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("origin", sa.String(40), nullable=False),
            sa.Column("name", sa.String(120), nullable=False, server_default=""),
            sa.Column("kind", sa.String(10), nullable=False, server_default="hub"),
            sa.Column("business_id", sa.Integer(), nullable=True),
            sa.Column("support_url", sa.String(300), nullable=True),
            sa.Column("admin_url", sa.String(300), nullable=True),
            sa.Column("site_url", sa.String(300), nullable=True),
            sa.Column("status_url", sa.String(300), nullable=True),
            sa.Column("desk_url", sa.String(300), nullable=True),
            sa.Column("desk_key", sa.Text(), nullable=True),
            sa.Column("desk_acting_for", sa.String(200), nullable=True),
            sa.Column("moved_to", sa.String(40), nullable=True),
            sa.Column("pulled_at", sa.DateTime(), nullable=True),
            sa.Column("pull_note", sa.String(300), nullable=True),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="SET NULL",
                                    name="fk_support_apps_business_id"),
            sa.UniqueConstraint("origin", name="uq_support_apps_origin"),
        )
        op.create_index("ix_support_apps_business_id", "support_apps", ["business_id"])

    have = {c["name"] for c in insp.get_columns("tickets")}
    uniques = {u["name"] for u in insp.get_unique_constraints("tickets")}
    fks = {f["name"] for f in insp.get_foreign_keys("tickets")}
    indexes = {i["name"] for i in insp.get_indexes("tickets")}
    client_nullable = next(c for c in insp.get_columns("tickets") if c["name"] == "client_id")["nullable"]

    with op.batch_alter_table("tickets") as batch:
        for name, type_, kw in NEW_TICKET_COLUMNS:
            if name not in have:
                batch.add_column(sa.Column(name, type_, nullable=kw.get("nullable", True),
                                           server_default=kw.get("server_default")))
        if not client_nullable:
            batch.alter_column("client_id", existing_type=sa.Integer(), nullable=True)
        if "fk_tickets_business_id" not in fks:
            batch.create_foreign_key("fk_tickets_business_id", "businesses",
                                     ["business_id"], ["id"], ondelete="CASCADE")
        if "uq_ticket_origin_ref" not in uniques:
            batch.create_unique_constraint("uq_ticket_origin_ref", ["origin", "origin_ref"])
    if "ix_tickets_business_id" not in indexes:
        op.create_index("ix_tickets_business_id", "tickets", ["business_id"])

    _backfill_waiting()


def _backfill_waiting():
    """Who speaks next on every open ticket, from its thread as it stands.

    The same reading as support_service.refresh_waiting, written out in SQL
    terms because a migration must not import the app's models.
    """
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, created_at FROM tickets WHERE status NOT IN ('resolved', 'dismissed')"
    )).fetchall()
    for tid, created in rows:
        last = bind.execute(sa.text(
            "SELECT is_staff_reply, created_at FROM ticket_notes WHERE ticket_id = :t "
            "ORDER BY created_at DESC, id DESC LIMIT 1"), {"t": tid}).fetchone()
        if last is None:
            who, since = "you", created
        else:
            who, since = ("them" if last[0] else "you"), last[1]
        first = bind.execute(sa.text(
            "SELECT MIN(created_at) FROM ticket_notes WHERE ticket_id = :t AND is_staff_reply = :y"),
            {"t": tid, "y": True}).scalar()
        bind.execute(sa.text(
            "UPDATE tickets SET waiting_on = :w, waiting_since = :s, first_reply_at = :f WHERE id = :t"),
            {"w": who, "s": since, "f": first, "t": tid})
    # Closed tickets: only the first reply, which the response time reads.
    bind.execute(sa.text(
        "UPDATE tickets SET first_reply_at = (SELECT MIN(n.created_at) FROM ticket_notes n "
        "WHERE n.ticket_id = tickets.id AND n.is_staff_reply = :y) "
        "WHERE status IN ('resolved', 'dismissed')"), {"y": True})


def downgrade():
    insp = _inspect()
    bind = op.get_bind()
    have = {c["name"] for c in insp.get_columns("tickets")}
    uniques = {u["name"] for u in insp.get_unique_constraints("tickets")}
    fks = {f["name"] for f in insp.get_foreign_keys("tickets")}
    indexes = {i["name"] for i in insp.get_indexes("tickets")}

    # A ticket with no client is a desk's, read again on the next pull after
    # an upgrade; it cannot survive client_id going back to NOT NULL.
    orphan_ids = [r[0] for r in bind.execute(sa.text(
        "SELECT id FROM tickets WHERE client_id IS NULL")).fetchall()]
    for tid in orphan_ids:
        bind.execute(sa.text("DELETE FROM ticket_notes WHERE ticket_id = :t"), {"t": tid})
        bind.execute(sa.text("DELETE FROM tickets WHERE id = :t"), {"t": tid})

    if "ix_tickets_business_id" in indexes:
        op.drop_index("ix_tickets_business_id", table_name="tickets")
    with op.batch_alter_table("tickets") as batch:
        if "uq_ticket_origin_ref" in uniques:
            batch.drop_constraint("uq_ticket_origin_ref", type_="unique")
        if "fk_tickets_business_id" in fks:
            batch.drop_constraint("fk_tickets_business_id", type_="foreignkey")
        for name, _type, _kw in reversed(NEW_TICKET_COLUMNS):
            if name in have:
                batch.drop_column(name)
        batch.alter_column("client_id", existing_type=sa.Integer(), nullable=False)

    if "support_apps" in set(insp.get_table_names()):
        op.drop_index("ix_support_apps_business_id", table_name="support_apps")
        op.drop_table("support_apps")
