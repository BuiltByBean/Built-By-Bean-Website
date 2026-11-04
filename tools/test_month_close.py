# -*- coding: utf-8 -*-
"""The month closes itself when it is clean (automation item 14).

  1. Nightly, a finished month closes once nothing is unsorted, EVERY expense
     has its receipt (Michael, 2026-11-04: not only those over $75) and every
     account agrees; it keeps the totals it closed on.
  2. A month that is not clean stays open and the company gets ONE Needs
     attention row saying why: "October will not close: 1 unsorted, 1
     receipt", with the earlier open months counted under it.
  3. An account that does not agree holds every month open and says so.
  4. Closing by hand takes the row away at once; the month in progress is
     never closed.

Run: python tools/test_month_close.py
"""
import json
import os
import pathlib
import sys
import tempfile
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-close-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("STRIPE_SECRET_KEY", None)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, BankConnection, BankTransaction, BooksFlag, Business, Expense,  # noqa: E402
                    MonthClose, User)
import books_upkeep  # noqa: E402

application = create_app()
FAIL = []
TODAY = date(2026, 11, 4)


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def spend(conn, ext, amount, day, receipt=True, disposition="expense"):
    e = Expense(amount=-amount, date=day, business_id=conn.business_id, description=f"line {ext}",
                receipt_filename="r.pdf" if receipt else None)
    db.session.add(e)
    db.session.flush()
    db.session.add(BankTransaction(connection_id=conn.id, business_id=conn.business_id, external_id=ext,
                                   account_id="acct-1", amount=amount, occurred_on=day, status="sent",
                                   disposition=disposition, expense_id=e.id if disposition == "expense" else None))
    return e


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board")
    db.session.add_all([boss, bbb])
    db.session.flush()
    conn = BankConnection(business_id=bbb.id, provider="mercury", label="Mercury", token="x",
                          accounts_json=json.dumps({"acct-1": "Checking"}))
    db.session.add(conn)
    db.session.flush()
    spend(conn, "s1", -40.00, date(2026, 9, 3))
    spend(conn, "o1", -12.00, date(2026, 10, 3), receipt=False)       # a small one: still a receipt to find
    spend(conn, "o2", -9.00, date(2026, 10, 9), disposition="review")  # nobody has sorted it
    spend(conn, "n1", -5.00, date(2026, 11, 2), receipt=False)       # the month in progress
    total = sum(l.amount for l in BankTransaction.query.all())
    conn.balances_json = json.dumps({"acct-1": round(total, 2)})
    db.session.commit()
    ids = {"bbb": bbb.id, "boss": boss.id, "conn": conn.id}

    print("1. A clean month closes itself")
    note = books_upkeep.close_months(today=TODAY)
    closed = {m.month: m for m in MonthClose.query.all()}
    check("September closes", date(2026, 9, 1) in closed, note)
    sept = closed.get(date(2026, 9, 1))
    check("with the totals it closed on and who closed it",
          sept is not None and sept.expenses_total == 40.0 and sept.note == books_upkeep.NIGHT_NOTE,
          sept and (sept.expenses_total, sept.note))
    check("an empty finished month closes too", date(2026, 4, 1) in closed)
    check("the month in progress never closes", date(2026, 11, 1) not in closed)

    print("2. A month that is not clean says why")
    check("October stays open", date(2026, 10, 1) not in closed)
    flag = BooksFlag.query.filter_by(kind="month", key=str(ids["bbb"])).first()
    check("one row for the company", BooksFlag.query.filter_by(kind="month").count() == 1)
    check("saying why, in Michael's words", flag and flag.title == "October will not close: 1 unsorted, 1 receipt",
          flag and flag.title)
    check("and linking to the month", flag and flag.link.endswith("/month/2026-10"))
    check("a receipt under $75 still counts", "1 receipt" in (flag.title if flag else ""))

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True
page = c.get("/admin/attention/").get_data(as_text=True)
check("Needs attention shows it", "October will not close: 1 unsorted, 1 receipt" in page)

with application.app_context():
    print("3. An account that does not agree holds the month")
    BankTransaction.query.filter_by(external_id="o2").update({"disposition": "expense"})
    Expense.query.filter_by(description="line o1").update({"receipt_filename": "r.pdf"})
    BankConnection.query.filter_by(id=ids["conn"]).update({"balances_json": json.dumps({"acct-1": 1.0})})
    db.session.commit()
    books_upkeep.close_months(today=TODAY)
    flag = BooksFlag.query.filter_by(kind="month").first()
    check("October still open, and the row names the account",
          MonthClose.query.filter_by(month=date(2026, 10, 1)).first() is None
          and flag is not None and "Checking does not agree" in flag.title, flag and flag.title)
    good = round(sum(l.amount for l in BankTransaction.query.all()), 2)
    BankConnection.query.filter_by(id=ids["conn"]).update({"balances_json": json.dumps({"acct-1": good})})
    db.session.commit()
    books_upkeep.close_months(today=TODAY)
    check("once it agrees, October closes and the row goes",
          MonthClose.query.filter_by(month=date(2026, 10, 1)).first() is not None
          and BooksFlag.query.filter_by(kind="month").count() == 0)

    print("4. Closing by hand")
    MonthClose.query.filter_by(month=date(2026, 10, 1)).delete()
    BankTransaction.query.filter_by(external_id="o2").update({"disposition": "review"})
    db.session.commit()
    books_upkeep.close_months(today=TODAY)
    check("the row is back while October is open", BooksFlag.query.filter_by(kind="month").count() == 1)
r = c.post("/admin/books/%d/month/2026-10/close" % ids["bbb"])
with application.app_context():
    check("closing it on its page takes the row away at once",
          BooksFlag.query.filter_by(kind="month").count() == 0, r.status_code)

check("no em dash", "—" not in (ROOT / "books_upkeep.py").read_text(encoding="utf-8"))
print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
