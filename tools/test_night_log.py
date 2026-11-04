# -*- coding: utf-8 -*-
"""One record of every nightly run, and one row when it breaks.

docs/automation_gaps.md item 1. Proves:

  1. Each step is recorded with its summary; a step that raises is recorded
     as failed and the next step still runs.
  2. The night job's own main() records every step, including the invoice
     import when no vendor is active (it used to return early).
  3. Needs attention shows one row for a failed step and one for a night that
     did not run, and none when the newest night was clean.
  4. The Nights page lists the runs and their steps.

Run: python tools/test_night_log.py
"""
import os
import pathlib
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-nights-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("STRIPE_SECRET_KEY", None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, NightRun, User  # noqa: E402
import night_log  # noqa: E402

application = create_app()
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    db.session.add(boss)
    db.session.commit()
    boss_id = boss.id

print("1. Steps")
night = night_log.Night(application)
ran = []
night.step("first", lambda: "3 things")


def boom():
    raise ValueError("vendor said no")


night.step("second", boom)
night.step("third", lambda: ran.append(1))
status = night.finish()
with application.app_context():
    run = db.session.get(NightRun, night.run_id)
    steps = run.steps
check("every step is recorded in order", [s["name"] for s in steps] == ["first", "second", "third"])
check("with its summary", steps[0]["ok"] and steps[0]["note"] == "3 things")
check("a step that raises is failed with the error", not steps[1]["ok"] and "vendor said no" in steps[1]["note"])
check("and the next step still runs", ran == [1] and steps[2]["ok"])
check("the night is partial", status == "partial" and run.finished_at is not None)

print("2. The night job")
import sync_costs  # noqa: E402
import types  # noqa: E402
for name in ("sweep_repos", "audit_repos", "project_autofill", "store_ids_service", "stripe_books",
             "bank_feed", "receipts_service", "leads_refresh", "comptroller", "curate_practices"):
    sys.modules[name] = types.SimpleNamespace(main=lambda: 0)
# The live apps steps reach the network; their own tests are test_live_apps.
sys.modules["live_night"] = types.SimpleNamespace(steps=lambda night: night.step("live apps", lambda: "stub"))
sync_costs.sync_all_providers = lambda: []
sync_costs._invoices = lambda app: "0 new, 0 updated"
code = sync_costs.main()
with application.app_context():
    latest = NightRun.query.order_by(NightRun.id.desc()).first()
    names = [s["name"] for s in latest.steps]
check("every step is recorded, the invoice import included with no vendors",
      names[:2] == ["vendor costs", "Stripe invoices"] and "curator" in names
      and "Comptroller" in names and "project dates" in names
      and len(names) == len(set(names)) >= 12
      and {"bank feed", "receipts", "month close", "leads refresh"} <= set(names), names)
check("a clean night is ok and exits 0", latest.status == "ok" and code == 0)

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(boss_id)
    s["_fresh"] = True

print("3. Needs attention")
page = c.get("/admin/attention/").get_data(as_text=True)
check("no row after a clean night", "data-night-row" not in page)
with application.app_context():
    db.session.add(NightRun(status="partial", started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc),
                            steps_json='[{"name": "bank feed", "ok": false, "note": "Mercury 401", "seconds": 1}]'))
    db.session.commit()
page = c.get("/admin/attention/").get_data(as_text=True)
check("one row naming the step that failed", page.count("data-night-row") == 1 and "bank feed failed" in page)
with application.app_context():
    old = datetime.now(timezone.utc) - timedelta(hours=40)
    for r in NightRun.query.all():
        r.started_at = r.finished_at = old
    db.session.commit()
page = c.get("/admin/attention/").get_data(as_text=True)
check("a night that did not run is a row too", "Did not run" in page)

print("4. The Nights page")
nights = c.get("/admin/attention/nights").get_data(as_text=True)
check("lists the runs and their steps", "Mercury 401" in nights and "vendor costs" in nights and "Some failed" in nights)
check("no em dash", chr(0x2014) not in nights + page)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
