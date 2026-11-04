# -*- coding: utf-8 -*-
"""Books, the money's front door (docs/finances_plan.md items 1, 2, 7, 10, 11).

What is proved:

  1. Books opens on a company's Months (the Overview was retired into it the
     evening it shipped): one company and year at a time, its Income, Expenses and Net
     the Books' own figures to the cent, the tax tile, and a To do list whose
     every row is a link that lands where it is cleared (bank lines, missing
     receipts, a month to close). A GET changes nothing (no phase sync).
  2. Books is a tab per company with Months, Bank, Expenses, Receipts, Year
     report and Connections; the company row opens the same tab for the
     other company; a DBA's address opens its company.
  3. Bank lists only this company's lines; Tagged lists what a session
     logged that no line took, and Set aside takes one off.
  4. Expenses is this company's ledger only, filters apply to the tiles and
     rows together, and a bank row cannot be deleted.
  5. Adding an expense by hand: inside Books, with a company picker, and it
     lands in the company picked; a bank row's amount and date are not
     editable.
  6. Every old address lands: /admin/expenses (with its filters), /admin/bank/,
     /admin/books/?tab=..., /admin/books/receipts.
  7. CEO only: a member is refused every Finances page and never loops; the
     sidebar draws Finances for the CEO alone, in Michael's order.
  8. Financials by client on Clients (CEO only) and deadlines on Client support.

Run: python tools/test_finances_books.py
"""
import os
import pathlib
import re
import sys
import tempfile
from datetime import date, timedelta

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-finbooks-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ["GUIDANCE_API_KEY"] = "test-key"
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ.pop("STRIPE_SECRET_KEY", None)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, BankConnection, BankTransaction, Business, Client, Expense,  # noqa: E402
                    ExpenseTag, Project, User)
import books_service  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


today = date.today()
with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    hannah = User(username="hb", email="hb@example.test", first_name="Hannah", role="cmo")
    hannah.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board")
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="ehq", sales_source="hub")
    db.session.add_all([boss, hannah, bbb, ehq])
    db.session.flush()
    dd = Business(name="Data Dungeon", slug="dd", parent_id=bbb.id)
    kuper = Client(name="Cason Kuper")
    db.session.add_all([dd, kuper])
    db.session.flush()
    kp = Project(name="Kuper Plumbing", client_id=kuper.id, status="active", mvp_date=today + timedelta(days=9))
    db.session.add(kp)
    merc = BankConnection(business_id=bbb.id, token="t", label="Mercury")
    emerc = BankConnection(business_id=ehq.id, token="t", label="EHQ Mercury")
    db.session.add_all([merc, emerc])
    db.session.flush()
    first = today.replace(day=1)
    last_month = (first - timedelta(days=1)).replace(day=1)
    lines = [
        BankTransaction(connection_id=merc.id, business_id=bbb.id, external_id="b1", status="sent",
                        amount=-12.0, occurred_on=last_month + timedelta(days=3), counterparty="MYSTERY SHOP",
                        disposition="review"),
        BankTransaction(connection_id=emerc.id, business_id=ehq.id, external_id="e1", status="sent",
                        amount=-30.0, occurred_on=last_month + timedelta(days=4), counterparty="EHQ ONLY VENDOR",
                        disposition="review"),
    ]
    db.session.add_all(lines)
    db.session.flush()
    typed = Expense(amount=40.0, date=last_month + timedelta(days=5), business_id=bbb.id,
                    description="Cash for a domain", category="domain", client_id=kuper.id)
    dd_row = Expense(amount=7.5, date=last_month + timedelta(days=6), business_id=dd.id, description="Dungeon dice")
    ehq_row = Expense(amount=99.0, date=last_month + timedelta(days=7), business_id=ehq.id, description="EHQ thing")
    banked = Expense(amount=20.0, date=last_month + timedelta(days=8), business_id=bbb.id, description="Railway")
    db.session.add_all([typed, dd_row, ehq_row, banked])
    db.session.flush()
    bline = BankTransaction(connection_id=merc.id, business_id=bbb.id, external_id="b2", status="sent",
                            amount=-20.0, occurred_on=banked.date, counterparty="RAILWAY", disposition="expense",
                            expense_id=banked.id)
    db.session.add(bline)
    db.session.flush()
    banked.bank_line_id = bline.id
    tag = ExpenseTag(amount=15.0, occurred_on=today - timedelta(days=12), vendor="Somewhere", business_id=bbb.id)
    db.session.add(tag)
    db.session.commit()
    ids = dict(boss=boss.id, hannah=hannah.id, bbb=bbb.id, ehq=ehq.id, dd=dd.id, kuper=kuper.id, kp=kp.id,
               typed=typed.id, banked=banked.id, tag=tag.id, b1=lines[0].id, e1=lines[1].id)
    s = books_service.summarize(bbb, date(today.year, 1, 1), date(today.year + 1, 1, 1))
    year_net, year_exp = s["net"], s["expense_total"]


def client_for(user_id):
    c = application.test_client()
    with c.session_transaction() as sess:
        sess["_user_id"] = str(user_id)
        sess["_fresh"] = True
    return c


c = client_for(ids["boss"])
m = client_for(ids["hannah"])


def page(path, who=c):
    r = who.get(path)
    return r.status_code, r.get_data(as_text=True), r


print("1. Books is the front door (Michael retired the Overview, 2026-11-04)")
code, _, r = page("/admin/finances")
check("the old Overview address lands on the home company's Books",
      code == 301 and r.location.endswith(f"/admin/books/{ids['bbb']}/"), (code, r.location))
code, _, r = page(f"/admin/finances?business={ids['ehq']}&year={today.year}")
check("with its company and year", code == 301 and f"/admin/books/{ids['ehq']}/?year={today.year}" in r.location,
      r.location)
code, html, _ = page(f"/admin/books/{ids['bbb']}/")
check("Months opens for the CEO", code == 200, code)
check("its Expenses are the Books' to the cent", f"${year_exp:,.2f}" in html, year_exp)
check("and its Net", f"${abs(year_net):,.2f}" in html)
check("with the estimated tax beside them", "Estimated tax" in html)
todo = re.findall(r'data-todo="(\w+)"', html)
check("To do names the bank lines to sort and the missing receipts, and not the months listed below it",
      "bank" in todo and "receipt" in todo and "month" not in todo, todo)
check("each To do row is a link to where it is cleared",
      f'/admin/books/{ids["bbb"]}/bank' in html and f'/admin/books/{ids["bbb"]}/receipts' in html)
check("financials by client and deadlines are not on it",
      "Financials by client" not in html and "Kuper Plumbing delivery" not in html)
code, html, _ = page(f"/admin/books/{ids['ehq']}/")
check("EntertainHQ's opens on its own", code == 200 and "EntertainHQ LLC" in html)
check("and its To do is its own", "1 bank line to sort" in html, re.findall(r"\d+ bank lines? to sort", html))
src = (ROOT / "pm" / "books_routes.py").read_text(encoding="utf-8")
body = src[src.index("def company(id):"):src.index("def bank(id):")]
check("a GET changes nothing: no phase sync on Months", "sync_project_phases(" not in body)

print("2. Books is a tab per company")
code, _, r = page("/admin/books/")
check("the front door opens the home company's Months", code == 301 and r.location.endswith(f"/admin/books/{ids['bbb']}/"),
      (code, r.location))
code, html, _ = page(f"/admin/books/{ids['bbb']}/")
check("Months opens", code == 200 and "Months" in html and "Owners" in html, code)
for tab in ("Bank", "Expenses", "Receipts", "Year report", "Connections"):
    check(f"with a {tab} tab", f">\n            {tab}" in html or f"{tab}\n" in html)
check("the company row opens the same tab for the other company",
      f'href="/admin/books/{ids["ehq"]}/?year=' in html, re.findall(r'href="/admin/books/\d+/[^"]*"', html)[:6])
code, _, r = page(f"/admin/books/{ids['dd']}/")
check("a DBA's address opens its company", code == 301 and f"/admin/books/{ids['bbb']}/" in r.location)
for sub in ("bank", "expenses", "receipts", "connections", f"year/{today.year}",
            f"month/{last_month:%Y-%m}"):
    code, html, _ = page(f"/admin/books/{ids['bbb']}/{sub}")
    check(f"/{sub} opens inside the hub", code == 200 and 'data-panel="books"' in html
          and 'data-keep="books-tabs"' in html, code)

print("3. Bank")
code, html, _ = page(f"/admin/books/{ids['bbb']}/bank")
check("lists this company's lines only", "MYSTERY SHOP" in html and "EHQ ONLY VENDOR" not in html)
check("no paid model press", "Ask Claude" not in html)
code, html, _ = page(f"/admin/books/{ids['ehq']}/bank")
check("and the other company's its own", "EHQ ONLY VENDOR" in html and "MYSTERY SHOP" not in html)
code, html, _ = page(f"/admin/books/{ids['bbb']}/bank?view=tags")
check("Tagged lists the logged charge no line took", "Somewhere" in html and "$15.00" in html)
r = c.post(f"/admin/books/tags/{ids['tag']}/dismiss", data={"next": f"/admin/books/{ids['bbb']}/bank?view=tags"})
with application.app_context():
    check("Set aside takes it off", db.session.get(ExpenseTag, ids["tag"]).dismissed_at is not None
          and r.status_code == 302)

print("4. Expenses")
code, html, _ = page(f"/admin/books/{ids['bbb']}/expenses")
check("is this company's ledger, its DBA's included",
      "Cash for a domain" in html and "Dungeon dice" in html and "EHQ thing" not in html)
check("Total out is the company's, not everybody's", "$67.50" in html, re.findall(r"\$[\d,]+\.\d\d", html)[:6])
code, html, _ = page(f"/admin/books/{ids['bbb']}/expenses?category=domain")
check("a filter moves the tiles with the rows", "$40.00" in html and "Dungeon dice" not in html)
r = c.post(f"/admin/expenses/{ids['banked']}/delete", data={"next": f"/admin/books/{ids['bbb']}/expenses"})
with application.app_context():
    check("a bank row cannot be deleted", db.session.get(Expense, ids["banked"]) is not None)

print("5. Adding an expense by hand")
code, html, _ = page(f"/admin/expenses/new?business_id={ids['ehq']}")
check("opens inside Books, on the company asked for", code == 200 and 'data-panel="books"' in html
      and "EntertainHQ LLC" in html, code)
check("with a company picker, DBAs included", 'name="business_id"' in html and "Data Dungeon" in html)
check("and no recurring toggle", "Recurring" not in html and "frequency" not in html)
r = c.post("/admin/expenses/new", data={"business_id": ids["ehq"], "client_id": 0, "project_id": 0,
                                         "ticket_id": 0, "amount": "12.34", "category": "misc",
                                         "date": today.isoformat(), "description": "Cash at the print shop"})
with application.app_context():
    row = Expense.query.filter_by(description="Cash at the print shop").first()
    check("it lands in the company picked", row is not None and row.business_id == ids["ehq"], r.status_code)
    check("and the press returns to that company's Expenses",
          r.status_code == 302 and "business_id=" in r.location or "/books/" in r.location, r.location)
code, html, _ = page(f"/admin/expenses/{ids['banked']}/edit")
check("a bank row's amount is shown, not offered", code == 200 and "from the bank" in html
      and 'name="amount" value="20.0"' in html.replace("'", '"'))
c.post(f"/admin/expenses/{ids['banked']}/edit", data={"business_id": ids["bbb"], "client_id": ids["kuper"],
                                                      "project_id": 0, "ticket_id": 0, "amount": "999",
                                                      "category": "hosting", "date": "2020-01-01",
                                                      "description": "Railway"})
with application.app_context():
    row = db.session.get(Expense, ids["banked"])
    check("and saving it keeps the bank's amount and date", row.amount == 20.0 and row.date.year == today.year
          and row.client_id == ids["kuper"], (row.amount, row.date))

print("6. Every old address lands")
for old, want in ((f"/admin/expenses?business_id={ids['ehq']}&category=domain",
                   f"/admin/books/{ids['ehq']}/expenses?category=domain"),
                  (f"/admin/expenses?project_id={ids['kp']}", f"/admin/books/{ids['bbb']}/expenses?project_id={ids['kp']}"),
                  ("/admin/bank/", f"/admin/books/{ids['bbb']}/bank"),
                  ("/admin/bank/?view=all", f"/admin/books/{ids['bbb']}/bank?view=all"),
                  ("/admin/books/?tab=connections", f"/admin/books/{ids['bbb']}/connections"),
                  (f"/admin/books/?tab={ids['ehq']}", f"/admin/books/{ids['ehq']}/"),
                  ("/admin/books/?tab=tags", f"/admin/books/{ids['bbb']}/bank?view=tags"),
                  ("/admin/books/receipts?view=unmatched", f"/admin/books/{ids['bbb']}/receipts?view=unmatched")):
    r = c.get(old)
    check(f"{old} lands", r.status_code == 301 and r.location.endswith(want), (r.status_code, r.location))

print("7. CEO only")
for path in ("/admin/finances", f"/admin/books/{ids['bbb']}/", f"/admin/books/{ids['bbb']}/bank",
             f"/admin/books/{ids['bbb']}/expenses", "/admin/expenses/new", "/admin/bank/",
             f"/admin/expenses/{ids['typed']}/edit"):
    r = m.get(path)
    check(f"a member is refused {path}", r.status_code == 302 and "/admin/finances" not in r.location
          and "/books" not in r.location, (r.status_code, r.location))
r = m.get("/admin", follow_redirects=True)
check("and lands on the board, not in a loop", r.status_code == 200)
r = m.post(f"/admin/expenses/{ids['typed']}/delete")
with application.app_context():
    check("a member's delete is refused", db.session.get(Expense, ids["typed"]) is not None)
html = m.get("/admin/clients").get_data(as_text=True)
check("the sidebar draws no Finances for a member", 'data-group="finances"' not in html and "Invoicing" not in html)
html = c.get("/admin/clients").get_data(as_text=True)
nav = html[html.index('data-group="finances"'):html.index('data-group="finances"') + 4000]
order = [w for w in ("Books", "Taxes", "Invoicing", "Hosting") if w in nav]
check("the CEO's Finances is Books, Taxes, Invoicing, Hosting",
      order == ["Books", "Taxes", "Invoicing", "Hosting"]
      and nav.index("Books") < nav.index("Taxes") < nav.index("Invoicing") < nav.index("Hosting"),
      order)
check("and no Expenses or Dashboard link", "/admin/expenses\"" not in nav and "Dashboard" not in nav)

print("8. Where the Dashboard's other parts went")
check("Clients carries each client's money for the CEO (the typed $40 and the bank $20 put on Kuper)", "Spent on" in html and "$60.00" in html)
check("but not for a member", "Spent on" not in m.get("/admin/clients").get_data(as_text=True))
html = c.get("/admin/tickets").get_data(as_text=True)
check("Client support lists the deliveries due", "Kuper Plumbing delivery" in html)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
