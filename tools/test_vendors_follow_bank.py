# -*- coding: utf-8 -*-
"""Vendor amounts and covered charges follow the bank (automation item 15).

  1. A flat provider's amount and day come from its last settled line: a
     plan change moves the month's entry to the real charge, to the cent and
     on its day, the old guess goes, the line reads as covered, and the
     provider takes the new figure. A month with two such charges is left to
     review, because one may be another company's plan on the same card.
  2. A prepaid vendor's top-up is the expense; its usage rows record and
     attribute and book no expense, so the same money is not counted twice.
  3. A recurring expense whose vendor has a rule ends, and a child no bank
     line claimed within ten days is one Needs attention row.

Run: python tools/test_vendors_follow_bank.py
"""
import os
import pathlib
import sys
import tempfile
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-follow-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("ANTHROPIC_API_KEY", None)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, BankConnection, BankTransaction, BooksFlag, Business, Expense,  # noqa: E402
                    ServiceCostEntry, ServiceProvider, User)
import bank_feed  # noqa: E402
import books_upkeep  # noqa: E402
import service_costs_service as scs  # noqa: E402

application = create_app()
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def line(conn, ext, amount, name, day):
    l = BankTransaction(connection_id=conn.id, business_id=conn.business_id, external_id=ext, amount=amount,
                        occurred_on=day, status="sent", kind="debitCardTransaction", counterparty=name)
    db.session.add(l)
    db.session.flush()
    bank_feed.classify(l)
    db.session.commit()
    return l


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board")
    db.session.add_all([boss, bbb])
    db.session.flush()
    conn = BankConnection(business_id=bbb.id, provider="mercury", label="Mercury", token="x")
    claude = ServiceProvider(name="flat", display_name="Claude", is_active=True, monthly_cost=100.0, billing_day=15)
    twilio = ServiceProvider(name="twilio", display_name="Twilio", is_active=True)
    db.session.add_all([conn, claude, twilio])
    db.session.commit()
    bank_feed.remember("CLAUDE AI", "covered", vendor="Claude", category="ai_services", provider_id=claude.id)
    bank_feed.remember("TWILIO", "covered", vendor="Twilio", category="software", provider_id=twilio.id)
    bank_feed.remember("GITHUB", "expense", vendor="GitHub", category="software")
    db.session.commit()
    RES = "flat:subscription"

    print("1. A flat provider follows its bank line")
    # What the flat sync wrote on the 15th at the typed price.
    scs._record_cost_entry(claude, RES, date(2026, 10, 15), date(2026, 10, 15), 100.0, "Claude", {})
    db.session.commit()
    upgraded = line(conn, "c1", -200.00, "CLAUDE.AI SUBSCRIPTION", date(2026, 10, 16))
    check("the new price falls to review, as it did before", upgraded.disposition == "review")
    n = scs.follow_flat_from_bank(today=date(2026, 10, 20))
    rows = ServiceCostEntry.query.filter_by(provider_id=claude.id).all()
    check("the month's entry is the real charge, on its day",
          [(r.period_start, r.allocated_amount) for r in rows] == [(date(2026, 10, 16), 200.0)],
          [(r.period_start, r.allocated_amount) for r in rows])
    check("the old guess and its expense are gone",
          Expense.query.filter(Expense.description.like("Claude%")).count() == 1
          and Expense.query.filter(Expense.description.like("Claude%")).first().amount == 200.0)
    check("the line now reads as covered", db.session.get(BankTransaction, upgraded.id).disposition == "covered")
    claude = db.session.get(ServiceProvider, claude.id)
    check("and the provider takes the new amount and day", (claude.monthly_cost, claude.billing_day) == (200.0, 16),
          (claude.monthly_cost, claude.billing_day, n))
    check("a second run changes nothing", scs.follow_flat_from_bank(today=date(2026, 10, 20)) == 0)
    # Two charges in November: one may be EntertainHQ's plan on the same card.
    a = line(conn, "c2", -200.00, "CLAUDE.AI SUBSCRIPTION", date(2026, 11, 16))
    b = line(conn, "c3", -20.00, "CLAUDE.AI SUBSCRIPTION", date(2026, 11, 18))
    scs.follow_flat_from_bank(today=date(2026, 11, 20))
    check("a month with two charges is left alone",
          ServiceCostEntry.query.filter(ServiceCostEntry.provider_id == claude.id,
                                        ServiceCostEntry.period_start >= date(2026, 11, 1)).count() == 0
          and db.session.get(ServiceProvider, claude.id).monthly_cost == 200.0)

    print("2. A prepaid vendor's top-up is the expense")
    topup = line(conn, "t1", -20.00, "TWILIO SENDGRID", date(2026, 10, 7))
    check("the top-up is booked as an expense", topup.disposition == "expense" and topup.expense_id is not None,
          topup.disposition)
    scs._record_cost_entry(twilio, "twilio:sms", date(2026, 10, 1), date(2026, 10, 31), 7.43, "Twilio - SMS", {})
    db.session.commit()
    usage = ServiceCostEntry.query.filter_by(provider_id=twilio.id).first()
    check("its usage row is recorded and books nothing", usage.allocated_amount == 7.43 and usage.expense_id is None)
    check("so October's Twilio is the $20 that left the bank",
          sum(e.amount for e in Expense.query.filter(Expense.description.like("Twilio%")).all()) == 20.0)

    print("3. Recurring expenses the bank now books")
    parent = Expense(amount=4.00, description="GitHub Pro", date=date(2026, 8, 5), business_id=bbb.id,
                     is_recurring=True, frequency="monthly", next_due_date=date(2026, 11, 5), category="software")
    other = Expense(amount=12.00, description="Gym", date=date(2026, 8, 1), business_id=bbb.id,
                    is_recurring=True, frequency="monthly", next_due_date=date(2026, 11, 1))
    db.session.add_all([parent, other])
    db.session.flush()
    claimed = Expense(amount=4.00, description="GitHub Pro", date=date(2026, 9, 5), parent_expense_id=parent.id)
    lonely = Expense(amount=4.00, description="GitHub Pro", date=date(2026, 10, 5), parent_expense_id=parent.id)
    fresh = Expense(amount=4.00, description="GitHub Pro", date=date(2026, 10, 30), parent_expense_id=parent.id)
    db.session.add_all([claimed, lonely, fresh])
    db.session.flush()
    db.session.add(BankTransaction(connection_id=conn.id, business_id=bbb.id, external_id="g1", amount=-4.0,
                                   occurred_on=date(2026, 9, 5), status="sent", disposition="expense",
                                   expense_id=claimed.id))
    db.session.commit()
    note = books_upkeep.end_recurring(today=date(2026, 11, 4))
    parent, other = db.session.get(Expense, parent.id), db.session.get(Expense, other.id)
    check("a recurring expense whose vendor has a rule ends",
          parent.is_recurring is False and parent.recurring_end_date == date(2026, 11, 4), note)
    check("one with no rule carries on", other.is_recurring is True)
    flag = BooksFlag.query.filter_by(kind="recurring").first()
    ids_flagged = [i["id"] for i in (flag.items if flag else [])]
    check("a child no bank line claimed in ten days is listed, and only that one",
          ids_flagged == [lonely.id], ids_flagged)
    lonely_id = lonely.id

c = application.test_client()
with application.app_context():
    boss_id = User.query.first().id
with c.session_transaction() as s:
    s["_user_id"] = str(boss_id)
    s["_fresh"] = True
page = c.get("/admin/attention/").get_data(as_text=True)
check("Needs attention has one row for them", "1 recurring expense no bank line has claimed" in page)
page = c.get("/admin/books/checks?kind=recurring").get_data(as_text=True)
check("and the checks page lists it", f"/admin/expenses/{lonely_id}/edit" in page or "GitHub Pro" in page)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
