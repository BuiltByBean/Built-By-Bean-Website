# -*- coding: utf-8 -*-
"""The repair of the inbox's first sixty days (migration e9c1a3f5b247).

Builds a board shaped like production after the bad import (old mail waiting
on Needs attention, strangers' mail watched, "Wrote in" touches and a lead
moved to In conversation by them), runs the migration up, checks each is put
back and nothing else moved, then down, and checks each is restored.

Run: python tools/test_inbox_repair.py
"""
import os
import pathlib
import subprocess
import sys
import tempfile
from datetime import date, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-inbox-repair-")
DB = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["DATABASE_URL"] = DB
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["MAIL_SYNC_DISABLED"] = "1"
for flag in ("STRIPE_IMPORT_DISABLED", "HUB_PULL_DISABLED", "HUB_PUSH_DISABLED"):
    os.environ[flag] = "1"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, Message, Lead, LeadTouch  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def flask(*args):
    env = dict(os.environ, FLASK_APP="app:create_app")
    r = subprocess.run([sys.executable, "-m", "flask", "db", *args], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-800:], r.stderr[-1500:])
    return r.returncode == 0


app = create_app()
with app.app_context():
    db.create_all()
LIVE = datetime(2026, 11, 6, 21, 55)
with app.app_context():
    optimum = Lead(name="Optimum", dedupe_key="optimum|1", website="https://optimum.example", stage="in_conversation",
                   stage_changed_at=LIVE)
    worked = Lead(name="Worked Before", dedupe_key="worked|1", website="https://worked.example",
                  stage="in_conversation", stage_changed_at=LIVE)
    steady = Lead(name="Steady", dedupe_key="steady|1", email="owner@steady.example", stage="in_conversation",
                  stage_changed_at=datetime(2026, 10, 1))
    db.session.add_all([optimum, worked, steady])
    db.session.flush()
    db.session.add_all([
        LeadTouch(lead_id=optimum.id, channel="email", outcome="spoke", occurred_on=date(2026, 10, 14),
                  note="Wrote in: Your bill is now available", created_at=LIVE),
        LeadTouch(lead_id=worked.id, channel="phone", outcome="no_answer", occurred_on=date(2026, 9, 1),
                  note="Called, no answer", created_at=datetime(2026, 9, 1)),
        LeadTouch(lead_id=worked.id, channel="email", outcome="spoke", occurred_on=date(2026, 10, 19),
                  note="Wrote in: MARINES OFFICER SELECTION", created_at=LIVE),
    ])
    rows = [
        Message(source="gmail", direction="in", from_email="notify@jdentertain.example", subject="New Bug Report",
                gm_msgid="1", status="new", watched=True, client_id=None, received_at=datetime(2026, 9, 28)),
        Message(source="gmail", direction="in", from_email="bills@optimum.example", subject="Your bill",
                gm_msgid="2", status="new", watched=True, received_at=datetime(2026, 11, 6, 15)),
        Message(source="gmail", direction="in", from_email="owner@steady.example", subject="Question",
                gm_msgid="3", status="new", watched=True, received_at=datetime(2026, 11, 6, 15)),
        Message(source="contact_form", direction="in", from_email="dana@farm.example", subject="Website",
                status="new", watched=True, received_at=datetime(2026, 9, 1)),
    ]
    db.session.add_all(rows)
    db.session.commit()
    ids = {m.subject: m.id for m in rows}
    lead_ids = {"optimum": optimum.id, "worked": worked.id, "steady": steady.id}

check("stamped at the inbox", flask("stamp", "d6b4f8a2c731"))
check("the repair runs", flask("upgrade", "e9c1a3f5b247"))
with app.app_context():
    g = lambda s: db.session.get(Message, ids[s])  # noqa: E731
    check("old mail leaves Needs attention", g("New Bug Report").status == "archived")
    check("this week's mail stays", g("Your bill").status == "new" and g("Question").status == "new")
    check("a stranger's mail is no longer watched", g("Your bill").watched is False)
    check("a lead's exact address stays watched", g("Question").watched is True)
    check("the contact form is never touched", g("Website").status == "new" and g("Website").watched is True)
    notes = [t.note for t in LeadTouch.query.order_by(LeadTouch.id).all()]
    check("the import's touches go, a person's stays", notes == ["Called, no answer"], notes)
    st = {k: db.session.get(Lead, v).stage for k, v in lead_ids.items()}
    check("a lead nobody worked goes back to Lead", st["optimum"] == "lead", st)
    check("a lead worked before goes back to Contacted", st["worked"] == "contacted", st)
    check("a lead moved before the inbox is left alone", st["steady"] == "in_conversation", st)

check("and comes back down", flask("downgrade", "d6b4f8a2c731"))
with app.app_context():
    db.session.expire_all()
    g = lambda s: db.session.get(Message, ids[s])  # noqa: E731
    check("statuses restored", g("New Bug Report").status == "new")
    check("watched restored", g("Your bill").watched is True)
    check("touches restored", LeadTouch.query.count() == 3)
    check("stages restored", db.session.get(Lead, lead_ids["optimum"]).stage == "in_conversation"
          and db.session.get(Lead, lead_ids["worked"]).stage == "in_conversation")

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All passed.")
os._exit(1 if FAIL else 0)
