# -*- coding: utf-8 -*-
"""The books: owners' money, the year-end report, the monthly close, receipts
from every mailbox, and the read-only view EntertainHQ's admin reads.

Michael, 2026-11-03: "we're effectively building out our own bookkeeping
system", and for EntertainHQ's partners, "transparency ... but not to where
like we're having to track two systems at once". Proves:

  1. Money an owner puts in is neither income nor an expense, and is
     credited to that owner; the Chase rule says so.
  2. The year: income is paid invoices less their sales tax, expenses group
     into the return's lines, a DBA's expenses are its company's, and the
     CSV carries every line.
  3. The close: it lists what is left, closes only a finished month, keeps
     the figures it closed on, and shows a later change as a difference.
  4. Receipts: an HTML receipt and a PDF one are read for their amount,
     attached to the matching expense and to nothing else; a renewal notice
     is not a receipt; reading again stores nothing twice; a receipt with no
     charge waits, and attaches once its charge arrives.
  5. The hub: EntertainHQ's own app reads its books signed with its secret,
     its own sales become its income, a stranger is refused.
  6. The pages render with no em dash.

Run: python tools/test_books.py
"""
import email.message
import io
import json
import os
import pathlib
import sys
import tempfile
from datetime import date, datetime

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-books-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")
os.environ.pop("ANTHROPIC_API_KEY", None)

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, BankConnection, BankTransaction, Business, BusinessOwner, Client,  # noqa: E402
                    Expense, Invoice, MonthClose, Receipt, ReceiptMailbox, User)
import bank_feed  # noqa: E402
import books_service  # noqa: E402
import hub  # noqa: E402
import receipts_service  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name + (("  -> " + str(detail)) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


def tx(id_, amount, name, kind="debitCardTransaction", status="sent", day="2026-10-05"):
    return {"id": id_, "amount": amount, "counterpartyName": name, "kind": kind,
            "status": status, "createdAt": f"{day}T10:00:00Z",
            "postedAt": f"{day}T12:00:00Z" if status == "sent" else None, "accountId": "acct-1"}


def mail(subject, body, sender="Railway <billing@railway.app>", day="Mon, 05 Oct 2026 10:00:00 +0000",
         html=False, pdf=None, mid=None):
    m = email.message.EmailMessage()
    m["Subject"], m["From"], m["Date"] = subject, sender, day
    m["Message-ID"] = mid or f"<{abs(hash(subject + body))}@test>"
    if html:
        m.set_content("plain fallback")
        m.add_alternative(body, subtype="html")
    else:
        m.set_content(body)
    if pdf is not None:
        m.add_attachment(pdf, maintype="application", subtype="pdf", filename="invoice.pdf")
    return m.as_bytes()


def pdf_with(text):
    """A one-page PDF carrying `text`, made with pypdf's own writer."""
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
    w = PdfWriter()
    page = w.add_blank_page(612, 792)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                             NameObject("/Subtype"): NameObject("/Type1"),
                             NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject(
        {NameObject("/F1"): w._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 72 700 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = w._add_object(stream)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="bbb", sales_source="board")
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="ehq", sales_source="hub",
                   hub_slug="entertainhq", hub_secret="s3cret")
    db.session.add_all([boss, bbb, ehq])
    db.session.flush()
    dd = Business(name="Data Dungeon", slug="dd", parent_id=bbb.id)
    client = Client(name="Cason Kuper")
    db.session.add_all([dd, client,
                        BusinessOwner(business_id=bbb.id, name="Michael Bean", share_percent=100),
                        BusinessOwner(business_id=ehq.id, name="Michael Bean", share_percent=40),
                        BusinessOwner(business_id=ehq.id, name="Kenali Kendrick", share_percent=40),
                        BusinessOwner(business_id=ehq.id, name="Third Member", share_percent=20)])
    db.session.flush()
    db.session.add_all([
        Invoice(client_id=client.id, status="paid", total=1066, tax=66, amount_paid=1066,
                paid_at=datetime(2026, 10, 3)),
        Invoice(client_id=client.id, status="paid", total=500, tax=0, amount_paid=500,
                paid_at=datetime(2025, 12, 3)),
        Invoice(client_id=client.id, status="paid", total=66, tax=0, amount_paid=66,
                paid_at=datetime(2026, 10, 4), sales_tax_catchup=True),
        Expense(amount=20.0, description="Railway - Kuper Plumbing", category="hosting",
                date=date(2026, 10, 5), business_id=bbb.id),
        Expense(amount=12.37, description="OpenAI", category="ai_services",
                date=date(2026, 10, 6), business_id=bbb.id),
        Expense(amount=99.0, description="Apple Developer", category="software",
                date=date(2026, 10, 9), business_id=dd.id),
        Expense(amount=150.0, description="LegalZoom", category="legal_professional",
                date=date(2026, 9, 1), business_id=bbb.id),
        Expense(amount=42.48, description="Railway", category="hosting",
                date=date(2026, 10, 16), business_id=ehq.id),
    ])
    db.session.commit()
    ids = {"bbb": bbb.id, "ehq": ehq.id, "boss": boss.id}

    print("1. Owner money")
    bank_feed.remember("CHASE", "contribution", vendor="Michael Bean (from his Chase account)",
                       owner_name="Michael Bean")
    db.session.commit()
    conn = BankConnection(business_id=bbb.id, token="secret-token:x", synced_from=date(2026, 4, 1))
    db.session.add(conn)
    db.session.commit()
    bank_feed.sync_connection(conn, fetch=lambda t, s: iter([
        tx("c1", 5000.0, "Chase - Total Checking 8721", kind="externalTransfer", day="2026-11-05"),
        tx("c2", -300.0, "Michael Bean", kind="outgoingPayment", day="2026-11-20")]),
        accounts={"acct-1": "Checking"})
    c1 = BankTransaction.query.filter_by(external_id="c1").one()
    check("money in from Chase is Michael's contribution",
          c1.disposition == "contribution" and c1.owner_name == "Michael Bean" and c1.expense_id is None)
    c2 = BankTransaction.query.filter_by(external_id="c2").one()
    bank_feed.decide(c2, "draw", pattern="", keep=False, owner_name="Michael Bean")
    c2 = BankTransaction.query.filter_by(external_id="c2").one()
    check("money taken out is a draw, not an expense", c2.disposition == "draw" and c2.expense_id is None)
    money = books_service.owner_money_between(bbb, date(2026, 1, 1), date(2027, 1, 1))
    check("the year credits the owner both ways",
          money.get("Michael Bean") == {"in": 5000.0, "out": 300.0}, money)

    print("2. The year")
    s = books_service.summarize(bbb, date(2026, 1, 1), date(2027, 1, 1))
    check("income is paid invoices less sales tax, no catch-up, this year only",
          s["income_total"] == 1000.0, s["income_total"])
    check("a DBA's expense is its company's", any(e.description == "Apple Developer" for e in s["expenses"]))
    check("another company's expense is not", all(e.business_id != ids["ehq"] for e in s["expenses"]))
    check("the total", s["expense_total"] == round(20 + 12.37 + 99 + 150, 2), s["expense_total"])
    lines = {r["label"]: r["total"] for r in s["tax_lines"]}
    check("grouped into the return's lines",
          lines.get("Hosting and infrastructure") == 20.0
          and lines.get("Software and subscriptions") == round(12.37 + 99, 2)
          and lines.get("Legal and professional services") == 150.0, lines)
    check("by month", list(s["by_month"]) == ["2026-09", "2026-10"], list(s["by_month"]))

    print("3. The close")
    oct_ = books_service.summarize(bbb, date(2026, 10, 1), date(2026, 11, 1))
    check("it lists what has no receipt", len(oct_["no_receipt"]) == 3, len(oct_["no_receipt"]))

    print("4. Receipts")
    box = ReceiptMailbox(address="michaelbean21@gmail.com", password="x", business_id=bbb.id)
    db.session.add(box)
    db.session.commit()
    msgs = [
        mail("Your Railway receipt", "<table><tr><td>Subtotal</td><td>$18.00</td></tr>"
             "<tr><td>Total</td><td>$20.00</td></tr></table>", html=True),
        mail("Your invoice from OpenAI", "Thanks.", sender="OpenAI <billing@openai.com>",
             day="Tue, 06 Oct 2026 09:00:00 +0000", pdf=pdf_with("Amount paid $12.37")),
        mail("Your subscription will renew soon", "Total $99.00", sender="Apple <no_reply@apple.com>"),
        mail("Receipt for your order", "Order total: $49.99", sender="Amazon <auto@amazon.com>"),
        mail("Lunch with the team", "Total $25.00", sender="friend@example.com"),
    ]
    counts = receipts_service.sync_mailbox(box, fetcher=lambda b, since: iter(msgs))
    railway = Expense.query.filter_by(description="Railway - Kuper Plumbing").one()
    openai = Expense.query.filter_by(description="OpenAI").one()
    check("three receipts read (the renewal notice and the lunch are not receipts)",
          counts.get("new") == 3, counts)
    check("the HTML receipt's total, not its subtotal, attached to Railway",
          railway.receipt_filename is not None and Receipt.query.filter_by(expense_id=railway.id).one().amount == 20.0)
    check("the PDF receipt read and attached to OpenAI",
          openai.receipt_filename is not None and openai.receipt_filename.endswith(".pdf"))
    amazon = Receipt.query.filter_by(vendor="Amazon").one()
    check("a receipt with no charge waits", amazon.status == "unmatched" and amazon.amount == 49.99)
    receipts_service.sync_mailbox(box, fetcher=lambda b, since: iter(msgs))
    check("reading again stores nothing twice", Receipt.query.count() == 3, Receipt.query.count())
    db.session.add(Expense(amount=49.99, description="Amazon", category="office",
                           date=date(2026, 10, 7), business_id=bbb.id))
    db.session.commit()
    check("it attaches once its charge arrives", receipts_service.rematch() == 1
          and Receipt.query.filter_by(vendor="Amazon").one().status == "matched")
    stored = os.path.join(TMP, "receipts", railway.receipt_filename)
    check("the file is on the volume", os.path.exists(stored))

    # A second read running at the same moment saves the same message first:
    # the existence check passes, the insert collides. It shipped as a 500
    # that threw away the whole read (2026-11-03). Simulated by blinding the
    # check, so the insert itself meets the duplicate.
    seen_query = Receipt.query

    class Blind:
        def filter_by(self, **kw):
            return self if "message_key" in kw else seen_query.filter_by(**kw)

        def first(self):
            return None

        def count(self):
            return seen_query.count()

    Receipt.query = Blind()
    try:
        again = receipts_service.sync_mailbox(box, fetcher=lambda b, since: iter(msgs))
    finally:
        Receipt.query = seen_query
    check("a duplicate saved by another read is skipped, not a failure",
          "error" not in again and again.get("new") == 0 and Receipt.query.count() == 3, again)

print("5. The pages and the close")
c = application.test_client()
with c.session_transaction() as sess:
    sess["_user_id"] = str(ids["boss"])
    sess["_fresh"] = True
for url in ("/admin/books/", f"/admin/books/{ids['bbb']}/year/2026", f"/admin/books/{ids['bbb']}/month/2026-10",
            "/admin/books/receipts", f"/admin/books/{ids['ehq']}/year/2026"):
    r = c.get(url)
    body = r.get_data(as_text=True)
    check(f"{url} renders", r.status_code == 200, r.status_code)
    check(f"{url} has no em dash", "\u2014" not in body)
yr = c.get(f"/admin/books/{ids['bbb']}/year/2026").get_data(as_text=True)
check("the single-owner report shows Schedule C line numbers", "(line 17)" in yr)
ehq_yr = c.get(f"/admin/books/{ids['ehq']}/year/2026").get_data(as_text=True)
check("the partnership report does not", "(line " not in ehq_yr)
csv_text = c.get(f"/admin/books/{ids['bbb']}/year/2026.csv").get_data(as_text=True)
check("the CSV carries income, expenses and owner money",
      "Income," in csv_text and "LegalZoom" in csv_text and "Owner put in" in csv_text)
r = c.post(f"/admin/books/{ids['bbb']}/month/2026-10/close")
with application.app_context():
    closed = MonthClose.query.filter_by(business_id=ids["bbb"]).one()
    check("a finished month closes with its figures", closed.expenses_total == round(20 + 12.37 + 99 + 49.99, 2),
          closed.expenses_total)
r = c.post(f"/admin/books/{ids['bbb']}/month/{date.today():%Y-%m}/close", follow_redirects=True)
with application.app_context():
    check("the month still running does not", MonthClose.query.count() == 1)
    db.session.add(Expense(amount=5.0, description="Late charge", category="misc",
                           date=date(2026, 10, 20), business_id=ids["bbb"]))
    db.session.commit()
page = c.get(f"/admin/books/{ids['bbb']}/month/2026-10").get_data(as_text=True)
check("a change after closing shows as a difference", "Changed since it closed" in page)
r = c.post("/admin/books/mailboxes", data={"address": "", "password": ""}, follow_redirects=True)
check("a mailbox needs its address and password", "Give the address" in r.get_data(as_text=True))

# Connect reads in the background: the page answers at once, and a second
# press while the read runs starts nothing.
import threading  # noqa: E402
import time  # noqa: E402
gate = threading.Event()
real_fetch = receipts_service.fetch


def slow_fetch(mailbox, since):
    gate.wait(5)
    return iter([mail("Your receipt from Hetzner", "Total $7.00", sender="Hetzner <billing@hetzner.com>",
                      mid="<hetzner-1@test>")])


receipts_service.fetch = slow_fetch
started = time.time()
r = c.post("/admin/books/mailboxes", data={"address": "mbean@entertainhq.com", "password": "abcd efgh",
                                           "business_id": ids["ehq"]}, follow_redirects=True)
quick = time.time() - started
body = r.get_data(as_text=True)
check("Connect answers before the read finishes", quick < 2 and "Reading mbean@entertainhq.com" in body, quick)
check("the page says it is reading", "Reading now" in body)
with application.app_context():
    second = ReceiptMailbox.query.filter_by(address="mbean@entertainhq.com").one()
    check("the app password is kept without its spaces", second.password == "abcdefgh")
    second_id = second.id
r = c.post(f"/admin/books/mailboxes/{second_id}/sync", follow_redirects=True)
check("a second press while it reads starts nothing", "Already reading" in r.get_data(as_text=True))
gate.set()
for _ in range(50):
    if not receipts_service.reading(second_id):
        break
    time.sleep(0.1)
receipts_service.fetch = real_fetch
with application.app_context():
    got = db.session.get(ReceiptMailbox, second_id)
    check("and the read finishes on its own", got.last_ok and "1 new receipt" in (got.last_note or ""),
          got.last_note)

print("6. EntertainHQ reads its own books")
anon = application.test_client()


def signed(payload, slug="entertainhq", secret="s3cret"):
    body = hub.canonical(payload)
    ts, sig = hub.sign(secret, body)
    return anon.post("/api/hub/books", data=body, content_type="application/json",
                     headers={hub.ORIGIN_HEADER: slug, hub.TIMESTAMP_HEADER: ts,
                              hub.SIGNATURE_HEADER: sig})


r = signed({"year": 2026, "sales": [{"date": "2026-10-20", "total": 250.0, "ref": "Booking 1"}]})
data = r.get_json() or {}
check("signed, it answers", r.status_code == 200, r.status_code)
check("its own sales are its income", data.get("income_total") == 250.0, data.get("income_total"))
check("its expenses are its own and nobody else's",
      data.get("expense_total") == 42.48 and len(data.get("expenses", [])) == 1, data.get("expense_total"))
check("each partner is listed with a share",
      sorted(o["name"] for o in data.get("owners", [])) == ["Kenali Kendrick", "Michael Bean", "Third Member"])
check("a stranger is refused", signed({}, slug="nobody").status_code == 401)
check("a wrong secret is refused", signed({}, secret="nope").status_code == 401)

print()
print("FAILED: " + ", ".join(FAIL) if FAIL else "all passed")
sys.exit(1 if FAIL else 0)
