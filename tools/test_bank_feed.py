# -*- coding: utf-8 -*-
"""Each business's books, built from its bank, with nothing counted twice.

Michael, 2026-11-03: expense tracking "automated to like the highest
degree ... broken out specifically by business as well, so that way I'm not
accidentally double counting." This proves the parts that would quietly
come apart:

  1. Every expense lands in a business's books, whichever path made it, and
     a recurring child stays in its parent's.
  2. A night's read of a Mercury account: a vendor with a rule is booked, an
     unknown one waits for review, a transfer and a payout are never
     expenses, Mercury's own fee is, a pending charge books nothing until it
     settles, a settled one follows the bank's final amount, a cancelled one
     takes its expense away, and a vendor refund is a negative expense.
  3. A vendor whose sync already books Built by Bean's money is "covered"
     there and is a plain expense in EntertainHQ's books.
  4. An expense somebody already typed for the same charge is adopted, not
     doubled.
  5. Settling one line with "remember" settles every line like it, for
     good, in the business it names.
  6. Claude's suggestion is stored and one press accepts them all.
  7. The pages: the review list, the bank card on a business, the expense
     list's business filter, and a refused token said plainly.
  8. The guidance door files an expense under the business it is told.

Run: python tools/test_bank_feed.py
"""
import json
import os
import pathlib
import sys
import tempfile
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-bank-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["GUIDANCE_API_KEY"] = "test-key"
os.environ.pop("ANTHROPIC_API_KEY", None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, BankConnection, BankTransaction, Business, Client, Expense,  # noqa: E402
                    Project, ServiceProvider, User, VendorRule)
import bank_feed  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def tx(id_, amount, name, kind="debitCardTransaction", status="sent", day="2026-10-05", desc=""):
    return {"id": id_, "amount": amount, "counterpartyName": name, "kind": kind,
            "status": status, "createdAt": f"{day}T10:00:00Z",
            "postedAt": f"{day}T12:00:00Z" if status == "sent" else None,
            "accountId": "acct-1", "bankDescription": desc, "dashboardLink": "https://x"}


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board")
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="ehq", sales_source="hub")
    db.session.add_all([boss, bbb, ehq])
    db.session.flush()
    dd = Business(name="Data Dungeon", slug="dd", parent_id=bbb.id)
    client = Client(name="Kenali Kendrick")
    db.session.add_all([dd, client])
    db.session.flush()
    proj = Project(name="Talent Booker", client_id=client.id)
    railway = ServiceProvider(name="railway", display_name="Railway", is_active=True)
    db.session.add_all([proj, railway])
    db.session.commit()
    ids = {"bbb": bbb.id, "ehq": ehq.id, "dd": dd.id, "boss": boss.id, "proj": proj.id,
           "railway": railway.id}

    print("1. Every expense is in somebody's books")
    e = Expense(amount=5, description="typed", date=date(2026, 10, 1))
    db.session.add(e)
    db.session.commit()
    check("an expense with no business is Built by Bean's", e.business_id == ids["bbb"], e.business_id)
    parent = Expense(amount=9, description="EHQ monthly", date=date(2026, 9, 1), business_id=ids["ehq"],
                     is_recurring=True, frequency="monthly")
    db.session.add(parent)
    db.session.commit()
    child = Expense(amount=9, description="EHQ monthly", date=date(2026, 10, 1), parent_expense_id=parent.id)
    db.session.add(child)
    db.session.commit()
    check("a recurring child stays in its parent's books", child.business_id == ids["ehq"], child.business_id)
    db.session.delete(e)
    db.session.commit()

    print("2. A night's read of a Mercury account")
    bank_feed.remember("RAILWAY", "covered", vendor="Railway", category="hosting",
                       provider_id=ids["railway"])
    bank_feed.remember("OPENAI", "expense", vendor="OpenAI", category="ai_services")
    bank_feed.remember("MERCURY IO", "transfer", vendor="Card payoff")
    db.session.commit()
    # Somebody typed the GitHub charge already, as a session would log it.
    typed = Expense(amount=4.00, description="GitHub Pro (logged from Piped)", date=date(2026, 10, 3),
                    business_id=ids["bbb"], category="software")
    db.session.add(typed)
    db.session.commit()
    typed_id = typed.id

    conn = BankConnection(business_id=ids["bbb"], token="secret-token:x", synced_from=date(2026, 4, 1))
    db.session.add(conn)
    db.session.commit()
    night1 = [
        tx("t1", -20.00, "Railway Corporation"),
        tx("t2", -12.00, "OpenAI", status="pending"),
        tx("t3", -4.00, "GitHub, Inc.", day="2026-10-05"),
        tx("t4", -7.50, "GitHub, Inc.", day="2026-11-05"),
        tx("t5", 1500.00, "Stripe", kind="externalTransfer"),
        tx("t6", -300.00, "Mercury IO", kind="other"),
        tx("t7", -30.00, "Mercury", kind="wireFee"),
        tx("t8", -55.00, "Delta Airlines"),
        tx("t9", -10.00, "Savings", kind="internalTransfer"),
        tx("t10", 3.00, "OpenAI", kind="debitCardCredit"),
    ]
    counts = bank_feed.sync_connection(conn, fetch=lambda tok, start: iter(night1),
                                       accounts={"acct-1": "Checking"})
    lines = {l.external_id: l for l in BankTransaction.query.all()}
    check("all ten lines read", counts.get("read") == 10, counts)
    check("Railway is covered by its own sync (no expense)",
          lines["t1"].disposition == "covered" and lines["t1"].expense_id is None)
    check("a pending OpenAI charge books nothing yet",
          lines["t2"].disposition == "expense" and lines["t2"].expense_id is None)
    check("an unknown vendor waits for review",
          lines["t4"].disposition == "review" and lines["t8"].disposition == "review")
    check("the typed GitHub charge is adopted, not doubled",
          lines["t3"].disposition == "review" or lines["t3"].expense_id in (None, typed_id))
    check("a Stripe payout in is the company's own money moving, never income or an expense",
          lines["t5"].disposition == "transfer" and lines["t5"].expense_id is None)
    check("a card payoff with a rule is a transfer", lines["t6"].disposition == "transfer")
    check("Mercury's own fee is a bank-fee expense",
          lines["t7"].disposition == "expense" and lines["t7"].expense.category == "bank_fees"
          and lines["t7"].expense.amount == 30.0)
    check("an internal transfer is a transfer", lines["t9"].disposition == "transfer")
    check("money back from a known vendor is a negative expense",
          lines["t10"].expense is not None and lines["t10"].expense.amount == -3.0,
          lines["t10"].expense and lines["t10"].expense.amount)
    check("the connection says what it read",
          conn.last_ok and "10 lines read" in conn.last_note, conn.last_note)

    night2 = [tx("t2", -12.37, "OpenAI", status="sent", day="2026-10-06"),
              tx("t8", -55.00, "Delta Airlines", status="cancelled")]
    bank_feed.sync_connection(conn, fetch=lambda tok, start: iter(night2), accounts={"acct-1": "Checking"})
    l2 = BankTransaction.query.filter_by(external_id="t2").one()
    check("the settled charge books its final amount",
          l2.expense is not None and l2.expense.amount == 12.37 and l2.expense.business_id == ids["bbb"]
          and l2.expense.category == "ai_services", l2.expense and l2.expense.amount)
    check("a cancelled line is void", BankTransaction.query.filter_by(external_id="t8").one().disposition == "void")
    check("reading the same night again adds no line",
          BankTransaction.query.count() == 10, BankTransaction.query.count())

    print("3. Covered is only for the books the sync writes")
    ehq_conn = BankConnection(business_id=ids["ehq"], token="secret-token:y")
    db.session.add(ehq_conn)
    db.session.commit()
    bank_feed.sync_connection(ehq_conn, fetch=lambda tok, start: iter([tx("e1", -42.48, "RAILWAY APP")]),
                              accounts={})
    e1 = BankTransaction.query.filter_by(external_id="e1").one()
    check("EntertainHQ's Railway charge is EntertainHQ's expense",
          e1.disposition == "expense" and e1.expense and e1.expense.business_id == ids["ehq"],
          (e1.disposition, e1.expense and e1.expense.business_id))

    print("4. Settling a line settles every line like it")
    t4 = BankTransaction.query.filter_by(external_id="t4").one()
    settled = bank_feed.decide(t4, "expense", business_id=ids["dd"], category="software",
                               vendor="GitHub", pattern="GitHub, Inc.", keep=True)
    t3 = BankTransaction.query.filter_by(external_id="t3").one()
    t4 = BankTransaction.query.filter_by(external_id="t4").one()
    check("a rule is written", VendorRule.query.filter_by(pattern="GITHUB INC").first() is not None)
    check("the line is booked in the business named",
          t4.expense and t4.expense.business_id == ids["dd"] and t4.expense.amount == 7.5)
    check("and the other GitHub line settled with it", settled >= 1 and t3.disposition == "expense", settled)
    check("which adopted the typed expense instead of doubling it",
          t3.expense_id == typed_id and Expense.query.filter(Expense.amount == 4.0).count() == 1,
          (t3.expense_id, typed_id))
    nxt = [tx("t11", -7.50, "GITHUB, INC.", day="2026-12-05")]
    bank_feed.sync_connection(conn, fetch=lambda tok, start: iter(nxt), accounts={})
    t11 = BankTransaction.query.filter_by(external_id="t11").one()
    check("next month's GitHub charge needs nobody",
          t11.disposition == "expense" and t11.expense and t11.expense.business_id == ids["dd"])

    print("5. Claude's suggestion, and accepting them")
    bank_feed.sync_connection(conn, fetch=lambda tok, start: iter([tx("t12", -19.0, "SENTRY.IO"),
                                                                    tx("t13", -19.0, "SENTRY.IO", day="2026-11-04")]),
                              accounts={})

    class Block:
        type = "text"

        def __init__(self, text):
            self.text = text

    class Msg:
        stop_reason = "end_turn"

        def __init__(self, data):
            self.content = [Block(json.dumps(data))]

    class Stream:
        def __init__(self, kw):
            self.kw = kw

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get_final_message(self):
            text = self.kw["messages"][0]["content"]
            got = [int(line.split(" | ")[0]) for line in text.split("THE LINES")[1].splitlines()[1:] if " | " in line]
            return Msg({"lines": [{"id": i, "disposition": "expense", "vendor": "Sentry", "pattern": "SENTRY",
                                   "business_id": ids["ehq"], "category": "software", "project_id": 0,
                                   "confidence": "high", "why": "Error monitoring"} for i in got]})

    class Messages:
        def stream(self, **kw):
            return Stream(kw)

    class Beta:
        messages = Messages()

    class Fake:
        beta = Beta()

    n = bank_feed.suggest(client=Fake())
    t12 = BankTransaction.query.filter_by(external_id="t12").one()
    check("waiting lines are given a suggestion", n >= 2 and t12.suggestion["vendor"] == "Sentry", n)

print("6. The pages")
c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True
page = c.get("/admin/bank/")
body = page.get_data(as_text=True)
check("the review list renders", page.status_code == 200, page.status_code)
check("it shows the suggestion and the accept press", "Error monitoring" in body and "Accept" in body)
check("no em dashes", "\u2014" not in body)
r = c.post("/admin/bank/accept-suggested", follow_redirects=False)
with application.app_context():
    t12 = BankTransaction.query.filter_by(external_id="t12").one()
    t13 = BankTransaction.query.filter_by(external_id="t13").one()
    check("accepting settles both Sentry lines in EntertainHQ's books",
          t12.expense and t13.expense and t12.expense.business_id == ids["ehq"]
          and t13.expense.business_id == ids["ehq"])
    check("and leaves nothing to sort but what nobody suggested",
          BankTransaction.query.filter_by(disposition="review").count() == 0,
          BankTransaction.query.filter_by(disposition="review").count())

biz = c.get(f"/admin/businesses/{ids['bbb']}").get_data(as_text=True)
check("the business page carries its bank", 'id="bank"' in biz and "Read now" in biz and "Checking" in biz)
ehq_page = c.get(f"/admin/businesses/{ids['ehq']}").get_data(as_text=True)
check("its token is never printed", "secret-token" not in biz and "secret-token" not in ehq_page)

orig = bank_feed.mercury_accounts


def refuse(token):
    raise bank_feed.BankError("Mercury refused the token (401). Make a new read only token.", 401)


bank_feed.mercury_accounts = refuse
r = c.post("/admin/bank/connections", data={"business_id": ids["dd"], "token": "bad"},
           follow_redirects=True)
bank_feed.mercury_accounts = orig
check("a refused token is said plainly and nothing is kept",
      "refused the token" in r.get_data(as_text=True))
with application.app_context():
    check("no connection was made for it", BankConnection.query.filter_by(business_id=ids["dd"]).count() == 0)

ledger = c.get(f"/admin/expenses?business_id={ids['ehq']}").get_data(as_text=True)
check("the expense list filters to one business",
      "Every business" in ledger and "Sentry" in ledger and "OpenAI" not in ledger)
mine = c.get(f"/admin/expenses?business_id={ids['bbb']}").get_data(as_text=True)
check("and a company's books include its DBA's", "GitHub" in mine and "Sentry" not in mine)

print("7. The guidance door names the books")
r = c.post("/api/guidance/expenses", headers={"Authorization": "Bearer test-key"},
           json={"amount": 12.5, "description": "entertainhq.com renewal", "business": "EntertainHQ",
                 "date": "2026-10-09", "source": "test"})
with application.app_context():
    got = db.session.get(Expense, r.get_json()["id"])
    check("a logged expense lands in the business named", got.business_id == ids["ehq"], got.business_id)
r = c.post("/api/guidance/expenses", headers={"Authorization": "Bearer test-key"},
           json={"amount": 1, "description": "x", "business": "Nobody Inc", "source": "test"})
check("an unknown business is refused", r.status_code == 400)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
