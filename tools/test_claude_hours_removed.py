# -*- coding: utf-8 -*-
"""The hours Claude sessions logged come off, and can be put back.

Michael, 2026-11-05: "Delete Claude's" (rule "Claude never logs time").
Migration d9a3c6e1b704 on a scratch database. Proves:

  1. An entry the SessionEnd hook wrote (session_ref) and one the door's
     log_time wrote ("(logged from ...)") are removed, with a legacy mirror
     expense the delete would take with it; each is kept whole in
     time_entry_removals.
  2. An entry a person tracked is untouched, and so is a Claude entry that is
     already on an invoice line.
  3. Downgrade puts every row back with its id, hours, date and description,
     and its expense; upgrade again removes them again.

Run: python tools/test_claude_hours_removed.py
"""
import os
import pathlib
import subprocess
import sys
import tempfile
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-hours-")
DB = (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["DATABASE_URL"] = "sqlite:///" + DB
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, Client, Project, TimeEntry, Expense, Invoice, InvoiceLineItem  # noqa: E402

application = create_app()
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def flask_db(*args):
    r = subprocess.run([sys.executable, "-m", "flask", "--app", "app:create_app", "db", *args],
                       cwd=ROOT, env=dict(os.environ), capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-2000:], r.stderr[-2000:])
    return r


with application.app_context():
    db.create_all()
    c = Client(name="Kenali Kendrick")
    db.session.add(c)
    db.session.flush()
    p = Project(name="Talent Booker", client_id=c.id, phase="delivered")
    db.session.add(p)
    db.session.flush()

    def entry(desc, hours, ref=None):
        e = TimeEntry(project_id=p.id, client_id=c.id, hours=hours, rate_type="maintenance",
                      date=date(2026, 10, 3), description=desc, session_ref=ref)
        db.session.add(e)
        db.session.flush()
        return e

    hooked = entry("Session work", 0.5, ref="sess-1")
    doored = entry("Fixed the ticket (logged from Talent Booker)", 1.25)
    person = entry("Call with Kenali about the rollout", 1.0)
    billed = entry("Built the export (logged from Talent Booker)", 2.0)
    mirror = Expense(amount=50.0, description="billable time", category="billable_time",
                     date=date(2026, 10, 3), time_entry_id=doored.id)
    inv = Invoice(client_id=c.id, status="paid", stripe_invoice_id="in_1", total=200.0)
    db.session.add_all([mirror, inv])
    db.session.flush()
    db.session.add(InvoiceLineItem(invoice_id=inv.id, time_entry_id=billed.id, description="x",
                                   quantity=2.0, unit_amount=100.0, total=200.0, item_type="time"))
    db.session.commit()
    ids = dict(hooked=hooked.id, doored=doored.id, person=person.id, billed=billed.id, mirror=mirror.id)

check("stamped one before", flask_db("stamp", "c4f7a9d2e816").returncode == 0)

print("1. Claude's entries come off")
r = flask_db("upgrade", "d9a3c6e1b704")
check("upgrade runs", r.returncode == 0)
with application.app_context():
    db.session.expire_all()
    left = {e.id for e in TimeEntry.query.all()}
    check("the hook's and the door's entries are gone", ids["hooked"] not in left and ids["doored"] not in left, left)
    check("and the mirror expense with them", db.session.get(Expense, ids["mirror"]) is None)
    kept = db.session.execute(db.text("SELECT entry_id, expense_json FROM time_entry_removals ORDER BY entry_id")).fetchall()
    check("both kept whole, the expense with its entry",
          [k[0] for k in kept] == sorted([ids["hooked"], ids["doored"]])
          and any(k[1] for k in kept if k[0] == ids["doored"]), kept)

print("2. What a person tracked, and what is invoiced, stays")
check("the person's entry stays", ids["person"] in left)
check("the invoiced Claude entry stays", ids["billed"] in left)
check("the deploy log says what moved", "2 entries, 1.75h removed" in r.stdout + r.stderr, (r.stdout + r.stderr)[-400:])

print("3. Downgrade puts it all back")
check("downgrade runs", flask_db("downgrade", "c4f7a9d2e816").returncode == 0)
with application.app_context():
    db.session.expire_all()
    back = db.session.get(TimeEntry, ids["doored"])
    check("the door's entry is back as it was",
          back is not None and back.hours == 1.25 and back.date == date(2026, 10, 3)
          and back.description.startswith("Fixed the ticket"), back)
    check("the hook's entry keeps its session mark",
          getattr(db.session.get(TimeEntry, ids["hooked"]), "session_ref", None) == "sess-1")
    m = db.session.get(Expense, ids["mirror"])
    check("and the mirror expense is back on it", m is not None and m.time_entry_id == ids["doored"])
check("upgrade again removes them again", flask_db("upgrade", "d9a3c6e1b704").returncode == 0)
with application.app_context():
    db.session.expire_all()
    check("gone again", db.session.get(TimeEntry, ids["hooked"]) is None)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
