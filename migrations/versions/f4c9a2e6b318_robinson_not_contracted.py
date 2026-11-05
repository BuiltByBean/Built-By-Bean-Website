"""Robinson & Co. is not contracted, whatever is on file

e2b7d4f8a1c6 moved an unsigned project to Not contracted only when no signed
row stood against it, and Robinson & Co. kept reading "Contracted held" on the
live board afterwards: something completed is on file for it (its build
tested the board's links, and the hub with it, before any contract). Michael
said it in as many words on 2026-11-05: "the Robinson & Co. project is not
contracted". His word is the record here.

Kept in project_phase_corrections like the rest, and put back by downgrade.

Revision ID: f4c9a2e6b318
Revises: e2b7d4f8a1c6
Create Date: 2026-11-05
"""
import json
from datetime import date, datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "f4c9a2e6b318"
down_revision = "e2b7d4f8a1c6"
branch_labels = None
depends_on = None

NAME = "Robinsonandco Project Manager"
REASON = "Michael, 2026-11-05: not contracted, whatever is on file"
FIELDS = ("phase", "phase_locked", "go_live_date", "go_live_source", "build_started_on")
DATES = ("go_live_date", "build_started_on")


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def upgrade():
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, phase, phase_locked, go_live_date, go_live_source, build_started_on"
        " FROM projects WHERE name = :n AND phase <> 'not_contracted'"), {"n": NAME}).mappings().all()
    for r in rows:
        before = {k: _iso(r[k]) for k in FIELDS}
        bind.execute(sa.text(
            "INSERT INTO project_phase_corrections (project_id, before_json, reason, created_at)"
            " VALUES (:p, :b, :r, :t)"),
            {"p": r["id"], "b": json.dumps(before, default=str), "r": REASON,
             "t": datetime.now(timezone.utc).replace(tzinfo=None)})
        bind.execute(sa.text(
            "UPDATE projects SET phase = 'not_contracted', phase_locked = :f, build_started_on = NULL,"
            " go_live_date = NULL, go_live_source = NULL WHERE id = :id"), {"f": False, "id": r["id"]})
        print(f"project {r['id']} {NAME}: not contracted")


def downgrade():
    bind = op.get_bind()
    saved = bind.execute(sa.text(
        "SELECT id, project_id, before_json FROM project_phase_corrections WHERE reason = :r"),
        {"r": REASON}).all()
    for row_id, project_id, before_json in saved:
        before = json.loads(before_json)
        values = {k: (date.fromisoformat(before[k][:10]) if k in DATES and before.get(k) else before.get(k))
                  for k in FIELDS}
        values["phase_locked"] = bool(values["phase_locked"])
        sets = ", ".join(f"{k} = :{k}" for k in FIELDS)
        bind.execute(sa.text(f"UPDATE projects SET {sets} WHERE id = :id"), {**values, "id": project_id})
        bind.execute(sa.text("DELETE FROM project_phase_corrections WHERE id = :id"), {"id": row_id})
