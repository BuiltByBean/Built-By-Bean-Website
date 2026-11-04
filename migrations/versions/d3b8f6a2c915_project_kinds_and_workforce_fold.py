"""A project has a kind, a product has a stage, and Workforce folds into EntertainHQ

Michael, 2026-11-04, reading the Workspace's Projects tab: "EntertainHQ, Ideas,
Piped those are my products they wouldnt even follow the same phases", "Lets
Cook doesnt even belong on this page its a personal project", and "workforce
is not its own project its built into entertain hq".

- `projects.kind` and `projects.stage`. The kinds he named are written by NAME
  (only where nothing is set), so on any other database nothing is touched.
- The fold. Michael: "workforce was never ever its own project it was a
  feature added to talent booker". Matched by name (Workforce..., and Talent
  Booker), both exactly once, or nothing happens. Both are Kenali Kendrick's,
  so EVERYTHING on Workforce moves to Talent Booker, money included, and no
  client's figures change: every table that points at projects, read from the
  database itself, plus messages linked to it. A playbook Talent Booker already
  carries takes Workforce's ticked steps it lacks. A My Apps tile is detached
  rather than doubled when Talent Booker has its own (one card per app). Then
  Workforce is deleted. `project_folds` keeps the row whole and every id and
  row touched, the downgrade puts all of it back, and the deploy log says what
  moved.

Revision ID: d3b8f6a2c915
Revises: d1e7b4a92c05
Create Date: 2026-11-04
"""
import json
from datetime import date, datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "d3b8f6a2c915"
down_revision = "d1e7b4a92c05"
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


def _ids(bind, sql, **kw):
    return [r[0] for r in bind.execute(sa.text(sql), kw)]


def _in(ids):
    return ",".join(str(int(i)) for i in ids)


def _fold(bind):
    rows = bind.execute(sa.text("SELECT id, name FROM projects")).fetchall()
    workforce = [r for r in rows if (r.name or "").strip().lower().startswith("workforce")]
    target = [r for r in rows if (r.name or "").strip().lower() == "talent booker"]
    if len(workforce) != 1 or len(target) != 1 or workforce[0].id == target[0].id:
        print("project fold: Workforce and Talent Booker not both found once; nothing folded")
        return
    wid, tid = workforce[0].id, target[0].id
    moved, merged, detached = {}, [], []

    for table, column in _fks_to_projects():
        ids = _ids(bind, f"SELECT id FROM {table} WHERE {column} = :w", w=wid)
        if not ids:
            continue
        if table == "project_playbooks":
            have = dict(bind.execute(sa.text(
                "SELECT playbook_id, id FROM project_playbooks WHERE project_id = :t"), {"t": tid}).fetchall())
            for pp in bind.execute(sa.text(
                    f"SELECT * FROM project_playbooks WHERE id IN ({_in(ids)})")).mappings().fetchall():
                if pp["playbook_id"] not in have:
                    bind.execute(sa.text("UPDATE project_playbooks SET project_id = :t WHERE id = :i"),
                                 {"t": tid, "i": pp["id"]})
                    moved.setdefault(table, []).append(pp["id"])
                    continue
                # Talent Booker carries this playbook already: it takes the
                # ticks it lacks, and the rest go with the copy.
                into = have[pp["playbook_id"]]
                taken = set(_ids(bind, "SELECT playbook_step_id FROM project_playbook_steps "
                                       "WHERE project_playbook_id = :i", i=into))
                steps = bind.execute(sa.text("SELECT * FROM project_playbook_steps WHERE project_playbook_id = :i"),
                                     {"i": pp["id"]}).mappings().fetchall()
                move = [st["id"] for st in steps if st["playbook_step_id"] not in taken]
                drop = [{k: _plain(v) for k, v in st.items()} for st in steps if st["playbook_step_id"] in taken]
                if move:
                    bind.execute(sa.text(f"UPDATE project_playbook_steps SET project_playbook_id = :i "
                                         f"WHERE id IN ({_in(move)})"), {"i": into})
                bind.execute(sa.text("DELETE FROM project_playbook_steps WHERE project_playbook_id = :i"),
                             {"i": pp["id"]})
                bind.execute(sa.text("DELETE FROM project_playbooks WHERE id = :i"), {"i": pp["id"]})
                merged.append({"pp": {k: _plain(v) for k, v in pp.items()}, "moved_steps": move,
                               "dropped_steps": drop})
            continue
        if table == "app_links" and bind.execute(sa.text(
                "SELECT COUNT(*) FROM app_links WHERE project_id = :t"), {"t": tid}).scalar():
            # One card per app on My Apps: Talent Booker's own tile stays the
            # card, and Workforce's is let go in the half it was shown in.
            for tile_id, group in bind.execute(sa.text(
                    f"SELECT id, board_group FROM app_links WHERE id IN ({_in(ids)})")).fetchall():
                bind.execute(sa.text("UPDATE app_links SET project_id = NULL, board_group = :g WHERE id = :i"),
                             {"g": group or "client", "i": tile_id})
                detached.append({"id": tile_id, "board_group": group})
            continue
        bind.execute(sa.text(f"UPDATE {table} SET {column} = :t WHERE id IN ({_in(ids)})"), {"t": tid})
        moved[table] = moved.get(table, []) + ids

    if "team_message_links" in _tables():
        ids = _ids(bind, "SELECT id FROM team_message_links WHERE kind = 'project' AND record_id = :w", w=wid)
        if ids:
            bind.execute(sa.text(f"UPDATE team_message_links SET record_id = :t WHERE id IN ({_in(ids)})"),
                         {"t": tid})
            moved["team_message_links"] = ids

    project = dict(bind.execute(sa.text("SELECT * FROM projects WHERE id = :w"), {"w": wid}).mappings().first())
    bind.execute(sa.text("DELETE FROM projects WHERE id = :w"), {"w": wid})
    record = dict(moved)
    record["_merged_playbooks"] = merged
    record["_detached_tiles"] = detached
    bind.execute(sa.text(
        "INSERT INTO project_folds (from_project_id, into_project_id, outcome, moved_json, kept_json, "
        "project_json, reason, created_at) VALUES (:f, :t, 'deleted', :m, '{}', :p, :r, :c)"),
        {"f": wid, "t": tid, "m": json.dumps(record),
         "p": json.dumps({k: _plain(v) for k, v in project.items()}),
         "r": "Michael, 2026-11-04: workforce was never ever its own project it was a feature added to "
              "talent booker which is entertainhq",
         "c": datetime.now(timezone.utc).replace(tzinfo=None)})
    print(f"project fold: Workforce ({wid}) into Talent Booker ({tid}): moved "
          f"{json.dumps({k: len(v) for k, v in moved.items()})}; playbooks merged {len(merged)}; "
          f"tiles let go {len(detached)}")


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


def _insert(bind, table, row):
    cols = _columns(table)
    row = {k: v for k, v in row.items() if k in cols}
    if row:
        bind.execute(sa.text(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join(':' + k for k in row)})"),
                     row)


def downgrade():
    bind = op.get_bind()
    if "project_folds" in _tables():
        for fold in bind.execute(sa.text("SELECT * FROM project_folds ORDER BY id DESC")).mappings().fetchall():
            wid = fold["from_project_id"]
            row = json.loads(fold["project_json"] or "{}")
            if row and not bind.execute(sa.text("SELECT COUNT(*) FROM projects WHERE id = :w"), {"w": wid}).scalar():
                _insert(bind, "projects", row)
            elif row.get("status"):
                bind.execute(sa.text("UPDATE projects SET status = :s WHERE id = :w"), {"s": row["status"], "w": wid})
            record = json.loads(fold["moved_json"] or "{}")
            for item in record.pop("_merged_playbooks", []):
                _insert(bind, "project_playbooks", item["pp"])
                if item["moved_steps"]:
                    bind.execute(sa.text(f"UPDATE project_playbook_steps SET project_playbook_id = :i "
                                         f"WHERE id IN ({_in(item['moved_steps'])})"), {"i": item["pp"]["id"]})
                for st in item["dropped_steps"]:
                    _insert(bind, "project_playbook_steps", st)
            for tile in record.pop("_detached_tiles", []):
                bind.execute(sa.text("UPDATE app_links SET project_id = :w, board_group = :g WHERE id = :i"),
                             {"w": wid, "g": tile["board_group"], "i": tile["id"]})
            fks = dict(_fks_to_projects())
            for table, ids in record.items():
                if not ids or table not in _tables():
                    continue
                column = "record_id" if table == "team_message_links" else fks.get(table, "project_id")
                bind.execute(sa.text(f"UPDATE {table} SET {column} = :w WHERE id IN ({_in(ids)})"), {"w": wid})
        op.drop_table("project_folds")
    have = _columns("projects")
    with op.batch_alter_table("projects") as batch:
        if "stage" in have:
            batch.drop_column("stage")
        if "kind" in have:
            batch.drop_column("kind")
