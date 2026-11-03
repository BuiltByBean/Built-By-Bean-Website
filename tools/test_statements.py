# -*- coding: utf-8 -*-
"""Card statements, read into the books.

Michael's charges since April sit on cards with no feed: Built by Bean's
Chase debit, his personal debit and his personal credit card. Proves:

  1. Chase's credit card and checking exports, and a Debit/Credit export,
     all read into the bank's sign (money out negative); a card whose export
     shows purchases positive is flipped.
  2. Uploading the same statement twice stores each charge once, while two
     identical same-day charges stay two.
  3. On a personal card: a business charge with a rule becomes an expense
     paid personally by its owner (his money put in); paying the card off
     is a transfer; an unknown purchase waits for review and is never income.
  4. "This shop is personal", learned on a personal card, never marks the
     same shop personal on a company card.
  5. An expense already typed for the same charge is adopted, and marked as
     paid personally, not doubled; a receipt waiting in a mailbox attaches.
  6. A Railway charge on a personal card is covered by its sync and still
     counts as the owner's money put in.
  7. The Books page carries the section, and an upload lands on the review
     list; the nightly Mercury read never touches a statement account.

Run: python tools/test_statements.py
"""
import io
import os
import pathlib
import sys
import tempfile
from datetime import date

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-statements-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("ANTHROPIC_API_KEY", None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, BankConnection, BankTransaction, Business, BusinessOwner, Expense,  # noqa: E402
                    Receipt, ReceiptMailbox, ServiceProvider, User)
import bank_feed  # noqa: E402
import books_service  # noqa: E402
import statements  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


CHASE_CREDIT = """Transaction Date,Post Date,Description,Category,Type,Amount,Memo
10/05/2026,10/06/2026,GITHUB INC,Shopping,Sale,-4.00,
10/07/2026,10/08/2026,TARGET 00012345,Shopping,Sale,-52.17,
10/09/2026,10/09/2026,STARBUCKS STORE 123,Food & Drink,Sale,-5.25,
10/09/2026,10/09/2026,STARBUCKS STORE 123,Food & Drink,Sale,-5.25,
10/12/2026,10/12/2026,RAILWAY,Shopping,Sale,-20.00,
10/15/2026,10/15/2026,Payment Thank You-Mobile,,Payment,500.00,
10/18/2026,10/19/2026,TARGET 00012345,Shopping,Return,10.00,
"""
CHASE_CHECKING = """Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #
DEBIT,10/03/2026,"CLOUDFLARE   CLOUDFLARE.COM CA",-11.17,DEBIT_CARD,1200.00,,
CREDIT,10/04/2026,"ZELLE PAYMENT FROM CASON KUPER",450.00,QUICKPAY_CREDIT,1650.00,,
DEBIT,10/06/2026,"TARGET 00012345",-30.00,DEBIT_CARD,1620.00,,
"""
DEBIT_CREDIT = """Date,Description,Debit,Credit
2026-10-02,SENTRY.IO,26.00,
2026-10-03,REFUND SENTRY.IO,,26.00
"""
AMEX = """Date,Description,Amount
10/20/2026,ADOBE CREATIVE CLD,54.99
"""

print("1. Reading the formats")
cc = statements.parse(CHASE_CREDIT)
check("Chase credit card: seven rows, purchases negative",
      len(cc) == 7 and cc[0]["amount"] == -4.0 and cc[5]["amount"] == 500.0, [r["amount"] for r in cc])
ck = statements.parse(CHASE_CHECKING)
check("Chase checking: debits negative, the Zelle positive",
      [r["amount"] for r in ck] == [-11.17, 450.0, -30.0], [r["amount"] for r in ck])
dc = statements.parse(DEBIT_CREDIT)
check("Debit and Credit columns", [r["amount"] for r in dc] == [-26.0, 26.0], [r["amount"] for r in dc])
ax = statements.parse(AMEX, charges_positive=True)
check("a card that shows purchases positive is flipped", ax[0]["amount"] == -54.99)
check("two identical same-day coffees are two lines", len({r["ref"] for r in cc}) == 7)
try:
    statements.parse("hello,world\n1,2\n")
    check("a file that is not a statement is refused", False)
except statements.StatementError:
    check("a file that is not a statement is refused", True)

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board")
    db.session.add_all([boss, bbb])
    db.session.flush()
    railway = ServiceProvider(name="railway", display_name="Railway", is_active=True)
    db.session.add_all([railway, BusinessOwner(business_id=bbb.id, name="Michael Bean", share_percent=100)])
    db.session.commit()
    ids = {"bbb": bbb.id, "boss": boss.id}
    bank_feed.remember("GITHUB", "expense", vendor="GitHub", category="software")
    bank_feed.remember("RAILWAY", "covered", vendor="Railway", category="hosting", provider_id=railway.id)
    bank_feed.remember("CLOUDFLARE", "expense", vendor="Cloudflare", category="domain")
    bank_feed.remember("CHASE", "contribution", vendor="Michael Bean", owner_name="Michael Bean")
    # Typed earlier, for the same GitHub charge.
    db.session.add(Expense(amount=4.0, description="GitHub Pro", category="software",
                           date=date(2026, 10, 4), business_id=bbb.id))
    box = ReceiptMailbox(address="m@example.test", password="x")
    db.session.add(box)
    db.session.flush()
    db.session.add(Receipt(mailbox_id=box.id, message_key="<cf>", vendor="Cloudflare", subject="Receipt",
                           received_on=date(2026, 10, 2), amount=11.17, filename="cf.pdf",
                           original_name="cf.pdf", status="unmatched"))
    db.session.commit()

    personal = BankConnection(business_id=bbb.id, provider="statement", label="Chase Sapphire",
                              token="", kind="personal", owner_name="Michael Bean")
    company = BankConnection(business_id=bbb.id, provider="statement", label="Chase business debit",
                             token="", kind="business")
    db.session.add_all([personal, company])
    db.session.commit()

    print("2. The personal card")
    counts = statements.import_rows(personal, cc)
    lines = {(l.counterparty, l.amount): l for l in
             BankTransaction.query.filter_by(connection_id=personal.id).all()}
    gh = lines[("GITHUB INC", -4.0)]
    check("a business charge is an expense paid personally",
          gh.disposition == "expense" and gh.expense and gh.expense.paid_by == "Michael Bean")
    check("adopting the expense typed earlier, not doubling it",
          Expense.query.filter(Expense.amount == 4.0).count() == 1)
    check("paying the card off is a transfer",
          lines[("Payment Thank You-Mobile", 500.0)].disposition == "transfer")
    check("an unknown purchase waits for review",
          lines[("TARGET 00012345", -52.17)].disposition == "review")
    check("a return on a personal card is not income",
          lines[("TARGET 00012345", 10.0)].disposition == "review")
    check("the Railway charge is covered by its sync",
          lines[("RAILWAY", -20.0)].disposition == "covered" and lines[("RAILWAY", -20.0)].expense_id is None)
    moved = statements.import_rows(personal, [
        {"date": date(2026, 10, 20), "description": "CHASE ONLINE TRANSFER FROM BUSINESS", "amount": 300.0,
         "kind": "ACCT_XFER", "ref": "st:moved-in"},
        {"date": date(2026, 10, 21), "description": "ONLINE TRANSFER TO MERCURY", "amount": -200.0,
         "kind": "ACCT_XFER", "ref": "st:moved-out"}])
    inn = BankTransaction.query.filter_by(connection_id=personal.id, external_id="st:moved-in").one()
    out = BankTransaction.query.filter_by(connection_id=personal.id, external_id="st:moved-out").one()
    check("a contribution rule on a personal account settles as a transfer",
          inn.disposition == "transfer" and not inn.owner_name, inn.disposition)
    bank_feed.decide(out, "contribution", pattern="ONLINE TRANSFER TO MERCURY", owner_name="Michael Bean")
    out = db.session.get(BankTransaction, out.id)
    check("money moved from a personal account to a company is a transfer there, not counted twice",
          out.disposition == "transfer" and out.expense_id is None, out.disposition)
    # Google Play, $25, already in EntertainHQ's books from its old list; the
    # same charge on the personal card must not be booked to Built by Bean too.
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="ehq", sales_source="hub")
    db.session.add(ehq)
    db.session.flush()
    play = Expense(amount=25.0, description="Google Play developer account", category="software",
                   date=date(2026, 10, 30), business_id=ehq.id)
    db.session.add(play)
    db.session.commit()
    bank_feed.remember("GOOGLE *PLAY", "expense", vendor="Google Play", category="software")
    statements.import_rows(personal, [{"date": date(2026, 10, 31), "description": "GOOGLE *Play",
                                       "amount": -25.0, "kind": "Sale", "ref": "st:play"}])
    gp = BankTransaction.query.filter_by(connection_id=personal.id, external_id="st:play").one()
    check("a personal card's charge adopts the expense another company already has",
          gp.expense_id == play.id and Expense.query.filter(Expense.amount == 25.0).count() == 1
          and db.session.get(Expense, play.id).paid_by == "Michael Bean")
    # And one that was booked twice before this existed is folded into one.
    dup = Expense(amount=25.0, description="Google Play", category="software", date=date(2026, 10, 31),
                  business_id=bbb.id, paid_by="Michael Bean")
    db.session.add(dup)
    db.session.flush()
    gp.expense_id = dup.id
    db.session.commit()
    folded = bank_feed.fold_duplicates()
    gp = db.session.get(BankTransaction, gp.id)
    check("a charge already booked twice folds into the one that was there first",
          folded == 1 and gp.expense_id == play.id and db.session.get(Expense, dup.id) is None, folded)
    check("Claude is told the line is on a personal card",
          "PERSONAL CARD of Michael Bean" in bank_feed._account_words(gh))
    again = statements.import_rows(personal, statements.parse(CHASE_CREDIT))
    check("the same statement twice stores nothing twice",
          again["new"] == 0 and BankTransaction.query.filter_by(connection_id=personal.id).count() == 10)
    money = books_service.owner_money_between(bbb, date(2026, 1, 1), date(2027, 1, 1))
    check("the owner put in the GitHub and the Railway he paid personally",
          money.get("Michael Bean", {}).get("in") == 24.0, money)

    print("3. Personal stays personal")
    target = lines[("TARGET 00012345", -52.17)]
    bank_feed.decide(target, "personal", pattern="TARGET", vendor="Target", keep=True)
    check("the purchase is set aside", db.session.get(BankTransaction, target.id).disposition == "personal")
    statements.import_rows(company, ck)
    co_target = BankTransaction.query.filter_by(connection_id=company.id, amount=-30.0).one()
    check("the same shop on the company card is not marked personal",
          co_target.disposition == "review", co_target.disposition)
    zelle = BankTransaction.query.filter_by(connection_id=company.id, amount=450.0).one()
    check("a client payment into the company account is income", zelle.disposition == "income")
    cf = BankTransaction.query.filter_by(connection_id=company.id, amount=-11.17).one()
    check("a company card charge is the company's own, not paid personally",
          cf.expense and not cf.expense.paid_by)
    check("and the receipt waiting for it attached",
          Receipt.query.filter_by(message_key="<cf>").one().status == "matched"
          and cf.expense.receipt_filename == "cf.pdf")

    print("4. The nightly Mercury read")
    seen = []
    real = bank_feed.sync_connection
    bank_feed.sync_connection = lambda conn, **kw: seen.append(conn.id) or {}
    bank_feed.sync_all(application)
    bank_feed.sync_connection = real
    check("never touches a statement account", seen == [], seen)

print("5. The page")
c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True
page = c.get("/admin/books/?tab=connections").get_data(as_text=True)
check("the Books page lists the cards", 'id="statements"' in page and "Chase Sapphire" in page)
check("no em dash", "\u2014" not in page)
first = c.get("/admin/books/").get_data(as_text=True)
check("the first tab is a company, not the cards",
      "Chase Sapphire" not in first and 'id="company-' in first and "Connections" in first)
with application.app_context():
    sid = BankConnection.query.filter_by(label="Chase business debit").one().id
r = c.post(f"/admin/books/statements/{sid}/upload",
           data={"statement": (io.BytesIO(DEBIT_CREDIT.encode()), "sentry.csv")},
           content_type="multipart/form-data", follow_redirects=False)
check("an upload with lines to sort goes to the review list",
      r.status_code == 302 and r.headers["Location"].endswith("/admin/bank/"), r.headers.get("Location"))
r = c.post(f"/admin/books/statements/{sid}/upload",
           data={"statement": (io.BytesIO(b"nothing,here\n1,2\n"), "junk.csv")},
           content_type="multipart/form-data", follow_redirects=True)
check("a file that is not a statement is said plainly", "no date, description and amount" in r.get_data(as_text=True))
r = c.post("/admin/books/statements", data={"label": "Personal debit", "business_id": ids["bbb"],
                                             "kind": "personal", "owner_name": "Michael Bean"},
           follow_redirects=True)
with application.app_context():
    made = BankConnection.query.filter_by(label="Personal debit").one()
    check("a new personal card is added", made.kind == "personal" and made.provider == "statement"
          and made.owner_name == "Michael Bean")

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
