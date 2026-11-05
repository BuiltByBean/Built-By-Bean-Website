"""The migration that put the projects right on 2026-11-05 (e2b7d4f8a1c6).

Michael read the Workspace's Projects tab: three builds nobody had signed for
read Contracted (one MVP), and Kuper Plumbing read Free maintenance a month
after its window closed, with Talent Booker beside it, both "Live Nov 05".
This seeds those rows as production had them, runs the migration, checks each
one, runs it down and checks every row is back exactly, then up again.

    python tools/test_not_contracted.py
"""
import importlib.util
import os
import pathlib
import sys
import tempfile
from datetime import date, datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-not-contracted-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from sqlalchemy import inspect, text  # noqa: E402

from app import create_app  # noqa: E402
from models import db, Client, Project, SignatureRequest  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(f"  {'ok' if cond else 'FAIL'}   {name}" + ("" if cond else f"  [{detail}]"))
    if not cond:
        FAIL.append(name)


def migrate(direction):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    path = ROOT / "migrations" / "versions" / "e2b7d4f8a1c6_not_contracted.py"
    spec = importlib.util.spec_from_file_location("m_not_contracted", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with db.engine.begin() as conn:
        ctx = MigrationContext.configure(conn)
        with Operations.context(ctx):
            getattr(mod, direction)()


FIELDS = ("phase", "phase_locked", "go_live_date", "go_live_source", "build_started_on")


def state():
    db.session.expire_all()
    return {p.name: tuple(getattr(p, f) for f in FIELDS) for p in Project.query.all()}


app = create_app()
with app.app_context():
    db.create_all()
    night = "kuperplumbing.com"
    rows = {}
    for client_name, name, kw in (
        ("Cason Kuper", "Kuper Plumbing", dict(phase="free_maintenance", mvp_date=date(2026, 9, 30),
                                               go_live_date=date(2026, 11, 5), go_live_source=night)),
        ("Kenali Kendrick", "Talent Booker", dict(phase="free_maintenance", mvp_date=date(2026, 6, 1),
                                                  go_live_date=date(2026, 11, 5),
                                                  go_live_source="staff.jdentertain.com")),
        ("Louis Lucas", "Deed in Hand", dict(phase="mvp", build_started_on=date(2026, 11, 4))),
        ("Lucas Miller", "Christ Community Church", dict(phase="contracted")),
        ("Zachary Robinson", "Robinsonandco Project Manager",
         dict(phase="contracted", phase_locked=True, mvp_date=date(2027, 1, 1),
              build_started_on=date(2026, 9, 4), go_live_date=date(2026, 11, 5),
              go_live_source="admin.robinsonandcodesign.com")),
        ("Ann Typed", "Typed go-live", dict(phase="in_production", go_live_date=date(2026, 3, 1))),
        ("Sam Signed", "Christ Community Church", dict(phase="contracted")),
    ):
        client = Client(name=client_name, email=f"{client_name.split()[0].lower()}@example.test")
        db.session.add(client)
        db.session.flush()
        p = Project(client_id=client.id, name=name, status="active", **kw)
        db.session.add(p)
        db.session.flush()
        rows[(client_name, name)] = p.id
        if client_name == "Sam Signed":
            # Same name, but signed: the migration must leave it contracted.
            db.session.add(SignatureRequest(envelope_id="env-sam", title="SOW", kind="sow",
                                            client_id=client.id, project_id=p.id, signer_name="S",
                                            signer_email="s@example.test", status="completed",
                                            completed_at=datetime(2026, 10, 1, tzinfo=timezone.utc)))
    db.session.commit()
    # The model already has the column; production's table does not.
    with db.engine.begin() as conn:
        conn.execute(text("ALTER TABLE projects DROP COLUMN not_live_on"))
    db.session.expire_all()
    with db.engine.connect() as conn:
        before = {r[0]: tuple(r[1:]) for r in conn.execute(text(
            "SELECT id, phase, phase_locked, go_live_date, go_live_source, build_started_on FROM projects"))}

    print("1. up")
    migrate("upgrade")
    check("projects gained not_live_on", "not_live_on" in {c["name"] for c in inspect(db.engine).get_columns("projects")})
    get = lambda key: db.session.get(Project, rows[key])  # noqa: E731
    db.session.expire_all()
    k = get(("Cason Kuper", "Kuper Plumbing"))
    check("Kuper Plumbing is In production, live from Oct 1",
          k.phase == "in_production" and k.go_live_date == date(2026, 10, 1) and "2026-10-01" in k.go_live_source,
          (k.phase, k.go_live_date, k.go_live_source))
    tb = get(("Kenali Kendrick", "Talent Booker"))
    check("Talent Booker is In production, the night's go-live gone",
          tb.phase == "in_production" and tb.go_live_date is None and tb.go_live_source is None,
          (tb.phase, tb.go_live_date))
    for key in (("Louis Lucas", "Deed in Hand"), ("Lucas Miller", "Christ Community Church"),
                ("Zachary Robinson", "Robinsonandco Project Manager")):
        p = get(key)
        check(f"{key[1]} is Not contracted, unheld, with no build or go-live",
              p.phase == "not_contracted" and not p.phase_locked and p.build_started_on is None
              and p.go_live_date is None and p.go_live_source is None,
              tuple(getattr(p, f) for f in FIELDS))
    check("a go-live somebody typed is left", get(("Ann Typed", "Typed go-live")).go_live_date == date(2026, 3, 1))
    check("a signed project of the same name stays contracted",
          get(("Sam Signed", "Christ Community Church")).phase == "contracted")
    with db.engine.connect() as conn:
        kept = conn.execute(text("SELECT count(*) FROM project_phase_corrections")).scalar()
    check("every changed row is kept for the way back", kept == 5, kept)

    print("2. down puts every row back")
    migrate("downgrade")
    with db.engine.connect() as conn:
        after = {r[0]: tuple(r[1:]) for r in conn.execute(text(
            "SELECT id, phase, phase_locked, go_live_date, go_live_source, build_started_on FROM projects"))}
    check("every row exactly as it was", after == before,
          {i: (before[i], after.get(i)) for i in before if before[i] != after.get(i)})
    check("the record table is gone", "project_phase_corrections" not in inspect(db.engine).get_table_names())
    check("the column is gone", "not_live_on" not in {c["name"] for c in inspect(db.engine).get_columns("projects")})

    print("3. up again")
    migrate("upgrade")
    db.session.expire_all()
    check("and right again", get(("Cason Kuper", "Kuper Plumbing")).phase == "in_production"
          and get(("Louis Lucas", "Deed in Hand")).phase == "not_contracted")

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
