# -*- coding: utf-8 -*-
"""Every business owned, and the sales tax return each one files.

The board became the command center over more than one business on
2026-10-30, the day Built by Bean filed its first two returns. Those two
returns are the fixture: whatever this file proves, it proves against what
WebFile actually said.

What is proved:

  1. A period's code, label and due date are WebFile's: 262 is Apr-Jun 2026,
     due Jul 20; a due date on a weekend moves to Monday.
  2. The returns owed run from the first taxable sale through today.
  3. Late is 5% then 10% plus $50; on time keeps 0.5%.
  4. Sales split by the location trading that day, in whole dollars, and
     reproduce both filed returns to the cent: $339.90, then $165.00 and
     $491.70. A sale no location covers is shown, never dropped.
  5. The pages draw for the CEO and refuse everyone else; a return is
     recorded with its confirmation, which comes back out; the board's own
     record prints; the WebFile steps show what to type.
  6. The hub: a business's app reads its returns and gets figures for the
     sales it sends, records a return, puts and gets a confirmation; a bad
     signature, a stranger and another business's file are all refused.
  7. A business whose sales come from its app is asked for them.

Run: python tools/test_business_returns.py
"""
import base64
import json
import os
import pathlib
import sys
import tempfile
from datetime import date, datetime
from types import SimpleNamespace as NS

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
TMP = tempfile.mkdtemp(prefix="board-returns-")
os.environ["DATABASE_URL"] = "sqlite:///" + (pathlib.Path(TMP) / "board.db").as_posix()
os.environ["UPLOAD_FOLDER"] = TMP
os.environ.setdefault("SECRET_KEY", "test")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from app import create_app  # noqa: E402
from models import (db, Business, BusinessLocation, Client, Invoice, SalesTaxFiling,  # noqa: E402
                    SalesTaxFilingFile, User)
import hub  # noqa: E402
import sales_tax  # noqa: E402
import pm.business_routes as br  # noqa: E402

application = create_app()
application.config["WTF_CSRF_ENABLED"] = False
br.import_invoices_from_stripe = lambda ttl=300: (0, 0, [])
FAIL = []


def check(name, cond, detail=""):
    print(("  ok   " if cond else "  FAIL ") + name
          + (("  -> " + str(detail)[:300]) if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


print("PERIODS:")
check("Apr-Jun 2026 is 262", sales_tax.period_code(2026, 2) == "262")
check("Oct-Dec 2026 is 264", sales_tax.period_code(2026, 4) == "264")
check("its label", sales_tax.period_label(2026, 3) == "Jul–Sep 2026", sales_tax.period_label(2026, 3))
check("Q2 due Jul 20", sales_tax.due_date(2026, 2) == date(2026, 7, 20))
check("Q4 due the next January", sales_tax.due_date(2026, 4) == date(2027, 1, 20))
check("a Sunday 20th moves to Monday", sales_tax.due_date(2025, 2) == date(2025, 7, 21),
      sales_tax.due_date(2025, 2))
# EntertainHQ's calendar names these two; the board must name the same days.
check("Q4 2029 rolls past MLK Day to Tue Jan 22", sales_tax.due_date(2029, 4) == date(2030, 1, 22),
      sales_tax.due_date(2029, 4))
check("Q4 2030 rolls off MLK Day to Tue Jan 21", sales_tax.due_date(2030, 4) == date(2031, 1, 21),
      sales_tax.due_date(2030, 4))
check("Q1 2027 is Tue Apr 20", sales_tax.due_date(2027, 1) == date(2027, 4, 20))
owed = sales_tax.periods_owed(date(2026, 4, 9), date(2026, 10, 30))
check("owed from the first sale through today", owed == [(2026, 2), (2026, 3), (2026, 4)], owed)
check("nothing owed before a first sale", sales_tax.periods_owed(None, date(2026, 10, 30)) == [])
check("a running quarter is open", sales_tax.status_of(2026, 4, None, date(2026, 10, 30)) == "open")
check("ended, not yet due", sales_tax.status_of(2026, 3, None, date(2026, 10, 5)) == "due")
check("past due is late", sales_tax.status_of(2026, 3, None, date(2026, 10, 30)) == "late")
check("a filing makes it filed", sales_tax.status_of(2026, 2, object(), date(2026, 10, 30)) == "filed")


print("\nLATE AND ON TIME:")
c = sales_tax.charges_if_paid_on(339.90, date(2026, 7, 20), date(2026, 10, 30))
check("102 days late is 10% and $50", c["late"] and c["penalty_rate"] == 10 and c["penalty"] == 33.99
      and c["late_fee"] == 50.0, c)
check("interest from the 61st day", c["interest_from"] == date(2026, 9, 19), c["interest_from"])
c = sales_tax.charges_if_paid_on(656.70, date(2026, 10, 20), date(2026, 10, 30))
check("10 days late is 5%, $32.84 as WebFile said", c["penalty_rate"] == 5 and c["penalty"] == 32.84, c)
c = sales_tax.charges_if_paid_on(105.60, date(2027, 1, 20), date(2027, 1, 15))
check("on time keeps 0.5%", not c["late"] and c["discount"] == 0.53, c)


print("\nTHE TWO RETURNS FILED ON 2026-10-30:")
FW = NS(id=1, webfile_number="00002", label="Fort Worth", local_rate=2.0,
        opened_on=date(2026, 4, 9), closed_on=date(2026, 9, 17))
PA = NS(id=2, webfile_number="00001", label="Paris", local_rate=2.0,
        opened_on=date(2026, 9, 18), closed_on=None)
BBB = NS(locations=[FW, PA])
BBB.location_on = lambda day: Business.location_on(BBB, day)


def sale(day, total, ref=""):
    return {"date": day, "total": total, "taxable": None, "ref": ref}


q2 = [sale(date(2026, 4, 9), 2500.0), sale(date(2026, 5, 1), 1650.0), sale(date(2026, 6, 15), 1000.0)]
r = sales_tax.build_return(BBB.location_on, q2, 80.0, year=2026, quarter=2)
check("Apr-Jun is one line, Fort Worth", [l["number"] for l in r["lines"]] == ["00002"], r["lines"])
check("5,150 and 4,120", (r["total_sales"], r["taxable_sales"]) == (5150, 4120))
check("$339.90: 257.50 state, 82.40 local", (r["tax"], r["state_tax"], r["local_tax"]) == (339.90, 257.50, 82.40), r)

q3 = [sale(date(2026, 7, 1), 2500.0), sale(date(2026, 8, 3), 4900.0), sale(date(2026, 9, 1), 50.0),
      sale(date(2026, 9, 17), 0.0), sale(date(2026, 9, 30), 2500.0)]
r = sales_tax.build_return(BBB.location_on, q3, 80.0, year=2026, quarter=3)
lines = {l["number"]: l for l in r["lines"]}
check("Jul-Sep splits at the move", sorted(lines) == ["00001", "00002"], lines.keys())
check("Paris 2,500 / 2,000 is $165.00", (lines["00001"]["total_sales"], lines["00001"]["taxable_sales"],
                                         lines["00001"]["tax"]) == (2500, 2000, 165.0), lines["00001"])
check("Fort Worth 7,450 / 5,960 is $491.70", (lines["00002"]["total_sales"], lines["00002"]["taxable_sales"],
                                              lines["00002"]["tax"]) == (7450, 5960, 491.70), lines["00002"])
check("the return is $656.70", r["tax"] == 656.70, r["tax"])
check("lines in WebFile's order, 00001 first", [l["number"] for l in r["lines"]] == ["00001", "00002"])

r = sales_tax.build_return(BBB.location_on, [sale(date(2026, 4, 1), 100.0)], 80.0, year=2026, quarter=2)
check("a sale before any location opened is unplaced, not dropped",
      len(r["unplaced"]) == 1 and not r["lines"], r)
r = sales_tax.build_return(BBB.location_on, [{"date": date(2026, 9, 20), "total": 100.0, "taxable": 100.0}],
                           80.0, year=2026, quarter=3)
check("an app's own taxable figure is used as given", r["taxable_sales"] == 100, r)
r = sales_tax.build_return(BBB.location_on, [sale(date(2026, 10, 2), 0.5)], 80.0, year=2026, quarter=4)
check("whole dollars round half up", r["total_sales"] == 1 and r["taxable_sales"] == 0, r)


print("\nTHE PAGES:")
with application.app_context():
    db.create_all()
    boss = User(username="mb", email="mb@example.test", first_name="Michael", role="ceo")
    boss.set_password("x")
    member = User(username="hb", email="hb@example.test", first_name="Hannah", role="member")
    member.set_password("x")
    k = Client(name="Kenali Kendrick", email="k@example.test")
    db.session.add_all([boss, member, k])
    db.session.flush()
    bbb = Business(name="Built by Bean LLC", short_name="Built by Bean", slug="built-by-bean",
                   texas_taxpayer_number="32093304155", sales_tax_first_sale=date(2026, 4, 9),
                   sales_tax_webfile="RT000000", sales_source="board", taxable_share=80.0)
    ehq = Business(name="EntertainHQ LLC", short_name="EntertainHQ", slug="entertainhq",
                   texas_taxpayer_number="32108463343", sales_tax_first_sale=date(2026, 7, 1),
                   sales_source="hub", hub_slug="entertainhq", hub_secret="s3cret",
                   hub_base_url="https://ehq.example.test", taxable_share=80.0)
    other = Business(name="Other LLC", slug="other", hub_slug="other", hub_secret="other-secret")
    db.session.add_all([bbb, ehq, other])
    db.session.flush()
    db.session.add_all([
        BusinessLocation(business_id=bbb.id, webfile_number="00002", label="Fort Worth",
                         local_rate=2.0, opened_on=date(2026, 4, 9), closed_on=date(2026, 9, 17)),
        BusinessLocation(business_id=bbb.id, webfile_number="00001", label="Paris",
                         local_rate=2.0, opened_on=date(2026, 9, 18)),
        BusinessLocation(business_id=ehq.id, webfile_number="00001", label="Paris",
                         local_rate=2.0, opened_on=date(2026, 7, 1)),
    ])
    for n, (day, total) in enumerate([(date(2026, 4, 9), 2500.0), (date(2026, 5, 1), 1650.0),
                                      (date(2026, 6, 15), 1000.0), (date(2026, 7, 1), 2500.0),
                                      (date(2026, 8, 3), 4900.0), (date(2026, 9, 1), 50.0),
                                      (date(2026, 9, 30), 2500.0)], start=1):
        db.session.add(Invoice(client_id=k.id, status="paid", total=total, tax=0.0, subtotal=total,
                               amount_paid=total, issued_on=day, invoice_number=f"BBB-{n}",
                               stripe_invoice_id=f"in_{n}"))
    # Tax billed back is not a sale and must not move a return.
    db.session.add(Invoice(client_id=k.id, status="paid", total=699.60, tax=0.0, subtotal=699.60,
                           amount_paid=699.60, issued_on=date(2026, 9, 20), sales_tax_catchup=True,
                           stripe_invoice_id="in_catch"))
    db.session.commit()
    boss_id, member_id, bbb_id, ehq_id, other_id = boss.id, member.id, bbb.id, ehq.id, other.id

c = application.test_client()
with c.session_transaction() as sess:
    sess["_user_id"] = str(member_id)
resp = c.get("/admin/businesses")
check("a member is turned away from Businesses", resp.status_code == 302, resp.status_code)
resp = c.get("/admin/taxes/sales/returns")
check("and from Returns", resp.status_code == 302, resp.status_code)

with c.session_transaction() as sess:
    sess["_user_id"] = str(boss_id)

hub_calls = []


def fake_fetch(base_url, path, payload, *, secret, origin_slug, timeout=20):
    hub_calls.append((base_url, path, payload, origin_slug))
    return {"sales": [{"date": "2026-08-14", "total": 300.0, "taxable": 240.0, "ref": "ehq-1"},
                      {"date": "2026-08-20", "total": "bad"}]}


br.hub.fetch = fake_fetch

resp = c.get("/admin/businesses")
body = resp.get_data(as_text=True)
check("Businesses draws", resp.status_code == 200, resp.status_code)
check("with both taxpayer numbers", "32093304155" in body and "32108463343" in body)
check("and says what is not on file", "Not on file" in body)
check("the list does not call out to an app", not hub_calls, hub_calls)

resp = c.get("/admin/taxes/sales/returns")
body = resp.get_data(as_text=True)
check("Returns draws", resp.status_code == 200, resp.status_code)
check("Built by Bean's Apr-Jun shows $339.90", "$339.90" in body)
check("Jul-Sep shows $656.70", "$656.70" in body)

resp = c.get("/admin/taxes/sales/returns/built-by-bean/2026/q3")
body = resp.get_data(as_text=True)
check("a return draws", resp.status_code == 200, resp.status_code)
check("with the period code to pick", ">263<" in body)
check("the numbers to type, per location", all(x in body for x in (">2500<", ">2000<", ">7450<", ">5960<")))
check("the sales behind them, without the billed-back tax", "BBB-7" in body and "699.60" not in body)
check("the payment step names the electronic check", "Electronic Check" in body)

resp = c.get("/admin/taxes/sales/returns/entertainhq/2026/q3")
body = resp.get_data(as_text=True)
check("an app's business is asked for its sales", hub_calls and hub_calls[-1][1] == "/api/hub/tax/sales"
      and hub_calls[-1][3] == "entertainhq", hub_calls)
check("and a bad row in its answer is skipped", ">300<" in body and ">240<" in body)
with application.app_context():
    check("the ask is stamped", db.session.get(Business, ehq_id).hub_pull_note == "1 sale",
          db.session.get(Business, ehq_id).hub_pull_note)

pdf_bytes = b"%PDF-1.4 confirmation"
resp = c.post("/admin/taxes/sales/returns/built-by-bean/2026/q3/record", data={
    "reference_number": "30326098451", "payment_reference": "3029644780",
    "trace_number": "902AA0027035223", "payment_method": "credit card",
    "total_sales": "9,950", "taxable_sales": "7,960", "tax_due": "656.70", "penalty": "32.84",
    "late_filing_penalty": "50", "interest": "", "discount": "", "processing_fee": "16.89",
    "amount_paid": "", "filed_on": "2026-10-30", "filed_time": "11:25",
    "loc_number": ["00001", "00002"], "loc_label": ["Paris", "Fort Worth"],
    "loc_total": ["2500", "7450"], "loc_taxable": ["2000", "5960"],
    "loc_state": ["125", "372.5"], "loc_local": ["40", "119.2"],
    "confirmation": [(__import__("io").BytesIO(pdf_bytes), "Q3 confirmation.pdf"),
                     (__import__("io").BytesIO(b"MZ"), "virus.exe")],
}, content_type="multipart/form-data")
check("recording redirects back", resp.status_code == 302, resp.status_code)
with application.app_context():
    f = SalesTaxFiling.query.filter_by(business_id=bbb_id, year=2026, quarter=3).one()
    check("paid to the state is worked out when left blank", f.amount_paid == 739.54, f.amount_paid)
    check("and the card fee on top", f.total_charged == 756.43, f.total_charged)
    check("what was typed per location is kept", [l["number"] for l in f.location_rows] == ["00001", "00002"])
    check("filed at the time WebFile printed", f.filed_at == datetime(2026, 10, 30, 11, 25), f.filed_at)
    check("the PDF is kept and the .exe is not", [x.original_name for x in f.files] == ["Q3 confirmation.pdf"],
          [x.original_name for x in f.files])
    file_id, filing_id = f.files[0].id, f.id

resp = c.get(f"/admin/taxes/sales/files/{file_id}")
check("the confirmation comes back out", resp.status_code == 200 and resp.data == pdf_bytes, resp.status_code)
resp = c.get(f"/admin/taxes/sales/filings/{filing_id}/record.pdf")
check("the board's own record prints", resp.status_code == 200 and resp.data[:4] == b"%PDF", resp.data[:8])
resp = c.get("/admin/taxes/sales/returns/built-by-bean/2026/q3")
body = resp.get_data(as_text=True)
check("a filed return shows what was paid", "$739.54" in body and "30326098451" in body)
check("and no longer shows the WebFile steps", "File Original Return" not in body)

resp = c.post("/admin/taxes/sales/returns/built-by-bean/2026/q2/record",
              data={"reference_number": "", "tax_due": "339.90"})
with application.app_context():
    check("no reference number, no record",
          SalesTaxFiling.query.filter_by(business_id=bbb_id, quarter=2).first() is None)

resp = c.get("/admin/taxes/sales/returns/built-by-bean/2026/q4")
body = resp.get_data(as_text=True)
check("a running quarter draws", resp.status_code == 200)
check("and has nothing to file yet", "File Original Return" not in body)

for path in ("/admin/businesses/new", f"/admin/businesses/{bbb_id}/edit", "/admin/taxes/sales/guide"):
    resp = c.get(path)
    check(f"{path} draws", resp.status_code == 200, resp.status_code)

resp = c.post("/admin/businesses/new", data={
    "name": "Next Thing LLC", "texas_taxpayer_number": "321-0000-0000", "sales_tax_webfile": "rt 123 456",
    "sales_tax_frequency": "quarterly", "taxable_share": "80", "sales_source": "manual", "is_active": "1"})
with application.app_context():
    nb = Business.query.filter_by(name="Next Thing LLC").one()
    check("a new business gets a slug from its name", nb.slug == "next-thing", nb.slug)
    check("numbers are cleaned as typed", nb.texas_taxpayer_number == "32100000000"
          and nb.sales_tax_webfile == "RT123456", (nb.texas_taxpayer_number, nb.sales_tax_webfile))
    nb_id = nb.id
resp = c.post(f"/admin/businesses/{nb_id}/locations", data={
    "label": "Paris", "webfile_number": "00001", "local_rate": "2", "opened_on": "2026-11-01",
    "closed_on": "2026-10-01"})
with application.app_context():
    check("a location cannot close before it opens", not BusinessLocation.query.filter_by(business_id=nb_id).count())


print("\nTHE HUB:")


def signed(path, payload, slug="entertainhq", secret="s3cret"):
    body = hub.canonical(payload)
    ts, sig = hub.sign(secret, body)
    return c.post(path, data=body, content_type="application/json",
                  headers={hub.ORIGIN_HEADER: slug, hub.TIMESTAMP_HEADER: ts, hub.SIGNATURE_HEADER: sig})


c2 = application.test_client()  # no session: the hub is not signed in
resp = c2.post("/api/hub/tax/returns", data=b"{}", content_type="application/json",
               headers={hub.ORIGIN_HEADER: "entertainhq", hub.TIMESTAMP_HEADER: "1", hub.SIGNATURE_HEADER: "x"})
check("a bad signature is refused", resp.status_code == 401, resp.status_code)
resp = signed("/api/hub/tax/returns", {}, slug="nobody")
check("a stranger gets the same answer", resp.status_code == 401, resp.status_code)

c = c2
resp = signed("/api/hub/tax/returns", {"sales": [{"date": "2026-08-14", "total": 300, "taxable": 240}]})
data = resp.get_json() or {}
check("its returns come back", resp.status_code == 200 and data.get("periods"), resp.status_code)
q3 = next((p for p in data.get("periods", []) if p["code"] == "263"), {})
check("with figures for the sales it sent", (q3.get("figures") or {}).get("taxable_sales") == 240, q3)
check("and never a WebFile number", "webfile" not in json.dumps(data).lower().replace("webfile_number", ""))

resp = signed("/api/hub/tax/filings", {"year": 2026, "quarter": 3, "reference_number": "999",
                                       "tax_due": 19.8, "payment_method": "electronic check",
                                       "filed_at": "2026-10-20T09:00:00", "recorded_by": "kenali"})
check("it records a return", resp.status_code == 200, resp.get_data(as_text=True))
resp = signed("/api/hub/tax/files/put", {"year": 2026, "quarter": 3, "name": "ehq.pdf",
                                         "data": base64.b64encode(b"%PDF ehq").decode()})
fid = (resp.get_json() or {}).get("file", {}).get("id")
check("it keeps a confirmation", resp.status_code == 200 and fid, resp.get_data(as_text=True))
resp = signed("/api/hub/tax/files/get", {"id": fid})
check("and gets it back", base64.b64decode((resp.get_json() or {}).get("data", "")) == b"%PDF ehq")
resp = signed("/api/hub/tax/files/get", {"id": file_id})
check("but not Built by Bean's", resp.status_code == 404, resp.status_code)
resp = signed("/api/hub/tax/files/get", {"id": fid}, slug="other", secret="other-secret")
check("nor does another business get EntertainHQ's", resp.status_code == 404, resp.status_code)
resp = signed("/api/hub/tax/files/put", {"year": 2026, "quarter": 2, "name": "x.pdf", "data": "JVBERg=="})
check("no confirmation before the return is recorded", resp.status_code == 404, resp.status_code)
with application.app_context():
    f = SalesTaxFiling.query.filter_by(business_id=ehq_id, year=2026, quarter=3).one()
    check("the record says who sent it", f.recorded_by == "kenali via entertainhq", f.recorded_by)

resp = signed("/api/hub/tax/filings/undo", {"year": 2026, "quarter": 3})
check("its Undo will not drop a return with a confirmation kept", resp.status_code == 409, resp.status_code)
resp = signed("/api/hub/tax/filings", {"year": 2026, "quarter": 2, "reference_number": "777", "tax_due": 1})
resp = signed("/api/hub/tax/filings/undo", {"year": 2026, "quarter": 2})
check("but takes back one it recorded itself", (resp.get_json() or {}).get("removed") is True,
      resp.get_data(as_text=True))
with application.app_context():
    db.session.add(SalesTaxFiling(business_id=ehq_id, year=2026, quarter=1, reference_number="1",
                                  recorded_by="mb"))
    db.session.commit()
resp = signed("/api/hub/tax/filings/undo", {"year": 2026, "quarter": 1})
check("and never one recorded on the board", resp.status_code == 409, resp.status_code)

print("\nall passed" if not FAIL else f"\n{len(FAIL)} FAILED: " + "; ".join(FAIL))
sys.exit(1 if FAIL else 0)
