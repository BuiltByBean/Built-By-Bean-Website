# -*- coding: utf-8 -*-
"""Every money page tells the same story about the same company.

Michael, 2026-11-03: "does my finances every page settle with each from a
numbers standpoint?" They did not. The finance dashboard counted EntertainHQ's
expenses as Built by Bean's, the Taxes page took its profit from Stripe's
payouts (sales tax in, Stripe's fee taken off twice) less every company's
expenses, and the Books read the local invoice rows while the dashboard read
Stripe live. Proves:

  1. The dashboard's Total Expenses is Built by Bean's family alone (its DBA
     in, EntertainHQ out), and a client's expense column the same.
  2. The Taxes page's profit is the Books page's net for the year, to the
     cent, with sales tax out and Stripe's fee counted once.
  3. Built by Bean's books plus EntertainHQ's are the Expenses page's total.
  4. EntertainHQ's tile on Businesses reads its Stripe income, not "App not
     reporting".

Run: python tools/test_one_set_of_figures.py
"""
import os
import pathlib
import re
import sys
import tempfile
from datetime import date, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-figures-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("STRIPE_SECRET_KEY", None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, Business, Client, Expense, Invoice, StripeActivity, User)  # noqa: E402
import books_service  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []
YEAR = date.today().year


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def money(text, label):
    """The first dollar figure after `label` in the page's text."""
    flat = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))
    m = re.search(re.escape(label) + r".{0,200}?(-?)\$([\d,]+\.\d\d)", flat)
    return None if not m else float(m.group(2).replace(",", "")) * (-1 if m.group(1) else 1)


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board")
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="ehq", sales_source="hub",
                   stripe_key="rk_test_x")
    db.session.add_all([boss, bbb, ehq])
    db.session.flush()
    dd = Business(name="Data Dungeon", slug="dd", parent_id=bbb.id)
    client = Client(name="Kenali Kendrick")
    db.session.add_all([dd, client])
    db.session.flush()
    db.session.add_all([
        # $1,000 of work with $66 of sales tax on top, and a catch-up bill.
        Invoice(client_id=client.id, status="paid", total=1066, tax=66, amount_paid=1066,
                paid_at=datetime(YEAR, 2, 3)),
        Invoice(client_id=client.id, status="paid", total=500, tax=0, amount_paid=500,
                paid_at=datetime(YEAR, 5, 3)),
        Invoice(client_id=client.id, status="paid", total=66, tax=0, amount_paid=66,
                paid_at=datetime(YEAR, 5, 4), sales_tax_catchup=True),
        Expense(amount=100.0, description="Railway", category="hosting", date=date(YEAR, 2, 5),
                business_id=bbb.id, client_id=client.id),
        Expense(amount=31.0, description="Stripe fees", category="bank_fees", date=date(YEAR, 2, 28),
                business_id=bbb.id),
        Expense(amount=9.0, description="Data Dungeon domain", category="domain", date=date(YEAR, 5, 5),
                business_id=dd.id),
        # EntertainHQ's own costs, tied to the same client as its product.
        Expense(amount=619.78, description="Google Workspace", category="software", date=date(YEAR, 5, 6),
                business_id=ehq.id, client_id=client.id),
        StripeActivity(business_id=ehq.id, external_id="txn_1", kind="charge", category="charge", amount=250.0, fee=7.55,
                       net=242.45, created_on=date(YEAR, 5, 9), description="Booking"),
    ])
    db.session.commit()
    ids = {"boss": boss.id, "bbb": bbb.id}
    bbb_year = books_service.summarize(bbb, date(YEAR, 1, 1), date(YEAR + 1, 1, 1))

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True

print("1. The finance dashboard is Built by Bean's")
dash = c.get("/admin/finances").get_data(as_text=True)
check("Total Expenses is Built by Bean and its DBA, not EntertainHQ",
      money(dash, "Total Expenses") == 140.0, money(dash, "Total Expenses"))
check("the client's expense column leaves EntertainHQ's spending out",
      "$619.78" not in dash and "$719.78" not in dash)

print("2. The Taxes page's profit is the Books page's net")
taxes = c.get("/admin/taxes/").get_data(as_text=True)
check("books: $1,500 earned (tax and catch-up out) less $140 spent",
      bbb_year["income_total"] == 1500.0 and bbb_year["expense_total"] == 140.0, bbb_year["net"])
check("Taxes shows the same profit to the cent",
      money(taxes, "Business profit") == bbb_year["net"], money(taxes, "Business profit"))
check("and says what it is made of", "$1,500.00 earned" in re.sub(r"\s+", " ", taxes))

print("3. The companies add up to the Expenses page")
with application.app_context():
    ehq_row = Business.query.filter_by(slug="ehq").one()
    ehq_year = books_service.summarize(ehq_row, date(YEAR, 1, 1), date(YEAR + 1, 1, 1))
exp = c.get("/admin/expenses").get_data(as_text=True)
check("Built by Bean plus EntertainHQ is the Expenses total",
      round(bbb_year["expense_total"] + ehq_year["expense_total"], 2) == money(exp, "Total out"),
      (bbb_year["expense_total"], ehq_year["expense_total"], money(exp, "Total out")))

print("4. EntertainHQ's tile reads its Stripe")
biz = re.sub(r"\s+", " ", c.get("/admin/businesses").get_data(as_text=True))
check("EntertainHQ's lifetime revenue is its Stripe sales",
      "$250.00" in biz and biz.count("App not reporting") == 0, biz.count("App not reporting"))

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
