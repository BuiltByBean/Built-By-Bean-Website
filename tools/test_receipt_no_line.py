# -*- coding: utf-8 -*-
"""A receipt with no bank line means a card the board cannot see (automation
audit, smaller item).

  1. A known vendor's receipt with no bank line for its amount within five
     days on any connection is listed, and is one Needs attention row.
  2. Not listed: a receipt whose charge is on a connection, a stranger's
     receipt (a mortgage notice), and a receipt newer than every
     connection's lines reach, which may simply not have arrived yet.

Run: python tools/test_receipt_no_line.py
"""
import os
import pathlib
import sys
import tempfile
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-noline-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("ANTHROPIC_API_KEY", None)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, BankConnection, BankTransaction, BooksFlag, Business, Receipt,  # noqa: E402
                    ReceiptMailbox, User)
import bank_feed  # noqa: E402
import books_upkeep  # noqa: E402

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
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board")
    db.session.add_all([boss, bbb])
    db.session.flush()
    conn = BankConnection(business_id=bbb.id, provider="mercury", label="Mercury", token="x")
    box = ReceiptMailbox(address="m@example.test", password="x")
    db.session.add_all([conn, box])
    db.session.flush()
    bank_feed.remember("PIRATESHIP", "expense", vendor="Pirate Ship", category="office")
    for ext, amount, day in (("a", -20.00, date(2026, 10, 3)), ("b", -1.00, date(2026, 11, 1))):
        db.session.add(BankTransaction(connection_id=conn.id, business_id=bbb.id, external_id=ext,
                                       amount=amount, occurred_on=day, status="sent", disposition="expense"))

    def receipt(key, sender, amount, day, subject="Your receipt"):
        r = Receipt(mailbox_id=box.id, message_key=key, sender=sender, vendor=sender.split(" <")[0],
                    subject=subject, received_on=day, amount=amount, status="unmatched")
        db.session.add(r)
        return r

    unseen = receipt("1", "Railway <billing@railway.app>", 42.00, date(2026, 10, 1))
    receipt("2", "Railway <billing@railway.app>", 20.00, date(2026, 10, 1))      # on the bank Oct 3
    receipt("3", "Pirate Ship <help@pirateship.com>", 9.15, date(2026, 10, 12))  # a vendor from a rule
    receipt("4", "Mr. Cooper <noreply@mrcooper.com>", 1450.00, date(2026, 10, 1), "Your mortgage payment")
    receipt("5", "Railway <billing@railway.app>", 33.00, date(2026, 10, 30))     # too new to tell
    db.session.commit()
    boss_id, unseen_id = boss.id, unseen.id

    note = books_upkeep.receipts_without_line(today=date(2026, 11, 4))
    flag = BooksFlag.query.filter_by(kind="receipts").first()
    listed = sorted((i["vendor"], i["amount"]) for i in (flag.items if flag else []))
    check("a known vendor's receipt with no bank line is listed", ("Railway", 42.0) in listed, listed)
    check("and so is one from a vendor a rule names", ("Pirate Ship", 9.15) in listed, listed)
    check("not one whose charge is on a connection", ("Railway", 20.0) not in listed, listed)
    check("not a stranger's", all(v != "Mr. Cooper" for v, _ in listed), listed)
    check("not one newer than every connection reaches", ("Railway", 33.0) not in listed, listed)
    check("one row", flag is not None and flag.title == "2 receipts with no bank line", flag and flag.title)

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(boss_id)
    s["_fresh"] = True
page = c.get("/admin/attention/").get_data(as_text=True)
check("Needs attention shows it", "2 receipts with no bank line" in page)
page = c.get("/admin/books/checks?kind=receipts").get_data(as_text=True)
check("the checks page lists them with their documents", f"/admin/books/receipts/{unseen_id}/file" in page)
r = c.post(f"/admin/books/receipts/{unseen_id}/ignore", data={"next": "checks"})
with application.app_context():
    flag = BooksFlag.query.filter_by(kind="receipts").first()
    check("setting one aside takes it off the list at once",
          r.status_code == 302 and "checks" in r.headers.get("Location", "")
          and flag is not None and flag.title == "1 receipt with no bank line", flag and flag.title)
    books_upkeep.receipts_without_line(today=date(2026, 11, 4))
    flag = BooksFlag.query.filter_by(kind="receipts").first()
    check("and the next night leaves it off", flag is not None and flag.count == 1)
    books_upkeep.receipts_without_line(today=date(2027, 1, 4))
    check("a receipt older than the window is no longer asked about",
          BooksFlag.query.filter_by(kind="receipts").count() == 0)
check("a stranger cannot read the checks page",
      application.test_client().get("/admin/books/checks?kind=receipts").status_code in (302, 401, 403))

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
