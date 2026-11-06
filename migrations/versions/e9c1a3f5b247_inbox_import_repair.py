"""Put back what the inbox's first read of sixty days wrongly did (issue #40).

Revision ID: e9c1a3f5b247
Revises: d6b4f8a2c731

The inbox went live at 21:50 UTC on 2026-11-06 (a720a51). Its first pass
read 400 mails quietly, as history; the passes after it read the rest of the
sixty days as if each mail had just arrived. So:

  - dozens of old mails, most of them J&D's ticket notices from September,
    sat on Needs attention as waiting on a reply;
  - mail from strangers was tied to leads by domain (a cable bill to the
    Optimum lead, a recruiting mail to Marine Corps Recruiting), each logged
    as "spoke to them" and the lead moved to In conversation.

The code now treats any mail older than three days as history and matches a
lead by its exact address only. This puts the rows back, and keeps every row
it changed, whole, in `inbox_import_repairs`, so the downgrade restores them.
Client stages were checked by hand on the board: the one client in
conversation (Goldridge) got there by his own reply on Nov 3, before any of
this, so no client is touched.
"""
import json

from alembic import op
import sqlalchemy as sa

revision = "e9c1a3f5b247"
down_revision = "d6b4f8a2c731"
branch_labels = None
depends_on = None

LIVE = "2026-11-06 21:45:00"        # just before the inbox deploy, UTC
HISTORY = "2026-11-03 21:50:00"     # three days before it went live


def _bind():
    return op.get_bind()


def _record(bind, kind, row_id, before):
    bind.execute(sa.text("INSERT INTO inbox_import_repairs (kind, row_id, before_json) "
                         "VALUES (:k, :i, :b)"), {"k": kind, "i": row_id, "b": json.dumps(before, default=str)})


def upgrade():
    bind = _bind()
    if "inbox_import_repairs" not in sa.inspect(bind).get_table_names():
        op.create_table(
            "inbox_import_repairs",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("row_id", sa.Integer(), nullable=False),
            sa.Column("before_json", sa.Text(), nullable=False),
        )
    if "messages" not in sa.inspect(bind).get_table_names():
        return

    # 1. Old mail is history: off Needs attention.
    for mid, status in bind.execute(sa.text(
            "SELECT id, status FROM messages WHERE gm_msgid IS NOT NULL AND direction = 'in' "
            "AND status = 'new' AND received_at < :h"), {"h": HISTORY}).fetchall():
        _record(bind, "message_status", mid, {"status": status})
        bind.execute(sa.text("UPDATE messages SET status = 'archived' WHERE id = :i"), {"i": mid})

    # 2. A stranger's mail is the inbox's alone: watched only for a client or
    #    a lead by its exact address.
    exact = ("(SELECT 1 FROM leads l WHERE l.client_id IS NULL AND lower(l.email) = lower(m.from_email)) "
             "OR EXISTS (SELECT 1 FROM lead_people p JOIN leads l2 ON l2.id = p.lead_id "
             "WHERE l2.client_id IS NULL AND lower(p.email) = lower(m.from_email))")
    names = sa.inspect(bind).get_table_names()
    has_people = "lead_people" in names
    cond = (f"EXISTS {exact}" if has_people else
            "EXISTS (SELECT 1 FROM leads l WHERE l.client_id IS NULL AND lower(l.email) = lower(m.from_email))")
    for mid, watched in bind.execute(sa.text(
            "SELECT m.id, m.watched FROM messages m WHERE m.gm_msgid IS NOT NULL AND m.direction = 'in' "
            f"AND m.source = 'gmail' AND m.client_id IS NULL AND m.watched = :t AND NOT ({cond})"),
            {"t": True}).fetchall():
        _record(bind, "message_watched", mid, {"watched": bool(watched)})
        bind.execute(sa.text("UPDATE messages SET watched = :f WHERE id = :i"), {"f": False, "i": mid})

    if "lead_touches" not in names or "leads" not in names:
        return

    # 3. The touches the import wrote ("Wrote in: ..."), kept whole.
    cols = [c["name"] for c in sa.inspect(bind).get_columns("lead_touches")]
    rows = bind.execute(sa.text(
        f"SELECT {', '.join(cols)} FROM lead_touches WHERE created_at >= :live AND note LIKE 'Wrote in:%'"),
        {"live": LIVE}).fetchall()
    for row in rows:
        data = dict(zip(cols, row))
        _record(bind, "lead_touch", data["id"], data)
        bind.execute(sa.text("DELETE FROM lead_touches WHERE id = :i"), {"i": data["id"]})

    # 4. The leads it moved to In conversation go back: Contacted when somebody
    #    had worked them before, else Lead.
    for lid, stage, changed in bind.execute(sa.text(
            "SELECT id, stage, stage_changed_at FROM leads WHERE stage = 'in_conversation' "
            "AND stage_changed_at >= :live"), {"live": LIVE}).fetchall():
        worked = bind.execute(sa.text(
            "SELECT 1 FROM lead_touches WHERE lead_id = :i AND created_at < :live LIMIT 1"),
            {"i": lid, "live": LIVE}).first()
        _record(bind, "lead_stage", lid, {"stage": stage, "stage_changed_at": changed})
        bind.execute(sa.text("UPDATE leads SET stage = :s, stage_changed_at = NULL WHERE id = :i"),
                     {"s": "contacted" if worked else "lead", "i": lid})


def downgrade():
    bind = _bind()
    if "inbox_import_repairs" not in sa.inspect(bind).get_table_names():
        return
    for kind, row_id, before in bind.execute(sa.text(
            "SELECT kind, row_id, before_json FROM inbox_import_repairs ORDER BY id DESC")).fetchall():
        data = json.loads(before)
        if kind == "message_status":
            bind.execute(sa.text("UPDATE messages SET status = :s WHERE id = :i"), {"s": data["status"], "i": row_id})
        elif kind == "message_watched":
            bind.execute(sa.text("UPDATE messages SET watched = :w WHERE id = :i"), {"w": data["watched"], "i": row_id})
        elif kind == "lead_touch":
            keys = list(data)
            bind.execute(sa.text(f"INSERT INTO lead_touches ({', '.join(keys)}) VALUES "
                                 f"({', '.join(':' + k for k in keys)})"), data)
        elif kind == "lead_stage":
            bind.execute(sa.text("UPDATE leads SET stage = :s, stage_changed_at = :c WHERE id = :i"),
                         {"s": data["stage"], "c": data["stage_changed_at"], "i": row_id})
    op.drop_table("inbox_import_repairs")
