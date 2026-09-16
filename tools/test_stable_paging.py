# -*- coding: utf-8 -*-
"""A paginated list needs a total order, or it is a different list each press.

The expense ledger ordered by date alone. Every vendor charge for a month is
dated the last day of it, so well over twenty rows share a date, and a date
alone does not tell the database which order to return that block in. Page one
and page two then cut through it at different points. Measured on the live
board: 75 slots across four pages, 67 distinct rows, eight expenses returned on
BOTH page one and page two and eight others on neither.

What is proved:

  1. Every paginated query in the app ends its ordering on a unique column.
     This is the half that fails on the shipped code, on any database, and it
     is a source check for a reason: see below.
  2. Walking the real ledger page by page returns every row exactly once, with
     forty five rows sharing one date.
  3. The same for time entries, which tie on a date the same way.

Why the first half is a source check. SQLite hands back rows in rowid order
when nothing else decides it, so the fault does not reproduce on the database
this suite runs against - the behavioural half passes on the broken code and
proves nothing there. A check that cannot fail is worse than no check
(CLAUDE.md, the Cerebro principle), so the structural half is the one that
carries this, and the behavioural half is there to show the fix works end to
end rather than only in the SQL.

Run: python tools/test_stable_paging.py
"""
import os
import pathlib
import re
import sys
import tempfile
from datetime import date, datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-paging-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


print("EVERY PAGINATED QUERY ENDS ON SOMETHING UNIQUE:")

# The ordering that applies to a .paginate() is either on the same statement or
# on the nearest order_by above it. Both shapes are in this repo.
FILES = ["app.py", "pm/leads_routes.py", "pm/contract_routes.py",
         "pm/messages_routes.py", "pm/features_routes.py", "pm/notes_routes.py"]
found = 0
for rel in FILES:
    path = ROOT / rel
    if not path.exists():
        continue
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if ".paginate(" not in line:
            continue
        found += 1
        # The statement itself, then backwards to the nearest order_by.
        window = [line] + [lines[j] for j in range(i - 1, max(-1, i - 12), -1)]
        ordering = next((w for w in window if "order_by(" in w), None)
        where = f"{rel}:{i + 1}"
        if ordering is None:
            check(f"{where} orders its rows at all", False, line.strip()[:80])
            continue
        # The last thing inside order_by(...), which is what breaks the ties.
        inner = ordering.split("order_by(", 1)[1]
        last = re.split(r",\s*", inner.rsplit(")", 1)[0].rsplit(")", 1)[0])[-1]
        check(f"{where} breaks ties on an id", ".id" in last, last.strip()[:70])
check("and every paginated query was looked at", found >= 5, found)


print("\nFORTY FIVE EXPENSES, ALL ON ONE DAY:")
from app import create_app  # noqa: E402
from models import db, Client, Expense, Project, TimeEntry, User  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    db.session.add(boss)
    for n in range(45):
        db.session.add(Expense(category="service_cost", amount=1.0 + n,
                               date=date(2026, 8, 31),
                               description=f"Vendor charge number {n:02d}"))
    # A time entry needs a project to hang off.
    client = Client(name="Paging Test Ltd", email="paging@example.test")
    db.session.add(client)
    db.session.flush()
    project = Project(name="Paging Test", client_id=client.id,
                      created_at=datetime.now(timezone.utc))
    db.session.add(project)
    db.session.flush()
    for n in range(45):
        db.session.add(TimeEntry(date=date(2026, 8, 31), hours=1.0,
                                 project_id=project.id, client_id=client.id,
                                 description=f"Time entry number {n:02d}",
                                 created_at=datetime.now(timezone.utc)))
    db.session.commit()
    boss_id = boss.id

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(boss_id)
    s["_fresh"] = True


def walk(path, needle):
    """Every row the pages hand back, in order, over the whole list."""
    seen = []
    for page in range(1, 8):
        html = c.get(f"{path}?page={page}").data.decode("utf-8", "replace")
        hits = re.findall(needle + r" number (\d\d)", html)
        if not hits:
            break
        seen.extend(hits)
    return seen


for what, path, needle in (("expenses", "/admin/expenses", "Vendor charge"),
                           ("time entries", "/admin/time", "Time entry")):
    seen = walk(path, needle)
    dupes = sorted({x for x in seen if seen.count(x) > 1})
    missing = sorted({f"{n:02d}" for n in range(45)} - set(seen))
    check(f"{what}: every row came back", len(seen) >= 45, len(seen))
    check(f"{what}: THE POINT: none came back twice", not dupes, dupes)
    check(f"{what}: and none went missing", not missing, missing)

print("\n" + ("ALL PASS" if not FAIL else str(len(FAIL)) + " FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
