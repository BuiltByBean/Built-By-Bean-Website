# -*- coding: utf-8 -*-
"""A company's own Stripe in its books.

Michael, 2026-11-03: income comes from Stripe, where the sale happens, not
from what has reached the bank: "what if there's a bunch of money sitting in
Stripe that we haven't transferred over to our Mercury account?" Proves:

  1. Income is every sale gross on the day paid, less refunds, including a
     sale Stripe has not paid out yet; app-sent sales do not override it.
  2. Stripe's fees are one expense per month in that company's books,
     corrected in place on the next read, never doubled.
  3. The payout landing in Mercury is a transfer, never income again.
  4. A read is repeatable: the same lines read twice store nothing twice.
  5. A refused key is said plainly and kept off the business.
  6. The business page shows the Stripe card, without the key.

Run: python tools/test_stripe_books.py
"""
import os
import pathlib
import sys
import tempfile
from datetime import date, datetime, timezone

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-stripe-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import db, BankConnection, BankTransaction, Business, Expense, StripeActivity, User  # noqa: E402
import bank_feed  # noqa: E402
import books_service  # noqa: E402
import stripe_books  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def ts(day):
    return int(datetime.fromisoformat(day + "T15:00:00+00:00").timestamp())


ROWS = [
    {"id": "txn_1", "created": ts("2026-10-05"), "amount": 10000, "fee": 320, "net": 9680,
     "category": "charge", "type": "charge", "description": "Membership, Venue A"},
    {"id": "txn_2", "created": ts("2026-10-20"), "amount": 5000, "fee": 175, "net": 4825,
     "category": "charge", "type": "charge", "description": "Membership, Venue B"},
    {"id": "txn_3", "created": ts("2026-10-22"), "amount": -2000, "fee": 0, "net": -2000,
     "category": "refund", "type": "refund", "description": "Refund, Venue B"},
    {"id": "txn_4", "created": ts("2026-10-08"), "amount": -9680, "fee": 0, "net": -9680,
     "category": "payout", "type": "payout", "description": "STRIPE PAYOUT"},
    {"id": "txn_5", "created": ts("2026-11-02"), "amount": 2500, "fee": 103, "net": 2397,
     "category": "charge", "type": "charge", "description": "Membership, Venue C"},
]

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="ehq", sales_source="hub",
                   stripe_key="rk_test_x")
    db.session.add_all([boss, ehq])
    db.session.commit()
    ids = {"ehq": ehq.id, "boss": boss.id}

    print("1. Income from Stripe")
    counts = stripe_books.sync(ehq, fetcher=lambda key, since: iter(ROWS))
    check("five lines read", counts.get("read") == 5 and counts.get("new") == 5, counts)
    oct_ = books_service.summarize(ehq, date(2026, 10, 1), date(2026, 11, 1))
    check("October income is sales gross less the refund", oct_["income_total"] == 130.0,
          oct_["income_total"])
    nov = books_service.summarize(ehq, date(2026, 11, 1), date(2026, 12, 1))
    check("a sale not yet paid out still counts", nov["income_total"] == 25.0, nov["income_total"])
    sent = books_service.summarize(ehq, date(2026, 10, 1), date(2026, 11, 1),
                                   sales=[{"date": date(2026, 10, 9), "total": 999.0}])
    check("an app's own list does not override Stripe", sent["income_total"] == 130.0, sent["income_total"])

    print("2. Fees")
    fees = Expense.query.filter_by(business_id=ehq.id, category="bank_fees").order_by(Expense.date).all()
    check("one fee expense per month", [(e.description, e.amount) for e in fees]
          == [("Stripe fees, Oct 2026", 4.95), ("Stripe fees, Nov 2026", 1.03)],
          [(e.description, e.amount) for e in fees])
    check("in that company's books", all(e.business_id == ids["ehq"] for e in fees))

    print("3. Read again")
    ROWS[1]["fee"] = 200
    stripe_books.sync(ehq, fetcher=lambda key, since: iter(ROWS))
    check("nothing stored twice", StripeActivity.query.count() == 5)
    fees = Expense.query.filter_by(business_id=ehq.id, category="bank_fees").all()
    check("the month's fee is corrected in place", len(fees) == 2
          and any(e.amount == 5.2 for e in fees), [(e.description, e.amount) for e in fees])

    print("4. The payout in the bank")
    conn = BankConnection(business_id=ehq.id, token="secret-token:x")
    db.session.add(conn)
    db.session.commit()
    bank_feed.sync_connection(conn, fetch=lambda t, s: iter([
        {"id": "m1", "amount": 96.80, "counterpartyName": "Stripe", "kind": "externalTransfer",
         "status": "sent", "createdAt": "2026-10-10T10:00:00Z", "postedAt": "2026-10-10T12:00:00Z",
         "accountId": "a", "bankDescription": "STRIPE TRANSFER ST-ABC"}]), accounts={"a": "Checking"})
    line = BankTransaction.query.filter_by(external_id="m1").one()
    check("is a transfer, never income", line.disposition == "transfer" and line.expense_id is None)
    oct_ = books_service.summarize(ehq, date(2026, 10, 1), date(2026, 11, 1))
    check("and income is unchanged by it", oct_["income_total"] == 130.0, oct_["income_total"])

print("5. The page")
c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True
page = c.get(f"/admin/books/{ids['ehq']}/connections").get_data(as_text=True)
check("its Books Connections has its Stripe card", 'id="stripe"' in page and "Connected" in page)
check("and never prints the key", "rk_test_x" not in page)
orig = stripe_books.check_key


def refuse(key):
    raise stripe_books.StripeKeyError("Stripe refused that key.")


stripe_books.check_key = refuse
with application.app_context():
    db.session.get(Business, ids["ehq"]).stripe_key = None
    db.session.commit()
r = c.post(f"/admin/books/{ids['ehq']}/stripe", data={"key": "rk_bad"}, follow_redirects=True)
stripe_books.check_key = orig
check("a refused key is said plainly", "Stripe refused that key" in r.get_data(as_text=True))
with application.app_context():
    check("and is not kept", not db.session.get(Business, ids["ehq"]).stripe_key)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
