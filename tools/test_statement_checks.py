# -*- coding: utf-8 -*-
"""Card statements ask for themselves and reconcile (automation item 13).

  1. A Chase checking export carries the balance after each row: the upload
     keeps the opening and the closing balance whichever order the file is
     in, and the books' bank check holds the lines to the difference, so a
     month nobody uploaded shows as a disagreement.
  2. A source with nothing past last month's end is one Needs attention row,
     and an upload clears it. A card export's Category column is kept.
  3. Chase's alert emails: parsed in both formats, other mail ignored; the
     card is learned from a charge already on one source; a new charge is a
     provisional line booked at once; the statement folds over it rather than
     writing it twice; an alert the statement never confirmed is cancelled
     with its expense.

Run: python tools/test_statement_checks.py
"""
import os
import pathlib
import sys
import tempfile
from datetime import date, datetime
from email.message import EmailMessage

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-stmt-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("ANTHROPIC_API_KEY", None)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, BankConnection, BankTransaction, Business, CardAlert, Expense,  # noqa: E402
                    ReceiptMailbox, User)
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


HEAD = "Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #\n"
# Newest first, as Chase writes it. 1,000.00 before September.
SEPT = HEAD + ("DEBIT,09/20/2026,GITHUB INC,-4.00,DEBIT_CARD,946.00,\n"
               "CREDIT,09/10/2026,CHECK DEPOSIT,100.00,CHECK_DEPOSIT,950.00,\n"
               "DEBIT,09/02/2026,RAILWAY,-150.00,DEBIT_CARD,850.00,\n")
OCT = HEAD + ("DEBIT,10/25/2026,SENTRY,-26.00,DEBIT_CARD,900.00,\n"
              "DEBIT,10/05/2026,RAILWAY,-20.00,DEBIT_CARD,926.00,\n")
NOV = HEAD + ("DEBIT,11/02/2026,RAILWAY,-30.00,DEBIT_CARD,870.00,\n")

print("1. Balances")
rows = statements.parse(SEPT)
check("the balance column is read", [r["balance"] for r in rows] == [946.0, 950.0, 850.0])
check("newest first: opening before the oldest row, closing on the newest",
      statements.balances_of(rows) == (1000.0, date(2026, 9, 2), 946.0, date(2026, 9, 20)),
      statements.balances_of(rows))
check("oldest first gives the same answer",
      statements.balances_of(list(reversed(rows))) == (1000.0, date(2026, 9, 2), 946.0, date(2026, 9, 20)))
check("a file whose balances do not add up is not trusted",
      statements.balances_of([{"date": date(2026, 9, 1), "amount": -5.0, "balance": 10.0},
                              {"date": date(2026, 9, 2), "amount": -5.0, "balance": 99.0},
                              {"date": date(2026, 9, 3), "amount": -5.0, "balance": 1.0}]) is None)
card_rows = statements.parse("Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
                             "10/03/2026,10/04/2026,CHUYS,Food & Drink,Sale,-18.40,\n")
check("a card export's Category is kept, and it has no balance",
      card_rows[0]["category"] == "Food & Drink" and statements.balances_of(card_rows) is None)

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board")
    db.session.add_all([boss, bbb])
    db.session.flush()
    chk = BankConnection(business_id=bbb.id, provider="statement", label="Chase business checking")
    cardc = BankConnection(business_id=bbb.id, provider="statement", label="Freedom", kind="personal",
                           owner_name="Michael Bean")
    box = ReceiptMailbox(address="m@example.test", password="x")
    db.session.add_all([chk, cardc, box])
    db.session.commit()
    bank_feed.remember("RAILWAY", "expense", vendor="Railway", category="hosting")
    bank_feed.remember("STARBUCKS", "expense", vendor="Starbucks", category="meals")
    db.session.commit()
    ids = {"boss": boss.id, "bbb": bbb.id, "chk": chk.id, "card": cardc.id, "box": box.id}

    statements.import_rows(chk, statements.parse(SEPT))
    statements.import_rows(chk, statements.parse(NOV))
    check("the opening and closing balances are kept",
          (chk.opening_balance, chk.opening_on, chk.balance, chk.balance_on)
          == (1000.0, date(2026, 9, 2), 870.0, date(2026, 11, 2)),
          (chk.opening_balance, chk.opening_on, chk.balance, chk.balance_on))
    row = next(a for a in books_service.bank_check(bbb, date(2026, 9, 30)) if a["name"] == chk.label)
    check("with October never uploaded, the lines do not add up", row["agrees"] is False
          and row["board"] == 916.0 and "870.00" in row["message"], row)
    statements.import_rows(chk, statements.parse(OCT))
    row = next(a for a in books_service.bank_check(bbb, date(2026, 10, 31)) if a["name"] == chk.label)
    check("once it is, they agree to the cent", row["agrees"] is True and row["board"] == 870.0, row)

print("2. A statement is due")
with application.app_context():
    cardc = db.session.get(BankConnection, ids["card"])
    due = statements.statements_due(today=date(2026, 11, 4))
    check("a source never uploaded is due", [d["connection"].id for d in due] == [ids["card"]], due)
    row = next(a for a in books_service.bank_check(db.session.get(Business, ids["bbb"]), date(2026, 10, 31))
               if a["name"] == "Freedom")
    check("and the month's check says no statement reaches it", row["agrees"] is False, row)
c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True
page = c.get("/admin/attention/").get_data(as_text=True)
check("Needs attention names it", "statement to upload" in page and "Freedom" in page)
with application.app_context():
    statements.import_rows(db.session.get(BankConnection, ids["card"]), statements.parse(
        "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
        "10/20/2026,10/21/2026,GITHUB INC,Shopping,Sale,-20.00,\n"
        "10/03/2026,10/04/2026,CHUYS,Food & Drink,Sale,-18.40,\n"))
    line = BankTransaction.query.filter_by(connection_id=ids["card"], counterparty="CHUYS").first()
    check("the card's category is on its line", line.merchant_category == "Food & Drink")
    check("an upload after the month ended clears it", statements.statements_due(today=date(2026, 11, 4)) == [])
    row = next(a for a in books_service.bank_check(db.session.get(Business, ids["bbb"]), date(2026, 10, 31))
               if a["name"] == "Freedom")
    check("a card with no balance agrees once its uploads reach the month", row["agrees"] is True, row)


print("3. Chase's alert emails")


def alert(subject, body, key, sender="Chase <no.reply.alerts@chase.com>"):
    m = EmailMessage()
    m["From"], m["Subject"], m["Message-ID"] = sender, subject, key
    m["Date"] = "Mon, 02 Nov 2026 15:00:00 -0600"
    m.set_content(body)
    return m.as_bytes()


NEW = ("You made a $12.34 transaction with STARBUCKS",
       "Account\nChase Freedom (...1234)\nDate\nNov 2, 2026 at 3:00 PM ET\nMerchant\nSTARBUCKS\nAmount\n$12.34")
OLD = ("Your Single Transaction Alert from Chase",
       "This is an Alert to help you manage your credit card account ending in 1234.\n"
       "A charge of ($USD) 45.00 at AMAZON.COM has been authorized on Nov 3, 2026 at 1:00 PM ET.")
got = statements.parse_alert(alert(*NEW, "<a1@chase>"))
check("the current format", got and got["amount"] == -12.34 and got["merchant"] == "STARBUCKS"
      and got["last_four"] == "1234" and got["date"] == date(2026, 11, 2), got)
got = statements.parse_alert(alert(*OLD, "<a2@chase>"))
check("the older format", got and got["amount"] == -45.0 and got["merchant"] == "AMAZON.COM"
      and got["last_four"] == "1234" and got["date"] == date(2026, 11, 3), got)
check("a statement notice is not a transaction",
      statements.parse_alert(alert("Your statement is ready", "Your balance is $500.00", "<s@chase>")) is None)
check("mail that is not from Chase is ignored",
      statements.parse_alert(alert(*NEW, "<x@phish>", sender="Chase <alerts@chase-secure.com>")) is None)

MAIL = [alert("You made a $20.00 transaction with GITHUB INC",
              "Chase Freedom (...1234)\nDate\nOct 20, 2026 at 9:00 AM ET\nMerchant\nGITHUB INC\nAmount\n$20.00",
              "<a0@chase>"),
        alert(*NEW, "<a1@chase>"),
        alert("You made a $50.00 transaction with CHUYS",
              "Chase Freedom (...1234)\nDate\nNov 2, 2026 at 8:00 PM ET\nMerchant\nCHUYS\nAmount\n$50.00",
              "<a3@chase>")]
with application.app_context():
    note = statements.sync_alerts(fetcher=lambda box, since: iter(MAIL))
    card = db.session.get(BankConnection, ids["card"])
    check("the card is learned from the charge already on its statement", card.last_four == "1234", card.last_four)
    first = CardAlert.query.filter_by(message_key="<a0@chase>").first()
    check("and that alert points at the existing line, writing nothing",
          first.line_id is not None and db.session.get(BankTransaction, first.line_id).kind == "statement")
    star = BankTransaction.query.filter_by(connection_id=ids["card"], kind="alert", counterparty="STARBUCKS").first()
    check("a new charge is a provisional line", star is not None and star.status == "sent", note)
    check("booked at once by its rule, paid by the card's owner",
          star.disposition == "expense" and star.expense_id
          and db.session.get(Expense, star.expense_id).paid_by == "Michael Bean")
    star_id, star_expense = star.id, star.expense_id
    statements.sync_alerts(fetcher=lambda box, since: iter(MAIL))
    check("reading the same mail again stores nothing twice", CardAlert.query.count() == 3)
    chuys_alert = BankTransaction.query.filter_by(connection_id=ids["card"], kind="alert", counterparty="CHUYS").first()
    chuys_id = chuys_alert.id
    # The statement: Starbucks posted a day later, Chuy's with a tip on.
    counts = statements.import_rows(card, statements.parse(
        "Transaction Date,Post Date,Description,Category,Type,Amount,Memo\n"
        "11/15/2026,11/16/2026,SENTRY,Software,Sale,-26.00,\n"
        "11/03/2026,11/04/2026,STARBUCKS STORE 0042,Food & Drink,Sale,-12.34,\n"
        "11/02/2026,11/03/2026,CHUYS,Food & Drink,Sale,-60.00,\n"
        "11/01/2026,11/02/2026,DELTA,Travel,Sale,-5.00,\n"))
    star = db.session.get(BankTransaction, star_id)
    check("the statement folds over the alert's line", counts["folded_alerts"] == 1 and star.kind == "statement"
          and star.counterparty == "STARBUCKS STORE 0042" and star.occurred_on == date(2026, 11, 3), counts)
    check("keeping the one expense", star.expense_id == star_expense
          and Expense.query.filter(Expense.description.like("Starbucks%")).count() == 1)
    gone = db.session.get(BankTransaction, chuys_id)
    check("an alert the statement did not confirm is cancelled", gone.status == "cancelled"
          and gone.disposition == "void" and gone.expense_id is None, (gone.status, gone.disposition))
    check("and the statement's own charge stands",
          BankTransaction.query.filter_by(connection_id=ids["card"], amount=-60.0, kind="statement").count() == 1)

for path in ("statements.py", "books_upkeep.py"):
    check(f"no em dash in {path}", "—" not in (ROOT / path).read_text(encoding="utf-8"))

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
