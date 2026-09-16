# -*- coding: utf-8 -*-
"""A month to date figure is one row that grows, not a row a night.

Twilio's monthly usage record carries an end_date that moves with today while
the month is open. `period_end` is part of a cost entry's key, so the nightly
sync never matched what it wrote the night before and booked the whole month
to date again every night. September 2026 read $462.79 of outbound SMS in the
ledger against $59.67 of real usage.

What is proved:

  1. Fifteen nights of the real Twilio payload produce ONE entry and ONE
     expense, holding the latest figure and not the sum of the readings.
  2. The entry is keyed to the calendar month, so its key cannot move.
  3. THE PROTECTED CASE: a vendor billing twice in one month still records
     both. Those are single day charges, not a running total, and the fold
     must never touch them (_sync_flat: Anthropic, March and May 2026).
  4. The migration folds a ledger that already carries the duplicates, keeps
     the newest reading, deletes the rest with their expenses, and leaves the
     twice billed vendor alone.
  5. NO EXPENSE IS DATED IN THE FUTURE. The entry's period is a key and is the
     whole month; the expense's date is a fact about when money went out, and
     the two are not the same field. A month in progress dates to today.

Run: python tools/test_cost_periods.py
"""
import json
import os
import pathlib
import sys
import tempfile
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-costs-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import service_costs_service as costs  # noqa: E402
from app import create_app  # noqa: E402
from models import db, Expense, ServiceCostEntry, ServiceProvider  # noqa: E402

application = create_app()
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


# Twilio, as it actually answers: monthly usage records whose end_date is
# today while the month is open, and whose price is the month to date.
READINGS = [3.20, 8.83, 15.96, 19.87, 20.52, 20.88, 21.46, 25.99,
            34.69, 39.29, 45.03, 45.58, 45.92, 55.90, 59.67]
TODAY = date(2026, 9, 1)


class Answer:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def twilio_on(day, price):
    """What the API returns on `day`, with the month to date at `price`."""
    return Answer({"usage_records": [{
        "category": "sms-outbound",
        "description": "Standard Outbound SMS",
        "price": str(price),
        "start_date": day.replace(day=1).isoformat(),
        # The whole bug in one field: it moves.
        "end_date": day.isoformat(),
    }]})


with application.app_context():
    db.create_all()
    twilio = ServiceProvider(
        name="twilio", display_name="Twilio", is_active=True,
        credentials_json=json.dumps({"account_sid": "AC0", "auth_token": "t"}))
    db.session.add(twilio)
    db.session.commit()
    twilio_id = twilio.id

    print("FIFTEEN NIGHTS OF THE SAME MONTH:")
    for i, price in enumerate(READINGS):
        day = date(2026, 9, 1) + timedelta(days=i)
        costs.date = type("D", (), {"today": staticmethod(lambda d=day: d),
                                    "fromisoformat": staticmethod(date.fromisoformat)})
        costs.requests = type("R", (), {
            "get": staticmethod(lambda *a, _d=day, _p=price, **kw: twilio_on(_d, _p))})
        costs._sync_twilio(twilio)

    entries = ServiceCostEntry.query.filter_by(provider_id=twilio_id).all()
    check("one entry, not fifteen", len(entries) == 1, len(entries))
    if entries:
        e = entries[0]
        check("holding the latest reading, not the sum of them",
              round(e.raw_amount, 2) == 59.67, e.raw_amount)
        check("THE POINT: not the sum, which is what the ledger showed",
              round(e.raw_amount, 2) != round(sum(READINGS), 2),
              f"{e.raw_amount} vs {sum(READINGS)}")
        check("keyed to the first of the month", e.period_start == date(2026, 9, 1),
              e.period_start)
        check("and to the last of it, which cannot move",
              e.period_end == date(2026, 9, 30), e.period_end)
        check("its description names the month once",
              e.description.count("(Sep 2026)") == 1, e.description)
    expenses = Expense.query.filter_by(category="service_cost").all()
    check("one expense beside it", len(expenses) == 1, len(expenses))
    if expenses:
        # The last sync above ran on 15 September, mid month. The entry is
        # keyed to the whole month either way; the expense is not dated past
        # the day it was read.
        check("THE POINT: dated a day that has happened, not the month's end",
              expenses[0].date == date(2026, 9, 15), expenses[0].date)
        check("and still inside the month it covers",
              (expenses[0].date.year, expenses[0].date.month) == (2026, 9),
              expenses[0].date)
        check("for the real figure", round(expenses[0].amount, 2) == 59.67,
              expenses[0].amount)

    print("\nA MONTH THAT CLOSED, AND A NEW ONE:")
    # The last nightly run of September, which is what settles the month on
    # its own last day. Nothing re-reads a closed month afterwards - the sync
    # only ever asks for the current one - so the date a month keeps is
    # whatever its final run saw. That is a real date in the right month
    # either way, and with a nightly job the final run is the last day.
    for day, price in ((date(2026, 9, 30), 61.40),):
        costs.date = type("D", (), {"today": staticmethod(lambda d=day: d),
                                    "fromisoformat": staticmethod(date.fromisoformat)})
        costs.requests = type("R", (), {
            "get": staticmethod(lambda *a, _d=day, _p=price, **kw: twilio_on(_d, _p))})
        costs._sync_twilio(twilio)

    day = date(2026, 10, 4)
    costs.date = type("D", (), {"today": staticmethod(lambda d=day: d),
                                "fromisoformat": staticmethod(date.fromisoformat)})
    costs.requests = type("R", (), {
        "get": staticmethod(lambda *a, **kw: twilio_on(day, 4.10))})
    costs._sync_twilio(twilio)
    entries = ServiceCostEntry.query.filter_by(provider_id=twilio_id).order_by(
        ServiceCostEntry.period_start).all()
    check("October is its own row", len(entries) == 2, len(entries))
    check("and September holds its final reading",
          round(entries[0].raw_amount, 2) == 61.40, entries[0].raw_amount)
    sept_expense = db.session.get(Expense, entries[0].expense_id)
    check("September's expense settled on the last day of September, now it is over",
          sept_expense.date == date(2026, 9, 30), sept_expense.date)
    oct_expense = db.session.get(Expense, entries[1].expense_id)
    check("and October, still running, is dated the day it was read",
          oct_expense.date == date(2026, 10, 4), oct_expense.date)
    check("nothing in the ledger is dated ahead of the day it was read",
          all(e.date <= date(2026, 10, 4)
              for e in Expense.query.filter_by(category="service_cost").all()),
          [str(e.date) for e in Expense.query.filter_by(category="service_cost").all()])


# ── The migration, over a ledger that already has the duplicates ──
print("\nFOLDING WHAT THE OLD CODE LEFT BEHIND:")
import sqlalchemy as sa  # noqa: E402
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "fold", ROOT / "migrations" / "versions" / "d4f81c27a3b9_one_cost_entry_per_month.py")
fold = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fold)

with application.app_context():
    db.drop_all()
    db.create_all()
    provider = ServiceProvider(name="twilio", display_name="Twilio", is_active=True)
    flat = ServiceProvider(name="anthropic", display_name="Claude", is_active=True)
    db.session.add_all([provider, flat])
    db.session.commit()

    # The ledger as it stood: one row per night, each holding the month to date.
    for i, price in enumerate(READINGS):
        day = date(2026, 9, 1) + timedelta(days=i)
        exp = Expense(category="service_cost", amount=price, date=day,
                      description=f"Twilio - Standard Outbound SMS ({day:%b %Y})")
        db.session.add(exp)
        db.session.flush()
        db.session.add(ServiceCostEntry(
            provider_id=provider.id, resource_identifier="twilio:sms-outbound",
            period_start=date(2026, 9, 1), period_end=day,
            raw_amount=price, allocated_amount=price, expense_id=exp.id,
            description=f"Twilio - Standard Outbound SMS ({day:%b %Y})"))
    # August, already settled: one row, and it must survive untouched.
    aug = Expense(category="service_cost", amount=70.51, date=date(2026, 8, 31))
    db.session.add(aug)
    db.session.flush()
    db.session.add(ServiceCostEntry(
        provider_id=provider.id, resource_identifier="twilio:sms-outbound",
        period_start=date(2026, 8, 1), period_end=date(2026, 8, 31),
        raw_amount=70.51, allocated_amount=70.51, expense_id=aug.id))
    # The protected case: one vendor, two charges, one month, both real.
    for day, amount in ((date(2026, 3, 26), 21.32), (date(2026, 3, 28), 86.75)):
        exp = Expense(category="service_cost", amount=amount, date=day)
        db.session.add(exp)
        db.session.flush()
        db.session.add(ServiceCostEntry(
            provider_id=flat.id, resource_identifier="anthropic:subscription",
            period_start=day, period_end=day,
            raw_amount=amount, allocated_amount=amount, expense_id=exp.id))
    db.session.commit()

    before = ServiceCostEntry.query.count()
    check("the ledger starts with the duplicates in it", before == 18, before)

    class FakeOp:
        """Alembic hands a real Connection, so the test has to as well: a
        scoped_session cannot be inspected and the guard would blow up."""

        @staticmethod
        def get_bind():
            return db.session.connection()

    fold.op = FakeOp
    fold.upgrade()
    db.session.commit()

    sept = ServiceCostEntry.query.filter_by(
        resource_identifier="twilio:sms-outbound",
        period_start=date(2026, 9, 1)).all()
    check("September is one row now", len(sept) == 1, len(sept))
    if sept:
        check("holding the newest reading", round(sept[0].raw_amount, 2) == 59.67,
              sept[0].raw_amount)
        check("with the month's own bounds", sept[0].period_end == date(2026, 9, 30),
              sept[0].period_end)
        # Not the month's end: the same honest date the sync writes.
        settled = db.session.get(Expense, sept[0].expense_id).date
        check("and its expense dated no later than today",
              settled == min(date(2026, 9, 30), date.today()), settled)
    check("the fourteen duplicate expenses went with them",
          Expense.query.filter_by(category="service_cost").count() == 4,
          Expense.query.filter_by(category="service_cost").count())
    aug_rows = ServiceCostEntry.query.filter_by(period_start=date(2026, 8, 1)).all()
    check("August, already settled, is untouched",
          len(aug_rows) == 1 and round(aug_rows[0].raw_amount, 2) == 70.51)
    twice = ServiceCostEntry.query.filter_by(
        resource_identifier="anthropic:subscription").all()
    check("THE PROTECTED CASE: a vendor that billed twice still has both rows",
          len(twice) == 2, len(twice))
    check("and neither was widened to a month",
          all(r.period_start == r.period_end for r in twice),
          [(r.period_start, r.period_end) for r in twice])

    total = sum(r.allocated_amount for r in ServiceCostEntry.query.all())
    check("the ledger totals what was really spent",
          round(total, 2) == round(59.67 + 70.51 + 21.32 + 86.75, 2), round(total, 2))

    print("\nRUNNING IT TWICE CHANGES NOTHING:")
    fold.upgrade()
    db.session.commit()
    check("still one September row", ServiceCostEntry.query.filter_by(
        period_start=date(2026, 9, 1)).count() == 1)
    check("still four entries in total", ServiceCostEntry.query.count() == 4,
          ServiceCostEntry.query.count())

print("\n" + ("ALL PASS" if not FAIL else str(len(FAIL)) + " FAILED: " + ", ".join(FAIL)))
sys.exit(1 if FAIL else 0)
