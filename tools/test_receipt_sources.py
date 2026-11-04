# -*- coding: utf-8 -*-
"""Receipts that attach themselves where one charge is not one receipt.

Michael, 2026-11-03: "getting the receipts for them ... and having an
automatic process for that going forward." Of about a hundred expenses with
no receipt, most could never match one: Railway's bill is one receipt split
across a row per project, Stripe sends no receipt for its fees, an
Anthropic receipt read $200.00 off its subtotal where the charge was $213.20,
and the sales tax payments' confirmations were on the board already, kept
with the returns. Proves:

  1. A receipt whose total matches a vendor's whole split month proves every
     row of it, and only for a vendor the receipt names.
  2. A receipt read as one figure still matches a charge for another total
     on it (tax included), and a subtotal is never a total.
  3. A month of Stripe's fees gets a statement written from Stripe's own
     lines, attached to that month's fee expense.
  4. A sales tax payment gets the confirmation kept with its return, as a
     copy.
  5. Deleting one expense of a split month keeps the shared receipt.
  6. The Receipts page lists what is missing first.

Run: python tools/test_receipt_sources.py
"""
import io
import os
import pathlib
import sys
import tempfile
from datetime import date, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-receipt-sources-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, Business, Expense, Receipt, ReceiptMailbox, SalesTaxFiling,  # noqa: E402
                    SalesTaxFilingFile, ServiceCostEntry, ServiceProvider, User)
import receipts_service  # noqa: E402
import service_costs_service  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []
RECEIPTS = pathlib.Path(TMP) / "receipts"
RECEIPTS.mkdir(exist_ok=True)


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def stored(name, html):
    (RECEIPTS / name).write_text(html, encoding="utf-8")
    return name


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board")
    railway = ServiceProvider(name="railway", display_name="Railway", is_active=True)
    stripe_p = ServiceProvider(name="stripe", display_name="Stripe", is_active=True)
    box = ReceiptMailbox(address="m@example.test", password="x")
    db.session.add_all([boss, bbb, railway, stripe_p, box])
    db.session.flush()

    # October's Railway bill, $72.38, split across three projects.
    split = []
    for i, amt in enumerate((40.00, 20.38, 12.00)):
        e = Expense(amount=amt, description=f"Railway - Project {i} (Oct 2026)", category="hosting",
                    date=date(2026, 10, 31), business_id=bbb.id)
        db.session.add(e)
        db.session.flush()
        db.session.add(ServiceCostEntry(provider_id=railway.id, expense_id=e.id, resource_identifier=f"p{i}",
                                        period_start=date(2026, 10, 1), period_end=date(2026, 10, 31),
                                        raw_amount=amt, allocated_amount=amt, description="x"))
        split.append(e)
    # An unrelated charge for the same total, from a vendor the receipt does not name.
    decoy = Expense(amount=72.38, description="Office chair", category="office",
                    date=date(2026, 10, 30), business_id=bbb.id)
    claude = Expense(amount=213.20, description="Claude Max", category="ai_services",
                     date=date(2026, 10, 20), business_id=bbb.id)
    tax = Expense(amount=756.43, description="Texas Comptroller (state tax)", category="taxes_licenses",
                  date=date(2026, 11, 2), business_id=bbb.id)
    db.session.add_all([decoy, claude, tax])
    db.session.commit()

    print("1. A vendor's split month")
    rw = Receipt(mailbox_id=box.id, message_key="<rw>", vendor="Railway Corporation",
                 sender="Railway Corporation <invoice+statements@stripe.com>",
                 subject="Your receipt from Railway Corporation 2374-7492", received_on=date(2026, 11, 1),
                 amount=72.38, filename=stored("rw.html", "<p>Amount paid $72.38</p>"),
                 original_name="rw.html", status="unmatched")
    db.session.add(rw)
    db.session.flush()
    # The decoy is a single charge for the same amount in the same days, so
    # the old rule would take it; the vendor's own month must win when the
    # receipt names the vendor.
    receipts_service.match(rw)
    db.session.commit()
    check("every row of Railway's October carries the one receipt",
          all(db.session.get(Expense, e.id).receipt_filename == "rw.html" for e in split))
    check("and nothing else does", db.session.get(Expense, decoy.id).receipt_filename is None)

    print("2. Another total on the receipt")
    an = Receipt(mailbox_id=box.id, message_key="<an>", vendor="Anthropic, PBC", sender="Anthropic",
                 subject="Your receipt from Anthropic, PBC", received_on=date(2026, 10, 20), amount=200.00,
                 filename=stored("an.html", "<table><tr><td>Subtotal</td><td>$200.00</td></tr>"
                                            "<tr><td>Tax</td><td>$13.20</td></tr>"
                                            "<tr><td>Amount paid</td><td>$213.20</td></tr></table>"),
                 original_name="an.html", status="unmatched")
    db.session.add(an)
    db.session.flush()
    receipts_service.match(an)
    db.session.commit()
    check("the $213.20 charge takes the receipt that first read $200.00",
          db.session.get(Expense, claude.id).receipt_filename == "an.html")
    check("a subtotal is not a total",
          200.00 not in receipts_service._CANDIDATES["an.html"], receipts_service._CANDIDATES["an.html"])

    print("3. Stripe's fees")
    fee = Expense(amount=66.14, description="Stripe fees - Kenali Kendrick (Oct 2026)", category="bank_fees",
                  date=date(2026, 10, 31), business_id=bbb.id)
    db.session.add(fee)
    db.session.flush()
    db.session.add(ServiceCostEntry(provider_id=stripe_p.id, expense_id=fee.id,
                                    resource_identifier="stripe-fees:cus_123", period_start=date(2026, 10, 1),
                                    period_end=date(2026, 10, 31), raw_amount=66.14, allocated_amount=66.14,
                                    description="x"))
    db.session.commit()
    service_costs_service._stripe_fee_statement(
        stripe_p, "stripe-fees:cus_123", date(2026, 10, 1), "Stripe fees - Kenali Kendrick",
        [{"date": date(2026, 10, 3), "id": "txn_1", "type": "charge", "description": "Invoice 12",
          "amount": 2200.0, "fee": 66.14}])
    db.session.commit()
    fee = db.session.get(Expense, fee.id)
    page = (RECEIPTS / (fee.receipt_filename or "missing")).read_text(encoding="utf-8") \
        if fee.receipt_filename else ""
    check("the month's fee expense has a statement", fee.receipt_filename == "stripe-fees-cus_123-2026-10.html")
    check("written from Stripe's own lines", "txn_1" in page and "$66.14" in page)

    print("4. Sales tax")
    filing = SalesTaxFiling(business_id=bbb.id, year=2026, quarter=3, filed_at=datetime(2026, 10, 30, 15),
                            amount_paid=739.54)  # the card fee was never typed in
    db.session.add(filing)
    db.session.flush()
    (pathlib.Path(TMP) / "tax_filings").mkdir(exist_ok=True)
    (pathlib.Path(TMP) / "tax_filings" / "conf.pdf").write_bytes(b"%PDF-1.4 confirmation")
    db.session.add(SalesTaxFilingFile(filing_id=filing.id, stored_name="conf.pdf",
                                      original_name="WebFile confirmation.pdf"))
    db.session.commit()
    receipts_service.rematch()
    # A second return with no confirmation uploaded: the board's own record.
    bare = SalesTaxFiling(business_id=bbb.id, year=2026, quarter=2, filed_at=datetime(2026, 10, 30, 15),
                          amount_paid=426.93, reference_number="R-1")
    tax2 = Expense(amount=436.79, description="Texas Comptroller (state tax)", category="taxes_licenses",
                   date=date(2026, 11, 2), business_id=bbb.id)
    db.session.add_all([bare, tax2])
    db.session.commit()
    receipts_service.rematch()
    tax2 = db.session.get(Expense, tax2.id)
    check("a return with no confirmation gives the board's own record",
          (tax2.receipt_original_name or "").endswith("(board record).pdf")
          and (RECEIPTS / tax2.receipt_filename).read_bytes().startswith(b"%PDF"), tax2.receipt_original_name)
    tax = db.session.get(Expense, tax.id)
    check("the payment carries the return's confirmation",
          tax.receipt_original_name == "WebFile confirmation.pdf" and tax.receipt_filename != "conf.pdf"
          and (RECEIPTS / tax.receipt_filename).exists())

    ids = {"boss": boss.id, "first": split[0].id}

print("5. A shared receipt outlives one of its expenses")
c = application.test_client()
with c.session_transaction() as s:
    s["_user_id"] = str(ids["boss"])
    s["_fresh"] = True
c.post(f"/admin/expenses/{ids['first']}/delete")
check("the Railway receipt is still on the volume", (RECEIPTS / "rw.html").exists())

print("6. The page")
html = c.get("/admin/books/receipts", follow_redirects=True).get_data(as_text=True)
check("Missing comes first and lists the expense without one", "Office chair" in html and "Add receipt" in html)
check("no em dash", "—" not in html)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
