# -*- coding: utf-8 -*-
"""The door and Needs attention agree about which vendor bills are missing.

docs/automation_gaps.md fault 8. The door's get_costs reported Railway
(EntertainHQ)'s October as not recorded while Needs attention correctly gave it
grace: that account's month runs 16th to 16th, so the October bill does not
exist until November 16. Both now read provider_bills.bill_months. Proves:

  1. A Railway account that pulls its bills: the month just finished is not
     missing on either side; the door names it as not billed yet; an older
     gap is missing on both.
  2. A Railway account typed by hand: last month is missing on both.
  3. The two answers are the same list, month for month.

Dates are relative to today, so this holds in any month.

Run: python tools/test_bills_months.py
"""
import json
import os
import pathlib
import sys
import tempfile
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-bills-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["GUIDANCE_API_KEY"] = "door-key"
os.environ.pop("STRIPE_SECRET_KEY", None)
for flag in ("STRIPE_IMPORT_DISABLED", "HUB_PULL_DISABLED", "HUB_PUSH_DISABLED", "MAIL_SYNC_DISABLED"):
    os.environ[flag] = "1"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, ProviderInvoice, ServiceCostEntry, ServiceProvider  # noqa: E402
import provider_bills  # noqa: E402
from pm import attention_routes  # noqa: E402

application = create_app()
application.config["GUIDANCE_API_KEY"] = "door-key"
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def back(months):
    m = date.today().replace(day=1)
    for _ in range(months):
        m = (m - timedelta(days=1)).replace(day=1)
    return m


LAST, TWO, THREE, FOUR = back(1), back(2), back(3), back(4)

with application.app_context():
    db.create_all()
    pulled = ServiceProvider(name="railway", display_name="Railway (EntertainHQ)",
                             credentials_json=json.dumps({"workspace_id": "ws_ehq"}))
    typed = ServiceProvider(name="railway", display_name="Railway",
                            credentials_json=json.dumps({"token": "x"}))
    db.session.add_all([pulled, typed])
    db.session.flush()
    for p in (pulled, typed):
        db.session.add(ServiceCostEntry(provider_id=p.id, resource_identifier="proj",
                                        period_start=FOUR, period_end=FOUR + timedelta(days=27),
                                        raw_amount=10.0, allocated_amount=10.0))
    # The pulled account has every bill but THREE (an old gap: the pull broke)
    # and LAST (its billing month has not closed yet).
    for m in (FOUR, TWO):
        db.session.add(ProviderInvoice(provider_id=pulled.id, period_month=m, amount=40.0,
                                       note="From Railway: 1 invoice"))
    # The typed account has every bill but LAST.
    for m in (FOUR, THREE, TWO):
        db.session.add(ProviderInvoice(provider_id=typed.id, period_month=m, amount=20.0))
    db.session.commit()
    pulled_id, typed_id = pulled.id, typed.id

print("1. The shared reading")
with application.app_context():
    missing, waiting = provider_bills.bill_months(db.session.get(ServiceProvider, pulled_id))
    check("pulled: the month just finished is not missing", LAST not in missing, missing)
    check("pulled: it is named as not billed yet", waiting == [LAST], waiting)
    check("pulled: an older gap is missing", missing == [THREE], missing)
    missing, waiting = provider_bills.bill_months(db.session.get(ServiceProvider, typed_id))
    check("typed: last month is missing, with no grace", missing == [LAST] and waiting == [], (missing, waiting))

print("2. Needs attention and the door give the same answer")
with application.app_context():
    rows = {r["provider"].id: [m for m in r["missing"]]
            for r in attention_routes._bills_to_enter(force=True)}
with application.test_client() as http:
    resp = http.get("/api/guidance/costs", headers={"Authorization": "Bearer door-key"})
    body = resp.get_json() or {}
items = body.get("providers") or body.get("costs") or (body if isinstance(body, list) else [])
door = {i["display_name"]: i for i in items}
check("the door answers", resp.status_code == 200 and door, (resp.status_code, str(body)[:200]))
ehq = door.get("Railway (EntertainHQ)", {})
own = door.get("Railway", {})
fmt = lambda months: [m.strftime("%Y-%m") for m in months]  # noqa: E731
check("THE FAULT: the door no longer calls EntertainHQ's last month not recorded",
      LAST.strftime("%Y-%m") not in ehq.get("months_not_recorded", []), ehq.get("months_not_recorded"))
check("the door says it is not billed yet",
      ehq.get("months_not_billed_yet") == [LAST.strftime("%Y-%m")], ehq.get("months_not_billed_yet"))
check("pulled account: both sides list the same months",
      ehq.get("months_not_recorded") == fmt(rows.get(pulled_id, [])), (ehq.get("months_not_recorded"), rows))
check("typed account: both sides list the same months",
      own.get("months_not_recorded") == fmt(rows.get(typed_id, [])) == [LAST.strftime("%Y-%m")],
      (own.get("months_not_recorded"), rows))

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "All passed.")
sys.exit(1 if FAIL else 0)
