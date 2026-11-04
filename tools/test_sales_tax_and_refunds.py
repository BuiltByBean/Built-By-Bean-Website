# -*- coding: utf-8 -*-
"""Sales tax comes off once, and a refund is money that went back.

Michael, 2026-11-03: "the total paid is higher than my income, what gives?" The
gap was sales tax, and Books was right to leave it out. Reconciling it found two
faults underneath, both in figures every money page reads:

  1. Income leaves sales tax out, and the payment to the Comptroller was ALSO an
     expense, so the tax came off the profit twice: $996.60 of the $1,193.22
     paid on 2026-11-02.
  2. Stripe leaves a refunded invoice "paid" with amount_paid untouched, so three
     refunded $1.99 charges counted as income and as money in.

Proves:

  1. A return's payment splits into tax and cost, to the cent, with the two
     returns Built by Bean really filed.
  2. Nothing that matches a charge is thrown by the split: a bank line still
     adopts it and rereads leave it alone, an owner still put the whole charge
     in, and a receipt still finds it.
  3. A return and its charge can arrive in either order, and taking the return
     away puts the charge back. A franchise tax payment is never taken for one.
  4. A company whose income is gross keeps its payment as a whole expense.
  5. Refunds are read beside the invoices, by either way Stripe links them, on
     the day they went back, in proportion when the invoice carried tax.
  6. Total Paid less the sales tax shown under it IS the Books page's income.
  7. The migration fixes what is there, twice over, and comes back exactly.

Run: python tools/test_sales_tax_and_refunds.py
"""
import importlib.util
import os
import pathlib
import re
import sys
import tempfile
from datetime import date, datetime, timezone
from types import SimpleNamespace as NS

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-sales-tax-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("STRIPE_SECRET_KEY", None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import stripe  # noqa: E402

from app import create_app  # noqa: E402
from models import (db, BankConnection, BankTransaction, Business, Client, Expense,  # noqa: E402
                    Invoice, SalesTaxFiling, User)
import bank_feed  # noqa: E402
import books_service  # noqa: E402
import receipts_service  # noqa: E402
import sales_tax  # noqa: E402
import statements  # noqa: E402
import stripe_service  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []
# Last year, because a fixture must never pin a date still in the future.
YEAR = date.today().year - 1
START, END = date(YEAR, 1, 1), date(YEAR + 1, 1, 1)


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail != "" and not cond else ""))
    if not cond:
        FAIL.append(name)


def flat(html):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def money(text, label):
    m = re.search(re.escape(label) + r".{0,200}?(-?)\$([\d,]+\.\d\d)", text)
    return None if not m else float(m.group(2).replace(",", "")) * (-1 if m.group(1) else 1)


def ts(month, day):
    return int(datetime(YEAR, month, day, 12, tzinfo=timezone.utc).timestamp())


# ── A fake Stripe in the shapes the live API sends ─────────────────────────
def invoice(id, total, month, day, *, tax=0.0, status="paid", customer=("cus_k", "Kenali Kendrick"),
            catchup=False, lines=()):
    cents = round(total * 100)
    return NS(id=id, number=id.upper(), status=status, total=cents,
              total_excluding_tax=cents - round(tax * 100),
              amount_due=0 if status == "paid" else cents,
              amount_paid=cents if status == "paid" else 0,
              created=ts(month, day), due_date=None,
              customer=NS(id=customer[0], name=customer[1], deleted=False),
              status_transitions=NS(paid_at=ts(month, day) if status == "paid" else None,
                                    finalized_at=ts(month, day)),
              metadata=NS(bbb_sales_tax="catchup") if catchup else NS(),
              lines=NS(data=[NS(description=d, amount=round(a * 100)) for d, a in lines]),
              description=None, hosted_invoice_url=None, invoice_pdf=None)


INVOICES = [
    invoice("in_work", 1500.00, 4, 9),
    invoice("in_taxed", 1599.00, 11, 3, tax=99.00),
    invoice("in_back_k", 699.60, 10, 28, catchup=True),
    invoice("in_back_c", 402.60, 11, 3, catchup=True, customer=("cus_c", "Cason Kuper")),
    invoice("in_sub_1", 1.99, 7, 24, customer=("cus_e", "Ethan Lane"),
            lines=[("Monthly hosting", 1.99)]),
    invoice("in_sub_2", 1.99, 9, 24, customer=("cus_e", "Ethan Lane")),
    invoice("in_half", 106.60, 5, 1, tax=6.60),
    invoice("in_open", 50.00, 9, 1, status="open", customer=("cus_c", "Cason Kuper")),
    invoice("in_stray", 5.00, 9, 2, status="open", customer=("cus_x", "Nobody Here")),
]
REFUNDS = [
    # The way the current API answers: no `invoice` on the charge, so the
    # road to the invoice is the payment behind it.
    NS(id="re_1", status="succeeded", amount=199, created=ts(8, 3),
       charge=NS(payment_intent="pi_sub_1"), payment_intent=None),
    # The way older versions answer: it says so on the charge.
    NS(id="re_2", status="succeeded", amount=199, created=ts(10, 2),
       charge=NS(invoice="in_sub_2"), payment_intent=None),
    # Half of an invoice that carried tax gives half the tax back with it.
    NS(id="re_3", status="succeeded", amount=5330, created=ts(6, 1),
       charge=NS(payment_intent="pi_half"), payment_intent=None),
    # One that failed gave nothing back.
    NS(id="re_4", status="failed", amount=99999, created=ts(6, 2),
       charge=NS(invoice="in_work"), payment_intent=None),
    # A refund on a charge no invoice raised has nothing to do with these rows.
    NS(id="re_5", status="succeeded", amount=700, created=ts(6, 3),
       charge=NS(payment_intent="pi_no_invoice"), payment_intent=None),
]
PAYMENTS = {"pi_sub_1": "in_sub_1", "pi_half": "in_half"}
refund_failure = {"on": False}


def _refund_list(**_kw):
    if refund_failure["on"]:
        raise RuntimeError("Stripe said no")
    return NS(auto_paging_iter=lambda: iter(REFUNDS))


def _payment_list(payment=None, **_kw):
    found = PAYMENTS.get(payment["payment_intent"])
    return NS(data=[NS(invoice=found)] if found else [])


stripe.api_key = "sk_test_fake"
stripe.Invoice = NS(list=lambda **_kw: NS(auto_paging_iter=lambda: iter(INVOICES)))
stripe.Refund = NS(list=_refund_list)
stripe.InvoicePayment = NS(list=_payment_list)
# The page's account panel asks Stripe for a balance; it has nothing to do with this.
import pm.stripe_routes as stripe_routes  # noqa: E402
stripe_routes._account_overview = lambda: {
    "available_balance": 0.0, "pending_balance": 0.0, "account_outstanding": 0.0,
    "open_invoice_count": 0, "payments": [], "payouts": []}


def fresh_stripe():
    stripe_service._invoice_cache.update({"ts": 0, "data": None, "refunds": None})
    stripe_service._refund_invoices.clear()


Q2 = dict(year=YEAR, quarter=2, tax_due=339.90, penalty=34.00, late_filing_penalty=50.00, interest=3.03,
          discount=0.0, amount_paid=426.93, processing_fee=9.86, filed_at=datetime(YEAR, 10, 30, 14))
Q3 = dict(year=YEAR, quarter=3, tax_due=656.70, penalty=32.84, late_filing_penalty=50.00, interest=0.0,
          discount=0.0, amount_paid=739.54, processing_fee=16.89, filed_at=datetime(YEAR, 10, 30, 15))

with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board")
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="ehq", sales_source="hub")
    kenali = Client(name="Kenali Kendrick", stripe_customer_id="cus_k")
    db.session.add_all([boss, bbb, ehq, kenali])
    db.session.flush()
    big = Expense(amount=756.43, description="Texas Comptroller (state tax)", category="taxes_licenses",
                  date=date(YEAR, 11, 2), business_id=bbb.id, paid_by="Michael Bean")
    small = Expense(amount=436.79, description="Texas Comptroller (state tax)", category="taxes_licenses",
                    date=date(YEAR, 11, 2), business_id=bbb.id)
    franchise = Expense(amount=300.00, description="Texas Comptroller (franchise tax)",
                        category="taxes_licenses", date=date(YEAR, 11, 2), business_id=bbb.id)
    railway = Expense(amount=100.00, description="Railway", category="hosting",
                      date=date(YEAR, 8, 1), business_id=bbb.id)
    db.session.add_all([big, small, franchise, railway,
                        SalesTaxFiling(business_id=bbb.id, **Q2), SalesTaxFiling(business_id=bbb.id, **Q3)])
    db.session.commit()
    ids = {"boss": boss.id, "bbb": bbb.id, "ehq": ehq.id, "big": big.id, "small": small.id,
           "franchise": franchise.id, "kenali": kenali.id}

    print("1. A return's payment splits into tax and cost")
    check("both returns are settled", books_service.settle_sales_tax() == 2)
    big, small = db.session.get(Expense, ids["big"]), db.session.get(Expense, ids["small"])
    check("$756.43 carried $656.70 and cost $99.73", (big.sales_tax_remitted, big.amount) == (656.70, 99.73),
          (big.sales_tax_remitted, big.amount))
    check("$436.79 carried $339.90 and cost $96.89", (small.sales_tax_remitted, small.amount) == (339.90, 96.89),
          (small.sales_tax_remitted, small.amount))
    check("what left the bank has not moved", (big.charged, small.charged) == (756.43, 436.79))
    check("each is linked to its own return", big.sales_tax_filing.quarter == 3 and small.sales_tax_filing.quarter == 2)
    check("the row says where the money went, with its commas and to the cent",
          big.sales_tax_note == "$756.43 charged: $656.70 sales tax, $82.84 penalties and interest, $16.89 card fee",
          big.sales_tax_note)
    check("the other one adds up too",
          small.sales_tax_note == "$436.79 charged: $339.90 sales tax, $87.03 penalties and interest, $9.86 card fee",
          small.sales_tax_note)
    check("the real return's split is the $196.62 that was really lost",
          round(big.amount + small.amount, 2) == 196.62)
    check("settling again changes nothing", books_service.settle_sales_tax() == 0)
    check("a franchise tax payment is left whole",
          db.session.get(Expense, ids["franchise"]).amount == 300.00
          and not db.session.get(Expense, ids["franchise"]).sales_tax_remitted)

    print("2. Nothing that matches a charge is thrown by it")
    money_in = books_service.owner_money_between(db.session.get(Business, ids["bbb"]), START, END)
    check("the owner still put in the whole charge, not what is left of it",
          money_in.get("Michael Bean", {}).get("in") == 756.43, money_in)
    company = BankConnection(business_id=ids["bbb"], provider="statement", label="Chase debit",
                             token="", kind="business")
    db.session.add(company)
    db.session.flush()
    bank_feed.remember("TEXAS COMPTROLLER", "expense", vendor="Texas Comptroller (state tax)",
                       business_id=ids["bbb"], category="taxes_licenses")
    db.session.commit()
    statements.import_rows(company, [{"ref": "line-1", "date": date(YEAR, 11, 3), "amount": -756.43,
                                      "description": "TEXAS COMPTROLLER PMT"}])
    line = BankTransaction.query.filter_by(external_id="line-1").one()
    check("the statement line adopts the split row rather than booking it again",
          line.expense_id == ids["big"], line.expense_id)
    check("the charge is still one row",
          Expense.query.filter(Expense.description.ilike("%state tax%")).count() == 2)
    bank_feed.classify(line)
    db.session.commit()
    big = db.session.get(Expense, ids["big"])
    check("reading the bank line again keeps the tax out", (big.amount, big.charged) == (99.73, 756.43),
          (big.amount, big.charged))
    receipts_service.rematch()
    check("the return's record still finds the charge it paid",
          bool(db.session.get(Expense, ids["big"]).receipt_filename))

    print("3. A return and its charge, in either order")
    Q1 = dict(year=YEAR, quarter=1, tax_due=100.00, amount_paid=100.00, processing_fee=2.30,
              filed_at=datetime(YEAR, 4, 10, 9))
    db.session.add(SalesTaxFiling(business_id=ids["bbb"], **Q1))
    db.session.commit()
    statements.import_rows(company, [{"ref": "line-2", "date": date(YEAR, 4, 12), "amount": -102.30,
                                      "description": "TEXAS COMPTROLLER PMT"}])
    line2 = BankTransaction.query.filter_by(external_id="line-2").one()
    arrived = db.session.get(Expense, line2.expense_id)
    check("recorded first, charge later: the bank line's expense is settled",
          (arrived.sales_tax_remitted, arrived.amount) == (100.00, 2.30),
          (arrived.sales_tax_remitted, arrived.amount))
    ids["arrived"] = arrived.id
    typed = Expense(amount=500.00, description="Comptroller, Q4 sales tax", category="taxes_licenses",
                    date=date(YEAR + 1, 1, 18), business_id=ids["bbb"])
    db.session.add(typed)
    db.session.commit()
    ids["typed"] = typed.id
    summary = books_service.summarize(db.session.get(Business, ids["bbb"]), START, END)
    check("a payment still in another year is not this year's", typed not in summary["expenses"])

c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True

form = {"reference_number": "REF123", "payment_reference": "", "trace_number": "", "payment_method": "card",
        "notes": "", "total_sales": "6000", "taxable_sales": "4800", "tax_due": "500.00", "penalty": "0",
        "late_filing_penalty": "0", "interest": "0", "discount": "0", "processing_fee": "0",
        "amount_paid": "500.00", "filed_on": f"{YEAR + 1}-01-18", "filed_time": "10:00"}
res = c.post(f"/admin/taxes/sales/returns/bbb/{YEAR}/q4/record", data=form)
check("recording the return works", res.status_code == 302, res.status_code)
with application.app_context():
    typed = db.session.get(Expense, ids["typed"])
    check("charge first, return later: recording the return settles it",
          (typed.sales_tax_remitted, typed.amount, typed.charged) == (500.00, 0.0, 500.00),
          (typed.sales_tax_remitted, typed.amount, typed.charged))
    check("nothing lost means nothing to prove a receipt for",
          typed not in books_service.summarize(
              db.session.get(Business, ids["bbb"]), date(YEAR + 1, 1, 1), date(YEAR + 2, 1, 1))["no_receipt"])
    filing_id = SalesTaxFiling.query.filter_by(business_id=ids["bbb"], year=YEAR, quarter=4).one().id
res = c.post(f"/admin/taxes/sales/filings/{filing_id}/delete")
check("removing the record works", res.status_code == 302, res.status_code)
with application.app_context():
    typed = db.session.get(Expense, ids["typed"])
    check("taking the return away puts the charge back whole",
          (typed.amount, typed.sales_tax_remitted, typed.sales_tax_filing_id) == (500.00, 0.0, None),
          (typed.amount, typed.sales_tax_remitted, typed.sales_tax_filing_id))
    disc = SalesTaxFiling(business_id=ids["bbb"], year=YEAR, quarter=4, tax_due=500.00, discount=5.00,
                          amount_paid=495.00, filed_at=datetime(YEAR + 1, 1, 18, 10))
    db.session.add(disc)
    typed.amount = 495.00
    db.session.commit()
    books_service.settle_sales_tax(disc)
    db.session.commit()
    typed = db.session.get(Expense, ids["typed"])
    check("a timely filing discount is tax the state let go of, so only what went is remitted",
          (typed.sales_tax_remitted, typed.amount) == (495.00, 0.0), (typed.sales_tax_remitted, typed.amount))

    print("4. A company whose income is gross keeps a whole expense")
    gross = Expense(amount=204.60, description="Texas Comptroller", category="taxes_licenses",
                    date=date(YEAR, 7, 20), business_id=ids["ehq"])
    db.session.add_all([gross, SalesTaxFiling(business_id=ids["ehq"], year=YEAR, quarter=2, tax_due=204.60,
                                              amount_paid=204.60, filed_at=datetime(YEAR, 7, 20, 9))])
    db.session.commit()
    books_service.settle_sales_tax()
    db.session.commit()
    check("EntertainHQ's sales are gross, so the payment is what takes the tax back out",
          (gross.amount, gross.sales_tax_remitted) == (204.60, 0.0), (gross.amount, gross.sales_tax_remitted))

    print("5. Refunds are read beside the invoices")
    fresh_stripe()
    rows = {r["id"]: r for r in stripe_service.get_stripe_invoices(ttl=0)}
    check("through the payment, the way the current API answers", rows["in_sub_1"]["refunded"] == 1.99,
          rows["in_sub_1"]["refunded"])
    check("through the charge, the way older versions answer", rows["in_sub_2"]["refunded"] == 1.99,
          rows["in_sub_2"]["refunded"])
    check("a refund that failed gave nothing back", rows["in_work"]["refunded"] == 0.0, rows["in_work"]["refunded"])
    check("a refund no invoice raised touches no invoice", round(sum(r["refunded"] for r in rows.values()), 2) == 57.28,
          sum(r["refunded"] for r in rows.values()))
    check("half of a taxed invoice earned half of what it would have",
          stripe_service.invoice_earned(rows["in_half"]) == 50.00, stripe_service.invoice_earned(rows["in_half"]))
    check("all of a refunded one earned nothing", stripe_service.invoice_earned(rows["in_sub_1"]) == 0.0)
    check("nothing is earned from a catch-up", stripe_service.invoice_earned(rows["in_back_k"]) == 0.0)
    totals = stripe_service.get_stripe_invoice_totals()
    check("the dashboard's revenue is after refunds and tax", round(totals["revenue"], 2) == 3050.00, totals["revenue"])
    check("and cash in is after refunds, tax and all", round(totals["paid"], 2) == 4254.50, totals["paid"])
    check("per client too", round(totals["revenue_by_customer"]["cus_e"], 2) == 0.0,
          totals["revenue_by_customer"]["cus_e"])
    hosting = stripe_service.get_hosting_revenue()
    check("a refunded month of hosting collected nothing",
          hosting["collected"] == 0.0 and hosting["paid_invoices"] == 0, hosting)

    refund_failure["on"] = True
    again = stripe_service.get_stripe_invoices(ttl=0)
    refund_failure["on"] = False
    check("a failed refund read keeps the invoices and the last good answer",
          len(again) == len(INVOICES) and {r["id"]: r for r in again}["in_half"]["refunded"] == 53.30)

    bbb_row = db.session.get(Business, ids["bbb"])
    year = books_service.summarize(bbb_row, START, END)
    months = year["by_month"]
    check("the sale stays in the month it was paid", months[f"{YEAR}-07"]["income"] == 1.99, months.get(f"{YEAR}-07"))
    check("and the refund lands in the month it went back", months[f"{YEAR}-08"]["income"] == -1.99,
          months.get(f"{YEAR}-08"))
    check("the income is earned money, less refunds and tax", year["income_total"] == 3050.00, year["income_total"])
    check("expenses carry the real cost of the returns: $99.73 + $96.89 + $2.30 + $300 + $100",
          year["expense_total"] == 598.92, year["expense_total"])
    check("the net is the two of them", year["net"] == 2451.08, year["net"])
    check("the line on the return holds no tax that was passed through",
          next(r for r in year["tax_lines"] if r["label"] == "Taxes and licenses")["total"] == 498.92,
          year["tax_lines"])

    made, updated, orphans = stripe_service.import_invoices_from_stripe(ttl=0)
    check("the importer names the invoice it could not place", "IN_STRAY" in orphans, orphans)
    check("but not one with no money left in it",
          "IN_SUB_1" not in orphans and "IN_SUB_2" not in orphans, orphans)
    half = Invoice.query.filter_by(stripe_invoice_id="in_half").one()
    check("the local row carries the refund", half.amount_refunded == 53.30, half.amount_refunded)
    check("the client page's revenue reads the same as the dashboard's",
          round(db.session.get(Client, ids["kenali"]).total_revenue, 2) == 3050.00,
          db.session.get(Client, ids["kenali"]).total_revenue)

    st = NS(rate_percent=8.25, taxable_share=80.0, count_from=None, effective_percent=6.6)
    undone = NS(id=1, total=100.0, tax=0.0, status="paid", project_id=None, client_id=1, issued_on=date(YEAR, 5, 1),
                sales_tax_catchup=False, sales_tax_exempt=False, amount_paid=100.0, amount_refunded=100.0,
                amount_due=0.0, invoice_number="1")
    row = sales_tax.invoice_row(undone, st, None, None, client_exempt=False)
    check("a sale refunded in full owes no sales tax", row["excluded"] == "refunded" and not row["counted"], row)
    undone.amount_refunded = 40.0
    check("a part refund stays on the return, erring towards the state",
          sales_tax.invoice_row(undone, st, None, None, client_exempt=False)["counted"])

print("6. Total Paid less its sales tax is the Books page's income")
res = c.get("/admin/stripe/invoices")
check("the Invoices page renders", res.status_code == 200, res.status_code)
page = flat(res.get_data(as_text=True))
paid = money(page, "Total Paid")
check("Total Paid is what stayed", paid == 4254.50, paid)
check("the sales tax in it is shown beside it", "$1,204.50 of it sales tax" in page, page[:400])
check("and the refunds", "$57.28 refunded" in page)
with application.app_context():
    income = books_service.summarize(db.session.get(Business, ids["bbb"]), START, END)["income_total"]
check("Total Paid less the sales tax is the Books page's income, to the cent",
      round(paid - 1204.50, 2) == income, (paid, income))
html = res.get_data(as_text=True)
check("a row refunded in full says so", re.sub(r"\s+", " ", html).count(">Refunded</span>") == 2,
      re.sub(r"\s+", " ", html).count(">Refunded</span>"))
check("a part refund says how much", "$53.30 refunded" in page)

res = c.get("/admin/expenses?per_page=100", follow_redirects=True)
check("the expense list renders", res.status_code == 200, res.status_code)
check("the row says where the rest of the charge went",
      "$756.43 charged: $656.70 sales tax" in flat(res.get_data(as_text=True)))
check("and the row stays one line, because wrapped it stood eight lines tall on a phone",
      'truncate mt-0.5" title="$756.43 charged' in res.get_data(as_text=True))
form_page = flat(c.get(f"/admin/expenses/{ids['big']}/edit").get_data(as_text=True))
check("the edit page says it whole, the one place a phone can read it",
      "$756.43 charged: $656.70 sales tax, $82.84 penalties and interest, $16.89 card fee" in form_page,
      form_page[:200])
check("the books say the same to the accountant",
      "$756.43 charged: $656.70 sales tax, $82.84 penalties and interest, $16.89 card fee"
      in c.get(f"/admin/books/{ids['bbb']}/year/{YEAR}.csv").get_data(as_text=True))

print("7. The migration fixes what is there, and comes back exactly")
import sqlalchemy as sa  # noqa: E402
from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402

NAME = "a1f6c3e8d204_sales_tax_out_of_expenses_and_refunds"
spec = importlib.util.spec_from_file_location(NAME, ROOT / f"migrations/versions/{NAME}.py")
mig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mig)
engine = sa.create_engine("sqlite:///" + (pathlib.Path(TMP) / "before.db").as_posix())
with engine.begin() as conn:
    for ddl in (
        "CREATE TABLE businesses (id INTEGER PRIMARY KEY, parent_id INTEGER, sales_source VARCHAR(20))",
        "CREATE TABLE sales_tax_filings (id INTEGER PRIMARY KEY, business_id INTEGER, tax_due FLOAT, "
        "discount FLOAT, amount_paid FLOAT, filed_at DATETIME)",
        "CREATE TABLE expenses (id INTEGER PRIMARY KEY, amount FLOAT NOT NULL, description TEXT, date DATE, "
        "business_id INTEGER, time_entry_id INTEGER)",
        "CREATE TABLE invoices (id INTEGER PRIMARY KEY, amount_paid FLOAT)",
    ):
        conn.execute(sa.text(ddl))
    conn.execute(sa.text("INSERT INTO businesses VALUES (1, NULL, 'board'), (2, NULL, 'hub'), (3, 1, 'board')"))
    conn.execute(sa.text(
        "INSERT INTO sales_tax_filings VALUES (1, 1, 339.90, 0, 426.93, '2026-10-30 14:00:00'), "
        "(2, 1, 656.70, 0, 739.54, '2026-10-30 15:00:00'), (3, 2, 204.60, 0, 204.60, '2026-10-30 15:00:00'), "
        "(4, 1, 50.0, 0, 50.0, NULL)"))
    conn.execute(sa.text(
        "INSERT INTO expenses VALUES (1, 756.43, 'Texas Comptroller (state tax)', '2026-11-02', 1, NULL), "
        "(2, 436.79, 'Texas Comptroller (state tax)', '2026-11-02', 3, NULL), "
        "(3, 300.0, 'Texas Comptroller (franchise tax)', '2026-11-02', 1, NULL), "
        "(4, 204.60, 'Texas Comptroller', '2026-10-30', 2, NULL), "
        "(5, 739.54, 'Office chair', '2026-11-02', 1, NULL)"))


def amounts():
    with engine.connect() as conn:
        return {r[0]: r[1] for r in conn.execute(sa.text("SELECT id, amount FROM expenses"))}


def run(step):
    with engine.begin() as conn:
        mig.op = Operations(MigrationContext.configure(conn))
        getattr(mig, step)()


before = amounts()
run("upgrade")
after = amounts()
check("each return's charge comes down to what it really cost, a DBA's included",
      (after[1], after[2]) == (99.73, 96.89), after)
check("a franchise tax charge is left alone", after[3] == 300.0)
check("a company with gross income is left alone", after[4] == 204.60)
check("the same amount under another name is left alone", after[5] == 739.54)
with engine.connect() as conn:
    check("what it carried is written down", conn.execute(sa.text(
        "SELECT sales_tax_remitted, sales_tax_filing_id FROM expenses WHERE id = 1")).fetchone() == (656.70, 2))
run("upgrade")
check("running it a second time changes nothing", amounts() == after, amounts())
run("downgrade")
check("coming back restores every charge exactly", amounts() == before, amounts())
with engine.connect() as conn:
    names = {c["name"] for c in sa.inspect(conn).get_columns("expenses")}
check("and takes its columns with it", "sales_tax_remitted" not in names and "sales_tax_filing_id" not in names, names)
run("upgrade")
check("and it goes forward again to the same place", amounts() == after, amounts())

print()
if FAIL:
    print(f"{len(FAIL)} FAILED")
    sys.exit(1)
print("all passed")
