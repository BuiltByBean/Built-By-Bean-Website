"""A project has a kind, a product has a stage, and Workforce folds into EntertainHQ

Michael, 2026-11-04, reading the Workspace's Projects tab: "EntertainHQ, Ideas,
Piped those are my products they wouldnt even follow the same phases", "Lets
Cook doesnt even belong on this page its a personal project", and "workforce
is not its own project its built into entertain hq".

- `projects.kind` and `projects.stage`. The kinds he named are written by NAME
  (only where nothing is set), so on any other database nothing is touched.
- The fold. Matched by name, both exactly once, or nothing happens. What is
  only work moves to EntertainHQ: tasks, playbook checklists EntertainHQ does
  not already carry, and messages linked to the project. Everything else that
  points at Workforce (time, invoices, expenses, tickets, contracts, documents,
  a tile when EntertainHQ already has one, any table this does not know) stays,
  because moving it would move a client's money onto another client. If
  nothing stays, Workforce is deleted; otherwise it is archived. Either way
  `project_folds` keeps the row whole and every id moved, and the downgrade
  puts it all back. What happened is printed in the deploy log.

Revision ID: d3b8f6a2c915
Revises: c6d2a8f41e97
Create Date: 2026-11-04
"""
import json
from datetime import date, datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "d3b8f6a2c915"
down_revision = "c6d2a8f41e97"
branch_labels = None
depends_on = None

PRODUCTS = ("entertainhq", "piped", "ideas")
PERSONAL = ("lets cook",)


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def _columns(table):
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def _fks_to_projects():
    """Every (table, column) that points at projects.id, read from the
    database itself, so a table added by another session is never missed."""
    insp = sa.inspect(op.get_bind())
    out = []
    for table in insp.get_table_names():
        if table == "projects":
            continue
        for fk in insp.get_foreign_keys(table):
            if fk.get("referred_table") == "projects" and len(fk.get("constrained_columns") or []) == 1:
                out.append((table, fk["constrained_columns"][0]))
    return sorted(set(out))


def _plain(v):
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    return v


def _fold(bind):
    rows = bind.execute(sa.text("SELECT id, name, status FROM projects")).fetchall()
    workforce = [r for r in rows if (r.name or "").lower().startswith("workforce")]
    target = [r for r in rows if (r.name or "").strip().lower() == "entertainhq"]
    if len(workforce) != 1 or len(target) != 1 or workforce[0].id == target[0].id:
        print("project fold: Workforce and EntertainHQ not both found once; nothing folded")
        return
    wid, tid = workforce[0].id, target[0].id
    moved, kept = {}, {}

    def take(table, column, ids):
        if ids:
            bind.execute(sa.text(f"UPDATE {table} SET {column} = :t WHERE id IN ({','.join(str(i) for i in ids)})"),
                         {"t": tid})
            moved[table] = moved.get(table, []) + ids

    work = {("work_tasks", "project_id"), ("project_playbooks", "project_id"), ("app_links", "project_id")}
    for table, column in _fks_to_projects():
        ids = [r[0] for r in bind.execute(sa.text(f"SELECT id FROM {table} WHERE {column} = :w"), {"w": wid})]
        if not ids:
            continue
        if (table, column) == ("work_tasks", "project_id"):
            take(table, column, ids)
        elif (table, column) == ("project_playbooks", "project_id"):
            have = {r[0] for r in bind.execute(sa.text(
                "SELECT playbook_id FROM project_playbooks WHERE project_id = :t"), {"t": tid})}
            mine = bind.execute(sa.text(
                f"SELECT id, playbook_id FROM project_playbooks WHERE id IN ({','.join(map(str, ids))})")).fetchall()
            take(table, column, [r.id for r in mine if r.playbook_id not in have])
            dup = [r.id for r in mine if r.playbook_id in have]
            if dup:
                kept[table] = len(dup)
        elif (table, column) == ("app_links", "project_id"):
            # One card per app on My Apps: EntertainHQ's own tile wins, and a
            # second tile on it would make register_app edit the wrong one.
            if bind.execute(sa.text("SELECT COUNT(*) FROM app_links WHERE project_id = :t"), {"t": tid}).scalar():
                kept[table] = len(ids)
            else:
                take(table, column, ids)
        else:
            kept[table] = len(ids)
        work.discard((table, column))

    if "team_message_links" in _tables():
        ids = [r[0] for r in bind.execute(sa.text(
            "SELECT id FROM team_message_links WHERE kind = 'project' AND record_id = :w"), {"w": wid})]
        if ids:
            bind.execute(sa.text(f"UPDATE team_message_links SET record_id = :t WHERE id IN ({','.join(map(str, ids))})"),
                         {"t": tid})
            moved["team_message_links"] = ids

    project = dict(bind.execute(sa.text("SELECT * FROM projects WHERE id = :w"), {"w": wid}).mappings().first())
    outcome = "archived" if kept else "deleted"
    if kept:
        bind.execute(sa.text("UPDATE projects SET status = 'archived' WHERE id = :w"), {"w": wid})
    else:
        bind.execute(sa.text("DELETE FROM projects WHERE id = :w"), {"w": wid})
    bind.execute(sa.text(
        "INSERT INTO project_folds (from_project_id, into_project_id, outcome, moved_json, kept_json, "
        "project_json, reason, created_at) VALUES (:f, :t, :o, :m, :k, :p, :r, :c)"),
        {"f": wid, "t": tid, "o": outcome, "m": json.dumps(moved), "k": json.dumps(kept),
         "p": json.dumps({k: _plain(v) for k, v in project.items()}),
         "r": "Michael, 2026-11-04: workforce is not its own project its built into entertain hq",
         "c": datetime.now(timezone.utc).replace(tzinfo=None)})
    print(f"project fold: Workforce ({wid}) into EntertainHQ ({tid}): {outcome}; "
          f"moved {json.dumps({k: len(v) for k, v in moved.items()})}; kept {json.dumps(kept)}")


def upgrade():
    bind = op.get_bind()
    have = _columns("projects")
    with op.batch_alter_table("projects") as batch:
        if "kind" not in have:
            batch.add_column(sa.Column("kind", sa.String(length=20), nullable=True))
        if "stage" not in have:
            batch.add_column(sa.Column("stage", sa.String(length=20), nullable=True))
    if "project_folds" not in _tables():
        op.create_table(
            "project_folds",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("from_project_id", sa.Integer(), nullable=False),
            sa.Column("into_project_id", sa.Integer(), nullable=False),
            sa.Column("outcome", sa.String(length=20), nullable=False),
            sa.Column("moved_json", sa.Text(), nullable=False),
            sa.Column("kept_json", sa.Text(), nullable=False),
            sa.Column("project_json", sa.Text(), nullable=False),
            sa.Column("reason", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_project_folds"),
        )

    for pid, name in bind.execute(sa.text("SELECT id, name FROM projects WHERE kind IS NULL")).fetchall():
        flat = (name or "").strip().lower()
        if flat in PRODUCTS:
            bind.execute(sa.text("UPDATE projects SET kind = 'product' WHERE id = :i"), {"i": pid})
        elif flat in PERSONAL:
            bind.execute(sa.text("UPDATE projects SET kind = 'personal' WHERE id = :i"), {"i": pid})

    if not bind.execute(sa.text("SELECT COUNT(*) FROM project_folds")).scalar():
        _fold(bind)


def downgrade():
    bind = op.get_bind()
    if "project_folds" in _tables():
        for fold in bind.execute(sa.text("SELECT * FROM project_folds ORDER BY id DESC")).mappings().fetchall():
            row = json.loads(fold["project_json"] or "{}")
            wid = fold["from_project_id"]
            cols = _columns("projects")
            row = {k: v for k, v in row.items() if k in cols}
            if fold["outcome"] == "deleted" and row and not bind.execute(
                    sa.text("SELECT COUNT(*) FROM projects WHERE id = :w"), {"w": wid}).scalar():
                names = ", ".join(row)
                binds = ", ".join(f":{k}" for k in row)
                bind.execute(sa.text(f"INSERT INTO projects ({names}) VALUES ({binds})"), row)
            elif row.get("status"):
                bind.execute(sa.text("UPDATE projects SET status = :s WHERE id = :w"),
                             {"s": row["status"], "w": wid})
            for table, ids in json.loads(fold["moved_json"] or "{}").items():
                if not ids or table not in _tables():
                    continue
                column = "record_id" if table == "team_message_links" else "project_id"
                bind.execute(sa.text(f"UPDATE {table} SET {column} = :w WHERE id IN ({','.join(map(str, ids))})"),
                             {"w": wid})
        op.drop_table("project_folds")
    have = _columns("projects")
    with op.batch_alter_table("projects") as batch:
        if "stage" in have:
            batch.drop_column("stage")
        if "kind" in have:
            batch.drop_column("kind")
