"""Not contracted is a phase, and the dates the night guessed come off

Michael, 2026-11-05, on the Workspace's Projects tab: Robinson & Co., Deed in
Hand and Christ Community Church read Contracted (Deed in Hand MVP) with
nothing signed, and Kuper Plumbing read Free maintenance a month after its
window closed. "The automated processes that are supposed to be moving these
things, are not working."

Two faults. Every project started at Contracted, and the night took the day a
project was put on the board as its contract date, so Deed in Hand's first
commit moved it to MVP. And the night filled go-live with the first night it
saw a real domain answer, so Kuper Plumbing, Talent Booker and Robinson & Co.,
all answering long before the step existed, got Nov 5 and a fresh window.

This adds `projects.not_live_on` (the code half is project_autofill), clears
every go-live the night wrote from 2026-11-04 on, puts the three unsigned
projects at Not contracted (only while nothing signed says otherwise), gives
Kuper Plumbing the go-live its own notes give ("live with real customers about
2026-10-01") and puts Kuper Plumbing and Talent Booker In production. Every
row it changes is kept whole in project_phase_corrections, and downgrade puts
each one back.

Revision ID: e2b7d4f8a1c6
Revises: d9a3c6e1b704
Create Date: 2026-11-05
"""
import json
from datetime import date, datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "e2b7d4f8a1c6"
down_revision = "d9a3c6e1b704"
branch_labels = None
depends_on = None

NIGHT_STARTED = date(2026, 11, 4)
NOT_SIGNED = ("Robinsonandco Project Manager", "Deed in Hand", "Christ Community Church")
FIELDS = ("phase", "phase_locked", "go_live_date", "go_live_source", "build_started_on")
DATES = ("go_live_date", "build_started_on")


def _as_date(value):
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def _signed(bind, project_id, client_id):
    return bind.execute(sa.text(
        "SELECT 1 FROM signature_requests WHERE completed_at IS NOT NULL AND ("
        " project_id = :p OR (project_id IS NULL AND client_id = :c"
        " AND kind IN ('sow', 'engagement_letter')))"),
        {"p": project_id, "c": client_id}).first() is not None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "not_live_on" not in {c["name"] for c in insp.get_columns("projects")}:
        op.add_column("projects", sa.Column("not_live_on", sa.Date(), nullable=True))
    if "project_phase_corrections" not in insp.get_table_names():
        op.create_table(
            "project_phase_corrections",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("project_id", sa.Integer(), nullable=False),
            sa.Column("before_json", sa.Text(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_project_phase_corrections"),
        )

    rows = bind.execute(sa.text(
        "SELECT id, name, client_id, phase, phase_locked, go_live_date, go_live_source,"
        " build_started_on FROM projects")).mappings().all()
    for r in rows:
        after, why = {}, []
        live_on = _as_date(r["go_live_date"])
        if r["go_live_source"] and live_on and live_on >= NIGHT_STARTED:
            after.update(go_live_date=None, go_live_source=None)
            why.append("go-live was the night it was first looked at, not the day it went live")
        if r["name"] in NOT_SIGNED and r["phase"] != "not_contracted" \
                and not _signed(bind, r["id"], r["client_id"]):
            after.update(phase="not_contracted", phase_locked=False, build_started_on=None,
                         go_live_date=None, go_live_source=None)
            why.append("nothing is signed")
        if r["name"] == "Kuper Plumbing":
            after.update(go_live_date=date(2026, 10, 1), phase="in_production",
                         go_live_source="its notes: live with real customers about 2026-10-01")
            why.append("live since about Oct 1, its free window ended Oct 31")
        if r["name"] == "Talent Booker" and r["phase"] != "in_production":
            after.update(phase="in_production")
            why.append("delivered Jun 1 and hosting billed since April, its free window long over")
        changed = {k: v for k, v in after.items() if v != (_as_date(r[k]) if k in DATES else r[k])}
        if not changed:
            continue
        before = {k: (r[k].isoformat() if k in DATES and r[k] is not None and hasattr(r[k], "isoformat") else r[k])
                  for k in FIELDS}
        bind.execute(sa.text(
            "INSERT INTO project_phase_corrections (project_id, before_json, reason, created_at)"
            " VALUES (:p, :b, :r, :t)"),
            {"p": r["id"], "b": json.dumps(before, default=str), "r": "; ".join(why),
             "t": datetime.now(timezone.utc).replace(tzinfo=None)})
        sets = ", ".join(f"{k} = :{k}" for k in changed)
        bind.execute(sa.text(f"UPDATE projects SET {sets} WHERE id = :id"), {**changed, "id": r["id"]})
        print(f"project {r['id']} {r['name']}: {', '.join(f'{k} {v}' for k, v in changed.items())}")


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "project_phase_corrections" in insp.get_table_names():
        saved = bind.execute(sa.text(
            "SELECT project_id, before_json FROM project_phase_corrections ORDER BY id DESC")).all()
        for project_id, before_json in saved:
            before = json.loads(before_json)
            values = {k: (_as_date(before.get(k)) if k in DATES else before.get(k)) for k in FIELDS}
            values["phase_locked"] = bool(values["phase_locked"])
            sets = ", ".join(f"{k} = :{k}" for k in FIELDS)
            bind.execute(sa.text(f"UPDATE projects SET {sets} WHERE id = :id"), {**values, "id": project_id})
        op.drop_table("project_phase_corrections")
    # The old code has no phase before Contracted.
    bind.execute(sa.text("UPDATE projects SET phase = 'contracted' WHERE phase = 'not_contracted'"))
    if "not_live_on" in {c["name"] for c in insp.get_columns("projects")}:
        with op.batch_alter_table("projects") as batch:
            batch.drop_column("not_live_on")
