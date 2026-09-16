# -*- coding: utf-8 -*-
"""A vendor account can be the client's, and then its costs are not mine.

Michael's own Twilio runbook sets the model out: "Get onto the CLIENT'S Twilio
account, then create your own API key on it", and "TWILIO_ACCOUNT_SID names
whose account is billed, not a credential". The board had nowhere to record
that, so every cost entry wrote an Expense and a client's own texting spend
landed in Michael's ledger, his Total out, his profit and his tax figures as
money he had paid. He had paid none of it.

What is proved:

  1. An account of ours books an expense, exactly as before.
  2. THE POINT: an account that belongs to a CLIENT books no expense at all,
     while still recording what it cost and who it was for. The cost survives,
     the claim on his wallet does not.
  3. Saying so AFTER the charges are already in the ledger takes them out, on
     the press, rather than leaving them there until the nightly sync.
  4. And saying it back again puts them back, so the switch is not a one way
     door.
  5. The ledger and its Total out drop by exactly what was taken off it.

Run: python tools/test_whose_account.py
"""
import json
import os
import pathlib
import sys
import tempfile
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-whose-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import service_costs_service as costs  # noqa: E402
from app import create_app  # noqa: E402
from models import (db, Client, Expense, ServiceCostEntry,  # noqa: E402
                    ServiceProvider, User)

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


TODAY = date(2026, 9, 16)


class Answer:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def twilio_answers(url, **kw):
    """Usage records, and the account identity lookup beside them."""
    if "/Usage/" in url:
        return Answer({"usage_records": [{
            "category": "sms-outbound", "description": "Standard Outbound SMS",
            "price": "59.67", "start_date": "2026-09-01",
            "end_date": TODAY.isoformat()}]})
    return Answer({"friendly_name": "Talent Booker - Kenali", "status": "active"})


costs.date = type("D", (), {"today": staticmethod(lambda: TODAY),
                            "fromisoformat": staticmethod(date.fromisoformat)})
costs.requests = type("R", (), {"get": staticmethod(
    lambda url, *a, **kw: twilio_answers(url, **kw))})


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    kenali = Client(name="Kenali Kendrick", email="k@example.test")
    db.session.add_all([boss, kenali])
    db.session.flush()
    mine = ServiceProvider(
        name="twilio", display_name="Twilio", is_active=True,
        credentials_json=json.dumps({"account_sid": "AC0", "auth_token": "t"}))
    db.session.add(mine)
    db.session.commit()
    provider_id, kenali_id, boss_id = mine.id, kenali.id, boss.id

    print("AN ACCOUNT OF MINE:")
    costs._sync_twilio(mine)
    check("records the cost", ServiceCostEntry.query.count() == 1)
    check("and books it as an expense", Expense.query.count() == 1,
          Expense.query.count())
    check("which is unallocated, because nobody said whose it was",
          "[unallocated]" in (ServiceCostEntry.query.first().description or ""))
    check("and the board learned what the vendor calls the account",
          mine.account_label == "Talent Booker - Kenali", mine.account_label)

    print("\nSAYING IT IS THE CLIENT'S, AFTER THE FACT:")

c = application.test_client()
with c.session_transaction() as sess:
    sess["_user_id"] = str(boss_id)
    sess["_fresh"] = True


def ledger_total():
    page = c.get("/admin/expenses").data.decode("utf-8", "replace")
    import re
    m = re.search(r"TOTAL OUT.*?\$([\d,]+\.\d\d)", page, re.S | re.I)
    return float(m.group(1).replace(",", "")) if m else None


before_total = ledger_total()
check("the ledger counts it while it is thought to be mine",
      before_total == 59.67, before_total)

r = c.post(f"/admin/service-costs/providers/{provider_id}/edit",
           data={"name": "twilio", "twilio_account_sid": "AC0",
                 "twilio_auth_token": "t", "is_active": "on",
                 "account_client_id": str(kenali_id)},
           follow_redirects=True)
body = r.data.decode("utf-8", "replace")
check("the press says what came off the ledger",
      "came off your ledger" in body and "Kenali Kendrick's card" in body,
      body[body.find("came off") - 120:body.find("came off") + 80] if "came off" in body else "no flash")

with application.app_context():
    entries = ServiceCostEntry.query.all()
    check("THE POINT: the cost is still recorded", len(entries) == 1, len(entries))
    check("and it still says what it cost", round(entries[0].raw_amount, 2) == 59.67)
    check("THE POINT: but it is no longer an expense",
          Expense.query.count() == 0, Expense.query.count())
    check("nothing dangles: the entry points at no expense",
          entries[0].expense_id is None, entries[0].expense_id)
    check("and it is attributed to them, not left unallocated",
          "[unallocated]" not in (entries[0].description or ""), entries[0].description)

after_total = ledger_total()
check("the ledger total drops by exactly that much",
      after_total == 0.0, after_total)

print("\nAND A NIGHTLY SYNC DOES NOT PUT IT BACK:")
with application.app_context():
    provider = db.session.get(ServiceProvider, provider_id)
    costs._sync_twilio(provider)
    check("still no expense after another sync", Expense.query.count() == 0,
          Expense.query.count())
    check("still one cost entry", ServiceCostEntry.query.count() == 1)

print("\nAND IT IS NOT A ONE WAY DOOR:")
r = c.post(f"/admin/service-costs/providers/{provider_id}/edit",
           data={"name": "twilio", "twilio_account_sid": "AC0",
                 "twilio_auth_token": "t", "is_active": "on",
                 "account_client_id": ""},
           follow_redirects=True)
with application.app_context():
    check("saying it is mine again books it back",
          Expense.query.count() == 1, Expense.query.count())
    check("for the same money", round(Expense.query.first().amount, 2) == 59.67,
          Expense.query.first().amount)
check("and the total comes back with it", ledger_total() == 59.67, ledger_total())

print("\nTHE PAGE SAYS WHOSE IT IS:")
page = c.get("/admin/service-costs/providers").data.decode("utf-8", "replace")
check("the card names the payer", "Billed to" in page and "Built by Bean" in page)
check("and what the vendor calls the account", "Talent Booker - Kenali" in page)

print("\n" + ("ALL PASS" if not FAIL else str(len(FAIL)) + " FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
